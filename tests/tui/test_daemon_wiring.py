from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp
from sheppy.tui.widgets import status as st
from sheppy.tui.widgets.node_list import NodeList
from tests.tui._fake_daemon import FakeDaemonClient, payload

MANIFEST = "examples/cockpit-demo.yaml"


def make_app(fake):
    return SheppyApp(load_manifest(MANIFEST), path=MANIFEST, client=fake)


async def test_connected_daemon_renders_running_glyph_and_footer():
    fake = FakeDaemonClient({"camera": payload("camera", "running",
                                               alt="realsense")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        cell = str(app.query_one("#node-0 .col-status").content)
        assert st.glyph(st.Status.RUNNING) in cell
        footer = str(app.query_one("#sf-daemon").content)
        assert "●" in footer and "1/11" in footer


async def test_offline_daemon_shows_unknown_and_offline_footer():
    app = make_app(FakeDaemonClient(connect_ok=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "?" in str(app.query_one("#node-0 .col-status").content)
        assert "offline" in str(app.query_one("#sf-daemon").content)
        assert app._client.spawn_attempts == [False]   # browsing never spawns


async def test_daemon_dropping_during_connect_renders_offline_not_crash():
    fake = FakeDaemonClient(connect_ok=True)
    fake.raise_on_request = True
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.daemon_connected is False
        assert "?" in str(app.query_one("#node-0 .col-status").content)
        assert "offline" in str(app.query_one("#sf-daemon").content)


async def test_space_launches_resolved_spec():
    fake = FakeDaemonClient()
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        # select camera/realsense first (enter, enter walks in)
        await pilot.press("enter", "enter")
        await pilot.press("escape", "space")
        launches = [kw for op, kw in fake.requests if op == "launch"]
        assert launches, f"no launch in {fake.requests}"
        spec = launches[-1]["spec"]
        assert spec["node"] == "camera" and spec["alt_id"] == "realsense"
        descriptor = spec["descriptor"]
        assert descriptor["supervise"] == "inherit"
        assert descriptor["start"][0] == "bash" and \
            "ros2 launch" in descriptor["start"][2]


async def test_space_without_selection_on_dead_node_warns():
    fake = FakeDaemonClient()
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")
        assert not any(op == "launch" for op, _ in fake.requests)
        assert any("no alternative selected" in w
                   for w in app._runtime_warnings)


async def test_x_stops_and_r_restarts_current_node():
    fake = FakeDaemonClient({"camera": payload("camera", "running")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("x")
        await pilot.press("r")
        ops = [op for op, _ in fake.requests]
        assert "stop" in ops and "restart" in ops


async def test_crash_event_updates_glyph_live():
    fake = FakeDaemonClient({"camera": payload("camera", "running")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        fake.push(payload("camera", "crashed"))
        await pilot.pause()
        assert st.glyph(st.Status.CRASHED) in \
            str(app.query_one("#node-0 .col-status").content)


async def test_drift_marker_when_selection_differs_from_running():
    fake = FakeDaemonClient({"camera": payload("camera", "running",
                                               alt="mock_camera")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter")     # select realsense (desired)
        await pilot.pause()
        assert "Δ" in str(app.query_one("#node-0 .col-status").content)
