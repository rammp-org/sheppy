import asyncio

from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp
from tests.tui._fake_daemon import FakeDaemonClient, payload
from tests.tui.widgets._themed import plain

MANIFEST = "examples/cockpit-demo.yaml"


def make_app(fake):
    return SheppyApp(load_manifest(MANIFEST), path=MANIFEST, client=fake)


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
        assert "frames flowing" in text


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


async def test_detail_tab_shows_an_edited_param_with_its_manifest_value():
    app = make_app(FakeDaemonClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter")           # select realsense
        app._on_params("camera", {"enable_depth": False})   # what `p` does
        await pilot.pause()
        text = plain(app.query_one("#detail"))
        assert "enable_depth: false (manifest true)" in text


async def test_detail_tab_renders_after_switching_from_an_edited_alt():
    app = make_app(FakeDaemonClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter")           # select realsense
        app._on_params("camera", {"enable_depth": False})
        await pilot.press("down", "enter")            # select mock_camera
        await pilot.pause()
        assert app.state.selected("camera") == "mock_camera"
        assert "mock_camera" in plain(app.query_one("#detail"))


async def test_process_tab_lists_running_params_and_per_key_drift():
    fake = FakeDaemonClient({"camera": payload(
        "camera", "running", alt="realsense", params={"enable_depth": False})})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.state.override("camera", "enable_depth", True)  # back to manifest
        await pilot.press("3")
        await pilot.pause(0.1)
        text = plain(app.query_one("#detail-process"))
        assert "alternative realsense" in text
        assert "params      enable_depth: false\n" in text
        assert ("launch command changed since start; params differ: "
                "enable_depth: false → true") in text


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
        assert "enable_depth: false" in text and "device lost" in text
        app._proc_timer.pause()        # only the highlight refreshes now
        await pilot.pause()
        logs = sum(op == "logs" for op, _ in fake.requests)
        await pilot.press("enter", "down")            # highlight mock_camera
        await pilot.pause(0.1)
        text = plain(app.query_one("#detail-process"))
        assert "not running" in text
        assert "realsense crashed (exit 7)" in text
        assert "enable_depth" not in text and "device lost" not in text
        assert sum(op == "logs" for op, _ in fake.requests) == logs
        await pilot.press("up")                       # back to realsense
        await pilot.pause(0.1)
        assert "device lost" in plain(app.query_one("#detail-process"))


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
        assert "alternative bag_v1" in text and "recording" in text


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
