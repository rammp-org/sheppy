"""Async client for sheppyd, shared by the CLI and the TUI. Auto-spawns
the daemon on demand (user decision: zero-setup operation)."""
import asyncio
import os
import subprocess
import sys

from sheppy.daemon.config import sheppy_home, socket_path
from sheppy.daemon.protocol import Decoder, encode


class DaemonError(Exception):
    pass


def spawn_daemon() -> None:
    subprocess.Popen(
        [sys.executable, "-m", "sheppy.daemon"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True)


class DaemonClient:
    def __init__(self, home: "str | None" = None) -> None:
        self._home = home or sheppy_home()
        self.connected = False
        self._writer = None
        self._pending: dict = {}
        self._next_id = 0
        self._callbacks: list = []
        self._pump_task = None

    async def connect(self, spawn: bool = True) -> bool:
        reader = writer = None
        deadline = asyncio.get_running_loop().time() + 3.0
        spawned = False
        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(
                    socket_path(self._home))
                break
            except (OSError, ValueError):
                if not spawn:
                    return False
                if not spawned:
                    spawn_daemon()
                    spawned = True
                if asyncio.get_running_loop().time() > deadline:
                    return False
                await asyncio.sleep(0.05)
        self._writer = writer
        self.connected = True
        self._pump_task = asyncio.ensure_future(self._pump(reader))
        return True

    async def request(self, op: str, **kw) -> dict:
        if not self.connected:
            raise DaemonError("not connected to sheppyd")
        self._next_id += 1
        rid = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[rid] = future
        self._writer.write(encode({"id": rid, "op": op, **kw}))
        await self._writer.drain()
        return await future

    def on_event(self, callback) -> None:
        self._callbacks.append(callback)

    async def subscribe(self) -> dict:
        return await self.request("subscribe")

    async def close(self) -> None:
        self.connected = False
        if self._pump_task:
            self._pump_task.cancel()
        if self._writer:
            self._writer.close()

    async def _pump(self, reader) -> None:
        decoder = Decoder()
        while True:
            data = await reader.read(65536)
            if not data:
                break
            for msg in decoder.feed(data):
                if "event" in msg:
                    if msg["event"] != "hello":
                        for cb in self._callbacks:
                            cb(msg)
                elif msg.get("id") in self._pending:
                    self._pending.pop(msg["id"]).set_result(msg)
        self.connected = False
        for future in self._pending.values():
            if not future.done():
                future.set_exception(DaemonError("sheppyd connection lost"))
        self._pending.clear()
