import time

import yaml

from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.markup import escape
from textual.message import Message
from textual.widgets import Input, RichLog, Static, TabbedContent, TabPane

from sheppy.manifest import Alternative, Node
from sheppy.launch.builtins import param_text
from sheppy.launch.resolve import fmt
from sheppy.tui.widgets import status as st
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
    contract), PROCESS (live runtime state) and YAML render live now; the
    TOPICS 'live' column remains a placeholder for phase 4."""

    _log = (None, [], 0)    # (node, lines, width) the output area holds

    DEFAULT_CSS = """
    DetailTabs { width: 1fr; height: 1fr; background: $background; }
    DetailTabs Tabs { background: $subhead-bg; }
    DetailTabs Tab { color: $text-muted; margin: 0 1 0 0; }
    DetailTabs Tab.-active { color: $foreground; text-style: bold; }
    /* bounded, so a focused param field below the fold scrolls in */
    DetailTabs TabbedContent, DetailTabs ContentSwitcher { height: 1fr; }
    DetailTabs TabPane { padding: 1 2; height: 1fr; overflow-y: auto; }
    DetailTabs Static { padding: 0 0; }
    DetailTabs RichLog { height: 1fr; min-height: 5; background: $background; }
    """

    def compose(self):
        with TabbedContent(id="detailtabs"):
            with TabPane("DETAIL", id="tab-detail"):
                # Styled grid; every user-derived value is escape()d below.
                yield Static("", id="detail")
                yield ParamFields()
            with TabPane("TOPICS", id="tab-topics"):
                yield Static("", id="detail-topics")
            with TabPane("PROCESS", id="tab-process"):
                yield Static("", id="detail-process")
                yield RichLog(id="process-log", wrap=True, min_width=1)
            with TabPane("YAML", id="tab-yaml"):
                yield Static("", id="detail-yaml", markup=False)

    def on_mount(self) -> None:
        # Anchored, the output stays at the bottom as the facts above it
        # change height, until the user scrolls up.
        self.query_one("#process-log", RichLog).anchor()

    def activate(self, tab_id: str) -> None:
        self.query_one("#detailtabs", TabbedContent).active = tab_id

    def show(self, node: Node, alt: "Alternative | None",
             summary_rows: "list | None" = None,
             params: "dict | None" = None) -> None:
        """params: the alternative's effective values (manifest + profile
        overrides) for the selected one, shown as fields; None shows the
        manifest's."""
        try:
            detail = self.query_one("#detail", Static)
            topics = self.query_one("#detail-topics", Static)
            yaml_s = self.query_one("#detail-yaml", Static)
        except NoMatches:
            # Inner TabPane content isn't mounted yet (TabbedContent composes
            # on a later async pass than the node list's first highlight).
            # The app re-drives detail via call_after_refresh once mounted.
            return
        self.query_one(ParamFields).show(node.name, params or {},
                                         alt.params if alt else {})
        if alt is None:
            detail.update("")
            topics.update("")
            yaml_s.update("")
            return
        detail.update(self._detail_markup(node, alt, summary_rows, params))
        topics.update(self._topics(alt))
        yaml_s.update(self._yaml(alt))

    def focus_params(self) -> None:
        self.activate("tab-detail")
        self.query_one(ParamFields).focus_first()

    def show_process(self, payload: "dict | None", lines: list,
                     connected: bool, drift: "str | None" = None,
                     other: bool = False,
                     selected: "dict | None" = None) -> None:
        """selected: the selection's params, to list under a params drift
        the ones that differ, with their running values."""
        try:
            target = self.query_one("#detail-process", Static)
            self._show_log(payload["node"] if payload and not other
                           else None, lines)
        except NoMatches:
            return
        if not connected:
            target.update(c("muted", "sheppyd ○ offline"))
            return
        def row(key, value):
            return f"{c('muted', f'{key:<12}')}{value}"
        drift_rows = [row("drift", c("yellow", f"Δ {drift}"))] if drift else []
        if selected is not None:
            ran = payload["spec"].get("params") or {}
            drift_rows += [
                row("", c("fg", f"{k}: {fmt(ran[k]) if k in ran else '—'}")
                    + " " + c("muted", "running"))
                for k in sorted(ran.keys() | selected.keys())
                if k not in ran or k not in selected or ran[k] != selected[k]]
        if other:       # the highlighted alternative isn't running (#191)
            out = [row("state", c("muted", f"{st.glyph(st.Status.NONE)} "
                                           "not running")), *drift_rows]
            if payload is not None:     # name the run of another one
                exit_ = (f" (exit {payload['exit_code']})"
                         if payload["exit_code"] is not None else "")
                out += ["", c("muted", f"{payload['spec']['alt_id']} "
                                       f"{payload['state']}{exit_}")]
            target.update("\n".join(out))
            return
        if payload is None:
            target.update("\n".join(
                [c("muted", "not supervised — space to launch"), *drift_rows]))
            return
        status = st.runtime(payload["state"])
        out = [row("state", c(st.color_key(status),
                              f"{st.glyph(status)} {payload['state']}")),
               *drift_rows]
        out.append(row("alternative", c("fg", payload["spec"]["alt_id"])))
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
            out += ["", c("muted", "last output")]  # the RichLog below
        target.update("\n".join(out))

    def _show_log(self, node: "str | None", lines: list) -> None:
        """The output tail scrolls (#196): at the bottom it follows new
        lines; scrolled up, it holds still until you scroll back down."""
        log = self.query_one("#process-log", RichLog)
        if node == self._log[0] and not log.is_vertical_scroll_end:
            return
        if (node, lines, log.size.width) != self._log:     # width: re-wrap
            self._log = (node, lines, log.size.width)
            log.clear()
            if lines:
                log.write("\n".join(lines), scroll_end=False)
        # now, not after the refresh: the user may scroll up before then;
        # the anchor keeps it at the bottom as the facts change height
        log.scroll_end(animate=False, immediate=True, x_axis=False)

    def _detail_markup(self, node: Node, alt: Alternative,
                        summary_rows: "list | None" = None,
                        params: "dict | None" = None) -> str:
        """Styled field grid for the DETAIL tab (muted keys, colored values).
        format_detail() remains the plain-text form (YAML-adjacent, tested)."""
        def row(key: str, value: str) -> str:
            return f"{c('muted', f'{key:<12}')}{value}"

        # c() escapes its text argument internally; only the value outside
        # c() (the bold title) needs an explicit escape().
        title = f"[bold]{escape(node.name)}[/] {c('muted', '/ ' + alt.id)}"
        lines = [title, ""]
        lines.append(row("kind", c("purple", alt.kind)))
        for label, value in (summary_rows or []):
            lines.append(row(label, c("fg", str(value))))
        lines.append(row("machine", c("fg", alt.machine or "—")))
        if not params:          # else ParamFields shows them
            lines.extend(_param_rows(row, alt.params))
        return "\n".join(lines)

    def _topics(self, alt: Alternative) -> str:
        lines = [c("muted", f"{'topic':<30}{'dir':<6}{'declared':<10}live")]
        for t in alt.publishes:
            et = escape(t)
            lines.append(f"{et:<30}{c('green', 'pub'):<6}✓         {c('muted', '—')}")
        for t in alt.subscribes:
            et = escape(t)
            lines.append(f"{et:<30}{c('yellow', 'sub'):<6}✓         {c('muted', '—')}")
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
        if alt.raw:
            data["config"] = alt.raw
        return yaml.safe_dump(data, sort_keys=False).rstrip()


