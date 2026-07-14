from textual.app import ComposeResult
from tests.tui.widgets._themed import ThemedApp
from sheppy.manifest import Node, Alternative
from sheppy.tui.widgets.detail_tabs import DetailTabs, format_detail


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
        assert "phase 2b" in str(app.query_one("#detail-process").content)


async def test_show_none_is_defensive():
    app = _Harness()
    async with app.run_test():
        dt = app.query_one(DetailTabs)
        dt.show(_node(), None)  # must not raise
        assert str(app.query_one("#detail").content) == ""
