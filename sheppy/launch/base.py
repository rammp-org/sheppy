"""The launcher plugin contract and the context that mediates a launcher's
side effects. Launchers are client-side; they return data, never run in
the daemon."""
import os
from typing import Protocol

import yaml

from sheppy.daemon.config import sheppy_home
from sheppy.launch.descriptor import LaunchDescriptor


class LaunchContext:
    def __init__(self, node_name, manifest, home=None, manifest_dir=None):
        self.node_name = node_name
        self.manifest = manifest
        self._home = home or sheppy_home()
        self._warnings = []
        self.manifest_dir = manifest_dir or "."

    def warn(self, msg: str) -> None:
        self._warnings.append(msg)

    @property
    def warnings(self) -> list:
        return list(self._warnings)

    def scratch_dir(self) -> str:
        d = os.path.join(self._home, "scratch", self.node_name)
        os.makedirs(d, exist_ok=True)
        return d

    def write_params_file(self, params: dict,
                          ros_node_name: "str | None" = None) -> str:
        key = ros_node_name or "/**"
        path = os.path.join(self.scratch_dir(), "params.yaml")
        with open(path, "w") as f:
            yaml.safe_dump({key: {"ros__parameters": dict(params)}}, f)
        return path


class Launcher(Protocol):
    kind: str

    def validate(self, raw_alt: dict) -> list: ...

    def launch(self, alt, params: dict,
               ctx: LaunchContext) -> LaunchDescriptor: ...

    def summary(self, alt) -> list: ...
