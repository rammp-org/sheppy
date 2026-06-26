# tests/tui/test_app.py
from sheppy.manifest import Manifest, Node, Alternative, LoadResult, ValidationError
from sheppy.tui.app import format_detail, SheppyApp


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
        # Highlight node 0 (camera); focus stays on #nodes.
        app.query_one("#nodes").index = 0
        await pilot.pause()
        # Deliberate descent: Enter on the node list focuses #alternatives.
        await pilot.press("enter")
        await pilot.pause()
        # Navigate to "mock" (index 1) in the alternatives list.
        app.query_one("#alternatives").index = 1
        await pilot.pause()
        # Select the alternative via Enter on #alternatives.
        await pilot.press("enter")
        await pilot.pause()
        assert app.selection.selected("camera") == "mock"
        # Textual 8.2.7: Static/Label stores content via .content property, not .renderable
        first_label = str(app.query_one("#node-0 Label").content)
        assert "mock" in first_label


async def test_node_list_navigation_keeps_focus():
    """Arrow-key navigation on #nodes must NOT steal focus to #alternatives."""
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        await pilot.pause()
        nodes_lv = app.query_one("#nodes")
        # On startup, focus should be on #nodes (first focusable widget).
        assert nodes_lv.has_focus, (
            f"Expected #nodes to have focus on startup, got {app.focused!r}"
        )
        # Press Down — advances the node highlight and repopulates alternatives.
        await pilot.press("down")
        await pilot.pause()
        # Focus must still be on #nodes, not stolen by _populate_alternatives.
        assert nodes_lv.has_focus, (
            f"Expected #nodes to retain focus after Down, got {app.focused!r}"
        )
        # The highlight should have advanced to index 1 (planner).
        assert nodes_lv.index == 1, (
            f"Expected nodes index 1 after Down, got {nodes_lv.index}"
        )


# --- Task 6: format_detail pure-function tests ---

def test_format_detail_launch_file():
    alt = Alternative(id="rs", kind="launch_file", package="realsense2_camera",
                      launch_file="rs_launch.py", publishes=["/camera/img"])
    text = format_detail(alt)
    assert "launch_file" in text
    assert "realsense2_camera" in text and "rs_launch.py" in text
    assert "/camera/img" in text


def test_format_detail_process():
    alt = Alternative(id="u", kind="process", command="/opt/sim/Unreal -game")
    text = format_detail(alt)
    assert "/opt/sim/Unreal -game" in text


def test_format_detail_executable():
    alt = Alternative(id="cam", kind="executable", package="our_mocks",
                      executable="mock_camera")
    text = format_detail(alt)
    assert "our_mocks" in text
    assert "mock_camera" in text


# --- Task 6: app integration tests ---

async def test_detail_updates_on_highlight():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        app.query_one("#alternatives").index = 0
        await pilot.pause()
        # Textual 8.2.7: Static exposes text via .content (not .renderable)
        detail = str(app.query_one("#detail").content)
        assert "realsense" in detail or "process" in detail


async def test_status_bar_shows_error_count():
    result = LoadResult(_result().manifest,
                        [ValidationError("nodes[0]", "boom")])
    app = SheppyApp(result, path="system.yaml")
    async with app.run_test() as pilot:
        # Textual 8.2.7: Static exposes text via .content (not .renderable)
        status = str(app.query_one("#status").content)
        assert "system.yaml" in status and "1 error" in status


async def test_error_overlay_toggles():
    result = LoadResult(_result().manifest,
                        [ValidationError("nodes[0]", "boom")])
    app = SheppyApp(result, path="system.yaml")
    async with app.run_test() as pilot:
        assert app.query_one("#errors").display is False
        await pilot.press("e")
        await pilot.pause()
        errors = app.query_one("#errors")
        assert errors.display is True
        # Textual 8.2.7: Static exposes text via .content (not .renderable)
        assert "boom" in str(errors.content)
