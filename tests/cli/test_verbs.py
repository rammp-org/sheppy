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
    captured = capsys.readouterr()
    assert "restarted camera" in captured.out
    assert "warning" not in captured.err     # nothing changed since `up`
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


def test_up_refuses_an_alternative_with_load_errors(site, capsys):
    # A selected alternative that failed manifest validation must not be
    # launched with a half-built command (#61): print the error, leave the
    # node alone, converge the rest, exit 1.
    manifest_path = site / "system.yaml"
    manifest_path.write_text(manifest_path.read_text() + (
        "  - name: broken_alt\n"
        "    alternatives:\n"
        "      - id: nocmd\n"
        "        kind: process\n"))
    store = ProfileStore(str(site / "profiles"))
    store.save(Profile(name="cam-only",
                       selections={"camera": "fake", "broken_alt": "nocmd"}))

    rc = cli.main(["up", "cam-only", "--manifest", str(manifest_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "start broken_alt" not in captured.out
    assert "broken_alt" in captured.err and "needs 'command'" in captured.err
    assert "camera: running" in captured.out
    cli.main(["status"])
    assert "broken_alt" not in capsys.readouterr().out


def test_up_refuses_a_duplicate_node_name(site, capsys):
    # Two nodes named camera: up must not guess and launch the first (#231).
    manifest_path = site / "system.yaml"
    manifest_path.write_text(manifest_path.read_text() + (
        "  - name: camera\n"
        "    alternatives:\n"
        "      - id: fake\n"
        "        kind: process\n"
        "        command: \"true\"\n"))

    rc = cli.main(["up", "cam-only", "--manifest", str(manifest_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "start camera" not in captured.out
    assert captured.err.count(
        "camera: not launched, duplicate node name 'camera'") == 1


def test_up_settle_timeout_follows_the_daemon_graces(site, capsys, monkeypatch):
    # A launch_grace above the old fixed 30 s made healthy nodes "time out"
    # while still launching (#103): the settle timeout must come from the
    # daemon config, and `up` must say it is waiting.
    (site / "home" / "sheppyd.json").write_text(json.dumps(
        {"launch_grace": 35, "stop_grace": 5, "kill_grace": 5}))
    seen = {}

    async def fake_wait(client, desired, timeout):
        seen["timeout"] = timeout
        return 0

    monkeypatch.setattr(cli, "_wait_stable", fake_wait)
    rc = cli.main(["up", "cam-only", "--manifest", str(site / "system.yaml")])
    out = capsys.readouterr().out
    assert rc == 0
    assert seen["timeout"] == 35 + 5 + 5 + 10
    assert "waiting for 1 node(s) to settle" in out


def test_up_settle_timeout_honors_a_descriptor_launch_grace(
        site, capsys, monkeypatch):
    # A detached launcher can raise its own launch grace (grace["launch"]),
    # which sheppyd honors over launch_grace; the settle bound must grow
    # with it or a healthy unit "times out" while still launching (#103).
    manifest_path = site / "system.yaml"
    manifest_path.write_text(manifest_path.read_text() + (
        "  - name: unit\n"
        "    alternatives:\n"
        "      - id: slow\n"
        "        kind: slow_unit\n"))
    store = ProfileStore(str(site / "profiles"))
    store.save(Profile(name="cam-only",
                       selections={"camera": "fake", "unit": "slow"}))

    class SlowUnitLauncher:
        kind = "slow_unit"

        def validate(self, raw_alt):
            return []

        def launch(self, alt, params, ctx):
            from sheppy.launch.descriptor import LaunchDescriptor
            return LaunchDescriptor.detached(
                "unit", (PY, "-c", "pass"), poll=(PY, "-c", "pass"),
                grace={"launch": 15})

        def summary(self, alt):
            return []

    import importlib
    resolve_mod = importlib.import_module("sheppy.launch.resolve")
    from sheppy.launch.registry import LauncherRegistry, default_registry
    launchers = list(default_registry()._by_kind.values()) + [SlowUnitLauncher()]
    monkeypatch.setattr(resolve_mod, "default_registry",
                        lambda: LauncherRegistry(launchers))
    monkeypatch.setattr("sheppy.launch.registry.default_registry",
                        lambda: LauncherRegistry(launchers))
    seen = {}

    async def fake_wait(client, desired, timeout):
        seen["timeout"] = timeout
        return 0

    monkeypatch.setattr(cli, "_wait_stable", fake_wait)
    rc = cli.main(["up", "cam-only", "--manifest", str(manifest_path)])
    assert rc == 0
    assert seen["timeout"] == 15 + 0.3 + 0.3 + 10      # graces from the fixture


def _spec(alt="fake", params=None, start=("true",)):
    from sheppy.launch.descriptor import LaunchDescriptor
    from sheppy.launch.resolve import LaunchSpec
    return LaunchSpec(node="camera", alt_id=alt, params=params or {},
                      descriptor=LaunchDescriptor.inherit(start))


@pytest.mark.parametrize("running, desired, reason", [
    (_spec(alt="sim"), _spec(alt="real"), "alternative sim → real"),
    (_spec(start=("old",)), _spec(start=("new",)), "launch command changed"),
    (_spec(params={"rate": 10, "old": 1}, start=("old",)),
     _spec(params={"rate": 30}, start=("new",)),
     "launch command changed; params old: 1 → —; rate: 10 → 30"),
])
def test_restart_reason_names_what_changed(running, desired, reason):
    assert cli._restart_reason({"state": "running", "spec": running.to_wire()},
                               desired) == reason


def test_up_says_why_it_restarts_a_node(site, capsys):
    manifest = site / "system.yaml"
    manifest.write_text(manifest.read_text().replace(
        "time.sleep(30)'\"",
        "time.sleep(30)'\"\n        params: {rate: 10}"))
    ProfileStore(str(site / "profiles")).save(Profile(
        name="fast", selections={"camera": "fake"},
        overrides={"camera": {"rate": 30}}))
    assert cli.main(["up", "cam-only", "--manifest", str(manifest)]) == 0
    capsys.readouterr()
    manifest.write_text(manifest.read_text().replace("sleep(30)", "sleep(31)"))
    assert cli.main(["up", "fast", "--manifest", str(manifest)]) == 0
    assert ("restart camera (launch command changed; params rate: 10 → 30)"
            in capsys.readouterr().out)
    assert cli.main(["restart", "camera"]) == 0
    out = capsys.readouterr().out
    assert "restarted camera" in out
    assert "alternative  fake" in out and "params       rate: 30" in out


def test_restart_warns_when_the_manifest_changed_since_up(site, capsys):
    manifest = site / "system.yaml"
    assert cli.main(["up", "cam-only", "--manifest", str(manifest)]) == 0
    manifest.write_text(manifest.read_text().replace("sleep(30)", "sleep(31)"))
    capsys.readouterr()
    assert cli.main(["restart", "camera"]) == 0
    captured = capsys.readouterr()
    assert "restarted camera" in captured.out
    assert ("camera: restarted with the params it was launched with, but "
            "profile cam-only now resolves differently (launch command "
            f"changed); 'sheppy up cam-only --manifest {manifest}' applies "
            "it") in captured.err


def test_restart_warns_when_the_profile_no_longer_selects_the_node(
        site, capsys):
    assert cli.main(["up", "cam-only",
                     "--manifest", str(site / "system.yaml")]) == 0
    ProfileStore(str(site / "profiles")).save(
        Profile(name="cam-only", selections={}))
    capsys.readouterr()
    assert cli.main(["restart", "camera"]) == 0
    assert ("profile cam-only no longer selects it; 'sheppy up cam-only"
            in capsys.readouterr().err)


def test_status_of_one_node(site, capsys):
    cli.main(["up", "cam-only", "--manifest", str(site / "system.yaml")])
    capsys.readouterr()
    assert cli.main(["status", "camera"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("camera               running    fake")
    assert lines[1:3] == ["  alternative  fake", "  params       —"]
    assert lines[3].startswith("  start        ") and "sleep(30)" in lines[3]


def test_status_of_an_unsupervised_node_fails(site, capsys):
    cli.main(["up", "cam-only", "--manifest", str(site / "system.yaml")])
    capsys.readouterr()
    assert cli.main(["status", "flaky"]) == 1
    assert "flaky: not supervised" in capsys.readouterr().err


def test_status_of_a_node_without_sheppyd_fails(site, capsys):
    assert cli.main(["status", "camera"]) == 1
    assert "not running" in capsys.readouterr().out


def test_daemon_stop_leaves_nodes_running_for_the_next_daemon(site, capsys):
    # #227: asyncio's teardown finalized each node's subprocess transport,
    # which SIGKILLs a child that is still running.
    import fcntl
    import os
    import re
    import time

    from sheppy.daemon.config import lock_path

    home = str(site / "home")
    manifest = str(site / "system.yaml")
    assert cli.main(["up", "cam-only", "--manifest", manifest]) == 0
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    pid = int(re.search(r"pid=(\d+)", capsys.readouterr().out).group(1))
    assert cli.main(["daemon", "stop"]) == 0
    with open(lock_path(home), "w") as lock:   # wait for sheppyd to exit
        for _ in range(100):
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("sheppyd did not exit")
        fcntl.flock(lock, fcntl.LOCK_UN)
    os.kill(pid, 0)                            # still alive
    capsys.readouterr()
    assert cli.main(["up", "cam-only", "--manifest", manifest]) == 0
    assert "already converged" in capsys.readouterr().out
    log = (site / "home" / "logs" / "sheppyd.log").read_text()
    assert "adopted: camera" in log


def _write_runs(log_dir, node, runs: dict) -> None:
    (log_dir / node).mkdir(parents=True)
    for name, text in runs.items():
        (log_dir / node / name).write_text(text)


def test_logs_all_prints_the_latest_run_file_without_sheppyd(
        tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    whole = "".join(f"line {i}\n" for i in range(1000))   # past ring_lines
    _write_runs(tmp_path / "logs", "camera", {
        "20261102-090000-999000000.log": whole,
        "20261102-090000-001000000.log": "same second, earlier\n",
        "20261101-090000-000000001.log": "older run\n",
        "zzz.txt": "not a run\n",
    })
    assert cli.main(["logs", "camera", "--all"]) == 0
    assert capsys.readouterr().out == whole


def test_logs_all_reads_log_dir_from_sheppyd_json(tmp_path, capsys,
                                                  monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    (tmp_path / "sheppyd.json").write_text(
        json.dumps({"log_dir": str(tmp_path / "elsewhere")}))
    _write_runs(tmp_path / "elsewhere", "camera",
                {"20261102-090000-000002.log": "from elsewhere\n"})
    assert cli.main(["logs", "camera", "--all"]) == 0
    assert capsys.readouterr().out == "from elsewhere\n"


def test_logs_all_fails_when_the_node_has_no_run_files(tmp_path, capsys,
                                                       monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    assert cli.main(["logs", "camera", "--all"]) == 1
    assert ("camera: no run files in "
            f"{tmp_path / 'logs' / 'camera'}") in capsys.readouterr().err


def test_logs_all_rejects_a_name_outside_log_dir(tmp_path, capsys,
                                                 monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    _write_runs(tmp_path, "secret", {"20261102-090000-000000001.log": "x\n"})
    assert cli.main(["logs", "../secret", "--all"]) == 1
    assert capsys.readouterr().out == ""


def test_logs_all_rejects_n(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    with pytest.raises(SystemExit) as exc:
        cli.main(["logs", "camera", "--all", "-n", "5"])
    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_logs_all_of_a_supervised_node(site, capsys):
    cli.main(["up", "broken", "--manifest", str(site / "system.yaml")])
    capsys.readouterr()
    assert cli.main(["logs", "flaky", "--all"]) == 0
    assert capsys.readouterr().out == "no such device\n"
