from textual.app import ComposeResult
from sheppy.tui.widgets.header_bar import HeaderBar
from tests.tui.widgets._themed import ThemedApp


class _Harness(ThemedApp):
    def compose(self) -> ComposeResult:
        yield HeaderBar()


async def test_header_shows_profile_source_and_errors():
    app = _Harness()
    async with app.run_test():
        hb = app.query_one(HeaderBar)
        hb.update_state("integration-test", True, "system.yaml", 12, 3)
        assert "integration-test" in str(app.query_one("#profilebar").content)
        assert "*" in str(app.query_one("#profilebar").content)
        src = str(app.query_one("#hb-source").content)
        assert "system.yaml" in src and "12" in src
        assert "3" in str(app.query_one("#hb-errors").content)


async def test_header_none_profile_and_no_errors():
    app = _Harness()
    async with app.run_test():
        hb = app.query_one(HeaderBar)
        hb.update_state(None, False, "system.yaml", 1, 0)
        bar = str(app.query_one("#profilebar").content)
        assert "none" in bar.lower() and "*" not in bar
