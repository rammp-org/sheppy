"""Client-side resolution: alternative -> LaunchSpec via a launcher, plus
the converge diff. The daemon never sees a manifest."""
import json
from dataclasses import dataclass

from sheppy.launch.base import LaunchContext
from sheppy.launch.descriptor import LaunchDescriptor
from sheppy.launch.registry import default_registry


@dataclass(frozen=True)
class LaunchSpec:
    node: str
    alt_id: str
    descriptor: LaunchDescriptor
    params: dict

    @property
    def argv(self) -> tuple:
        return self.descriptor.start

    def to_wire(self) -> dict:
        return {"node": self.node, "alt_id": self.alt_id,
                "params": dict(self.params),
                "descriptor": self.descriptor.to_wire()}


def resolve(manifest, node_name, alt, params, registry=None, manifest_dir=None):
    registry = registry or default_registry()
    ctx = LaunchContext(node_name, manifest, manifest_dir=manifest_dir)
    launcher = registry.get(alt.kind)
    try:
        descriptor = launcher.launch(alt, params, ctx)
    except Exception as e:
        ctx.warn(f"'{node_name}': launcher {alt.kind!r} failed to resolve: "
                 f"{type(e).__name__}: {e}")
        return (None, ctx.warnings)
    if not isinstance(descriptor, LaunchDescriptor):
        ctx.warn(f"'{node_name}': launcher {alt.kind!r} returned "
                 f"{type(descriptor).__name__}, not a LaunchDescriptor")
        return (None, ctx.warnings)
    errs = descriptor.validate()
    if errs:
        ctx.warn(f"'{node_name}': launcher {alt.kind!r} returned an invalid "
                 f"descriptor: {'; '.join(errs)}")
        return (None, ctx.warnings)
    return (LaunchSpec(node=node_name, alt_id=alt.id, descriptor=descriptor,
                       params=dict(params)), ctx.warnings)


def fmt(value) -> str:
    """A param value as it reads in YAML flow style: true, 3, "base"."""
    return json.dumps(value, default=str, ensure_ascii=False)


def changes(old: dict, new: dict) -> list:
    """`key: old → new` for each differing key; — for a key on one side only."""
    side = lambda d, k: fmt(d[k]) if k in d else "—"
    return [f"{k}: {side(old, k)} → {side(new, k)}"
            for k in sorted(old.keys() | new.keys())
            if k not in old or k not in new or old[k] != new[k]]


_ALIVE = ("launching", "running")


def diff(desired, actual):
    stops, restarts, starts = [], [], []
    for node, payload in actual.items():
        if payload["state"] in _ALIVE and node not in desired:
            stops.append(("stop", node))
    for node, spec in desired.items():
        payload = actual.get(node)
        alive = payload is not None and payload["state"] in _ALIVE
        if not alive:
            starts.append(("start", node))
        elif payload["spec"].get("descriptor") != spec.descriptor.to_wire():
            restarts.append(("restart", node))
    return stops + restarts + starts
