# Sheppy Phase 2a.5 — Cockpit Shell (design)

**Status:** Approved — ready for implementation planning
**Date:** 2026-07-13
**Depends on:** Phase 1 (catalog browser) and Phase 2a (profiles), both merged.

## 1. Goal & scope

Restyle the Sheppy TUI to the **Operator Cockpit** layout (from the north-star
mockup), decomposed into small, independently-testable widgets. Show every piece
of data that exists today (manifest + profile state) in its cockpit position, and
render data belonging to later phases as **clearly-labeled placeholders**.

The point of this phase is not new capability — it is to **freeze the layout
contract**. Phase 2b (daemon + launch), Phase 3 (multi-machine), and Phase 4
(introspection) should each fill an existing slot with real data rather than
trigger a re-layout.

**In scope:** visual restyle to the cockpit; decomposition of the monolithic
`app.py` view layer into focused widget classes; a centralized palette and a
centralized status-glyph vocabulary; placeholder slots for future-phase data;
migration of existing TUI tests to the new structure.

**Explicitly NOT in scope:** the `sheppyd` daemon, launching/killing processes,
SSH/multi-machine, ROS graph introspection, any new profile semantics, and any
change to the manifest data model. This phase adds **zero** new backend behavior.

## 2. Guiding principle

Long-term maintainability over everything else. Concretely:

- **One responsibility per file**, communicating through well-defined interfaces,
  each understandable and testable in isolation.
- **Single source of truth** for cross-cutting concerns: the palette lives in one
  place; the status-glyph vocabulary lives in one place.
- **Preserve what is proven.** The Phase 1/2a interaction model (`ListView`-based
  navigation, focus discipline, never-crash error handling, profile save/load) is
  relocated into widgets, not rewritten. The 80-test suite is the safety net for
  that relocation.

## 3. Architecture — widget decomposition

`app.py` becomes thin orchestration: it owns `ProfileState`/`ProfileStore`,
composes the widgets, routes semantic messages between widgets and state, and
manages the error overlay. All rendering moves into a new package
`sheppy/tui/widgets/`, one responsibility per file:

| Module | Type | Responsibility | Emits |
|---|---|---|---|
| `theme.py` | `Theme` | Single source of the Atom One Dark palette, registered on the app | — |
| `status.py` | enum + glyph map | Single source of status vocabulary: `NONE ○`, `SELECTED ◆` (used now); `RUNNING ●`, `LAUNCHING ◐`, `CRASHED ✕`, `WARN ⚠` (reserved, defined but unused until 2b) | — |
| `header_bar.py` | `HeaderBar` | `🐑 sheppy` · active profile name + dirty `*` · manifest path · node count · error count · clock | — |
| `machines_strip.py` | `MachinesStrip` | Chips built from `manifest.machines` (`name`, `host`); status glyph `○` + "connection — phase 3" note | — |
| `node_list.py` | `NodeList` | Left pane. Wraps a `ListView` with id `#nodes`. Columnar rows: `status · node · selected-alt · host` | `NodeHighlighted`, `NodeSelected` |
| `alternatives_panel.py` | `AlternativesPanel` | Middle pane. Wraps a `ListView` with id `#alternatives`. Per alternative: radio `◉/○` + `kind · package` subline + declared topic counts `↑<pub> ↓<sub>` | `AlternativeSelected` |
| `detail_tabs.py` | `DetailTabs` | Right pane. `TabbedContent` with tabs DETAIL / TOPICS / PROCESS / YAML | — |
| `status_footer.py` | `StatusFooter` | Keycap hints derived from a single keymap list + `sheppyd ○ offline — phase 2b` segment | — |

**Preserved verbatim (relocated, not rewritten):**

- The `ListView` interaction model lives inside `NodeList` / `AlternativesPanel`.
  Same highlight/select semantics and the same focus discipline (arrow-nav on the
  node list must not steal focus; deliberate Enter descends into alternatives).
  The list IDs `#nodes` and `#alternatives` stay stable so behavioral tests keep
  their anchors.
- `profile_modals.py` (SaveNameModal, LoadModal, ConfirmModal, ParamEditorModal)
  is unchanged.
- The error overlay (`e` to toggle) and all never-crash handling carry over.

**Why not `DataTable` for the node list:** it would give literal grid columns but
uses a different interaction model (cursor + `RowSelected` instead of
`ListView.Highlighted/Selected`), discarding the proven focus discipline and its
regression tests. Rejected in favor of a `Horizontal` of `Label`s inside each
`ListItem`, which keeps the event model intact.

