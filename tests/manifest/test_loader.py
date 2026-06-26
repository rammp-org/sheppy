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
