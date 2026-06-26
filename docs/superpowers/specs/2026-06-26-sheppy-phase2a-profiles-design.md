# Sheppy Phase 2a — Profiles — Design Spec

**Date:** 2026-06-26
**Status:** Approved for implementation
**One-liner:** Save and load named selection sets (which alternative is active per node) plus declared-param overrides, as version-controllable per-profile YAML files, managed from the TUI.

---

## 1. Context & Scope

Phase 1 shipped the catalog browser: load a manifest, browse nodes/alternatives, single-select one alternative per node in memory. That selection is lost when the TUI closes. Phase 2a makes it durable and reusable: a **profile** is a named, saved configuration — the per-node alternative choices plus overrides of those alternatives' declared parameters — so the team can flip the whole system between named setups ("all-mock", "real-camera", "sim-only").

The original Phase 2 bundled profiles + the `sheppyd` daemon + launching. That is two subsystems, so Phase 2 was split: **2a = profiles (this spec)**, **2b = `sheppyd` daemon + local launch** (next cycle). 2a is pure persistence + TUI on top of Phase 1; nothing launches yet. Locking the profile schema here is what 2b will execute.

### Decisions locked during brainstorming
- A profile stores **alternative selections + param overrides** (not machine assignment — that is Phase 3).
- **Storage:** one YAML file per profile, in `<manifest_dir>/profiles/`. The filename stem is the canonical profile name.
- **Override scope:** declared params only — a profile may override only keys present in the selected alternative's manifest `params`. The TUI edits values, not keys.
- **In-memory model:** a new `ProfileState` *composes* the existing `SelectionState` (which stays untouched) and adds override tracking + load/save lifecycle.
- **Never crash** on a bad profile or on manifest drift — surface errors/warnings and keep going (Phase 1 ethos).

### Out of scope for 2a
Launching, the `sheppyd` daemon, machine assignment, multi-machine, and undeclared/arbitrary params.

## 2. Profile Schema

```yaml
# profiles/all-mock.yaml   — filename stem "all-mock" IS the profile name
description: "Everything mocked for desk testing"   # optional
selections:                  # node name -> alternative id
  camera: mock_camera
  sim_gui: unreal
overrides:                   # node name -> { declared-param -> value }
  camera:
    fps: 30
```

- **Filename is canonical.** The profile name is the filename stem; the file does not store its own name (no drift). Names are restricted to `[A-Za-z0-9_-]+`.
- **Partial profiles are valid.** A node absent from `selections` is simply unselected when the profile is applied.
- **Overrides are keyed by node** and apply to that node's *selected* alternative. Effective params for a node = the selected alternative's manifest `params` merged with (overridden by) the profile's `overrides[node]`.
- **Override values** are stored and parsed as YAML scalars, so `true`, `30`, `1.5`, and plain strings all round-trip naturally.

## 3. Components

Each unit has one responsibility and is testable in isolation. Pure-logic units (models, store, reconcile, state) carry all behavior; the TUI only renders and forwards events.

### 3.1 `sheppy/profiles/models.py`
```python
@dataclass(frozen=True)
class Profile:
    name: str
    selections: dict[str, str]            # node -> alternative id
    overrides: dict[str, dict[str, object]]  # node -> {param -> value}
    description: str = ""
```

### 3.2 `sheppy/profiles/store.py`
Pure file I/O + YAML. Knows nothing about the manifest.
- `ProfileStore(profiles_dir: str)`
- `list_profiles() -> list[str]` — sorted profile names (stems of `*.yaml`); empty if the dir is absent.
- `load(name) -> ProfileLoadResult` — `ProfileLoadResult(profile: Profile | None, errors: list[str])`; missing file or bad YAML → `profile=None` + one error (never raises).
- `save(profile) -> None` — writes `profiles_dir/<name>.yaml`, creating the dir if needed. Rejects names not matching `[A-Za-z0-9_-]+` with `ValueError`.
- `delete(name) -> None` — removes the file; no error if already gone.

### 3.3 `sheppy/profiles/reconcile.py`
The only unit needing both a profile and a manifest.
- `reconcile(profile: Profile, manifest: Manifest) -> ReconcileResult`
- `ReconcileResult(selections: dict[str,str], overrides: dict[str,dict[str,object]], warnings: list[str])`
- Drops, with a warning each:
  - a selection whose node is not in the manifest, or whose alternative id is not among that node's alternatives;
  - an override for a node not selected (after the above filtering), or an override key not present in the selected alternative's declared `params`.
- Returns only the clean, applicable subset. Never raises.