## 4. Placeholder contract

Every future-phase slot is present in the layout and visibly labeled so it never
reads as real data:

| Slot | Shown now | Label | Fills in |
|---|---|---|---|
| MachinesStrip status | real name+host, glyph `○` | "connection — phase 3" | Phase 3 |
| DetailTabs · PROCESS | placeholder panel | "requires sheppyd — phase 2b" | Phase 2b |
| DetailTabs · TOPICS `live` column | `—` | "live — phase 4" | Phase 4 |
| Node / alternative status glyph | selection-based (`◆`/`○`) | (legend in alternatives panel) | Phase 2b (runtime glyphs) |
| StatusFooter daemon segment | `sheppyd ○ offline` | "phase 2b" | Phase 2b |
| HeaderBar node count | `N nodes` | — | Phase 2b adds running-count |

## 5. Detail tabs

`TabbedContent` switched with number keys `1`–`4` plus Textual's native tab
navigation. Content:

- **DETAIL** — field grid (`kind`, `package`/`executable`/`launch_file`/`command`
  as applicable, `machine`, `params`) plus a `RUNNING (—)` placeholder badge.
- **TOPICS** — the contract table: `topic · dir · declared · live`, rows from the
  alternative's `publishes`/`subscribes`; `live` column is the `—` placeholder.
- **PROCESS** — placeholder panel ("requires sheppyd — phase 2b").
- **YAML** — `yaml.safe_dump` of the selected alternative's fields.

All tabs render defensively: a node with no alternatives, an alternative with no
params, or a node with nothing selected each render cleanly (no exception).

## 6. Data flow

- **Startup:** app builds `ProfileState` from the manifest; composes HeaderBar,
  MachinesStrip, the three-pane body (NodeList | AlternativesPanel | DetailTabs),
  StatusFooter, and the (hidden) error overlay.
- **Highlight node:** `NodeList` posts `NodeHighlighted(node)` → app calls
  `AlternativesPanel.show(node, selected_id)` and `DetailTabs.show(node, alt)`.
- **Select alternative:** `AlternativesPanel` posts `AlternativeSelected(alt)` →
  app calls `state.select(node, alt.id)`, then refreshes the node row, the header
  dirty flag, and the alternative radios.
- **Profile save / load / edit-params:** the existing `action_*` logic is
  unchanged; after `state.apply(...)` the app refreshes the affected widgets.
- **Warnings/errors:** routed to the error overlay and reflected in the header
  error count.

## 7. Theming & fidelity

The Atom One Dark palette is centralized in a registered Textual `Theme`
(`theme.py`) — the single source for every color. Chips use Textual `round`
borders.

Terminal-inapplicable flourishes from the HTML mockup are intentionally dropped:
the fake window chrome (traffic-light dots), CRT scanlines, and font selection
(the terminal controls the font). Truecolor hex values render correctly on modern
terminals.

## 8. Testing

- **Per-widget unit tests:** mount each widget in a minimal harness app; assert
  rendered content via `.content` and assert emitted messages.
- **Behavioral tests migrated, not dropped:** the Phase 1/2a contracts are
  re-expressed against the new structure — selection updates state; arrow-nav on
  the node list keeps focus; deliberate Enter descends; profile save/load
  round-trips (including description); malformed manifest/profile input never
  crashes and surfaces warnings in the overlay. Tests that asserted on old chrome
  (`#status`, `#profilebar`, `#detail` content) are updated to the new widgets.
- **Bar:** full suite green; every preserved behavior still has an assertion.

## 9. Forward-compatibility note

Consistent with the Phase 2a spec's forward-compat constraint, this phase must not
foreclose the future launcher/capability-plugin split. The `status.py` vocabulary
describes **runtime state** (none/selected/running/launching/crashed/warn), which
is orthogonal to **launch mechanism** (`process`/`executable`/`launch_file`) and to
**runtime capabilities** (graph/health/logs). Nothing in the cockpit hardcodes a
fixed set of alternative `kind`s beyond what the manifest already defines, and no
widget assumes one-plugin-per-alternative. The PROCESS tab and node/alt status
glyphs are the seams where a future capability plugin contributes data; they are
placeholders here precisely so that contribution is additive.

## 10. Non-goals

- No `DataTable` (would discard the proven interaction model).
- No daemon, launch/kill, SSH, or ROS graph introspection.
- No new profile semantics or manifest schema changes.
