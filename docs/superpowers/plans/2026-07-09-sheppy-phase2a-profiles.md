# Sheppy Phase 2a — Profiles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save and load named selection sets (which alternative is active per node) plus declared-param overrides, as per-profile YAML files, managed from the TUI.

**Architecture:** A new `sheppy/profiles/` package holds four pure-logic units — `models` (the `Profile` dataclass), `store` (YAML file I/O), `reconcile` (drop manifest-drifted entries), and `state` (`ProfileState`, which *composes* the Phase 1 `SelectionState` and adds override + save/load lifecycle). The TUI swaps its bare `SelectionState` for a `ProfileState`, gains a profile bar, and three modal flows: save, load/delete, and a param editor.

**Tech Stack:** Python 3.10+, Textual 8.2.7, PyYAML, pytest + pytest-asyncio, uv.

**Spec:** `docs/superpowers/specs/2026-06-26-sheppy-phase2a-profiles-design.md`

## Global Constraints

- **Python `>=3.10`.** Use `str | None` union syntax; `dict`/`list` as generics.
- **uv only.** Run tests with `uv run pytest`. No new runtime deps (PyYAML is already a dependency); no `uv.lock` change expected.
- **Never crash.** `ProfileStore.load`, `list_profiles`, `delete`, and `reconcile` never raise. The sole intentional raise is `ProfileStore.save` → `ValueError` on an invalid name, and `ProfileState.override` → `KeyError` on an undeclared param.
- **Profile names** must match `^[A-Za-z0-9_-]+$`. Define this regex once as `NAME_RE` in `sheppy/profiles/store.py` and import it where else needed.
- **Filename is canonical.** A profile's name is its filename stem; the YAML file never stores its own name.
- **Profiles directory** = `<dirname(manifest_path)>/profiles`, derived in `sheppy/cli.py`.
- **Textual 8.2.7 specifics:** `Static`/`Label` expose text via `.content` (NOT `.renderable`). `ListView.clear()` and `.append()` return awaitables — `await` them in async handlers. Modals subclass `ModalScreen` from `textual.screen`; open with `self.push_screen(modal, callback)`; return a value with `self.dismiss(value)`.
- **Testing style:** pure units tested without the UI; TUI exercised with Textual's async pilot (`app.run_test()`).

---

## File Structure

```
sheppy/profiles/__init__.py      # re-exports Profile, ProfileStore, ProfileLoadResult,
                                 #   reconcile, ReconcileResult, ProfileState
sheppy/profiles/models.py        # Profile dataclass
sheppy/profiles/store.py         # ProfileStore, ProfileLoadResult, NAME_RE
sheppy/profiles/reconcile.py     # reconcile(), ReconcileResult
sheppy/profiles/state.py         # ProfileState (composes SelectionState)
sheppy/tui/profile_modals.py     # SaveNameModal, LoadModal, ConfirmModal, ParamEditorModal
sheppy/tui/app.py                # wire ProfileStore + ProfileState; profile bar; key bindings
sheppy/cli.py                    # derive profiles_dir; pass to SheppyApp
tests/profiles/__init__.py
tests/profiles/test_models.py
tests/profiles/test_store.py
tests/profiles/test_reconcile.py
tests/profiles/test_state.py
tests/tui/test_profiles.py       # pilot tests for save/load/param-editor flows
```

Reference (Phase 1, unchanged — do not modify):
- `sheppy/manifest/models.py`: `Manifest.node(name) -> Node | None`; `Node(name, alternatives, description="", select="single")`; `Alternative(id, kind, machine=None, package=None, executable=None, launch_file=None, command=None, params={}, publishes=[], subscribes=[])`.
- `sheppy/selection.py`: `SelectionState(manifest)` with `select(node, alt)` (raises `KeyError` on unknown node/alt), `clear(node)`, `selected(node) -> str | None`.

---

### Task 1: `Profile` model

**Files:**
- Create: `sheppy/profiles/__init__.py`
- Create: `sheppy/profiles/models.py`
- Create: `tests/profiles/__init__.py`
- Test: `tests/profiles/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Profile(name: str, selections: dict[str, str] = {}, overrides: dict[str, dict[str, object]] = {}, description: str = "")` — frozen dataclass with `field(default_factory=...)` for the two dict fields.

- [ ] **Step 1: Write the failing test**

```python
# tests/profiles/test_models.py
from sheppy.profiles import Profile


def test_profile_defaults_are_independent():
    a = Profile(name="a")
    b = Profile(name="b")
    a.selections["camera"] = "mock"
    assert b.selections == {}          # mutable defaults must not be shared


def test_profile_holds_fields():
    p = Profile(
        name="all-mock",
        selections={"camera": "mock_camera"},
        overrides={"camera": {"fps": 30}},
        description="desk testing",
    )
    assert p.name == "all-mock"
    assert p.selections["camera"] == "mock_camera"
    assert p.overrides["camera"]["fps"] == 30
    assert p.description == "desk testing"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/profiles/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy.profiles'`.

- [ ] **Step 3: Write minimal implementation**

```python
# tests/profiles/__init__.py
```
(empty file)

```python
# sheppy/profiles/models.py
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    name: str
    selections: dict[str, str] = field(default_factory=dict)
    overrides: dict[str, dict[str, object]] = field(default_factory=dict)
    description: str = ""
```

