from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp
from sheppy.tui.daemon_modals import ConvergeModal
from tests.tui._fake_daemon import FakeDaemonClient, payload

MANIFEST = "examples/cockpit-demo.yaml"


def make_app(fake):
    return SheppyApp(load_manifest(MANIFEST), path=MANIFEST, client=fake)


async def test_converge_all_shows_plan_then_executes():
    fake = FakeDaemonClient()
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter", "escape")   # select camera alt
        await pilot.press("L")
        await pilot.pause()
        assert isinstance(app.screen, ConvergeModal)
        text = " ".join(str(s.content) for s in app.screen.query("Static"))
        assert "start camera" in text
        await pilot.press("enter")
        await pilot.pause()
        launches = [kw for op, kw in fake.requests if op == "launch"]
        assert launches and launches[-1]["spec"]["node"] == "camera"


async def test_converge_all_escape_touches_nothing():
    fake = FakeDaemonClient()
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter", "escape")
        await pilot.press("L")
        await pilot.press("escape")
        await pilot.pause()
        assert not any(op == "launch" for op, _ in fake.requests)


async def test_converge_all_when_converged_warns():
    fake = FakeDaemonClient()
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("L")                # nothing selected, nothing runs
        await pilot.pause()
        assert not isinstance(app.screen, ConvergeModal)
        assert any("already converged" in w for w in app._runtime_warnings)


async def test_converge_all_leaves_orphans_alone():
    fake = FakeDaemonClient({"old_recorder": payload("old_recorder",
                                                     "running")})
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter", "escape", "L")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert not any(op == "stop" for op, _ in fake.requests)


async def test_converge_all_survives_status_error_reply():
    fake = FakeDaemonClient()
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Connected at startup; now make the daemon's status handler reply
        # not-ok (no "nodes" key) so converge_all hits the guard, not a crash.
        fake.status_not_ok = True
        await pilot.press("enter", "enter", "escape")   # select an alt
        await pilot.press("L")
        await pilot.pause()
        # no crash, no modal, no launch issued
        assert not isinstance(app.screen, ConvergeModal)
        assert not any(op == "launch" for op, _ in fake.requests)


async def test_stop_all_confirms_and_includes_orphans():
    fake = FakeDaemonClient({
        "camera": payload("camera", "running", alt="realsense"),
        "old_recorder": payload("old_recorder", "running"),
    })
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("X")
        await pilot.pause()
        # ConfirmModal accepts "y" (see profile_modals.py ConfirmModal.on_key)
        await pilot.press("y")
        await pilot.pause()
        stopped = sorted(kw["node"] for op, kw in fake.requests
                         if op == "stop")
        assert stopped == ["camera", "old_recorder"]


async def test_snapshot_copies_running_set_and_skips_orphans():
    fake = FakeDaemonClient({
        "camera": payload("camera", "running", alt="mock_camera"),
        "old_recorder": payload("old_recorder", "running"),
    })
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("!")
        await pilot.pause()
        assert app.state.selected("camera") == "mock_camera"
        assert app.state.is_dirty is True
        assert "mock_camera" in str(app.query_one("#node-0 .col-alt").content)
        assert any("old_recorder" in w for w in app._runtime_warnings)
