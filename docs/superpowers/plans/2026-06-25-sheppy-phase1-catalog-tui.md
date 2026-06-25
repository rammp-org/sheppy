# Sheppy Phase 1 — Manifest Schema + Catalog Browser TUI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Textual TUI that loads and validates a curated `system.yaml`, browses its nodes and alternatives, and lets the user single-select one alternative per node (mock vs. real) — no daemon, no launching.

**Architecture:** A pure-Python model/loader layer (`sheppy.manifest`) and selection layer (`sheppy.selection`) carry all logic and are unit-tested without any UI. The Textual layer (`sheppy.tui`) is thin: widgets render the model and forward key events. This separation is deliberate so the TUI becomes a thin `sheppyd` client in Phase 2 with no rewrite.

**Tech Stack:** Python 3.10+, [Textual](https://textual.textualize.io/) (TUI), PyYAML (manifest parsing), pytest + pytest-asyncio (tests; Textual's `app.run_test()` pilot is async).

## Global Constraints

- Python 3.10+ (uses `X | None` union syntax).
- The manifest (`system.yaml`) is the single source of truth — no auto-discovery in Phase 1.
- `select` supports only the value `single` (one active alternative per node).
- Never crash on a bad manifest — surface validation errors and stay browsable where possible.
- All logic lives in `sheppy.manifest` / `sheppy.selection` (pure Python). `sheppy.tui` widgets only render and forward events.
- Use TDD: failing test first, minimal implementation, commit per task.

---

### Task 1: Project scaffold and tooling

**Files:**
- Create: `pyproject.toml`
- Create: `sheppy/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable `sheppy` package; `sheppy.__version__: str`; a working `pytest` setup with `asyncio_mode = auto`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smoke.py
import sheppy


def test_package_has_version():
    assert isinstance(sheppy.__version__, str)
    assert sheppy.__version__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy'`

- [ ] **Step 3: Create the package and config**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "sheppy"
version = "0.1.0"
description = "Herds the ROS2 nodes of a distributed robotics project."
requires-python = ">=3.10"
dependencies = [
    "textual>=0.50",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-asyncio>=0.23",
]

[project.scripts]
sheppy = "sheppy.cli:main"

[tool.setuptools.packages.find]
include = ["sheppy*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

```python
# sheppy/__init__.py
__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

```
# .gitignore
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
.venv/
dist/
build/
```

- [ ] **Step 4: Install dev deps and run the test to verify it passes**

Run: `pip install -e ".[dev]" && python -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml sheppy/__init__.py tests/__init__.py tests/test_smoke.py .gitignore
git commit -m "feat: scaffold sheppy package and test tooling"
```

---

### Task 2: Manifest data models

**Files:**
- Create: `sheppy/manifest/__init__.py`
- Create: `sheppy/manifest/models.py`
- Create: `tests/manifest/__init__.py`
- Create: `tests/manifest/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces (all `@dataclass(frozen=True)` in `sheppy.manifest.models`, re-exported from `sheppy.manifest`):
  - `Machine(name: str, host: str, user: str, ros_setup: str | None = None)`
  - `Alternative(id: str, kind: str, machine: str | None = None, package: str | None = None, executable: str | None = None, launch_file: str | None = None, command: str | None = None, params: dict = {}, publishes: list[str] = [], subscribes: list[str] = [])`
  - `Node(name: str, alternatives: list[Alternative], description: str = "", select: str = "single")`
  - `Manifest(machines: list[Machine], nodes: list[Node])`
  - `Manifest.node(name: str) -> Node | None` — lookup helper.

- [ ] **Step 1: Write the failing test**

```python
# tests/manifest/test_models.py
from sheppy.manifest import Machine, Alternative, Node, Manifest


def test_construct_full_model():
    alt = Alternative(id="realsense", kind="launch_file", package="realsense2_camera",
                      launch_file="rs_launch.py", publishes=["/camera/color/image_raw"])
    node = Node(name="camera", alternatives=[alt], description="RGB-D source")
    manifest = Manifest(machines=[Machine(name="robot", host="10.0.0.20", user="r")],
                        nodes=[node])
    assert manifest.nodes[0].alternatives[0].id == "realsense"
    assert node.select == "single"  # default
    assert alt.params == {} and alt.subscribes == []  # mutable defaults isolated


def test_manifest_node_lookup():
    node = Node(name="camera", alternatives=[])
    manifest = Manifest(machines=[], nodes=[node])
    assert manifest.node("camera") is node
    assert manifest.node("missing") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/manifest/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy.manifest'`

- [ ] **Step 3: Write minimal implementation**

```python
# sheppy/manifest/models.py
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Machine:
    name: str
    host: str
    user: str
    ros_setup: str | None = None


@dataclass(frozen=True)
class Alternative:
    id: str
    kind: str  # "executable" | "launch_file" | "process"
    machine: str | None = None
    package: str | None = None
    executable: str | None = None
    launch_file: str | None = None
    command: str | None = None
    params: dict = field(default_factory=dict)
    publishes: list[str] = field(default_factory=list)
    subscribes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Node:
    name: str
    alternatives: list[Alternative]
    description: str = ""
    select: str = "single"


@dataclass(frozen=True)
class Manifest:
    machines: list[Machine]
    nodes: list[Node]

    def node(self, name: str) -> "Node | None":
        for n in self.nodes:
            if n.name == name:
                return n
        return None
```

```python
# sheppy/manifest/__init__.py
from sheppy.manifest.models import Machine, Alternative, Node, Manifest

__all__ = ["Machine", "Alternative", "Node", "Manifest"]
```

```python
# tests/manifest/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/manifest/test_models.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add sheppy/manifest/ tests/manifest/__init__.py tests/manifest/test_models.py
git commit -m "feat: add manifest data models"
```

---

### Task 3: Manifest loader and validation

**Files:**
- Create: `sheppy/manifest/errors.py`
- Create: `sheppy/manifest/loader.py`
- Modify: `sheppy/manifest/__init__.py`
- Create: `tests/manifest/test_loader.py`

**Interfaces:**
- Consumes: `Machine`, `Alternative`, `Node`, `Manifest` from Task 2.
- Produces (re-exported from `sheppy.manifest`):
  - `ValidationError(location: str, message: str)` — `@dataclass(frozen=True)`.
  - `LoadResult(manifest: Manifest | None, errors: list[ValidationError])` — `@dataclass(frozen=True)`; `LoadResult.ok` property returns `not errors`.
  - `VALID_KINDS: frozenset[str]` = `{"executable", "launch_file", "process"}`.
  - `parse_manifest(data: object) -> LoadResult` — validates an already-parsed Python object (best-effort: builds the model where it can, collects every error).
  - `load_manifest(path: str) -> LoadResult` — reads the file, parses YAML, delegates to `parse_manifest`. On file-not-found or YAML syntax error returns `LoadResult(None, [ValidationError(...)])`.

Validation rules (each violation → one `ValidationError`; the model is still built best-effort so the TUI stays browsable):
- Top-level not a mapping → `manifest=None`, one error at location `"<root>"`.
- `machines`/`nodes` present but not a list → error; treat as empty.
- Machine missing `name`/`host`/`user` → error at `machines[i]`.
- Node missing `name` → error; node missing/empty/`non-list` `alternatives` → error at `nodes[i]`.
- `select` present and not `"single"` → error at `nodes[i]`.
- Duplicate node `name` → error at `nodes[i]`.
- Alternative missing `id` → error; `kind` missing or not in `VALID_KINDS` → error at `nodes[i].alternatives[j]`.
- Per-kind required fields missing: `executable` needs `package`+`executable`; `launch_file` needs `package`+`launch_file`; `process` needs `command` → error.
- Duplicate alternative `id` within a node → error.
- Alternative `machine` set but not a declared machine name → error.

- [ ] **Step 1: Write the failing tests**

```python
# tests/manifest/test_loader.py
import textwrap
from sheppy.manifest import parse_manifest, load_manifest, LoadResult


def _valid_data():
    return {
        "machines": [{"name": "robot", "host": "10.0.0.20", "user": "r"}],
        "nodes": [
            {"name": "camera", "select": "single", "alternatives": [
                {"id": "realsense", "kind": "launch_file", "package": "realsense2_camera",
                 "launch_file": "rs_launch.py", "machine": "robot",
                 "publishes": ["/camera/color/image_raw"]},
                {"id": "mock_camera", "kind": "executable", "package": "our_mocks",
                 "executable": "mock_camera"},
            ]},
            {"name": "sim_gui", "alternatives": [
                {"id": "unreal", "kind": "process", "command": "/opt/sim/Unreal -game"},
            ]},
        ],
    }


def test_valid_manifest_parses_clean():
    result = parse_manifest(_valid_data())
    assert result.ok
    assert result.errors == []
    assert [n.name for n in result.manifest.nodes] == ["camera", "sim_gui"]
    assert result.manifest.node("camera").alternatives[0].kind == "launch_file"


def test_top_level_not_mapping():
    result = parse_manifest(["not", "a", "mapping"])
    assert result.manifest is None
    assert len(result.errors) == 1
    assert result.errors[0].location == "<root>"


def test_unknown_machine_reference():
    data = _valid_data()
    data["nodes"][0]["alternatives"][0]["machine"] = "ghost"
    result = parse_manifest(data)
    assert not result.ok
    assert any("ghost" in e.message for e in result.errors)
    # still browsable: model built despite the error
    assert result.manifest is not None


def test_duplicate_node_name():
    data = _valid_data()
    data["nodes"].append({"name": "camera", "alternatives": [
        {"id": "x", "kind": "process", "command": "true"}]})
    result = parse_manifest(data)
    assert any("camera" in e.message and "duplicate" in e.message.lower()
               for e in result.errors)


def test_duplicate_alternative_id():
    data = _valid_data()
    data["nodes"][0]["alternatives"][1]["id"] = "realsense"
    result = parse_manifest(data)
    assert any("realsense" in e.message and "duplicate" in e.message.lower()
               for e in result.errors)


def test_bad_kind():
    data = _valid_data()
    data["nodes"][1]["alternatives"][0]["kind"] = "wizardry"
    result = parse_manifest(data)
    assert any(e.location == "nodes[1].alternatives[0]" for e in result.errors)


def test_missing_kind_fields():
    data = _valid_data()
    # executable alt missing 'executable'
    del data["nodes"][0]["alternatives"][1]["executable"]
    result = parse_manifest(data)
    assert any("executable" in e.message for e in result.errors)


def test_bad_select_value():
    data = _valid_data()
    data["nodes"][0]["select"] = "multi"
    result = parse_manifest(data)
    assert any("select" in e.message for e in result.errors)


def test_node_missing_alternatives():
    data = _valid_data()
    data["nodes"][0]["alternatives"] = []
    result = parse_manifest(data)
    assert any(e.location == "nodes[0]" for e in result.errors)


def test_load_missing_file():
    result = load_manifest("/no/such/system.yaml")
    assert result.manifest is None
    assert len(result.errors) == 1


def test_load_bad_yaml(tmp_path):
    p = tmp_path / "system.yaml"
    p.write_text("nodes: [unclosed\n")
    result = load_manifest(str(p))
    assert result.manifest is None
    assert len(result.errors) == 1


def test_load_valid_file(tmp_path):
    p = tmp_path / "system.yaml"
    p.write_text(textwrap.dedent("""
        machines:
          - {name: robot, host: 10.0.0.20, user: r}
        nodes:
          - name: camera
            alternatives:
              - {id: mock, kind: executable, package: our_mocks, executable: mock_camera}
    """))
    result = load_manifest(str(p))
    assert result.ok
    assert result.manifest.node("camera") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/manifest/test_loader.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_manifest'`

- [ ] **Step 3: Write minimal implementation**

```python
# sheppy/manifest/errors.py
from dataclasses import dataclass, field
from sheppy.manifest.models import Manifest


@dataclass(frozen=True)
class ValidationError:
    location: str
    message: str


@dataclass(frozen=True)
class LoadResult:
    manifest: Manifest | None
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors
```

```python
# sheppy/manifest/loader.py
import yaml
from sheppy.manifest.models import Machine, Alternative, Node, Manifest
from sheppy.manifest.errors import ValidationError, LoadResult

VALID_KINDS = frozenset({"executable", "launch_file", "process"})

_KIND_REQUIRED = {
    "executable": ("package", "executable"),
    "launch_file": ("package", "launch_file"),
    "process": ("command",),
}


def _build_alternative(raw: dict, loc: str, machine_names: set, errors: list) -> Alternative:
    alt_id = raw.get("id")
    if not alt_id:
        errors.append(ValidationError(loc, "alternative is missing 'id'"))
    kind = raw.get("kind")
    if kind not in VALID_KINDS:
        errors.append(ValidationError(
            loc, f"alternative '{alt_id}' has invalid kind {kind!r}; "
                 f"must be one of {sorted(VALID_KINDS)}"))
    else:
        for required in _KIND_REQUIRED[kind]:
            if not raw.get(required):
                errors.append(ValidationError(
                    loc, f"alternative '{alt_id}' of kind '{kind}' "
                         f"is missing '{required}'"))
    machine = raw.get("machine")
    if machine is not None and machine not in machine_names:
        errors.append(ValidationError(
            loc, f"alternative '{alt_id}' references unknown machine '{machine}'"))
    return Alternative(
        id=alt_id or "", kind=kind or "", machine=machine,
        package=raw.get("package"), executable=raw.get("executable"),
        launch_file=raw.get("launch_file"), command=raw.get("command"),
        params=raw.get("params") or {},
        publishes=raw.get("publishes") or [], subscribes=raw.get("subscribes") or [])


def _build_node(raw: dict, loc: str, machine_names: set, errors: list) -> Node:
    name = raw.get("name")
    if not name:
        errors.append(ValidationError(loc, "node is missing 'name'"))
    select = raw.get("select", "single")
    if select != "single":
        errors.append(ValidationError(loc, f"node 'select' must be 'single', got {select!r}"))
    raw_alts = raw.get("alternatives")
    alternatives = []
    if not isinstance(raw_alts, list) or not raw_alts:
        errors.append(ValidationError(loc, f"node '{name}' must have a non-empty 'alternatives' list"))
        raw_alts = raw_alts if isinstance(raw_alts, list) else []
    seen_ids = set()
    for j, raw_alt in enumerate(raw_alts):
        alt = _build_alternative(raw_alt, f"{loc}.alternatives[{j}]", machine_names, errors)
        if alt.id and alt.id in seen_ids:
            errors.append(ValidationError(
                f"{loc}.alternatives[{j}]", f"duplicate alternative id '{alt.id}'"))
        seen_ids.add(alt.id)
        alternatives.append(alt)
    return Node(name=name or "", alternatives=alternatives,
                description=raw.get("description", ""), select=select)


def parse_manifest(data: object) -> LoadResult:
    errors: list[ValidationError] = []
    if not isinstance(data, dict):
        return LoadResult(None, [ValidationError("<root>", "manifest must be a mapping")])

    raw_machines = data.get("machines", [])
    if not isinstance(raw_machines, list):
        errors.append(ValidationError("machines", "'machines' must be a list"))
        raw_machines = []
    machines = []
    for i, rm in enumerate(raw_machines):
        for required in ("name", "host", "user"):
            if not rm.get(required):
                errors.append(ValidationError(f"machines[{i}]", f"machine missing '{required}'"))
        machines.append(Machine(name=rm.get("name", ""), host=rm.get("host", ""),
                                user=rm.get("user", ""), ros_setup=rm.get("ros_setup")))
    machine_names = {m.name for m in machines}

    raw_nodes = data.get("nodes", [])
    if not isinstance(raw_nodes, list):
        errors.append(ValidationError("nodes", "'nodes' must be a list"))
        raw_nodes = []
    nodes = []
    seen_names = set()
    for i, rn in enumerate(raw_nodes):
        node = _build_node(rn, f"nodes[{i}]", machine_names, errors)
        if node.name and node.name in seen_names:
            errors.append(ValidationError(f"nodes[{i}]", f"duplicate node name '{node.name}'"))
        seen_names.add(node.name)
        nodes.append(node)

    return LoadResult(Manifest(machines=machines, nodes=nodes), errors)


def load_manifest(path: str) -> LoadResult:
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        return LoadResult(None, [ValidationError("<file>", f"manifest not found: {path}")])
    except yaml.YAMLError as exc:
        return LoadResult(None, [ValidationError("<file>", f"invalid YAML: {exc}")])
    return parse_manifest(raw)
```

```python
# sheppy/manifest/__init__.py
from sheppy.manifest.models import Machine, Alternative, Node, Manifest
from sheppy.manifest.errors import ValidationError, LoadResult
from sheppy.manifest.loader import parse_manifest, load_manifest, VALID_KINDS

__all__ = [
    "Machine", "Alternative", "Node", "Manifest",
    "ValidationError", "LoadResult",
    "parse_manifest", "load_manifest", "VALID_KINDS",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/manifest/test_loader.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add sheppy/manifest/ tests/manifest/test_loader.py
git commit -m "feat: add manifest loader and validation"
```

---

### Task 4: SelectionState

**Files:**
- Create: `sheppy/selection.py`
- Create: `tests/test_selection.py`

**Interfaces:**
- Consumes: `Manifest`, `Node` from `sheppy.manifest`.
- Produces: `SelectionState`:
  - `__init__(self, manifest: Manifest)`
  - `select(self, node_name: str, alternative_id: str) -> None` — sets the single active alternative for a node; raises `KeyError` if the node or alternative id is unknown; fires change listeners.
  - `clear(self, node_name: str) -> None` — unsets the node's selection (raises `KeyError` on unknown node); fires listeners.
  - `selected(self, node_name: str) -> str | None` — the selected alternative id, or `None`.
  - `on_change(self, callback)` — register `callback(node_name: str, alternative_id: str | None)`; called after each `select`/`clear`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selection.py
import pytest
from sheppy.manifest import Manifest, Node, Alternative
from sheppy.selection import SelectionState


def _manifest():
    return Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="realsense", kind="process", command="true"),
            Alternative(id="mock", kind="process", command="true"),
        ]),
    ])


