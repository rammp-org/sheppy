# sheppy/tui/profile_modals.py
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label

from sheppy.profiles import NAME_RE


class SaveNameModal(ModalScreen["str | None"]):
    """Prompt for a profile name; dismiss with the name or None."""

    def __init__(self, initial: str = "") -> None:
        super().__init__()
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Save profile as:")
            yield Input(value=self._initial, placeholder="name", id="name")
            yield Label("", id="name-error")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if not NAME_RE.match(name):
            self.query_one("#name-error", Label).update(
                "invalid name — use letters, digits, '-' or '_'")
            return
        self.dismiss(name)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
