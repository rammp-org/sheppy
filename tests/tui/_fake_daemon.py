class FakeDaemonClient:
    """Test double matching DaemonClient's surface. Seed `nodes` with
    daemon status payloads; `push()` fires a live event into the app."""

    def __init__(self, nodes: "dict | None" = None, connect_ok: bool = True):
        self.connected = False
        self._ok = connect_ok
        self.nodes = dict(nodes or {})
        self.requests: list = []
        self._callbacks: list = []
        self.spawn_attempts: list = []
        self.raise_on_request = False

    async def connect(self, spawn: bool = True) -> bool:
        self.spawn_attempts.append(spawn)
        self.connected = self._ok
        return self._ok

    def on_event(self, callback) -> None:
        self._callbacks.append(callback)

    async def subscribe(self) -> dict:
        return {"ok": True}

    async def request(self, op: str, **kw) -> dict:
        self.requests.append((op, kw))
        if self.raise_on_request:
            from sheppy.daemon.client import DaemonError
            raise DaemonError("lost")
        if op == "status":
            return {"ok": True, "nodes": {n: dict(p)
                                          for n, p in self.nodes.items()}}
        return {"ok": True}

    async def close(self) -> None:
        self.connected = False

    def push(self, event: dict) -> None:
        for cb in self._callbacks:
            cb(event)


def payload(node, state, alt="a", argv=None, usage=None, adopted=False):
    return {"event": "status", "node": node, "state": state, "pid": 4242,
            "exit_code": 7 if state == "crashed" else None,
            "started_at": 0.0, "adopted": adopted, "usage": usage,
            "spec": {"node": node, "alt_id": alt,
                     "argv": argv or ["bash", "-c", "x"], "params": {}}}
