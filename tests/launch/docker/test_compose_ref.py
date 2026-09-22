import os
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
    svc, warnings = load_service(path, "perception", os.environ)
    assert svc["image"] == "org/perc:1.2"
    assert svc["network_mode"] == "host"          # default applied
    assert warnings == []


def test_load_service_warns_on_unsupported_interpolation(tmp_path, monkeypatch):
    # only ${VAR} and ${VAR:-default} are expanded; the other compose forms
    # pass through literally, which must not happen silently (#72)
    monkeypatch.setenv("TAG", "1.2")
    path = write(tmp_path, """
        services:
          perception:
            image: org/perc:$TAG
            environment:
              A: ${NET-host}
              B: ${TAG:?need it}
              C: costs $$5
              D: ${TAG}-ok
    """)
    svc, warnings = load_service(path, "perception", os.environ)
    assert svc["image"] == "org/perc:$TAG"
    assert svc["environment"]["A"] == "${NET-host}"
    assert svc["environment"]["D"] == "1.2-ok"
    for form in ("$TAG", "${NET-host}", "${TAG:?need it}", "$$"):
        assert any(repr(form) in w for w in warnings), form
    assert len(warnings) == 4
    assert all("${VAR}" in w and "${VAR:-default}" in w for w in warnings)


def test_repeated_unsupported_form_in_one_value_warns_once(tmp_path):
    write(tmp_path, "services: {perception: {image: i, command: '$A and $A'}}")
    _, warnings = load_service(tmp_path / "demo.compose.yml", "perception", {})
    assert len(warnings) == 1


def test_launcher_surfaces_interpolation_warnings(tmp_path):
    write(tmp_path, "services: {perception: {image: org/perc:$TAG}}")
    a = Alternative(id="real", kind="docker",
                    config={"compose": {"file": "demo.compose.yml",
                                        "service": "perception"}})
    ctx = LaunchContext("perception", Manifest(machines=[], nodes=[]),
                        home=str(tmp_path), manifest_dir=str(tmp_path))
    DockerLauncher().launch(a, {}, ctx)
    assert any("'perception'" in w and "'$TAG'" in w for w in ctx.warnings)


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


def test_compose_service_paths_resolve_against_compose_file_dir(tmp_path):
    # As compose does: relative to the compose file, not the manifest (#33).
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "svc.yml").write_text(textwrap.dedent("""
        services:
          perception:
            image: org/perc:1
            volumes: ["./maps:/maps"]
            env_file: ./ros.env
    """))
    a = Alternative(id="real", kind="docker",
                    config={"compose": {"file": "deploy/svc.yml",
                                        "service": "perception"}})
    ctx = LaunchContext("perception", Manifest(machines=[], nodes=[]),
                        home=str(tmp_path), manifest_dir=str(tmp_path))
    d = DockerLauncher().launch(a, {}, ctx)
    assert f"{tmp_path}/deploy/maps:/maps" in d.start
    assert f"{tmp_path}/deploy/ros.env" in d.start


def test_missing_service_warns_not_crashes(tmp_path):
    path = write(tmp_path, "services: {other: {image: i}}")
    a = Alternative(id="real", kind="docker",
                    config={"compose": {"file": "demo.compose.yml",
                                        "service": "perception"}})
    ctx = LaunchContext("perception", Manifest(machines=[], nodes=[]),
                        home=str(tmp_path), manifest_dir=str(tmp_path))
    d = DockerLauncher().launch(a, {}, ctx)     # must not raise
    assert any("perception" in w for w in ctx.warnings)


def test_malformed_compose_ref_warns_not_crashes(tmp_path):
    # 'compose' as a non-mapping (e.g. a plain string) must not crash
    # launch(); it should warn and fall back like a missing service does.
    a = Alternative(id="real", kind="docker", config={"compose": "juststring"})
    ctx = LaunchContext("perception", Manifest(machines=[], nodes=[]),
                        home=str(tmp_path), manifest_dir=str(tmp_path))
    d = DockerLauncher().launch(a, {}, ctx)     # must not raise
    assert any("compose" in w for w in ctx.warnings)
