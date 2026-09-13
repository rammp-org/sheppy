import asyncio

from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from textual.markup import escape

from sheppy.manifest import Alternative, Node
from sheppy.tui.widgets.theme import c


class AlternativeRow(ListItem):
    """A row that remembers the node and alternative it renders. Handlers act
    on what the row shows, not on its position: the pane repopulates
    asynchronously, so its rows can be out of step with the app's node
    cursor."""

    def __init__(self, node: Node, alt: Alternative, *children, **kwargs):
        super().__init__(*children, **kwargs)
        self.node = node
        self.alt = alt


class AlternativesPanel(ListView):
    """Middle pane. Per alternative: radio + id, then a kind·package subline
    with declared topic counts (↑pub ↓sub). Running/stopped state is a phase-2b
    concern and deliberately absent here. Re-posts semantic messages."""

    DEFAULT_CSS = """
    AlternativesPanel { width: 1fr; height: 1fr; background: $background; padding: 0; }
    AlternativesPanel > ListItem {
        height: auto; padding: 1 1; background: $background;
        border-left: thick $background;
    }
    /* Pin the item body to its content height so the highlighted row's
       accent bar spans only the row, not the whole pane. */
    AlternativesPanel > ListItem > Vertical { height: auto; }
    AlternativesPanel > ListItem.-highlight {
        background: $sel-bg; border-left: thick $accent;
    }
    AlternativesPanel .alt-main { text-style: bold; }
    AlternativesPanel .alt-sub { color: $text-muted; }
    """

    # Carry what the row rendered, not its index: the app's node cursor may
    # already be on another node by the time the message is handled.
    class AlternativeHighlighted(Message):
        def __init__(self, node: Node, alt: Alternative) -> None:
            self.node = node
            self.alt = alt
            super().__init__()

    class AlternativeSelected(Message):
        def __init__(self, node: Node, alt: Alternative) -> None:
            self.node = node
            self.alt = alt
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(id="alternatives", **kwargs)
        # Two overlapping rebuilds (a highlight and a worker's reshow) would
        # interleave clear/append and mount duplicate alt-N ids.
        self._rebuild = asyncio.Lock()

    def highlighted_row(self) -> "AlternativeRow | None":
        """The alternative row under the cursor, or None (nothing highlighted,
        or the pane holds a note)."""
        row = self.highlighted_child
        return row if isinstance(row, AlternativeRow) else None

    async def show(self, node: Node, selected_id: "str | None") -> None:
        async with self._rebuild:
            await self.clear()
            for j, alt in enumerate(node.alternatives):
                await self.append(AlternativeRow(
                    node, alt, self._widget(alt, alt.id == selected_id),
                    id=f"alt-{j}"))

    async def show_note(self, text: str) -> None:
        async with self._rebuild:
            await self.clear()
            await self.append(ListItem(
                Label(text, classes="alt-note", markup=False), disabled=True))

    def _widget(self, alt, is_sel):
        radio = "◉" if is_sel else "○"
        ckey = "green" if is_sel else "muted"
        pkg = alt.package or alt.command or "—"
        counts = f"↑{len(alt.publishes)} ↓{len(alt.subscribes)}"
        return Vertical(
            Label(f"{c(ckey, radio)} {escape(alt.id)}", classes="alt-main"),
            Label(c("muted", f"{alt.kind} · {pkg}   {counts}"), classes="alt-sub"),
        )

    def on_list_view_highlighted(self, event) -> None:
        event.stop()
        row = self.highlighted_row()
        if row is not None:
            self.post_message(self.AlternativeHighlighted(row.node, row.alt))

    def on_list_view_selected(self, event) -> None:
        event.stop()
        row = self.highlighted_row()
        if row is not None:
            self.post_message(self.AlternativeSelected(row.node, row.alt))
