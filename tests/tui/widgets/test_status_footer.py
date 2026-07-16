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
        assert "sheppyd" in text and "offline" in text


def test_keymap_covers_core_actions():
    labels = {label for _, label in KEYMAP}
    assert {"save", "load", "params", "errors", "apply", "stop"} <= labels


async def test_set_daemon_connected_shows_running_count():
    app = _Harness()
    async with app.run_test():
        app.query_one(StatusFooter).set_daemon(True, 3, 12)
        text = str(app.query_one("#sf-daemon").content)
        assert "●" in text and "3/12 running" in text


async def test_set_daemon_disconnected_shows_offline():
    app = _Harness()
    async with app.run_test():
        app.query_one(StatusFooter).set_daemon(False, 0, 12)
        text = str(app.query_one("#sf-daemon").content)
        assert "offline" in text