```python
# sheppy/profiles/__init__.py
from sheppy.profiles.models import Profile

__all__ = ["Profile"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/profiles/test_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add sheppy/profiles/__init__.py sheppy/profiles/models.py tests/profiles/__init__.py tests/profiles/test_models.py
git commit -m "feat(profiles): add Profile model"
```

---

### Task 2: `ProfileStore` (YAML file I/O)

**Files:**
- Create: `sheppy/profiles/store.py`
- Modify: `sheppy/profiles/__init__.py`
- Test: `tests/profiles/test_store.py`

**Interfaces:**
- Consumes: `Profile` (Task 1).
- Produces:
  - `NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")`
  - `ProfileLoadResult(profile: Profile | None, errors: list[str])` — frozen dataclass.
  - `ProfileStore(profiles_dir: str)` with:
    - `list_profiles() -> list[str]` — sorted stems of `*.yaml`; `[]` if dir absent.
    - `load(name: str) -> ProfileLoadResult` — never raises.
    - `save(profile: Profile) -> None` — raises `ValueError` if `profile.name` fails `NAME_RE`.
    - `delete(name: str) -> None` — idempotent; never raises.

- [ ] **Step 1: Write the failing test**

```python
# tests/profiles/test_store.py
from sheppy.profiles import Profile
from sheppy.profiles.store import ProfileStore
import pytest


def test_save_then_load_round_trip(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    p = Profile(name="all-mock",
                selections={"camera": "mock_camera"},
                overrides={"camera": {"fps": 30}},
                description="desk testing")
    store.save(p)
    res = store.load("all-mock")
    assert res.errors == []
    assert res.profile == p


def test_list_profiles_sorted_and_empty(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    assert store.list_profiles() == []          # dir does not exist yet
    store.save(Profile(name="zeta"))
    store.save(Profile(name="alpha"))
    assert store.list_profiles() == ["alpha", "zeta"]


def test_load_missing_file_returns_error(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    res = store.load("nope")
    assert res.profile is None
    assert len(res.errors) == 1


def test_load_bad_yaml_returns_error(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    (d / "broken.yaml").write_text("selections: [unclosed\n")
    store = ProfileStore(str(d))
    res = store.load("broken")
    assert res.profile is None
    assert len(res.errors) == 1


def test_save_rejects_bad_name(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    with pytest.raises(ValueError):
        store.save(Profile(name="bad name!"))


def test_delete_is_idempotent(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    store.save(Profile(name="temp"))
    store.delete("temp")
    store.delete("temp")           # second delete must not raise
    assert store.list_profiles() == []


def test_empty_profile_round_trips(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    store.save(Profile(name="empty"))
    res = store.load("empty")
    assert res.profile == Profile(name="empty")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/profiles/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy.profiles.store'`.

- [ ] **Step 3: Write minimal implementation**

```python
# sheppy/profiles/store.py
import os
import re
from dataclasses import dataclass

import yaml

from sheppy.profiles.models import Profile

NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class ProfileLoadResult:
    profile: "Profile | None"
    errors: list


class ProfileStore:
    def __init__(self, profiles_dir: str) -> None:
        self._dir = profiles_dir

    def _path(self, name: str) -> str:
        return os.path.join(self._dir, f"{name}.yaml")

    def list_profiles(self) -> list:
        if not os.path.isdir(self._dir):
            return []
        stems = [fn[:-5] for fn in os.listdir(self._dir) if fn.endswith(".yaml")]
        return sorted(stems)

    def load(self, name: str) -> ProfileLoadResult:
        path = self._path(name)
        if not os.path.isfile(path):
            return ProfileLoadResult(None, [f"profile not found: {name}"])
        try:
            with open(path) as f:
                raw = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return ProfileLoadResult(None, [f"invalid YAML in profile '{name}': {e}"])
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            return ProfileLoadResult(None, [f"profile '{name}' is not a mapping"])
        errors: list = []
        selections = raw.get("selections") or {}
        overrides = raw.get("overrides") or {}
        description = raw.get("description") or ""
        if not isinstance(selections, dict):
            errors.append(f"profile '{name}': 'selections' is not a mapping; ignored")
            selections = {}
        if not isinstance(overrides, dict):
            errors.append(f"profile '{name}': 'overrides' is not a mapping; ignored")
            overrides = {}
        profile = Profile(
            name=name,
            selections=dict(selections),
            overrides={k: dict(v) for k, v in overrides.items() if isinstance(v, dict)},
            description=str(description),
        )
        return ProfileLoadResult(profile, errors)

    def save(self, profile: Profile) -> None:
        if not NAME_RE.match(profile.name):
            raise ValueError(f"invalid profile name: {profile.name!r}")
        os.makedirs(self._dir, exist_ok=True)
        data: dict = {}
        if profile.description:
            data["description"] = profile.description
        if profile.selections:
            data["selections"] = dict(profile.selections)
        if profile.overrides:
            data["overrides"] = {k: dict(v) for k, v in profile.overrides.items()}
        with open(self._path(profile.name), "w") as f:
            yaml.safe_dump(data, f, sort_keys=True, default_flow_style=False)

    def delete(self, name: str) -> None:
        try:
            os.remove(self._path(name))
        except FileNotFoundError:
            pass
```

Then extend the package exports:

```python
# sheppy/profiles/__init__.py
from sheppy.profiles.models import Profile
from sheppy.profiles.store import ProfileStore, ProfileLoadResult, NAME_RE

__all__ = ["Profile", "ProfileStore", "ProfileLoadResult", "NAME_RE"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/profiles/test_store.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add sheppy/profiles/store.py sheppy/profiles/__init__.py tests/profiles/test_store.py
git commit -m "feat(profiles): add ProfileStore YAML persistence"
```