def test_starts_unselected():
    state = SelectionState(_manifest())
    assert state.selected("camera") is None


def test_select_is_single():
    state = SelectionState(_manifest())
    state.select("camera", "realsense")
    assert state.selected("camera") == "realsense"
    state.select("camera", "mock")  # replaces — single-select
    assert state.selected("camera") == "mock"


def test_clear():
    state = SelectionState(_manifest())
    state.select("camera", "mock")
    state.clear("camera")
    assert state.selected("camera") is None


def test_unknown_node_or_alt_raises():
    state = SelectionState(_manifest())
    with pytest.raises(KeyError):
        state.select("ghost", "mock")
    with pytest.raises(KeyError):
        state.select("camera", "ghost")
    with pytest.raises(KeyError):
        state.clear("ghost")


def test_change_listener_fires():
    state = SelectionState(_manifest())
    events = []
    state.on_change(lambda node, alt: events.append((node, alt)))
    state.select("camera", "mock")
    state.clear("camera")
    assert events == [("camera", "mock"), ("camera", None)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_selection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy.selection'`

- [ ] **Step 3: Write minimal implementation**

```python
# sheppy/selection.py
from typing import Callable
from sheppy.manifest import Manifest

ChangeListener = Callable[[str, "str | None"], None]


class SelectionState:
    def __init__(self, manifest: Manifest) -> None:
        self._manifest = manifest
        self._selected: dict[str, str] = {}
        self._listeners: list[ChangeListener] = []

    def on_change(self, callback: ChangeListener) -> None:
        self._listeners.append(callback)

    def _notify(self, node_name: str, alt_id: "str | None") -> None:
        for cb in self._listeners:
            cb(node_name, alt_id)

    def _node(self, node_name: str):
        node = self._manifest.node(node_name)
        if node is None:
            raise KeyError(f"unknown node: {node_name}")
        return node

    def select(self, node_name: str, alternative_id: str) -> None:
        node = self._node(node_name)
        if not any(a.id == alternative_id for a in node.alternatives):
            raise KeyError(f"unknown alternative '{alternative_id}' for node '{node_name}'")
        self._selected[node_name] = alternative_id
        self._notify(node_name, alternative_id)

    def clear(self, node_name: str) -> None:
        self._node(node_name)
        self._selected.pop(node_name, None)
        self._notify(node_name, None)

    def selected(self, node_name: str) -> "str | None":
        return self._selected.get(node_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_selection.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add sheppy/selection.py tests/test_selection.py
git commit -m "feat: add in-memory single-select SelectionState"
```

---

### Task 5: TUI app skeleton with node + alternative navigation and selection

**Files:**
- Create: `sheppy/tui/__init__.py`
- Create: `sheppy/tui/app.py`
- Create: `tests/tui/__init__.py`
- Create: `tests/tui/test_app.py`

**Interfaces:**
- Consumes: `LoadResult`, `Manifest`, `Node` from `sheppy.manifest`; `SelectionState` from `sheppy.selection`.
- Produces: `SheppyApp(App)`:
  - `__init__(self, load_result: LoadResult)` — stores the result; builds a `SelectionState` if `load_result.manifest` is not `None`.
  - Composes a left `ListView#nodes` (one `ListItem` per node, each with a `Label` whose text is `"<name>  [<selected-or-—>]"`), and a right `ListView#alternatives` (rebuilt for the highlighted node).
  - Exposes `self.selection: SelectionState | None`.
  - Key/selection behavior: highlighting a node (re)populates `#alternatives`; pressing `enter` on an alternative calls `self.selection.select(node, alt)` and refreshes the node's label marker.
  - Each node `ListItem` has `id=f"node-{index}"`; each alternative `ListItem` has `id=f"alt-{index}"`, so tests can locate them.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tui/test_app.py
from sheppy.manifest import Manifest, Node, Alternative, LoadResult
from sheppy.tui.app import SheppyApp


def _result():
    manifest = Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="realsense", kind="process", command="true"),
            Alternative(id="mock", kind="process", command="true"),
        ]),
        Node(name="planner", alternatives=[
            Alternative(id="astar", kind="process", command="true"),
        ]),
    ])
    return LoadResult(manifest, [])


