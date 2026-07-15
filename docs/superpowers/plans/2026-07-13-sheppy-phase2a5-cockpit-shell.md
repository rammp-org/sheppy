# Sheppy Phase 2a.5 — Cockpit Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the Sheppy TUI to the Operator Cockpit layout, decomposed into focused per-file widgets, with clearly-labeled placeholders for future-phase data — with no change to selection, profile, or never-crash behavior.

**Architecture:** `app.py` becomes thin orchestration owning `ProfileState`/`ProfileStore` and routing semantic messages between presentational widgets under `sheppy/tui/widgets/`. The proven `ListView` interaction model and focus discipline are relocated into `NodeList`/`AlternativesPanel`, not rewritten. A single `Theme` and a single status-glyph vocabulary are the sources of truth for palette and status.

**Tech Stack:** Python ≥3.10, uv, Textual 8.2.7, PyYAML, pytest + pytest-asyncio (`asyncio_mode="auto"`).

## Global Constraints

- **Python ≥3.10**; **uv only** — run tests with `uv run pytest`, never bare `pytest`/`pip`.
- **Textual 8.2.7 idioms:** `Static`/`Label` expose text via `.content` (not `.renderable`); `ListView.clear()`/`.append()` return awaitables (await them in async methods); modals call `event.stop()` in handled `on_key` branches; `App.query_one` cannot see pushed-modal widgets — query via `app.screen`; widget IDs must match `[A-Za-z_][A-Za-z0-9_-]*`.
- **Never-crash ethos:** malformed manifest/profile input surfaces warnings in the error overlay and the app stays usable; widgets render defensively (no alternatives / no params / nothing selected must not raise).
- **Single source of truth:** the Atom One Dark palette lives only in `sheppy/tui/widgets/theme.py`; the status-glyph vocabulary lives only in `sheppy/tui/widgets/status.py`. No hex color or status glyph is duplicated elsewhere.
- **Preserve the proven model:** keep the `ListView`-based navigation and focus discipline (arrow-nav on the node list does not steal focus; deliberate Enter descends into alternatives). Keep these stable IDs so existing tests keep their anchors: `#nodes`, `#alternatives`, `#node-{i}`, `#profilebar`, `#detail`, `#errors`.
- **Scope:** no daemon, launch, SSH, or ROS graph introspection; no new profile semantics; no manifest schema change.

## File Structure

**Create:**
- `sheppy/tui/widgets/__init__.py` — package marker
- `sheppy/tui/widgets/theme.py` — `PALETTE` dict, `c()` markup helper, `SHEPPY_DARK` Theme
- `sheppy/tui/widgets/status.py` — `Status` enum, `glyph()`, `color_key()`
- `sheppy/tui/widgets/header_bar.py` — `HeaderBar`
- `sheppy/tui/widgets/machines_strip.py` — `MachinesStrip`
- `sheppy/tui/widgets/status_footer.py` — `KEYMAP`, `StatusFooter`
- `sheppy/tui/widgets/detail_tabs.py` — `format_detail()`, `DetailTabs`
- `sheppy/tui/widgets/node_list.py` — `NodeList`
- `sheppy/tui/widgets/alternatives_panel.py` — `AlternativesPanel`
- `tests/tui/widgets/test_theme.py`, `test_status.py`, `test_header_bar.py`, `test_machines_strip.py`, `test_status_footer.py`, `test_detail_tabs.py`, `test_node_list.py`, `test_alternatives_panel.py`

**Modify:**
- `sheppy/tui/app.py` — rewrite compose + wiring; re-export `format_detail`
- `tests/tui/test_app.py` — migrate assertions to new widgets
- `tests/tui/test_profiles.py` — migrate node-label assertions to `.col-alt`

---

### Task 1: Foundations — theme + status vocabulary

**Files:**
- Create: `sheppy/tui/widgets/__init__.py`
- Create: `sheppy/tui/widgets/theme.py`
- Create: `sheppy/tui/widgets/status.py`
- Test: `tests/tui/widgets/test_theme.py`, `tests/tui/widgets/test_status.py`

**Interfaces:**
- Produces: `theme.PALETTE: dict[str,str]`; `theme.c(key: str, text: str) -> str` (wraps text in Rich hex markup); `theme.SHEPPY_DARK: textual.theme.Theme` (name `"sheppy-dark"`). `status.Status` (enum: `NONE, SELECTED, RUNNING, LAUNCHING, CRASHED, WARN`); `status.glyph(s: Status) -> str`; `status.color_key(s: Status) -> str` (a key into `PALETTE`).

- [ ] **Step 1: Write the failing tests**

`tests/tui/widgets/test_theme.py`:
```python
from sheppy.tui.widgets.theme import PALETTE, c, SHEPPY_DARK


def test_palette_has_atom_one_dark_green():
    assert PALETTE["green"] == "#98c379"
    assert PALETTE["bg"] == "#282c34"


def test_c_wraps_text_in_hex_markup():
    assert c("green", "hi") == "[#98c379]hi[/]"


def test_theme_name():
    assert SHEPPY_DARK.name == "sheppy-dark"
    assert SHEPPY_DARK.dark is True
```

`tests/tui/widgets/test_status.py`:
```python
from sheppy.tui.widgets.status import Status, glyph, color_key


def test_glyphs_for_current_phase():
    assert glyph(Status.NONE) == "○"
    assert glyph(Status.SELECTED) == "◆"


def test_every_status_has_a_glyph_and_color():
    for s in Status:
        assert isinstance(glyph(s), str) and glyph(s)
        assert color_key(s) in {
            "muted", "green", "yellow", "red", "blue", "orange"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/widgets/test_theme.py tests/tui/widgets/test_status.py -v`
Expected: FAIL with `ModuleNotFoundError: sheppy.tui.widgets`.

- [ ] **Step 3: Create the package marker**

`sheppy/tui/widgets/__init__.py`:
```python
```
(empty file)

- [ ] **Step 4: Implement `theme.py`**

