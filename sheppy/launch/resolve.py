"""Client-side resolution: alternative -> LaunchSpec via a launcher, plus
the converge diff. The daemon never sees a manifest."""
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
    descriptor = launcher.launch(alt, params, ctx)
    return (LaunchSpec(node=node_name, alt_id=alt.id, descriptor=descriptor,
                       params=dict(params)), ctx.warnings)


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
        elif (payload["spec"].get("descriptor") != spec.descriptor.to_wire()
              or payload["spec"].get("params") != spec.params):
            restarts.append(("restart", node))
    return stops + restarts + starts