def _param_rows(row, params: dict) -> list:
    """One read-only row per param."""
    if not params:
        return [row("params", c("muted", "—"))]
    return [row("params" if i == 0 else "", c("fg", f"{k}: {fmt(v)}"))
            for i, (k, v) in enumerate(params.items())]


class ParamRow(Horizontal):
    """A param of the selected alternative as a field (#194): Enter
    applies it, Esc or leaving the field puts back its value."""

    DEFAULT_CSS = """
    ParamRow { height: 1; padding-left: 2; overflow-x: auto;
               scrollbar-size-horizontal: 0; }
    ParamRow:focus-within { background: $sel-bg; }
    ParamRow Static { width: auto; }
    ParamRow .param-key { color: $text-muted; }
    ParamRow .param-note { margin-left: 2; }
    /* capped, so a long value scrolls inside the field as you type;
       underlined, with no block, so it reads as clickable (#199) */
    ParamRow Input, ParamRow Input:focus {
        width: auto; min-width: 2; max-width: 50%; color: $foreground;
        background: transparent; background-tint: transparent;
        text-style: underline; }
    ParamRow.-edited Input, ParamRow.-edited .param-key { color: $warning; }
    """
    BINDINGS = [("escape", "leave", "Back")]

    class Edited(Message):
        def __init__(self, node: str, param: str, value) -> None:
            super().__init__()
            self.node, self.param, self.value = node, param, value

    def __init__(self, node: str, param: str, width: int,
                 value, manifest) -> None:
        super().__init__()
        self.node, self.param, self._width = node, param, width
        self.value, self.manifest = value, manifest

    def compose(self):
        yield Static(f"{self.param:<{self._width}}", markup=False,
                     classes="param-key")
        yield Input(param_text(self.value), compact=True)
        yield Static("", classes="param-note")

    def on_mount(self) -> None:
        self._paint()

    def set(self, value, manifest) -> None:
        self.value, self.manifest = value, manifest
        if self.is_mounted:
            self.query_one(Input).value = param_text(value)
            self._paint()

    def _paint(self, error: str = "") -> None:
        edited = self.value != self.manifest
        self.set_class(edited, "-edited")
        self.query_one(".param-note", Static).update(
            c("red", error) if error else
            c("muted", f"← {fmt(self.manifest)}") if edited else "")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if event.value == param_text(self.value):
            self._paint()   # clears a parse error from an earlier Enter
            return      # untouched: re-parsing could change its type (#70)
        try:
            value = yaml.safe_load(event.value)
        except yaml.YAMLError:
            self._paint("not valid YAML, Esc puts it back")
            return
        self.post_message(self.Edited(self.node, self.param, value))

    def on_input_blurred(self, event: Input.Blurred) -> None:
        if self.app.app_focus:      # not when the terminal loses focus
            self.set(self.value, self.manifest)     # nothing applies

    def action_leave(self) -> None:
        self.screen.query_one("AlternativesPanel").focus()


class ParamFields(Vertical):
    """The selected alternative's params as ParamRows."""

    DEFAULT_CSS = "ParamFields { height: auto; }"

    def __init__(self) -> None:
        super().__init__()
        self._rows: list = []

    def show(self, node: str, params: dict, manifest: dict) -> None:
        if [(r.node, r.param) for r in self._rows] == \
                [(node, k) for k in params]:
            for r in self._rows:        # in place, so a focused field stays
                r.set(params[r.param], manifest[r.param])
            return
        width = max(map(len, params), default=0) + 2
        self._rows = [ParamRow(node, k, width, v, manifest[k])
                      for k, v in params.items()]
        self.refresh(recompose=True)

    def compose(self):
        if self._rows:
            yield Static(c("muted", "params"))
        yield from self._rows

    def focus_first(self) -> None:
        # call_next runs after a recompose show() queued has mounted the rows
        self.call_next(
            lambda: self._rows and self._rows[0].query_one(Input).focus())