`sheppy/tui/widgets/theme.py`:
```python
"""Atom One Dark palette and Textual theme — the single source of truth
for Sheppy's colors. Widgets import PALETTE / c() for inline markup and the
app registers SHEPPY_DARK. Do not hardcode hex colors anywhere else."""
from textual.theme import Theme

PALETTE = {
    "bg": "#282c34",
    "surface": "#21252b",
    "panel": "#1b1e24",
    "fg": "#abb2bf",
    "muted": "#5c6370",
    "green": "#98c379",
    "purple": "#c678dd",
    "blue": "#61afef",
    "red": "#e06c75",
    "yellow": "#e5c07b",
    "orange": "#d19a66",
    "border": "#2c313a",
}


def c(key: str, text: str) -> str:
    """Wrap text in Rich hex markup using a PALETTE color key."""
    return f"[{PALETTE[key]}]{text}[/]"


SHEPPY_DARK = Theme(
    name="sheppy-dark",
    primary=PALETTE["blue"],
    secondary=PALETTE["purple"],
    accent=PALETTE["green"],
    foreground=PALETTE["fg"],
    background=PALETTE["bg"],
    surface=PALETTE["surface"],
    panel=PALETTE["panel"],
    success=PALETTE["green"],
    warning=PALETTE["yellow"],
    error=PALETTE["red"],
    dark=True,
)
```

- [ ] **Step 5: Implement `status.py`**

`sheppy/tui/widgets/status.py`:
```python
"""Status vocabulary — the single source of truth for status glyphs and
their colors. NONE/SELECTED are used in phase 2a.5; RUNNING/LAUNCHING/
CRASHED/WARN are reserved for phase 2b (runtime process state) and defined
now so later phases extend a table rather than restructure the UI."""
from enum import Enum


class Status(Enum):
    NONE = "none"
    SELECTED = "selected"
    RUNNING = "running"        # reserved — phase 2b
    LAUNCHING = "launching"    # reserved — phase 2b
    CRASHED = "crashed"        # reserved — phase 2b
    WARN = "warn"              # reserved — phase 2b


_GLYPH = {
    Status.NONE: "○",
    Status.SELECTED: "◆",
    Status.RUNNING: "●",
    Status.LAUNCHING: "◐",
    Status.CRASHED: "✕",
    Status.WARN: "⚠",
}

_COLOR = {
    Status.NONE: "muted",
    Status.SELECTED: "green",
    Status.RUNNING: "green",
    Status.LAUNCHING: "yellow",
    Status.CRASHED: "red",
    Status.WARN: "yellow",
}


def glyph(status: Status) -> str:
    return _GLYPH[status]


def color_key(status: Status) -> str:
    return _COLOR[status]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/tui/widgets/test_theme.py tests/tui/widgets/test_status.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add sheppy/tui/widgets/__init__.py sheppy/tui/widgets/theme.py sheppy/tui/widgets/status.py tests/tui/widgets/test_theme.py tests/tui/widgets/test_status.py
git commit -m "feat(tui): add cockpit theme + status vocabulary foundations"
```

---

### Task 2: HeaderBar

**Files:**
- Create: `sheppy/tui/widgets/header_bar.py`
- Test: `tests/tui/widgets/test_header_bar.py`

**Interfaces:**
- Consumes: `theme.c`.
- Produces: `HeaderBar(Horizontal)` with `update_state(profile_name: str | None, dirty: bool, path: str | None, node_count: int, error_count: int) -> None`. Contains child Statics with IDs `#profilebar` (profile name + dirty `*`), `#hb-source` (path + node count), `#hb-errors` (error count).

- [ ] **Step 1: Write the failing test**

`tests/tui/widgets/test_header_bar.py`:
```python
from textual.app import App, ComposeResult
from sheppy.tui.widgets.header_bar import HeaderBar


class _Harness(App):
    def compose(self) -> ComposeResult:
        yield HeaderBar()


async def test_header_shows_profile_source_and_errors():
    app = _Harness()
    async with app.run_test():
        hb = app.query_one(HeaderBar)
        hb.update_state("integration-test", True, "system.yaml", 12, 3)
        assert "integration-test" in str(app.query_one("#profilebar").content)
        assert "*" in str(app.query_one("#profilebar").content)
        src = str(app.query_one("#hb-source").content)
        assert "system.yaml" in src and "12" in src
        assert "3" in str(app.query_one("#hb-errors").content)


async def test_header_none_profile_and_no_errors():
    app = _Harness()
    async with app.run_test():
        hb = app.query_one(HeaderBar)
        hb.update_state(None, False, "system.yaml", 1, 0)
        bar = str(app.query_one("#profilebar").content)
        assert "none" in bar.lower() and "*" not in bar
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/widgets/test_header_bar.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `header_bar.py`**

`sheppy/tui/widgets/header_bar.py`:
```python
from datetime import datetime

from textual.containers import Horizontal
from textual.widgets import Static

from sheppy.tui.widgets.theme import c


class HeaderBar(Horizontal):
    """Top chrome: brand · profile chip · source · (spacer) · errors · clock.
    Presentational — the app pushes state in via update_state()."""

    DEFAULT_CSS = """
    HeaderBar { height: 1; background: $panel; padding: 0 1; }
    HeaderBar > Static { width: auto; height: 1; }
    HeaderBar #hb-spring { width: 1fr; }
    """

    def compose(self):
        yield Static(c("green", "🐑 sheppy"), id="hb-brand")
        yield Static("", id="profilebar")
        yield Static("", id="hb-source")
        yield Static("", id="hb-spring")
        yield Static("", id="hb-errors")
        yield Static("", id="hb-clock")

    def on_mount(self) -> None:
        self._tick()
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        self.query_one("#hb-clock", Static).update(
            c("muted", f"◷ {datetime.now().strftime('%H:%M:%S')}"))

    def update_state(self, profile_name, dirty, path, node_count,
                     error_count) -> None:
        name = profile_name or "<none>"
        dirty_mark = c("yellow", "*") if dirty else ""
        self.query_one("#profilebar", Static).update(
            f"  {c('purple', '◆ profile')} {name}{dirty_mark}")
        source = f"{path or '<no file>'} · {node_count} nodes"
        self.query_one("#hb-source", Static).update(f"  {c('muted', source)}")
        if error_count:
            errtext = c("red", f"✕ {error_count} error(s)")
        else:
            errtext = c("muted", "✓ no errors")
        self.query_one("#hb-errors", Static).update(errtext)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/widgets/test_header_bar.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/widgets/header_bar.py tests/tui/widgets/test_header_bar.py
