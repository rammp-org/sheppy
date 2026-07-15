from textual.app import App, ComposeResult
from sheppy.tui.widgets.status_footer import StatusFooter, KEYMAP


class _Harness(App):
    def compose(self) -> ComposeResult:
        yield StatusFooter()


async def test_footer_shows_keymap_and_daemon_placeholder():
    app = _Harness()
    async with app.run_test():
        text = " ".join(str(s.content) for s in app.query("StatusFooter Static"))
        assert "save" in text and "load" in text and "errors" in text
        assert "sheppyd" in text and "phase 2b" in text


def test_keymap_covers_core_actions():
    labels = {label for _, label in KEYMAP}
    assert {"save", "load", "params", "errors"} <= labels