async def test_node_list_renders():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        nodes = app.query_one("#nodes")
        labels = [item.query_one("Label").renderable for item in nodes.children]
        text = "\n".join(str(label) for label in labels)
        assert "camera" in text and "planner" in text


async def test_highlighting_node_populates_alternatives():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        alts = app.query_one("#alternatives")
        text = "\n".join(str(i.query_one("Label").renderable) for i in alts.children)
        assert "realsense" in text and "mock" in text


async def test_selecting_alternative_updates_state_and_label():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        alts = app.query_one("#alternatives")
        alts.index = 1  # "mock"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.selection.selected("camera") == "mock"
        first_label = str(app.query_one("#node-0 Label").renderable)
        assert "mock" in first_label
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tui/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy.tui'`

- [ ] **Step 3: Write minimal implementation**

```python
# sheppy/tui/__init__.py
```

```python
# tests/tui/__init__.py
```

```python
# sheppy/tui/app.py
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Header, Footer, Label, ListView, ListItem

from sheppy.manifest import LoadResult, Node
from sheppy.selection import SelectionState


def _node_label(node: Node, selection: SelectionState | None) -> str:
    chosen = selection.selected(node.name) if selection else None
    return f"{node.name}  [{chosen or '—'}]"


class SheppyApp(App):
    CSS = """
    #nodes { width: 40%; border: solid $accent; }
    #alternatives { width: 60%; border: solid $accent; }
    """

    def __init__(self, load_result: LoadResult) -> None:
        super().__init__()
        self.load_result = load_result
        self.manifest = load_result.manifest
        self.selection: SelectionState | None = (
            SelectionState(self.manifest) if self.manifest else None)

    def compose(self) -> ComposeResult:
        yield Header()
        node_items = []
        if self.manifest:
            for i, node in enumerate(self.manifest.nodes):
                node_items.append(
                    ListItem(Label(_node_label(node, self.selection)), id=f"node-{i}"))
        yield Horizontal(
            ListView(*node_items, id="nodes"),
            ListView(id="alternatives"),
        )
        yield Footer()

    def _current_node(self) -> Node | None:
        if not self.manifest:
            return None
        idx = self.query_one("#nodes", ListView).index
        if idx is None:
            return None
        return self.manifest.nodes[idx]

    def _populate_alternatives(self, node: Node) -> None:
        alts = self.query_one("#alternatives", ListView)
        alts.clear()
        chosen = self.selection.selected(node.name) if self.selection else None
        for j, alt in enumerate(node.alternatives):
            marker = "•" if alt.id == chosen else " "
            alts.append(ListItem(Label(f"({marker}) {alt.id}  [{alt.kind}]"), id=f"alt-{j}"))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "nodes":
            node = self._current_node()
            if node:
                self._populate_alternatives(node)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "alternatives" or not self.selection:
            return
        node = self._current_node()
        alt_idx = self.query_one("#alternatives", ListView).index
        if node is None or alt_idx is None:
            return
        alt = node.alternatives[alt_idx]
        self.selection.select(node.name, alt.id)
        self._refresh_node_label(node)
        self._populate_alternatives(node)

    def _refresh_node_label(self, node: Node) -> None:
        idx = self.manifest.nodes.index(node)
        label = self.query_one(f"#node-{idx} Label", Label)
        label.update(_node_label(node, self.selection))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tui/test_app.py -v`
