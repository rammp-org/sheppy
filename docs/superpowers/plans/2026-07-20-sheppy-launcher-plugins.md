# Sheppy Launcher Plugins + Docker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standardized, developer-extensible launcher-plugin surface that every launch type is expressed through, with Docker as the first non-trivial plugin.

**Architecture:** Three layers. Client-side **launcher plugins** (one per `kind`) turn an alternative + effective params into a **`LaunchDescriptor`** — pure JSON data. The daemon executes descriptors and never runs third-party code. A descriptor is `inherit` (the started process *is* the unit — today's process behavior) or `detached` (the unit outlives the starter, controlled by `start`/`watch`/`stop`/`logs` commands — Docker, etc.). Existing kinds migrate to launchers; nothing is special-cased.

**Tech Stack:** Python ≥3.10. Client (launchers, registry, resolver, TUI/CLI) may use stdlib + PyYAML + Textual. `sheppy/daemon/` stays **stdlib-only**. Discovery via `importlib.metadata` entry points. pytest + pytest-asyncio (`asyncio_mode="auto"`).

**Spec:** `docs/superpowers/specs/2026-07-20-sheppy-launcher-plugins-design.md`

## Global Constraints

- **Declarative, client-side plugins.** A launcher returns data (a `LaunchDescriptor`); it runs client-side. The daemon never imports a launcher or runs third-party code.
- `sheppy/daemon/` imports **stdlib only** (enforced by `tests/daemon/test_purity.py`). `sheppy/launch/` may import PyYAML but **not** textual. The docker launcher's compose parsing uses PyYAML (client-side).
- Run tests with `uv run pytest`; never bare pytest. **All currently-passing tests must stay green at every task** unless a task explicitly migrates them.
- After editing `pyproject.toml` entry points, run `uv sync` so `importlib.metadata` sees them.
- Daemon node states are exactly `"launching" | "running" | "stopping" | "crashed" | "stopped"`.
- `LaunchDescriptor.supervise` is exactly `"inherit"` or `"detached"`. A `detached` descriptor supplies exactly one of `watch` / `poll`.
- The `stats` command (if present) prints exactly two whitespace-separated numbers: `<cpu_pct> <rss_mb>`. Reformatting a runtime's native output into those two numbers is the launcher's job; the daemon's parser is fixed.
- **Never-crash ethos:** malformed manifests, launcher errors, daemon errors → warnings/status, never exceptions.
- **Behavior preservation:** the three existing kinds must produce byte-identical launch commands after migration; the existing resolver and e2e tests are the net.
- Every manifest-derived string reaching a shell is quoted (reuse `_param_token` / `shlex.quote`; the existing injection tests carry over).
- `SHEPPY_HOME` overrides `~/.sheppy` everywhere (test isolation).
- Match existing style: frozen dataclasses, short focused modules, comments only for non-obvious constraints.

## File Structure

```
sheppy/launch/descriptor.py    LaunchDescriptor: shape, validation, wire       (T1)
sheppy/launch/base.py          Launcher Protocol + LaunchContext               (T2)
sheppy/launch/registry.py      entry-point discovery, kind -> Launcher         (T3)
sheppy/launch/builtins.py      process/executable/launch_file launchers        (T4)
sheppy/launch/resolve.py       resolve() via registry; diff() on descriptors   (T4,T5)
sheppy/launch/docker/__init__.py   DockerLauncher                              (T8)
sheppy/launch/docker/compose.py    compose service -> docker run args          (T8,T9)
sheppy/launch/docker/params.py     effective params -> ROS2 params YAML        (T10)
sheppy/daemon/process.py       + DetachedSupervisor; strategy select           (T5,T6)
sheppy/daemon/table.py         descriptor-aware launch + detached re-adopt      (T5,T7)
sheppy/daemon/server.py        launch validates descriptor; protocol bump      (T5)
docs/launcher-plugins.md       developer plugin guide                          (T12)
examples/docker-demo.yaml      docker manifest for the integration test        (T13)
```

---

### Task 1: `LaunchDescriptor`

**Files:**
- Create: `sheppy/launch/descriptor.py`
- Test: `tests/launch/test_descriptor.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass(frozen=True) LaunchDescriptor` with fields: `supervise: str`, `start: tuple`, `name: str | None = None`, `watch: tuple | None = None`, `poll: tuple | None = None`, `stop: tuple | None = None`, `logs: tuple | None = None`, `stats: tuple | None = None`, `reset: tuple | None = None`, `grace: dict = {}`. Command fields are tuples of str.
  - classmethods `inherit(start) -> LaunchDescriptor` and `detached(name, start, *, watch=None, poll=None, stop=None, logs=None, stats=None, reset=None, grace=None) -> LaunchDescriptor`.
  - `validate(self) -> list[str]` — structural errors (empty = valid).
  - `to_wire(self) -> dict` (lists, drops None/empty) and `from_wire(d: dict) -> LaunchDescriptor`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/launch/test_descriptor.py
import pytest
from sheppy.launch.descriptor import LaunchDescriptor as LD


def test_inherit_roundtrips_and_validates():
    d = LD.inherit(("bash", "-c", "echo hi"))
    assert d.supervise == "inherit" and d.start == ("bash", "-c", "echo hi")
    assert d.validate() == []
    assert d.to_wire() == {"supervise": "inherit",
                           "start": ["bash", "-c", "echo hi"]}
    assert LD.from_wire(d.to_wire()) == d


def test_detached_with_watch_roundtrips():
    d = LD.detached("sheppy-cam",
                    start=("docker", "run", "-d", "--name", "sheppy-cam", "img"),
                    watch=("docker", "wait", "sheppy-cam"),
                    stop=("docker", "stop", "sheppy-cam"),
                    logs=("docker", "logs", "-f", "sheppy-cam"))
    assert d.validate() == []
    assert LD.from_wire(d.to_wire()) == d
    assert d.to_wire()["name"] == "sheppy-cam"


def test_detached_requires_name_and_exit_detection():
    no_name = LD.detached("", start=("x",), watch=("w",))
    assert any("name" in e for e in no_name.validate())
    neither = LD.detached("n", start=("x",))
    assert any("watch" in e and "poll" in e for e in neither.validate())
    both = LD.detached("n", start=("x",), watch=("w",), poll=("p",))
    assert any("watch" in e and "poll" in e for e in both.validate())
    poll_ok = LD.detached("n", start=("x",), poll=("p",))
    assert poll_ok.validate() == []


def test_start_required_and_supervise_valid():
    assert any("start" in e for e in LD.inherit(()).validate())
    bad = LD(supervise="weird", start=("x",))
    assert any("supervise" in e for e in bad.validate())


def test_from_wire_tolerates_lists_and_missing_optionals():
    wire = {"supervise": "detached", "name": "n",
            "start": ["a", "b"], "poll": ["p"]}
    d = LD.from_wire(wire)
    assert d.start == ("a", "b") and d.poll == ("p",) and d.watch is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/launch/test_descriptor.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# sheppy/launch/descriptor.py
"""The one client<->daemon contract: how to start, watch, stop, and read
logs for a supervised unit. Pure, JSON-serializable data."""
from dataclasses import dataclass, field

INHERIT = "inherit"
DETACHED = "detached"
_CMD_FIELDS = ("start", "watch", "poll", "stop", "logs", "stats", "reset")


def _t(v):
    return tuple(v) if v else None


@dataclass(frozen=True)
class LaunchDescriptor:
    supervise: str
    start: tuple
    name: "str | None" = None
    watch: "tuple | None" = None
    poll: "tuple | None" = None
    stop: "tuple | None" = None
    logs: "tuple | None" = None
    stats: "tuple | None" = None
    reset: "tuple | None" = None
    grace: dict = field(default_factory=dict)

    @classmethod
    def inherit(cls, start) -> "LaunchDescriptor":
        return cls(supervise=INHERIT, start=tuple(start))

    @classmethod
    def detached(cls, name, start, *, watch=None, poll=None, stop=None,
                 logs=None, stats=None, reset=None, grace=None):
        return cls(supervise=DETACHED, name=name or None, start=tuple(start),
                   watch=_t(watch), poll=_t(poll), stop=_t(stop),
                   logs=_t(logs), stats=_t(stats), reset=_t(reset),
                   grace=dict(grace or {}))

    def validate(self) -> list:
        errs = []
        if self.supervise not in (INHERIT, DETACHED):
            errs.append(f"supervise must be {INHERIT!r} or {DETACHED!r}, "
                        f"got {self.supervise!r}")
        if not self.start:
            errs.append("descriptor needs a non-empty 'start'")
        if self.supervise == DETACHED:
            if not self.name:
                errs.append("detached descriptor needs a 'name'")
            if bool(self.watch) == bool(self.poll):
                errs.append("detached descriptor needs exactly one of "
                            "'watch' or 'poll'")
        return errs

    def to_wire(self) -> dict:
        out = {"supervise": self.supervise, "start": list(self.start)}
        if self.name:
            out["name"] = self.name
        for f in _CMD_FIELDS:
            if f == "start":
                continue
            v = getattr(self, f)
            if v:
                out[f] = list(v)
        if self.grace:
            out["grace"] = dict(self.grace)
        return out

    @classmethod
    def from_wire(cls, d: dict) -> "LaunchDescriptor":
        return cls(
            supervise=d.get("supervise", ""), start=tuple(d.get("start") or ()),
            name=d.get("name"), watch=_t(d.get("watch")), poll=_t(d.get("poll")),
            stop=_t(d.get("stop")), logs=_t(d.get("logs")),
            stats=_t(d.get("stats")), reset=_t(d.get("reset")),
            grace=dict(d.get("grace") or {}))
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/launch/test_descriptor.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add sheppy/launch/descriptor.py tests/launch/test_descriptor.py
git commit -m "feat(launch): LaunchDescriptor — the client/daemon launch contract"
```

---

### Task 2: `Launcher` contract + `LaunchContext`

**Files:**
- Create: `sheppy/launch/base.py`
- Test: `tests/launch/test_context.py`

**Interfaces:**
- Consumes: `LaunchDescriptor` (T1), `Manifest` from `sheppy.manifest`, `sheppy_home` from `sheppy.daemon.config`.
- Produces:
  - `class Launcher(Protocol)` with `kind: str`, `validate(raw_alt: dict) -> list[str]`, `launch(alt, params, ctx) -> LaunchDescriptor`, `summary(alt) -> list[tuple[str, str]]`.
  - `class LaunchContext` — `__init__(self, node_name, manifest, home=None)`; `node_name: str`, `manifest`; `scratch_dir() -> str` (creates `<home>/scratch/<node>/`, returns it); `write_params_file(params: dict, ros_node_name: str | None = None) -> str` (writes a ROS2 params YAML into the scratch dir, returns its path); `warn(msg: str) -> None` and `warnings` property (accumulates launcher warnings that `resolve()` surfaces).
  - The params YAML shape: `{ros_node_name or "/**": {"ros__parameters": params}}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/launch/test_context.py
import os
import yaml
from sheppy.launch.base import LaunchContext
from sheppy.manifest import Manifest


def ctx(tmp_path, node="camera"):
    return LaunchContext(node, Manifest(machines=[], nodes=[]),
                         home=str(tmp_path))


def test_scratch_dir_is_created_under_home(tmp_path):
    d = ctx(tmp_path).scratch_dir()
    assert os.path.isdir(d) and str(tmp_path) in d and "camera" in d


def test_write_params_file_wildcard(tmp_path):
    path = ctx(tmp_path).write_params_file({"max_range": 5.0, "frame": "cam"})
    data = yaml.safe_load(open(path))
    assert data == {"/**": {"ros__parameters": {"max_range": 5.0,
                                                "frame": "cam"}}}


def test_write_params_file_named_node(tmp_path):
    path = ctx(tmp_path).write_params_file({"x": 1}, ros_node_name="percep")
    data = yaml.safe_load(open(path))
    assert data == {"percep": {"ros__parameters": {"x": 1}}}


def test_write_params_file_overwrites_same_node(tmp_path):
    c = ctx(tmp_path)
    first = c.write_params_file({"x": 1})
    second = c.write_params_file({"x": 2})
    assert first == second                     # stable path per node
    assert yaml.safe_load(open(second))["/**"]["ros__parameters"]["x"] == 2


def test_warnings_accumulate(tmp_path):
    c = ctx(tmp_path)
    assert c.warnings == []
    c.warn("params ignored")
    c.warn("second")
    assert c.warnings == ["params ignored", "second"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/launch/test_context.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# sheppy/launch/base.py
"""The launcher plugin contract and the context that mediates a launcher's
side effects. Launchers are client-side; they return data, never run in
the daemon."""
import os
from typing import Protocol

import yaml

from sheppy.daemon.config import sheppy_home
from sheppy.launch.descriptor import LaunchDescriptor


class LaunchContext:
    def __init__(self, node_name: str, manifest, home: "str | None" = None):
        self.node_name = node_name
        self.manifest = manifest
        self._home = home or sheppy_home()
        self._warnings: list = []

    def warn(self, msg: str) -> None:
        self._warnings.append(msg)

    @property
    def warnings(self) -> list:
        return list(self._warnings)

    def scratch_dir(self) -> str:
        d = os.path.join(self._home, "scratch", self.node_name)
        os.makedirs(d, exist_ok=True)
        return d

    def write_params_file(self, params: dict,
                          ros_node_name: "str | None" = None) -> str:
        key = ros_node_name or "/**"
        path = os.path.join(self.scratch_dir(), "params.yaml")
        with open(path, "w") as f:
            yaml.safe_dump({key: {"ros__parameters": dict(params)}}, f)
        return path


class Launcher(Protocol):
    kind: str

    def validate(self, raw_alt: dict) -> list: ...

    def launch(self, alt, params: dict,
               ctx: LaunchContext) -> LaunchDescriptor: ...

    def summary(self, alt) -> list: ...
```

- [ ] **Step 4: Update the purity test (yaml now legitimately enters `launch/`)**

`base.py` imports PyYAML, so `tests/daemon/test_purity.py`'s current
"`sheppy.launch` imports no yaml" assertion is now wrong. The real guarantee
is that the **daemon** modules stay stdlib-only *and never transitively pull
in `sheppy.launch`* (which would drag yaml in). Rewrite the file:

```python
# tests/daemon/test_purity.py
import subprocess
import sys

# Importing the daemon must pull in NO third-party module and must not drag
# in sheppy.launch (which is allowed to use yaml on the client side).
DAEMON = """
import sys
import sheppy.daemon.__main__
import sheppy.daemon.client
import sheppy.daemon.server
import sheppy.daemon.table
import sheppy.daemon.process
bad = {'textual', 'yaml', 'rich'} & {m.split('.')[0] for m in sys.modules}
assert not bad, f"daemon pulled in {bad}"
assert 'sheppy.launch' not in sys.modules, "daemon must not import sheppy.launch"
"""

# The launch package may use yaml, but must stay UI-free (no textual/rich).
LAUNCH = """
import sys
import sheppy.launch
bad = {'textual', 'rich'} & {m.split('.')[0] for m in sys.modules}
assert not bad, f"launch pulled in {bad}"
"""


def test_daemon_is_stdlib_only():
    assert subprocess.run([sys.executable, "-c", DAEMON]).returncode == 0


def test_launch_is_ui_free():
    assert subprocess.run([sys.executable, "-c", LAUNCH]).returncode == 0
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/launch/test_context.py tests/daemon/test_purity.py -v`
Expected: all passed (4 context + 2 purity).

- [ ] **Step 6: Commit**

```bash
git add sheppy/launch/base.py tests/launch/test_context.py tests/daemon/test_purity.py
git commit -m "feat(launch): Launcher contract and LaunchContext"
```

---

### Task 3: `LauncherRegistry` + entry-point discovery

**Files:**
- Create: `sheppy/launch/registry.py`
- Test: `tests/launch/test_registry.py`

**Interfaces:**
- Consumes: `Launcher` protocol (T2).
- Produces:
  - `class UnknownKind(Exception)`.
  - `class LauncherRegistry` — `__init__(self, launchers=None)` (inject for tests); `register(launcher)`; `get(kind) -> Launcher` (raises `UnknownKind` with a helpful message listing known kinds); `kinds() -> list[str]`.
  - classmethod `discover() -> LauncherRegistry` — loads every entry point in group `sheppy.launchers` (`importlib.metadata.entry_points(group="sheppy.launchers")`), instantiates each (`ep.load()()`), and registers it. A launcher whose entry point fails to load is skipped (never crash discovery).
  - `default_registry() -> LauncherRegistry` — module-level cached `discover()` result (built once).

- [ ] **Step 1: Write the failing tests**

```python
# tests/launch/test_registry.py
import pytest
from sheppy.launch.registry import LauncherRegistry, UnknownKind


class FakeLauncher:
    def __init__(self, kind):
        self.kind = kind
    def validate(self, raw_alt): return []
    def launch(self, alt, params, ctx): return None
    def summary(self, alt): return []


def test_register_and_get():
    reg = LauncherRegistry([FakeLauncher("process"), FakeLauncher("docker")])
    assert reg.get("docker").kind == "docker"
    assert reg.kinds() == ["docker", "process"]


def test_unknown_kind_lists_known():
    reg = LauncherRegistry([FakeLauncher("process")])
    with pytest.raises(UnknownKind) as ei:
        reg.get("nope")
    assert "nope" in str(ei.value) and "process" in str(ei.value)


def test_discover_loads_entry_points(monkeypatch):
    class _EP:
        name = "docker"
        def load(self): return lambda: FakeLauncher("docker")
    monkeypatch.setattr("sheppy.launch.registry.entry_points",
                        lambda group: [_EP()])
    reg = LauncherRegistry.discover()
    assert reg.get("docker").kind == "docker"


def test_discover_skips_a_broken_entry_point(monkeypatch):
    class _Good:
        def load(self): return lambda: FakeLauncher("process")
    class _Bad:
        def load(self): raise ImportError("boom")
    monkeypatch.setattr("sheppy.launch.registry.entry_points",
                        lambda group: [_Bad(), _Good()])
    reg = LauncherRegistry.discover()
    assert reg.kinds() == ["process"]           # bad one skipped, not fatal
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/launch/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# sheppy/launch/registry.py
"""Discover launcher plugins via entry points (group 'sheppy.launchers').
Built-ins and third-party launchers register identically."""
from importlib.metadata import entry_points


class UnknownKind(Exception):
    pass


class LauncherRegistry:
    def __init__(self, launchers=None):
        self._by_kind = {}
        for launcher in (launchers or []):
            self.register(launcher)

    def register(self, launcher) -> None:
        self._by_kind[launcher.kind] = launcher

    def get(self, kind: str):
        try:
            return self._by_kind[kind]
        except KeyError:
            known = ", ".join(self.kinds()) or "(none)"
            raise UnknownKind(
                f"no launcher registered for kind {kind!r}; known: {known}")

    def kinds(self) -> list:
        return sorted(self._by_kind)

    @classmethod
    def discover(cls) -> "LauncherRegistry":
        reg = cls()
        for ep in entry_points(group="sheppy.launchers"):
            try:
                reg.register(ep.load()())
            except Exception:
                continue                        # a broken plugin never breaks discovery
        return reg


_DEFAULT = None


def default_registry() -> "LauncherRegistry":
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = LauncherRegistry.discover()
    return _DEFAULT
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/launch/test_registry.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add sheppy/launch/registry.py tests/launch/test_registry.py
git commit -m "feat(launch): LauncherRegistry with entry-point discovery"
```

---

### Task 4: Migrate the three built-in kinds to launchers

**Files:**
- Create: `sheppy/launch/builtins.py`
- Modify: `sheppy/launch/resolve.py`, `sheppy/launch/__init__.py`, `pyproject.toml`
- Test: `tests/launch/test_builtins.py`; existing `tests/launch/test_resolve.py` must stay green.

**Interfaces:**
- Consumes: `LaunchDescriptor` (T1), `LaunchContext` (T2), `LauncherRegistry`/`default_registry` (T3), `Alternative`/`Manifest`.
- Produces:
  - `sheppy/launch/builtins.py`: `ProcessLauncher`, `ExecutableLauncher`, `LaunchFileLauncher` (each with `kind`, `validate`, `launch`, `summary`), plus the shared helpers `_value`, `_param_token`, `_ros_setup` moved here from `resolve.py`. Each `launch()` returns `LaunchDescriptor.inherit(("bash", "-c", <same command as today>))`.
  - `resolve.py`: `LaunchSpec` now holds `descriptor: LaunchDescriptor` (with an `argv` **property** = `descriptor.start` for compatibility) and, in this task, `to_wire()` **still emits** `{node, alt_id, argv, params}` (argv = list(descriptor.start)) so the daemon is untouched. `resolve(manifest, node_name, alt, params, registry=None) -> (LaunchSpec, list[str])` now dispatches through the registry (default = `default_registry()`), builds a `LaunchContext`, and returns `ctx.warnings`. `diff()` unchanged.
  - `pyproject.toml`: entry points registering the three kinds (and a placeholder comment for `docker`, added in T8). After editing, run `uv sync`.

Command-building rules (must match `resolve.py` today byte-for-byte): executable → `exec ros2 run <pkg> <exe> [--ros-args -p 'k:=v' …]`; launch_file → `exec ros2 launch <pkg> <file> ['k:=v' …]`; process → `<command>` verbatim, params warned-and-ignored; `ros_setup` prefix `source <setup> && ` when the alternative's machine has one. Reuse `_param_token`/`shlex.quote`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/launch/test_builtins.py
from sheppy.launch.builtins import (
    ProcessLauncher, ExecutableLauncher, LaunchFileLauncher)
from sheppy.launch.base import LaunchContext
from sheppy.manifest import Alternative, Machine, Manifest

ROBOT = Machine(name="robot", host="h", user="u",
                ros_setup="/opt/ros/humble/setup.bash")


def ctx(tmp_path, manifest=None):
    return LaunchContext("n", manifest or Manifest(machines=[], nodes=[]),
                         home=str(tmp_path))


def cmd(desc):
    assert desc.supervise == "inherit"
    assert desc.start[:2] == ("bash", "-c")
    return desc.start[2]


def test_executable_matches_legacy_command(tmp_path):
    alt = Alternative(id="real", kind="executable", machine="robot",
                      package="cam_pkg", executable="cam_node")
    c = ctx(tmp_path, Manifest(machines=[ROBOT], nodes=[]))
    desc = ExecutableLauncher().launch(alt, {"fps": 30}, c)
    text = cmd(desc)
    assert text.startswith("source /opt/ros/humble/setup.bash && ")
    assert "exec ros2 run cam_pkg cam_node --ros-args -p 'fps:=30'" in text
    assert c.warnings == []


def test_launch_file_matches_legacy(tmp_path):
    alt = Alternative(id="rs", kind="launch_file", package="p",
                      launch_file="rs.py")
    desc = LaunchFileLauncher().launch(alt, {"depth": "on it"}, ctx(tmp_path))
    assert "exec ros2 launch p rs.py 'depth:=on it'" in cmd(desc)


def test_process_verbatim_and_warns(tmp_path):
    alt = Alternative(id="gui", kind="process", command="rviz2 | tee /tmp/l")
    c = ctx(tmp_path)
    desc = ProcessLauncher().launch(alt, {"x": 1}, c)
    assert cmd(desc) == "rviz2 | tee /tmp/l"
    assert any("ignored" in w for w in c.warnings)


def test_injection_still_escaped(tmp_path):
    alt = Alternative(id="x", kind="executable", package="p", executable="e")
    desc = ExecutableLauncher().launch(
        alt, {"msg": "x'; touch /tmp/PWNED; echo '"}, ctx(tmp_path))
    import shlex
    tokens = shlex.split(cmd(desc))
    assert "touch" not in tokens                # trapped inside one quoted token
```

Add a launcher-contract conformance test (spec §11) — a single test every registered launcher must satisfy:

```python
# tests/launch/test_conformance.py
from sheppy.launch.registry import default_registry


def test_every_registered_launcher_meets_the_contract():
    reg = default_registry()
    assert reg.kinds()                         # discovery found the built-ins
    for kind in reg.kinds():
        launcher = reg.get(kind)
        assert launcher.kind == kind
        assert isinstance(launcher.validate({}), list)      # never raises
        assert callable(launcher.launch) and callable(launcher.summary)
```

Also add to `tests/launch/test_resolve.py` (proving resolve() still works through the registry, and the wire is unchanged this task):

```python
def test_resolve_still_emits_argv_wire(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    from sheppy.launch import resolve
    from sheppy.manifest import Alternative, Manifest
    alt = Alternative(id="a", kind="executable", package="p", executable="e")
    spec, warns = resolve(Manifest(machines=[], nodes=[]), "n", alt, {})
    wire = spec.to_wire()
    assert wire["argv"][0] == "bash" and "ros2 run p e" in wire["argv"][2]
    assert "descriptor" not in wire            # still argv-shaped in Task 4
```

- [ ] **Step 2: Run to verify the new tests fail (and existing resolve tests still pass)**

Run: `uv run pytest tests/launch -v`
Expected: new builtins/resolve tests FAIL (ModuleNotFoundError / no `descriptor`); the pre-existing `test_resolve.py` cases still pass against the current code until Step 3.

- [ ] **Step 3: Implement `builtins.py`, refactor `resolve.py`**

```python
# sheppy/launch/builtins.py
"""The three original kinds, now launchers emitting inherit descriptors.
Command strings are byte-identical to the pre-plugin resolver."""
import json
import shlex

from sheppy.launch.descriptor import LaunchDescriptor


def _value(v) -> str:
    return json.dumps(v) if isinstance(v, (bool, int, float)) else str(v)


def _param_token(k, v) -> str:
    inner = f"{k}:={_value(v)}"
    return "'" + inner.replace("'", "'\\''") + "'"


def _ros_setup(manifest, machine_name):
    if machine_name is None:
        return None
    for m in manifest.machines:
        if m.name == machine_name:
            return m.ros_setup
    return None


def _wrap(manifest, alt, cmd):
    setup = _ros_setup(manifest, alt.machine)
    if setup:
        cmd = f"source {shlex.quote(setup)} && {cmd}"
    return LaunchDescriptor.inherit(("bash", "-c", cmd))


class ExecutableLauncher:
    kind = "executable"

    def validate(self, raw_alt):
        missing = [f for f in ("package", "executable") if not raw_alt.get(f)]
        return [f"executable alternative needs '{f}'" for f in missing]

    def launch(self, alt, params, ctx):
        q = shlex.quote
        cmd = f"exec ros2 run {q(alt.package or '')} {q(alt.executable or '')}"
        if params:
            toks = " ".join(f"-p {_param_token(k, v)}" for k, v in params.items())
            cmd += f" --ros-args {toks}"
        return _wrap(ctx.manifest, alt, cmd)

    def summary(self, alt):
        return [("package", alt.package or "—"),
                ("executable", alt.executable or "—")]


class LaunchFileLauncher:
    kind = "launch_file"

    def validate(self, raw_alt):
        missing = [f for f in ("package", "launch_file") if not raw_alt.get(f)]
        return [f"launch_file alternative needs '{f}'" for f in missing]

    def launch(self, alt, params, ctx):
        q = shlex.quote
        cmd = f"exec ros2 launch {q(alt.package or '')} {q(alt.launch_file or '')}"
        for k, v in params.items():
            cmd += f" {_param_token(k, v)}"
        return _wrap(ctx.manifest, alt, cmd)

    def summary(self, alt):
        return [("package", alt.package or "—"),
                ("launch_file", alt.launch_file or "—")]


class ProcessLauncher:
    kind = "process"

    def validate(self, raw_alt):
        return [] if raw_alt.get("command") else ["process alternative needs 'command'"]

    def launch(self, alt, params, ctx):
        if params:
            ctx.warn(f"'{ctx.node_name}': params on process-kind alternative "
                     f"'{alt.id}' are ignored")
        return _wrap(ctx.manifest, alt, alt.command or "")

    def summary(self, alt):
        return [("command", alt.command or "—")]
```

```python
# sheppy/launch/resolve.py  — replace the file
"""Client-side resolution: alternative -> LaunchSpec via a launcher, plus
the converge diff. The daemon never sees a manifest."""
from dataclasses import dataclass

from sheppy.launch.base import LaunchContext
from sheppy.launch.descriptor import LaunchDescriptor
from sheppy.launch.registry import default_registry


@dataclass(frozen=True)
class LaunchSpec:
    node: str
    alt_id: str
    descriptor: LaunchDescriptor
    params: dict

    @property
    def argv(self) -> tuple:
        return self.descriptor.start

    def to_wire(self) -> dict:
        # Task 4: still argv-shaped so the daemon is untouched. Task 5 flips
        # this to emit 'descriptor'.
        return {"node": self.node, "alt_id": self.alt_id,
                "argv": list(self.descriptor.start), "params": dict(self.params)}


def resolve(manifest, node_name, alt, params, registry=None):
    registry = registry or default_registry()
    ctx = LaunchContext(node_name, manifest)
    launcher = registry.get(alt.kind)
    descriptor = launcher.launch(alt, params, ctx)
    return (LaunchSpec(node=node_name, alt_id=alt.id, descriptor=descriptor,
                       params=dict(params)), ctx.warnings)


_ALIVE = ("launching", "running")


def diff(desired, actual):
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

Update `sheppy/launch/__init__.py` to also export nothing new (still `LaunchSpec, diff, resolve`). Add to `pyproject.toml`:

```toml
[project.entry-points."sheppy.launchers"]
process = "sheppy.launch.builtins:ProcessLauncher"
executable = "sheppy.launch.builtins:ExecutableLauncher"
launch_file = "sheppy.launch.builtins:LaunchFileLauncher"
# docker added in Task 8
```

Then reinstall so entry points are visible:

```bash
uv sync
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: all green — the new builtins/resolve tests pass, and every pre-existing test (resolver, daemon, tui, cli, e2e) still passes because the wire is byte-identical. If `default_registry()` finds no launchers, entry points aren't installed → re-run `uv sync`.

- [ ] **Step 5: Commit**

```bash
git add sheppy/launch tests/launch pyproject.toml uv.lock
git commit -m "feat(launch): migrate process/executable/launch_file to launchers"
```

---

### Task 5: Flip the wire to descriptors; daemon selects a strategy

**Files:**
- Modify: `sheppy/launch/resolve.py` (to_wire + diff), `sheppy/tui/app.py` (`_drift`), `sheppy/daemon/server.py` (launch validation + protocol bump), `sheppy/daemon/table.py` (strategy select)
- Modify tests: `tests/daemon/test_table.py`, `tests/daemon/test_server.py`, `tests/daemon/test_client.py` (spec-helper shape), `tests/launch/test_resolve.py` (wire is now descriptor)
- Test: add `tests/daemon/test_descriptor_wire.py`

**Interfaces:**
- `LaunchSpec.to_wire()` now emits `{node, alt_id, params, descriptor}` where `descriptor = self.descriptor.to_wire()`. The `argv` property stays (client-internal convenience).
- `diff(desired, actual)`: a node needs **restart** when the running descriptor or params differ from desired — `payload["spec"]["descriptor"] != spec.descriptor.to_wire() or payload["spec"]["params"] != spec.params`.
- Daemon `spec` on the wire and in status payloads is `{node, alt_id, params, descriptor}`. The daemon reads the descriptor as a **dict** and never imports `sheppy.launch`.
- `table.launch(spec)`: `inherit` → `ManagedProcess` (injecting `argv = descriptor["start"]` so `ManagedProcess` is unchanged); `detached` → raises `ValueError("detached supervision not yet supported")` until Task 6 (the server turns any handler exception into an error reply, so this never crashes the daemon).
- Server hello `protocol` bumps to `2`.

- [ ] **Step 1: Write the failing test**

```python
# tests/daemon/test_descriptor_wire.py
import asyncio, sys
from sheppy.daemon import process as pr
from sheppy.daemon.config import Config
from sheppy.daemon.table import ProcessTable

INHERIT = {"supervise": "inherit",
           "start": [sys.executable, "-c", "import time; time.sleep(30)"]}


def make_table(tmp_path):
    cfg = Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"),
                 launch_grace=0.1, stop_grace=0.3, kill_grace=0.3)
    return ProcessTable(cfg, on_event=lambda n, p: None)


def spec(node, descriptor=INHERIT):
    return {"node": node, "alt_id": "a", "params": {}, "descriptor": descriptor}


async def wait_state(table, node, state, timeout=5.0):
    async def poll():
        while table.status().get(node, {}).get("state") != state:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def test_inherit_descriptor_launches_via_managed_process(tmp_path):
    table = make_table(tmp_path)
    await table.launch(spec("camera"))
    await wait_state(table, "camera", pr.RUNNING)
    payload = table.status()["camera"]
    assert payload["spec"]["descriptor"]["supervise"] == "inherit"
    await table.stop_all()


async def test_detached_descriptor_errors_until_task6(tmp_path):
    table = make_table(tmp_path)
    det = {"supervise": "detached", "name": "x", "start": ["true"],
           "watch": ["true"]}
    import pytest
    with pytest.raises(ValueError):
        await table.launch(spec("d", det))
```

Add to `tests/launch/test_resolve.py`, replacing `test_resolve_still_emits_argv_wire`:

```python
def test_resolve_emits_descriptor_wire(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    from sheppy.launch import resolve
    from sheppy.manifest import Alternative, Manifest
    alt = Alternative(id="a", kind="executable", package="p", executable="e")
    spec, _ = resolve(Manifest(machines=[], nodes=[]), "n", alt, {})
    wire = spec.to_wire()
    assert "argv" not in wire
    assert wire["descriptor"]["supervise"] == "inherit"
    assert "ros2 run p e" in wire["descriptor"]["start"][2]
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/daemon/test_descriptor_wire.py tests/launch/test_resolve.py::test_resolve_emits_descriptor_wire -v`
Expected: FAIL (wire still argv; table still argv-only).

- [ ] **Step 3: Implement**

`resolve.py` — `to_wire` and `diff`:

```python
    def to_wire(self) -> dict:
        return {"node": self.node, "alt_id": self.alt_id,
                "params": dict(self.params),
                "descriptor": self.descriptor.to_wire()}
```

```python
def diff(desired, actual):
    stops, restarts, starts = [], [], []
    for node, payload in actual.items():
        if payload["state"] in _ALIVE and node not in desired:
            stops.append(("stop", node))
    for node, spec in desired.items():
        payload = actual.get(node)
        alive = payload is not None and payload["state"] in _ALIVE
        if not alive:
            starts.append(("start", node))
        elif (payload["spec"].get("descriptor") != spec.descriptor.to_wire()
              or payload["spec"].get("params") != spec.params):
            restarts.append(("restart", node))
    return stops + restarts + starts
```

`sheppy/tui/app.py` `_drift` (the line comparing argv, ~207):

```python
        spec, _ = resolve(self.manifest, node.name, alt,
                          self.state.effective_params(node.name))
        return (payload["spec"].get("descriptor") != spec.descriptor.to_wire()
                or payload["spec"].get("params") != spec.params)
```

`server.py` — replace launch validation and bump protocol. Add a module-level validator (no `sheppy.launch` import):

```python
def _validate_descriptor(node, d) -> "str | None":
    if not node:
        return "spec requires 'node'"
    if not isinstance(d, dict):
        return "spec requires a 'descriptor'"
    if d.get("supervise") not in ("inherit", "detached"):
        return f"descriptor.supervise invalid: {d.get('supervise')!r}"
    start = d.get("start")
    if not isinstance(start, list) or not start:
        return "descriptor needs a non-empty 'start'"
    if d.get("supervise") == "detached":
        if not d.get("name"):
            return "detached descriptor needs 'name'"
        if bool(d.get("watch")) == bool(d.get("poll")):
            return "detached descriptor needs exactly one of 'watch'/'poll'"
    return None
```

In the launch dispatch:

```python
        if op == "launch":
            spec = msg.get("spec") or {}
            err = _validate_descriptor(spec.get("node"), spec.get("descriptor"))
            if err:
                return {"ok": False, "error": err}
            await self.table.launch(spec)
            return {"ok": True}
```

In the hello event, change `"protocol": 1` to `"protocol": 2`.

`table.py` `launch`:

```python
    async def launch(self, spec: dict) -> None:
        node = spec["node"]
        old = self._entries.get(node)
        if old is not None and not old._exited.is_set() \
                and old.state != pr.STOPPED:
            await old.stop()
        log = NodeLog(self._cfg.log_dir, node,
                      self._cfg.ring_lines, self._cfg.keep_runs)
        descriptor = spec.get("descriptor") or {}
        supervise = descriptor.get("supervise")
        if supervise == "inherit":
            mp_spec = {**spec, "argv": list(descriptor["start"])}
            proc = pr.ManagedProcess(mp_spec, self._cfg, log, self._on_state)
        elif supervise == "detached":
            raise ValueError("detached supervision not yet supported")  # Task 6
        else:
            raise ValueError(f"unknown supervise: {supervise!r}")
        self._entries[node] = proc
        await proc.start()
```

Migrate the daemon test spec-helpers. In `tests/daemon/test_table.py`, `tests/daemon/test_server.py`, `tests/daemon/test_client.py`, change each `spec()` helper to descriptor form:

```python
def spec(node, argv=SLEEP, alt="a"):
    return {"node": node, "alt_id": alt, "params": {},
            "descriptor": {"supervise": "inherit", "start": list(argv)}}
```

(In `test_server.py`/`test_client.py` the signature is `spec(node, argv=SLEEP)` — keep it, just change the body as above.) In `tests/daemon/test_table.py`, update the one assertion that read `["spec"]["argv"]`:

```python
    assert table.status()["flaky"]["spec"]["descriptor"]["start"] == list(CRASH)
```

In `tests/daemon/test_server.py`, the `Wire.connect` hello assertion becomes `hello["protocol"] == 2`.

`tests/daemon/test_process.py` is **unchanged** — it constructs `ManagedProcess` directly with `argv` specs, which still works.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: all green. Behavior is identical for inherit; only the wire shape and drift comparison changed.

- [ ] **Step 5: Commit**

```bash
git add sheppy/launch/resolve.py sheppy/tui/app.py sheppy/daemon/server.py sheppy/daemon/table.py tests/
git commit -m "feat(daemon): carry LaunchDescriptor on the wire; strategy select"
```

---

### Task 6: `DetachedSupervisor`

**Files:**
- Modify: `sheppy/daemon/process.py` (add `DetachedSupervisor`), `sheppy/daemon/table.py` (wire the detached branch)
- Test: `tests/daemon/test_detached.py`

**Interfaces:**
- Consumes: `Supervised` base + state constants (`LAUNCHING`/`RUNNING`/`STOPPING`/`CRASHED`/`STOPPED`), `NodeLog`, `Config`.
- Produces: `class DetachedSupervisor(Supervised)` whose descriptor commands come from `spec["descriptor"]`. Behavior: run `reset` (best-effort) then `start`; a non-zero `start` ⇒ **crashed** (launch failed). On success: stream `logs` into the `NodeLog`, go `launching`, and detect exit via `watch` (blocking; its stdout is the exit code) or `poll` (liveness on an interval; exit code `None`). `stop` runs the `stop` command; the `watch`/`poll` then observes exit. Launch-grace before `running`, same as the process path.
- `table.launch`: the `detached` branch (the `ValueError` placeholder from Task 5) becomes `pr.DetachedSupervisor(spec, self._cfg, log, self._on_state)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_detached.py
import asyncio
import os

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config
from sheppy.daemon.logs import NodeLog


def make(tmp_path, descriptor, **cfg_kw):
    cfg_kw.setdefault("launch_grace", 0.15)
    cfg = Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"), **cfg_kw)
    log = NodeLog(cfg.log_dir, "n", cfg.ring_lines, cfg.keep_runs)
    states = []
    spec = {"node": "n", "alt_id": "a", "params": {}, "descriptor": descriptor}
    sup = pr.DetachedSupervisor(spec, cfg, log,
                                on_state=lambda s: states.append(s.state))
    return sup, states, log


def sh(script):
    return ["sh", "-c", script]


async def wait_for(cond, timeout=5.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def test_runs_then_stops_clean(tmp_path):
    state = str(tmp_path / "STATE")
    desc = {"supervise": "detached", "name": "n",
            "start": sh(f"echo up > {state}"),
            "watch": sh(f"while [ -f {state} ]; do sleep 0.02; done; echo 0"),
            "stop":  sh(f"rm -f {state}"),
            "logs":  sh("echo hello-from-unit")}
    sup, states, log = make(tmp_path, desc)
    await sup.start()
    assert sup.state == pr.LAUNCHING
    await wait_for(lambda: sup.state == pr.RUNNING)
    await sup.stop()
    assert sup.state == pr.STOPPED
    assert states == [pr.LAUNCHING, pr.RUNNING, pr.STOPPING, pr.STOPPED]


async def test_start_failure_is_crashed(tmp_path):
    desc = {"supervise": "detached", "name": "n",
            "start": sh("exit 3"), "watch": sh("echo 0")}
    sup, _, _ = make(tmp_path, desc)
    await sup.start()
    await sup.wait()
    assert sup.state == pr.CRASHED


async def test_crash_via_watch_exit_carries_code(tmp_path):
    desc = {"supervise": "detached", "name": "n",
            "start": sh("true"),
            "watch": sh("sleep 0.25; echo 5"),
            "stop":  sh("true")}
    sup, states, _ = make(tmp_path, desc, launch_grace=0.1)
    await sup.start()
    await sup.wait()
    assert states == [pr.LAUNCHING, pr.RUNNING, pr.CRASHED]
    assert sup.exit_code == 5


async def test_logs_reach_the_ring(tmp_path):
    state = str(tmp_path / "S")
    desc = {"supervise": "detached", "name": "n",
            "start": sh(f"echo up > {state}"),
            "watch": sh(f"while [ -f {state} ]; do sleep 0.02; done; echo 0"),
            "stop":  sh(f"rm -f {state}"),
            "logs":  sh("echo container-says-hi")}
    sup, _, log = make(tmp_path, desc)
    await sup.start()
    await wait_for(lambda: "container-says-hi" in (log.read_new() or log.tail()))
    await sup.stop()
    assert "container-says-hi" in log.tail()


async def test_reset_runs_before_start(tmp_path):
    order = str(tmp_path / "ORDER")
    desc = {"supervise": "detached", "name": "n",
            "reset": sh(f"echo reset >> {order}"),
            "start": sh(f"echo start >> {order}"),
            "watch": sh("sleep 0.3; echo 0"), "stop": sh("true")}
    sup, _, _ = make(tmp_path, desc, launch_grace=0.05)
    await sup.start()
    await wait_for(lambda: os.path.exists(order))
    assert open(order).read().split() == ["reset", "start"]
    await sup.stop()


async def test_poll_mode_without_watch(tmp_path):
    state = str(tmp_path / "P")
    desc = {"supervise": "detached", "name": "n",
            "start": sh(f"echo up > {state}"),
            "poll":  sh(f"test -f {state}"),
            "stop":  sh(f"rm -f {state}"),
            "grace": {"poll": 0.05}}
    sup, _, _ = make(tmp_path, desc, launch_grace=0.05)
    await sup.start()
    await wait_for(lambda: sup.state == pr.RUNNING)
    await sup.stop()
    assert sup.state == pr.STOPPED
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/daemon/test_detached.py -v`
Expected: FAIL — `AttributeError: DetachedSupervisor`.

- [ ] **Step 3: Implement `DetachedSupervisor` in `process.py`**

```python
# append to sheppy/daemon/process.py
import time as _time   # if 'time' isn't already imported at module top, use it


def _parse_exit(out: bytes) -> "int | None":
    try:
        return int(out.strip().split()[-1])
    except (ValueError, IndexError):
        return None


class DetachedSupervisor(Supervised):
    """Supervises a unit that outlives the process that started it (a
    container, a transient service). Driven entirely by the descriptor's
    command-set; the daemon learns no runtime specifics."""

    def __init__(self, spec, cfg, log, on_state) -> None:
        super().__init__(spec, cfg, log, on_state)
        d = spec["descriptor"]
        self._start_cmd = list(d["start"])
        self._reset_cmd = d.get("reset")
        self._watch_cmd = d.get("watch")
        self._poll_cmd = d.get("poll")
        self._stop_cmd = d.get("stop")
        self._logs_cmd = d.get("logs")
        self._stats_cmd = d.get("stats")
        grace = d.get("grace") or {}
        self._launch_grace = grace.get("launch", cfg.launch_grace)
        self._poll_interval = grace.get("poll", 1.0)
        self._watch_task = None
        self._logs_proc = None
        self.adopted = False

    async def _run_once(self, argv, capture=False):
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=(asyncio.subprocess.PIPE if capture
                        else asyncio.subprocess.DEVNULL),
                stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.DEVNULL)
        except (OSError, ValueError):
            return 127, b""
        out, _ = await proc.communicate()
        return proc.returncode, (out or b"")

    async def _open_logs(self):
        if not self._logs_cmd:
            return
        fd = self.log.open_run()
        try:
            self._logs_proc = await asyncio.create_subprocess_exec(
                *self._logs_cmd, stdout=fd, stderr=fd,
                stdin=asyncio.subprocess.DEVNULL)
        except (OSError, ValueError):
            self._logs_proc = None
        finally:
            os.close(fd)

    async def start(self) -> None:
        self._stop_requested = False
        self._exited = asyncio.Event()
        self.exit_code = None
        self.started_at = time.time()
        if self._reset_cmd:
            await self._run_once(self._reset_cmd)          # best-effort cleanup
        rc, _ = await self._run_once(self._start_cmd)
        if rc != 0:
            self._set(CRASHED)                             # launch failed
            self._exited.set()
            return
        await self._open_logs()
        self._set(LAUNCHING)
        self._watch_task = asyncio.ensure_future(
            self._watch() if self._watch_cmd else self._poll())

    async def _watch(self) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._watch_cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.DEVNULL)
        except (OSError, ValueError):
            self._finish(None)
            return
        try:
            out, _ = await asyncio.wait_for(
                asyncio.shield(proc.communicate()), self._launch_grace)
        except asyncio.TimeoutError:
            if not self._stop_requested:
                self._set(RUNNING)
            out, _ = await proc.communicate()
        self._finish(_parse_exit(out))

    async def _poll(self) -> None:
        try:
            await asyncio.wait_for(self._exited.wait(), self._launch_grace)
            return
        except asyncio.TimeoutError:
            pass
        if not self._stop_requested:
            self._set(RUNNING)
        while not self._stop_requested:
            await asyncio.sleep(self._poll_interval)
            rc, _ = await self._run_once(self._poll_cmd)
            if rc != 0:
                break
        self._finish(None)

    def _finish(self, code) -> None:
        if self._exited.is_set():
            return
        self.exit_code = code
        self.log.read_new()
        self._exited.set()
        self._set(STOPPED if self._stop_requested else CRASHED)

    async def stop(self) -> None:
        if self._exited.is_set():
            return
        self._stop_requested = True
        self._set(STOPPING)
        if self._stop_cmd:
            await self._run_once(self._stop_cmd)
        await self._exited.wait()
```

Then in `table.py` `launch`, replace the detached placeholder:

```python
        elif supervise == "detached":
            proc = pr.DetachedSupervisor(spec, self._cfg, log, self._on_state)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/daemon/test_detached.py tests/daemon/test_descriptor_wire.py -v`
Expected: all pass (6 detached + 2 wire). If the poll grace-wait test is slow, that's expected (poll mode trades responsiveness); keep graces small as written.

- [ ] **Step 5: Commit**

```bash
git add sheppy/daemon/process.py sheppy/daemon/table.py tests/daemon/test_detached.py
git commit -m "feat(daemon): DetachedSupervisor for units that outlive the starter"
```

---

### Task 7: Detached re-adoption by name + state-file persistence

**Files:**
- Modify: `sheppy/daemon/process.py` (`DetachedSupervisor.mark_adopted` + `reattach`), `sheppy/daemon/table.py` (`_persist` includes detached; `adopt_from_state` branches)
- Test: `tests/daemon/test_detached_adopt.py`

**Interfaces:**
- `DetachedSupervisor.mark_adopted(started_at)` — sync: set `state=RUNNING`, `adopted=True`, `started_at`, fresh `_exited`. `async reattach()` — re-open the `logs` follower and start `watch`/`poll` against the existing unit (no `reset`/`start`).
- `table._persist()` also records detached entries as `{"detached": True, "spec", "name", "started_at"}` (no pid/proc_start — identity is the name).
- `table.adopt_from_state()` branches: an entry with `"detached"` re-adopts via `DetachedSupervisor` (`mark_adopted` + schedule `reattach()`); an entry with `proc_start` uses the existing pidfd path. Stays **sync** (schedules the async reattach with `asyncio.ensure_future`), so the existing process re-adoption tests are untouched.

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_detached_adopt.py
import asyncio
import json

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config, state_path
from sheppy.daemon.logs import NodeLog
from sheppy.daemon.table import ProcessTable


def cfg_for(tmp_path):
    return Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"),
                  launch_grace=0.1)


def make_table(tmp_path):
    return ProcessTable(cfg_for(tmp_path), on_event=lambda n, p: None)


def sh(s):
    return ["sh", "-c", s]


def detached_spec(node, state):
    return {"node": node, "alt_id": "a", "params": {}, "descriptor": {
        "supervise": "detached", "name": f"unit-{node}",
        "start": sh(f"echo up > {state}"),
        "watch": sh(f"while [ -f {state} ]; do sleep 0.02; done; echo 0"),
        "stop":  sh(f"rm -f {state}"),
        "logs":  sh("true")}}


async def wait_state(table, node, state, timeout=5.0):
    async def poll():
        while table.status().get(node, {}).get("state") != state:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def test_detached_is_persisted(tmp_path):
    state = str(tmp_path / "S")
    table = make_table(tmp_path)
    await table.launch(detached_spec("cam", state))
    await wait_state(table, "cam", pr.RUNNING)
    data = json.loads(open(state_path(str(tmp_path))).read())
    assert data["nodes"]["cam"]["detached"] is True
    assert data["nodes"]["cam"]["name"] == "unit-cam"
    await table.stop("cam")


async def test_detached_readopted_and_controllable(tmp_path):
    state = str(tmp_path / "S")
    table_a = make_table(tmp_path)
    await table_a.launch(detached_spec("cam", state))
    await wait_state(table_a, "cam", pr.RUNNING)
    # "daemon restart": drop table_a without stopping (STATE file persists)
    table_b = make_table(tmp_path)
    assert "cam" in table_b.adopt_from_state()
    await wait_state(table_b, "cam", pr.RUNNING)
    assert table_b.status()["cam"]["adopted"] is True
    await table_b.stop("cam")                 # really removes STATE
    assert table_b.status()["cam"]["state"] == pr.STOPPED


async def test_readopt_of_gone_unit_resolves_stopped(tmp_path):
    state = str(tmp_path / "S")
    table_a = make_table(tmp_path)
    await table_a.launch(detached_spec("cam", state))
    await wait_state(table_a, "cam", pr.RUNNING)
    import os
    os.remove(state)                          # the unit is gone
    table_b = make_table(tmp_path)
    table_b.adopt_from_state()
    await wait_state(table_b, "cam", pr.CRASHED)   # watch returns immediately
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/daemon/test_detached_adopt.py -v`
Expected: FAIL (detached not persisted / not re-adopted).

- [ ] **Step 3: Implement**

Add to `DetachedSupervisor`:

```python
    def mark_adopted(self, started_at) -> None:
        self._stop_requested = False
        self._exited = asyncio.Event()
        self.exit_code = None
        self.adopted = True
        self.started_at = started_at
        self.state = RUNNING

    async def reattach(self) -> None:
        await self._open_logs()
        self._watch_task = asyncio.ensure_future(
            self._watch() if self._watch_cmd else self._poll())
```

In `table.py` `_persist`, replace the per-entry recording loop so detached
entries are kept (they have no pid):

```python
    def _persist(self) -> None:
        live = {}
        for node, e in self._entries.items():
            if e._exited.is_set() or e.state in (pr.STOPPED, pr.CRASHED):
                continue
            if getattr(e, "_name", None):                  # detached
                live[node] = {"detached": True, "spec": e.spec,
                              "name": e._name, "started_at": e.started_at}
            elif e.pid is not None:
                ps = _proc_start_ticks(e.pid)
                if ps is None:
                    continue
                live[node] = {"spec": e.spec, "pid": e.pid,
                              "started_at": e.started_at, "proc_start": ps}
        os.makedirs(self._cfg.home, exist_ok=True)
        path = state_path(self._cfg.home)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"nodes": live}, f)
        os.replace(tmp, path)
