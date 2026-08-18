from sheppy.launch.docker import DockerLauncher
from sheppy.launch.base import LaunchContext
from sheppy.manifest import Alternative, Manifest


def ctx(tmp_path):
    return LaunchContext("perception", Manifest(machines=[], nodes=[]),
                         home=str(tmp_path))


def alt(**config):
    return Alternative(id="real", kind="docker", config=config)


def test_inline_container_descriptor(tmp_path):
    a = alt(container={"image": "org/perc:1",
                       "command": "ros2 launch perc up.py"})
    d = DockerLauncher().launch(a, {}, ctx(tmp_path))
    assert d.supervise == "detached" and d.name == "sheppy-perception"
    assert d.start[:5] == ("docker", "run", "-d", "--name", "sheppy-perception")
    assert d.start[-5:] == ("org/perc:1", "ros2", "launch", "perc", "up.py")
    assert d.watch == ("docker", "wait", "sheppy-perception")
    assert d.stop[:3] == ("docker", "stop", "--time")
    assert d.reset == ("docker", "rm", "-f", "sheppy-perception")
    assert d.validate() == []


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
