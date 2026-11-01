import os
import subprocess

import pytest

from sheppy.launch.docker import DockerLauncher
from sheppy.launch.base import LaunchContext
from sheppy.manifest import Alternative, Manifest


def ctx(tmp_path):
    return LaunchContext("perception", Manifest(machines=[], nodes=[]),
                         home=str(tmp_path))


def alt(**config):
    return Alternative(id="real", kind="docker", raw=config)


def test_inline_container_descriptor(tmp_path):
    a = alt(container={"image": "org/perc:1",
                       "command": "ros2 launch perc up.py"})
    d = DockerLauncher().launch(a, {}, ctx(tmp_path))
    assert d.supervise == "detached" and d.name == "sheppy-perception"
    run = d.start[d.start.index("docker"):]
    assert run[:7] == ("docker", "run", "--pull", "never", "-d", "--name",
                       "sheppy-perception")
    assert d.start[-5:] == ("org/perc:1", "ros2", "launch", "perc", "up.py")
    assert d.watch == ("docker", "wait", "sheppy-perception")
    assert d.stop[:3] == ("docker", "stop", "--time")
    assert d.reset == ("docker", "rm", "-f", "sheppy-perception")
    assert d.validate() == []


def test_launch_refuses_a_service_with_translation_errors(tmp_path):
    # A service the translator rejects (here: no image) must not become a
    # `docker run ... ''`; launch() raises so resolve() yields no spec (#67)
    a = alt(container={"command": "x"})
    with pytest.raises(ValueError, match="image"):
        DockerLauncher().launch(a, {}, ctx(tmp_path))


def test_validate_requires_exactly_one_source(tmp_path):
    dl = DockerLauncher()
    assert any("exactly one" in e for e in dl.validate({"kind": "docker"}))
    assert any("exactly one" in e for e in dl.validate(
        {"container": {"image": "i"}, "compose": {"file": "f", "service": "s"}}))
    assert dl.validate({"container": {"image": "i"}}) == []


def test_validate_surfaces_inline_compose_errors():
    errs = DockerLauncher().validate({"container": {"command": "x"}})  # no image
    assert any("image" in e for e in errs)


def test_summary_shows_inline_image_and_network():
    a = alt(container={"image": "org/perc:1", "network_mode": "host"})
    rows = DockerLauncher().summary(a)
    assert ("image", "org/perc:1") in rows
    assert ("network", "host") in rows


def test_summary_shows_compose_ref_when_no_inline_container():
    a = alt(compose={"file": "demo.compose.yml", "service": "perception"})
    rows = DockerLauncher().summary(a)
    assert rows == [("compose", "demo.compose.yml#perception")]


def test_validate_rejects_non_mapping_container():
    dl = DockerLauncher()
    for bad in ("myimage", ["a", "b"], 5):
        errs = dl.validate({"container": bad})
        assert errs, f"expected errors for container={bad!r}"


def test_validate_rejects_bad_environment_and_volumes_types():
    dl = DockerLauncher()
    errs = dl.validate({"container": {"image": "x", "environment": 5}})
    assert errs
    errs = dl.validate({"container": {"image": "x", "volumes": 5}})
    assert errs


def test_summary_does_not_raise_on_malformed_container():
    a = alt(container="justastring")
    rows = DockerLauncher().summary(a)
    assert ("image", "—") in rows


def test_summary_still_shows_image_for_well_formed_container():
    a = alt(container={"image": "org/perc:1"})
    rows = DockerLauncher().summary(a)
    assert ("image", "org/perc:1") in rows


def test_inline_container_paths_resolve_against_manifest_dir(tmp_path):
    a = alt(container={"image": "i", "volumes": ["./maps:/maps:ro"],
                       "env_file": "./ros.env"})
    c = LaunchContext("perception", Manifest(machines=[], nodes=[]),
                      home=str(tmp_path), manifest_dir="/proj")
    d = DockerLauncher().launch(a, {}, c)
    assert "/proj/maps:/maps:ro" in d.start
    assert "/proj/ros.env" in d.start


_FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$CALLS"
case "$1" in
  pull) [ -n "$PULL_OK" ] && echo "Status: Image is up to date" && exit 0
        echo "Error response from daemon: registry unreachable" >&2; exit 1;;
  image) [ -n "$CACHED" ];;
esac
"""


def run_start(tmp_path, container, pull_ok=True, cached=True):
    """Run the descriptor's start argv against a fake docker; the result
    and the docker subcommands it ran."""
    fake = tmp_path / "docker"
    fake.write_text(_FAKE_DOCKER)
    fake.chmod(0o755)
    calls = tmp_path / "calls"
    d = DockerLauncher().launch(alt(container=container), {}, ctx(tmp_path))
    p = subprocess.run(d.start, capture_output=True, text=True, env={
        "PATH": f"{tmp_path}:{os.environ['PATH']}", "CALLS": str(calls),
        "PULL_OK": "1" if pull_ok else "", "CACHED": "1" if cached else ""})
    return p, calls.read_text().splitlines()


@pytest.mark.parametrize("pull_ok,cached,rc,logged,ran", [
    (True, True, 0, "Image is up to date", True),
    (False, True, 0, "could not pull org/perc:1; using the cached image", True),
    (False, False, 1, "registry unreachable", False),
])
def test_default_pulls_before_run(tmp_path, pull_ok, cached, rc, logged, ran):
    # No pull_policy: pull output and errors reach stderr (the node's log);
    # offline, a cached image still launches; `docker run` never re-pulls
    p, calls = run_start(tmp_path, {"image": "org/perc:1"}, pull_ok, cached)
    assert p.returncode == rc and logged in p.stderr
    assert [c for c in calls if c.startswith("run")] == (
        ["run --pull never -d --name sheppy-perception org/perc:1"]
        if ran else [])


def test_default_pull_uses_the_service_platform(tmp_path):
    _, calls = run_start(tmp_path, {"image": "org/perc:1",
                                    "platform": "linux/arm64"})
    assert calls[0] == "pull --platform linux/arm64 org/perc:1"


def test_pull_policy_is_left_to_docker_run(tmp_path):
    a = alt(container={"image": "org/perc:1", "pull_policy": "missing"})
    d = DockerLauncher().launch(a, {}, ctx(tmp_path))
    assert d.start == ("docker", "run", "-d", "--name", "sheppy-perception",
                       "--pull", "missing", "org/perc:1")
