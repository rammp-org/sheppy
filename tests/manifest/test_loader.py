import textwrap
from sheppy.manifest import parse_manifest, load_manifest, LoadResult


def _valid_data():
    return {
        "machines": [{"name": "robot", "host": "10.0.0.20", "user": "r"}],
        "nodes": [
            {"name": "camera", "select": "single", "alternatives": [
                {"id": "realsense", "kind": "launch_file", "package": "realsense2_camera",
                 "launch_file": "rs_launch.py", "machine": "robot",
                 "publishes": ["/camera/color/image_raw"]},
                {"id": "mock_camera", "kind": "executable", "package": "our_mocks",
                 "executable": "mock_camera"},
            ]},
            {"name": "sim_gui", "alternatives": [
                {"id": "unreal", "kind": "process", "command": "/opt/sim/Unreal -game"},
            ]},
        ],
    }


def test_valid_manifest_parses_clean():
    result = parse_manifest(_valid_data())
    assert result.ok
    assert result.errors == []
    assert [n.name for n in result.manifest.nodes] == ["camera", "sim_gui"]
    assert result.manifest.node("camera").alternatives[0].kind == "launch_file"


def test_top_level_not_mapping():
    result = parse_manifest(["not", "a", "mapping"])
    assert result.manifest is None
    assert len(result.errors) == 1
    assert result.errors[0].location == "<root>"


def test_unknown_machine_reference():
    data = _valid_data()
    data["nodes"][0]["alternatives"][0]["machine"] = "ghost"
    result = parse_manifest(data)
    assert not result.ok
    assert any("ghost" in e.message for e in result.errors)
    # still browsable: model built despite the error
    assert result.manifest is not None


def test_duplicate_node_name():
    data = _valid_data()
    data["nodes"].append({"name": "camera", "alternatives": [
        {"id": "x", "kind": "process", "command": "true"}]})
    result = parse_manifest(data)
    assert any("camera" in e.message and "duplicate" in e.message.lower()
               for e in result.errors)


def test_duplicate_alternative_id():
    data = _valid_data()
    data["nodes"][0]["alternatives"][1]["id"] = "realsense"
    result = parse_manifest(data)
    assert any("realsense" in e.message and "duplicate" in e.message.lower()
               for e in result.errors)


def test_bad_kind():
    data = _valid_data()
    data["nodes"][1]["alternatives"][0]["kind"] = "wizardry"
    result = parse_manifest(data)
    assert any(e.location == "nodes[1].alternatives[0]" for e in result.errors)


def test_missing_kind_fields():
    data = _valid_data()
    # executable alt missing 'executable'
    del data["nodes"][0]["alternatives"][1]["executable"]
    result = parse_manifest(data)
    assert any("executable" in e.message for e in result.errors)


def test_errors_for_maps_locations_to_the_alternative():
    data = _valid_data()
    del data["nodes"][0]["alternatives"][1]["executable"]
    result = parse_manifest(data)
    camera = result.manifest.node("camera")
    good, bad = camera.alternatives
    assert result.errors_for(camera, good) == []
    assert [e.message for e in result.errors_for(camera, bad)] == [
        "alternative 'mock_camera': executable alternative needs 'executable'"]
    sim = result.manifest.node("sim_gui")
    assert result.errors_for(sim, sim.alternatives[0]) == []


def test_bad_select_value():
    data = _valid_data()
    data["nodes"][0]["select"] = "multi"
    result = parse_manifest(data)
    assert any("select" in e.message for e in result.errors)


def test_node_missing_alternatives():
    data = _valid_data()
    data["nodes"][0]["alternatives"] = []
    result = parse_manifest(data)
    assert any(e.location == "nodes[0]" for e in result.errors)


def test_load_missing_file():
    result = load_manifest("/no/such/system.yaml")
    assert result.manifest is None
    assert len(result.errors) == 1


def test_load_bad_yaml(tmp_path):
    p = tmp_path / "system.yaml"
    p.write_text("nodes: [unclosed\n")
    result = load_manifest(str(p))
    assert result.manifest is None
    assert len(result.errors) == 1