git commit -m "feat(tui): add cockpit HeaderBar widget"
```

---

### Task 3: MachinesStrip

**Files:**
- Create: `sheppy/tui/widgets/machines_strip.py`
- Test: `tests/tui/widgets/test_machines_strip.py`

**Interfaces:**
- Consumes: `theme.c`; `sheppy.manifest.Machine` (fields `name`, `host`).
- Produces: `MachinesStrip(Horizontal)` constructed as `MachinesStrip(machines: list[Machine])`. Renders one chip Static per machine (id `#ms-{i}`) plus a phase-3 note (`#ms-note`); empty list renders `#ms-empty`.

- [ ] **Step 1: Write the failing test**

`tests/tui/widgets/test_machines_strip.py`:
```python
from textual.app import App, ComposeResult
from sheppy.manifest import Machine
from sheppy.tui.widgets.machines_strip import MachinesStrip


class _Harness(App):
    def __init__(self, machines):
        super().__init__()
        self._machines = machines

    def compose(self) -> ComposeResult:
        yield MachinesStrip(self._machines)


async def test_renders_declared_machines_and_phase3_note():
    machines = [Machine(name="robot", host="10.0.0.20", user="ros"),
                Machine(name="workstation", host="local", user="ros")]
    app = _Harness(machines)
    async with app.run_test():
        text = " ".join(str(s.content) for s in app.query("MachinesStrip Static"))
        assert "robot" in text and "10.0.0.20" in text
        assert "workstation" in text
        assert "phase 3" in text


async def test_empty_machines_render_placeholder():
    app = _Harness([])
    async with app.run_test():
        assert app.query_one("#ms-empty") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/widgets/test_machines_strip.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `machines_strip.py`**

`sheppy/tui/widgets/machines_strip.py`:
```python
from textual.containers import Horizontal
from textual.widgets import Static

from sheppy.tui.widgets.theme import c


class MachinesStrip(Horizontal):
    """Declared machines from the manifest as chips. Connection status is a
    phase-3 placeholder (glyph is always ○ 'declared, not monitored')."""

    DEFAULT_CSS = """
    MachinesStrip { height: 1; background: $surface; padding: 0 1; }
    MachinesStrip > Static { width: auto; height: 1; margin: 0 1 0 0; }
    """

    def __init__(self, machines, **kwargs):
        super().__init__(**kwargs)
        self._machines = list(machines)

    def compose(self):
        yield Static(c("muted", "MACHINES"), id="ms-label")
        if not self._machines:
            yield Static(c("muted", "— none declared —"), id="ms-empty")
        for i, m in enumerate(self._machines):
            chip = f"{c('muted', '○')} {c('fg', m.name)} {c('muted', m.host)}"
            yield Static(chip, id=f"ms-{i}")
        yield Static(c("muted", "· connection status — phase 3"), id="ms-note")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/widgets/test_machines_strip.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/widgets/machines_strip.py tests/tui/widgets/test_machines_strip.py
git commit -m "feat(tui): add cockpit MachinesStrip (phase-3 placeholder status)"
```

---

### Task 4: StatusFooter

**Files:**
- Create: `sheppy/tui/widgets/status_footer.py`
- Test: `tests/tui/widgets/test_status_footer.py`

**Interfaces:**
- Consumes: `theme.c`.
- Produces: `StatusFooter(Horizontal)`; `KEYMAP: list[tuple[str,str]]` (single source of key hints). Renders one hint Static per keymap entry plus `#sf-daemon` (phase-2b placeholder).

- [ ] **Step 1: Write the failing test**

`tests/tui/widgets/test_status_footer.py`:
```python
from textual.app import App, ComposeResult
from sheppy.tui.widgets.status_footer import StatusFooter, KEYMAP


class _Harness(App):
    def compose(self) -> ComposeResult:
        yield StatusFooter()


async def test_footer_shows_keymap_and_daemon_placeholder():
    app = _Harness()
    async with app.run_test():
        text = " ".join(str(s.content) for s in app.query("StatusFooter Static"))
        assert "save" in text and "load" in text and "errors" in text
        assert "sheppyd" in text and "phase 2b" in text


def test_keymap_covers_core_actions():
    labels = {label for _, label in KEYMAP}
    assert {"save", "load", "params", "errors"} <= labels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/widgets/test_status_footer.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `status_footer.py`**

`sheppy/tui/widgets/status_footer.py`:
```python
from textual.containers import Horizontal
from textual.widgets import Static

from sheppy.tui.widgets.theme import c

# Single source of truth for the footer key hints (display only; the actual
# bindings live on the app).
KEYMAP = [
    ("↑↓", "move"),
    ("⏎", "select"),
    ("s", "save"),
    ("l", "load"),
    ("p", "params"),
    ("e", "errors"),
    ("1-4", "tabs"),
]


class StatusFooter(Horizontal):
    """Bottom chrome: key hints + a phase-2b daemon-status placeholder."""

    DEFAULT_CSS = """
    StatusFooter { height: 1; background: $panel; padding: 0 1; }
    StatusFooter > Static { width: auto; height: 1; margin: 0 2 0 0; }
    StatusFooter #sf-spring { width: 1fr; margin: 0; }
    """

    def compose(self):
        for i, (key, label) in enumerate(KEYMAP):
            yield Static(f"{c('green', key)} {c('muted', label)}", id=f"sf-{i}")
        yield Static("", id="sf-spring")
        yield Static(c("muted", "sheppyd ○ offline — phase 2b"), id="sf-daemon")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/widgets/test_status_footer.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/widgets/status_footer.py tests/tui/widgets/test_status_footer.py
