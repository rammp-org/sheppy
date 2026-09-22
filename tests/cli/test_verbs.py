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
                command: "{PY} -c 'import sys; print(\\"no such device\\", file=sys.stderr); raise SystemExit(4)'"
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
    out = capsys.readouterr().out
    assert "flaky: crashed" in out
    # The node's last log line is printed under its status line, so the
    # reason is visible without a `sheppy logs` round trip (#97).
    after = out.split("flaky: crashed", 1)[1].splitlines()
    assert after[1].startswith("  ") and "no such device" in after[1]


def _register_launcher(monkeypatch, launcher) -> None:
    """Make the loader and resolve() see `launcher` alongside the built-in
    kinds."""
    import importlib
    # sheppy.launch's __init__ re-binds the name "resolve" to the resolve()
    # function, shadowing the submodule at that attribute — so `import
    # sheppy.launch.resolve as x` would resolve to the function, not the
    # module. Go through sys.modules via import_module to get the module.
    resolve_mod = importlib.import_module("sheppy.launch.resolve")
    from sheppy.launch.registry import LauncherRegistry, default_registry
    launchers = list(default_registry()._by_kind.values()) + [launcher]
    monkeypatch.setattr(resolve_mod, "default_registry",
                        lambda: LauncherRegistry(launchers))
    monkeypatch.setattr("sheppy.launch.registry.default_registry",
                        lambda: LauncherRegistry(launchers))


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

    _register_launcher(monkeypatch, BoomLauncher())

    rc = cli.main(["up", "cam-only", "--manifest", str(manifest_path)])
    captured = capsys.readouterr()
    assert rc == 1                          # the profile wasn't reached (#98)
    assert "kaboom" in captured.err
    assert "camera: running" in captured.out


def test_up_fails_when_the_daemon_rejects_a_launch(site, capsys, monkeypatch):
    # A launcher whose command can't be exec'd: sheppyd replies not-ok and
    # the node stays `stopped`. `up` must print the error and exit 1 (#97).
    manifest_path = site / "system.yaml"
    manifest_path.write_text(manifest_path.read_text() + (
        "  - name: bad\n"
        "    alternatives:\n"
        "      - id: missing\n"
        "        kind: missing_binary\n"))
    store = ProfileStore(str(site / "profiles"))
    store.save(Profile(name="cam-only",
                       selections={"camera": "fake", "bad": "missing"}))

    class MissingBinaryLauncher:
        kind = "missing_binary"

        def validate(self, raw_alt):
            return []

        def launch(self, alt, params, ctx):
            from sheppy.launch.descriptor import LaunchDescriptor
            return LaunchDescriptor.inherit(("/nonexistent/binary",))

        def summary(self, alt):
            return []

    _register_launcher(monkeypatch, MissingBinaryLauncher())

    rc = cli.main(["up", "cam-only", "--manifest", str(manifest_path)])
    captured = capsys.readouterr()
    assert rc == 1
    # sheppyd either rejects the launch (the node stays `stopped`) or, once
    # it maps spawn failures to `crashed` (#93), accepts it and logs why.
    assert "bad: stopped" in captured.out or "bad: crashed" in captured.out
    if "bad: " in captured.err:
        assert "/nonexistent/binary" in captured.err
    assert "camera: running" in captured.out


def test_status_and_restart_and_logs(site, capsys):
    cli.main(["up", "cam-only", "--manifest", str(site / "system.yaml")])
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    first = capsys.readouterr().out
    assert "camera" in first and "running" in first
    assert cli.main(["restart", "camera"]) == 0
    assert "restarted camera" in capsys.readouterr().out
    assert cli.main(["woof", "camera"]) == 0     # old name still works (#21)
    assert "restarted camera" in capsys.readouterr().out
    assert cli.main(["logs", "camera", "-n", "5"]) == 0


def test_down_stops_everything_and_daemon(site, capsys):
    cli.main(["up", "cam-only", "--manifest", str(site / "system.yaml")])
    capsys.readouterr()
    assert cli.main(["down"]) == 0
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    assert "not running" in capsys.readouterr().out


def test_verbs_warn_when_daemon_version_differs(site, capsys, monkeypatch):
    import sheppy
    cli.main(["up", "cam-only", "--manifest", str(site / "system.yaml")])
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    assert "sheppyd" not in capsys.readouterr().err
    real = sheppy.__version__                    # what the daemon reports
    monkeypatch.setattr(sheppy, "__version__", "0.0.0")   # client upgraded
    assert cli.main(["status"]) == 0
    assert (f"sheppy: sheppyd {real} is not this client's 0.0.0; "
            "run 'sheppy daemon stop' to restart it"
            ) in capsys.readouterr().err


def test_verbs_without_daemon_are_graceful(site, capsys):
    assert cli.main(["status"]) == 0
    assert "not running" in capsys.readouterr().out
    assert cli.main(["restart", "camera"]) == 1