### 3.4 `sheppy/profiles/state.py`
`ProfileState` composes `SelectionState` (Phase 1) and owns the override + lifecycle layer.
- `ProfileState(manifest)` — builds an internal `SelectionState`; exposes selection passthroughs (`select`, `clear`, `selected`) so the TUI has one façade.
- `override(node, param, value)` / `clear_override(node, param)` — mutate per-node overrides; an override equal to the manifest default is dropped (kept minimal). Raises `KeyError` if `param` is not declared on the node's selected alternative.
- `effective_params(node) -> dict` — selected alternative's `params` merged with this node's overrides.
- `apply(selections, overrides, profile_name)` — replace working state from a reconciled profile; sets `active_profile_name`, clears `is_dirty`.
- `to_profile(name) -> Profile` — snapshot current selections + overrides.
- `active_profile_name: str | None` and `is_dirty: bool` — any selection/override change after `apply`/save sets `is_dirty = True`.

### 3.5 TUI additions (`sheppy/tui/`)
- **Profile bar** — a `Static` showing `Profile: <name> *` (`*` when `is_dirty`) or `Profile: <none>`.
- **Load overlay** (`l`) — a modal listing `store.list_profiles()`; `Enter` loads (store.load → reconcile → state.apply), routing any reconcile warnings to the existing error/warning overlay; `x` then a confirm deletes.
- **Save** (`s`) — if `active_profile_name` is set, overwrite it; otherwise open a name-input modal (validated against `[A-Za-z0-9_-]+`), then `store.save(state.to_profile(name))` and clear dirty.
- **Param editor** (`p`) — modal for the highlighted node's selected alternative; one row per declared param with an editable value field pre-filled from `effective_params`. On submit, each field is parsed as a YAML scalar: a value differing from the manifest default becomes an override; a value equal to the default clears any override. Invalid YAML in a field is rejected with an inline message. No selected alternative → the editor reports there is nothing to edit.

## 4. Data Flow

Load: `profiles/<name>.yaml → ProfileStore.load → reconcile(manifest) → ProfileState.apply → TUI renders selections, overrides, profile bar`.

Save: `ProfileState.to_profile(name) → ProfileStore.save → profiles/<name>.yaml`.

Edit: selecting an alternative or editing a param mutates `ProfileState`, which flips `is_dirty`, which re-renders the profile bar.

The CLI derives the profiles directory as `<dirname(manifest_path)>/profiles`. `SheppyApp` gains a `ProfileStore`, and its working state becomes a `ProfileState` instead of a bare `SelectionState`.

## 5. Error Handling

- **Bad/missing profile file** → `ProfileStore.load` returns errors; surfaced in the overlay; app stays usable.
- **Manifest drift** → `reconcile` drops stale selections/overrides with warnings; the applicable remainder still applies; warnings shown in the overlay.
- **Invalid profile name** on save → rejected before writing, with a message; nothing is persisted.
- **Invalid param value** (un-parseable YAML scalar) in the editor → field-level rejection; the override is not recorded.
- **Empty/absent `profiles/` dir** → `list_profiles()` returns `[]`; save creates the dir.

## 6. Testing

**Pure (no UI):**
- `models` — construction, mutable-default isolation.
- `store` — save→load round-trip; `list_profiles` sorting and empty-dir; bad YAML and missing file return one error; `save` rejects bad names; `delete` is idempotent.
- `reconcile` — clean profile passes through; each drift case (unknown node, unknown alt, override on unselected node, undeclared override key) drops exactly that item with a warning.
- `state` — override/clear_override, drop-when-equal-default, `effective_params` merge, `KeyError` on undeclared param, `apply` sets active name + clears dirty, any mutation sets dirty, `to_profile` snapshot round-trips through reconcile.

**TUI (Textual pilot):**
- Save current selection → file exists; load it back into a fresh app → selections applied, profile bar shows the name, not dirty.
- Param editor: open on a node, change a declared value, submit → override recorded and `effective_params` reflects it; reset to default → override cleared.
- Mutating a selection after load sets the dirty `*`.
- Load overlay lists profiles and applies on `Enter`; delete removes the file after confirm.

## 7. File Structure

```
sheppy/profiles/__init__.py      # re-exports Profile, ProfileStore, reconcile, ProfileState
sheppy/profiles/models.py
sheppy/profiles/store.py
sheppy/profiles/reconcile.py
sheppy/profiles/state.py
sheppy/tui/app.py                # wires ProfileStore + ProfileState; profile bar; key bindings
sheppy/tui/profile_modals.py     # load/save-name/param-editor modal screens
tests/profiles/…                 # one test module per pure unit
tests/tui/test_profiles.py       # pilot tests for the profile flows
```

## 8. Deferred to later phases
- Launching a profile's processes and the `sheppyd` daemon (Phase 2b).
- Per-node machine assignment overrides (Phase 3).
- Undeclared/arbitrary params and typed param schemas.
