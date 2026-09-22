import asyncio
import os
import sys

import pytest

from sheppy import __version__
from sheppy.daemon.client import DaemonClient, DaemonError, spawn_daemon
from sheppy.daemon.config import socket_path
from sheppy.daemon.protocol import encode

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]


def spec(node, argv=SLEEP):
    return {"node": node, "alt_id": "a", "params": {},
            "descriptor": {"supervise": "inherit", "start": list(argv)}}


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    c = DaemonClient(str(tmp_path))
    assert await c.connect(spawn=True) is True          # auto-spawns sheppyd
    yield c
    # teardown: stop everything, then stop the daemon itself
    if not c.connected:
        c = DaemonClient(str(tmp_path))
        if not await c.connect(spawn=False):
            return
    nodes = (await c.request("status"))["nodes"]
    for node in nodes:
        await c.request("stop", node=node)
    await c.request("shutdown")
    await c.close()


async def test_autospawn_creates_daemon_and_socket(client, tmp_path):
    assert os.path.exists(socket_path(str(tmp_path)))
    assert (await client.request("status"))["ok"]


async def test_second_client_connects_without_spawning(client, tmp_path):
    other = DaemonClient(str(tmp_path))
    assert await other.connect(spawn=False) is True
    assert (await other.request("status"))["ok"]
    await other.close()


async def test_launch_and_stop_through_client(client):
    assert (await client.request("launch", spec=spec("camera")))["ok"]
    nodes = (await client.request("status"))["nodes"]
    assert nodes["camera"]["state"] in ("launching", "running")
    assert (await client.request("stop", node="camera"))["ok"]


async def test_events_reach_callback(client):
    events: list = []
    client.on_event(events.append)
    await client.subscribe()
    await client.request(
        "launch", spec=spec("flaky", [sys.executable, "-c",
                                      "raise SystemExit(5)"]))
    async def crashed():
        while not any(e.get("node") == "flaky" and e["state"] == "crashed"
                      for e in events):
            await asyncio.sleep(0.02)
    await asyncio.wait_for(crashed(), 5)


async def test_close_fails_inflight_requests_instead_of_hanging(client):
    # Issue a request and close immediately, racing the reply. The reply may
    # occasionally win the race and resolve ok; the non-negotiable behavior
    # is that the future NEVER hangs — close() must drain pending futures
    # with DaemonError on every disconnect path (cancel, EOF, reset).
    pending = asyncio.ensure_future(client.request("status"))
    await asyncio.sleep(0)      # let the request get written and registered
    await client.close()
    try:
        reply = await asyncio.wait_for(pending, 5)
        assert reply["ok"]
    except DaemonError:
        pass


async def test_connect_without_spawn_returns_false(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    c = DaemonClient(str(tmp_path))
    assert await c.connect(spawn=False) is False
    with pytest.raises(DaemonError):
        await c.request("status")


async def test_cancelled_request_does_not_kill_connection(client):
    """A caller that cancels mid-flight (e.g. a Textual exclusive worker
    replaced by its successor) must not break the pump when the daemon's
    late reply arrives — other in-flight requests used to fail with
    'sheppyd connection lost' while the socket was perfectly healthy."""
    slow = {"node": "slow", "alt_id": "a", "params": {}, "descriptor": {
        "supervise": "detached", "name": "slow",
        "start": ["sleep", "1.0"],        # its reply arrives a second late
        "poll": ["true"]}}
    doomed = asyncio.ensure_future(client.request("launch", spec=slow))
    await asyncio.sleep(0.1)
    doomed.cancel()
    with pytest.raises(asyncio.CancelledError):
        await doomed
    await asyncio.sleep(1.2)
    # the late reply for `doomed` arrived above; the pump must survive it
    assert (await client.request("status"))["ok"]
    assert client.connected


async def test_spawn_daemon_sends_stderr_to_daemon_log(tmp_path, monkeypatch):
    # A daemon that dies before it can log anything must still leave a
    # trace (#88): its stderr is appended to logs/sheppyd.log.
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    fake = tmp_path / "fake-python"
    fake.write_text("#!/bin/sh\necho 'boom from stderr' >&2\n")
    fake.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(fake))
    spawn_daemon()
    log = tmp_path / "logs" / "sheppyd.log"

    async def written():
        while not (log.exists() and "boom from stderr" in log.read_text()):
            await asyncio.sleep(0.02)
    await asyncio.wait_for(written(), 5)


async def test_spawn_daemon_creates_home_owner_only(tmp_path, monkeypatch):
    # spawn_daemon() now creates the home (for the log dir) before sheppyd
    # does; the state file with node specs lives there, so 0o700 like
    # sheppyd's own makedirs, not the umask default.
    home = tmp_path / "home"
    monkeypatch.setenv("SHEPPY_HOME", str(home))
    fake = tmp_path / "fake-python"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(fake))
    spawn_daemon()
    assert os.stat(home).st_mode & 0o777 == 0o700


async def test_daemon_exit_reaches_callback_as_disconnected(client):
    # #108: the pump learns of the socket closing first; without telling
    # its callbacks, the TUI kept showing the last-known state.
    events: list = []
    client.on_event(events.append)
    await client.request("shutdown")

    async def gone():
        while {"event": "disconnected"} not in events:
            await asyncio.sleep(0.02)
    await asyncio.wait_for(gone(), 5)
    assert client.connected is False


async def test_connect_records_daemon_version(client):
    assert client.daemon_version == __version__
    assert client.version_mismatch() is None


async def test_stale_daemon_version_is_reported(tmp_path, monkeypatch):
    """A daemon left running across an upgrade still says its old
    version in the hello; the client surfaces it (#58)."""
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))

    async def old_daemon(reader, writer):
        writer.write(encode({"event": "hello", "sheppyd": "0.1",
                             "protocol": 2}))
        await writer.drain()
        await reader.read()

    server = await asyncio.start_unix_server(
        old_daemon, socket_path(str(tmp_path)))
    c = DaemonClient(str(tmp_path))
    try:
        assert await c.connect(spawn=False) is True
        assert c.daemon_version == "0.1"
        assert c.version_mismatch() == (
            f"sheppyd 0.1 is not this client's {__version__}; "
            "run 'sheppy daemon stop' to restart it")
    finally:
        await c.close()
        # No wait_closed(): on CPython 3.12 it never returns once the last
        # connection has already gone (gh-109538 lineage), and 3.13 fixed it.
        server.close()
