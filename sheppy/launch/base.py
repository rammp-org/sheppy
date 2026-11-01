"""The launcher plugin contract and the context that mediates a launcher's
side effects. Launchers are client-side; they return data, never run in
the daemon."""
import hashlib
import os
import threading
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
        # Content-addressed and never rewritten: a file a running container
        # mounts can't change under it, and other params get another path,
        # so the descriptor changes with them (#182, #64).
        key = ros_node_name or "/**"
        data = yaml.safe_dump({key: {"ros__parameters": dict(params)}}).encode()
        path = os.path.join(self.scratch_dir(),
                            f"params-{hashlib.sha256(data).hexdigest()[:16]}.yaml")
        if not os.path.exists(path):
            tmp = f"{path}.{os.getpid()}.{threading.get_ident()}"
            with open(tmp, "wb") as f:
                f.write(data)
            os.chmod(tmp, 0o644)       # readable by a non-root container user
            os.replace(tmp, path)
        return path


class Launcher(Protocol):
    kind: str

    def validate(self, raw_alt: dict) -> list: ...

    def launch(self, alt, params: dict,
               ctx: LaunchContext) -> LaunchDescriptor: ...

    def summary(self, alt) -> list: ...
