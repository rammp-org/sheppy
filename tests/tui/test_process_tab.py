import asyncio

from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp
from tests.tui._fake_daemon import FakeDaemonClient, payload
from tests.tui.widgets._themed import plain
from sheppy.tui.widgets.detail_tabs import ParamRow
from textual.widgets import Input

MANIFEST = "examples/cockpit-demo.yaml"


def make_app(fake):
    return SheppyApp(load_manifest(MANIFEST), path=MANIFEST, client=fake)


def log_text(app):
    return "\n".join(app.query_one("#process-log").lines)


async def test_process_tab_renders_live_process():
    fake = FakeDaemonClient({"camera": payload("camera", "running",
                                               alt="realsense",
                                               usage={"cpu_pct": 3.0,
                                                      "rss_mb": 142.0})})
    fake.log_lines = ["[INFO] frames flowing"]     # see FakeDaemonClient tweak
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause(0.1)
        text = str(app.query_one("#detail-process").content)
        assert "running" in text and "4242" in text
        assert "3% 142M" in text
        assert log_text(app) == "[INFO] frames flowing"    # #193: prefix kept


async def test_process_tab_offline_and_unsupervised_states():
    app = make_app(FakeDaemonClient(connect_ok=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause(0.1)
        assert "offline" in str(app.query_one("#detail-process").content)


async def test_process_tab_explains_drift_on_running_node():
    fake = FakeDaemonClient({"camera": payload("camera", "running",
                                               alt="mock_camera")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "up", "enter")     # select realsense
        await pilot.press("3")
        await pilot.pause(0.1)
        text = str(app.query_one("#detail-process").content)
        assert "running mock_camera, selected realsense" in text


async def test_process_tab_explains_drift_on_unsupervised_node():
    app = make_app(FakeDaemonClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter")           # select realsense
        await pilot.press("3")
        await pilot.pause(0.1)
        text = str(app.query_one("#detail-process").content)
        assert "realsense selected, not running" in text


async def test_orphan_rows_render_and_stop_works():
    fake = FakeDaemonClient({"old_recorder": payload("old_recorder",
                                                     "running",
                                                     alt="bag_v1")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        rows = " ".join(str(l.content)
                        for l in app.query("NodeList Label"))
        assert "old_recorder" in rows and "bag_v1" in rows
        divider = " ".join(str(l.content)
                           for l in app.query(".orphan-divider Label"))
        assert "not in this manifest" in divider
        # navigate to the orphan row (12 manifest nodes + divider)
        for _ in range(13):
            await pilot.press("down")
        await pilot.pause()
        await pilot.press("x")
        assert ("stop", {"node": "old_recorder"}) in fake.requests
        await pilot.press("space")
        assert not any(op == "launch" for op, _ in fake.requests)
        assert any("stop/logs only" in w for w in app._runtime_warnings)


async def test_edit_params_on_orphan_row_does_not_crash():
    # Regression: `p` (edit params) used _current_node(), which indexed
    # manifest.nodes with the raw ListView index — out of range on an
    # orphan row → IndexError. It must warn, not crash.
    fake = FakeDaemonClient({"old_recorder": payload("old_recorder",
                                                     "running",
                                                     alt="bag_v1")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        for _ in range(13):            # onto the orphan row
            await pilot.press("down")
        await pilot.pause()
        assert app._current_orphan == "old_recorder"
        await pilot.press("p")         # edit params — must not raise
        await pilot.pause()
        assert app._current_node() is None    # range-safe on orphan rows
        assert any("stop/logs only" in w for w in app._runtime_warnings)


async def test_up_after_orphan_rows_vanish_keeps_the_app_running():
    # #107: sheppyd restarted with no orphans while the cursor sat on an
    # orphan row. The rows went away but the ListView index still pointed
    # past the end, and Up raised IndexError inside Textual.
    fake = FakeDaemonClient({"old_recorder": payload("old_recorder",
                                                     "running",
                                                     alt="bag_v1")})
    app = make_app(fake)

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(13):            # onto the orphan row
                await pilot.press("down")
            await pilot.pause()
            assert app._current_orphan == "old_recorder"
            app.actual = {}                # a fresh daemon knows nothing
            app._refresh_runtime()
            await pilot.pause()
            assert not app.query(".orphan-row")
            await pilot.press("up")
            await pilot.pause()
            assert app.is_running
            nodes = app.query_one("#nodes")
            assert nodes.index == len(app.manifest.nodes) - 2
            assert app._current_orphan is None

    await asyncio.wait_for(scenario(), 10)


async def test_status_burst_with_orphans_keeps_the_app_running():
    # #44: each status event restarts the orphan-rows rebuild. A rebuild
    # cancelled mid-`await item.remove()` cancelled the rows' own tasks, and
    # Textual's app loop, awaiting those same tasks, ended with exit code 0.
    names = [f"orphan_{i}" for i in range(7)]
    fake = FakeDaemonClient({n: payload(n, "running", alt="x") for n in names})
    app = make_app(fake)

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(10):
                fake.push(payload(names[0], "running", alt="x"))
                await asyncio.sleep(0)
            await pilot.pause(0.2)
            assert app.is_running
            assert len(app.query(".orphan-row")) == len(names)

    # a dead app loop leaves the pilot waiting forever, so bound it
    await asyncio.wait_for(scenario(), 10)


async def test_status_events_keep_the_orphan_rows_mounted():
    # #46: each status event used to remove and re-append the divider and
    # the orphan rows, so they flashed on every usage update.
    fake = FakeDaemonClient({"old_recorder": payload("old_recorder",
                                                     "launching",
                                                     alt="bag_v1")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        divider = app.query_one(".orphan-divider")
        row = app.query_one(".orphan-row")
        before = str(row.query_one(".col-status").content)
        fake.push(payload("old_recorder", "running", alt="bag_v1"))
        await pilot.pause(0.1)
        assert app.query_one(".orphan-divider") is divider
        assert app.query_one(".orphan-row") is row
        assert str(row.query_one(".col-status").content) != before


async def test_orphan_rebuild_cancelled_part_way_is_redone():
    # A rebuild cancelled while its last row is mounting leaves that row
    # without its labels; the next call must rebuild, not update in place.
    from sheppy.tui.widgets.node_list import NodeList
    app = make_app(FakeDaemonClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        nodes = app.query_one(NodeList)
        orphans = [payload("old_recorder", "running", alt="bag_v1")]
        rebuild = asyncio.create_task(nodes.set_orphans(orphans))
        while not nodes.query(".orphan-row"):
            await asyncio.sleep(0)
        rebuild.cancel()
        await nodes.set_orphans(orphans)
        await pilot.pause()
        assert len(app.query(".orphan-divider")) == 1
        assert len(app.query(".orphan-row .col-status")) == 1


async def test_enter_in_a_param_field_applies_the_edit():
    fake = FakeDaemonClient({"camera": payload("camera", "running",
                                               alt="realsense")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.state.selected("camera") == "realsense"   # adopted
        app.state.is_dirty = False
        await pilot.press("enter")
        await pilot.press("p", *"false", "enter")
        await pilot.pause()
        assert app.state.effective_params("camera")["enable_depth"] is False
        row = next(r for r in app.query(ParamRow) if r.param == "enable_depth")
        assert row.query_one(Input).value == "false"
        assert row.has_class("-edited")
        assert plain(row.query_one(".param-note")) == "(manifest true)"
        assert "*" in str(app.query_one("#profilebar").content)
        await pilot.press("escape", "3")
        await pilot.pause(0.1)
        assert "Δ params changed" in plain(app.query_one("#detail-process"))


async def test_typing_in_a_param_field_triggers_no_action():
    fake = FakeDaemonClient({"camera": payload("camera", "running",
                                               alt="realsense")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "p")       # realsense, adopted
        await pilot.pause()
        field = app.focused
        keys = ["x", "r", "space", "1", "2", "3", "4", "s", "l", "L", "X",
                "e", "p", "exclamation_mark", "q"]
        await pilot.press(*keys)
        await pilot.pause(0.1)
        assert app.is_running and len(app.screen_stack) == 1
        assert field.value == "xr 1234slLXep!q" and app.focused is field
        assert not any(op in ("stop", "restart", "launch")
                       for op, _ in fake.requests)
        assert app.query_one("#detailtabs").active == "tab-detail"
        assert not app.show_errors


async def test_detail_tab_renders_after_switching_from_an_edited_alt():
    app = make_app(FakeDaemonClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter")           # select realsense
        await pilot.press("p", *"false", "enter", "escape")
        await pilot.press("down", "enter")            # select mock_camera
        await pilot.pause()
        assert app.state.selected("camera") == "mock_camera"
        assert "mock_camera" in plain(app.query_one("#detail"))


async def test_process_tab_lists_only_the_changed_params_running_values():
    fake = FakeDaemonClient({"camera": payload(
        "camera", "running", alt="realsense", params={"enable_depth": False})})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.state.override("camera", "enable_depth", True)  # back to manifest
        await pilot.press("3")
        await pilot.pause(0.1)
        text = plain(app.query_one("#detail-process"))
        assert ("drift       Δ params changed\n"
                "            enable_depth: false running\n"
                "alternative realsense") in text
        assert "pointcloud.enable" not in text


async def test_process_tab_follows_the_highlighted_alternative():
    # #191: PROCESS describes the highlighted alternative, as DETAIL does;
    # another alternative's run is only named, without its params or logs.
    fake = FakeDaemonClient({"camera": payload(
        "camera", "crashed", alt="realsense", params={"enable_depth": False})})
    fake.log_lines = ["[ERROR] device lost"]
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause(0.1)
        text = plain(app.query_one("#detail-process"))
        assert "alternative realsense" in text
        assert log_text(app) == "[ERROR] device lost"
        app._proc_timer.pause()        # only the highlight refreshes now
        await pilot.pause()
        logs = sum(op == "logs" for op, _ in fake.requests)
        await pilot.press("enter", "down")            # highlight mock_camera
        await pilot.pause(0.1)
        text = plain(app.query_one("#detail-process"))
        assert "not running" in text
        assert text.endswith("realsense crashed (exit 7)")
        assert log_text(app) == ""
        assert sum(op == "logs" for op, _ in fake.requests) == logs
        await pilot.press("up")                       # back to realsense
        await pilot.pause(0.1)
        assert log_text(app) == "[ERROR] device lost"


async def test_process_tab_on_an_orphan_shows_its_run():
    fake = FakeDaemonClient({"old_recorder": payload("old_recorder",
                                                     "running",
                                                     alt="bag_v1")})
    fake.log_lines = ["[INFO] recording"]
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3")
        for _ in range(13):            # onto the orphan row
            await pilot.press("down")
        await pilot.pause(0.1)
        text = plain(app.query_one("#detail-process"))
        assert "alternative bag_v1" in text
        assert log_text(app) == "[INFO] recording"


async def test_process_tab_shows_drift_on_the_selected_alternative_only():
    fake = FakeDaemonClient({"camera": payload("camera", "running",
                                               alt="realsense")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3", "enter", "down", "enter")  # select mock_camera
        await pilot.pause(0.1)
        text = plain(app.query_one("#detail-process"))
        assert "running realsense, selected mock_camera" in text
        await pilot.press("down")                     # rosbag_replay
        await pilot.pause(0.1)
        assert "drift" not in plain(app.query_one("#detail-process"))


async def test_process_tab_shows_a_run_of_an_alternative_the_manifest_lacks():
    fake = FakeDaemonClient({"camera": payload("camera", "running",
                                               alt="gone_alt")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause(0.1)
        text = plain(app.query_one("#detail-process"))
        assert "alternative gone_alt" in text and "4242" in text
        assert "running gone_alt, not in this manifest" in text


async def test_alternative_highlight_off_the_process_tab_asks_for_no_logs():
    fake = FakeDaemonClient({"camera": payload("camera", "running",
                                               alt="realsense")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "down", "up")      # DETAIL stays open
        await pilot.pause(0.1)
        assert not any(op == "logs" for op, _ in fake.requests)



async def test_space_to_launch_shows_on_the_selected_alternative_only():
    # space launches the selected alternative, not the highlighted one
    app = make_app(FakeDaemonClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3", "enter", "enter")      # select realsense
        await pilot.pause(0.1)
        assert "space to launch" in plain(app.query_one("#detail-process"))
        await pilot.press("down")                     # mock_camera
        await pilot.pause(0.1)
        text = plain(app.query_one("#detail-process"))
        assert "not running" in text and "space to launch" not in text



async def test_process_output_scrolls_follows_and_stays_put():
    # #196: a long tail that follows new output at the bottom and stays
    # where it is once scrolled up.
    fake = FakeDaemonClient({"camera": payload("camera", "running",
                                               alt="realsense")})
    fake.log_lines = [f"line {i}" for i in range(100)]
    app = make_app(fake)
    async with app.run_test(size=(160, 30)) as pilot:
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause(0.1)
        app._proc_timer.pause()                       # refresh by hand
        assert ("logs", {"node": "camera", "n": 300}) in fake.requests
        log = app.query_one("#process-log")
        assert log.line_count == 100 and log.max_scroll_y > 0
        assert log.is_vertical_scroll_end
        fake.log_lines.append("line 100")
        app._refresh_process_tab()
        await pilot.pause()
        assert log.lines[-1] == "line 100" and log.is_vertical_scroll_end
        log.scroll_to(y=10, animate=False, immediate=True)
        fake.log_lines.append("line 101")
        app._refresh_process_tab()
        fake.push(payload("camera", "running", alt="realsense"))
        await pilot.pause()
        assert log.lines[-1] == "line 101" and log.scroll_y == 10


async def test_process_output_keys_scroll_and_app_keys_still_act():
    fake = FakeDaemonClient({"camera": payload("camera", "running",
                                               alt="realsense")})
    fake.log_lines = [f"line {i}" for i in range(100)]
    app = make_app(fake)
    async with app.run_test(size=(160, 30)) as pilot:
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause(0.1)
        log = app.query_one("#process-log")
        log.focus()
        await pilot.press("pageup")
        await pilot.pause()
        assert log.scroll_y < log.max_scroll_y
        await pilot.press("x")                        # read-only: x stops
        await pilot.pause()
        assert ("stop", {"node": "camera"}) in fake.requests
