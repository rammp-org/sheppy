# tests/tui/test_app.py
from sheppy.manifest import Manifest, Node, Alternative, LoadResult
from sheppy.tui.app import SheppyApp


def _result():
    manifest = Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="realsense", kind="process", command="true"),
            Alternative(id="mock", kind="process", command="true"),
        ]),
        Node(name="planner", alternatives=[
            Alternative(id="astar", kind="process", command="true"),
        ]),
    ])
    return LoadResult(manifest, [])


async def test_node_list_renders():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        nodes = app.query_one("#nodes")
        # Textual 8.2.7: Static/Label stores content via .content property, not .renderable
        labels = [item.query_one("Label").content for item in nodes.children]
        text = "\n".join(str(label) for label in labels)
        assert "camera" in text and "planner" in text


async def test_highlighting_node_populates_alternatives():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        alts = app.query_one("#alternatives")
        # Textual 8.2.7: Static/Label stores content via .content property, not .renderable
        text = "\n".join(str(i.query_one("Label").content) for i in alts.children)
        assert "realsense" in text and "mock" in text


async def test_selecting_alternative_updates_state_and_label():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        alts = app.query_one("#alternatives")
        alts.index = 1  # "mock"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.selection.selected("camera") == "mock"
        # Textual 8.2.7: Static/Label stores content via .content property, not .renderable
        first_label = str(app.query_one("#node-0 Label").content)
        assert "mock" in first_label
