from sheppy.paramdiff import changes, fmt


def test_fmt_reads_like_yaml_flow_values():
    assert [fmt(v) for v in (True, 3, 0.5, "base", None, [1, 2])] == \
        ["true", "3", "0.5", '"base"', "null", "[1, 2]"]


def test_changes_lists_each_differing_key_old_to_new():
    assert changes({"rate": 10, "frame": "a", "same": 1},
                   {"rate": 30, "fps": 5, "same": 1}) == [
        'fps: — → 5', 'frame: "a" → —', "rate: 10 → 30"]
    assert changes({"x": None}, {}) == ["x: null → —"]
    assert changes({"x": 1}, {"x": 1}) == []
