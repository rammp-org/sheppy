import os

from sheppy.launch.descriptor import LaunchDescriptor
from sheppy.launch.resolve import resolve
from sheppy.manifest import load_manifest

_MANIFEST_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "examples", "cockpit-demo.yaml")
_manifest = None


def _default_spec_fields(node: str, alt: str) -> dict:
    """A descriptor + params matching what resolve() would actually produce
    for (node, alt) -- with no overrides -- in examples/cockpit-demo.yaml
    (the manifest every TUI test uses). This makes the app's drift
    comparison (payload["spec"] vs. the resolved spec for the *selected*
    alternative) meaningful: a payload for the currently-selected alt with
    no param overrides converges (no drift); a payload for any other alt,
    or with an override applied, drifts. Falls back to a synthetic inherit
    descriptor for orphan node/alt combos that aren't in that manifest."""
    global _manifest
    if _manifest is None:
        _manifest = load_manifest(_MANIFEST_PATH).manifest
    n = _manifest.node(node) if _manifest else None
    a = next((x for x in n.alternatives if x.id == alt), None) if n else None
    if a is None:
        descriptor = LaunchDescriptor.inherit(
            ("bash", "-c", f"exec {node}-{alt}")).to_wire()
        return {"descriptor": descriptor, "params": {}}
    spec, _ = resolve(_manifest, node, a, dict(a.params))
    return {"descriptor": spec.descriptor.to_wire(), "params": spec.params}


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
        self.status_not_ok = False
        self.log_lines: list = []

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
        if op == "status" and self.status_not_ok:
            return {"ok": False, "error": "boom"}
        if op == "status":
            return {"ok": True, "nodes": {n: dict(p)
                                          for n, p in self.nodes.items()}}
        if op == "logs":
            return {"ok": True, "lines": list(self.log_lines)}
        return {"ok": True}

    async def close(self) -> None:
        self.connected = False

    def push(self, event: dict) -> None:
        for cb in self._callbacks:
            cb(event)


def payload(node, state, alt="a", usage=None, adopted=False):
    return {"event": "status", "node": node, "state": state, "pid": 4242,
            "exit_code": 7 if state == "crashed" else None,
            "started_at": 0.0, "adopted": adopted, "usage": usage,
            "spec": {"node": node, "alt_id": alt,
                     **_default_spec_fields(node, alt)}}