---

### Task 3: `reconcile` (drop manifest-drifted entries)

**Files:**
- Create: `sheppy/profiles/reconcile.py`
- Modify: `sheppy/profiles/__init__.py`
- Test: `tests/profiles/test_reconcile.py`

**Interfaces:**
- Consumes: `Profile` (Task 1); `Manifest`, `Node`, `Alternative` from `sheppy.manifest`.
- Produces:
  - `ReconcileResult(selections: dict[str, str], overrides: dict[str, dict[str, object]], warnings: list[str])` — frozen dataclass.
  - `reconcile(profile: Profile, manifest: Manifest) -> ReconcileResult` — never raises. Drops, with one warning each: a selection whose node is missing or whose alt id is unknown; an override on a node not in the cleaned selections; an override key not declared in the selected alternative's `params`.

- [ ] **Step 1: Write the failing test**

```python
# tests/profiles/test_reconcile.py
from sheppy.manifest import Manifest, Node, Alternative
from sheppy.profiles import Profile
from sheppy.profiles.reconcile import reconcile


def _manifest():
    return Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="mock", kind="process", command="true", params={"fps": 15}),
            Alternative(id="real", kind="process", command="true"),
        ]),
    ])


def test_clean_profile_passes_through():
    p = Profile(name="p", selections={"camera": "mock"},
                overrides={"camera": {"fps": 30}})
    r = reconcile(p, _manifest())
    assert r.selections == {"camera": "mock"}
    assert r.overrides == {"camera": {"fps": 30}}
    assert r.warnings == []


def test_unknown_node_selection_dropped():
    p = Profile(name="p", selections={"ghost": "x"})
    r = reconcile(p, _manifest())
    assert r.selections == {}
    assert len(r.warnings) == 1


def test_unknown_alternative_dropped():
    p = Profile(name="p", selections={"camera": "nope"})
    r = reconcile(p, _manifest())
    assert r.selections == {}
    assert len(r.warnings) == 1


def test_override_on_unselected_node_dropped():
    p = Profile(name="p", selections={}, overrides={"camera": {"fps": 30}})
    r = reconcile(p, _manifest())
    assert r.overrides == {}
    assert len(r.warnings) == 1


def test_undeclared_override_key_dropped():
    # "real" declares no params, so fps is undeclared for it
    p = Profile(name="p", selections={"camera": "real"},
                overrides={"camera": {"fps": 30}})
    r = reconcile(p, _manifest())
    assert r.selections == {"camera": "real"}
    assert r.overrides == {}
    assert len(r.warnings) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/profiles/test_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy.profiles.reconcile'`.

- [ ] **Step 3: Write minimal implementation**

```python
# sheppy/profiles/reconcile.py
from dataclasses import dataclass

from sheppy.manifest import Manifest
from sheppy.profiles.models import Profile


@dataclass(frozen=True)
class ReconcileResult:
    selections: dict
    overrides: dict
    warnings: list


def _selected_alt(manifest: Manifest, node_name: str, alt_id: str):
    node = manifest.node(node_name)
    if node is None:
        return None
    for a in node.alternatives:
        if a.id == alt_id:
            return a
    return None


def reconcile(profile: Profile, manifest: Manifest) -> ReconcileResult:
    warnings: list = []
    selections: dict = {}
    for node_name, alt_id in profile.selections.items():
        node = manifest.node(node_name)
        if node is None:
            warnings.append(f"dropped selection: unknown node '{node_name}'")
            continue
        if not any(a.id == alt_id for a in node.alternatives):
            warnings.append(
                f"dropped selection: node '{node_name}' has no alternative '{alt_id}'")
            continue
        selections[node_name] = alt_id

    overrides: dict = {}
    for node_name, params in profile.overrides.items():
        if node_name not in selections:
            warnings.append(
                f"dropped overrides for '{node_name}': node is not selected")
            continue
        alt = _selected_alt(manifest, node_name, selections[node_name])
        declared = alt.params if alt else {}
        kept: dict = {}
        for key, value in params.items():
            if key not in declared:
                warnings.append(
                    f"dropped override '{node_name}.{key}': not a declared param")
                continue
            kept[key] = value
        if kept:
            overrides[node_name] = kept

    return ReconcileResult(selections=selections, overrides=overrides, warnings=warnings)
```

Then extend exports:

```python
# sheppy/profiles/__init__.py
from sheppy.profiles.models import Profile
from sheppy.profiles.store import ProfileStore, ProfileLoadResult, NAME_RE
from sheppy.profiles.reconcile import reconcile, ReconcileResult

__all__ = [
    "Profile", "ProfileStore", "ProfileLoadResult", "NAME_RE",
    "reconcile", "ReconcileResult",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/profiles/test_reconcile.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add sheppy/profiles/reconcile.py sheppy/profiles/__init__.py tests/profiles/test_reconcile.py
git commit -m "feat(profiles): add reconcile for manifest drift"
```

---

### Task 4: `ProfileState` (composes `SelectionState`)

**Files:**
- Create: `sheppy/profiles/state.py`
- Modify: `sheppy/profiles/__init__.py`
- Test: `tests/profiles/test_state.py`