Expected: PASS (all three tests)

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/ tests/tui/
git commit -m "feat: add TUI app with node/alternative navigation and selection"
```

---

### Task 6: Detail pane, status bar, and error overlay

**Files:**
- Modify: `sheppy/tui/app.py`
- Modify: `tests/tui/test_app.py`

**Interfaces:**
- Consumes: everything from Task 5 plus `Alternative` from `sheppy.manifest`.
- Produces (additions to `SheppyApp`):
  - A `Static#detail` pane below `#alternatives` showing the highlighted alternative's fields: `kind`, the kind-relevant launch field (`package`/`executable`/`launch_file`/`command`), `machine`, `params`, `publishes`, `subscribes`.
  - A `Static#status` bar at the bottom showing `f"{path or '<no file>'} — {ok|N error(s)}"` where N is `len(load_result.errors)`. The app stores the manifest path via `SheppyApp(load_result, path: str | None = None)`.
  - An error overlay toggled by the `e` key: a `Static#errors` (hidden by default) listing each `ValidationError` as `f"{loc}: {message}"`. Visible state tracked by a `show_errors` reactive; `e` flips it.
  - Module-level `format_detail(alt: Alternative) -> str` (pure function, unit-testable without the UI).

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/tui/test_app.py
from sheppy.manifest import Alternative, ValidationError
from sheppy.tui.app import format_detail, SheppyApp