STATUS = {
    "camera": {"state": "running", "started_at": 1.0, "exit_code": None,
               "pid": 11, "spec": {"alt_id": "fake"}},
    "flaky": {"state": "crashed", "started_at": 1.0, "exit_code": 4,
              "pid": 12, "spec": {"alt_id": "dies"}},
}


def test_status_is_colored_on_a_terminal(capsys, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    cli._print_status(STATUS)
    out = capsys.readouterr().out
    assert out.isascii()
    assert "\033[32mrunning" in out and "\033[31mcrashed" in out
    assert "\033[31mexit=4" in out


def test_status_is_plain_when_piped_or_no_color(capsys, monkeypatch):
    cli._print_status(STATUS)                  # capsys stdout is not a tty
    piped = capsys.readouterr().out
    assert "\033[" not in piped
    assert piped.splitlines()[1].startswith(
        "flaky                crashed    dies           pid=12 exit=4")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    cli._print_status(STATUS)
    assert capsys.readouterr().out == piped


def test_unknown_profile_errors(site, capsys):
    rc = cli.main(["up", "nope", "--manifest", str(site / "system.yaml")])
    assert rc == 1


def test_up_leaves_a_node_alone_when_its_launcher_stops_resolving(
        site, capsys, monkeypatch):
    # A node that is running fine must not be stopped just because its
    # launcher fails to resolve on the next `up` (#98): it stays out of the
    # plan, the failure is printed, and `up` exits 1.
    manifest_path = site / "system.yaml"
    manifest_path.write_text(manifest_path.read_text() + (
        "  - name: compose\n"
        "    alternatives:\n"
        "      - id: svc\n"
        "        kind: sometimes\n"))
    store = ProfileStore(str(site / "profiles"))
    store.save(Profile(name="cam-only",
                       selections={"camera": "fake", "compose": "svc"}))

    class SometimesLauncher:
        kind = "sometimes"
        fails = False

        def validate(self, raw_alt):
            return []

        def launch(self, alt, params, ctx):
            if self.fails:
                raise FileNotFoundError("compose file went missing")
            from sheppy.launch.descriptor import LaunchDescriptor
            return LaunchDescriptor.inherit(
                (PY, "-c", "import time; time.sleep(30)"))

        def summary(self, alt):
            return []

    launcher = SometimesLauncher()
    _register_launcher(monkeypatch, launcher)
    assert cli.main(["up", "cam-only", "--manifest", str(manifest_path)]) == 0
    capsys.readouterr()

    launcher.fails = True
    rc = cli.main(["up", "cam-only", "--manifest", str(manifest_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "stop compose" not in captured.out
    assert "compose" in captured.err and "went missing" in captured.err
    cli.main(["status"])
    status = capsys.readouterr().out
    assert any(line.startswith("compose") and "running" in line
               for line in status.splitlines())


def test_daemon_dying_mid_command_is_reported_not_raised(tmp_path, monkeypatch,
                                                         capsys):
    # A fake sheppyd that hangs up after the first request (#99): the CLI
    # must print one line and exit 1, not traceback.
    import json
    import socket
    import threading

    from sheppy import __version__
    from sheppy.daemon.config import socket_path

    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(socket_path(str(tmp_path)))
    srv.listen(1)

    def drop_first_request():
        conn, _ = srv.accept()
        # connect() waits for the hello (#58) before any request goes out
        conn.sendall(json.dumps({"event": "hello", "sheppyd": __version__,
                                 "protocol": 2}).encode() + b"\n")
        conn.recv(65536)
        conn.close()
        srv.close()

    threading.Thread(target=drop_first_request, daemon=True).start()

    rc = cli.main(["status"])

    assert rc == 1
    assert "sheppy: sheppyd: sheppyd connection lost" in capsys.readouterr().err


def test_ctrl_c_during_verb_exits_130(monkeypatch):
    async def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_dispatch", interrupted)

    assert cli.main(["status"]) == 130


def test_up_warns_about_nonfatal_profile_errors(site, capsys):
    # A profile that loads with a discarded section must say so (#102).
    (site / "profiles" / "sloppy.yaml").write_text(
        "selections: {camera: fake}\noverrides: [1, 2]\n")
    rc = cli.main(["up", "sloppy", "--manifest", str(site / "system.yaml")])
    assert rc == 0
    assert "'overrides' is not a mapping; ignored" in capsys.readouterr().err


@pytest.mark.parametrize("n", ["0", "-5", "x"])
def test_logs_rejects_non_positive_line_count(n, capsys, tmp_path,
                                              monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))   # argparse fails first
    with pytest.raises(SystemExit) as exc:
        cli.main(["logs", "camera", "-n", n])
    assert exc.value.code == 2
    assert "positive integer" in capsys.readouterr().err
