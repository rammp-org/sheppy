import json
import sys
import textwrap

import pytest

from sheppy import cli
from sheppy.profiles import ProfileStore
from sheppy.profiles.models import Profile

PY = sys.executable


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A manifest of process-kind nodes (no ros2 needed), a profile,
    an isolated SHEPPY_HOME with fast graces."""
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "sheppyd.json").write_text(json.dumps(
        {"launch_grace": 0.1, "stop_grace": 0.3, "kill_grace": 0.3}))
    manifest = tmp_path / "system.yaml"
    manifest.write_text(textwrap.dedent(f"""\
        machines: []
        nodes:
          - name: camera
            alternatives:
              - id: fake
                kind: process
                command: "{PY} -c 'import time; time.sleep(30)'"
          - name: flaky
            alternatives:
              - id: dies
                kind: process
                command: "{PY} -c 'raise SystemExit(4)'"
        """))
    store = ProfileStore(str(tmp_path / "profiles"))
    store.save(Profile(name="cam-only", selections={"camera": "fake"}))
    store.save(Profile(name="broken", selections={"flaky": "dies"}))
    yield tmp_path
    cli.main(["down"])                      # always leave no daemon behind


def test_up_launches_profile_and_reports(site, capsys):
    rc = cli.main(["up", "cam-only", "--manifest", str(site / "system.yaml")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "start camera" in out and "camera: running" in out


def test_up_is_idempotent(site, capsys):
    assert cli.main(["up", "cam-only",
                     "--manifest", str(site / "system.yaml")]) == 0
    capsys.readouterr()
    rc = cli.main(["up", "cam-only", "--manifest", str(site / "system.yaml")])
    assert rc == 0
    assert "already converged" in capsys.readouterr().out


def test_up_exits_nonzero_on_crash(site, capsys):
    rc = cli.main(["up", "broken", "--manifest", str(site / "system.yaml")])
    assert rc == 1
    assert "flaky: crashed" in capsys.readouterr().out


def test_up_skips_node_whose_launcher_raises(site, capsys, monkeypatch):
    # A launcher plugin raising in launch() must not crash `sheppy up`; the
    # affected node is skipped (warned about) and the rest still launches.
    manifest_path = site / "system.yaml"
    manifest_path.write_text(manifest_path.read_text() + (
        "  - name: broken_launcher\n"
        "    alternatives:\n"
        "      - id: boom\n"
        "        kind: boom\n"))
    store = ProfileStore(str(site / "profiles"))
    store.save(Profile(name="cam-only",
                       selections={"camera": "fake", "broken_launcher": "boom"}))

    class BoomLauncher:
        kind = "boom"

        def validate(self, raw_alt):
            return []

        def launch(self, alt, params, ctx):
            raise RuntimeError("kaboom")

        def summary(self, alt):
            return []

    import importlib
    # sheppy.launch's __init__ re-binds the name "resolve" to the resolve()
    # function, shadowing the submodule at that attribute — so `import
    # sheppy.launch.resolve as x` would resolve to the function, not the
    # module. Go through sys.modules via import_module to get the module.
    resolve_mod = importlib.import_module("sheppy.launch.resolve")
    from sheppy.launch.registry import LauncherRegistry, default_registry
    launchers = list(default_registry()._by_kind.values()) + [BoomLauncher()]
    monkeypatch.setattr(resolve_mod, "default_registry",
                        lambda: LauncherRegistry(launchers))

    rc = cli.main(["up", "cam-only", "--manifest", str(manifest_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "kaboom" in captured.err
    assert "camera: running" in captured.out


def test_status_and_woof_and_logs(site, capsys):
    cli.main(["up", "cam-only", "--manifest", str(site / "system.yaml")])
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    first = capsys.readouterr().out
    assert "camera" in first and "running" in first
    assert cli.main(["woof", "camera"]) == 0
    capsys.readouterr()
    assert cli.main(["logs", "camera", "-n", "5"]) == 0


def test_down_stops_everything_and_daemon(site, capsys):
    cli.main(["up", "cam-only", "--manifest", str(site / "system.yaml")])
    capsys.readouterr()
    assert cli.main(["down"]) == 0
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    assert "not running" in capsys.readouterr().out


def test_verbs_without_daemon_are_graceful(site, capsys):
    assert cli.main(["status"]) == 0
    assert "not running" in capsys.readouterr().out
    assert cli.main(["woof", "camera"]) == 1


def test_unknown_profile_errors(site, capsys):
    rc = cli.main(["up", "nope", "--manifest", str(site / "system.yaml")])
    assert rc == 1