**Interfaces:**
- Consumes: `SelectionState` (`sheppy.selection`); `Manifest`, `Alternative` (`sheppy.manifest`); `Profile` (Task 1).
- Produces `ProfileState(manifest)` with:
  - `select(node, alt) -> None`, `clear(node) -> None`, `selected(node) -> str | None` — passthroughs to the inner `SelectionState`; `select`/`clear` set `is_dirty = True`.
  - `selected_alt(node_name) -> Alternative | None` — the currently-selected alternative object, or `None`.
  - `override(node_name, param, value) -> None` — raises `KeyError` if `param` is not declared on the selected alternative (or none is selected); a value equal to the manifest default clears the override; sets `is_dirty = True`.
  - `clear_override(node_name, param) -> None` — sets `is_dirty = True`.
  - `effective_params(node_name) -> dict` — selected alternative's `params` merged with this node's overrides; `{}` if nothing selected.
  - `apply(selections: dict, overrides: dict, profile_name: str | None) -> None` — replace working state; set `active_profile_name`; clear `is_dirty`.
  - `to_profile(name) -> Profile` — snapshot current selections + non-empty overrides.
  - `mark_saved(name: str) -> None` — set `active_profile_name = name`, `is_dirty = False`.
  - attributes `active_profile_name: str | None` (init `None`), `is_dirty: bool` (init `False`).

- [ ] **Step 1: Write the failing test**

```python
# tests/profiles/test_state.py
from sheppy.manifest import Manifest, Node, Alternative
from sheppy.profiles import Profile, reconcile
from sheppy.profiles.state import ProfileState
import pytest


def _manifest():
    return Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="mock", kind="process", command="true", params={"fps": 15}),
            Alternative(id="real", kind="process", command="true"),
        ]),
    ])


def test_select_marks_dirty():
    st = ProfileState(_manifest())
    assert st.is_dirty is False
    st.select("camera", "mock")
    assert st.selected("camera") == "mock"
    assert st.is_dirty is True


def test_override_and_effective_params():
    st = ProfileState(_manifest())
    st.select("camera", "mock")
    st.override("camera", "fps", 30)
    assert st.effective_params("camera") == {"fps": 30}


def test_override_equal_to_default_is_dropped():
    st = ProfileState(_manifest())
    st.select("camera", "mock")
    st.override("camera", "fps", 30)
    st.override("camera", "fps", 15)          # back to the manifest default
    assert st.effective_params("camera") == {"fps": 15}
    assert st.to_profile("p").overrides == {}   # nothing stored


def test_override_undeclared_param_raises():
    st = ProfileState(_manifest())
    st.select("camera", "real")               # "real" declares no params
    with pytest.raises(KeyError):
        st.override("camera", "fps", 30)


def test_apply_sets_active_name_and_clears_dirty():
    st = ProfileState(_manifest())
    p = Profile(name="all-mock", selections={"camera": "mock"},
                overrides={"camera": {"fps": 30}})
    r = reconcile(p, _manifest())
    st.apply(r.selections, r.overrides, "all-mock")
    assert st.selected("camera") == "mock"
    assert st.effective_params("camera") == {"fps": 30}
    assert st.active_profile_name == "all-mock"
    assert st.is_dirty is False


def test_mutation_after_apply_sets_dirty():
    st = ProfileState(_manifest())
    st.apply({"camera": "mock"}, {}, "all-mock")
    assert st.is_dirty is False
    st.select("camera", "real")
    assert st.is_dirty is True


def test_to_profile_round_trips_through_reconcile():
    st = ProfileState(_manifest())
    st.select("camera", "mock")
    st.override("camera", "fps", 30)
    p = st.to_profile("snapshot")
    r = reconcile(p, _manifest())
    assert r.selections == {"camera": "mock"}
    assert r.overrides == {"camera": {"fps": 30}}


def test_mark_saved_clears_dirty():
    st = ProfileState(_manifest())
    st.select("camera", "mock")
    assert st.is_dirty is True
    st.mark_saved("all-mock")
    assert st.active_profile_name == "all-mock"
    assert st.is_dirty is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/profiles/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheppy.profiles.state'`.

- [ ] **Step 3: Write minimal implementation**