git commit -m "feat(tui): add cockpit StatusFooter (phase-2b daemon placeholder)"
```

---

### Task 5: DetailTabs

**Files:**
- Create: `sheppy/tui/widgets/detail_tabs.py`
- Test: `tests/tui/widgets/test_detail_tabs.py`

**Interfaces:**
- Consumes: `theme.c`; `sheppy.manifest.Node`, `Alternative`; `yaml`.
- Produces: `format_detail(alt: Alternative) -> str` (moved verbatim from `app.py`); `DetailTabs(Vertical)` with `show(node: Node, alt: Alternative | None) -> None` and `activate(tab_id: str) -> None`. Tab IDs: `tab-detail`, `tab-topics`, `tab-process`, `tab-yaml`. Content Statics: `#detail`, `#detail-topics`, `#detail-process`, `#detail-yaml`.

- [ ] **Step 1: Write the failing test**

`tests/tui/widgets/test_detail_tabs.py`:
```python
from textual.app import App, ComposeResult
from sheppy.manifest import Node, Alternative
from sheppy.tui.widgets.detail_tabs import DetailTabs, format_detail


def _node():
    return Node(name="camera", alternatives=[
        Alternative(id="realsense", kind="launch_file",
                    package="realsense2_camera", launch_file="rs_launch.py",
                    publishes=["/camera/img"], subscribes=["/tf"])])


class _Harness(App):
    def compose(self) -> ComposeResult:
        yield DetailTabs()


def test_format_detail_covers_kinds():
    alt = Alternative(id="u", kind="process", command="/opt/sim/Unreal -game")
    assert "/opt/sim/Unreal -game" in format_detail(alt)


async def test_show_populates_detail_topics_yaml():
    app = _Harness()
    async with app.run_test():
        dt = app.query_one(DetailTabs)
        node = _node()
        dt.show(node, node.alternatives[0])
        assert "realsense" in str(app.query_one("#detail").content)
        topics = str(app.query_one("#detail-topics").content)
        assert "/camera/img" in topics and "phase 4" in topics
        assert "realsense2_camera" in str(app.query_one("#detail-yaml").content)
        assert "phase 2b" in str(app.query_one("#detail-process").content)


async def test_show_none_is_defensive():
    app = _Harness()
    async with app.run_test():
        dt = app.query_one(DetailTabs)
        dt.show(_node(), None)  # must not raise
        assert str(app.query_one("#detail").content) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/widgets/test_detail_tabs.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `detail_tabs.py`** (move `format_detail` here from `app.py`)

`sheppy/tui/widgets/detail_tabs.py`:
```python
import yaml

from textual.containers import Vertical
from textual.widgets import Static, TabbedContent, TabPane

from sheppy.manifest import Alternative, Node
from sheppy.tui.widgets.theme import c


def format_detail(alt: Alternative) -> str:
    """Pure function: format an Alternative's fields as a multi-line string."""
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


class DetailTabs(Vertical):
    """Right pane: DETAIL / TOPICS / PROCESS / YAML. DETAIL, TOPICS (declared
    contract) and YAML render manifest data now; the TOPICS 'live' column and
    the whole PROCESS tab are labeled placeholders for phases 4 and 2b."""

    DEFAULT_CSS = """
    DetailTabs { width: 1fr; height: 1fr; }
    DetailTabs Static { padding: 0 1; }
    """

    def compose(self):
        with TabbedContent(id="detailtabs"):
            with TabPane("DETAIL", id="tab-detail"):
                yield Static("", id="detail")
            with TabPane("TOPICS", id="tab-topics"):
                yield Static("", id="detail-topics")
            with TabPane("PROCESS", id="tab-process"):
                yield Static(c("muted", "requires sheppyd — phase 2b"),
                             id="detail-process")
            with TabPane("YAML", id="tab-yaml"):
                yield Static("", id="detail-yaml")

    def activate(self, tab_id: str) -> None:
        self.query_one("#detailtabs", TabbedContent).active = tab_id

    def show(self, node: Node, alt: "Alternative | None") -> None:
        if alt is None:
            self.query_one("#detail", Static).update("")
            self.query_one("#detail-topics", Static).update("")
            self.query_one("#detail-yaml", Static).update("")
            return
        self.query_one("#detail", Static).update(format_detail(alt))
        self.query_one("#detail-topics", Static).update(self._topics(alt))
        self.query_one("#detail-yaml", Static).update(self._yaml(alt))

    def _topics(self, alt: Alternative) -> str:
        lines = [c("muted", f"{'topic':<30}{'dir':<6}{'declared':<10}live")]
        for t in alt.publishes:
            lines.append(f"{t:<30}{c('green', 'pub'):<6}✓         {c('muted', '—')}")
        for t in alt.subscribes:
            lines.append(f"{t:<30}{c('yellow', 'sub'):<6}✓         {c('muted', '—')}")
        if not alt.publishes and not alt.subscribes:
            lines.append(c("muted", "(no declared topics)"))
        lines.append(c("muted", "live column — phase 4"))
        return "\n".join(lines)

    def _yaml(self, alt: Alternative) -> str:
        data = {
            "id": alt.id, "kind": alt.kind, "machine": alt.machine,
            "package": alt.package, "executable": alt.executable,
            "launch_file": alt.launch_file, "command": alt.command,
            "params": alt.params, "publishes": alt.publishes,
            "subscribes": alt.subscribes,
        }
        data = {k: v for k, v in data.items() if v not in (None, [], {})}
        return yaml.safe_dump(data, sort_keys=False).rstrip()
```

Note: the `{c('green','pub'):<6}` width padding pads the *markup* string, not the visible glyph, so columns will be slightly loose — acceptable for this shell. Do not "fix" by stripping color; the loose alignment is intentional and cheap.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/widgets/test_detail_tabs.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/widgets/detail_tabs.py tests/tui/widgets/test_detail_tabs.py
git commit -m "feat(tui): add cockpit DetailTabs (DETAIL/TOPICS/PROCESS/YAML)"
```

---

### Task 6: NodeList

**Files:**
- Create: `sheppy/tui/widgets/node_list.py`
- Test: `tests/tui/widgets/test_node_list.py`

**Interfaces:**
- Consumes: `theme.c`; `status` (`Status`, `glyph`, `color_key`); `sheppy.manifest.Node`.
- Produces: `NodeList(ListView)` constructed as `NodeList(nodes: list[Node], selection: dict[str,str])`; own id is `#nodes`; rows are `ListItem` with id `#node-{i}` containing labels classed `.col-status`, `.col-name`, `.col-alt`, `.col-host`. Method `set_selection(selection: dict[str,str]) -> None`. Messages: `NodeList.NodeHighlighted(index: int)`, `NodeList.NodeSelected(index: int)`.

