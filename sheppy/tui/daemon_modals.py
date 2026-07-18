"""Modals for daemon actions. Presentational; the app executes."""
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from sheppy.tui.widgets.theme import c

_VERB_COLOR = {"stop": "red", "restart": "yellow", "start": "green"}


class ConvergeModal(ModalScreen[bool]):
    BINDINGS = [("enter", "apply", "Apply"), ("escape", "cancel", "Cancel")]

    def __init__(self, actions: "list[tuple[str, str]]") -> None:
        super().__init__()
        self._actions = actions

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(c("fg", f"converge — {len(self._actions)} action(s)"))
            for verb, node in self._actions:
                # Whole line in one color span: c() escapes the joined text,
                # so a color-tag boundary can never split "verb node" and
                # break substring checks against the plan text.
                yield Static(c(_VERB_COLOR[verb], f"{verb} {node}"))
            yield Static(c("muted", "enter apply · esc cancel"))

    def action_apply(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
