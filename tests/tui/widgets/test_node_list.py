from textual.app import App, ComposeResult
from sheppy.manifest import Node, Alternative
from sheppy.tui.widgets.node_list import NodeList


def _nodes():
    return [
        Node(name="camera", alternatives=[
            Alternative(id="realsense", kind="launch_file",
                        package="realsense2_camera", machine="robot")]),
        Node(name="planner", alternatives=[
            Alternative(id="astar", kind="process", command="true")]),
    ]


class _Harness(App):
    def __init__(self, selection):
        super().__init__()
        self._selection = selection

    def compose(self) -> ComposeResult:
        yield NodeList(_nodes(), self._selection)


async def test_rows_show_name_alt_and_host():
    app = _Harness({"camera": "realsense"})
    async with app.run_test():
        row = app.query_one("#node-0")
        assert "camera" in str(row.query_one(".col-name").content)
        assert "realsense" in str(row.query_one(".col-alt").content)
        assert "robot" in str(row.query_one(".col-host").content)


async def test_unselected_row_shows_dashes():
    app = _Harness({})
    async with app.run_test():
        row = app.query_one("#node-1")
        assert "—" in str(row.query_one(".col-alt").content)


async def test_set_selection_updates_row():
    app = _Harness({})
    async with app.run_test():
        app.query_one(NodeList).set_selection({"planner": "astar"})
        row = app.query_one("#node-1")
        assert "astar" in str(row.query_one(".col-alt").content)


async def test_arrow_nav_keeps_focus_and_emits_highlight():
    app = _Harness({})
    async with app.run_test() as pilot:
        nl = app.query_one(NodeList)
        assert nl.has_focus
        await pilot.press("down")
        await pilot.pause()
        assert nl.has_focus and nl.index == 1
