from sheppy.tui.widgets.status import Status, glyph, color_key, runtime


def test_glyphs_for_current_phase():
    assert glyph(Status.NONE) == "○"
    assert glyph(Status.SELECTED) == "◆"


def test_every_status_has_a_glyph_and_color():
    for s in Status:
        assert isinstance(glyph(s), str) and glyph(s)
        assert color_key(s) in {
            "muted", "green", "yellow", "red", "blue", "orange"}


def test_runtime_mapping():
    assert runtime("running") is Status.RUNNING
    assert runtime("launching") is Status.LAUNCHING
    assert runtime("stopping") is Status.STOPPING
    assert runtime("crashed") is Status.CRASHED
    assert runtime("stopped") is Status.NONE
    assert runtime(None) is Status.NONE
    assert runtime("wat") is Status.WARN


def test_new_glyphs():
    assert glyph(Status.STOPPING) == "◐"
    assert glyph(Status.UNKNOWN) == "?"