def test_format_detail_launch_file():
    alt = Alternative(id="rs", kind="launch_file", package="realsense2_camera",
                      launch_file="rs_launch.py", publishes=["/camera/img"])
    text = format_detail(alt)
    assert "launch_file" in text
    assert "realsense2_camera" in text and "rs_launch.py" in text
    assert "/camera/img" in text


def test_format_detail_process():
    alt = Alternative(id="u", kind="process", command="/opt/sim/Unreal -game")
    text = format_detail(alt)
    assert "/opt/sim/Unreal -game" in text


async def test_detail_updates_on_highlight():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        app.query_one("#alternatives").index = 0
        await pilot.pause()
        detail = str(app.query_one("#detail").renderable)
        assert "realsense" in detail or "process" in detail


async def test_status_bar_shows_error_count():
    result = LoadResult(_result().manifest,
                        [ValidationError("nodes[0]", "boom")])
    app = SheppyApp(result, path="system.yaml")
    async with app.run_test() as pilot:
        status = str(app.query_one("#status").renderable)
        assert "system.yaml" in status and "1 error" in status


async def test_error_overlay_toggles():
    result = LoadResult(_result().manifest,
                        [ValidationError("nodes[0]", "boom")])
    app = SheppyApp(result, path="system.yaml")
    async with app.run_test() as pilot:
        assert app.query_one("#errors").display is False
        await pilot.press("e")
        await pilot.pause()
        errors = app.query_one("#errors")
        assert errors.display is True
        assert "boom" in str(errors.renderable)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tui/test_app.py -v`
Expected: FAIL — `ImportError: cannot import name 'format_detail'`

- [ ] **Step 3: Write minimal implementation**

```python
# replace the top of sheppy/tui/app.py imports and add format_detail; update class

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Header, Footer, Label, ListView, ListItem, Static

