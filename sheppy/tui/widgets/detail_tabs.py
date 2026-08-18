import time

import yaml

from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.markup import escape
from textual.widgets import Static, TabbedContent, TabPane

from sheppy.manifest import Alternative, Node
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

    DEFAULT_CSS = """
    DetailTabs { width: 1fr; height: 1fr; background: $background; }
    DetailTabs Tabs { background: $subhead-bg; }
    DetailTabs Tab { color: $text-muted; margin: 0 1 0 0; }
    DetailTabs Tab.-active { color: $foreground; text-style: bold; }
    DetailTabs TabPane { padding: 1 2; }
    DetailTabs Static { padding: 0 0; }
    """

    def compose(self):
        with TabbedContent(id="detailtabs"):
            with TabPane("DETAIL", id="tab-detail"):
                # Styled grid; every user-derived value is escape()d below.
                yield Static("", id="detail")
            with TabPane("TOPICS", id="tab-topics"):
                yield Static("", id="detail-topics")
            with TabPane("PROCESS", id="tab-process"):
                yield Static("", id="detail-process")
            with TabPane("YAML", id="tab-yaml"):
                yield Static("", id="detail-yaml", markup=False)

    def activate(self, tab_id: str) -> None:
        self.query_one("#detailtabs", TabbedContent).active = tab_id

    def show(self, node: Node, alt: "Alternative | None",
             summary_rows: "list | None" = None) -> None:
        try:
            detail = self.query_one("#detail", Static)
            topics = self.query_one("#detail-topics", Static)
            yaml_s = self.query_one("#detail-yaml", Static)
        except NoMatches:
            # Inner TabPane content isn't mounted yet (TabbedContent composes
            # on a later async pass than the node list's first highlight).
            # The app re-drives detail via call_after_refresh once mounted.
            return
        if alt is None:
            detail.update("")
            topics.update("")
            yaml_s.update("")
            return
        detail.update(self._detail_markup(node, alt, summary_rows))
        topics.update(self._topics(alt))
        yaml_s.update(self._yaml(alt))

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

    def _detail_markup(self, node: Node, alt: Alternative,
                        summary_rows: "list | None" = None) -> str:
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
        if alt.params:
            pairs = ", ".join(f"{k}: {v}" for k, v in alt.params.items())
            lines.append(row("params", c("orange", "{ " + pairs + " }")))
        else:
            lines.append(row("params", c("muted", "—")))
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
        if alt.config:
            data["config"] = alt.config
        return yaml.safe_dump(data, sort_keys=False).rstrip()
