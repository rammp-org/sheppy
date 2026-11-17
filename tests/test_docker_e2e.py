# tests/test_docker_e2e.py
import shutil
import subprocess
import sys

import pytest

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config
from sheppy.daemon.table import ProcessTable


def _docker_ok():
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


pytestmark = pytest.mark.skipif(not _docker_ok(),
                                reason="docker not available")


def _table(tmp_path):
    cfg = Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"),
                 launch_grace=0.5)
    return ProcessTable(cfg, on_event=lambda n, p: None)


def _spec(name):
    return {"node": "sleeper", "alt_id": "alpine", "params": {}, "descriptor": {
        "supervise": "detached", "name": name,
        "start": ["docker", "run", "-d", "--name", name, "alpine:3",
                  "sleep", "3600"],
        "watch": ["docker", "wait", name],
        "stop": ["docker", "stop", "--time", "2", name],
        "logs": ["docker", "logs", "-f", name],
        "reset": ["docker", "rm", "-f", name]}}


async def _wait(table, node, state, timeout=30.0):
    import asyncio
    async def poll():
        while table.status().get(node, {}).get("state") != state:
            await asyncio.sleep(0.1)
    await asyncio.wait_for(poll(), timeout)


async def test_real_container_runs_and_stops(tmp_path):
    name = "sheppy-e2e-sleeper"
    subprocess.run(["docker", "rm", "-f", name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    table = _table(tmp_path)
    try:
        await table.launch(_spec(name))
        await _wait(table, "sleeper", pr.RUNNING)
        await table.stop("sleeper")
        await _wait(table, "sleeper", pr.STOPPED)
    finally:
        subprocess.run(["docker", "rm", "-f", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def test_container_restarted_outside_sheppy_stays_running(tmp_path):
    # `docker restart` ends `docker wait`; the node must not show crashed
    # while its container is up again (#220).
    from sheppy.launch.base import LaunchContext
    from sheppy.launch.docker import DockerLauncher
    from sheppy.manifest import Alternative, Manifest
    name = "sheppy-e2e-restart"
    alt = Alternative(id="alpine", kind="docker", raw={"container": {
        "image": "alpine:3", "command": "sleep 3600", "pull_policy": "missing"}})
    ctx = LaunchContext("e2e-restart", Manifest(machines=[], nodes=[]),
                        home=str(tmp_path))
    descriptor = DockerLauncher().launch(alt, {}, ctx).to_wire()
    spec = {"node": "sleeper", "alt_id": "alpine", "params": {},
            "descriptor": descriptor}
    table = _table(tmp_path)
    try:
        await table.launch(spec)
        await _wait(table, "sleeper", pr.RUNNING)
        before = _container_id(name)
        subprocess.run(["docker", "restart", "-t", "0", name], check=True,
                       stdout=subprocess.DEVNULL)
        import asyncio
        await asyncio.sleep(1.0)
        assert table.status()["sleeper"]["state"] == pr.RUNNING
        assert _container_id(name) == before
        subprocess.run(["docker", "kill", name], stdout=subprocess.DEVNULL)
        await _wait(table, "sleeper", pr.CRASHED)   # a real exit still counts
    finally:
        subprocess.run(["docker", "rm", "-f", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _container_id(name):
    return subprocess.run(["docker", "inspect", "-f", "{{.Id}}", name],
                          capture_output=True, text=True).stdout.strip()