- [ ] **Step 1: Write the failing test**

`tests/tui/widgets/test_node_list.py`:
```python
from textual.app import App, ComposeResult
from sheppy.manifest import Node, Alternative
from sheppy.tui.widgets.node_list import NodeList


def _nodes():
    return [
        Node(name="camera", alternatives=[
            Alternative(id="realsense", kind="launch_file",
                        package="realsense2_camera", machine="robot")]),
        Node(name="planner", alternatives=[
            Alternative(id="astar", kind="process", command="true")]),
    ]


class _Harness(App):
    def __init__(self, selection):
        super().__init__()
        self._selection = selection

    def compose(self) -> ComposeResult:
        yield NodeList(_nodes(), self._selection)


async def test_rows_show_name_alt_and_host():
    app = _Harness({"camera": "realsense"})
    async with app.run_test():
        row = app.query_one("#node-0")
        assert "camera" in str(row.query_one(".col-name").content)
        assert "realsense" in str(row.query_one(".col-alt").content)
        assert "robot" in str(row.query_one(".col-host").content)


async def test_unselected_row_shows_dashes():
    app = _Harness({})
    async with app.run_test():
        row = app.query_one("#node-1")
        assert "—" in str(row.query_one(".col-alt").content)


async def test_set_selection_updates_row():
    app = _Harness({})
    async with app.run_test():
        app.query_one(NodeList).set_selection({"planner": "astar"})
        row = app.query_one("#node-1")
        assert "astar" in str(row.query_one(".col-alt").content)


async def test_arrow_nav_keeps_focus_and_emits_highlight():
    app = _Harness({})
    async with app.run_test() as pilot:
        nl = app.query_one(NodeList)
        assert nl.has_focus
        await pilot.press("down")
        await pilot.pause()
        assert nl.has_focus and nl.index == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/widgets/test_node_list.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `node_list.py`**

`sheppy/tui/widgets/node_list.py`:
```python
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from sheppy.manifest import Node
from sheppy.tui.widgets import status as st
from sheppy.tui.widgets.theme import c


def _selected_alt(node: Node, selected_id):
    for a in node.alternatives:
        if a.id == selected_id:
            return a
    return None


class NodeList(ListView):
    """Left pane. Columnar node rows (status · node · alt · host). Wraps
    ListView to preserve the proven highlight/select/focus behavior, and
    re-posts semantic messages so the app doesn't depend on ListView internals.
    Presentational: renders from a plain selection dict (node -> alt id)."""

    DEFAULT_CSS = """
    NodeList { width: 34%; height: 1fr; border: solid $accent; }
    NodeList .col-status { width: 3; }
    NodeList .col-name { width: 1fr; }
    NodeList .col-alt { width: auto; color: $text-muted; }
    NodeList .col-host { width: 10; color: $text-muted; }
    """

    class NodeHighlighted(Message):
        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    class NodeSelected(Message):
        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    def __init__(self, nodes, selection, **kwargs):
        super().__init__(id="nodes", **kwargs)
        self._nodes = list(nodes)
        self._selection = dict(selection)

    def compose(self):
        for i, node in enumerate(self._nodes):
            yield self._row(i, node)

    def _row(self, i, node):
        sel = self._selection.get(node.name)
        status = st.Status.SELECTED if sel else st.Status.NONE
        alt = _selected_alt(node, sel)
        host = alt.machine if (alt and alt.machine) else "—"
        return ListItem(
            Horizontal(
                Label(c(st.color_key(status), st.glyph(status)),
                      classes="col-status"),
                Label(node.name, classes="col-name"),
                Label(sel or "—", classes="col-alt"),
                Label(host, classes="col-host"),
            ),
            id=f"node-{i}",
        )

    def set_selection(self, selection) -> None:
        self._selection = dict(selection)
        for i, node in enumerate(self._nodes):
            sel = self._selection.get(node.name)
            status = st.Status.SELECTED if sel else st.Status.NONE
            alt = _selected_alt(node, sel)
            host = alt.machine if (alt and alt.machine) else "—"
            row = self.query_one(f"#node-{i}")
            row.query_one(".col-status", Label).update(
                c(st.color_key(status), st.glyph(status)))
            row.query_one(".col-alt", Label).update(sel or "—")
            row.query_one(".col-host", Label).update(host)

    def on_list_view_highlighted(self, event) -> None:
        event.stop()
        if self.index is not None:
            self.post_message(self.NodeHighlighted(self.index))

    def on_list_view_selected(self, event) -> None:
        event.stop()
        if self.index is not None:
            self.post_message(self.NodeSelected(self.index))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/widgets/test_node_list.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/widgets/node_list.py tests/tui/widgets/test_node_list.py
git commit -m "feat(tui): add cockpit NodeList (columnar rows, semantic messages)"
```

---

### Task 7: AlternativesPanel

**Files:**
- Create: `sheppy/tui/widgets/alternatives_panel.py`
- Test: `tests/tui/widgets/test_alternatives_panel.py`

**Interfaces:**
- Consumes: `theme.c`; `sheppy.manifest.Node`, `Alternative`.
- Produces: `AlternativesPanel(ListView)`; own id is `#alternatives`; async `show(node: Node, selected_id: str | None) -> None` (awaits clear/append); rows are `ListItem` id `#alt-{j}` containing labels classed `.alt-main`, `.alt-sub`. Messages: `AlternativesPanel.AlternativeHighlighted(index: int)`, `AlternativesPanel.AlternativeSelected(index: int)`.

- [ ] **Step 1: Write the failing test**

