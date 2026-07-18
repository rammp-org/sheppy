import asyncio
import os
import sys

import pytest

from sheppy.daemon.client import DaemonClient, DaemonError
from sheppy.daemon.config import socket_path

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]


def spec(node, argv=SLEEP):
    return {"node": node, "alt_id": "a", "argv": argv, "params": {}}


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
