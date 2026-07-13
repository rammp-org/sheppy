# sheppy/tui/app.py
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Header, Footer, Label, ListView, ListItem, Static

from sheppy.manifest import LoadResult, Node, Alternative
from sheppy.profiles import ProfileState, ProfileStore, reconcile
from sheppy.tui.profile_modals import (
    SaveNameModal, LoadModal, ConfirmModal, ParamEditorModal,
)


def _node_label(node: Node, state: "ProfileState | None") -> str:
    chosen = state.selected(node.name) if state else None
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
    #alternatives { height: auto; max-height: 50%; border: solid $accent; }
    #detail { height: 1fr; border: solid $accent; padding: 0 1; }
    #status { dock: bottom; height: 1; background: $panel; }
    #errors { dock: bottom; height: auto; background: $error; color: $text; padding: 0 1; }
    #profilebar { dock: top; height: 1; background: $boost; color: $text; padding: 0 1; }
    #dialog { width: 60; height: auto; border: thick $accent; background: $surface; padding: 1 2; }
    """
    BINDINGS = [
        ("e", "toggle_errors", "Errors"),
        ("escape", "focus_nodes", "Nodes"),
        ("s", "save_profile", "Save"),
        ("l", "load_profile", "Load"),
        ("p", "edit_params", "Params"),
    ]
    show_errors = reactive(False)

    def __init__(self, load_result: LoadResult, path: str | None = None,
                 profiles_dir: str | None = None) -> None:
        super().__init__()
        self.load_result = load_result
        self.path = path
        self.manifest = load_result.manifest
        self.state: "ProfileState | None" = (
            ProfileState(self.manifest) if self.manifest else None)
        self.store: "ProfileStore | None" = (
            ProfileStore(profiles_dir) if profiles_dir else None)
        self._runtime_warnings: list = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._profile_bar_text(), id="profilebar")
        node_items = []
        if self.manifest:
            for i, node in enumerate(self.manifest.nodes):
                node_items.append(
                    ListItem(Label(_node_label(node, self.state)), id=f"node-{i}"))
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

    def _profile_bar_text(self) -> str:
        if not self.state:
            return "Profile: <none>"
        name = self.state.active_profile_name or "<none>"
        dirty = " *" if self.state.is_dirty else ""
        return f"Profile: {name}{dirty}"

    def _refresh_profile_bar(self) -> None:
        try:
            self.query_one("#profilebar", Static).update(self._profile_bar_text())
        except NoMatches:
            pass

    def _status_text(self) -> str:
        n = len(self.load_result.errors)
        state = "ok" if n == 0 else f"{n} error(s)"
        return f"{self.path or '<no file>'} — {state}"

    def _errors_text(self) -> str:
        lines = [f"{e.location}: {e.message}" for e in self.load_result.errors]
        lines.extend(self._runtime_warnings)
        if not lines:
            return "no errors"
        return "\n".join(lines)

    def action_toggle_errors(self) -> None:
        self.show_errors = not self.show_errors

    def action_focus_nodes(self) -> None:
        self.query_one("#nodes").focus()

    def action_save_profile(self) -> None:
        if not self.state or not self.store:
            return
        if self.state.active_profile_name:
            self.store.save(self.state.to_profile(self.state.active_profile_name))
            self.state.mark_saved(self.state.active_profile_name)
            self._refresh_profile_bar()
        else:
            self.push_screen(SaveNameModal(), self._on_save_name)

    def _on_save_name(self, name: "str | None") -> None:
        if not name or not self.state or not self.store:
            return
        self.store.save(self.state.to_profile(name))
        self.state.mark_saved(name)
        self._refresh_profile_bar()

    def action_load_profile(self) -> None:
        if not self.state or not self.store:
            return
        self.push_screen(LoadModal(self.store.list_profiles()), self._on_load_choice)

    def _on_load_choice(self, choice: "tuple | None") -> None:
        if not choice or not self.state or not self.store:
            return
        action, name = choice
        if action == "delete":
            self.push_screen(
                ConfirmModal(f"Delete profile '{name}'?"),
                lambda ok: self.store.delete(name) if ok else None)
            return
        result = self.store.load(name)
        if result.profile is None:
            self._append_warnings(result.errors)
            return
        rec = reconcile(result.profile, self.manifest)
        self.state.apply(rec.selections, rec.overrides, name)
        if rec.warnings:
            self._append_warnings(rec.warnings)
        self._rebuild_after_apply()

    def action_edit_params(self) -> None:
        if not self.state:
            return
        node = self._current_node()
        if node is None:
            return
        if self.state.selected_alt(node.name) is None:
            self._append_warnings([f"'{node.name}': no alternative selected to edit"])
            return
        params = self.state.effective_params(node.name)
        if not params:
            self._append_warnings([f"'{node.name}': selected alternative declares no params"])
            return
        self.push_screen(
            ParamEditorModal(params),
            lambda values: self._on_params(node.name, values))

    def _on_params(self, node_name: str, values: "dict | None") -> None:
        if values is None or not self.state:
            return
        for param, value in values.items():
            self.state.override(node_name, param, value)
        self._refresh_profile_bar()

    def _append_warnings(self, warnings: list) -> None:
        self._runtime_warnings.extend(warnings)
        try:
            self.query_one("#errors", Static).update(self._errors_text())
        except NoMatches:
            pass
        self.show_errors = True

    def _rebuild_after_apply(self) -> None:
        if self.manifest:
            for i, node in enumerate(self.manifest.nodes):
                try:
                    self.query_one(f"#node-{i} Label", Label).update(
                        _node_label(node, self.state))
                except NoMatches:
                    pass
        self._refresh_profile_bar()

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
        chosen = self.state.selected(node.name) if self.state else None
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
        if event.list_view.id != "alternatives" or not self.state:
            return
        node = self._current_node()
        alt_idx = self.query_one("#alternatives", ListView).index
        if node is None or alt_idx is None:
            return
        alt = node.alternatives[alt_idx]
        self.state.select(node.name, alt.id)
        self._refresh_node_label(node)
        self._refresh_profile_bar()
        await self._populate_alternatives(node)

    def _refresh_node_label(self, node: Node) -> None:
        idx = self.query_one("#nodes", ListView).index
        label = self.query_one(f"#node-{idx} Label", Label)
        label.update(_node_label(node, self.state))
