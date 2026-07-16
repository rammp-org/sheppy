"""Manifest alternative -> final LaunchSpec argv, and the converge diff.
Pure functions: the daemon never sees a manifest; this is the smart half
of dumb-daemon/smart-client."""
import json
import shlex
from dataclasses import dataclass

from sheppy.manifest import Alternative, Manifest


@dataclass(frozen=True)
class LaunchSpec:
    node: str
    alt_id: str
    argv: tuple
    params: dict

    def to_wire(self) -> dict:
        return {"node": self.node, "alt_id": self.alt_id,
                "argv": list(self.argv), "params": dict(self.params)}


def _value(v) -> str:
    # bools/numbers as JSON (true/false is what ros2 parses); strings raw
    return json.dumps(v) if isinstance(v, (bool, int, float)) else str(v)


def resolve(manifest: Manifest, node_name: str, alt: Alternative,
            params: dict) -> "tuple[LaunchSpec, list[str]]":
    warnings: list[str] = []
    q = shlex.quote
    if alt.kind == "executable":
        cmd = f"exec ros2 run {q(alt.package or '')} {q(alt.executable or '')}"
        if params:
            tokens = " ".join(
                f"-p '{k}:={_value(v)}'" for k, v in params.items())
            cmd += f" --ros-args {tokens}"
    elif alt.kind == "launch_file":
        cmd = f"exec ros2 launch {q(alt.package or '')} {q(alt.launch_file or '')}"
        for k, v in params.items():
            cmd += f" '{k}:={_value(v)}'"
    else:  # "process": verbatim; exec would break pipelines, and the
        # process group covers the whole tree anyway
        cmd = alt.command or ""
        if params:
            warnings.append(
                f"'{node_name}': params on process-kind alternative "
                f"'{alt.id}' are ignored in phase 2b")
    setup = _ros_setup(manifest, alt.machine)
    if setup:
        cmd = f"source {q(setup)} && {cmd}"
    return (LaunchSpec(node=node_name, alt_id=alt.id,
                       argv=("bash", "-c", cmd), params=dict(params)),
            warnings)


def _ros_setup(manifest: Manifest, machine_name: "str | None") -> "str | None":
    if machine_name is None:
        return None
    for m in manifest.machines:
        if m.name == machine_name:
            return m.ros_setup
    return None


_ALIVE = ("launching", "running")


def diff(desired: dict, actual: dict) -> "list[tuple[str, str]]":
    stops, restarts, starts = [], [], []
    for node, payload in actual.items():
        if payload["state"] in _ALIVE and node not in desired:
            stops.append(("stop", node))
    for node, spec in desired.items():
        payload = actual.get(node)
        alive = payload is not None and payload["state"] in _ALIVE
        if not alive:
            starts.append(("start", node))
        elif payload["spec"]["argv"] != list(spec.argv):
            restarts.append(("restart", node))
    return stops + restarts + starts
