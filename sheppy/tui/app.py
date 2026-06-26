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

    async def _populate_alternatives(self, node: Node) -> None:
        """Rebuild the alternatives list for the given node and focus it.

        Awaits clear() and each append() so DOM mutations are complete before
        returning — important in Textual 8.2.7 where these return awaitables
        (AwaitRemove / AwaitMount).

        After populating, focus is moved to the alternatives list so that a
        subsequent enter keypress selects the highlighted alternative.
        """
        alts = self.query_one("#alternatives", ListView)
        await alts.clear()
        chosen = self.selection.selected(node.name) if self.selection else None
        for j, alt in enumerate(node.alternatives):
            marker = "•" if alt.id == chosen else " "
            await alts.append(ListItem(Label(f"({marker}) {alt.id}  [{alt.kind}]"), id=f"alt-{j}"))
        alts.focus()

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "nodes":
            node = self._current_node()
            if node:
                await self._populate_alternatives(node)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
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
        idx = self.manifest.nodes.index(node)
        label = self.query_one(f"#node-{idx} Label", Label)
        label.update(_node_label(node, self.selection))