from sheppy.manifest import LoadResult, Node, Alternative
from sheppy.selection import SelectionState


def format_detail(alt: Alternative) -> str:
    lines = [f"id: {alt.id}", f"kind: {alt.kind}"]
    if alt.kind == "executable":
        lines.append(f"package/executable: {alt.package} / {alt.executable}")
    elif alt.kind == "launch_file":
        lines.append(f"package/launch_file: {alt.package} / {alt.launch_file}")
    elif alt.kind == "process":
        lines.append(f"command: {alt.command}")
    lines.append(f"machine: {alt.machine or '—'}")
    lines.append(f"params: {alt.params or '—'}")
    lines.append(f"publishes: {', '.join(alt.publishes) or '—'}")
    lines.append(f"subscribes: {', '.join(alt.subscribes) or '—'}")
    return "\n".join(lines)
```

```python
# the SheppyApp class becomes (replacing the Task 5 version):

class SheppyApp(App):
    CSS = """
    #nodes { width: 40%; border: solid $accent; }
    #alternatives { height: 50%; border: solid $accent; }
    #detail { height: 50%; border: solid $accent; padding: 0 1; }
    #status { dock: bottom; height: 1; background: $panel; }
    #errors { dock: bottom; height: auto; background: $error; color: $text; padding: 0 1; }
    """
    BINDINGS = [("e", "toggle_errors", "Errors")]
    show_errors = reactive(False)

    def __init__(self, load_result: LoadResult, path: "str | None" = None) -> None:
        super().__init__()
        self.load_result = load_result
        self.path = path
        self.manifest = load_result.manifest
        self.selection = SelectionState(self.manifest) if self.manifest else None

    def compose(self) -> ComposeResult:
        yield Header()
        node_items = []
        if self.manifest:
            for i, node in enumerate(self.manifest.nodes):
                node_items.append(
                    ListItem(Label(_node_label(node, self.selection)), id=f"node-{i}"))
        yield Horizontal(
            ListView(*node_items, id="nodes"),
            Vertical(ListView(id="alternatives"), Static(id="detail")),
        )
        yield Static(self._status_text(), id="status")
        errors = Static(self._errors_text(), id="errors")
        errors.display = False
        yield errors
        yield Footer()

    def _status_text(self) -> str:
        n = len(self.load_result.errors)
        state = "ok" if n == 0 else f"{n} error(s)"
        return f"{self.path or '<no file>'} — {state}"

    def _errors_text(self) -> str:
        if not self.load_result.errors:
            return "no errors"
        return "\n".join(f"{e.location}: {e.message}" for e in self.load_result.errors)

    def action_toggle_errors(self) -> None:
        self.show_errors = not self.show_errors

    def watch_show_errors(self, value: bool) -> None:
        try:
            self.query_one("#errors").display = value
        except Exception:
            pass

    def _current_node(self) -> "Node | None":
        if not self.manifest:
            return None
        idx = self.query_one("#nodes", ListView).index
        return self.manifest.nodes[idx] if idx is not None else None

    def _populate_alternatives(self, node: Node) -> None:
        alts = self.query_one("#alternatives", ListView)
        alts.clear()
        chosen = self.selection.selected(node.name) if self.selection else None
        for j, alt in enumerate(node.alternatives):
            marker = "•" if alt.id == chosen else " "
            alts.append(ListItem(Label(f"({marker}) {alt.id}  [{alt.kind}]"), id=f"alt-{j}"))

    def _show_detail(self, node: Node) -> None:
        idx = self.query_one("#alternatives", ListView).index
        detail = self.query_one("#detail", Static)
        if idx is None or not node.alternatives:
            detail.update("")
            return
        detail.update(format_detail(node.alternatives[idx]))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "nodes":
            node = self._current_node()
            if node:
                self._populate_alternatives(node)
                self._show_detail(node)
        elif event.list_view.id == "alternatives":
            node = self._current_node()
            if node:
                self._show_detail(node)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "alternatives" or not self.selection:
            return
        node = self._current_node()
        alt_idx = self.query_one("#alternatives", ListView).index
        if node is None or alt_idx is None:
            return
        self.selection.select(node.name, node.alternatives[alt_idx].id)
        self._refresh_node_label(node)
        self._populate_alternatives(node)

    def _refresh_node_label(self, node: Node) -> None:
        idx = self.manifest.nodes.index(node)
        self.query_one(f"#node-{idx} Label", Label).update(_node_label(node, self.selection))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tui/test_app.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/app.py tests/tui/test_app.py