```

In `table.py` `adopt_from_state`, branch before the pid path:

```python
        adopted = []
        for node, rec in nodes.items():
            if rec.get("detached"):
                log = NodeLog(self._cfg.log_dir, node,
                              self._cfg.ring_lines, self._cfg.keep_runs)
                log.attach_latest()
                sup = pr.DetachedSupervisor(rec["spec"], self._cfg, log,
                                            self._on_state)
                sup.mark_adopted(rec["started_at"])
                self._entries[node] = sup
                asyncio.ensure_future(sup.reattach())
                adopted.append(node)
                continue
            ticks = _proc_start_ticks(rec["pid"])
            if ticks is None or rec["proc_start"] is None \
                    or ticks != rec["proc_start"]:
                continue
            # ... existing AdoptedProcess path unchanged ...
```

- [ ] **Step 4: Run the daemon suite**

Run: `uv run pytest tests/daemon -v`
Expected: all pass — new detached-adopt tests plus the untouched process re-adoption tests.

- [ ] **Step 5: Commit**

```bash
git add sheppy/daemon/process.py sheppy/daemon/table.py tests/daemon/test_detached_adopt.py
git commit -m "feat(daemon): re-adopt detached units by name across daemon restart"
```

---

### Task 8: Manifest — generic `config` bag + registry-driven validation

**Files:**
- Modify: `sheppy/manifest/models.py` (add `config`), `sheppy/manifest/loader.py` (delegate validation to the launcher registry)
- Test: `tests/manifest/test_loader.py` (existing tests stay green; add two)

**Interfaces:**
- `Alternative` gains `config: dict = field(default_factory=dict)` — the raw alternative mapping, so any launcher (docker, third-party) reads its kind-specific fields from `alt.config` without new core fields.
- The loader no longer hardcodes valid kinds or required fields. It accepts any kind with a registered launcher and delegates field validation to `registry.get(kind).validate(raw)`. An unknown kind is an error listing the known kinds. This makes the built-in launchers' `validate()` (from Task 4) the single source of field validation — no special case.

Why no import cycle: `loader.py → registry.py` only; `registry.py` imports `importlib.metadata` at module load and loads launchers lazily in `discover()`; the built-in launchers import `descriptor` (not `base`/`manifest`), so nothing imports back to `manifest`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/manifest/test_loader.py
def test_config_bag_captures_kind_specific_fields():
    data = _valid_data()
    data["nodes"][0]["alternatives"][0]["some_custom_field"] = {"a": 1}
    result = parse_manifest(data)
    alt = result.manifest.node("camera").alternatives[0]
    assert alt.config["some_custom_field"] == {"a": 1}


def test_unknown_kind_lists_known_kinds():
    data = _valid_data()
    data["nodes"][1]["alternatives"][0]["kind"] = "wizardry"
    result = parse_manifest(data)
    msgs = [e.message for e in result.errors]
    assert any("wizardry" in m and "executable" in m for m in msgs)
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/manifest/test_loader.py::test_config_bag_captures_kind_specific_fields tests/manifest/test_loader.py::test_unknown_kind_lists_known_kinds -v`
Expected: FAIL (`config` doesn't exist; unknown-kind message doesn't list kinds).

