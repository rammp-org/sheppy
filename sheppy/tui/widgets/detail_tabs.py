import yaml

from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.markup import escape
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
    DetailTabs { width: 1fr; height: 1fr; background: $background; }
    DetailTabs Tabs { background: $panel; }
    DetailTabs Tab { color: $text-muted; margin: 0 1 0 0; }
    DetailTabs Tab.-active { color: $foreground; text-style: bold; }
    DetailTabs TabPane { padding: 1 2; }
    DetailTabs Static { padding: 0 0; }
    """

    def compose(self):
        with TabbedContent(id="detailtabs"):
            with TabPane("DETAIL", id="tab-detail"):
                yield Static("", id="detail", markup=False)
            with TabPane("TOPICS", id="tab-topics"):
                yield Static("", id="detail-topics")
            with TabPane("PROCESS", id="tab-process"):
                yield Static(c("muted", "requires sheppyd — phase 2b"),
                             id="detail-process")
            with TabPane("YAML", id="tab-yaml"):
                yield Static("", id="detail-yaml", markup=False)

    def activate(self, tab_id: str) -> None:
        self.query_one("#detailtabs", TabbedContent).active = tab_id

    def show(self, node: Node, alt: "Alternative | None") -> None:
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
        detail.update(format_detail(alt))
        topics.update(self._topics(alt))
        yaml_s.update(self._yaml(alt))

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
        return yaml.safe_dump(data, sort_keys=False).rstrip()
