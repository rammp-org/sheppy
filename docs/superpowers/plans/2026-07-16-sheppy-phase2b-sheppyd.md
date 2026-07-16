# Sheppy Phase 2b: `sheppyd` + Local Launch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stdlib-only local supervisor daemon (`sheppyd`) that launches, watches, stops and restarts the manifest's node processes, plus the client library, CLI verbs, and live cockpit-TUI integration.

**Architecture:** Dumb daemon / smart client. Clients (TUI, CLI) resolve manifest+profile into final `LaunchSpec` argv; `sheppyd` is a durable process table on one asyncio loop, speaking NDJSON over a unix socket. Child stdout/stderr goes straight to per-node log files (never a pipe into the daemon); the ring buffer is a tail-view over those files. Spec: `docs/superpowers/specs/2026-07-16-sheppy-phase2b-sheppyd-design.md`.

**Tech Stack:** Python ≥3.10 stdlib only for `sheppy/daemon/` (asyncio, json, os, signal, fcntl, shlex, resource). Textual 8.2.7 + PyYAML on the client side. pytest + pytest-asyncio (`asyncio_mode="auto"`).

## Global Constraints

- `sheppy/daemon/` and `sheppy/launch/` import **stdlib only** — no textual, yaml, rich (enforced by test in Task 12).
- Zero idle CPU: no periodic timers while no client is subscribed.
- Children must survive daemon death: child stdio goes to log-file fds, `start_new_session=True` always.
- Run tests with `uv run pytest`; never bare pytest. All 104 existing tests must stay green.
- Every user-derived string rendered in the TUI goes through `theme.c()` or `markup=False` (markup-injection ethos from 2a.5).
- Daemon states are the strings `"launching" | "running" | "stopping" | "crashed" | "stopped"`.
- Defaults: `ring_lines=300, keep_runs=5, coredumps=False, usage_interval=2.0, launch_grace=2.0, stop_grace=5.0, kill_grace=5.0`.
- `SHEPPY_HOME` env var overrides `~/.sheppy` everywhere (this is how every test isolates itself).
- Match existing code style: dataclasses, no type-checking ceremony, short modules, comments only for non-obvious constraints.

## File Structure

```
sheppy/daemon/__init__.py     empty marker
sheppy/daemon/protocol.py     NDJSON encode / incremental Decoder      (Task 1)
sheppy/daemon/config.py       flat-JSON config + all paths             (Task 2)
sheppy/daemon/logs.py         NodeLog: files, ring-buffer tail, prune  (Task 3)
sheppy/daemon/process.py      spawn / grace / stop-escalation          (Task 4)
sheppy/daemon/table.py        ProcessTable + state file + re-adopt     (Task 5)
sheppy/daemon/usage.py        /proc CPU+RSS per process group          (Task 6)
sheppy/daemon/server.py       socket server, dispatch, events          (Task 7)
sheppy/daemon/__main__.py     entry point: lock, adopt, serve          (Task 7)
sheppy/daemon/client.py       async DaemonClient + auto-spawn          (Task 8)
sheppy/launch/__init__.py     re-exports
sheppy/launch/resolve.py      LaunchSpec resolver + converge diff      (Task 9)
sheppy/cli.py                 argparse subcommands                     (Task 10)
sheppy/tui/*                  live status wiring                       (Tasks 11–14)
```

---

### Task 1: NDJSON protocol module

**Files:**
- Create: `sheppy/daemon/__init__.py` (empty), `sheppy/daemon/protocol.py`
- Test: `tests/daemon/test_protocol.py` (create `tests/daemon/__init__.py` empty)

**Interfaces:**
- Consumes: nothing.
- Produces: `encode(msg: dict) -> bytes`; `class Decoder` with `feed(data: bytes) -> list[dict]`. A malformed line decodes to `{"malformed": "<raw text>"}` — the server replies with an error instead of dying.

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_protocol.py
from sheppy.daemon.protocol import Decoder, encode


def test_encode_appends_newline_and_roundtrips():
    d = Decoder()
    msgs = d.feed(encode({"op": "status", "id": 1}))
    assert msgs == [{"op": "status", "id": 1}]


def test_decoder_buffers_partial_lines():
    d = Decoder()
    raw = encode({"a": 1}) + encode({"b": 2})
    assert d.feed(raw[:5]) == []
    assert d.feed(raw[5:]) == [{"a": 1}, {"b": 2}]


def test_malformed_line_is_flagged_not_fatal():
    d = Decoder()
    msgs = d.feed(b"{not json}\n" + encode({"ok": 1}))
    assert msgs[0] == {"malformed": "{not json}"}
    assert msgs[1] == {"ok": 1}


