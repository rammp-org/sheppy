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
        # Rows now have multiple column Labels; join them.
        text = "\n".join(
            " ".join(str(l.content) for l in item.query("Label"))
            for item in nodes.children)
        assert "camera" in text and "planner" in text


async def test_highlighting_node_populates_alternatives():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        alts = app.query_one("#alternatives")
        text = "\n".join(
            " ".join(str(l.content) for l in item.query("Label"))
            for item in alts.children)
        assert "realsense" in text and "mock" in text


async def test_selecting_alternative_updates_state_and_label():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        app.query_one("#alternatives").index = 1
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.selected("camera") == "mock"
        assert "mock" in str(app.query_one("#node-0 .col-alt").content)


async def test_enter_on_selected_alternative_deselects_it():
    # #52: a node with nothing selected is left out of the launch set.
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        app.query_one("#alternatives").index = 1
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.selected("camera") == "mock"
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.selected("camera") is None
        assert str(app.query_one("#node-0 .col-alt").content) == "—"
        radios = " ".join(str(l.content) for l in
                          app.query("#alternatives .alt-main"))
        assert "◉" not in radios


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


def _alt_ids(panel):
    return [str(item.query(".alt-main").first().content).split()[-1]
            for item in panel.children]


async def test_rebuild_after_apply_does_not_outrun_the_node_cursor():
    """Regression for #19. The repopulation that follows an apply must not
    interleave with the node cursor's own — moving the cursor while it runs
    used to leave the previous node's alternatives in the pane."""
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        panel = app.query_one("#alternatives")
        assert _alt_ids(panel) == ["realsense", "mock"]

        app._rebuild_after_apply()          # queues a reshow of camera
        app.query_one("#nodes").index = 1   # cursor moves to planner
        for _ in range(3):
            await pilot.pause()
        assert _alt_ids(panel) == ["astar"]


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


async def test_arrow_navigation_fills_the_detail_tab():
    # #112: ListView.append() no longer sets an index, so after show() the
    # pane had no highlighted row and the detail tabs stayed blank until
    # Enter. The cursor lands on the selected alternative, else the first.
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        await pilot.pause()
        alts = app.query_one("#alternatives")
        assert alts.index == 0
        assert "realsense" in str(app.query_one("#detail").content)
        await pilot.press("down")               # planner
        await pilot.pause()
        assert alts.index == 0
        assert "astar" in str(app.query_one("#detail").content)
        app.state.select("camera", "mock")
        await pilot.press("up")                 # back to camera
        await pilot.pause()
        assert alts.index == 1                  # the selected one
        assert "mock" in str(app.query_one("#detail").content)


async def test_status_bar_shows_error_count():
    result = LoadResult(_result().manifest,
                        [ValidationError("nodes[0]", "boom")])
    app = SheppyApp(result, path="system.yaml")
    async with app.run_test() as pilot:
        src = str(app.query_one("#hb-source").content)
        err = str(app.query_one("#hb-errors").content)
        assert "system.yaml" in src and "1 error" in err


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


async def test_runtime_warnings_dedupe_and_cap():
    """Regression for #30: the overlay grew without bound."""
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app._append_warnings(["nothing running"])
        app._append_warnings(["nothing running"])
        assert app._runtime_warnings == ["nothing running"]
        app._append_warnings([f"w{i}" for i in range(30)])
        assert len(app._runtime_warnings) == 20
        assert app._runtime_warnings[-1] == "w29"


async def test_dismissing_overlay_clears_runtime_warnings_only():
    result = LoadResult(_result().manifest,
                        [ValidationError("nodes[0]", "boom")])
    app = SheppyApp(result, path="system.yaml")
    async with app.run_test() as pilot:
        app._append_warnings(["nothing running"])
        await pilot.pause()
        errors = app.query_one("#errors")
        assert errors.display is True
        await pilot.press("e")                  # dismiss
        await pilot.pause()
        assert app._runtime_warnings == []
        await pilot.press("e")                  # reopen
        await pilot.pause()
        text = str(errors.content)
        assert "boom" in text and "nothing running" not in text


async def test_stale_alternatives_pane_acts_only_on_what_a_row_shows():
    """Regression for #17. The pane's rows and the node cursor can fall out of
    step. #20 and #29 closed the reshow race that produced this, so build the
    state directly: planner is highlighted while the pane also holds camera's
    rows. A row's position says nothing about which alternative it shows, so
    highlighting one must not index planner's shorter list, and selecting a
    camera row must not record anything as planner's selection."""
    from sheppy.tui.widgets.alternatives_panel import AlternativeRow
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 1
        await pilot.pause()
        planner = app._current_node()
        assert planner.name == "planner"
        camera = app.manifest.node("camera")
        panel = app.query_one("#alternatives")
        for alt in camera.alternatives:
            await panel.append(AlternativeRow(camera, alt, panel._widget(alt, False)))
        await pilot.pause()
        stale = [i for i, row in enumerate(panel.children) if row.node is camera]
        assert len(panel.children) > len(planner.alternatives) and stale

        panel.focus()
        for i in range(len(panel.children)):    # some are out of range for planner
            panel.index = i
            await pilot.pause()
        for i in stale:
            panel.index = i
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.selected("planner") is None, panel.children[i].alt.id
            assert app.state.selected("camera") is None, panel.children[i].alt.id


async def test_q_quits():
    """`q` quits too: some terminals (VSCode) swallow Ctrl+Q."""
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running
