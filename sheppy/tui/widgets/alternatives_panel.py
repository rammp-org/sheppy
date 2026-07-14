from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from textual.markup import escape

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
            Label(f"{c(ckey, radio)} {escape(alt.id)}", classes="alt-main"),
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