`tests/tui/widgets/test_alternatives_panel.py`:
```python
from textual.app import App, ComposeResult
from sheppy.manifest import Node, Alternative
from sheppy.tui.widgets.alternatives_panel import AlternativesPanel


def _node():
    return Node(name="camera", alternatives=[
        Alternative(id="realsense", kind="launch_file",
                    package="realsense2_camera",
                    publishes=["/a", "/b"], subscribes=["/tf"]),
        Alternative(id="mock", kind="executable", package="our_mocks"),
    ])


class _Harness(App):
    def compose(self) -> ComposeResult:
        yield AlternativesPanel()


async def test_show_renders_radio_kind_package_and_counts():
    app = _Harness()
    async with app.run_test():
        panel = app.query_one(AlternativesPanel)
        await panel.show(_node(), "realsense")
        text = " ".join(str(l.content) for l in app.query("#alt-0 Label"))
        assert "realsense" in text
        assert "launch_file" in text and "realsense2_camera" in text
        assert "↑2" in text and "↓1" in text  # declared topic counts


async def test_show_is_defensive_on_empty_alternatives():
    app = _Harness()
    async with app.run_test():
        panel = app.query_one(AlternativesPanel)
        await panel.show(Node(name="x", alternatives=[]), None)  # must not raise
        assert len(app.query("#alt-0")) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/widgets/test_alternatives_panel.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `alternatives_panel.py`**

`sheppy/tui/widgets/alternatives_panel.py`:
```python
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from sheppy.manifest import Node
from sheppy.tui.widgets.theme import c


class AlternativesPanel(ListView):
    """Middle pane. Per alternative: radio + id, then a kind·package subline
    with declared topic counts (↑pub ↓sub). Running/stopped state is a phase-2b
    concern and deliberately absent here. Re-posts semantic messages."""

    DEFAULT_CSS = """
    AlternativesPanel { width: 26%; height: 1fr; border: solid $accent; }
    AlternativesPanel .alt-sub { color: $text-muted; }
    """

    class AlternativeHighlighted(Message):
        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    class AlternativeSelected(Message):
        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(id="alternatives", **kwargs)

    async def show(self, node: Node, selected_id: "str | None") -> None:
        await self.clear()
        for j, alt in enumerate(node.alternatives):
            await self.append(
                ListItem(self._widget(alt, alt.id == selected_id), id=f"alt-{j}"))

    def _widget(self, alt, is_sel):
        radio = "◉" if is_sel else "○"
        ckey = "green" if is_sel else "muted"
        pkg = alt.package or alt.command or "—"
        counts = f"↑{len(alt.publishes)} ↓{len(alt.subscribes)}"
        return Vertical(
            Label(f"{c(ckey, radio)} {alt.id}", classes="alt-main"),
            Label(c("muted", f"{alt.kind} · {pkg}   {counts}"), classes="alt-sub"),
        )

    def on_list_view_highlighted(self, event) -> None:
        event.stop()
        if self.index is not None:
            self.post_message(self.AlternativeHighlighted(self.index))

    def on_list_view_selected(self, event) -> None:
        event.stop()
        if self.index is not None:
            self.post_message(self.AlternativeSelected(self.index))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/widgets/test_alternatives_panel.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add sheppy/tui/widgets/alternatives_panel.py tests/tui/widgets/test_alternatives_panel.py
git commit -m "feat(tui): add cockpit AlternativesPanel (radio + counts, messages)"
```

---

### Task 8: App integration — compose, navigation, theme, tab keys

**Files:**
- Modify: `sheppy/tui/app.py` (rewrite compose + navigation; register theme; tab bindings; re-export `format_detail`)
- Modify: `tests/tui/test_app.py` (migrate navigation/detail/status assertions)

**Interfaces:**
- Consumes: all widgets from Tasks 1–7; `ProfileState`, `ProfileStore`, `reconcile` (unchanged).
- Produces: `SheppyApp` composing `HeaderBar`, `MachinesStrip`, a body `Horizontal(NodeList, AlternativesPanel, DetailTabs)`, `StatusFooter`, and the hidden `#errors` overlay. Message handlers: `on_node_list_node_highlighted`, `on_node_list_node_selected`, `on_alternatives_panel_alternative_highlighted`, `on_alternatives_panel_alternative_selected`. Helpers: `_current_selection()`, `_refresh_header()`, `_current_node()`, `_show_detail(node)`. Re-exports `format_detail`. **This task keeps the profile actions from the current `app.py` in place unchanged; Task 9 rewires their refresh calls.**

- [ ] **Step 1: Rewrite `sheppy/tui/app.py`**