```python
# sheppy/profiles/state.py
from sheppy.manifest import Manifest
from sheppy.profiles.models import Profile
from sheppy.selection import SelectionState


class ProfileState:
    def __init__(self, manifest: Manifest) -> None:
        self._manifest = manifest
        self._selection = SelectionState(manifest)
        self._overrides: dict = {}
        self.active_profile_name: "str | None" = None
        self.is_dirty: bool = False

    # --- selection passthroughs ---
    def select(self, node_name: str, alternative_id: str) -> None:
        self._selection.select(node_name, alternative_id)
        self.is_dirty = True

    def clear(self, node_name: str) -> None:
        self._selection.clear(node_name)
        self.is_dirty = True

    def selected(self, node_name: str) -> "str | None":
        return self._selection.selected(node_name)

    def selected_alt(self, node_name: str):
        alt_id = self._selection.selected(node_name)
        if alt_id is None:
            return None
        node = self._manifest.node(node_name)
        if node is None:
            return None
        for a in node.alternatives:
            if a.id == alt_id:
                return a
        return None

    # --- overrides ---
    def override(self, node_name: str, param: str, value: object) -> None:
        alt = self.selected_alt(node_name)
        if alt is None or param not in alt.params:
            raise KeyError(
                f"param '{param}' is not declared on the selected alternative "
                f"for node '{node_name}'")
        if value == alt.params[param]:
            self.clear_override(node_name, param)
            return
        self._overrides.setdefault(node_name, {})[param] = value
        self.is_dirty = True

    def clear_override(self, node_name: str, param: str) -> None:
        node_overrides = self._overrides.get(node_name)
        if node_overrides is not None:
            node_overrides.pop(param, None)
            if not node_overrides:
                self._overrides.pop(node_name, None)
        self.is_dirty = True

    def effective_params(self, node_name: str) -> dict:
        alt = self.selected_alt(node_name)
        if alt is None:
            return {}
        merged = dict(alt.params)
        merged.update(self._overrides.get(node_name, {}))
        return merged

    # --- lifecycle ---
    def apply(self, selections: dict, overrides: dict,
              profile_name: "str | None") -> None:
        self._selection = SelectionState(self._manifest)
        for node_name, alt_id in selections.items():
            self._selection.select(node_name, alt_id)
        self._overrides = {n: dict(p) for n, p in overrides.items()}
        self.active_profile_name = profile_name
        self.is_dirty = False

    def to_profile(self, name: str) -> Profile:
        selections: dict = {}
        for node in self._manifest.nodes:
            sel = self._selection.selected(node.name)
            if sel is not None:
                selections[node.name] = sel
        overrides = {n: dict(p) for n, p in self._overrides.items() if p}
        return Profile(name=name, selections=selections, overrides=overrides)

    def mark_saved(self, name: str) -> None:
        self.active_profile_name = name
        self.is_dirty = False
```

Then extend exports:

```python
# sheppy/profiles/__init__.py
from sheppy.profiles.models import Profile
from sheppy.profiles.store import ProfileStore, ProfileLoadResult, NAME_RE
from sheppy.profiles.reconcile import reconcile, ReconcileResult
from sheppy.profiles.state import ProfileState

__all__ = [
    "Profile", "ProfileStore", "ProfileLoadResult", "NAME_RE",
    "reconcile", "ReconcileResult", "ProfileState",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/profiles/test_state.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add sheppy/profiles/state.py sheppy/profiles/__init__.py tests/profiles/test_state.py
git commit -m "feat(profiles): add ProfileState composing SelectionState"
```

---

### Task 5: Wire `ProfileState` + profile bar into the TUI

Swap the app's bare `SelectionState` for a `ProfileState`, derive the profiles directory in the CLI, and render a profile bar that reflects the active name and dirty flag. No modals yet.

**Files:**
- Modify: `sheppy/tui/app.py`
- Modify: `sheppy/cli.py`
- Modify: `tests/tui/test_app.py` (rename `app.selection` → `app.state`)
- Test: `tests/tui/test_profiles.py` (new — profile-bar assertions)

**Interfaces:**
- Consumes: `ProfileState`, `ProfileStore` (Tasks 2, 4).
- Produces on `SheppyApp`: attribute `self.state: ProfileState | None` (replaces `self.selection`); attribute `self.store: ProfileStore | None`; `__init__(self, load_result, path=None, profiles_dir=None)`; method `_refresh_profile_bar() -> None`; a `Static(id="profilebar")`.
  `build_app` derives `profiles_dir = os.path.join(os.path.dirname(path), "profiles")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/tui/test_profiles.py
import os
from sheppy.manifest import Manifest, Node, Alternative, LoadResult
from sheppy.tui.app import SheppyApp


def _result():
    manifest = Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="mock", kind="process", command="true", params={"fps": 15}),
            Alternative(id="real", kind="process", command="true"),
        ]),
    ])
    return LoadResult(manifest, [])


async def test_profile_bar_starts_none(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        bar = str(app.query_one("#profilebar").content)
        assert "none" in bar.lower()


async def test_selecting_marks_profile_bar_dirty(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        await pilot.press("enter")            # descend into alternatives
        await pilot.pause()
        app.query_one("#alternatives").index = 0
        await pilot.pause()
        await pilot.press("enter")            # select "mock"
        await pilot.pause()
        assert app.state.selected("camera") == "mock"
        bar = str(app.query_one("#profilebar").content)
        assert "*" in bar                     # dirty marker
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_profiles.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'profiles_dir'` (or `NoMatches` for `#profilebar`).

- [ ] **Step 3: Write minimal implementation**

In `sheppy/tui/app.py`, update imports and the class. Replace the `SelectionState` import and the `__init__`/`compose` wiring:

```python
# top of sheppy/tui/app.py — swap the selection import
from sheppy.profiles import ProfileState, ProfileStore
```
(Remove `from sheppy.selection import SelectionState`. Keep the `_node_label`/`format_detail` helpers unchanged — they only call `.selected(...)`, which `ProfileState` provides.)

Update the type hint on `_node_label`'s second parameter for clarity:

```python
def _node_label(node: Node, state: "ProfileState | None") -> str:
    chosen = state.selected(node.name) if state else None
    return f"{node.name}  [{chosen or '—'}]"
```

Rewrite `__init__`:

```python
    def __init__(self, load_result: LoadResult, path: str | None = None,
                 profiles_dir: str | None = None) -> None:
        super().__init__()
        self.load_result = load_result
        self.path = path
        self.manifest = load_result.manifest
        self.state: "ProfileState | None" = (
            ProfileState(self.manifest) if self.manifest else None)
        self.store: "ProfileStore | None" = (
            ProfileStore(profiles_dir) if profiles_dir else None)
```

In `compose`, pass `self.state` to `_node_label`, and add the profile bar directly under the header:

```python
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._profile_bar_text(), id="profilebar")
        node_items = []
        if self.manifest:
            for i, node in enumerate(self.manifest.nodes):
                node_items.append(
                    ListItem(Label(_node_label(node, self.state)), id=f"node-{i}"))
        yield Horizontal(
            ListView(*node_items, id="nodes"),
            Vertical(
                ListView(id="alternatives"),
                Static(id="detail"),
            ),
        )
        yield Static(self._status_text(), id="status")
        errors = Static(self._errors_text(), id="errors")
        errors.display = False
        yield errors
        yield Footer()
```

Add the bar helpers (place near `_status_text`):

```python
    def _profile_bar_text(self) -> str:
        if not self.state:
            return "Profile: <none>"
        name = self.state.active_profile_name or "<none>"
        dirty = " *" if self.state.is_dirty else ""
        return f"Profile: {name}{dirty}"

    def _refresh_profile_bar(self) -> None:
        try:
            self.query_one("#profilebar", Static).update(self._profile_bar_text())
        except NoMatches:
            pass
```

Add a CSS rule for the bar (inside the `CSS` string):

```
    #profilebar { dock: top; height: 1; background: $boost; color: $text; padding: 0 1; }
```

Replace every remaining `self.selection` with `self.state` in the file. Specifically in `_populate_alternatives`:

```python
        chosen = self.state.selected(node.name) if self.state else None
```

and in `on_list_view_selected` (the guard and the select call):

```python
        if event.list_view.id != "alternatives" or not self.state:
            return
        node = self._current_node()
        alt_idx = self.query_one("#alternatives", ListView).index
        if node is None or alt_idx is None:
            return
        alt = node.alternatives[alt_idx]
        self.state.select(node.name, alt.id)
        self._refresh_node_label(node)
        self._refresh_profile_bar()
        await self._populate_alternatives(node)
```

and in `_refresh_node_label`:

```python
        label.update(_node_label(node, self.state))
```

Update `sheppy/cli.py`:

```python
# sheppy/cli.py
import os
import sys
from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp


def build_app(argv: list[str]) -> SheppyApp:
    path = argv[0] if argv else "system.yaml"
    result = load_manifest(path)
    profiles_dir = os.path.join(os.path.dirname(os.path.abspath(path)), "profiles")
    return SheppyApp(result, path=path, profiles_dir=profiles_dir)


def main(argv: "list[str] | None" = None) -> int:
    app = build_app(argv if argv is not None else sys.argv[1:])
    app.run()
    return 0
```

Update `tests/tui/test_app.py`: replace the two occurrences of `app.selection` with `app.state` (in `test_selecting_alternative_updates_state_and_label`). No other test changes.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/tui/ -v`
Expected: PASS — the two new profile-bar tests plus the existing app tests (with the `app.state` rename) all pass.

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/app.py sheppy/cli.py tests/tui/test_app.py tests/tui/test_profiles.py
git commit -m "feat(tui): wire ProfileState and profile bar"
```

---

### Task 6: Save flow (`SaveNameModal` + `s` binding)

**Files:**
- Create: `sheppy/tui/profile_modals.py`
- Modify: `sheppy/tui/app.py`
- Test: `tests/tui/test_profiles.py` (append)

**Interfaces:**
- Consumes: `NAME_RE` (`sheppy.profiles`); `ProfileState`, `ProfileStore` (Tasks 2, 4).
- Produces: `SaveNameModal(ModalScreen[str | None])` — dismisses with a validated name, or `None` on cancel. On `SheppyApp`: binding `("s", "save_profile", "Save")`; `action_save_profile()`; callback `_on_save_name(name)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/tui/test_profiles.py  (append)
async def test_save_writes_file_and_updates_bar(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        # select an alternative so there is something to save
        app.query_one("#nodes").index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        app.query_one("#alternatives").index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        # open the save modal, type a name, submit
        await pilot.press("s")
        await pilot.pause()
        for ch in "desk":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert os.path.isfile(os.path.join(str(tmp_path), "desk.yaml"))
        bar = str(app.query_one("#profilebar").content)
        assert "desk" in bar and "*" not in bar       # saved → not dirty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_profiles.py::test_save_writes_file_and_updates_bar -v`
Expected: FAIL — no `s` binding / `SaveNameModal` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# sheppy/tui/profile_modals.py
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label

from sheppy.profiles import NAME_RE


class SaveNameModal(ModalScreen["str | None"]):
    """Prompt for a profile name; dismiss with the name or None."""

    def __init__(self, initial: str = "") -> None:
        super().__init__()
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Save profile as:")
            yield Input(value=self._initial, placeholder="name", id="name")
            yield Label("", id="name-error")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if not NAME_RE.match(name):
            self.query_one("#name-error", Label).update(
                "invalid name — use letters, digits, '-' or '_'")
            return
        self.dismiss(name)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
```

In `sheppy/tui/app.py`, import the modal and add the binding + actions:

```python
from sheppy.tui.profile_modals import SaveNameModal
```

Add to `BINDINGS`:

```python
        ("s", "save_profile", "Save"),
```

Add the actions (near `action_focus_nodes`):

```python
    def action_save_profile(self) -> None:
        if not self.state or not self.store:
            return
        if self.state.active_profile_name:
            self.store.save(self.state.to_profile(self.state.active_profile_name))
            self.state.mark_saved(self.state.active_profile_name)
            self._refresh_profile_bar()
        else:
            self.push_screen(SaveNameModal(), self._on_save_name)

    def _on_save_name(self, name: "str | None") -> None:
        if not name or not self.state or not self.store:
            return
        self.store.save(self.state.to_profile(name))
        self.state.mark_saved(name)
        self._refresh_profile_bar()
