import textwrap
from sheppy.launch.docker.compose import load_service
from sheppy.launch.docker import DockerLauncher
from sheppy.launch.base import LaunchContext
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


def test_missing_service_warns_not_crashes(tmp_path):
    path = write(tmp_path, "services: {other: {image: i}}")
    a = Alternative(id="real", kind="docker",
                    config={"compose": {"file": "demo.compose.yml",
                                        "service": "perception"}})
    ctx = LaunchContext("perception", Manifest(machines=[], nodes=[]),
                        home=str(tmp_path), manifest_dir=str(tmp_path))
    d = DockerLauncher().launch(a, {}, ctx)     # must not raise
    assert any("perception" in w for w in ctx.warnings)