Replace the entire file with:
```python
# sheppy/tui/app.py
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Static

from sheppy.manifest import LoadResult, Node
from sheppy.profiles import ProfileState, ProfileStore, reconcile
from sheppy.tui.profile_modals import (
    SaveNameModal, LoadModal, ConfirmModal, ParamEditorModal,
)
from sheppy.tui.widgets.theme import SHEPPY_DARK
from sheppy.tui.widgets.header_bar import HeaderBar
from sheppy.tui.widgets.machines_strip import MachinesStrip
from sheppy.tui.widgets.status_footer import StatusFooter
from sheppy.tui.widgets.node_list import NodeList
from sheppy.tui.widgets.alternatives_panel import AlternativesPanel
from sheppy.tui.widgets.detail_tabs import DetailTabs, format_detail  # re-export

__all__ = ["SheppyApp", "format_detail"]


class SheppyApp(App):
    CSS = """
    #body { height: 1fr; }
    #errors { dock: bottom; height: auto; background: $error; color: $text; padding: 0 1; }
    #dialog { width: 60; height: auto; border: thick $accent; background: $surface; padding: 1 2; }
    """
    BINDINGS = [
        ("e", "toggle_errors", "Errors"),
        ("escape", "focus_nodes", "Nodes"),
        ("s", "save_profile", "Save"),
        ("l", "load_profile", "Load"),
        ("p", "edit_params", "Params"),
        ("1", "show_tab('tab-detail')", "Detail"),
        ("2", "show_tab('tab-topics')", "Topics"),
        ("3", "show_tab('tab-process')", "Process"),
        ("4", "show_tab('tab-yaml')", "YAML"),
    ]
    show_errors = reactive(False)

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
        self._runtime_warnings: list = []

    # ---- composition -----------------------------------------------------
    def compose(self) -> ComposeResult:
        yield HeaderBar()
        yield MachinesStrip(self.manifest.machines if self.manifest else [])
        nodes = self.manifest.nodes if self.manifest else []
        yield Horizontal(
            NodeList(nodes, self._current_selection()),
            AlternativesPanel(),
            DetailTabs(),
            id="body",
        )
        yield StatusFooter()
        errors = Static(self._errors_text(), id="errors")
        errors.display = False
        yield errors

    def on_mount(self) -> None:
        self.register_theme(SHEPPY_DARK)
        self.theme = "sheppy-dark"
        self._refresh_header()

    # ---- view-model helpers ---------------------------------------------
    def _current_selection(self) -> dict:
        if not self.state or not self.manifest:
            return {}
        out = {}
        for n in self.manifest.nodes:
            sel = self.state.selected(n.name)
            if sel:
                out[n.name] = sel
        return out

    def _refresh_header(self) -> None:
        try:
            hb = self.query_one(HeaderBar)
        except NoMatches:
            return
        name = self.state.active_profile_name if self.state else None
        dirty = self.state.is_dirty if self.state else False
        node_count = len(self.manifest.nodes) if self.manifest else 0
        hb.update_state(name, dirty, self.path, node_count,
                        len(self.load_result.errors))

    def _errors_text(self) -> str:
        lines = [f"{e.location}: {e.message}" for e in self.load_result.errors]
        lines.extend(self._runtime_warnings)
        return "\n".join(lines) if lines else "no errors"

    def _current_node(self) -> "Node | None":
        if not self.manifest:
            return None
        idx = self.query_one(NodeList).index
        if idx is None:
            return None
        return self.manifest.nodes[idx]

    def _show_detail(self, node: Node) -> None:
        idx = self.query_one(AlternativesPanel).index
        alt = (node.alternatives[idx]
               if idx is not None and node.alternatives else None)
        self.query_one(DetailTabs).show(node, alt)

    # ---- navigation wiring ----------------------------------------------
    async def on_node_list_node_highlighted(
            self, event: NodeList.NodeHighlighted) -> None:
        if not self.manifest:
            return
        node = self.manifest.nodes[event.index]
        sel = self.state.selected(node.name) if self.state else None
        await self.query_one(AlternativesPanel).show(node, sel)
        self._show_detail(node)

    def on_node_list_node_selected(self, event: NodeList.NodeSelected) -> None:
        # Deliberate descent: move focus into the alternatives pane.
        self.query_one(AlternativesPanel).focus()

    def on_alternatives_panel_alternative_highlighted(
            self, event: AlternativesPanel.AlternativeHighlighted) -> None:
        node = self._current_node()
        if node and node.alternatives and event.index is not None:
            self.query_one(DetailTabs).show(node, node.alternatives[event.index])

    async def on_alternatives_panel_alternative_selected(
            self, event: AlternativesPanel.AlternativeSelected) -> None:
        node = self._current_node()
        if node is None or not self.state or event.index is None:
            return
        alt = node.alternatives[event.index]
        self.state.select(node.name, alt.id)
        self.query_one(NodeList).set_selection(self._current_selection())
        self._refresh_header()
        await self.query_one(AlternativesPanel).show(node, alt.id)

    # ---- actions ---------------------------------------------------------
    def action_toggle_errors(self) -> None:
        self.show_errors = not self.show_errors

    def action_focus_nodes(self) -> None:
        self.query_one(NodeList).focus()

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one(DetailTabs).activate(tab_id)

    def action_save_profile(self) -> None:
        if not self.state or not self.store:
            return
        if self.state.active_profile_name:
            name = self.state.active_profile_name
            try:
                self.store.save(self.state.to_profile(name))
            except ValueError as e:
                self._append_warnings([f"could not save profile '{name}': {e}"])
                return
            self.state.mark_saved(name)
            self._refresh_header()
        else:
            self.push_screen(SaveNameModal(), self._on_save_name)

    def _on_save_name(self, name: "str | None") -> None:
        if not name or not self.state or not self.store:
            return
        self.store.save(self.state.to_profile(name))
        self.state.mark_saved(name)
        self._refresh_header()

    def action_load_profile(self) -> None:
        if not self.state or not self.store:
            return
        self.push_screen(LoadModal(self.store.list_profiles()),
                         self._on_load_choice)

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
        self.state.apply(rec.selections, rec.overrides, name,
                         description=result.profile.description)
        if rec.warnings:
            self._append_warnings(rec.warnings)
        self._rebuild_after_apply()

    def action_edit_params(self) -> None:
        if not self.state:
            return
        node = self._current_node()
        if node is None:
            return
        if self.state.selected_alt(node.name) is None:
            self._append_warnings(
                [f"'{node.name}': no alternative selected to edit"])
            return
        params = self.state.effective_params(node.name)
        if not params:
            self._append_warnings(
                [f"'{node.name}': selected alternative declares no params"])
            return
        self.push_screen(
            ParamEditorModal(params),
            lambda values: self._on_params(node.name, values))

    def _on_params(self, node_name: str, values: "dict | None") -> None:
        if values is None or not self.state:
            return
        for param, value in values.items():
            self.state.override(node_name, param, value)
        self._refresh_header()

    # ---- errors / rebuild ------------------------------------------------
    def _append_warnings(self, warnings: list) -> None:
        self._runtime_warnings.extend(warnings)
        try:
            self.query_one("#errors", Static).update(self._errors_text())
        except NoMatches:
            pass
        self.show_errors = True

    def _rebuild_after_apply(self) -> None:
        self.query_one(NodeList).set_selection(self._current_selection())
        self._refresh_header()
        node = self._current_node()
        if node:
            self.run_worker(self._reshow(node), exclusive=False)

    async def _reshow(self, node: Node) -> None:
        sel = self.state.selected(node.name) if self.state else None
        await self.query_one(AlternativesPanel).show(node, sel)
        self._show_detail(node)

    def watch_show_errors(self, value: bool) -> None:
        try:
            self.query_one("#errors").display = value
        except NoMatches:
            pass
```

- [ ] **Step 2: Migrate `tests/tui/test_app.py`**

Replace the four navigation/detail/status tests so they match the new widget structure. Change these specific tests (leave the `format_detail` pure-function tests as-is — they still import from `sheppy.tui.app` via the re-export):