```

Add modal-dialog CSS to the `CSS` string:

```
    #dialog { width: 60; height: auto; border: thick $accent; background: $surface; padding: 1 2; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/test_profiles.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/profile_modals.py sheppy/tui/app.py tests/tui/test_profiles.py
git commit -m "feat(tui): add save-profile flow"
```

---

### Task 7: Load + delete flow (`LoadModal`, `ConfirmModal` + `l` binding)

**Files:**
- Modify: `sheppy/tui/profile_modals.py`
- Modify: `sheppy/tui/app.py`
- Test: `tests/tui/test_profiles.py` (append)

**Interfaces:**
- Consumes: `ProfileStore`, `reconcile`, `ProfileState` (Tasks 2–4); `SaveNameModal` (Task 6, for the file layout).
- Produces:
  - `LoadModal(ModalScreen[tuple | None])` — built from `names: list[str]`; dismisses with `("load", name)` on Enter, `("delete", name)` on `d`, or `None` on Escape.
  - `ConfirmModal(ModalScreen[bool])` — `y` → `True`, `n`/Escape → `False`.
  - On `SheppyApp`: binding `("l", "load_profile", "Load")`; `action_load_profile()`; `_on_load_choice(choice)`; `_append_warnings(list)` + `self._runtime_warnings` list; `_rebuild_after_apply()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/tui/test_profiles.py  (append)
from sheppy.profiles import Profile, ProfileStore


async def test_load_applies_profile(tmp_path):
    ProfileStore(str(tmp_path)).save(
        Profile(name="mocked", selections={"camera": "mock"}))
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("enter")            # load the highlighted (only) profile
        await pilot.pause()
        assert app.state.selected("camera") == "mock"
        bar = str(app.query_one("#profilebar").content)
        assert "mocked" in bar and "*" not in bar
        # node label reflects the applied selection
        assert "mock" in str(app.query_one("#node-0 Label").content)


