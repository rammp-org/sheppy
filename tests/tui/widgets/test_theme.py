from sheppy.tui.widgets.theme import PALETTE, c, SHEPPY_DARK


def test_palette_has_atom_one_dark_green():
    assert PALETTE["green"] == "#98c379"
    assert PALETTE["bg"] == "#282c34"


def test_c_wraps_text_in_hex_markup():
    assert c("green", "hi") == "[#98c379]hi[/]"


def test_theme_name():
    assert SHEPPY_DARK.name == "sheppy-dark"
    assert SHEPPY_DARK.dark is True
