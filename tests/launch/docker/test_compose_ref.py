import textwrap
from sheppy.launch.docker.compose import load_service
from sheppy.launch.docker import DockerLauncher
from sheppy.launch.base import LaunchContext
from sheppy.launch.resolve import resolve
from sheppy.manifest import Alternative, Manifest


def write(tmp_path, text):
    p = tmp_path / "demo.compose.yml"
    p.write_text(textwrap.dedent(text))
    return str(p)


def test_load_service_with_interpolation(tmp_path, monkeypatch):
    monkeypatch.setenv("TAG", "1.2")
    path = write(tmp_path, """
        services:
          perception:
            image: org/perc:${TAG}
            network_mode: ${NET:-host}
            command: ros2 launch perc up.py
    """)
    svc = load_service(path, "perception", __import__("os").environ)
    assert svc["image"] == "org/perc:1.2"
    assert svc["network_mode"] == "host"          # default applied


def test_launcher_reads_compose_reference(tmp_path):
    path = write(tmp_path, """
        services:
          perception:
            image: org/perc:1
            command: ros2 launch perc up.py
    """)
    a = Alternative(id="real", kind="docker",
                    config={"compose": {"file": "demo.compose.yml",
                                        "service": "perception"}})
    ctx = LaunchContext("perception", Manifest(machines=[], nodes=[]),
                        home=str(tmp_path), manifest_dir=str(tmp_path))
    d = DockerLauncher().launch(a, {}, ctx)
    assert "org/perc:1" in d.start
    assert d.name == "sheppy-perception"


def _resolve(tmp_path, config):
    a = Alternative(id="real", kind="docker", config=config)
    return resolve(Manifest(machines=[], nodes=[]), "perception", a, {},
                   manifest_dir=str(tmp_path))


def test_missing_service_resolves_to_no_spec(tmp_path):
    # There is nothing to run, so resolve() must hand back None with the
    # warning rather than a `docker run ... ''` that crashes with no log (#67)
    write(tmp_path, "services: {other: {image: i}}")
    spec, warnings = _resolve(tmp_path, {"compose": {"file": "demo.compose.yml",
                                                     "service": "perception"}})
    assert spec is None
    assert any("perception" in w for w in warnings)


def test_missing_compose_file_resolves_to_no_spec(tmp_path):
    spec, warnings = _resolve(tmp_path, {"compose": {"file": "nope.yml",
                                                     "service": "perception"}})
    assert spec is None
    assert any("nope.yml" in w for w in warnings)


def test_malformed_compose_ref_resolves_to_no_spec(tmp_path):
    # 'compose' as a non-mapping (e.g. a plain string) must not crash
    # resolve(); it warns and yields no spec like a missing service does.
    spec, warnings = _resolve(tmp_path, {"compose": "juststring"})
    assert spec is None
    assert any("compose" in w for w in warnings)
