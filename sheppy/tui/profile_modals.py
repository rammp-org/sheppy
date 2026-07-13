# sheppy/tui/profile_modals.py
import yaml

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListView, ListItem

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
            event.stop()
            self.dismiss(None)


class LoadModal(ModalScreen["tuple | None"]):
    """List saved profiles. Enter=load, d=delete, Esc=cancel."""

    def __init__(self, names: list) -> None:
        super().__init__()
        self._names = names

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Load profile — Enter=load, d=delete, Esc=cancel")
            items = [ListItem(Label(n), id=f"prof-{i}")
                     for i, n in enumerate(self._names)]
            yield ListView(*items, id="proflist")

    def on_mount(self) -> None:
        self.query_one("#proflist", ListView).focus()

    def _highlighted(self) -> "str | None":
        idx = self.query_one("#proflist", ListView).index
        if idx is None:
            return None
        return self._names[idx]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = self._highlighted()
        if name is not None:
            self.dismiss(("load", name))

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
        elif event.key == "d":
            event.stop()
            name = self._highlighted()
            if name is not None:
                self.dismiss(("delete", name))


class ConfirmModal(ModalScreen[bool]):
    """Yes/no confirmation. y=True, n/Esc=False."""

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._prompt)
            yield Label("y = yes, n = no")

    def on_key(self, event) -> None:
        if event.key == "y":
            event.stop()
            self.dismiss(True)
        elif event.key in ("n", "escape"):
            event.stop()
            self.dismiss(False)


class ParamEditorModal(ModalScreen["dict | None"]):
    """Edit declared params of the selected alternative. Enter=apply, Esc=cancel.

    Each field is parsed as a YAML scalar so 30, 1.5, true, and plain strings
    round-trip naturally. A field that fails to parse is rejected inline.
    """

    def __init__(self, params: dict) -> None:
        super().__init__()
        self._params = params

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Edit params — Enter=apply, Esc=cancel")
            for name, value in self._params.items():
                yield Label(name)
                yield Input(value=str(value), id=f"param-{name}")
            yield Label("", id="param-error")

    def on_mount(self) -> None:
        # Focus the first param field so pilot key presses land and Enter submits.
        first = next(iter(self._params), None)
        if first is not None:
            self.query_one(f"#param-{first}", Input).focus()

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # A focused Input consumes Enter and emits Submitted (Enter never reaches
        # on_key), so submit here. Any field submitting applies the whole form.
        self._submit()

    def _submit(self) -> None:
        parsed: dict = {}
        for name in self._params:
            raw = self.query_one(f"#param-{name}", Input).value
            try:
                parsed[name] = yaml.safe_load(raw)
            except yaml.YAMLError:
                self.query_one("#param-error", Label).update(
                    f"invalid value for '{name}'")
                return
        self.dismiss(parsed)
