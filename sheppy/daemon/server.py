"""sheppyd's socket front-end: NDJSON request dispatch + event push.
stdlib only. A bad request can never take the daemon down."""
import asyncio
import os

from sheppy.daemon import usage as usage_mod
from sheppy.daemon.config import Config, socket_path
from sheppy.daemon.protocol import Decoder, encode
from sheppy.daemon.table import ProcessTable

VERSION = "0.1"


def _validate_descriptor(node, d) -> "str | None":
    if not node:
        return "spec requires 'node'"
    if not isinstance(d, dict):
        return "spec requires a 'descriptor'"
    if d.get("supervise") not in ("inherit", "detached"):
        return f"descriptor.supervise invalid: {d.get('supervise')!r}"
    start = d.get("start")
    if not isinstance(start, list) or not start:
        return "descriptor needs a non-empty 'start'"
    if d.get("supervise") == "detached":
        if not d.get("name"):
            return "detached descriptor needs 'name'"
        if bool(d.get("watch")) == bool(d.get("poll")):
            return "detached descriptor needs exactly one of 'watch'/'poll'"
    return None


class Server:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self.table = ProcessTable(cfg, on_event=self._broadcast_status)
        self._subscribers: set = set()
        self._usage: dict = {}
        self._usage_prev: dict = {}
        self._usage_task: "asyncio.Task | None" = None
        self._server = None
        self._shutdown = asyncio.Event()
        self._connections: set = set()
        self._inflight = 0

    # ---- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        path = socket_path(self._cfg.home)
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        if os.path.exists(path):
            os.unlink(path)               # stale — the flock is the authority
        self._server = await asyncio.start_unix_server(self._client, path)
        os.chmod(path, 0o600)

    async def wait_shutdown(self) -> None:
        await self._shutdown.wait()

    async def close(self) -> None:
        if self._usage_task:
            self._usage_task.cancel()
        if self._server:
            self._server.close()          # stop accepting new connections
        # Let in-flight requests finish and their replies flush; the bound
        # covers the longest legitimate op, a full stop escalation.
        deadline = (asyncio.get_running_loop().time()
                    + self._cfg.stop_grace + self._cfg.kill_grace + 1.0)
        while self._inflight and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
        # Server.wait_closed() (pre-3.13) blocks until every accepted
        # connection's handler returns, so nudge idle clients closed first.
        for writer in list(self._connections):
            writer.close()
        if self._server:
            await self._server.wait_closed()

    # ---- connections -------------------------------------------------------
    async def _client(self, reader, writer) -> None:
        self._connections.add(writer)
        writer.write(encode(
            {"event": "hello", "sheppyd": VERSION, "protocol": 2}))
        decoder = Decoder()
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                for msg in decoder.feed(data):
                    await self._handle(msg, writer)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._connections.discard(writer)
            self._subscribers.discard(writer)
            self._maybe_stop_usage()
            writer.close()

    async def _handle(self, msg, writer) -> None:
        if not isinstance(msg, dict) or "malformed" in msg:
            writer.write(encode({"id": None, "ok": False,
                                 "error": "malformed JSON line"}))
            return
        rid = msg.get("id")
        self._inflight += 1
        try:
            try:
                reply = await self._dispatch(msg, writer)
            except KeyError as e:
                reply = {"ok": False, "error": f"unknown node {e.args[0]!r}"}
            except Exception as e:        # never die on a request
                reply = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            writer.write(encode({"id": rid, **reply}))
        finally:
            self._inflight -= 1

    async def _dispatch(self, msg: dict, writer) -> dict:
        op = msg.get("op")
        if op == "launch":
            spec = msg.get("spec") or {}
            err = _validate_descriptor(spec.get("node"), spec.get("descriptor"))
            if err:
                return {"ok": False, "error": err}
            await self.table.launch(spec)
            return {"ok": True}
        if op == "stop":
            await self.table.stop(msg["node"])
            return {"ok": True}
        if op == "restart":
            await self.table.restart(msg["node"])
            return {"ok": True}
        if op == "status":
            return {"ok": True, "nodes": self._status_with_usage()}
        if op == "logs":
            lines = self.table.logs(msg["node"], int(msg.get("n", 100)))
            return {"ok": True, "lines": lines}
        if op == "subscribe":
            self._subscribers.add(writer)
            self._ensure_usage_task()
            return {"ok": True}
        if op == "shutdown":
            self._shutdown.set()
            return {"ok": True}
        return {"ok": False, "error": f"unknown op {op!r}"}

    # ---- events + usage ------------------------------------------------------
    def _status_with_usage(self) -> dict:
        nodes = self.table.status()
        for node, payload in nodes.items():
            payload["usage"] = self._usage.get(node)
        return nodes

    def _broadcast_status(self, node: str, payload: dict) -> None:
        self._send_all({"event": "status", **payload,
                        "usage": self._usage.get(node)})

    def _send_all(self, msg: dict) -> None:
        data = encode(msg)
        for writer in list(self._subscribers):
            try:
                writer.write(data)
            except Exception:
                self._subscribers.discard(writer)

    def _ensure_usage_task(self) -> None:
        if self._usage_task is None or self._usage_task.done():
            self._usage_task = asyncio.ensure_future(self._usage_loop())

    def _maybe_stop_usage(self) -> None:
        if not self._subscribers and self._usage_task:
            self._usage_task.cancel()
            self._usage_task = None
            self._usage = {}
            self._usage_prev = {}

    async def _usage_loop(self) -> None:
        # Exists only while subscribers exist — sheppyd's sole periodic work.
        while self._subscribers:
            pgids = {n: p["pid"] for n, p in self.table.status().items()
                     if p["pid"] and p["state"] in ("launching", "running",
                                                    "stopping")}
            self._usage, self._usage_prev = usage_mod.sample(
                pgids, self._usage_prev)
            for node, payload in self._status_with_usage().items():
                if node in self._usage:
                    self._send_all({"event": "status", **payload})
            await asyncio.sleep(self._cfg.usage_interval)