git commit -m "feat: add detail pane, status bar, and error overlay"
```

---

### Task 7: CLI entrypoint

**Files:**
- Create: `sheppy/cli.py`
- Create: `tests/test_cli.py`
- Create: `examples/system.yaml`

**Interfaces:**
- Consumes: `load_manifest` from `sheppy.manifest`; `SheppyApp` from `sheppy.tui.app`.
- Produces:
  - `build_app(argv: list[str]) -> SheppyApp` — resolves the manifest path (first positional arg, default `system.yaml`), calls `load_manifest`, and returns a `SheppyApp(result, path=path)`. Pure enough to test without running the UI.
  - `main(argv: list[str] | None = None) -> int` — builds the app and calls `app.run()`; returns `0`. Wired to the `sheppy` console script.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
from sheppy.cli import build_app


def test_build_app_loads_given_path():
    app = build_app(["examples/system.yaml"])
    assert app.manifest is not None
    assert app.manifest.node("camera") is not None
    assert app.path == "examples/system.yaml"


def test_build_app_missing_file_is_graceful():
    app = build_app(["/no/such/file.yaml"])
    assert app.manifest is None
    assert len(app.load_result.errors) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy.cli'`

- [ ] **Step 3: Write minimal implementation and the example manifest**

```python
# sheppy/cli.py
import sys
from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp


def build_app(argv: list[str]) -> SheppyApp:
    path = argv[0] if argv else "system.yaml"
    result = load_manifest(path)
    return SheppyApp(result, path=path)


def main(argv: "list[str] | None" = None) -> int:
    app = build_app(argv if argv is not None else sys.argv[1:])
    app.run()
    return 0
```

