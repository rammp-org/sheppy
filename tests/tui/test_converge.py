import asyncio
import pytest

from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp
from sheppy.tui.daemon_modals import ConvergeModal
from tests.tui._fake_daemon import FakeDaemonClient, payload

MANIFEST = "examples/cockpit-demo.yaml"


def make_app(fake):
    return SheppyApp(load_manifest(MANIFEST), path=MANIFEST, client=fake)


def test_drift_returns_none_when_resolve_fails(monkeypatch):
    # A launcher raising in launch() must never crash _drift, which runs
    # on every daemon status event via the per-node refresh loop.
    app = SheppyApp(load_manifest(MANIFEST), path=MANIFEST)
    node = app.manifest.node("camera")
    app.state.select("camera", "realsense")
    monkeypatch.setattr("sheppy.tui.app.resolve",
                        lambda *a, **kw: (None, ["boom"]))
    payload = {"state": "running", "spec": {"alt_id": "realsense"}}
    assert app._drift(node, payload) is None


def _relaunched_differently():
    p = payload("camera", "running", alt="realsense")
    p["spec"]["descriptor"] = {**p["spec"]["descriptor"],
                               "start": ["bash", "-c", "exec old-realsense"]}
    return p


@pytest.mark.parametrize("selected, running, reason", [
    (None, None, None),
    ("realsense", payload("camera", "running", alt="realsense"), None),
    ("realsense", None, "realsense selected, not running"),
    ("realsense", payload("camera", "crashed", alt="realsense"),
     "realsense selected, not running"),
    (None, payload("camera", "running", alt="mock_camera"),
     "running mock_camera, nothing selected"),
    ("realsense", payload("camera", "running", alt="mock_camera"),
     "running mock_camera, selected realsense"),
    ("realsense", payload("camera", "running", alt="realsense",
                          params={"enable_depth": False}),
     "params differ: enable_depth"),
    ("realsense", _relaunched_differently(),
     "launch command changed since start"),
    ("realsense", payload("camera", "running", alt="bag_v9"),
     "running bag_v9, not in this manifest"),
])
def test_drift_names_the_reason(selected, running, reason):
    app = SheppyApp(load_manifest(MANIFEST), path=MANIFEST)
    if selected:
        app.state.select("camera", selected)
    assert app._drift(app.manifest.node("camera"), running) == reason


async def test_converge_node_survives_launcher_raising(monkeypatch):
    fake = FakeDaemonClient()
    app = make_app(fake)
    monkeypatch.setattr("sheppy.tui.app.resolve",
                        lambda *a, **kw: (None, ["boom"]))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter", "escape")   # select camera alt
        await pilot.press("space")                      # converge_node
        await pilot.pause()
        assert not any(op == "launch" for op, _ in fake.requests)
        assert any("boom" in w for w in app._runtime_warnings)


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


async def test_converge_all_leaves_unresolved_nodes_alone(monkeypatch):
    # camera is selected and running; its launcher now fails to resolve.
    # Apply-all must not stop it (#98): it stays out of the plan, and the
    # unselected lidar is still stopped.
    fake = FakeDaemonClient({
        "camera": payload("camera", "running", alt="realsense"),
        "lidar": payload("lidar", "running"),
    })
    app = make_app(fake)
    monkeypatch.setattr("sheppy.tui.app.resolve",
                        lambda *a, **kw: (None, ["boom"]))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.state.select("camera", "realsense")
        await pilot.press("L")
        await pilot.pause()
        assert isinstance(app.screen, ConvergeModal)
        text = " ".join(str(s.content) for s in app.screen.query("Static"))
        assert "camera" not in text
        await pilot.press("enter")
        await pilot.pause()
        stopped = [kw["node"] for op, kw in fake.requests if op == "stop"]
        assert stopped == ["lidar"]
        assert any("camera" in w and "left as is" in w
                   for w in app._runtime_warnings)


async def test_space_and_apply_all_refuse_an_alternative_with_load_errors(
        tmp_path):
    # An alternative that failed validation is never launched (#61): both
    # `space` and `L` refuse it, and the load error lands in the overlay.
    path = tmp_path / "system.yaml"
    path.write_text(
        "machines: []\n"
        "nodes:\n"
        "  - name: cam\n"
        "    alternatives:\n"
        "      - id: nocmd\n"
        "        kind: process\n")
    fake = FakeDaemonClient()
    app = SheppyApp(load_manifest(str(path)), path=str(path), client=fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.state.select("cam", "nocmd")
        await pilot.press("space")
        await pilot.pause()
        assert not any(op == "launch" for op, _ in fake.requests)
        assert any("needs 'command'" in w for w in app._runtime_warnings)
        assert app.show_errors
        await pilot.press("L")
        await pilot.pause()
        assert not isinstance(app.screen, ConvergeModal)
        assert not any(op == "launch" for op, _ in fake.requests)


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


async def test_converge_all_runs_actions_in_parallel():
    # lidar is in the manifest but unselected -> "stop"; camera -> "start"
    fake = FakeDaemonClient({"lidar": payload("lidar", "running")})
    fake.delay = 0.05
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter", "escape")   # select camera alt
        await pilot.press("L")
        await pilot.pause()
        assert isinstance(app.screen, ConvergeModal)
        await pilot.press("enter")
        await asyncio.sleep(0.2)
        await pilot.pause()
        ops = [op for op, _ in fake.requests if op in ("launch", "stop")]
        assert len(ops) >= 2
        assert fake.max_inflight == len(ops)


async def test_stop_all_stops_nodes_in_parallel():
    fake = FakeDaemonClient({
        "camera": payload("camera", "running", alt="realsense"),
        "old_recorder": payload("old_recorder", "running"),
    })
    fake.delay = 0.05
    app = make_app(fake)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("X")
        await pilot.pause()
        await pilot.press("y")
        await asyncio.sleep(0.2)
        await pilot.pause()
        assert sum(op == "stop" for op, _ in fake.requests) == 2
        assert fake.max_inflight == 2
