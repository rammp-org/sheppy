from sheppy.launch.resolve import changes, fmt


def test_fmt_reads_like_yaml_flow_values():
    assert [fmt(v) for v in (True, 3, 0.5, "base", None, [1, 2])] == \
        ["true", "3", "0.5", '"base"', "null", "[1, 2]"]


def test_changes_lists_each_differing_key_old_to_new():
    assert changes({"rate": 10, "frame": "a", "same": 1},
                   {"rate": 30, "fps": 5, "same": 1}) == [
        'fps: — → 5', 'frame: "a" → —', "rate: 10 → 30"]
    assert changes({"x": None}, {}) == ["x: null → —"]
    assert changes({"x": 1}, {"x": 1}) == []


def test_changes_lists_a_type_only_change():
    # 1 == 1.0 and 0 == False in Python, but ROS reads them as different
    # types (#230)
    assert changes({"gain": 1, "on": 0}, {"gain": 1.0, "on": False}) == [
        "gain: 1 → 1.0", "on: 0 → false"]