def test_blank_lines_are_ignored():
    d = Decoder()
    assert d.feed(b"\n\n" + encode({"x": 1}) + b"\n") == [{"x": 1}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy.daemon'`

- [ ] **Step 3: Implement**

```python
# sheppy/daemon/protocol.py
"""NDJSON framing for the sheppyd socket. stdlib only."""
import json


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode()


class Decoder:
    """Incremental newline-delimited JSON decoder. A malformed line yields
    {"malformed": <text>} so the caller can answer with an error instead of
    tearing down the connection."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> list[dict]:
        self._buf += data
        out: list[dict] = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"malformed": line.decode(errors="replace")})
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_protocol.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sheppy/daemon tests/daemon
git commit -m "feat(daemon): NDJSON protocol encode/decode"
```

---

### Task 2: Config and paths

**Files:**
- Create: `sheppy/daemon/config.py`
- Test: `tests/daemon/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass(frozen=True) Config` fields: `home: str, log_dir: str, ring_lines: int = 300, keep_runs: int = 5, coredumps: bool = False, usage_interval: float = 2.0, launch_grace: float = 2.0, stop_grace: float = 5.0, kill_grace: float = 5.0`
  - `sheppy_home() -> str` — `$SHEPPY_HOME` or `~/.sheppy`
  - `load_config(home: str | None = None) -> tuple[Config, list[str]]` — reads `<home>/sheppyd.json` (flat JSON, all keys optional); a bad file or unknown/mistyped key becomes a warning string, never an exception
  - `socket_path(home) -> str`, `state_path(home) -> str`, `lock_path(home) -> str`, `daemon_log_path(cfg) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_config.py
import json
from sheppy.daemon.config import (
    Config, load_config, sheppy_home, socket_path, state_path, lock_path,
)


def test_defaults_when_no_file(tmp_path):
    cfg, warnings = load_config(str(tmp_path))
    assert cfg.ring_lines == 300 and cfg.keep_runs == 5
    assert cfg.coredumps is False and cfg.usage_interval == 2.0
    assert cfg.launch_grace == 2.0 and cfg.stop_grace == 5.0
    assert cfg.kill_grace == 5.0
    assert cfg.log_dir == str(tmp_path / "logs")
    assert warnings == []


def test_file_overrides_and_unknown_key_warns(tmp_path):
    (tmp_path / "sheppyd.json").write_text(
        json.dumps({"ring_lines": 50, "coredumps": True, "bogus": 1}))
    cfg, warnings = load_config(str(tmp_path))
    assert cfg.ring_lines == 50 and cfg.coredumps is True
    assert any("bogus" in w for w in warnings)


def test_bad_json_falls_back_to_defaults_with_warning(tmp_path):
    (tmp_path / "sheppyd.json").write_text("{nope")
    cfg, warnings = load_config(str(tmp_path))
    assert cfg.ring_lines == 300
    assert len(warnings) == 1


def test_sheppy_home_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    assert sheppy_home() == str(tmp_path)


def test_paths_derive_from_home(monkeypatch, tmp_path):
    # With SHEPPY_HOME set, the socket lives under home even if
    # XDG_RUNTIME_DIR exists — tests rely on this for isolation.
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    home = str(tmp_path)
    assert socket_path(home) == str(tmp_path / "sheppyd.sock")
    assert state_path(home) == str(tmp_path / "sheppyd.state.json")
    assert lock_path(home) == str(tmp_path / "sheppyd.lock")


def test_socket_uses_xdg_when_no_sheppy_home(monkeypatch, tmp_path):
    monkeypatch.delenv("SHEPPY_HOME", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    import os
    assert socket_path(os.path.expanduser("~/.sheppy")) == \
        str(tmp_path / "sheppy" / "sheppyd.sock")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: Implement**

```python
# sheppy/daemon/config.py
"""Flat-JSON daemon config and all sheppyd filesystem paths. stdlib only.

The config file is deliberately one flat object of plain-word keys
(user request: configs must be easy to understand). JSON, not YAML,
because the daemon has no YAML parser by design."""
import dataclasses
import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    home: str
    log_dir: str
    ring_lines: int = 300
    keep_runs: int = 5
    coredumps: bool = False
    usage_interval: float = 2.0
    launch_grace: float = 2.0
    stop_grace: float = 5.0
    kill_grace: float = 5.0


_TUNABLE = {f.name: f.type for f in dataclasses.fields(Config)
            if f.name not in ("home",)}


def sheppy_home() -> str:
    return os.environ.get("SHEPPY_HOME") or os.path.expanduser("~/.sheppy")


def load_config(home: "str | None" = None) -> "tuple[Config, list[str]]":
    home = home or sheppy_home()
    warnings: list[str] = []
    raw: dict = {}
    path = os.path.join(home, "sheppyd.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw = loaded
            else:
                warnings.append(f"{path}: expected a JSON object; using defaults")
        except (json.JSONDecodeError, OSError) as e:
            warnings.append(f"{path}: {e}; using defaults")
    kwargs: dict = {}
    for key, value in raw.items():
        if key not in _TUNABLE:
            warnings.append(f"{path}: unknown key '{key}' ignored")
            continue
        kwargs[key] = value
    log_dir = kwargs.pop("log_dir", None) or os.path.join(home, "logs")
    try:
        cfg = Config(home=home, log_dir=log_dir, **kwargs)
    except TypeError as e:
        warnings.append(f"{path}: {e}; using defaults")
        cfg = Config(home=home, log_dir=os.path.join(home, "logs"))
    return cfg, warnings


def socket_path(home: str) -> str:
    # SHEPPY_HOME pins everything under home (test isolation); otherwise
    # prefer XDG_RUNTIME_DIR (tmpfs, correct perms, cleared on logout).
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if not os.environ.get("SHEPPY_HOME") and xdg:
        return os.path.join(xdg, "sheppy", "sheppyd.sock")
    return os.path.join(home, "sheppyd.sock")


def state_path(home: str) -> str:
    return os.path.join(home, "sheppyd.state.json")


def lock_path(home: str) -> str:
    return os.path.join(home, "sheppyd.lock")


def daemon_log_path(cfg: Config) -> str:
    return os.path.join(cfg.log_dir, "sheppyd.log")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_config.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add sheppy/daemon/config.py tests/daemon/test_config.py
git commit -m "feat(daemon): flat-JSON config and sheppyd paths"
```

---

### Task 3: Log files and ring buffers

**Files:**
- Create: `sheppy/daemon/logs.py`
- Test: `tests/daemon/test_logs.py`

**Interfaces:**
- Consumes: `Config` (Task 2).
- Produces: `class NodeLog(log_dir: str, node: str, ring_lines: int, keep_runs: int)` with:
  - `open_run() -> int` — prunes old runs to `keep_runs - 1`, creates `<log_dir>/<node>/<YYYYmmdd-HHMMSS>-<suffix>.log`, resets ring+offset, returns an `O_APPEND` **fd for the child** (caller closes it after spawn)
  - `attach_latest() -> bool` — re-adoption: point at the newest existing run file, rebuild the ring from its tail, offset = EOF; False if none
  - `read_new() -> list[str]` — incremental read from the tracked offset (partial trailing line buffered until its newline arrives); appends to the ring, returns the new lines
  - `tail(n: int | None = None) -> list[str]` — ring contents (last `n`)
  - `path: str | None` — current run file

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_logs.py
import os
from sheppy.daemon.logs import NodeLog


def make_log(tmp_path, **kw):
    kw.setdefault("ring_lines", 5)
    kw.setdefault("keep_runs", 3)
    return NodeLog(str(tmp_path), "camera", **kw)


def test_open_run_creates_file_and_child_can_write(tmp_path):
    log = make_log(tmp_path)
    fd = log.open_run()
    os.write(fd, b"hello\nworld\n")
    os.close(fd)
    assert log.read_new() == ["hello", "world"]
    assert log.tail() == ["hello", "world"]
    assert log.path and log.path.endswith(".log")


def test_partial_line_held_until_newline(tmp_path):
    log = make_log(tmp_path)
    fd = log.open_run()
    os.write(fd, b"first\nhal")
    assert log.read_new() == ["first"]
    os.write(fd, b"f second\n")
    os.close(fd)
    assert log.read_new() == ["half second"]


def test_ring_is_capped(tmp_path):
    log = make_log(tmp_path, ring_lines=3)
    fd = log.open_run()
    os.write(fd, b"".join(b"line %d\n" % i for i in range(10)))
    os.close(fd)
    log.read_new()
    assert log.tail() == ["line 7", "line 8", "line 9"]
    assert log.tail(2) == ["line 8", "line 9"]


def test_prune_keeps_keep_runs_files(tmp_path):
    log = make_log(tmp_path, keep_runs=3)
    for _ in range(5):
        os.close(log.open_run())
    node_dir = tmp_path / "camera"
    assert len(list(node_dir.glob("*.log"))) == 3


def test_attach_latest_rebuilds_tail(tmp_path):
    log = make_log(tmp_path, ring_lines=2)
    fd = log.open_run()
    os.write(fd, b"a\nb\nc\n")
    os.close(fd)
    # a fresh NodeLog (new daemon) re-adopts the same node dir
    fresh = make_log(tmp_path, ring_lines=2)
    assert fresh.attach_latest() is True
    assert fresh.tail() == ["b", "c"]
    assert fresh.read_new() == []      # offset is at EOF


def test_attach_latest_with_no_runs_returns_false(tmp_path):
    assert make_log(tmp_path).attach_latest() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_logs.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# sheppy/daemon/logs.py
"""Per-node log files and the in-memory ring-buffer view. stdlib only.

Children write straight into the run file (they get the fd at spawn);
sheppyd never sits between a child and its output. The ring buffer is a
tail-view rebuilt by incremental reads of that file."""
import os
import time
from collections import deque


class NodeLog:
    def __init__(self, log_dir: str, node: str, ring_lines: int,
                 keep_runs: int) -> None:
        self._dir = os.path.join(log_dir, node)
        self._ring_lines = ring_lines
        self._keep_runs = keep_runs
        self._ring: deque = deque(maxlen=ring_lines)
        self._offset = 0
        self._partial = b""
        self.path: "str | None" = None

    def open_run(self) -> int:
        os.makedirs(self._dir, exist_ok=True)
        self._prune(self._keep_runs - 1)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        suffix = f"{time.time_ns() % 1_000_000:06d}"   # uniquify fast restarts
        self.path = os.path.join(self._dir, f"{stamp}-{suffix}.log")
        self._ring.clear()
        self._offset = 0
        self._partial = b""
        return os.open(self.path,
                       os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)

    def attach_latest(self) -> bool:
        runs = self._runs()
        if not runs:
            return False
        self.path = runs[-1]
        size = os.path.getsize(self.path)
        with open(self.path, "rb") as f:
            f.seek(max(0, size - 64 * 1024))     # tail window is plenty
            lines = f.read().decode(errors="replace").splitlines()
        self._ring.clear()
        self._ring.extend(lines[-self._ring_lines:])
        self._offset = size
        self._partial = b""
        return True

    def read_new(self) -> list[str]:
        if not self.path:
            return []
        try:
            with open(self.path, "rb") as f:
                f.seek(self._offset)
                data = f.read()
        except OSError:
            return []
        self._offset += len(data)
        data = self._partial + data
        *complete, self._partial = data.split(b"\n")
        lines = [c.decode(errors="replace") for c in complete]
        self._ring.extend(lines)
        return lines

    def tail(self, n: "int | None" = None) -> list[str]:
        lines = list(self._ring)
        return lines if n is None else lines[-n:]

    def _runs(self) -> list[str]:
        if not os.path.isdir(self._dir):
            return []
        return sorted(os.path.join(self._dir, f)
                      for f in os.listdir(self._dir) if f.endswith(".log"))

    def _prune(self, keep: int) -> None:
        runs = self._runs()
        for stale in runs[:max(0, len(runs) - keep)] if keep >= 0 else runs:
            try:
                os.unlink(stale)
            except OSError:
                pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_logs.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add sheppy/daemon/logs.py tests/daemon/test_logs.py
git commit -m "feat(daemon): per-node log files with ring-buffer tail view"
```

---

### Task 4: ManagedProcess — spawn, grace, crash, stop escalation

**Files:**
- Create: `sheppy/daemon/process.py`
- Test: `tests/daemon/test_process.py`

**Interfaces:**
- Consumes: `NodeLog` (Task 3), `Config` (Task 2).
- Produces: state constants `LAUNCHING, RUNNING, STOPPING, CRASHED, STOPPED` (the strings from Global Constraints) and

  ```python
  class ManagedProcess:
      def __init__(self, spec: dict, cfg: Config, log: NodeLog,
                   on_state) -> None: ...   # on_state: callable(ManagedProcess)
      spec: dict; state: str; pid: int | None
      started_at: float | None; exit_code: int | None   # negative = -signal
      async def start(self) -> None
      async def stop(self) -> None          # full escalation, returns when dead
      async def wait(self) -> None          # until the child has exited
  ```

  Behavior contract: `start` spawns `spec["argv"]` in its own session with stdout/stderr on the `NodeLog` run fd and env additions `PYTHONUNBUFFERED=1`, `RCUTILS_LOGGING_BUFFERED_STREAM=0` (+ `RLIMIT_CORE` unlimited if `cfg.coredumps`). State goes `launching`, then `running` if the child survives `cfg.launch_grace`. Exit without a stop request ⇒ `crashed`; after a stop request ⇒ `stopped`. `stop` signals the **process group**: SIGINT, SIGTERM after `stop_grace`, SIGKILL after `kill_grace`. Every transition calls `on_state(self)` and the final one happens after `log.read_new()` (dying words are in the ring).

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_process.py
import asyncio
import os
import sys

import pytest

from sheppy.daemon.config import Config
from sheppy.daemon.logs import NodeLog
from sheppy.daemon import process as pr


def make_cfg(tmp_path, **kw):
    kw.setdefault("launch_grace", 0.2)
    kw.setdefault("stop_grace", 0.3)
    kw.setdefault("kill_grace", 0.3)
    return Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"), **kw)


def make_mp(tmp_path, code, **cfg_kw):
    cfg = make_cfg(tmp_path, **cfg_kw)
    log = NodeLog(cfg.log_dir, "n", cfg.ring_lines, cfg.keep_runs)
    states = []
    mp = pr.ManagedProcess(
        {"node": "n", "alt_id": "a", "argv": [sys.executable, "-c", code],
         "params": {}},
        cfg, log, on_state=lambda m: states.append(m.state))
    return mp, states, log


async def wait_for(cond, timeout=5.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def test_survives_grace_becomes_running_then_stops_clean(tmp_path):
    mp, states, _ = make_mp(tmp_path, "import time; time.sleep(30)")
    await mp.start()
    assert mp.state == pr.LAUNCHING and mp.pid
    await wait_for(lambda: mp.state == pr.RUNNING)
    await mp.stop()
    assert mp.state == pr.STOPPED          # stop requested ⇒ not a crash
    assert states == [pr.LAUNCHING, pr.RUNNING, pr.STOPPING, pr.STOPPED]


async def test_instant_failure_is_crashed_with_exit_code(tmp_path):
    mp, _, _ = make_mp(tmp_path, "raise SystemExit(3)")
    await mp.start()
    await mp.wait()
    assert mp.state == pr.CRASHED and mp.exit_code == 3


async def test_late_crash_after_running(tmp_path):
    mp, states, _ = make_mp(
        tmp_path, "import time; time.sleep(0.5); raise SystemExit(2)",
        launch_grace=0.1)
    await mp.start()
    await mp.wait()
    assert states == [pr.LAUNCHING, pr.RUNNING, pr.CRASHED]
    assert mp.exit_code == 2


async def test_sigint_ignorer_is_escalated(tmp_path):
    code = ("import signal, time\n"
            "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "time.sleep(30)\n")
    mp, _, _ = make_mp(tmp_path, code)
    await mp.start()
    await wait_for(lambda: mp.state == pr.RUNNING)
    await mp.stop()                        # SIGINT ignored → SIGTERM lands
    assert mp.state == pr.STOPPED


async def test_dying_words_reach_the_ring(tmp_path):
    mp, _, log = make_mp(tmp_path,
                         "print('goodbye cruel world'); raise SystemExit(1)")
    await mp.start()
    await mp.wait()
    assert "goodbye cruel world" in log.tail()


async def test_process_group_kills_grandchildren(tmp_path):
    code = ("import subprocess, sys\n"
            "p = subprocess.Popen(['sleep', '30'])\n"
            "print(p.pid, flush=True)\n"
            "p.wait()\n")
    mp, _, log = make_mp(tmp_path, code)
    await mp.start()
    await wait_for(lambda: log.read_new() is not None and log.tail())
    grandchild = int(log.tail()[0])
    await mp.stop()
    await asyncio.sleep(0.1)               # give the kernel a beat to reap
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_process.py -v`
Expected: FAIL — `ImportError` (no `sheppy.daemon.process`)

- [ ] **Step 3: Implement**

```python
# sheppy/daemon/process.py
"""One supervised child process: spawn, launch grace, crash detection,
SIGINT→SIGTERM→SIGKILL escalation. stdlib only."""
import asyncio
import os
import resource
import signal
import time

LAUNCHING = "launching"
RUNNING = "running"
STOPPING = "stopping"
CRASHED = "crashed"
STOPPED = "stopped"

_CHILD_ENV = {
    # A log file is not a tty: without these, stdio full-buffers and a
    # crashed node's last lines would be stuck in a userspace buffer.
    "PYTHONUNBUFFERED": "1",
    "RCUTILS_LOGGING_BUFFERED_STREAM": "0",
}


def _unlimited_core() -> None:
    resource.setrlimit(resource.RLIMIT_CORE,
                       (resource.RLIM_INFINITY, resource.RLIM_INFINITY))


class ManagedProcess:
    def __init__(self, spec: dict, cfg, log, on_state) -> None:
        self.spec = spec
        self.state = STOPPED
        self.pid: "int | None" = None
        self.started_at: "float | None" = None
        self.exit_code: "int | None" = None
        self._cfg = cfg
        self.log = log
        self._on_state = on_state
        self._stop_requested = False
        self._exited = asyncio.Event()

    def _set(self, state: str) -> None:
        self.state = state
        self._on_state(self)

    async def start(self) -> None:
        fd = self.log.open_run()
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.spec["argv"],
                stdout=fd, stderr=fd, stdin=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                env={**os.environ, **_CHILD_ENV},
                preexec_fn=_unlimited_core if self._cfg.coredumps else None)
        finally:
            os.close(fd)                   # the child holds its own copy
        self.pid = proc.pid
        self.started_at = time.time()
        self._stop_requested = False
        self._exited = asyncio.Event()
        self.exit_code = None
        self._set(LAUNCHING)
        asyncio.ensure_future(self._watch(proc))

    async def _watch(self, proc) -> None:
        try:
            rc = await asyncio.wait_for(
                asyncio.shield(proc.wait()), self._cfg.launch_grace)
        except asyncio.TimeoutError:
            if not self._stop_requested:
                self._set(RUNNING)
            rc = await proc.wait()
        self.exit_code = rc
        self.log.read_new()                # capture dying words in the ring
        self._exited.set()
        self._set(STOPPED if self._stop_requested else CRASHED)

    async def stop(self) -> None:
        if self.pid is None or self._exited.is_set():
            return
        self._stop_requested = True
        self._set(STOPPING)
        escalation = ((signal.SIGINT, self._cfg.stop_grace),
                      (signal.SIGTERM, self._cfg.kill_grace))
        for sig, grace in escalation:
            self._signal_group(sig)
            if await self._exited_within(grace):
                return
        self._signal_group(signal.SIGKILL)
        await self._exited.wait()

    async def wait(self) -> None:
        await self._exited.wait()

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(self.pid, sig)       # pgid == pid (new session)
        except ProcessLookupError:
            pass

    async def _exited_within(self, grace: float) -> bool:
        try:
            await asyncio.wait_for(asyncio.shield(self._exited.wait()), grace)
            return True
        except asyncio.TimeoutError:
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_process.py -v`
Expected: 6 passed. If `test_process_group_kills_grandchildren` flakes on the 0.1 s reap window, poll `os.kill(grandchild, 0)` inside `wait_for` instead of sleeping once — do not lengthen sleeps.

- [ ] **Step 5: Commit**

```bash
git add sheppy/daemon/process.py tests/daemon/test_process.py
git commit -m "feat(daemon): ManagedProcess spawn/grace/crash/stop-escalation"
```

---

### Task 5: ProcessTable, state file, re-adoption

**Files:**
- Modify: `sheppy/daemon/process.py` (extract base class, add `AdoptedProcess`)
- Create: `sheppy/daemon/table.py`
- Test: `tests/daemon/test_table.py`

**Interfaces:**
- Consumes: `ManagedProcess` + state constants (Task 4), `NodeLog` (Task 3), `Config`/`state_path` (Task 2).
- Produces:

  ```python
  class ProcessTable:
      def __init__(self, cfg: Config, on_event) -> None: ...
          # on_event: callable(node: str, payload: dict) — fired on every
          # state transition (server broadcasts these verbatim)
      async def launch(self, spec: dict) -> None   # stops a different running
          # process of the same node first (invariant: ≤1 per node)
      async def stop(self, node: str) -> None      # KeyError if unknown node
      async def restart(self, node: str) -> None   # relaunch the same spec
      async def stop_all(self) -> None
      def status(self) -> dict[str, dict]          # node -> payload
      def logs(self, node: str, n: int) -> list[str]   # KeyError if unknown
      def adopt_from_state(self) -> list[str]      # re-adopt live pids; returns nodes
      def entry(self, node: str)                   # the process object (for tests)
  ```

  Payload shape (everything the TUI/CLI needs; `exit_code` may be a negative signal number, and is always `None` for adopted processes): `{"node", "state", "pid", "exit_code", "started_at", "adopted", "spec"}`.

  State file `<home>/sheppyd.state.json` (atomic `tmp+rename`): `{"nodes": {node: {"spec", "pid", "started_at", "proc_start"}}}` for **live** entries only; `proc_start` is `/proc/<pid>/stat` field 22 (start ticks) so a recycled pid is never adopted.

  In `process.py`: the stop/escalation/wait machinery moves to a base class `Supervised` (fields `pid, state, exit_code, started_at, spec, log`; methods `stop, wait, _set, _signal_group, _exited_within`) — `ManagedProcess(Supervised)` keeps `start`/`_watch` unchanged; new `AdoptedProcess(Supervised)` re-owns a previous daemon's child via `os.pidfd_open` + `loop.add_reader` (event-driven exit detection with no polling; we are not the parent, so `exit_code` stays `None`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_table.py
import asyncio
import json
import sys

import pytest

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config, state_path
from sheppy.daemon.table import ProcessTable

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]
CRASH = [sys.executable, "-c", "raise SystemExit(7)"]


def make_table(tmp_path, events=None):
    cfg = Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"),
                 launch_grace=0.1, stop_grace=0.3, kill_grace=0.3)
    sink = events if events is not None else []
    return ProcessTable(cfg, on_event=lambda n, p: sink.append((n, p))), cfg


def spec(node, argv=SLEEP, alt="a"):
    return {"node": node, "alt_id": alt, "argv": argv, "params": {}}


async def wait_state(table, node, state, timeout=5.0):
    async def poll():
        while table.status().get(node, {}).get("state") != state:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def test_launch_two_nodes_and_status(tmp_path):
    table, _ = make_table(tmp_path)
    await table.launch(spec("camera"))
    await table.launch(spec("lidar"))
    await wait_state(table, "camera", pr.RUNNING)
    await wait_state(table, "lidar", pr.RUNNING)
    st = table.status()
    assert st["camera"]["pid"] and st["camera"]["spec"]["alt_id"] == "a"
    await table.stop_all()


async def test_relaunch_same_node_replaces(tmp_path):
    table, _ = make_table(tmp_path)
    await table.launch(spec("camera", alt="real"))
    await wait_state(table, "camera", pr.RUNNING)
    old_pid = table.status()["camera"]["pid"]
    await table.launch(spec("camera", alt="mock"))
    await wait_state(table, "camera", pr.RUNNING)
    st = table.status()["camera"]
    assert st["spec"]["alt_id"] == "mock" and st["pid"] != old_pid
    await table.stop_all()


async def test_crash_is_retained_with_exit_code(tmp_path):
    table, _ = make_table(tmp_path)
    await table.launch(spec("flaky", CRASH))
    await wait_state(table, "flaky", pr.CRASHED)
    assert table.status()["flaky"]["exit_code"] == 7


async def test_restart_relaunches_same_spec(tmp_path):
    table, _ = make_table(tmp_path)
    await table.launch(spec("flaky", CRASH))
    await wait_state(table, "flaky", pr.CRASHED)
    await table.restart("flaky")
    await wait_state(table, "flaky", pr.CRASHED)   # crashes again — same spec
    assert table.status()["flaky"]["spec"]["argv"] == CRASH


async def test_unknown_node_raises(tmp_path):
    table, _ = make_table(tmp_path)
    with pytest.raises(KeyError):
        await table.stop("ghost")
    with pytest.raises(KeyError):
        table.logs("ghost", 10)


async def test_state_file_tracks_live_entries(tmp_path):
    table, cfg = make_table(tmp_path)
    await table.launch(spec("camera"))
    await wait_state(table, "camera", pr.RUNNING)
    data = json.loads(open(state_path(cfg.home)).read())
    assert "camera" in data["nodes"]
    assert data["nodes"]["camera"]["proc_start"] > 0
    await table.stop("camera")
    data = json.loads(open(state_path(cfg.home)).read())
    assert data["nodes"] == {}


async def test_readoption_controls_previous_daemons_child(tmp_path):
    table_a, cfg = make_table(tmp_path)
    await table_a.launch(spec("camera"))
    await wait_state(table_a, "camera", pr.RUNNING)
    pid = table_a.status()["camera"]["pid"]
    # "daemon dies": table_a is dropped without stopping the child
    table_b, _ = make_table(tmp_path)
    assert table_b.adopt_from_state() == ["camera"]
    st = table_b.status()["camera"]
    assert st["pid"] == pid and st["adopted"] is True
    assert st["state"] == pr.RUNNING
    await table_b.stop("camera")            # really kills the orphan
    assert table_b.status()["camera"]["state"] == pr.STOPPED
    assert table_b.status()["camera"]["exit_code"] is None  # not our child


async def test_adoption_skips_dead_and_recycled_pids(tmp_path):
    _, cfg = make_table(tmp_path)
    import os
    os.makedirs(cfg.home, exist_ok=True)
    with open(state_path(cfg.home), "w") as f:
        json.dump({"nodes": {"ghost": {
            "spec": spec("ghost"), "pid": 2 ** 22 - 1,
            "started_at": 0.0, "proc_start": 1}}}, f)
    table_b, _ = make_table(tmp_path)
    assert table_b.adopt_from_state() == []
    assert table_b.status() == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_table.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy.daemon.table'`

- [ ] **Step 3: Refactor `process.py` — extract `Supervised`, add `AdoptedProcess`**

Move `stop`, `wait`, `_set`, `_signal_group`, `_exited_within` (verbatim, from Task 4's `ManagedProcess`) into a new base class; `ManagedProcess` keeps only `__init__`, `start`, `_watch`. Then add the adopted variant:

```python
# sheppy/daemon/process.py — new/changed parts only; moved methods unchanged
class Supervised:
    """Common supervision surface: state, stop escalation, exit event."""

    def __init__(self, spec: dict, cfg, log, on_state) -> None:
        self.spec = spec
        self.state = STOPPED
        self.pid: "int | None" = None
        self.started_at: "float | None" = None
        self.exit_code: "int | None" = None
        self._cfg = cfg
        self.log = log
        self._on_state = on_state
        self._stop_requested = False
        self._exited = asyncio.Event()

    # stop / wait / _set / _signal_group / _exited_within — moved verbatim


class ManagedProcess(Supervised):
    # start / _watch — unchanged from Task 4
    ...


class AdoptedProcess(Supervised):
    """A previous daemon's child, re-owned via pidfd. Not our child: exit
    codes are unknowable (None); exit is observed event-driven through the
    pidfd becoming readable — no polling."""

    def __init__(self, spec: dict, cfg, log, on_state,
                 pid: int, started_at: float) -> None:
        super().__init__(spec, cfg, log, on_state)
        self.pid = pid
        self.started_at = started_at
        self.adopted = True
        self._pidfd = os.pidfd_open(pid)
        asyncio.get_running_loop().add_reader(self._pidfd, self._pidfd_ready)
        self.state = RUNNING           # it survived at least one daemon

    def _pidfd_ready(self) -> None:
        loop = asyncio.get_running_loop()
        loop.remove_reader(self._pidfd)
        os.close(self._pidfd)
        self.log.read_new()
        self._exited.set()
        self._set(STOPPED if self._stop_requested else CRASHED)
```

Also add `self.adopted = False` to `Supervised.__init__` (before `AdoptedProcess` overrides it) so every payload can carry it.

- [ ] **Step 4: Implement the table**

```python
# sheppy/daemon/table.py
"""The daemon's heart: node -> supervised process, mirrored to a state
file so a restarted daemon re-adopts still-live children. stdlib only."""
import json
import os

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config, state_path
from sheppy.daemon.logs import NodeLog


def _proc_start_ticks(pid: int) -> "int | None":
    """Field 22 of /proc/<pid>/stat — guards against recycled pids."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read()
        return int(data.rsplit(b")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


class ProcessTable:
    def __init__(self, cfg: Config, on_event) -> None:
        self._cfg = cfg
        self._on_event = on_event
        self._entries: dict = {}

    # ---- operations -------------------------------------------------------
    async def launch(self, spec: dict) -> None:
        node = spec["node"]
        old = self._entries.get(node)
        if old is not None and not old._exited.is_set() \
                and old.state != pr.STOPPED:
            await old.stop()
        log = NodeLog(self._cfg.log_dir, node,
                      self._cfg.ring_lines, self._cfg.keep_runs)
        proc = pr.ManagedProcess(spec, self._cfg, log, self._on_state)
        self._entries[node] = proc
        await proc.start()

    async def stop(self, node: str) -> None:
        await self._entries[node].stop()

    async def restart(self, node: str) -> None:
        entry = self._entries[node]
        await entry.stop()
        await self.launch(entry.spec)

    async def stop_all(self) -> None:
        for node in list(self._entries):
            await self.stop(node)

    # ---- views ------------------------------------------------------------
    def status(self) -> dict:
        return {n: self._payload(e) for n, e in self._entries.items()}

    def logs(self, node: str, n: int) -> list[str]:
        entry = self._entries[node]
        entry.log.read_new()
        return entry.log.tail(n)

    def entry(self, node: str):
        return self._entries[node]

    # ---- persistence ------------------------------------------------------
    def adopt_from_state(self) -> list[str]:
        try:
            with open(state_path(self._cfg.home)) as f:
                nodes = json.load(f).get("nodes", {})
        except (OSError, json.JSONDecodeError):
            return []
        adopted = []
        for node, rec in nodes.items():
            if _proc_start_ticks(rec["pid"]) != rec["proc_start"]:
                continue                       # dead, or a recycled pid
            log = NodeLog(self._cfg.log_dir, node,
                          self._cfg.ring_lines, self._cfg.keep_runs)
            log.attach_latest()
            self._entries[node] = pr.AdoptedProcess(
                rec["spec"], self._cfg, log, self._on_state,
                pid=rec["pid"], started_at=rec["started_at"])
            adopted.append(node)
        self._persist()
        return adopted

    def _on_state(self, proc) -> None:
        self._persist()
        self._on_event(proc.spec["node"], self._payload(proc))

    def _payload(self, e) -> dict:
        return {"node": e.spec["node"], "state": e.state, "pid": e.pid,
                "exit_code": e.exit_code, "started_at": e.started_at,
                "adopted": getattr(e, "adopted", False), "spec": e.spec}

    def _persist(self) -> None:
        live = {}
        for node, e in self._entries.items():
            if e.pid is None or e._exited.is_set():
                continue
            if e.state in (pr.STOPPED, pr.CRASHED):
                continue
            live[node] = {"spec": e.spec, "pid": e.pid,
                          "started_at": e.started_at,
                          "proc_start": _proc_start_ticks(e.pid)}
        os.makedirs(self._cfg.home, exist_ok=True)
        path = state_path(self._cfg.home)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"nodes": live}, f)
        os.replace(tmp, path)                  # atomic on POSIX
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/daemon/test_table.py tests/daemon/test_process.py -v`
Expected: all pass (Task 4's suite proves the `Supervised` extraction changed nothing).

- [ ] **Step 6: Commit**

```bash
git add sheppy/daemon/process.py sheppy/daemon/table.py tests/daemon/test_table.py
git commit -m "feat(daemon): ProcessTable with state file and pidfd re-adoption"
```

---

### Task 6: /proc usage sampling

**Files:**
- Create: `sheppy/daemon/usage.py`
- Test: `tests/daemon/test_usage.py`

**Interfaces:**
- Consumes: nothing (pure /proc reads).
- Produces: `sample(pgids: dict[str, int], prev: dict) -> tuple[dict, dict]` — `pgids` maps node → process-group id; returns `({node: {"cpu_pct": float, "rss_mb": float}}, new_prev)`. CPU% is computed from tick deltas against `prev` (an opaque dict threaded between calls; first call yields `0.0`). Whole process **groups** are summed, so a `ros2 launch` tree is one number. Nodes whose group has vanished are omitted.

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_usage.py
import subprocess
import sys
import time

from sheppy.daemon.usage import sample


def spawn(code):
    return subprocess.Popen([sys.executable, "-c", code],
                            start_new_session=True)   # pgid == pid


def test_rss_is_positive_for_live_group():
    child = spawn("import time; time.sleep(30)")
    try:
        usage, prev = sample({"n": child.pid}, {})
        assert usage["n"]["rss_mb"] > 0
        assert usage["n"]["cpu_pct"] == 0.0            # first sample
        assert prev["n"]
    finally:
        child.kill(); child.wait()


def test_busy_group_shows_cpu_between_samples():
    child = spawn("while True: pass")
    try:
        _, prev = sample({"n": child.pid}, {})
        time.sleep(0.3)
        usage, _ = sample({"n": child.pid}, prev)
        assert usage["n"]["cpu_pct"] > 20
    finally:
        child.kill(); child.wait()


def test_group_sums_children():
    code = ("import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c',"
            " 'import time; time.sleep(30)'])\n"
            "time.sleep(30)\n")
    child = spawn(code)
    try:
        time.sleep(0.5)                                # let the child fork
        solo = spawn("import time; time.sleep(30)")
        usage, _ = sample({"pair": child.pid, "solo": solo.pid}, {})
        assert usage["pair"]["rss_mb"] > usage["solo"]["rss_mb"]
        solo.kill(); solo.wait()
    finally:
        import os, signal
        os.killpg(child.pid, signal.SIGKILL); child.wait()


def test_dead_group_is_omitted():
    child = spawn("pass")
    child.wait()
    usage, prev = sample({"gone": child.pid}, {})
    assert usage == {} and prev == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_usage.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# sheppy/daemon/usage.py
"""CPU%% and RSS per process group, from /proc. stdlib only.

Called only while a client is subscribed — sampling is the single
periodic cost sheppyd ever incurs, and it's off when nobody watches."""
import os
import time

_CLK = os.sysconf("SC_CLK_TCK")
_PAGE = os.sysconf("SC_PAGESIZE")


def _scan() -> dict:
    """pgid -> [cpu_ticks_total, rss_pages_total] over all live processes."""
    by_pgid: dict = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", "rb") as f:
                after = f.read().rsplit(b")", 1)[1].split()
            pgrp = int(after[2])               # stat field 5
            ticks = int(after[11]) + int(after[12])   # utime + stime
            with open(f"/proc/{entry}/statm", "rb") as f:
                rss_pages = int(f.read().split()[1])
        except (OSError, ValueError, IndexError):
            continue                           # process vanished mid-read
        acc = by_pgid.setdefault(pgrp, [0, 0])
        acc[0] += ticks
        acc[1] += rss_pages
    return by_pgid


def sample(pgids: dict, prev: dict) -> "tuple[dict, dict]":
    by_pgid = _scan()
    now = time.monotonic()
    usage: dict = {}
    new_prev: dict = {}
    for node, pgid in pgids.items():
        if pgid not in by_pgid:
            continue
        ticks, pages = by_pgid[pgid]
        cpu = 0.0
        if node in prev:
            prev_ticks, prev_now = prev[node]
            dt = now - prev_now
            if dt > 0:
                cpu = max(0.0, (ticks - prev_ticks) / _CLK / dt * 100)
        new_prev[node] = (ticks, now)
        usage[node] = {"cpu_pct": round(cpu, 1),
                       "rss_mb": round(pages * _PAGE / 1048576, 1)}
    return usage, new_prev
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_usage.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sheppy/daemon/usage.py tests/daemon/test_usage.py
git commit -m "feat(daemon): per-process-group CPU/RSS sampling from /proc"
```

---

### Task 7: Socket server and `sheppyd` entry point

**Files:**
- Create: `sheppy/daemon/server.py`, `sheppy/daemon/__main__.py`
- Modify: `pyproject.toml` (add `sheppyd = "sheppy.daemon.__main__:main"` to `[project.scripts]`)
- Test: `tests/daemon/test_server.py`

**Interfaces:**
- Consumes: `ProcessTable` (5), `usage.sample` (6), `protocol` (1), `config` (2).
- Produces:

  ```python
  class Server:
      def __init__(self, cfg: Config) -> None
      table: ProcessTable
      async def start(self) -> None          # bind socket (0600), begin serving
      async def wait_shutdown(self) -> None  # returns after a shutdown op
      async def close(self) -> None          # close socket; children untouched
  ```

  Wire behavior: on connect the server sends `{"event":"hello","sheppyd":"0.1","protocol":1}`. Requests `{"id", "op", ...}` get `{"id", "ok": true, ...}` or `{"id", "ok": false, "error": "..."}`. Ops: `launch(spec)`, `stop(node)`, `restart(node)`, `status()` → `{"nodes": {...}}` with usage merged in, `logs(node, n)` → `{"lines": [...]}`, `subscribe()`, `shutdown`. Subscribed connections receive `{"event":"status", ...payload, "usage": {...}|null}` on every transition, plus refreshed payloads on each usage tick. The usage task exists **only while subscribers exist**. Malformed lines, unknown ops, unknown nodes, and handler exceptions produce error replies — never a daemon death.

  `main(argv) -> int` in `__main__.py`: create home (0700), load config (warnings → daemon log), take the `fcntl` lock (exit 1 with a stderr message if another sheppyd holds it), remove a stale socket file, adopt from state, install SIGTERM/SIGINT → shutdown, serve. On shutdown the daemon exits **without stopping children** (spec §6).

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_server.py
import asyncio
import json
import os
import sys

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config, socket_path
from sheppy.daemon.protocol import Decoder, encode
from sheppy.daemon.server import Server

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]
CRASH = [sys.executable, "-c", "raise SystemExit(9)"]


def spec(node, argv=SLEEP):
    return {"node": node, "alt_id": "a", "argv": argv, "params": {}}


class Wire:
    """Minimal test client: request/response by id + captured events."""

    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.decoder = Decoder()
        self.events: list = []
        self.replies: dict = {}
        self._next_id = 0

    @classmethod
    async def connect(cls, home):
        reader, writer = await asyncio.open_unix_connection(socket_path(home))
        wire = cls(reader, writer)
        hello = await wire._read_one()
        assert hello["event"] == "hello" and hello["protocol"] == 1
        return wire

    async def _read_one(self):
        while True:
            msgs = self.decoder.feed(await self.reader.read(65536))
            if msgs:
                self._sort(msgs[1:])
                return msgs[0]

    def _sort(self, msgs):
        for m in msgs:
            if "event" in m:
                self.events.append(m)
            else:
                self.replies[m["id"]] = m

    async def request(self, op, **kw):
        self._next_id += 1
        rid = self._next_id
        self.writer.write(encode({"id": rid, "op": op, **kw}))
        await self.writer.drain()
        while rid not in self.replies:
            msg = await self._read_one()
            self._sort([msg])
        return self.replies.pop(rid)

    async def wait_event(self, pred, timeout=5.0):
        async def poll():
            while True:
                for e in self.events:
                    if pred(e):
                        return e
                self._sort([await self._read_one()])
        return await asyncio.wait_for(poll(), timeout)


async def make_server(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    cfg = Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"),
                 launch_grace=0.1, stop_grace=0.3, kill_grace=0.3,
                 usage_interval=0.1)
    server = Server(cfg)
    await server.start()
    return server


async def test_launch_status_stop_roundtrip(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    wire = await Wire.connect(str(tmp_path))
    assert (await wire.request("launch", spec=spec("camera")))["ok"]
    reply = await wire.request("status")
    assert reply["nodes"]["camera"]["state"] in (pr.LAUNCHING, pr.RUNNING)
    assert (await wire.request("stop", node="camera"))["ok"]
    reply = await wire.request("status")
    assert reply["nodes"]["camera"]["state"] == pr.STOPPED
    await server.close()


async def test_subscriber_sees_crash_event_with_usage_field(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    watcher = await Wire.connect(str(tmp_path))
    assert (await watcher.request("subscribe"))["ok"]
    actor = await Wire.connect(str(tmp_path))
    await actor.request("launch", spec=spec("flaky", CRASH))
    crash = await watcher.wait_event(
        lambda e: e.get("node") == "flaky" and e["state"] == pr.CRASHED)
    assert crash["exit_code"] == 9 and "usage" in crash
    await server.close()


async def test_malformed_unknown_op_unknown_node_never_kill_daemon(
        tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    wire = await Wire.connect(str(tmp_path))
    wire.writer.write(b"{broken\n")
    await wire.writer.drain()
    err = await wire._read_one()
    assert err["ok"] is False
    reply = await wire.request("frobnicate")
    assert reply["ok"] is False and "unknown op" in reply["error"]
    reply = await wire.request("stop", node="ghost")
    assert reply["ok"] is False and "ghost" in reply["error"]
    assert (await wire.request("status"))["ok"]      # still alive
    await server.close()


async def test_launch_rejects_bad_spec(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    wire = await Wire.connect(str(tmp_path))
    reply = await wire.request("launch", spec={"node": "x"})   # no argv
    assert reply["ok"] is False
    await server.close()


async def test_logs_op_returns_tail(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    wire = await Wire.connect(str(tmp_path))
    await wire.request("launch", spec=spec(
        "talker", [sys.executable, "-c",
                   "print('hi there'); import time; time.sleep(30)"]))
    await asyncio.sleep(0.3)
    reply = await wire.request("logs", node="talker", n=10)
    assert "hi there" in reply["lines"]
    await wire.request("stop", node="talker")
    await server.close()


async def test_shutdown_leaves_children_running(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    wire = await Wire.connect(str(tmp_path))
    await wire.request("launch", spec=spec("camera"))
    pid = (await wire.request("status"))["nodes"]["camera"]["pid"]
    assert (await wire.request("shutdown"))["ok"]
    await asyncio.wait_for(server.wait_shutdown(), 2)
    await server.close()
    os.kill(pid, 0)                       # child survived the daemon
    import signal
    os.killpg(pid, signal.SIGKILL)        # cleanup


async def test_socket_has_owner_only_perms(tmp_path, monkeypatch):
    server = await make_server(tmp_path, monkeypatch)
    mode = os.stat(socket_path(str(tmp_path))).st_mode & 0o777
    assert mode == 0o600
    await server.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy.daemon.server'`

- [ ] **Step 3: Implement the server**

```python
# sheppy/daemon/server.py
"""sheppyd's socket front-end: NDJSON request dispatch + event push.
stdlib only. A bad request can never take the daemon down."""
import asyncio
import os

from sheppy.daemon import usage as usage_mod
from sheppy.daemon.config import Config, socket_path
from sheppy.daemon.protocol import Decoder, encode
from sheppy.daemon.table import ProcessTable

VERSION = "0.1"


class Server:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self.table = ProcessTable(cfg, on_event=self._broadcast_status)
        self._subscribers: set = set()
        self._usage: dict = {}
        self._usage_prev: dict = {}
        self._usage_task: "asyncio.Task | None" = None
        self._server = None
        self._shutdown = asyncio.Event()

    # ---- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        path = socket_path(self._cfg.home)
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        if os.path.exists(path):
            os.unlink(path)               # stale — the flock is the authority
        self._server = await asyncio.start_unix_server(self._client, path)
        os.chmod(path, 0o600)

    async def wait_shutdown(self) -> None:
        await self._shutdown.wait()

    async def close(self) -> None:
        if self._usage_task:
            self._usage_task.cancel()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    # ---- connections -------------------------------------------------------
    async def _client(self, reader, writer) -> None:
        writer.write(encode(
            {"event": "hello", "sheppyd": VERSION, "protocol": 1}))
        decoder = Decoder()
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                for msg in decoder.feed(data):
                    await self._handle(msg, writer)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._subscribers.discard(writer)
            self._maybe_stop_usage()
            writer.close()

    async def _handle(self, msg: dict, writer) -> None:
        rid = msg.get("id")
        if "malformed" in msg:
            writer.write(encode({"id": rid, "ok": False,
                                 "error": "malformed JSON line"}))
            return
        try:
            reply = await self._dispatch(msg, writer)
        except KeyError as e:
            reply = {"ok": False, "error": f"unknown node {e.args[0]!r}"}
        except Exception as e:            # never die on a request
            reply = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        writer.write(encode({"id": rid, **reply}))

    async def _dispatch(self, msg: dict, writer) -> dict:
        op = msg.get("op")
        if op == "launch":
            spec = msg.get("spec") or {}
            argv = spec.get("argv")
            if not spec.get("node") or not isinstance(argv, list) or not argv:
                return {"ok": False,
                        "error": "spec requires 'node' and non-empty 'argv'"}
            await self.table.launch(spec)
            return {"ok": True}
        if op == "stop":
            await self.table.stop(msg["node"])
            return {"ok": True}
        if op == "restart":
            await self.table.restart(msg["node"])
            return {"ok": True}
        if op == "status":
            return {"ok": True, "nodes": self._status_with_usage()}
        if op == "logs":
            lines = self.table.logs(msg["node"], int(msg.get("n", 100)))
            return {"ok": True, "lines": lines}
        if op == "subscribe":
            self._subscribers.add(writer)
            self._ensure_usage_task()
            return {"ok": True}
        if op == "shutdown":
            self._shutdown.set()
            return {"ok": True}
        return {"ok": False, "error": f"unknown op {op!r}"}

    # ---- events + usage ------------------------------------------------------
    def _status_with_usage(self) -> dict:
        nodes = self.table.status()
        for node, payload in nodes.items():
            payload["usage"] = self._usage.get(node)
        return nodes

    def _broadcast_status(self, node: str, payload: dict) -> None:
        self._send_all({"event": "status", **payload,
                        "usage": self._usage.get(node)})

    def _send_all(self, msg: dict) -> None:
        data = encode(msg)
        for writer in list(self._subscribers):
            try:
                writer.write(data)
            except Exception:
                self._subscribers.discard(writer)

    def _ensure_usage_task(self) -> None:
        if self._usage_task is None or self._usage_task.done():
            self._usage_task = asyncio.ensure_future(self._usage_loop())

    def _maybe_stop_usage(self) -> None:
        if not self._subscribers and self._usage_task:
            self._usage_task.cancel()
            self._usage_task = None
            self._usage = {}
            self._usage_prev = {}

    async def _usage_loop(self) -> None:
        # Exists only while subscribers exist — sheppyd's sole periodic work.
        while self._subscribers:
            pgids = {n: p["pid"] for n, p in self.table.status().items()
                     if p["pid"] and p["state"] in ("launching", "running",
                                                    "stopping")}
            self._usage, self._usage_prev = usage_mod.sample(
                pgids, self._usage_prev)
            for node, payload in self._status_with_usage().items():
                if node in self._usage:
                    self._send_all({"event": "status", **payload})
            await asyncio.sleep(self._cfg.usage_interval)
```

- [ ] **Step 4: Implement the entry point**

```python
# sheppy/daemon/__main__.py
"""sheppyd: take the single-instance lock, adopt survivors, serve."""
import asyncio
import fcntl
import os
import signal
import sys
import time

from sheppy.daemon.config import (
    daemon_log_path, load_config, lock_path, sheppy_home,
)
from sheppy.daemon.server import Server


def _log(cfg, text: str) -> None:
    os.makedirs(cfg.log_dir, exist_ok=True)
    with open(daemon_log_path(cfg), "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")


async def _amain(cfg, warnings) -> None:
    server = Server(cfg)
    adopted = server.table.adopt_from_state()
    await server.start()
    for w in warnings:
        _log(cfg, f"config: {w}")
    _log(cfg, f"started (adopted: {', '.join(adopted) or 'none'})")
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, server._shutdown.set)
    await server.wait_shutdown()
    await server.close()
    _log(cfg, "shut down (children left running)")


def main(argv: "list[str] | None" = None) -> int:
    home = sheppy_home()
    os.makedirs(home, mode=0o700, exist_ok=True)
    cfg, warnings = load_config(home)
    lock = open(lock_path(home), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("sheppyd: already running", file=sys.stderr)
        return 1
    asyncio.run(_amain(cfg, warnings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

And in `pyproject.toml`:

```toml
[project.scripts]
sheppy = "sheppy.cli:main"
sheppyd = "sheppy.daemon.__main__:main"
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/daemon/ -v`
Expected: all daemon tests pass.

- [ ] **Step 6: Commit**

```bash
git add sheppy/daemon/server.py sheppy/daemon/__main__.py pyproject.toml tests/daemon/test_server.py
git commit -m "feat(daemon): NDJSON socket server and sheppyd entry point"
```

---

### Task 8: DaemonClient with auto-spawn

**Files:**
- Create: `sheppy/daemon/client.py`
- Test: `tests/daemon/test_client.py`

**Interfaces:**
- Consumes: `protocol`, `config` (socket path), a real `sheppyd` via `python -m sheppy.daemon`.
- Produces:

  ```python
  class DaemonError(Exception): ...

  class DaemonClient:
      def __init__(self, home: str | None = None) -> None
      connected: bool
      async def connect(self, spawn: bool = True) -> bool
          # False if no daemon and spawn=False (or spawn failed within ~3 s)
      async def request(self, op: str, **kw) -> dict      # DaemonError if not connected
      def on_event(self, callback) -> None                # callback(event: dict)
      async def subscribe(self) -> dict                   # sends the subscribe op
      async def close(self) -> None
  ```

  `connect(spawn=True)` with no live socket detach-spawns `[sys.executable, "-m", "sheppy.daemon"]` (`start_new_session=True`, stdio → DEVNULL — the daemon writes its own log) and retries the socket every 50 ms for 3 s. The env (including `SHEPPY_HOME`) is inherited, which is exactly how tests isolate the spawned daemon. A background pump task reads the socket: replies resolve pending request futures by id; events go to the `on_event` callback. On EOF, `connected` flips False and pending requests get `DaemonError`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_client.py
import asyncio
import os
import sys

import pytest

from sheppy.daemon.client import DaemonClient, DaemonError
from sheppy.daemon.config import socket_path

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]


def spec(node, argv=SLEEP):
    return {"node": node, "alt_id": "a", "argv": argv, "params": {}}


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    c = DaemonClient(str(tmp_path))
    assert await c.connect(spawn=True) is True          # auto-spawns sheppyd
    yield c
    # teardown: stop everything, then stop the daemon itself
    if not c.connected:
        c = DaemonClient(str(tmp_path))
        if not await c.connect(spawn=False):
            return
    nodes = (await c.request("status"))["nodes"]
    for node in nodes:
        await c.request("stop", node=node)
    await c.request("shutdown")
    await c.close()


async def test_autospawn_creates_daemon_and_socket(client, tmp_path):
    assert os.path.exists(socket_path(str(tmp_path)))
    assert (await client.request("status"))["ok"]


async def test_second_client_connects_without_spawning(client, tmp_path):
    other = DaemonClient(str(tmp_path))
    assert await other.connect(spawn=False) is True
    assert (await other.request("status"))["ok"]
    await other.close()


async def test_launch_and_stop_through_client(client):
    assert (await client.request("launch", spec=spec("camera")))["ok"]
    nodes = (await client.request("status"))["nodes"]
    assert nodes["camera"]["state"] in ("launching", "running")
    assert (await client.request("stop", node="camera"))["ok"]


async def test_events_reach_callback(client):
    events: list = []
    client.on_event(events.append)
    await client.subscribe()
    await client.request(
        "launch", spec=spec("flaky", [sys.executable, "-c",
                                      "raise SystemExit(5)"]))
    async def crashed():
        while not any(e.get("node") == "flaky" and e["state"] == "crashed"
                      for e in events):
            await asyncio.sleep(0.02)
    await asyncio.wait_for(crashed(), 5)


async def test_connect_without_spawn_returns_false(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    c = DaemonClient(str(tmp_path))
    assert await c.connect(spawn=False) is False
    with pytest.raises(DaemonError):
        await c.request("status")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# sheppy/daemon/client.py
"""Async client for sheppyd, shared by the CLI and the TUI. Auto-spawns
the daemon on demand (user decision: zero-setup operation)."""
import asyncio
import os
import subprocess
import sys

from sheppy.daemon.config import sheppy_home, socket_path
from sheppy.daemon.protocol import Decoder, encode


class DaemonError(Exception):
    pass


def spawn_daemon() -> None:
    subprocess.Popen(
        [sys.executable, "-m", "sheppy.daemon"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True)


class DaemonClient:
    def __init__(self, home: "str | None" = None) -> None:
        self._home = home or sheppy_home()
        self.connected = False
        self._writer = None
        self._pending: dict = {}
        self._next_id = 0
        self._callbacks: list = []
        self._pump_task = None

    async def connect(self, spawn: bool = True) -> bool:
        reader = writer = None
        deadline = asyncio.get_running_loop().time() + 3.0
        spawned = False
        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(
                    socket_path(self._home))
                break
            except (OSError, ValueError):
                if not spawn:
                    return False
                if not spawned:
                    spawn_daemon()
                    spawned = True
                if asyncio.get_running_loop().time() > deadline:
                    return False
                await asyncio.sleep(0.05)
        self._writer = writer
        self.connected = True
        self._pump_task = asyncio.ensure_future(self._pump(reader))
        return True

    async def request(self, op: str, **kw) -> dict:
        if not self.connected:
            raise DaemonError("not connected to sheppyd")
        self._next_id += 1
        rid = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[rid] = future
        self._writer.write(encode({"id": rid, "op": op, **kw}))
        await self._writer.drain()
        return await future

    def on_event(self, callback) -> None:
        self._callbacks.append(callback)

    async def subscribe(self) -> dict:
        return await self.request("subscribe")

    async def close(self) -> None:
        self.connected = False
        if self._pump_task:
            self._pump_task.cancel()
        if self._writer:
            self._writer.close()

    async def _pump(self, reader) -> None:
        decoder = Decoder()
        while True:
            data = await reader.read(65536)
            if not data:
                break
            for msg in decoder.feed(data):
                if "event" in msg:
                    if msg["event"] != "hello":
                        for cb in self._callbacks:
                            cb(msg)
                elif msg.get("id") in self._pending:
                    self._pending.pop(msg["id"]).set_result(msg)
        self.connected = False
        for future in self._pending.values():
            if not future.done():
                future.set_exception(DaemonError("sheppyd connection lost"))
        self._pending.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_client.py -v`
Expected: 5 passed. These spawn a real detached `sheppyd`; the fixture teardown must leave no daemon behind (verify with `pgrep -f sheppy.daemon` afterwards if in doubt).

- [ ] **Step 5: Commit**

```bash
git add sheppy/daemon/client.py tests/daemon/test_client.py
git commit -m "feat(daemon): async DaemonClient with auto-spawn"
```

---

### Task 9: LaunchSpec resolver and converge diff

**Files:**
- Create: `sheppy/launch/__init__.py`, `sheppy/launch/resolve.py`
- Test: `tests/launch/test_resolve.py` (create `tests/launch/__init__.py` empty)

**Interfaces:**
- Consumes: `Manifest, Node, Alternative, Machine` from `sheppy.manifest` (fields as in `sheppy/manifest/models.py`).
- Produces (in `sheppy/launch/resolve.py`, re-exported from `sheppy/launch/__init__.py`):

  ```python
  @dataclass(frozen=True)
  class LaunchSpec:
      node: str; alt_id: str; argv: tuple; params: dict
      def to_wire(self) -> dict     # JSON-ready {"node","alt_id","argv":list,"params"}

  def resolve(manifest: Manifest, node_name: str, alt: Alternative,
              params: dict) -> tuple[LaunchSpec, list[str]]
      # warnings: e.g. params on a process-kind alternative (warned-and-ignored)

  def diff(desired: dict[str, LaunchSpec],
           actual: dict[str, dict]) -> list[tuple[str, str]]
      # actions in execution order: [("stop", node)...], then [("restart", node)...],
      # then [("start", node)...]. `actual` is the daemon status map ALREADY
      # FILTERED by the caller to manifest-known nodes (orphan policy lives
      # with the caller — user decision: converge never touches orphans).
  ```

  Resolution rules (spec §4): every manifest-derived string is `shlex.quote`d; command = `exec ros2 run <pkg> <exe> --ros-args -p k:=v…` / `exec ros2 launch <pkg> <file> k:=v…` / `<command>` verbatim (no exec — pipelines allowed; the process group covers the tree). If the alternative's `machine` resolves to a `Machine` with `ros_setup`, prefix `source <ros_setup> && `. Final argv: `("bash", "-c", command)`. Param values format as `json.dumps(v)` for bool/int/float (bools become `true`/`false`, which is what ros2 expects) and raw `str(v)` for strings, then the whole `k:=v` token is quoted. `diff` rules: a node is *alive* if its state is `launching` or `running`; alive + same `argv` ⇒ untouched; alive + different `argv` ⇒ restart; not alive (absent, crashed, stopped, stopping) but desired ⇒ start; alive but not in `desired` ⇒ stop.

- [ ] **Step 1: Write the failing tests**

```python
# tests/launch/test_resolve.py
from sheppy.launch.resolve import LaunchSpec, diff, resolve
from sheppy.manifest import Alternative, Machine, Manifest, Node


def manifest(machines=(), nodes=()):
    return Manifest(machines=list(machines), nodes=list(nodes))


ROBOT = Machine(name="robot", host="10.0.0.2", user="ros",
                ros_setup="/opt/ros/humble/setup.bash")


def cmd(spec):
    assert spec.argv[0] == "bash" and spec.argv[1] == "-c"
    return spec.argv[2]


def test_executable_kind_with_params_and_setup():
    alt = Alternative(id="real", kind="executable", machine="robot",
                      package="cam_pkg", executable="cam_node")
    spec, warnings = resolve(manifest([ROBOT]), "camera", alt,
                             {"fps": 30, "pointcloud.enable": True})
    assert warnings == []
    text = cmd(spec)
    assert text.startswith("source /opt/ros/humble/setup.bash && ")
    assert "exec ros2 run cam_pkg cam_node --ros-args" in text
    assert "-p 'fps:=30'" in text and "-p 'pointcloud.enable:=true'" in text
    assert spec.to_wire() == {"node": "camera", "alt_id": "real",
                              "argv": list(spec.argv),
                              "params": {"fps": 30,
                                         "pointcloud.enable": True}}


def test_launch_file_kind_arguments():
    alt = Alternative(id="rs", kind="launch_file", package="realsense2_camera",
                      launch_file="rs_launch.py")
    spec, _ = resolve(manifest(), "camera", alt, {"depth": "on it"})
    text = cmd(spec)
    assert "exec ros2 launch realsense2_camera rs_launch.py" in text
    assert "'depth:=on it'" in text          # value with a space is quoted
    assert "source" not in text              # no machine ⇒ no setup prefix


def test_process_kind_verbatim_and_params_warn():
    alt = Alternative(id="gui", kind="process",
                      command="rviz2 -d cfg.rviz | tee /tmp/log")
    spec, warnings = resolve(manifest(), "viz", alt, {"x": 1})
    assert cmd(spec) == "rviz2 -d cfg.rviz | tee /tmp/log"   # no exec, no -p
    assert any("ignored" in w for w in warnings)


def test_quoting_hostile_names():
    alt = Alternative(id="odd", kind="executable",
                      package="pkg; rm -rf /", executable="exe")
    spec, _ = resolve(manifest(), "n", alt, {})
    assert "'pkg; rm -rf /'" in cmd(spec)


def make_spec(node, alt="a", argv=("bash", "-c", "x")):
    return LaunchSpec(node=node, alt_id=alt, argv=tuple(argv), params={})


def actual(node, state, argv=("bash", "-c", "x")):
    return {"node": node, "state": state,
            "spec": {"node": node, "alt_id": "a", "argv": list(argv),
                     "params": {}}}


def test_diff_truth_table():
    desired = {"a": make_spec("a"), "b": make_spec("b"),
               "c": make_spec("c", argv=("bash", "-c", "new"))}
    live = {"b": actual("b", "running"),                  # matches → untouched
            "c": actual("c", "running"),                  # differs → restart
            "d": actual("d", "running"),                  # undesired → stop
            "e": actual("e", "crashed")}                  # dead, undesired → nothing
    actions = diff(desired, live)
    assert actions == [("stop", "d"), ("restart", "c"), ("start", "a")]


def test_diff_crashed_desired_node_restarts_via_start():
    desired = {"a": make_spec("a")}
    assert diff(desired, {"a": actual("a", "crashed")}) == [("start", "a")]


def test_diff_empty_when_converged():
    desired = {"a": make_spec("a")}
    assert diff(desired, {"a": actual("a", "running")}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/launch/test_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# sheppy/launch/__init__.py
from sheppy.launch.resolve import LaunchSpec, diff, resolve

__all__ = ["LaunchSpec", "diff", "resolve"]
```

```python
# sheppy/launch/resolve.py
"""Manifest alternative -> final LaunchSpec argv, and the converge diff.
Pure functions: the daemon never sees a manifest; this is the smart half
of dumb-daemon/smart-client."""
import json
import shlex
from dataclasses import dataclass

from sheppy.manifest import Alternative, Manifest


@dataclass(frozen=True)
class LaunchSpec:
    node: str
    alt_id: str
    argv: tuple
    params: dict

    def to_wire(self) -> dict:
        return {"node": self.node, "alt_id": self.alt_id,
                "argv": list(self.argv), "params": dict(self.params)}


def _value(v) -> str:
    # bools/numbers as JSON (true/false is what ros2 parses); strings raw
    return json.dumps(v) if isinstance(v, (bool, int, float)) else str(v)


def resolve(manifest: Manifest, node_name: str, alt: Alternative,
            params: dict) -> "tuple[LaunchSpec, list[str]]":
    warnings: list[str] = []
    q = shlex.quote
    if alt.kind == "executable":
        cmd = f"exec ros2 run {q(alt.package or '')} {q(alt.executable or '')}"
        if params:
            tokens = " ".join(
                f"-p {q(f'{k}:={_value(v)}')}" for k, v in params.items())
            cmd += f" --ros-args {tokens}"
    elif alt.kind == "launch_file":
        cmd = f"exec ros2 launch {q(alt.package or '')} {q(alt.launch_file or '')}"
        for k, v in params.items():
            cmd += f" {q(f'{k}:={_value(v)}')}"
    else:  # "process": verbatim; exec would break pipelines, and the
        # process group covers the whole tree anyway
        cmd = alt.command or ""
        if params:
            warnings.append(
                f"'{node_name}': params on process-kind alternative "
                f"'{alt.id}' are ignored in phase 2b")
    setup = _ros_setup(manifest, alt.machine)
    if setup:
        cmd = f"source {q(setup)} && {cmd}"
    return (LaunchSpec(node=node_name, alt_id=alt.id,
                       argv=("bash", "-c", cmd), params=dict(params)),
            warnings)


def _ros_setup(manifest: Manifest, machine_name: "str | None") -> "str | None":
    if machine_name is None:
        return None
    for m in manifest.machines:
        if m.name == machine_name:
            return m.ros_setup
    return None


_ALIVE = ("launching", "running")


def diff(desired: dict, actual: dict) -> "list[tuple[str, str]]":
    stops, restarts, starts = [], [], []
    for node, payload in actual.items():
        if payload["state"] in _ALIVE and node not in desired:
            stops.append(("stop", node))
    for node, spec in desired.items():
        payload = actual.get(node)
        alive = payload is not None and payload["state"] in _ALIVE
        if not alive:
            starts.append(("start", node))
        elif payload["spec"]["argv"] != list(spec.argv):
            restarts.append(("restart", node))
    return stops + restarts + starts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/launch/test_resolve.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add sheppy/launch tests/launch
git commit -m "feat(launch): LaunchSpec resolver and converge diff"
```

---

### Task 10: CLI verbs — `up`, `down`, `status`, `logs`, `woof`, `daemon`

**Files:**
- Modify: `sheppy/cli.py` (whole-file rewrite shown below; TUI path behavior unchanged)
- Test: `tests/cli/test_verbs.py` (create `tests/cli/__init__.py` empty)

**Interfaces:**
- Consumes: `DaemonClient` (8), `resolve`/`diff` (9), `load_manifest`, `ProfileStore`/`ProfileState`/`reconcile` (existing).
- Produces: `sheppy <manifest>` still opens the TUI (default `system.yaml`); new headless verbs per spec §8. `up` prints the action list, converges, waits until nothing is `launching`/`stopping`, prints final per-node states, exit 1 if anything crashed. Converge-restart executes as a `launch` op (the daemon's `launch` already stops a different running process of the same node — the daemon's `restart` op would re-run the *old* spec). Textual is only imported on the TUI path — the verbs must work on a machine where the TUI never runs.

- [ ] **Step 1: Write the failing tests**

```python
# tests/cli/test_verbs.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cli/test_verbs.py -v`
Expected: FAIL — argparse/`main` doesn't know the verbs yet.

- [ ] **Step 3: Rewrite `sheppy/cli.py`**

```python
# sheppy/cli.py
"""Entry point: `sheppy <manifest>` opens the TUI; verbs (up/down/status/
logs/woof/daemon) are headless and never import textual."""
import argparse
import asyncio
import os
import sys
import time

COMMANDS = {"up", "down", "status", "logs", "woof", "daemon"}


# ---- TUI path (unchanged behavior) ----------------------------------------
def build_app(argv: list[str]):
    from sheppy.manifest import load_manifest
    from sheppy.tui.app import SheppyApp
    path = argv[0] if argv else "system.yaml"
    result = load_manifest(path)
    profiles_dir = os.path.join(os.path.dirname(os.path.abspath(path)),
                                "profiles")
    return SheppyApp(result, path=path, profiles_dir=profiles_dir)


def main(argv: "list[str] | None" = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        return _run_verb(argv)
    app = build_app(argv)
    app.run()
    return 0


# ---- headless verbs --------------------------------------------------------
def _run_verb(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="sheppy")
    sub = p.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up", help="converge to a profile")
    up.add_argument("profile")
    up.add_argument("--manifest", default="system.yaml")
    sub.add_parser("down", help="stop everything, then stop sheppyd")
    sub.add_parser("status", help="one line per supervised node")
    lg = sub.add_parser("logs", help="tail a node's output")
    lg.add_argument("node")
    lg.add_argument("-n", type=int, default=50)
    wf = sub.add_parser("woof", help="restart a node")
    wf.add_argument("node")
    dm = sub.add_parser("daemon", help="daemon lifecycle")
    dm.add_argument("action", choices=["status", "stop"])
    args = p.parse_args(argv)
    return asyncio.run(_dispatch(args))


async def _dispatch(args) -> int:
    if args.cmd == "up":
        return await _up(args)
    from sheppy.daemon.client import DaemonClient
    client = DaemonClient()
    if not await client.connect(spawn=False):
        print("sheppyd: not running")
        return 0 if args.cmd in ("down", "status", "daemon") else 1
    try:
        if args.cmd == "down":
            nodes = (await client.request("status"))["nodes"]
            for node in sorted(nodes):
                await client.request("stop", node=node)
                print(f"stopped {node}")
            await client.request("shutdown")
            print("sheppyd stopped")
            return 0
        if args.cmd == "status":
            _print_status((await client.request("status"))["nodes"])
            return 0
        if args.cmd == "logs":
            reply = await client.request("logs", node=args.node, n=args.n)
            if not reply["ok"]:
                print(reply["error"], file=sys.stderr)
                return 1
            for line in reply["lines"]:
                print(line)
            return 0
        if args.cmd == "woof":
            reply = await client.request("restart", node=args.node)
            if not reply["ok"]:
                print(reply["error"], file=sys.stderr)
                return 1
            print(f"woof! restarted {args.node} 🐕")
            return 0
        # daemon status|stop
        if args.action == "status":
            nodes = (await client.request("status"))["nodes"]
            print(f"sheppyd: running ({len(nodes)} nodes supervised)")
            return 0
        await client.request("shutdown")
        print("sheppyd stopped (children left running)")
        return 0
    finally:
        await client.close()


def _print_status(nodes: dict) -> None:
    if not nodes:
        print("(nothing supervised)")
        return
    for node, p in sorted(nodes.items()):
        extra = ""
        if p["state"] == "crashed" and p["exit_code"] is not None:
            extra = f" exit={p['exit_code']}"
        elif p["started_at"] and p["state"] == "running":
            extra = f" up {int(time.time() - p['started_at'])}s"
        print(f"{node:<20} {p['state']:<10} "
              f"{p['spec']['alt_id']:<14} pid={p['pid']}{extra}")


async def _up(args) -> int:
    from sheppy.daemon.client import DaemonClient
    from sheppy.launch import diff, resolve
    from sheppy.manifest import load_manifest
    from sheppy.profiles import ProfileState, ProfileStore, reconcile

    result = load_manifest(args.manifest)
    if result.manifest is None:
        for e in result.errors:
            print(f"{e.location}: {e.message}", file=sys.stderr)
        return 1
    for e in result.errors:
        print(f"warning: {e.location}: {e.message}", file=sys.stderr)
    profiles_dir = os.path.join(
        os.path.dirname(os.path.abspath(args.manifest)), "profiles")
    loaded = ProfileStore(profiles_dir).load(args.profile)
    if loaded.profile is None:
        for err in loaded.errors:
            print(err, file=sys.stderr)
        return 1
    rec = reconcile(loaded.profile, result.manifest)
    for w in rec.warnings:
        print(f"warning: {w}", file=sys.stderr)
    state = ProfileState(result.manifest)
    state.apply(rec.selections, rec.overrides, args.profile)

    desired = {}
    for node in result.manifest.nodes:
        alt = state.selected_alt(node.name)
        if alt is None:
            continue
        spec, warns = resolve(result.manifest, node.name, alt,
                              state.effective_params(node.name))
        for w in warns:
            print(f"warning: {w}", file=sys.stderr)
        desired[node.name] = spec

    client = DaemonClient()
    if not await client.connect(spawn=True):
        print("could not start sheppyd", file=sys.stderr)
        return 1
    try:
        nodes = (await client.request("status"))["nodes"]
        actual = {n: p for n, p in nodes.items()
                  if result.manifest.node(n) is not None}   # orphans untouched
        actions = diff(desired, actual)
        if not actions:
            print("already converged")
            return 0
        for verb, node in actions:
            print(f"{verb} {node}")
        for verb, node in actions:
            if verb == "stop":
                await client.request("stop", node=node)
            else:   # start and restart both go through launch: the daemon
                # replaces a live process of the same node with the NEW spec
                await client.request("launch", spec=desired[node].to_wire())
        return await _wait_stable(client, desired)
    finally:
        await client.close()


async def _wait_stable(client, desired: dict, timeout: float = 30.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        nodes = (await client.request("status"))["nodes"]
        states = {n: nodes.get(n, {}).get("state") for n in desired}
        if not any(s in ("launching", "stopping") for s in states.values()):
            for n in sorted(states):
                print(f"{n}: {states[n]}")
            return 1 if "crashed" in states.values() else 0
        await asyncio.sleep(0.2)
    print("timed out waiting for nodes to settle", file=sys.stderr)
    return 1
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/cli/test_verbs.py tests/tui/test_app.py -v`
Expected: CLI tests pass and the TUI app tests still pass (`build_app` behavior unchanged).

- [ ] **Step 5: Commit**

```bash
git add sheppy/cli.py tests/cli
git commit -m "feat(cli): headless verbs — up/down/status/logs/woof/daemon"
```

---

### Task 11: Live status vocabulary + NodeList runtime rendering

**Files:**
- Modify: `sheppy/tui/widgets/status.py`, `sheppy/tui/widgets/node_list.py`
- Modify: `tests/tui/widgets/test_status.py`, `tests/tui/widgets/test_node_list.py`

**Interfaces:**
- Consumes: existing `Status` enum, `NodeList`/`NodeListHeader`.
- Produces:
  - `status.py`: new members `Status.STOPPING` (glyph `◐`, color `yellow`) and `Status.UNKNOWN` (glyph `?`, color `muted` — daemon absent, distinct from stopped); `runtime(state: str | None) -> Status` mapping daemon strings — `running→RUNNING, launching→LAUNCHING, stopping→STOPPING, crashed→CRASHED, stopped→NONE, None→NONE`, anything else → `WARN`. Update the module docstring: these are no longer "reserved".
  - `node_list.py`: `@dataclass RuntimeCell(status: st.Status, drift: bool = False, usage: str = "")` and `NodeList.set_runtime(cells: dict[str, RuntimeCell])`. **Meaning change:** `.col-status` now shows *runtime* state (+ a yellow `Δ` drift marker); selection is expressed only by `.col-alt` (green `-set`), so `set_selection` no longer touches `.col-status`. New `.col-usage` column (width 9, header `USAGE`); `.col-status` widens to 5 (`NodeListHeader` widths stay in sync — scoped-CSS rule). Initial rows render `Status.UNKNOWN` until the app pushes real cells.

- [ ] **Step 1: Extend the widget tests** (adjust the existing `set_selection` glyph assertion — it moves to `.col-alt` only — and add:)

```python
# tests/tui/widgets/test_node_list.py — additions
from sheppy.tui.widgets.node_list import NodeList, RuntimeCell
from sheppy.tui.widgets import status as st


async def test_set_runtime_renders_glyph_drift_and_usage():
    app = _Harness(NODES)               # existing two-node harness
    async with app.run_test():
        nl = app.query_one(NodeList)
        nl.set_runtime({
            "camera": RuntimeCell(st.Status.RUNNING, drift=True,
                                  usage="3% 142M"),
            "lidar": RuntimeCell(st.Status.CRASHED),
        })
        row0 = str(app.query_one("#node-0 .col-status").content)
        assert st.glyph(st.Status.RUNNING) in row0 and "Δ" in row0
        assert "3% 142M" in str(app.query_one("#node-0 .col-usage").content)
        row1 = str(app.query_one("#node-1 .col-status").content)
        assert st.glyph(st.Status.CRASHED) in row1 and "Δ" not in row1


async def test_rows_start_unknown_until_runtime_arrives():
    app = _Harness(NODES)
    async with app.run_test():
        assert "?" in str(app.query_one("#node-0 .col-status").content)


async def test_set_selection_marks_alt_not_status():
    app = _Harness(NODES)
    async with app.run_test():
        nl = app.query_one(NodeList)
        nl.set_selection({"camera": "real"})
        alt = app.query_one("#node-0 .col-alt")
        assert str(alt.content) == "real" and alt.has_class("-set")
        assert "?" in str(app.query_one("#node-0 .col-status").content)
```

And in `tests/tui/widgets/test_status.py`:

```python
from sheppy.tui.widgets.status import Status, glyph, runtime


def test_runtime_mapping():
    assert runtime("running") is Status.RUNNING
    assert runtime("launching") is Status.LAUNCHING
    assert runtime("stopping") is Status.STOPPING
    assert runtime("crashed") is Status.CRASHED
    assert runtime("stopped") is Status.NONE
    assert runtime(None) is Status.NONE
    assert runtime("wat") is Status.WARN


def test_new_glyphs():
    assert glyph(Status.STOPPING) == "◐"
    assert glyph(Status.UNKNOWN) == "?"
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest tests/tui/widgets/test_node_list.py tests/tui/widgets/test_status.py -v`

- [ ] **Step 3: Implement**

`status.py` — add members and mapping:

```python
class Status(Enum):
    NONE = "none"          # no runtime state (stopped / not supervised)
    SELECTED = "selected"  # 2a-era: kept for AlternativesPanel radio rows
    RUNNING = "running"
    LAUNCHING = "launching"
    STOPPING = "stopping"
    CRASHED = "crashed"
    WARN = "warn"
    UNKNOWN = "unknown"    # daemon absent — NOT the same as stopped

# _GLYPH additions: STOPPING "◐", UNKNOWN "?"
# _COLOR additions: STOPPING "yellow", UNKNOWN "muted"

_RUNTIME = {"running": Status.RUNNING, "launching": Status.LAUNCHING,
            "stopping": Status.STOPPING, "crashed": Status.CRASHED,
            "stopped": Status.NONE}


def runtime(state: "str | None") -> Status:
    if state is None:
        return Status.NONE
    return _RUNTIME.get(state, Status.WARN)
```

`node_list.py` — `RuntimeCell`, new column, runtime-first status cell:

```python
from dataclasses import dataclass


@dataclass
class RuntimeCell:
    status: st.Status
    drift: bool = False
    usage: str = ""


def _status_markup(cell: RuntimeCell) -> str:
    text = c(st.color_key(cell.status), st.glyph(cell.status))
    if cell.drift:
        text += c("yellow", " Δ")
    return text
```

In `NodeList.DEFAULT_CSS` and `NodeListHeader.DEFAULT_CSS`: `.col-status { width: 5; }`, add `.col-usage { width: 9; color: $text-muted; }` (header label `USAGE`). `_row()` initial status cell: `_status_markup(RuntimeCell(st.Status.UNKNOWN))`, and a `Label("", classes="col-usage", markup=False)` after `.col-host`. `set_selection`: delete the two `.col-status` update lines (alt/host updates stay). Add:

```python
    def set_runtime(self, cells: "dict[str, RuntimeCell]") -> None:
        for i, node in enumerate(self._manifest_nodes):
            cell = cells.get(node.name, RuntimeCell(st.Status.UNKNOWN))
            row = self.query_one(f"#node-{i}")
            row.query_one(".col-status", Label).update(_status_markup(cell))
            row.query_one(".col-usage", Label).update(cell.usage)
```

Also bump `#nodes-pane` `max-width` from 58 to 66 in `sheppy/tui/app.py` CSS so the new column fits at the mockup proportions.

- [ ] **Step 4: Run the full TUI suite**

Run: `uv run pytest tests/tui -v`
Expected: all pass (including migrated assertions).

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/widgets/status.py sheppy/tui/widgets/node_list.py sheppy/tui/app.py tests/tui/widgets/test_status.py tests/tui/widgets/test_node_list.py
git commit -m "feat(tui): runtime status vocabulary and live node-row rendering"
```

---

### Task 12: App ↔ daemon wiring — events, Space/x/r, footer/header

**Files:**
- Modify: `sheppy/tui/app.py`, `sheppy/tui/widgets/status_footer.py`, `sheppy/tui/widgets/header_bar.py`
- Create: `tests/tui/_fake_daemon.py`, `tests/tui/test_daemon_wiring.py`, `tests/daemon/test_purity.py`
- Modify: `tests/tui/widgets/test_status_footer.py`, `tests/tui/widgets/test_header_bar.py`

**Interfaces:**
- Consumes: `DaemonClient` surface (Task 8), `resolve` (9), `RuntimeCell`/`set_runtime` (11).
- Produces:
  - `SheppyApp.__init__(..., client=None)` — dependency injection; `None` means a real `DaemonClient()` is built on mount. `app.actual: dict[str, dict]` mirrors daemon payloads; `app.daemon_connected: bool`.
  - Startup connects with `spawn=False` (browsing must not breed daemons); the first launch-ish action calls `_ensure_daemon()` which connects with `spawn=True` (the user's auto-spawn decision).
  - Bindings: `space` converge node, `x` stop node, `r` restart node. Space with a selection resolves and sends `launch`; space on a node with **no** selection stops it if alive (converge-to-nothing) else warns.
  - `StatusFooter.set_daemon(connected: bool, running: int, total: int)` → `sheppyd ● 3/12 running` / `sheppyd ○ offline`. `HeaderBar.update_state(...)` gains optional `running: "int | None" = None`, appended to the source segment as `· ● N running` when not None.
  - `tests/tui/_fake_daemon.py` `FakeDaemonClient` — the standard TUI test double.
  - `tests/daemon/test_purity.py` — the stdlib-only guarantee from Global Constraints.

- [ ] **Step 1: Write the fake and the failing tests**

```python
# tests/tui/_fake_daemon.py
class FakeDaemonClient:
    """Test double matching DaemonClient's surface. Seed `nodes` with
    daemon status payloads; `push()` fires a live event into the app."""

    def __init__(self, nodes: "dict | None" = None, connect_ok: bool = True):
        self.connected = False
        self._ok = connect_ok
        self.nodes = dict(nodes or {})
        self.requests: list = []
        self._callbacks: list = []
        self.spawn_attempts: list = []

    async def connect(self, spawn: bool = True) -> bool:
        self.spawn_attempts.append(spawn)
        self.connected = self._ok
        return self._ok

    def on_event(self, callback) -> None:
        self._callbacks.append(callback)

    async def subscribe(self) -> dict:
        return {"ok": True}

    async def request(self, op: str, **kw) -> dict:
        self.requests.append((op, kw))
        if op == "status":
            return {"ok": True, "nodes": {n: dict(p)
                                          for n, p in self.nodes.items()}}
        return {"ok": True}

    async def close(self) -> None:
        self.connected = False

    def push(self, event: dict) -> None:
        for cb in self._callbacks:
            cb(event)


def payload(node, state, alt="a", argv=None, usage=None, adopted=False):
    return {"event": "status", "node": node, "state": state, "pid": 4242,
            "exit_code": 7 if state == "crashed" else None,
            "started_at": 0.0, "adopted": adopted, "usage": usage,
            "spec": {"node": node, "alt_id": alt,
                     "argv": argv or ["bash", "-c", "x"], "params": {}}}
```

```python
# tests/tui/test_daemon_wiring.py
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
        assert "●" in footer and "1/12" in footer


async def test_offline_daemon_shows_unknown_and_offline_footer():
    app = make_app(FakeDaemonClient(connect_ok=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "?" in str(app.query_one("#node-0 .col-status").content)
        assert "offline" in str(app.query_one("#sf-daemon").content)
        assert app._client.spawn_attempts == [False]   # browsing never spawns


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
        assert spec["argv"][0] == "bash" and "ros2 launch" in spec["argv"][2]


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
```

```python
# tests/daemon/test_purity.py
import subprocess
import sys

CODE = """
import sys
import sheppy.daemon.__main__
import sheppy.daemon.client
import sheppy.daemon.server
import sheppy.launch
bad = {'textual', 'yaml', 'rich'} & {m.split('.')[0] for m in sys.modules}
sys.exit(1 if bad else 0)
"""


def test_daemon_and_launch_import_no_third_party():
    proc = subprocess.run([sys.executable, "-c", CODE])
    assert proc.returncode == 0
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/tui/test_daemon_wiring.py tests/daemon/test_purity.py -v`
Expected: wiring tests FAIL (`client` kwarg unknown); purity may already pass — keep it anyway as the regression guard.

- [ ] **Step 3: Implement the app wiring**

In `sheppy/tui/app.py` (additions; existing handlers unchanged):

```python
from sheppy.launch import resolve
from sheppy.tui.widgets.node_list import NodeList, NodeListHeader, RuntimeCell
from sheppy.tui.widgets import status as st

    BINDINGS = [   # add to the existing list
        ("space", "converge_node", "Apply"),
        ("x", "stop_node", "Stop"),
        ("r", "restart_node", "Restart"),
    ]

    def __init__(self, load_result, path=None, profiles_dir=None,
                 client=None) -> None:
        ...existing body...
        self._client = client
        self.actual: dict = {}
        self.daemon_connected = False

    def on_mount(self) -> None:
        ...existing body...
        self.run_worker(self._daemon_connect(spawn=False), exclusive=False)

    async def _daemon_connect(self, spawn: bool) -> bool:
        if self._client is None:
            from sheppy.daemon.client import DaemonClient
            self._client = DaemonClient()
        if not await self._client.connect(spawn=spawn):
            self._refresh_runtime()
            return False
        self._client.on_event(self._on_daemon_event)
        await self._client.subscribe()
        reply = await self._client.request("status")
        self.actual = reply["nodes"]
        self.daemon_connected = True
        self._refresh_runtime()
        return True

    async def _ensure_daemon(self) -> bool:
        if self.daemon_connected:
            return True
        if not await self._daemon_connect(spawn=True):
            self._append_warnings(["could not start sheppyd"])
            return False
        return True

    def _on_daemon_event(self, event: dict) -> None:
        if event.get("event") != "status":
            return
        self.actual[event["node"]] = event
        self._refresh_runtime()

    # ---- runtime view ------------------------------------------------------
    def _refresh_runtime(self) -> None:
        if not self.manifest:
            return
        cells = {}
        running = 0
        for node in self.manifest.nodes:
            payload = self.actual.get(node.name)
            state = payload["state"] if payload else None
            if state == "running":
                running += 1
            if not self.daemon_connected:
                cells[node.name] = RuntimeCell(st.Status.UNKNOWN)
                continue
            cell = RuntimeCell(
                st.runtime(state), drift=self._drift(node, payload),
                usage=_fmt_usage(payload.get("usage") if payload else None))
            if payload and payload["state"] in ("launching", "running") \
                    and not any(a.id == payload["spec"]["alt_id"]
                                for a in node.alternatives):
                cell.usage = "alt?"      # running an alt this manifest lacks
            cells[node.name] = cell
        try:
            self.query_one(NodeList).set_runtime(cells)
            self.query_one(StatusFooter).set_daemon(
                self.daemon_connected, running, len(self.manifest.nodes))
        except NoMatches:
            pass

    def _drift(self, node, payload) -> bool:
        alive = payload is not None and payload["state"] in ("launching",
                                                             "running")
        alt = self.state.selected_alt(node.name) if self.state else None
        if not alive:
            return alt is not None          # desired but not running
        if alt is None:
            return True                     # running but nothing desired
        spec, _ = resolve(self.manifest, node.name, alt,
                          self.state.effective_params(node.name))
        return payload["spec"]["argv"] != list(spec.argv)

    # ---- daemon actions ----------------------------------------------------
    async def action_converge_node(self) -> None:
        node = self._current_node()
        if node is None or not self.state:
            return
        alt = self.state.selected_alt(node.name)
        payload = self.actual.get(node.name)
        alive = payload and payload["state"] in ("launching", "running")
        if alt is None and not alive:
            self._append_warnings(
                [f"'{node.name}': no alternative selected"])
            return
        if not await self._ensure_daemon():
            return
        if alt is None:                     # converge-to-nothing = stop
            await self._request_safely("stop", node=node.name)
            return
        spec, warns = resolve(self.manifest, node.name, alt,
                              self.state.effective_params(node.name))
        if warns:
            self._append_warnings(warns)
        await self._request_safely("launch", spec=spec.to_wire())

    async def action_stop_node(self) -> None:
        node = self._current_node()
        if node and self.daemon_connected:
            await self._request_safely("stop", node=node.name)

    async def action_restart_node(self) -> None:
        node = self._current_node()
        if node and self.daemon_connected:
            await self._request_safely("restart", node=node.name)

    async def _request_safely(self, op: str, **kw) -> "dict | None":
        from sheppy.daemon.client import DaemonError
        try:
            reply = await self._client.request(op, **kw)
        except DaemonError as e:
            self.daemon_connected = False
            self._append_warnings([str(e)])
            self._refresh_runtime()
            return None
        if not reply.get("ok"):
            self._append_warnings([f"{op}: {reply.get('error')}"])
        return reply


def _fmt_usage(usage: "dict | None") -> str:
    if not usage:
        return ""
    return f"{usage['cpu_pct']:.0f}% {usage['rss_mb']:.0f}M"
```

Import note: `FakeDaemonClient` has no `DaemonError` — `_request_safely` imports the real one, which is fine (the fake never raises it). If `space` turns out to be consumed by `ListView` before the app binding fires, give `NodeList`/`AlternativesPanel` a passthrough binding that calls `self.app.action_converge_node()`.

In `status_footer.py`: add id'd segment update —

```python
    def set_daemon(self, connected: bool, running: int, total: int) -> None:
        if connected:
            text = (f"{c('green', 'sheppyd ●')} "
                    f"{c('fg', f'{running}/{total} running')}")
        else:
            text = c("muted", "sheppyd ○ offline")
        self.query_one("#sf-daemon", Static).update(text)
```

(keep the existing compose-time placeholder as the initial content; drop any "— phase 2b" suffix). Extend the footer `KEYMAP` list with `("␣", "apply"), ("x", "stop"), ("r", "woof"), ("L", "converge"), ("!", "snap")` — this is the standing `Δ → space to apply` hint. In `header_bar.py`: `update_state(..., running=None)` appends `· ● {running} running` (green) to the source segment when `running is not None`; app passes it from `_refresh_runtime` via `_refresh_header` — simplest is: `_refresh_runtime` also calls `_refresh_header()` and `_refresh_header` reads `self.actual` to count. Update the two widget test files for the new signature/content.

- [ ] **Step 4: Run the suites**

Run: `uv run pytest tests/tui tests/daemon/test_purity.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui tests/tui tests/daemon/test_purity.py
git commit -m "feat(tui): live daemon wiring — status events, space/x/r, footer"
```

---

### Task 13: Converge-all overlay (`L`), stop-all (`X`), snapshot (`!`)

**Files:**
- Create: `sheppy/tui/daemon_modals.py`
- Modify: `sheppy/tui/app.py`
- Test: `tests/tui/test_converge.py`

**Interfaces:**
- Consumes: `diff`/`resolve` (9), `_ensure_daemon`/`_request_safely`/`actual` (12), existing `ConfirmModal`, `ProfileState.apply`.
- Produces: `ConvergeModal(actions: list[tuple[str, str]])` — a `ModalScreen[bool]` listing the plan (`stop` red / `restart` yellow / `start` green, one per line), Enter → True, Escape → False. App bindings `L` (converge all), `X` (stop all, incl. orphans, behind `ConfirmModal`), `!` (snapshot). Converge-all **excludes orphans** (user decision); `X` and only `X` includes them. Snapshot: Desired := the running set — selections and param overrides from the actually-launched specs; nodes not alive get cleared; orphans and unknown alt ids are skipped with a visible warning; result is dirty (save-as captures it).

- [ ] **Step 1: Write the failing tests**

```python
# tests/tui/test_converge.py
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
        # ConfirmModal accept — check profile_modals.py for its actual
        # accept key ("enter" vs "y") and use that here
        await pilot.press("enter")
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
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/tui/test_converge.py -v`
Expected: FAIL — no `daemon_modals`, no bindings.

- [ ] **Step 3: Implement the modal**

```python
# sheppy/tui/daemon_modals.py
"""Modals for daemon actions. Presentational; the app executes."""
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from sheppy.tui.widgets.theme import c

_VERB_COLOR = {"stop": "red", "restart": "yellow", "start": "green"}


class ConvergeModal(ModalScreen[bool]):
    BINDINGS = [("enter", "apply", "Apply"), ("escape", "cancel", "Cancel")]

    def __init__(self, actions: "list[tuple[str, str]]") -> None:
        super().__init__()
        self._actions = actions

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(c("fg", f"converge — {len(self._actions)} action(s)"))
            for verb, node in self._actions:
                yield Static(f"{c(_VERB_COLOR[verb], f'{verb:<8}')}"
                             f"{c('fg', node)}")
            yield Static(c("muted", "enter apply · esc cancel"))

    def action_apply(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
```

- [ ] **Step 4: Implement the app actions**

Additions to `sheppy/tui/app.py` (BINDINGS gain `("L", "converge_all", "Converge")`, `("X", "stop_all", "Stop all")`, `("exclamation_mark", "snapshot", "Snapshot")` — verify the `!` key name with `textual keys` if the binding doesn't fire, some Textual versions use the literal `"!"`):

```python
    async def action_converge_all(self) -> None:
        if not self.state or not self.manifest:
            return
        if not await self._ensure_daemon():
            return
        reply = await self._request_safely("status")
        if reply is None:
            return
        self.actual = reply["nodes"]
        desired = {}
        for node in self.manifest.nodes:
            alt = self.state.selected_alt(node.name)
            if alt is None:
                continue
            spec, warns = resolve(self.manifest, node.name, alt,
                                  self.state.effective_params(node.name))
            if warns:
                self._append_warnings(warns)
            desired[node.name] = spec
        known = {n: p for n, p in self.actual.items()
                 if self.manifest.node(n) is not None}    # orphans excluded
        actions = diff(desired, known)
        if not actions:
            self._append_warnings(["already converged"])
            return
        self.push_screen(
            ConvergeModal(actions),
            lambda ok: self.run_worker(self._execute(actions, desired))
            if ok else None)

    async def _execute(self, actions, desired) -> None:
        for verb, node in actions:
            if verb == "stop":
                await self._request_safely("stop", node=node)
            else:
                await self._request_safely(
                    "launch", spec=desired[node].to_wire())

    async def action_stop_all(self) -> None:
        if not self.daemon_connected:
            self._append_warnings(["sheppyd offline — nothing to stop"])
            return
        alive = [n for n, p in self.actual.items()
                 if p["state"] in ("launching", "running")]
        if not alive:
            self._append_warnings(["nothing running"])
            return
        self.push_screen(
            ConfirmModal(f"Stop all {len(alive)} running node(s), "
                         f"including any not in this manifest?"),
            lambda ok: self.run_worker(self._stop_nodes(alive))
            if ok else None)

    async def _stop_nodes(self, nodes: list) -> None:
        for node in nodes:
            await self._request_safely("stop", node=node)

    def action_snapshot(self) -> None:
        if not self.state or not self.manifest:
            return
        if not self.daemon_connected:
            self._append_warnings(["sheppyd offline — nothing to snapshot"])
            return
        selections, overrides, skipped = {}, {}, []
        for name, payload in self.actual.items():
            if payload["state"] not in ("launching", "running"):
                continue
            node = self.manifest.node(name)
            if node is None:
                skipped.append(name)
                continue
            alt = next((a for a in node.alternatives
                        if a.id == payload["spec"]["alt_id"]), None)
            if alt is None:
                skipped.append(f"{name} (unknown alternative)")
                continue
            selections[name] = alt.id
            over = {k: v for k, v in payload["spec"]["params"].items()
                    if k in alt.params and alt.params[k] != v}
            if over:
                overrides[name] = over
        self.state.apply(selections, overrides,
                         self.state.active_profile_name)
        self.state.is_dirty = True
        if skipped:
            self._append_warnings(
                [f"snapshot skipped (not in manifest): {', '.join(skipped)}"])
        self._rebuild_after_apply()
        self._refresh_runtime()
```

Reuse `#dialog` CSS (already styled in app CSS) for the modal container. `import` line gains `from sheppy.launch import diff, resolve` and `from sheppy.tui.daemon_modals import ConvergeModal`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/tui/test_converge.py tests/tui -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add sheppy/tui/daemon_modals.py sheppy/tui/app.py tests/tui/test_converge.py
git commit -m "feat(tui): converge overlay, stop-all, snapshot"
```

---

### Task 14: Live PROCESS tab + orphan rows

**Files:**
- Modify: `sheppy/tui/widgets/detail_tabs.py`, `sheppy/tui/widgets/node_list.py`, `sheppy/tui/widgets/alternatives_panel.py`, `sheppy/tui/app.py`
- Test: `tests/tui/test_process_tab.py`, additions to `tests/tui/widgets/test_node_list.py`

**Interfaces:**
- Consumes: everything from Tasks 11–13.
- Produces:
  - `DetailTabs.show_process(payload: dict | None, lines: list[str], connected: bool)` — offline → muted `sheppyd ○ offline`; `payload=None` → muted `not supervised — space to launch`; else a field grid (state colored via `status.py`, pid, uptime as `MmSSs`, exit code when crashed, cpu/rss) plus the last log lines (muted `last output` header; every line escaped).
  - `NodeList.set_orphans(orphans: list[dict])` — after the manifest rows, a disabled muted divider `─ not in this manifest ─` then one Actual-only row per orphan (runtime glyph, name, alt id from the spec echo, empty usage/host). New message `NodeList.OrphanHighlighted(name: str)`; `NodeHighlighted/NodeSelected` keep firing **only** for manifest rows (`ListView.index` past the manifest rows maps to `_orphan_names[index - len(manifest) - 1]`).
  - `AlternativesPanel.show_note(text: str)` — clears the list and shows one disabled muted line (used for orphan rows).
  - App: tracks the highlighted orphan (`self._current_orphan: str | None`, reset on normal `NodeHighlighted`); `x` works on orphans, `space`/`r` warn `not in this manifest — stop/logs only`; a 1 s `set_interval` (created paused) drives PROCESS-tab refresh and is resumed/paused by `TabbedContent.TabActivated` for `tab-process` — the timer never runs while the tab is hidden. Refresh fetches `logs` (n=15) via `_request_safely` for the current target (node or orphan) and calls `show_process`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tui/test_process_tab.py
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
```

Add to `tests/tui/_fake_daemon.py`: `self.log_lines: list = []` in `__init__`, and in `request()` before the fallback return: `if op == "logs": return {"ok": True, "lines": list(self.log_lines)}`.

Add to `tests/tui/widgets/test_node_list.py`:

```python
async def test_set_orphans_appends_divider_and_rows():
    app = _Harness(NODES)
    async with app.run_test():
        nl = app.query_one(NodeList)
        await nl.set_orphans([{"node": "ghost", "state": "running",
                               "spec": {"alt_id": "old"}}])
        labels = " ".join(str(l.content) for l in app.query("NodeList Label"))
        assert "ghost" in labels and "old" in labels
        await nl.set_orphans([])               # idempotent clear
        labels = " ".join(str(l.content) for l in app.query("NodeList Label"))
        assert "ghost" not in labels
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/tui/test_process_tab.py -v`

- [ ] **Step 3: Implement**

`detail_tabs.py` — add (import `status as st` and `time`):

```python
    def show_process(self, payload: "dict | None", lines: list,
                     connected: bool) -> None:
        try:
            target = self.query_one("#detail-process", Static)
        except NoMatches:
            return
        if not connected:
            target.update(c("muted", "sheppyd ○ offline"))
            return
        if payload is None:
            target.update(c("muted", "not supervised — space to launch"))
            return
        def row(key, value):
            return f"{c('muted', f'{key:<12}')}{value}"
        status = st.runtime(payload["state"])
        out = [row("state", c(st.color_key(status),
                              f"{st.glyph(status)} {payload['state']}"))]
        out.append(row("pid", c("fg", payload["pid"] or "—")))
        if payload["state"] == "running" and payload["started_at"]:
            up = int(time.time() - payload["started_at"])
            out.append(row("uptime", c("fg", f"{up // 60}m{up % 60:02d}s")))
        if payload["exit_code"] is not None:
            out.append(row("exit code", c("red", payload["exit_code"])))
        usage = payload.get("usage")
        if usage:
            out.append(row("usage", c("orange",
                f"{usage['cpu_pct']:.0f}% {usage['rss_mb']:.0f}M")))
        if lines:
            out.append("")
            out.append(c("muted", "last output"))
            out.extend(c("fg", line) for line in lines)
        target.update("\n".join(out))
```

`node_list.py` — orphans (divider + rows carry classes for cleanup; `_orphan_names` drives index mapping):

```python
    class OrphanHighlighted(Message):
        def __init__(self, name: str) -> None:
            self.name = name
            super().__init__()

    def set_orphans(self, orphans: list) -> None:
        for item in list(self.query(".orphan-divider, .orphan-row")):
            item.remove()
        self._orphan_names = [p["node"] for p in orphans]
        if not orphans:
            return
        divider = ListItem(
            Label("─ not in this manifest ─", classes="orphan-label"),
            classes="orphan-divider", disabled=True)
        self.append(divider)
        for i, p in enumerate(orphans):
            cell = RuntimeCell(st.runtime(p["state"]))
            self.append(ListItem(
                Horizontal(
                    Label(_status_markup(cell), classes="col-status"),
                    Label(p["node"], classes="col-name", markup=False),
                    Label(p["spec"]["alt_id"], classes="col-alt",
                          markup=False),
                    Label("—", classes="col-host"),
                    Label("", classes="col-usage"),
                ),
                id=f"orphan-{i}", classes="orphan-row"))
```

`__init__` gains `self._orphan_names: list = []`. Highlight/select mapping:

```python
    def on_list_view_highlighted(self, event) -> None:
        event.stop()
        if self.index is None:
            return
        n = len(self._manifest_nodes)
        if self.index < n:
            self.post_message(self.NodeHighlighted(self.index))
        elif self.index > n:                       # index n is the divider
            self.post_message(self.OrphanHighlighted(
                self._orphan_names[self.index - n - 1]))

    def on_list_view_selected(self, event) -> None:
        event.stop()
        if self.index is not None and self.index < len(self._manifest_nodes):
            self.post_message(self.NodeSelected(self.index))
```

DEFAULT_CSS additions: `NodeList > ListItem.orphan-divider { color: $text-muted; padding: 0 1; }` (`set_orphans` appends are awaitables in Textual — make `set_orphans` `async` and `await self.append(...)` / `item.remove()`; the app calls it from `_refresh_runtime` via `self.run_worker`).

`alternatives_panel.py`:

```python
    async def show_note(self, text: str) -> None:
        await self.clear()
        await self.append(ListItem(
            Label(text, classes="alt-note", markup=False), disabled=True))
```

`app.py`: `self._current_orphan: "str | None" = None`; `on_node_list_node_highlighted` sets it to `None` (first line); new handler:

```python
    async def on_node_list_orphan_highlighted(
            self, event: NodeList.OrphanHighlighted) -> None:
        self._current_orphan = event.name
        try:
            self.query_one("#alts-head", Static).update(
                c("muted", "ALTERNATIVES · not in this manifest"))
        except NoMatches:
            pass
        await self.query_one(AlternativesPanel).show_note(
            "not in this manifest — stop (x) and logs only")
        self._refresh_process_tab()
```

Action changes: `action_stop_node` targets `self._current_orphan or current node name`; `action_converge_node` and `action_restart_node` start with

```python
        if self._current_orphan:
            self._append_warnings(
                [f"'{self._current_orphan}': not in this manifest — "
                 f"stop/logs only"])
            return
```

`_refresh_runtime` ends with `self.run_worker(self.query_one(NodeList).set_orphans([p for n, p in sorted(self.actual.items()) if self.manifest.node(n) is None]), exclusive=False)` (guarded `try/except NoMatches`). PROCESS-tab plumbing:

```python
    # in on_mount:
        self._proc_timer = self.set_interval(
            1.0, self._refresh_process_tab, pause=True)

    def on_tabbed_content_tab_activated(self, event) -> None:
        if getattr(event.pane, "id", None) == "tab-process":
            self._proc_timer.resume()
            self._refresh_process_tab()
        else:
            self._proc_timer.pause()

    def _refresh_process_tab(self) -> None:
        self.run_worker(self._load_process_tab(), exclusive=True,
                        group="proctab")

    async def _load_process_tab(self) -> None:
        name = self._current_orphan or (
            self._current_node().name if self._current_node() else None)
        tabs = self.query_one(DetailTabs)
        if name is None or not self.daemon_connected:
            tabs.show_process(None, [], self.daemon_connected)
            return
        payload = self.actual.get(name)
        lines: list = []
        if payload is not None:
            reply = await self._request_safely("logs", node=name, n=15)
            if reply and reply.get("ok"):
                lines = reply["lines"]
        tabs.show_process(payload, lines, True)
```

- [ ] **Step 4: Run the suites**

Run: `uv run pytest tests/tui -v`
Expected: all pass, including the 2a.5 suites (navigation messages unchanged for manifest rows).

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui tests/tui
git commit -m "feat(tui): live PROCESS tab and orphan rows"
```

---

### Task 15: End-to-end test, demo manifest, README

**Files:**
- Create: `examples/local-demo.yaml`, `tests/test_e2e.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the whole stack. This is the one test that runs the real TUI against a real auto-spawned `sheppyd` — no fakes anywhere.

- [ ] **Step 1: Demo manifest (runs with zero ROS installed)**

```yaml
# examples/local-demo.yaml — sheppyd demo, no ROS required.
machines: []
nodes:
  - name: clock
    description: prints a heartbeat every second
    alternatives:
      - id: ticker
        kind: process
        command: "python3 -u -c 'import time\nwhile True: print(time.strftime(\"%T\")); time.sleep(1)'"
  - name: worker
    description: a well-behaved long-runner
    alternatives:
      - id: steady
        kind: process
        command: "python3 -c 'import time; time.sleep(3600)'"
      - id: flaky
        kind: process
        command: "python3 -c 'import time; time.sleep(3); raise SystemExit(1)'"
```

Sanity-check by hand: `uv run sheppy examples/local-demo.yaml`, select alternatives, `space`, watch glyphs; `uv run sheppy status` from another shell; `uv run sheppy down`.

- [ ] **Step 2: Write the end-to-end test**

```python
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
```

- [ ] **Step 3: Run it**

Run: `uv run pytest tests/test_e2e.py -v`
Expected: 1 passed (allow ~10 s — it spawns a real daemon and real children).

- [ ] **Step 4: Update README.md**

1. Getting-started blockquote: replace the "Launching, the daemon, and introspection arrive in later phases." sentence with "Phase 2b adds `sheppyd`: select, press `space`, and the process is really running — locally, surviving TUI detach."
2. Keys table — add rows:

```markdown
| `Space` | Launch/converge the highlighted node to its selected alternative |
| `x` / `r` | Stop / restart the highlighted node |
| `L` | Converge everything to the current selection (shows a plan first) |
| `X` | Stop all running nodes (confirmation; includes orphans) |
| `!` | Snapshot: copy what's running into the selection (then save-as) |
```

3. New section after "Run the TUI":

```markdown
### Launching for real: `sheppyd`

The first launch action auto-starts `sheppyd`, a tiny supervisor daemon
(stdlib-only, ~zero idle CPU) that owns the child processes — quit the TUI
and everything keeps running. Reconnect and it's all still there; even if
`sheppyd` itself dies, a restarted daemon re-adopts the survivors.

Headless verbs (no TUI needed):

```bash
uv run sheppy up <profile> --manifest system.yaml   # converge to a profile
uv run sheppy status                                # what's running
uv run sheppy logs <node> -n 50                     # tail a node's output
uv run sheppy woof <node>                           # restart it 🐕
uv run sheppy down                                  # stop everything + daemon
```

Node output goes to `~/.sheppy/logs/<node>/<timestamp>.log` (last 5 runs
kept). Optional flat-JSON config at `~/.sheppy/sheppyd.json`:

```json
{"ring_lines": 300, "keep_runs": 5, "coredumps": false,
 "usage_interval": 2.0, "launch_grace": 2.0,
 "stop_grace": 5.0, "kill_grace": 5.0}
```

Try it without ROS: `uv run sheppy examples/local-demo.yaml`.
```

4. Phases table: mark **2b** as `✅ Done`.
5. The cockpit-layout paragraph: delete "Process status … are labeled placeholders that later phases (2b/3/4) fill in" and say process status is live via `sheppyd`; machine connections (phase 3) and the topics live column (phase 4) remain placeholders.

- [ ] **Step 5: Full suite + commit**

Run: `uv run pytest`
Expected: everything green (2a suites + all new daemon/launch/cli/tui suites + e2e).

```bash
git add examples/local-demo.yaml tests/test_e2e.py README.md
git commit -m "feat: end-to-end launch test, no-ROS demo manifest, README for 2b"
```

---

## Manual verification (success criteria from spec §12)

After all tasks, on a real machine:

- `uv run sheppy examples/local-demo.yaml` → select, `space`, glyphs go ◐→●; quit; `uv run sheppy status` still shows it; relaunch TUI → state re-appears.
- `ps -o rss= -p $(pgrep -f sheppy.daemon)` < 35000 (KB) with nodes running.
- `pidstat -p $(pgrep -f sheppy.daemon) 5 3` shows ~0% CPU with the TUI closed (no subscribers).
- `kill -9 $(pgrep -f sheppy.daemon)`; children survive (`pgrep -f time.sleep`); next `sheppy status` auto-spawns a daemon that re-adopts them.

## Notes for implementers

- **Deliberate deviation from spec §7:** the client does not run a
  background reconnect loop. On connection loss the TUI flips to offline
  (grey `?` column) and the next launch-ish action reconnects via
  `_ensure_daemon(spawn=True)`. Simpler, and the TUI never blocks; revisit
  only if it proves annoying in practice.
- **Timing in tests:** always poll with a deadline (`wait_for`-style helpers shown in Tasks 4/5/7), never bare `sleep` as the assertion. Graces in test configs are 0.1–0.3 s.
- **Textual 8.2.7 gotchas** (hard-won in 2a.5): widget `DEFAULT_CSS` is scoped to the declaring widget; theme must be registered in `App.__init__`; `Static.content` for text; ListView `clear`/`append` are awaitables; `app.screen` (not `query_one`) for modals; `theme.c()` escapes internally — don't double-escape.
- **Cleanup discipline:** any test that spawns a real daemon must tear it down (`down`/`shutdown`) even on failure — a leaked sheppyd on a dev box will confuse the next test run via `SHEPPY_HOME` differences.