```python
async def test_node_list_renders():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        nodes = app.query_one("#nodes")
        # Rows now have multiple column Labels; join them.
        text = "\n".join(
            " ".join(str(l.content) for l in item.query("Label"))
            for item in nodes.children)
        assert "camera" in text and "planner" in text


async def test_highlighting_node_populates_alternatives():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        alts = app.query_one("#alternatives")
        text = "\n".join(
            " ".join(str(l.content) for l in item.query("Label"))
            for item in alts.children)
        assert "realsense" in text and "mock" in text


async def test_selecting_alternative_updates_state_and_label():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        app.query_one("#alternatives").index = 1
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.selected("camera") == "mock"
        assert "mock" in str(app.query_one("#node-0 .col-alt").content)


async def test_status_bar_shows_error_count():
    result = LoadResult(_result().manifest,
                        [ValidationError("nodes[0]", "boom")])
    app = SheppyApp(result, path="system.yaml")
    async with app.run_test() as pilot:
        src = str(app.query_one("#hb-source").content)
        err = str(app.query_one("#hb-errors").content)
        assert "system.yaml" in src and "1 error" in err
```

(`test_node_list_navigation_keeps_focus`, `test_detail_updates_on_highlight`, and `test_error_overlay_toggles` keep working unchanged — `#nodes`, `#detail`, and `#errors` IDs are preserved.)

- [ ] **Step 3: Run the affected tests to verify they pass**

Run: `uv run pytest tests/tui/test_app.py tests/tui/widgets -v`
Expected: PASS (all widget tests + migrated app tests).

- [ ] **Step 4: Commit**

```bash
git add sheppy/tui/app.py tests/tui/test_app.py
git commit -m "feat(tui): assemble cockpit shell in app + migrate navigation tests"
```

---

### Task 9: Profiles & errors re-integration + test migration + docs

**Files:**
- Modify: `tests/tui/test_profiles.py` (migrate node-label assertions to `.col-alt`)
- Modify: `README.md` (note the cockpit layout + `1`-`4` tab keys)

**Interfaces:**
- Consumes: the assembled `SheppyApp` from Task 8. No new production code — this task verifies the profile flows still hold against the new widgets and fixes the two node-label assertions that referenced the old single-Label rows.

- [ ] **Step 1: Migrate the node-label assertion in `test_profiles.py`**

In `test_load_applies_profile`, change the final assertion from the old single-Label form to the column label:
```python
        # node row reflects the applied selection (alt column)
        assert "mock" in str(app.query_one("#node-0 .col-alt").content)
```
Leave every other test in the file unchanged — `#profilebar`, `#nodes`, `#alternatives`, and the modal flows are all preserved.

- [ ] **Step 2: Run the full TUI suite to verify green**

Run: `uv run pytest tests/tui -v`
Expected: PASS. Confirm specifically that these preserved-behavior tests pass:
`test_profile_bar_starts_none`, `test_selecting_marks_profile_bar_dirty`,
`test_save_writes_file_and_updates_bar`, `test_load_applies_profile`,
`test_delete_removes_file`, `test_load_modal_escape_does_not_steal_focus`,
`test_param_editor_records_override`,
`test_param_editor_handles_non_identifier_param_names`,
`test_reload_preserves_description_across_resave`,
`test_save_does_not_crash_on_invalid_active_profile_stem`.

- [ ] **Step 3: Run the entire suite**

Run: `uv run pytest`
Expected: PASS (all prior tests + the new widget tests).

- [ ] **Step 4: Update `README.md`**

In the "Keys" table, add a row for the detail tabs:
```markdown
| `1`–`4` | Switch detail tab (Detail / Topics / Process / YAML) |
```
And add one line under the keys table:
```markdown
The TUI uses an operator-cockpit layout: a header bar (profile · source ·
errors · clock), a machines strip, the three-pane body (nodes · alternatives ·
tabbed detail), and a footer of key hints. Process status, live machine
connections, and the topics "live" column are labeled placeholders that later
phases (2b/3/4) fill in.
```

- [ ] **Step 5: Commit**

```bash
git add tests/tui/test_profiles.py README.md
git commit -m "feat(tui): verify profile flows on cockpit shell; migrate label test; docs"
```

---

## Self-Review

**1. Spec coverage:**
- §2 decomposition → Tasks 1–7 (one widget per file); §3 architecture (thin app, relocated ListView model, semantic messages) → Task 8. ✓
- §3 placeholder contract (machines phase-3, PROCESS phase-2b, TOPICS live phase-4, footer daemon phase-2b, selection-based glyphs) → Tasks 3, 5, 4, 6. ✓
- §4 real switchable tabs (DETAIL/TOPICS/YAML real, PROCESS placeholder, `1`-`4`) → Task 5 + Task 8 bindings. ✓
- §5 data flow (highlight→show, select→state.select+refresh, profile actions unchanged) → Task 8. ✓
- §6 theming (single-source palette/Theme, dropped CRT/window-chrome) → Task 1 + app `on_mount`. ✓
- §7 testing (per-widget unit tests + migrated behavioral tests) → every task's tests + Tasks 8–9 migration. ✓
- §9 forward-compat (status vocabulary orthogonal to launch kind) → Task 1 `status.py` with reserved runtime states. ✓

**2. Placeholder scan:** No "TBD"/"handle edge cases" — every code step shows complete code; test steps show real assertions; the one alignment caveat in Task 5 is an explicit design note, not a deferral.

**3. Type consistency:** `c(key, text)` signature consistent across all widgets; `Status`/`glyph`/`color_key` used identically in `node_list.py`; message classes `NodeHighlighted/NodeSelected/AlternativeHighlighted/AlternativeSelected` referenced with matching Textual handler names (`on_node_list_node_highlighted`, etc.); `format_detail` defined in Task 5 and re-exported in Task 8; stable IDs (`#nodes`, `#alternatives`, `#node-{i}`, `#profilebar`, `#detail`, `#errors`) preserved for the migrated tests.

**Note on `$text-muted`:** Textual provides `$text-muted` as a theme-derived variable; the widget CSS relies on it. If a step's test surfaces an "undefined variable" error, replace `$text-muted` with `$text 50%` in that widget's `DEFAULT_CSS` — this is the only CSS token not defined in `theme.py`.
