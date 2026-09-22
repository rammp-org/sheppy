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
    assert {"save", "load", "params", "errors", "apply node", "stop",
            "apply all", "stop all", "copy running"} <= labels


async def test_set_daemon_connected_shows_running_count():
    app = _Harness()
    async with app.run_test():
        app.query_one(StatusFooter).set_daemon(True, 3, 12)
        text = str(app.query_one("#sf-daemon").content)
        assert "●" in text and "3/12 running" in text


async def test_daemon_status_survives_a_narrow_terminal():
    # #40: the hints and the sheppyd status shared one row, and below ~167
    # columns the status was the first thing cut off on the right.
    app = _Harness()
    async with app.run_test(size=(80, 5)) as pilot:
        await pilot.pause()
        daemon = app.query_one("#sf-daemon")
        assert "sheppyd" in str(daemon.content)
        region = daemon.region
        assert app.screen.region.contains_region(region)
        x, y = region.right - 1, region.y
        assert app.screen.get_widget_at(x, y)[0] is daemon


async def test_set_daemon_disconnected_shows_offline():
    app = _Harness()
    async with app.run_test():
        app.query_one(StatusFooter).set_daemon(False, 0, 12)
        text = str(app.query_one("#sf-daemon").content)
        assert "offline" in text
