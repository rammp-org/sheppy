from textual.app import ComposeResult
from sheppy.manifest import Node, Alternative
from sheppy.tui.widgets.node_list import NodeList, RuntimeCell
from sheppy.tui.widgets import status as st
from tests.tui.widgets._themed import ThemedApp


def _nodes():
    return [
        Node(name="camera", alternatives=[
            Alternative(id="realsense", kind="launch_file",
                        package="realsense2_camera", machine="robot")]),
        Node(name="planner", alternatives=[
            Alternative(id="astar", kind="process", command="true")]),
    ]


NODES: dict = {}       # empty selection — _Harness's second (selection) arg


class _Harness(ThemedApp):
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


async def test_set_runtime_renders_glyph_drift_and_usage():
    app = _Harness({})               # existing two-node harness
    async with app.run_test():
        nl = app.query_one(NodeList)
        nl.set_runtime({
            "camera": RuntimeCell(st.Status.RUNNING, drift=True,
                                  usage="3% 142M"),
            "planner": RuntimeCell(st.Status.CRASHED),
        })
        row0 = str(app.query_one("#node-0 .col-status").content)
        assert st.glyph(st.Status.RUNNING) in row0 and "Δ" in row0
        assert "3% 142M" in str(app.query_one("#node-0 .col-usage").content)
        row1 = str(app.query_one("#node-1 .col-status").content)
        assert st.glyph(st.Status.CRASHED) in row1 and "Δ" not in row1


async def test_rows_start_unknown_until_runtime_arrives():
    app = _Harness({})
    async with app.run_test():
        assert "?" in str(app.query_one("#node-0 .col-status").content)


async def test_set_selection_marks_alt_not_status():
    app = _Harness({})
    async with app.run_test():
        nl = app.query_one(NodeList)
        nl.set_selection({"camera": "real"})
        alt = app.query_one("#node-0 .col-alt")
        assert str(alt.content) == "real" and alt.has_class("-set")
        assert "?" in str(app.query_one("#node-0 .col-status").content)


async def test_arrow_nav_keeps_focus_and_emits_highlight():
    app = _Harness({})
    async with app.run_test() as pilot:
        nl = app.query_one(NodeList)
        assert nl.has_focus
        await pilot.press("down")
        await pilot.pause()
        assert nl.has_focus and nl.index == 1


async def test_set_orphans_appends_divider_and_rows():
    app = _Harness(NODES)
    async with app.run_test():
        nl = app.query_one(NodeList)
        await nl.set_orphans([{"node": "ghost", "state": "running",
                               "spec": {"alt_id": "old"}}])
        labels = " ".join(str(l.content) for l in app.query("NodeList Label"))
        assert "ghost" in labels and "old" in labels
        await nl.set_orphans([])               # idempotent clear
        labels = " ".join(str(l.content) for l in app.query("NodeList Label"))
        assert "ghost" not in labels
