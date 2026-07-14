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
    NodeList {
        width: 34%; height: 1fr; background: $surface;
        border-right: solid $divider; padding: 0;
    }
    NodeList > ListItem {
        padding: 0 1; background: $surface;
        border-left: thick $surface;
    }
    NodeList > ListItem > Horizontal { height: 1; }
    NodeList > ListItem.-highlight {
        background: $sel-bg; border-left: thick $accent;
    }
    NodeList > ListItem.-highlight .col-name { text-style: bold; }
    NodeList .col-status { width: 3; }
    NodeList .col-name { width: 1fr; color: $foreground; }
    NodeList .col-alt { width: auto; color: $text-muted; }
    NodeList .col-host { width: 9; color: $text-muted; }
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
        self._manifest_nodes = list(nodes)
        self._selection = dict(selection)

    def compose(self):
        for i, node in enumerate(self._manifest_nodes):
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
                Label(node.name, classes="col-name", markup=False),
                Label(sel or "—", classes="col-alt", markup=False),
                Label(host, classes="col-host", markup=False),
            ),
            id=f"node-{i}",
        )

    def set_selection(self, selection) -> None:
        self._selection = dict(selection)
        for i, node in enumerate(self._manifest_nodes):
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
