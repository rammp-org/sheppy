# sheppy/tui/app.py
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Header, Footer, Label, ListView, ListItem, Static

from sheppy.manifest import LoadResult, Node, Alternative
from sheppy.selection import SelectionState


def _node_label(node: Node, selection: SelectionState | None) -> str:
    chosen = selection.selected(node.name) if selection else None
    return f"{node.name}  [{chosen or '—'}]"


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


class SheppyApp(App):
    CSS = """
    #nodes { width: 40%; border: solid $accent; }
    #alternatives { height: 50%; border: solid $accent; }
    #detail { height: 50%; border: solid $accent; padding: 0 1; }
    #status { dock: bottom; height: 1; background: $panel; }
    #errors { dock: bottom; height: auto; background: $error; color: $text; padding: 0 1; }
    """
    BINDINGS = [
        ("e", "toggle_errors", "Errors"),
        ("escape", "focus_nodes", "Nodes"),
    ]
    show_errors = reactive(False)

    def __init__(self, load_result: LoadResult, path: str | None = None) -> None:
        super().__init__()
        self.load_result = load_result
        self.path = path
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

    def action_focus_nodes(self) -> None:
        self.query_one("#nodes").focus()

    def watch_show_errors(self, value: bool) -> None:
        try:
            self.query_one("#errors").display = value
        except NoMatches:
            pass

    def _current_node(self) -> Node | None:
        if not self.manifest:
            return None
        idx = self.query_one("#nodes", ListView).index
        if idx is None:
            return None
        return self.manifest.nodes[idx]

    async def _populate_alternatives(self, node: Node) -> None:
        """Rebuild the alternatives list for the given node.

        Awaits clear() and each append() so DOM mutations are complete before
        returning — important in Textual 8.2.7 where these return awaitables
        (AwaitRemove / AwaitMount).

        Focus is NOT moved here; it remains wherever it was during node browsing.
        The caller (on_list_view_selected for the nodes list) is responsible for
        moving focus to #alternatives when the user deliberately descends.
        """
        alts = self.query_one("#alternatives", ListView)
        await alts.clear()
        chosen = self.selection.selected(node.name) if self.selection else None
        for j, alt in enumerate(node.alternatives):
            marker = "•" if alt.id == chosen else " "
            await alts.append(ListItem(Label(f"({marker}) {alt.id}  [{alt.kind}]"), id=f"alt-{j}"))

    def _show_detail(self, node: Node) -> None:
        idx = self.query_one("#alternatives", ListView).index
        detail = self.query_one("#detail", Static)
        if idx is None or not node.alternatives:
            detail.update("")
            return
        detail.update(format_detail(node.alternatives[idx]))

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "nodes":
            node = self._current_node()
            if node:
                await self._populate_alternatives(node)
                self._show_detail(node)
        elif event.list_view.id == "alternatives":
            node = self._current_node()
            if node:
                self._show_detail(node)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "nodes":
            # Deliberate descent: move focus from the node list into alternatives.
            self.query_one("#alternatives").focus()
            return
        if event.list_view.id != "alternatives" or not self.selection:
            return
        node = self._current_node()
        alt_idx = self.query_one("#alternatives", ListView).index
        if node is None or alt_idx is None:
            return
        alt = node.alternatives[alt_idx]
        self.selection.select(node.name, alt.id)
        self._refresh_node_label(node)
        await self._populate_alternatives(node)

    def _refresh_node_label(self, node: Node) -> None:
        idx = self.query_one("#nodes", ListView).index
        label = self.query_one(f"#node-{idx} Label", Label)
        label.update(_node_label(node, self.selection))
