from textual.app import App
from textual.widgets import Static

from sheppy.tui.widgets.header_bar import HeaderBar
from sheppy.tui.widgets.theme import SHEPPY_DARK


def test_update_state_before_children_exist_does_not_raise():
    # The app can push state before the bar's children are mounted (#12).
    bar = HeaderBar()
    bar.update_state("demo", True, "m.yaml", 2, 0)
    assert bar._pending is not None


async def test_state_pushed_early_is_drawn_once_children_mount():
    bar = HeaderBar()
    bar.update_state("demo", True, "m.yaml", 2, 0)

    class Host(App):
        def __init__(self):
            super().__init__()
            self.register_theme(SHEPPY_DARK)    # defines $chip-border
            self.theme = SHEPPY_DARK.name

        def compose(self):
            yield bar

    async with Host().run_test() as pilot:
        await pilot.pause()
        text = str(bar.query_one("#profilebar", Static).render())
        assert "demo" in text
        assert bar._pending is None
