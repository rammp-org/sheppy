from textual.app import ComposeResult
from tests.tui.widgets._themed import ThemedApp, plain
from sheppy.manifest import Node, Alternative
from textual.color import Color
from textual.widgets import Input
from sheppy.tui.widgets.detail_tabs import DetailTabs, ParamRow, format_detail


def _node():
    return Node(name="camera", alternatives=[
        Alternative(id="realsense", kind="launch_file",
                    package="realsense2_camera", launch_file="rs_launch.py",
                    publishes=["/camera/img"], subscribes=["/tf"])])


class _Harness(ThemedApp):
    def compose(self) -> ComposeResult:
        yield DetailTabs()


def test_format_detail_covers_kinds():
    alt = Alternative(id="u", kind="process", command="/opt/sim/Unreal -game")
    assert "/opt/sim/Unreal -game" in format_detail(alt)


async def test_show_populates_detail_topics_yaml():
    app = _Harness()
    async with app.run_test():
        dt = app.query_one(DetailTabs)
        node = _node()
        dt.show(node, node.alternatives[0])
        assert "realsense" in str(app.query_one("#detail").content)
        topics = str(app.query_one("#detail-topics").content)
        assert "/camera/img" in topics and "phase 4" in topics
        assert "realsense2_camera" in str(app.query_one("#detail-yaml").content)


async def test_show_none_is_defensive():
    app = _Harness()
    async with app.run_test():
        dt = app.query_one(DetailTabs)
        dt.show(_node(), None)  # must not raise
        assert str(app.query_one("#detail").content) == ""


async def test_selected_params_are_fields_yellow_when_edited():
    app = _Harness()
    async with app.run_test() as pilot:
        dt = app.query_one(DetailTabs)
        alt = Alternative(id="sim", kind="process", command="true",
                          params={"rate": 10, "frame": "base"})
        dt.show(Node(name="camera", alternatives=[alt]), alt,
                params={"rate": 30, "frame": "base"})
        await pilot.pause()
        rate, frame = app.query(ParamRow)
        assert rate.query_one(Input).value == "30"
        assert frame.query_one(Input).value == '"base"'
        assert plain(rate.query_one(".param-note")) == "(manifest 10)"
        assert plain(frame.query_one(".param-note")) == ""
        theme = app.theme_variables
        assert rate.query_one(Input).styles.color == Color.parse(
            theme["warning"])                       # the palette's yellow
        assert frame.query_one(Input).styles.color == Color.parse(
            theme["foreground"])
