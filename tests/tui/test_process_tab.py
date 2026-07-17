from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp
from tests.tui._fake_daemon import FakeDaemonClient, payload

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