async def test_delete_removes_file(tmp_path):
    ProfileStore(str(tmp_path)).save(Profile(name="gone", selections={}))
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("d")                # request delete of highlighted
        await pilot.pause()
        await pilot.press("y")                # confirm
        await pilot.pause()
        assert not os.path.isfile(os.path.join(str(tmp_path), "gone.yaml"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_profiles.py::test_load_applies_profile -v`
Expected: FAIL — no `l` binding / `LoadModal` does not exist.

- [ ] **Step 3: Write minimal implementation**

Append to `sheppy/tui/profile_modals.py`:

```python
from textual.widgets import ListView, ListItem


class LoadModal(ModalScreen["tuple | None"]):
    """List saved profiles. Enter=load, d=delete, Esc=cancel."""

    def __init__(self, names: list) -> None:
        super().__init__()
        self._names = names

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Load profile — Enter=load, d=delete, Esc=cancel")
            items = [ListItem(Label(n), id=f"prof-{i}")
                     for i, n in enumerate(self._names)]
            yield ListView(*items, id="proflist")

    def on_mount(self) -> None:
        self.query_one("#proflist", ListView).focus()

    def _highlighted(self) -> "str | None":
        idx = self.query_one("#proflist", ListView).index
        if idx is None:
            return None
        return self._names[idx]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = self._highlighted()
        if name is not None:
            self.dismiss(("load", name))

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "d":
            name = self._highlighted()
            if name is not None:
                self.dismiss(("delete", name))


class ConfirmModal(ModalScreen[bool]):
    """Yes/no confirmation. y=True, n/Esc=False."""

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._prompt)
            yield Label("y = yes, n = no")

    def on_key(self, event) -> None:
        if event.key == "y":
            self.dismiss(True)
        elif event.key in ("n", "escape"):
            self.dismiss(False)
```

In `sheppy/tui/app.py`, extend the modal import and add the load/delete machinery. Update the import line:

```python
from sheppy.tui.profile_modals import SaveNameModal, LoadModal, ConfirmModal
from sheppy.profiles import reconcile
```

Add to `BINDINGS`:

```python
        ("l", "load_profile", "Load"),
```

Initialise a runtime-warnings sink in `__init__` (after `self.store = ...`):

```python
        self._runtime_warnings: list = []
```

Fold runtime warnings into the error overlay — update `_errors_text`:

```python
    def _errors_text(self) -> str:
        lines = [f"{e.location}: {e.message}" for e in self.load_result.errors]
        lines.extend(self._runtime_warnings)
        if not lines:
            return "no errors"
        return "\n".join(lines)
```

Add the actions and helpers:

```python
    def action_load_profile(self) -> None:
        if not self.state or not self.store:
            return
        self.push_screen(LoadModal(self.store.list_profiles()), self._on_load_choice)

    def _on_load_choice(self, choice: "tuple | None") -> None:
        if not choice or not self.state or not self.store:
            return
        action, name = choice
        if action == "delete":
            self.push_screen(
                ConfirmModal(f"Delete profile '{name}'?"),
                lambda ok: self.store.delete(name) if ok else None)
            return
        result = self.store.load(name)
        if result.profile is None:
            self._append_warnings(result.errors)
            return
        rec = reconcile(result.profile, self.manifest)
        self.state.apply(rec.selections, rec.overrides, name)
        if rec.warnings:
            self._append_warnings(rec.warnings)
        self._rebuild_after_apply()

    def _append_warnings(self, warnings: list) -> None:
        self._runtime_warnings.extend(warnings)
        try:
            self.query_one("#errors", Static).update(self._errors_text())
        except NoMatches:
            pass
        self.show_errors = True

    def _rebuild_after_apply(self) -> None:
        if self.manifest:
            for i, node in enumerate(self.manifest.nodes):
                try:
                    self.query_one(f"#node-{i} Label", Label).update(
                        _node_label(node, self.state))
                except NoMatches:
                    pass
        self._refresh_profile_bar()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/test_profiles.py -v`
Expected: PASS (load + delete tests, plus earlier ones).

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/profile_modals.py sheppy/tui/app.py tests/tui/test_profiles.py
git commit -m "feat(tui): add load and delete profile flow"
```

---

### Task 8: Param editor (`ParamEditorModal` + `p` binding)

**Files:**
- Modify: `sheppy/tui/profile_modals.py`
- Modify: `sheppy/tui/app.py`
- Test: `tests/tui/test_profiles.py` (append)

**Interfaces:**
- Consumes: `ProfileState.effective_params`, `.selected_alt`, `.override` (Task 4).
- Produces:
  - `ParamEditorModal(ModalScreen[dict | None])` — built from `params: dict[str, object]` (param → current effective value). On Enter it parses every field with `yaml.safe_load`; any field that fails to parse is rejected inline (no dismiss); on success dismisses with `{param: parsed_value}`. Escape dismisses with `None`.
  - On `SheppyApp`: binding `("p", "edit_params", "Params")`; `action_edit_params()`; `_on_params(result)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/tui/test_profiles.py  (append)
async def test_param_editor_records_override(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        # select camera/mock (which declares fps: 15)
        app.query_one("#nodes").index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        app.query_one("#alternatives").index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        # return focus to the node list, then open the param editor on camera
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        # the fps field is pre-filled "15"; clear it and type 30
        field = app.query_one("#param-fps")
        field.value = "30"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.effective_params("camera") == {"fps": 30}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_profiles.py::test_param_editor_records_override -v`
Expected: FAIL — no `p` binding / `ParamEditorModal` does not exist.

- [ ] **Step 3: Write minimal implementation**

Append to `sheppy/tui/profile_modals.py`:

```python
import yaml


class ParamEditorModal(ModalScreen["dict | None"]):
    """Edit declared params of the selected alternative. Enter=apply, Esc=cancel.

    Each field is parsed as a YAML scalar so 30, 1.5, true, and plain strings
    round-trip naturally. A field that fails to parse is rejected inline.
    """

    def __init__(self, params: dict) -> None:
        super().__init__()
        self._params = params

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Edit params — Enter=apply, Esc=cancel")
            for name, value in self._params.items():
                yield Label(name)
                yield Input(value=str(value), id=f"param-{name}")
            yield Label("", id="param-error")

    def on_mount(self) -> None:
        # Focus the first param field so pilot key presses land and Enter submits.
        first = next(iter(self._params), None)
        if first is not None:
            self.query_one(f"#param-{first}", Input).focus()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # A focused Input consumes Enter and emits Submitted (Enter never reaches
        # on_key), so submit here. Any field submitting applies the whole form.
        self._submit()

    def _submit(self) -> None:
        parsed: dict = {}
        for name in self._params:
            raw = self.query_one(f"#param-{name}", Input).value
            try:
                parsed[name] = yaml.safe_load(raw)
            except yaml.YAMLError:
                self.query_one("#param-error", Label).update(
                    f"invalid value for '{name}'")
                return
        self.dismiss(parsed)
```

In `sheppy/tui/app.py`, extend the modal import and add the binding + actions:

```python
from sheppy.tui.profile_modals import (
    SaveNameModal, LoadModal, ConfirmModal, ParamEditorModal,
)
```

Add to `BINDINGS`:

```python
        ("p", "edit_params", "Params"),
```

Add the actions:

```python
    def action_edit_params(self) -> None:
        if not self.state:
            return
        node = self._current_node()
        if node is None:
            return
        if self.state.selected_alt(node.name) is None:
            self._append_warnings([f"'{node.name}': no alternative selected to edit"])
            return
        params = self.state.effective_params(node.name)
        if not params:
            self._append_warnings([f"'{node.name}': selected alternative declares no params"])
            return
        self.push_screen(
            ParamEditorModal(params),
            lambda values: self._on_params(node.name, values))

    def _on_params(self, node_name: str, values: "dict | None") -> None:
        if values is None or not self.state:
            return
        for param, value in values.items():
            self.state.override(node_name, param, value)
        self._refresh_profile_bar()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/test_profiles.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

```bash
uv run pytest
```
Expected: all tests pass (Phase 1 + Phase 2a).

```bash
git add sheppy/tui/profile_modals.py sheppy/tui/app.py tests/tui/test_profiles.py
git commit -m "feat(tui): add param editor for declared-param overrides"
```

---

## Post-implementation

- [ ] Update `README.md`: mark Phase 2a ✅ Done; add profile keys (`s` save, `l` load, `p` params) to the keybindings table; note that profiles live in `<manifest_dir>/profiles/`.
- [ ] Whole-branch review (opus) per subagent-driven-development, then finishing-a-development-branch to merge.
```