- [ ] **Step 3: Implement**

`models.py` — add the field to `Alternative`:

```python
    subscribes: list[str] = field(default_factory=list)
    config: dict = field(default_factory=dict)
```

`loader.py` — replace the `VALID_KINDS`/`_KIND_REQUIRED` block. Remove those two module constants and the kind/field validation they drove; import the registry and delegate:

```python
from sheppy.launch.registry import UnknownKind, default_registry
```

Inside `_build_alternative`, replace the `kind` validation block with:

```python
    kind = raw.get("kind")
    registry = default_registry()
    try:
        launcher = registry.get(kind)
    except UnknownKind:
        launcher = None
        errors.append(ValidationError(
            loc, f"alternative '{alt_id}' has unknown kind {kind!r}; "
                 f"known kinds: {', '.join(registry.kinds()) or '(none)'}"))
    if launcher is not None:
        for msg in launcher.validate(raw):
            errors.append(ValidationError(loc, f"alternative '{alt_id}': {msg}"))
```

And add `config=dict(raw)` to the returned `Alternative(...)`.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: all green. `test_bad_kind` passes (error at location), `test_missing_kind_fields` passes (the launcher's message contains the field name), and the two new tests pass. If discovery is empty (`registry.kinds()` empty), entry points aren't installed → `uv sync`.

- [ ] **Step 5: Commit**

```bash
git add sheppy/manifest/models.py sheppy/manifest/loader.py tests/manifest/test_loader.py
git commit -m "feat(manifest): config bag + registry-driven kind validation"
```

---

### Task 9: Docker launcher — inline `container:` → detached descriptor

**Files:**
- Create: `sheppy/launch/docker/__init__.py`, `sheppy/launch/docker/compose.py`
- Modify: `pyproject.toml` (register `docker`; then `uv sync`)
- Test: `tests/launch/docker/test_compose.py`, `tests/launch/docker/test_launcher.py` (add `tests/launch/docker/__init__.py`)

**Interfaces:**
- Consumes: `LaunchDescriptor` (T1), `LaunchContext` (T2), `Alternative.config` (T8).
- Produces:
  - `sheppy/launch/docker/compose.py`: `service_to_docker_args(service: dict) -> (flags: list[str], image: str, command: list[str], errors: list[str], warnings: list[str])`. Honored subset per spec §8; hard errors for `replicas > 1` and missing `image`; warn-and-ignore `restart`/`depends_on`/`healthcheck`.
  - `sheppy/launch/docker/__init__.py`: `class DockerLauncher` (`kind = "docker"`). `validate` requires exactly one of `compose`/`container` and surfaces compose errors for the inline case. `launch` emits a `detached` descriptor with `name = sheppy-<node>`, `start = docker run -d --name … <image> <command>`, `watch/stop/logs/reset` docker commands. (`compose:` reference and params-file come in T10/T11.)

- [ ] **Step 1: Write the failing tests**

```python
# tests/launch/docker/test_compose.py
from sheppy.launch.docker.compose import service_to_docker_args


def test_common_ros_service():
    svc = {"image": "org/perc:1", "command": "ros2 launch perc up.py",
           "environment": {"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"},
           "network_mode": "host", "ipc": "host",
           "devices": ["/dev/video0:/dev/video0"],
           "volumes": ["/opt/maps:/maps:ro"]}
    flags, image, command, errs, warns = service_to_docker_args(svc)
    assert errs == []
    assert image == "org/perc:1"
    assert command == ["ros2", "launch", "perc", "up.py"]
    assert "--network" in flags and "host" in flags
    assert flags[flags.index("--ipc") + 1] == "host"
    assert "-v" in flags and "/opt/maps:/maps:ro" in flags
    assert "--device" in flags and "/dev/video0:/dev/video0" in flags
    assert flags[flags.index("-e") + 1] == "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp"


def test_missing_image_is_error():
    _, _, _, errs, _ = service_to_docker_args({"command": "x"})
    assert any("image" in e for e in errs)


def test_replicas_gt_one_is_error():
    _, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "deploy": {"replicas": 3}})
    assert any("replicas" in e for e in errs)


def test_inapplicable_keys_warn():
    _, _, _, errs, warns = service_to_docker_args(
        {"image": "i", "restart": "always", "depends_on": ["db"]})
    assert errs == []
    assert any("restart" in w for w in warns)
    assert any("depends_on" in w for w in warns)


def test_environment_list_form_and_volume_longform():
    flags, _, _, _, _ = service_to_docker_args(
        {"image": "i", "environment": ["A=1", "B=2"],
         "volumes": [{"source": "/s", "target": "/t", "read_only": True}]})
    assert flags[flags.index("-e") + 1] == "A=1"
    assert "/s:/t:ro" in flags
```

```python
# tests/launch/docker/test_launcher.py
from sheppy.launch.docker import DockerLauncher
from sheppy.launch.base import LaunchContext
from sheppy.manifest import Alternative, Manifest


def ctx(tmp_path):
    return LaunchContext("perception", Manifest(machines=[], nodes=[]),
                         home=str(tmp_path))


def alt(**config):
    return Alternative(id="real", kind="docker", config=config)


def test_inline_container_descriptor(tmp_path):
    a = alt(container={"image": "org/perc:1",
                       "command": "ros2 launch perc up.py"})
    d = DockerLauncher().launch(a, {}, ctx(tmp_path))
    assert d.supervise == "detached" and d.name == "sheppy-perception"
    assert d.start[:5] == ("docker", "run", "-d", "--name", "sheppy-perception")
    assert d.start[-4:] == ("org/perc:1", "ros2", "launch", "perc")  # +up.py
    assert d.watch == ("docker", "wait", "sheppy-perception")
    assert d.stop[:3] == ("docker", "stop", "--time")
    assert d.reset == ("docker", "rm", "-f", "sheppy-perception")
    assert d.validate() == []


def test_validate_requires_exactly_one_source(tmp_path):
    dl = DockerLauncher()
    assert any("exactly one" in e for e in dl.validate({"kind": "docker"}))
    assert any("exactly one" in e for e in dl.validate(
        {"container": {"image": "i"}, "compose": {"file": "f", "service": "s"}}))
    assert dl.validate({"container": {"image": "i"}}) == []


def test_validate_surfaces_inline_compose_errors():
    errs = DockerLauncher().validate({"container": {"command": "x"}})  # no image
    assert any("image" in e for e in errs)
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/launch/docker -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `compose.py`**

```python
# sheppy/launch/docker/compose.py
"""Translate a docker-compose service definition into docker-run arguments.
We reuse compose's config vocabulary but not its orchestrator."""
import shlex

_WARN_KEYS = ("restart", "depends_on", "healthcheck")


def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _env_pairs(env):
    if not env:
        return []
    if isinstance(env, dict):
        return [(str(k), str(v)) for k, v in env.items()]
    out = []
    for item in env:
        k, _, v = str(item).partition("=")
        out.append((k, v))
    return out


def _volume_str(vol):
    if isinstance(vol, str):
        return vol
    src, tgt = vol.get("source", ""), vol.get("target", "")
    s = f"{src}:{tgt}"
    if vol.get("read_only"):
        s += ":ro"
    return s


def _command_list(cmd):
    if cmd is None:
        return []
    return list(cmd) if isinstance(cmd, (list, tuple)) else shlex.split(cmd)


def service_to_docker_args(service: dict):
    errors, warnings = [], []
    deploy = service.get("deploy") or {}
    if int(deploy.get("replicas") or 1) > 1:
        errors.append("compose 'replicas > 1' is not supported by sheppy")
    image = service.get("image")
    if not image:
        errors.append("docker service needs an 'image' "
                      "(build-only services are unsupported)")
    for key in _WARN_KEYS:
        if key in service:
            warnings.append(f"compose '{key}' is ignored (sheppy owns lifecycle)")

    flags = []
    for k, v in _env_pairs(service.get("environment")):
        flags += ["-e", f"{k}={v}"]
    for ef in _as_list(service.get("env_file")):
        flags += ["--env-file", str(ef)]
    if service.get("network_mode"):
        flags += ["--network", str(service["network_mode"])]
    if service.get("ipc"):
        flags += ["--ipc", str(service["ipc"])]
    if service.get("pid"):
        flags += ["--pid", str(service["pid"])]
    for vol in _as_list(service.get("volumes")):
        flags += ["-v", _volume_str(vol)]
    for dev in _as_list(service.get("devices")):
        flags += ["--device", str(dev)]
    if service.get("privileged"):
        flags += ["--privileged"]
    for cap in _as_list(service.get("cap_add")):
        flags += ["--cap-add", str(cap)]
    for cap in _as_list(service.get("cap_drop")):
        flags += ["--cap-drop", str(cap)]
    for port in _as_list(service.get("ports")):
        flags += ["-p", str(port)]
    if service.get("user"):
        flags += ["-u", str(service["user"])]
    if service.get("working_dir"):
        flags += ["-w", str(service["working_dir"])]
    if service.get("entrypoint"):
        ep = service["entrypoint"]
        flags += ["--entrypoint", ep if isinstance(ep, str) else " ".join(ep)]
    if service.get("gpus"):
        flags += ["--gpus", str(service["gpus"])]

    return flags, image or "", _command_list(service.get("command")), errors, warnings
```

- [ ] **Step 4: Implement `DockerLauncher`**

```python
# sheppy/launch/docker/__init__.py
"""The docker launcher: a compose service becomes a supervised container."""
from sheppy.launch.descriptor import LaunchDescriptor
from sheppy.launch.docker.compose import service_to_docker_args

__all__ = ["DockerLauncher"]


class DockerLauncher:
    kind = "docker"

    def _service(self, alt, ctx):
        # T10 adds the compose-file reference branch.
        return dict(alt.config.get("container") or {})

    def validate(self, raw_alt) -> list:
        has_compose = bool(raw_alt.get("compose"))
        has_inline = bool(raw_alt.get("container"))
        if has_compose == has_inline:
            return ["docker alternative needs exactly one of "
                    "'compose' or 'container'"]
        if has_inline:
            _, _, _, errs, _ = service_to_docker_args(raw_alt["container"])
            return errs
        return []

    def launch(self, alt, params, ctx) -> LaunchDescriptor:
        name = f"sheppy-{ctx.node_name}"
        service = self._service(alt, ctx)
        flags, image, command, errs, warns = service_to_docker_args(service)
        for w in warns:
            ctx.warn(w)
        for e in errs:
            ctx.warn(e)                       # validate() already flags these
        start = (["docker", "run", "-d", "--name", name] + flags
                 + [image] + command)
        return LaunchDescriptor.detached(
            name, start=start,
            watch=["docker", "wait", name],
            stop=["docker", "stop", "--time", "10", name],
            logs=["docker", "logs", "-f", "--tail", "300", name],
            reset=["docker", "rm", "-f", name])

    def summary(self, alt) -> list:
        svc = alt.config.get("container") or {}
        return [("image", svc.get("image", "—")),
                ("network", str(svc.get("network_mode", "default")))]
```

Register in `pyproject.toml` and reinstall:

```toml
[project.entry-points."sheppy.launchers"]
process = "sheppy.launch.builtins:ProcessLauncher"
executable = "sheppy.launch.builtins:ExecutableLauncher"
launch_file = "sheppy.launch.builtins:LaunchFileLauncher"
docker = "sheppy.launch.docker:DockerLauncher"
```

```bash
uv sync
```

- [ ] **Step 5: Run the suite**

Run: `uv run pytest tests/launch -q && uv run pytest -q`
Expected: docker tests pass; `docker` now discoverable so a `kind: docker` manifest validates (T8's loader accepts it); everything green.

- [ ] **Step 6: Commit**

```bash
git add sheppy/launch/docker tests/launch/docker pyproject.toml uv.lock
git commit -m "feat(docker): launcher + compose->docker-run translation (inline)"
```

---

### Task 10: Docker launcher — compose-file reference + `${VAR}` interpolation

**Files:**
- Modify: `sheppy/launch/base.py` (`LaunchContext.manifest_dir`), `sheppy/launch/resolve.py` (thread `manifest_dir`), `sheppy/tui/app.py` + `sheppy/cli.py` (pass the manifest dir), `sheppy/launch/docker/compose.py` (`load_service`), `sheppy/launch/docker/__init__.py` (`_service` reads the file)
- Test: `tests/launch/docker/test_compose_ref.py`

**Interfaces:**
- `LaunchContext.__init__(..., manifest_dir: str | None = None)` → `self.manifest_dir` (default `"."`). `resolve(manifest, node, alt, params, registry=None, manifest_dir=None)` passes it into the context. `app.py`/`cli.py` pass `os.path.dirname(os.path.abspath(self.path or "system.yaml"))`.
- `compose.load_service(path, service, env) -> dict` — read the compose YAML, apply `${VAR}` / `${VAR:-default}` interpolation from `env` over string values, return the named service. Raises `FileNotFoundError` / `KeyError` on a missing file / service.
- `DockerLauncher._service` resolves the `compose:` reference relative to `ctx.manifest_dir`. `validate` checks the reference structurally (has `file` and `service`); a missing file/service surfaces at resolve time (`ctx.warn`) and, if launched, as a crashed node — consistent with never-crash.

- [ ] **Step 1: Write the failing tests**

```python
# tests/launch/docker/test_compose_ref.py
import textwrap
from sheppy.launch.docker.compose import load_service
from sheppy.launch.docker import DockerLauncher
from sheppy.launch.base import LaunchContext
from sheppy.manifest import Alternative, Manifest


def write(tmp_path, text):
    p = tmp_path / "demo.compose.yml"
    p.write_text(textwrap.dedent(text))
    return str(p)


def test_load_service_with_interpolation(tmp_path, monkeypatch):
    monkeypatch.setenv("TAG", "1.2")
    path = write(tmp_path, """
        services:
          perception:
            image: org/perc:${TAG}
            network_mode: ${NET:-host}
            command: ros2 launch perc up.py
    """)
    svc = load_service(path, "perception", __import__("os").environ)
    assert svc["image"] == "org/perc:1.2"
    assert svc["network_mode"] == "host"          # default applied


def test_launcher_reads_compose_reference(tmp_path):
    path = write(tmp_path, """
        services:
          perception:
            image: org/perc:1
            command: ros2 launch perc up.py
    """)
    a = Alternative(id="real", kind="docker",
                    config={"compose": {"file": "demo.compose.yml",
                                        "service": "perception"}})
    ctx = LaunchContext("perception", Manifest(machines=[], nodes=[]),
                        home=str(tmp_path), manifest_dir=str(tmp_path))
    d = DockerLauncher().launch(a, {}, ctx)
    assert "org/perc:1" in d.start
    assert d.name == "sheppy-perception"


def test_missing_service_warns_not_crashes(tmp_path):
    path = write(tmp_path, "services: {other: {image: i}}")
    a = Alternative(id="real", kind="docker",
                    config={"compose": {"file": "demo.compose.yml",
                                        "service": "perception"}})
    ctx = LaunchContext("perception", Manifest(machines=[], nodes=[]),
                        home=str(tmp_path), manifest_dir=str(tmp_path))
    d = DockerLauncher().launch(a, {}, ctx)     # must not raise
    assert any("perception" in w for w in ctx.warnings)
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/launch/docker/test_compose_ref.py -v`
Expected: FAIL — `load_service` / `manifest_dir` missing.

- [ ] **Step 3: Implement**

`base.py` — replace `LaunchContext.__init__` with the manifest-dir-aware version:

```python
    def __init__(self, node_name, manifest, home=None, manifest_dir=None):
        self.node_name = node_name
        self.manifest = manifest
        self._home = home or sheppy_home()
        self._warnings = []
        self.manifest_dir = manifest_dir or "."
```

`resolve.py` — thread it:

```python
def resolve(manifest, node_name, alt, params, registry=None, manifest_dir=None):
    registry = registry or default_registry()
    ctx = LaunchContext(node_name, manifest, manifest_dir=manifest_dir)
    launcher = registry.get(alt.kind)
    descriptor = launcher.launch(alt, params, ctx)
    return (LaunchSpec(node=node_name, alt_id=alt.id, descriptor=descriptor,
                       params=dict(params)), ctx.warnings)
```

In `app.py` and `cli.py`, every `resolve(self.manifest, …)` call passes
`manifest_dir=os.path.dirname(os.path.abspath(self.path or "system.yaml"))`
(app: `self.path`; cli `_up`: `os.path.dirname(os.path.abspath(args.manifest))`).

`compose.py` — add interpolation + loader:

```python
import os
import re

import yaml

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _interpolate(value, env):
    if isinstance(value, str):
        return _VAR.sub(lambda m: env.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _interpolate(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, env) for v in value]
    return value


def load_service(path: str, service: str, env: dict) -> dict:
    with open(path) as f:
        doc = yaml.safe_load(f) or {}
    services = doc.get("services") or {}
    if service not in services:
        raise KeyError(service)
    return _interpolate(dict(services[service] or {}), dict(env))
```

`docker/__init__.py` — replace `_service` and tighten `validate`:

```python
    def _service(self, alt, ctx):
        inline = alt.config.get("container")
        if inline:
            return dict(inline)
        ref = alt.config.get("compose") or {}
        path = ref.get("file", "")
        if not os.path.isabs(path):
            path = os.path.join(ctx.manifest_dir, path)
        try:
            return load_service(path, ref.get("service"), os.environ)
        except (OSError, KeyError) as e:
            ctx.warn(f"'{ctx.node_name}': compose service "
                     f"{ref.get('service')!r} in {ref.get('file')!r}: {e}")
            return {}
```

Add `import os` and `from sheppy.launch.docker.compose import load_service` at the top of `docker/__init__.py`. In `validate`, the compose branch now checks structure:

```python
        if has_compose:
            ref = raw_alt["compose"]
            if not (isinstance(ref, dict) and ref.get("file") and ref.get("service")):
                return ["docker 'compose' needs 'file' and 'service'"]
            return []
```

(An empty service dict from a missing file yields a descriptor with no image; `service_to_docker_args` warns via `ctx.warn`, and a launch attempt crashes the node with the docker error — never a Python crash.)

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/launch/docker -q && uv run pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add sheppy/launch tests/launch/docker sheppy/tui/app.py sheppy/cli.py
git commit -m "feat(docker): compose-file reference with \${VAR} interpolation"
```

---

### Task 11: Docker launcher — params-file injection

**Files:**
- Modify: `sheppy/launch/docker/__init__.py`
- Test: `tests/launch/docker/test_params.py`

**Interfaces:**
- `DockerLauncher.launch`: when `params` is non-empty, write them via `ctx.write_params_file(params, ros_node_name)` (`ros_node_name = alt.config.get("ros_node_name")`), bind-mount the host file read-only at `/sheppy/params.yaml`, and append `--ros-args --params-file /sheppy/params.yaml` to the container command. Empty params → no mount, no args (unchanged from T9/T10).
- This makes a Docker node's `params` behave exactly like every other kind's: the param editor, profile overrides, and drift detection all work with no UI change (drift: editing a param rewrites the file, and the descriptor's `-v host:/…` path is stable, but the **params** on the wire change → `diff()` already restarts on a params change, per Task 5).

- [ ] **Step 1: Write the failing tests**

```python
# tests/launch/docker/test_params.py
import yaml
from sheppy.launch.docker import DockerLauncher
from sheppy.launch.base import LaunchContext
from sheppy.manifest import Alternative, Manifest


def ctx(tmp_path):
    return LaunchContext("perception", Manifest(machines=[], nodes=[]),
                         home=str(tmp_path), manifest_dir=str(tmp_path))


def test_params_are_written_mounted_and_referenced(tmp_path):
    a = Alternative(id="real", kind="docker",
                    config={"container": {"image": "img",
                                          "command": "ros2 launch p up.py"}})
    d = DockerLauncher().launch(a, {"max_range": 5.0}, ctx(tmp_path))
    start = list(d.start)
    # a read-only mount of the host params file at the fixed container path
    mount = next(s for s in start if s.endswith(":/sheppy/params.yaml:ro"))
    host_path = mount.split(":")[0]
    assert yaml.safe_load(open(host_path)) == {
        "/**": {"ros__parameters": {"max_range": 5.0}}}
    # command carries the --params-file arg
    tail = start[start.index("img") + 1:]
    assert tail[-3:] == ["--ros-args", "--params-file", "/sheppy/params.yaml"]


def test_ros_node_name_targets_the_params_file(tmp_path):
    a = Alternative(id="real", kind="docker",
                    config={"container": {"image": "img"},
                            "ros_node_name": "percep"})
    d = DockerLauncher().launch(a, {"x": 1}, ctx(tmp_path))
    mount = next(s for s in d.start if s.endswith(":/sheppy/params.yaml:ro"))
    data = yaml.safe_load(open(mount.split(":")[0]))
    assert data == {"percep": {"ros__parameters": {"x": 1}}}


def test_no_params_no_mount(tmp_path):
    a = Alternative(id="real", kind="docker",
                    config={"container": {"image": "img", "command": "run"}})
    d = DockerLauncher().launch(a, {}, ctx(tmp_path))
    assert not any(":/sheppy/params.yaml:ro" in s for s in d.start)
    assert "--params-file" not in d.start
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/launch/docker/test_params.py -v`
Expected: FAIL (no mount / no params-file args yet).

- [ ] **Step 3: Implement**

In `docker/__init__.py` `launch`, after computing `flags, image, command, …` and emitting warnings, insert the params injection before building `start`:

```python
        if params:
            host = ctx.write_params_file(params, alt.config.get("ros_node_name"))
            flags += ["-v", f"{host}:/sheppy/params.yaml:ro"]
            command += ["--ros-args", "--params-file", "/sheppy/params.yaml"]
        start = (["docker", "run", "-d", "--name", name] + flags
                 + [image] + command)
```

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/launch/docker -q && uv run pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add sheppy/launch/docker/__init__.py tests/launch/docker/test_params.py
git commit -m "feat(docker): inject ROS params via a bind-mounted params-file"
```

---

### Task 12: UI — kind-agnostic DETAIL via `summary()`

**Files:**
- Modify: `sheppy/tui/widgets/detail_tabs.py` (`show`/`_detail_markup`/`_yaml`), `sheppy/tui/app.py` (`_show_detail` passes summary rows)
- Test: `tests/tui/test_detail_docker.py`

**Interfaces:**
- `DetailTabs.show(node, alt, summary_rows=None)`: `_detail_markup` renders `kind` then the `summary_rows` (a `list[(label, value)]`) instead of the hardcoded per-kind block. `None` → no extra rows.
- The app computes rows via the registry and passes them, keeping the widget free of launcher imports:
  ```python
  def _summary_rows(self, alt):
      from sheppy.launch.registry import default_registry, UnknownKind
      try:
          return default_registry().get(alt.kind).summary(alt)
      except UnknownKind:
          return []
  ```
- `_yaml(alt)` also dumps `alt.config` when non-empty, so a Docker node's `container`/`compose` block is visible in the YAML tab.

- [ ] **Step 1: Write the failing test**

```python
# tests/tui/test_detail_docker.py
import textwrap
from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp
from tests.tui._fake_daemon import FakeDaemonClient


def write_manifest(tmp_path):
    p = tmp_path / "system.yaml"
    p.write_text(textwrap.dedent("""
        machines: []
        nodes:
          - name: perception
            alternatives:
              - id: real
                kind: docker
                container: {image: org/perc:1, command: "ros2 run p n"}
                params: {max_range: 5.0}
    """))
    return str(p)


async def test_docker_detail_shows_image_and_params_edit_works(tmp_path):
    path = write_manifest(tmp_path)
    app = SheppyApp(load_manifest(path), path=path,
                    profiles_dir=str(tmp_path / "profiles"),
                    client=FakeDaemonClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        detail = str(app.query_one("#detail").content)
        assert "org/perc:1" in detail          # summary() row rendered
        await pilot.press("p")                  # param editor opens, no crash
        await pilot.pause()
        assert app.state.effective_params("perception") == {"max_range": 5.0}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/tui/test_detail_docker.py -v`
Expected: FAIL (image not in detail; docker kind not rendered).

- [ ] **Step 3: Implement**

In `detail_tabs.py`, change `show` to accept `summary_rows=None`, store it, and in `_detail_markup` replace the `if alt.kind == "executable"… elif…` block (lines ~123–130) with:

```python
        for label, value in (summary_rows or []):
            lines.append(row(label, c("fg", str(value))))
```

Thread `summary_rows` from `show` into `_detail_markup` (add the parameter). In `_yaml`, after building the field dict, add:

```python
        if alt.config:
            data["config"] = alt.config
```

In `app.py` `_show_detail`:

```python
    def _show_detail(self, node: Node) -> None:
        idx = self.query_one(AlternativesPanel).index
        alt = (node.alternatives[idx]
               if idx is not None and node.alternatives else None)
        rows = self._summary_rows(alt) if alt else None
        self.query_one(DetailTabs).show(node, alt, summary_rows=rows)
```

Add the `_summary_rows` helper (shown in Interfaces). The module-level `format_detail()` legacy function (detail_tabs.py:17-25) can keep its hardcoded kinds — it's only used by older tests; leave it untouched.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/tui -q && uv run pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/widgets/detail_tabs.py sheppy/tui/app.py tests/tui/test_detail_docker.py
git commit -m "feat(tui): render DETAIL rows via launcher.summary(); config in YAML"
```

---

### Task 13: Developer plugin guide + example launcher

**Files:**
- Create: `docs/launcher-plugins.md`, `examples/launchers/echo_launcher.py`
- Modify: `docs/index.md`, `README.md`
- Test: none (docs); a doctest-style importability check for the example.

**Interfaces:** the guide documents the `Launcher` contract, the `LaunchDescriptor` vocabulary (both shapes, `watch` vs `poll`, the `stats` two-number contract), `LaunchContext`, and entry-point registration. `examples/launchers/echo_launcher.py` is a complete, working third-party-style launcher (`kind = "echo"`) that emits an `inherit` descriptor — a copy-paste starting point.

- [ ] **Step 1: Write the example launcher + an importability test**

```python
# examples/launchers/echo_launcher.py
"""A minimal example launcher. Register it in your package's pyproject:

    [project.entry-points."sheppy.launchers"]
    echo = "echo_launcher:EchoLauncher"

Then `kind: echo` alternatives run `echo <message>`.
"""
from sheppy.launch.descriptor import LaunchDescriptor


class EchoLauncher:
    kind = "echo"

    def validate(self, raw_alt):
        return [] if raw_alt.get("message") else ["echo alternative needs 'message'"]

    def launch(self, alt, params, ctx):
        msg = alt.config.get("message", "")
        return LaunchDescriptor.inherit(("bash", "-c", f"echo {msg!r}; sleep 3600"))

    def summary(self, alt):
        return [("message", alt.config.get("message", "—"))]
```

```python
# tests/test_example_launcher.py
def test_echo_launcher_emits_valid_descriptor():
    import importlib.util, os
    path = os.path.join("examples", "launchers", "echo_launcher.py")
    spec = importlib.util.spec_from_file_location("echo_launcher", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Alt:
        kind = "echo"; config = {"message": "hi"}
    d = mod.EchoLauncher().launch(_Alt(), {}, None)
    assert d.validate() == [] and d.supervise == "inherit"
    assert mod.EchoLauncher().validate({}) == ["echo alternative needs 'message'"]
```

- [ ] **Step 2: Run the importability test**

Run: `uv run pytest tests/test_example_launcher.py -v`
Expected: PASS.

- [ ] **Step 3: Write `docs/launcher-plugins.md`**

Write a complete guide covering: the three-layer model (client-side launcher → descriptor → daemon engine) and why plugins are declarative and never run in the daemon; the `Launcher` contract with each method's job; the full `LaunchDescriptor` vocabulary — `inherit` vs `detached`, `watch` (blocking, preferred) vs `poll`, `stop`/`logs`/`reset`, and the `stats` "print two numbers `<cpu_pct> <rss_mb>`" contract; `LaunchContext` (`scratch_dir`, `write_params_file`, `warn`); registering via entry points (`group = "sheppy.launchers"`, then reinstall); a worked walk-through of `examples/launchers/echo_launcher.py`; and how the built-in `process`/`docker` launchers are just launchers themselves. Link it from `docs/index.md` (add a "Guides" row) and from `README.md` (a "Writing a launcher plugin" pointer near the sheppyd section).

- [ ] **Step 4: Commit**

```bash
git add docs/launcher-plugins.md docs/index.md README.md examples/launchers tests/test_example_launcher.py
git commit -m "docs: launcher plugin guide + worked example launcher"
```

---

### Task 14: Docker example manifest + opt-in integration test

**Files:**
- Create: `examples/docker-demo.yaml`, `tests/test_docker_e2e.py`
- Test: the integration test (skipped unless Docker is available)

**Interfaces:** an opt-in end-to-end test that, only when `docker` is usable, launches a real throwaway container through the full stack (real resolver → descriptor → daemon `DetachedSupervisor`) and verifies running→stopped, re-adoption by name, and no leaked container.

- [ ] **Step 1: Example manifest (no ROS needed to browse)**

```yaml
# examples/docker-demo.yaml — a dockerized node; needs Docker only to launch.
machines: []
nodes:
  - name: sleeper
    description: a throwaway container node
    alternatives:
      - id: alpine
        kind: docker
        container:
          image: alpine:3
          command: "sleep 3600"
```

- [ ] **Step 2: Write the opt-in integration test**

```python
# tests/test_docker_e2e.py
import shutil
import subprocess
import sys

import pytest

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config
from sheppy.daemon.table import ProcessTable


def _docker_ok():
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


pytestmark = pytest.mark.skipif(not _docker_ok(),
                                reason="docker not available")


def _table(tmp_path):
    cfg = Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"),
                 launch_grace=0.5)
    return ProcessTable(cfg, on_event=lambda n, p: None)


def _spec(name):
    return {"node": "sleeper", "alt_id": "alpine", "params": {}, "descriptor": {
        "supervise": "detached", "name": name,
        "start": ["docker", "run", "-d", "--name", name, "alpine:3",
                  "sleep", "3600"],
        "watch": ["docker", "wait", name],
        "stop": ["docker", "stop", "--time", "2", name],
        "logs": ["docker", "logs", "-f", name],
        "reset": ["docker", "rm", "-f", name]}}


async def _wait(table, node, state, timeout=30.0):
    import asyncio
    async def poll():
        while table.status().get(node, {}).get("state") != state:
            await asyncio.sleep(0.1)
    await asyncio.wait_for(poll(), timeout)


async def test_real_container_runs_and_stops(tmp_path):
    name = "sheppy-e2e-sleeper"
    subprocess.run(["docker", "rm", "-f", name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    table = _table(tmp_path)
    try:
        await table.launch(_spec(name))
        await _wait(table, "sleeper", pr.RUNNING)
        await table.stop("sleeper")
        await _wait(table, "sleeper", pr.STOPPED)
    finally:
        subprocess.run(["docker", "rm", "-f", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
```

- [ ] **Step 3: Run it (skips cleanly without Docker)**

Run: `uv run pytest tests/test_docker_e2e.py -v`
Expected: PASS if Docker is available, else SKIPPED. On a Docker host, verify no leftover container: `docker ps -a --filter name=sheppy-e2e`.

- [ ] **Step 4: Full suite + commit**

Run: `uv run pytest -q`
Expected: everything green (the docker e2e skips without Docker).

```bash
git add examples/docker-demo.yaml tests/test_docker_e2e.py
git commit -m "test: opt-in docker integration + example docker manifest"
```

---

## Deferred to a follow-up (surfaced, not silently dropped)

- **Container resource usage (`stats`).** The `LaunchDescriptor` vocabulary and the daemon's per-node usage slot support it, but this plan does not emit a `stats` command from the docker launcher or wire the daemon to run one — Docker nodes show **blank** usage (the `/proc` sampler skips them, since a detached unit has no host pid). The reformatting of `docker stats` output into the daemon's fixed `<cpu_pct> <rss_mb>` contract is fiddly and the spec marks usage optional. A follow-up would add a small `sheppy/launch/docker/stats.py` helper (run as the `stats` argv) and the server-side sampling of detached `stats`.
- **Fully registry-driven manifest openness.** Task 8 gates kinds on `registry.kinds()`, so a third-party kind is accepted once its plugin is installed; no further work needed for that. (Listed here only to confirm it is done, not deferred.)

## Self-review notes

- Every task keeps the suite green: Phase A (T1–T4) is a behavior-preserving client refactor with the wire unchanged; T5 flips the wire with inherit-only; T6/T7 add detached; T8 makes validation registry-driven; T9–T11 add Docker; T12–T14 UI/docs/e2e.
- Purity: the daemon never imports `sheppy.launch` (it reads the descriptor as a dict); `tests/daemon/test_purity.py` is updated in T2 to assert exactly that while allowing yaml in `launch/`.
- Behavior preservation for the three original kinds is guarded by the pre-existing resolver + e2e tests through T4 and T5.