def test_load_directory_is_an_error_not_a_traceback(tmp_path):
    result = load_manifest(str(tmp_path))
    assert result.manifest is None
    assert len(result.errors) == 1
    assert result.errors[0].location == "<file>"
    assert "cannot read manifest" in result.errors[0].message


def test_load_unreadable_file_is_an_error_not_a_traceback(tmp_path):
    import os
    import pytest
    if os.geteuid() == 0:
        pytest.skip("root can read anything")
    p = tmp_path / "system.yaml"
    p.write_text("nodes: []\n")
    p.chmod(0)
    try:
        result = load_manifest(str(p))
    finally:
        p.chmod(0o600)
    assert result.manifest is None
    assert "cannot read manifest" in result.errors[0].message


def test_load_valid_file(tmp_path):
    p = tmp_path / "system.yaml"
    p.write_text(textwrap.dedent("""
        machines:
          - {name: robot, host: 10.0.0.20, user: r}
        nodes:
          - name: camera
            alternatives:
              - {id: mock, kind: executable, package: our_mocks, executable: mock_camera}
    """))
    result = load_manifest(str(p))
    assert result.ok
    assert result.manifest.node("camera") is not None


def test_non_dict_node_entry_does_not_crash():
    result = parse_manifest({"nodes": [None, "oops"]})
    assert result.manifest is not None
    assert len(result.errors) >= 2


def test_non_dict_alternative_entry_does_not_crash():
    data = _valid_data()
    data["nodes"][0]["alternatives"].append("not-a-mapping")
    result = parse_manifest(data)
    assert result.manifest is not None
    assert any("mapping" in e.message for e in result.errors)


def test_non_dict_machine_entry_does_not_crash():
    result = parse_manifest({"machines": [None], "nodes": []})
    assert result.manifest is not None
    assert any(e.location == "machines[0]" for e in result.errors)


def test_machines_not_a_list():
    result = parse_manifest({"machines": "robot", "nodes": []})
    assert any(e.location == "machines" for e in result.errors)
    assert result.manifest is not None


def test_nodes_not_a_list():
    result = parse_manifest({"nodes": "camera"})
    assert any(e.location == "nodes" for e in result.errors)
    assert result.manifest is not None


def test_machine_missing_fields():
    result = parse_manifest({"machines": [{"name": "robot"}], "nodes": []})
    assert any("host" in e.message for e in result.errors)


def test_node_missing_name():
    result = parse_manifest({"nodes": [{"alternatives": [
        {"id": "x", "kind": "process", "command": "true"}]}]})
    assert any("name" in e.message for e in result.errors)


def test_alternative_missing_id():
    data = _valid_data()
    del data["nodes"][0]["alternatives"][0]["id"]
    result = parse_manifest(data)
    assert any("id" in e.message for e in result.errors)


def test_non_list_alternatives_value():
    data = _valid_data()
    data["nodes"][0]["alternatives"] = "realsense"
    result = parse_manifest(data)
    assert any(e.location == "nodes[0]" for e in result.errors)
    assert result.manifest is not None


def test_config_bag_captures_kind_specific_fields():
    data = _valid_data()
    data["nodes"][0]["alternatives"][0]["some_custom_field"] = {"a": 1}
    result = parse_manifest(data)
    alt = result.manifest.node("camera").alternatives[0]
    assert alt.config["some_custom_field"] == {"a": 1}


def test_unknown_kind_lists_known_kinds():
    data = _valid_data()
    data["nodes"][1]["alternatives"][0]["kind"] = "wizardry"
    result = parse_manifest(data)
    msgs = [e.message for e in result.errors]
    assert any("wizardry" in m and "executable" in m for m in msgs)


