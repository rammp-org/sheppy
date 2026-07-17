# tests/test_e2e.py
"""The one full-stack test: real TUI, real DaemonClient, real sheppyd
(auto-spawned), real child processes. Everything else uses fakes/units."""
import asyncio
import json
import sys
import textwrap

import pytest

from sheppy import cli
from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp
from sheppy.tui.widgets import status as st


@pytest.fixture
def site(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SHEPPY_HOME", str(home))
    (home / "sheppyd.json").write_text(json.dumps(
        {"launch_grace": 0.2, "stop_grace": 0.3, "kill_grace": 0.3}))
    manifest = tmp_path / "system.yaml"
    manifest.write_text(textwrap.dedent(f"""\
        machines: []
        nodes:
          - name: camera
            alternatives:
              - id: fake
                kind: process
                command: "{sys.executable} -c 'import time; time.sleep(60)'"
        """))
    yield str(manifest)
    cli.main(["down"])


async def _wait_glyph(app, pilot, glyph, timeout=10.0):
    for _ in range(int(timeout / 0.1)):
        await pilot.pause(0.1)
        if glyph in str(app.query_one("#node-0 .col-status").content):
            return
    raise AssertionError(
        f"glyph {glyph!r} never appeared: "
        f"{app.query_one('#node-0 .col-status').content!r}")


async def test_select_space_run_stop_through_real_daemon(site):
    app = SheppyApp(load_manifest(site), path=site)     # client=None: real
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter", "escape")   # select camera/fake
        await pilot.press("space")                      # auto-spawns sheppyd
        await _wait_glyph(app, pilot, st.glyph(st.Status.RUNNING))
        footer = str(app.query_one("#sf-daemon").content)
        assert "●" in footer
        await pilot.press("x")
        await _wait_glyph(app, pilot, st.glyph(st.Status.NONE))