```yaml
# examples/system.yaml
machines:
  - {name: robot, host: 10.0.0.20, user: researcher, ros_setup: /opt/ros/humble/setup.bash}
  - {name: workstation, host: 10.0.0.5, user: researcher}

nodes:
  - name: camera
    description: "RGB-D source"
    select: single
    alternatives:
      - id: realsense
        kind: launch_file
        package: realsense2_camera
        launch_file: rs_launch.py
        machine: robot
        publishes: [/camera/color/image_raw, /camera/depth/points]
      - id: mock_camera
        kind: executable
        package: our_mocks
        executable: mock_camera
        machine: workstation
        publishes: [/camera/color/image_raw]

  - name: sim_gui
    select: single
    alternatives:
      - id: unreal
        kind: process
        command: "/opt/sim/UnrealEditor MyProject -game"
        machine: workstation
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite and the app manually**

Run: `python -m pytest -v`
Expected: PASS (entire suite)
Run (manual smoke, optional): `sheppy examples/system.yaml` — browse nodes/alternatives, press `enter` to select, `e` to toggle errors, `ctrl+c`/`q` to quit.

- [ ] **Step 6: Commit**

```bash
git add sheppy/cli.py tests/test_cli.py examples/system.yaml
git commit -m "feat: add sheppy CLI entrypoint and example manifest"
```

---

## Self-Review Notes

- **Spec coverage:** manifest schema (Tasks 2–3, §4), validation rules incl. unknown-machine/dup-id/per-kind-fields/select (Task 3, §4), single-select `SelectionState` (Task 4, §5 components), node list + detail pane + status bar (Tasks 5–6, §5), error overlay / never-crash (Tasks 3 & 6, §5 error handling), model/state separated from widgets (Tasks 2–4 pure Python; Tasks 5–6 thin TUI), testing approach incl. pilot tests (every task). Out-of-scope items (daemon, launching, profiles, SSH, introspection, add-from-executables) are not implemented — correct for Phase 1.
- **Naming consistency:** `LoadResult`, `parse_manifest`, `load_manifest`, `VALID_KINDS`, `SelectionState.select/clear/selected/on_change`, `SheppyApp`, `format_detail`, `build_app`, `main` are used consistently across producing and consuming tasks.
- **No placeholders:** every code step contains complete code; every run step lists the exact command and expected result.
