from textual.app import ComposeResult
from sheppy.manifest import Node, Alternative
from sheppy.tui.widgets.alternatives_panel import AlternativesPanel
from tests.tui.widgets._themed import ThemedApp


def _node():
    return Node(name="camera", alternatives=[
        Alternative(id="realsense", kind="launch_file",
                    package="realsense2_camera",
                    publishes=["/a", "/b"], subscribes=["/tf"]),
        Alternative(id="mock", kind="executable", package="our_mocks"),
    ])


class _Harness(ThemedApp):
    def compose(self) -> ComposeResult:
        yield AlternativesPanel()


async def test_show_renders_radio_kind_package_and_counts():
    app = _Harness()
    async with app.run_test():
        panel = app.query_one(AlternativesPanel)
        await panel.show(_node(), "realsense")
        text = " ".join(str(l.content) for l in app.query("#alt-0 Label"))
        assert "realsense" in text
        assert "launch_file" in text and "realsense2_camera" in text
        assert "↑2" in text and "↓1" in text  # declared topic counts


async def test_show_is_defensive_on_empty_alternatives():
    app = _Harness()
    async with app.run_test():
        panel = app.query_one(AlternativesPanel)
        await panel.show(Node(name="x", alternatives=[]), None)  # must not raise
        assert len(app.query("#alt-0")) == 0
