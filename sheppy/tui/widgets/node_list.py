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


class NodeListHeader(Horizontal):
    """Column-title row above the NodeList.

    Textual scopes DEFAULT_CSS to the declaring widget, so the column widths
    must be repeated here — keep them in sync with NodeList's col classes.
    """

    DEFAULT_CSS = """
    NodeListHeader { height: 1; background: $subhead-bg; padding: 0 1 0 2; }
    NodeListHeader Label { color: $text-muted; }
    NodeListHeader .col-status { width: 3; }
    NodeListHeader .col-name { width: 1fr; }
    NodeListHeader .col-alt { width: 14; }
    NodeListHeader .col-host { width: 8; }
    """

    def compose(self):
        yield Label("", classes="col-status")
        yield Label("NODE", classes="col-name")
        yield Label("ALTERNATIVE", classes="col-alt")
        yield Label("HOST", classes="col-host")


class NodeList(ListView):
    """Left pane. Columnar node rows (status · node · alt · host). Wraps
    ListView to preserve the proven highlight/select/focus behavior, and
    re-posts semantic messages so the app doesn't depend on ListView internals.
    Presentational: renders from a plain selection dict (node -> alt id)."""

    DEFAULT_CSS = """
    NodeList { width: 1fr; height: 1fr; background: $background; padding: 0; }
    NodeList > ListItem {
        padding: 0 1; background: $background;
        border-left: thick $background;
    }
    NodeList > ListItem > Horizontal { height: 1; }
    NodeList > ListItem.-highlight {
        background: $sel-bg; border-left: thick $accent;
    }
    NodeList > ListItem.-highlight .col-name { text-style: bold; }
    /* Keep col widths in sync with NodeListHeader (DEFAULT_CSS is scoped). */
    NodeList .col-status { width: 3; }
    NodeList .col-name { width: 1fr; color: $foreground; }
    NodeList .col-alt { width: 14; color: $text-muted; }
    NodeList .col-host { width: 8; color: $text-muted; }
    NodeList .col-alt.-set { color: $success; }
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
                Label(sel or "—", classes="col-alt -set" if sel else "col-alt",
                      markup=False),
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
            alt_label = row.query_one(".col-alt", Label)
            alt_label.update(sel or "—")
            alt_label.set_class(bool(sel), "-set")
            row.query_one(".col-host", Label).update(host)

    def on_list_view_highlighted(self, event) -> None:
        event.stop()
        if self.index is not None:
            self.post_message(self.NodeHighlighted(self.index))

    def on_list_view_selected(self, event) -> None:
        event.stop()
        if self.index is not None:
            self.post_message(self.NodeSelected(self.index))
