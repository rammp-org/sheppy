import asyncio
import json
import os
import sys

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config, socket_path
from sheppy.daemon.protocol import Decoder, encode
from sheppy.daemon.server import Server

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]
CRASH = [sys.executable, "-c", "raise SystemExit(9)"]


def spec(node, argv=SLEEP):
    return {"node": node, "alt_id": "a", "argv": argv, "params": {}}


class Wire:
    """Minimal test client: request/response by id + captured events."""

    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.decoder = Decoder()
        self.events: list = []
        self.replies: dict = {}
        self._next_id = 0

    @classmethod
    async def connect(cls, home):
        reader, writer = await asyncio.open_unix_connection(socket_path(home))
        wire = cls(reader, writer)
        hello = await wire._read_one()
        assert hello["event"] == "hello" and hello["protocol"] == 1
        return wire

    async def _read_one(self):
        while True:
            msgs = self.decoder.feed(await self.reader.read(65536))
            if msgs:
                self._sort(msgs[1:])
                return msgs[0]

    def _sort(self, msgs):
        for m in msgs:
            if "event" in m:
                self.events.append(m)
            else:
                self.replies[m["id"]] = m

    async def request(self, op, **kw):
        self._next_id += 1
        rid = self._next_id
        self.writer.write(encode({"id": rid, "op": op, **kw}))
        await self.writer.drain()
        while rid not in self.replies:
            msg = await self._read_one()
            self._sort([msg])
        return self.replies.pop(rid)

    async def wait_event(self, pred, timeout=5.0):
        async def poll():
            while True:
                for e in self.events:
                    if pred(e):
                        return e
                self._sort([await self._read_one()])
        return await asyncio.wait_for(poll(), timeout)


async def make_server(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    cfg = Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"),
                 launch_grace=0.1, stop_grace=0.3, kill_grace=0.3,
                 usage_interval=0.1)
    server = Server(cfg)
    await server.start()
    return server


async def test_launch_status_stop_roundtrip(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    wire = await Wire.connect(str(tmp_path))
    assert (await wire.request("launch", spec=spec("camera")))["ok"]
    reply = await wire.request("status")
    assert reply["nodes"]["camera"]["state"] in (pr.LAUNCHING, pr.RUNNING)
    assert (await wire.request("stop", node="camera"))["ok"]
    reply = await wire.request("status")
    assert reply["nodes"]["camera"]["state"] == pr.STOPPED
    await server.close()


async def test_subscriber_sees_crash_event_with_usage_field(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    watcher = await Wire.connect(str(tmp_path))
    assert (await watcher.request("subscribe"))["ok"]
    actor = await Wire.connect(str(tmp_path))
    await actor.request("launch", spec=spec("flaky", CRASH))
    crash = await watcher.wait_event(
        lambda e: e.get("node") == "flaky" and e["state"] == pr.CRASHED)
    assert crash["exit_code"] == 9 and "usage" in crash
    await server.close()


async def test_malformed_unknown_op_unknown_node_never_kill_daemon(
        tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    wire = await Wire.connect(str(tmp_path))
    wire.writer.write(b"{broken\n")
    await wire.writer.drain()
    err = await wire._read_one()
    assert err["ok"] is False
    reply = await wire.request("frobnicate")
    assert reply["ok"] is False and "unknown op" in reply["error"]
    reply = await wire.request("stop", node="ghost")
    assert reply["ok"] is False and "ghost" in reply["error"]
    assert (await wire.request("status"))["ok"]      # still alive
    await server.close()


async def test_non_dict_json_line_never_kill_daemon(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    wire = await Wire.connect(str(tmp_path))
    wire.writer.write(b"5\n")
    await wire.writer.drain()
    err = await wire._read_one()
    assert err["ok"] is False
    assert (await wire.request("status"))["ok"]      # still alive
    await server.close()


async def test_launch_rejects_bad_spec(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    wire = await Wire.connect(str(tmp_path))
    reply = await wire.request("launch", spec={"node": "x"})   # no argv
    assert reply["ok"] is False
    await server.close()


async def test_logs_op_returns_tail(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    wire = await Wire.connect(str(tmp_path))
    await wire.request("launch", spec=spec(
        "talker", [sys.executable, "-c",
                   "print('hi there'); import time; time.sleep(30)"]))
    await asyncio.sleep(0.3)
    reply = await wire.request("logs", node="talker", n=10)
    assert "hi there" in reply["lines"]
    await wire.request("stop", node="talker")
    await server.close()


async def test_shutdown_leaves_children_running(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    wire = await Wire.connect(str(tmp_path))
    await wire.request("launch", spec=spec("camera"))
    pid = (await wire.request("status"))["nodes"]["camera"]["pid"]
    assert (await wire.request("shutdown"))["ok"]
    await asyncio.wait_for(server.wait_shutdown(), 2)
    await asyncio.wait_for(server.close(), 5)
    os.kill(pid, 0)                       # child survived the daemon
    import signal
    os.killpg(pid, signal.SIGKILL)        # cleanup


async def test_shutdown_waits_for_inflight_stop_reply(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    slow = [sys.executable, "-c",
            "import signal, time\n"
            "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "time.sleep(30)\n"]
    a = await Wire.connect(str(tmp_path))
    await a.request("launch", spec=spec("stubborn", slow))
    await asyncio.sleep(0.15)              # past launch grace
    stop_reply = asyncio.ensure_future(a.request("stop", node="stubborn"))
    await asyncio.sleep(0.05)              # stop escalation now in flight
    b = await Wire.connect(str(tmp_path))
    await b.request("shutdown")
    await asyncio.wait_for(server.wait_shutdown(), 2)
    await asyncio.wait_for(server.close(), 5)
    reply = await asyncio.wait_for(stop_reply, 5)
    assert reply["ok"] is True             # in-flight reply was delivered


async def test_socket_has_owner_only_perms(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    mode = os.stat(socket_path(str(tmp_path))).st_mode & 0o777
    assert mode == 0o600
    await server.close()