def test_launcher_validate_raising_is_caught(monkeypatch):
    # The loader guard must protect against ANY launcher's validate()
    # raising, not just docker's — a launcher plugin bug must never
    # crash manifest loading.
    class BoomLauncher:
        kind = "boom"

        def validate(self, raw_alt):
            raise TypeError("kaboom")

        def launch(self, alt, params, ctx):
            raise NotImplementedError

        def summary(self, alt):
            return []

    from sheppy.launch.registry import LauncherRegistry
    fake_registry = LauncherRegistry([BoomLauncher()])
    monkeypatch.setattr(
        "sheppy.launch.registry.default_registry", lambda: fake_registry)

    data = _valid_data()
    data["nodes"][0]["alternatives"][0]["kind"] = "boom"
    result = parse_manifest(data)         # must not raise
    assert any("boom" in e.message and "kaboom" in e.message
               for e in result.errors)


def _docker_data(container):
    return {"nodes": [{"name": "n", "alternatives": [
        {"id": "d", "kind": "docker", "container": container}]}]}


def test_malformed_docker_container_string_does_not_crash():
    result = parse_manifest(_docker_data("myimage"))
    assert result.manifest is not None
    assert result.errors


def test_malformed_docker_container_list_does_not_crash():
    result = parse_manifest(_docker_data(["a", "b"]))
    assert result.errors


def test_malformed_docker_container_bad_environment_does_not_crash():
    result = parse_manifest(_docker_data({"image": "x", "environment": 5}))
    assert result.errors


def test_malformed_docker_container_bad_volumes_does_not_crash():
    result = parse_manifest(_docker_data({"image": "x", "volumes": 5}))
    assert result.errors


def test_node_name_must_be_a_safe_identifier():
    # Names become docker container names and scratch-dir paths (#66).
    for bad in ("camera 1", "../escape", "-lead", 123, "a/b"):
        data = _valid_data()
        data["nodes"][0]["name"] = bad
        result = parse_manifest(data)
        assert any(e.location == "nodes[0].name" for e in result.errors), bad
        assert result.manifest is not None
    for good in ("camera", "cam-1", "tf_broadcaster", "v1.2", "0"):
        data = _valid_data()
        data["nodes"][0]["name"] = good
        assert parse_manifest(data).ok, good


def test_alternative_id_must_be_a_safe_identifier():
    for bad in ("real sense", "../x", 7):
        data = _valid_data()
        data["nodes"][0]["alternatives"][0]["id"] = bad
        result = parse_manifest(data)
        assert any(e.location == "nodes[0].alternatives[0].id"
                   for e in result.errors), bad


def test_params_not_a_mapping_is_a_located_error():
    # params: "foo" used to load clean and then crash `sheppy up` and the
    # TUI in effective_params (#65).
    for bad in ("foo", ["a", "b"], 5):
        data = _valid_data()
        data["nodes"][0]["alternatives"][0]["params"] = bad
        result = parse_manifest(data)
        assert any(e.location == "nodes[0].alternatives[0].params"
                   and "mapping" in e.message for e in result.errors), bad
        # still browsable, with the bad value dropped
        assert result.manifest.node("camera").alternatives[0].params == {}


def test_publishes_and_subscribes_must_be_lists():
    data = _valid_data()
    data["nodes"][0]["alternatives"][0]["publishes"] = "/camera/image"
    data["nodes"][0]["alternatives"][0]["subscribes"] = {"a": 1}
    result = parse_manifest(data)
    locs = {e.location for e in result.errors}
    assert "nodes[0].alternatives[0].publishes" in locs
    assert "nodes[0].alternatives[0].subscribes" in locs
    alt = result.manifest.node("camera").alternatives[0]
    assert alt.publishes == [] and alt.subscribes == []


def test_publishes_elements_must_be_strings():
    # The TUI's detail tab joins these, which raises on a non-str element.
    data = _valid_data()
    data["nodes"][0]["alternatives"][0]["publishes"] = [{"topic": "/x"}, 5]
    result = parse_manifest(data)
    assert any(e.location == "nodes[0].alternatives[0].publishes"
               and "string" in e.message for e in result.errors)
    assert result.manifest.node("camera").alternatives[0].publishes == []
