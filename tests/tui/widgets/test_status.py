from sheppy.tui.widgets.status import Status, glyph, color_key


def test_glyphs_for_current_phase():
    assert glyph(Status.NONE) == "○"
    assert glyph(Status.SELECTED) == "◆"


def test_every_status_has_a_glyph_and_color():
    for s in Status:
        assert isinstance(glyph(s), str) and glyph(s)
        assert color_key(s) in {
            "muted", "green", "yellow", "red", "blue", "orange"}
