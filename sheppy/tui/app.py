# sheppy/tui/app.py
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Static

from sheppy.manifest import LoadResult, Node
from sheppy.profiles import ProfileState, ProfileStore, reconcile
from sheppy.tui.profile_modals import (
    SaveNameModal, LoadModal, ConfirmModal, ParamEditorModal,
)
from sheppy.tui.widgets.theme import SHEPPY_DARK
from sheppy.tui.widgets.header_bar import HeaderBar
from sheppy.tui.widgets.machines_strip import MachinesStrip
from sheppy.tui.widgets.status_footer import StatusFooter
from sheppy.tui.widgets.node_list import NodeList
from sheppy.tui.widgets.alternatives_panel import AlternativesPanel
from sheppy.tui.widgets.detail_tabs import DetailTabs, format_detail  # re-export

__all__ = ["SheppyApp", "format_detail"]


class SheppyApp(App):
    CSS = """
    #body { height: 1fr; }
    #errors { dock: bottom; height: auto; background: $error; color: $text; padding: 0 1; }
    #dialog { width: 60; height: auto; border: thick $accent; background: $surface; padding: 1 2; }
    """
    BINDINGS = [
        ("e", "toggle_errors", "Errors"),
        ("escape", "focus_nodes", "Nodes"),
        ("s", "save_profile", "Save"),
        ("l", "load_profile", "Load"),
        ("p", "edit_params", "Params"),
        ("1", "show_tab('tab-detail')", "Detail"),
        ("2", "show_tab('tab-topics')", "Topics"),
        ("3", "show_tab('tab-process')", "Process"),
        ("4", "show_tab('tab-yaml')", "YAML"),
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

    # ---- composition -----------------------------------------------------
    def compose(self) -> ComposeResult:
        yield HeaderBar()
        yield MachinesStrip(self.manifest.machines if self.manifest else [])
        nodes = self.manifest.nodes if self.manifest else []
        yield Horizontal(
            NodeList(nodes, self._current_selection()),
            AlternativesPanel(),
            DetailTabs(),
            id="body",
        )
        yield StatusFooter()
        errors = Static(self._errors_text(), id="errors")
        errors.display = False
        yield errors

    def on_mount(self) -> None:
        self.register_theme(SHEPPY_DARK)
        self.theme = "sheppy-dark"
        self._refresh_header()
        # call_after_refresh defers _populate_initial until the currently-queued
        # mount/compose messages have been processed, so TabbedContent's inner
        # panes (and #detail) are guaranteed to exist by the time it runs.
        self.call_after_refresh(self._populate_initial)

    # ---- view-model helpers ---------------------------------------------
    def _current_selection(self) -> dict:
        if not self.state or not self.manifest:
            return {}
        out = {}
        for n in self.manifest.nodes:
            sel = self.state.selected(n.name)
            if sel:
                out[n.name] = sel
        return out

    def _refresh_header(self) -> None:
        try:
            hb = self.query_one(HeaderBar)
        except NoMatches:
            return
        name = self.state.active_profile_name if self.state else None
        dirty = self.state.is_dirty if self.state else False
        node_count = len(self.manifest.nodes) if self.manifest else 0
        hb.update_state(name, dirty, self.path, node_count,
                        len(self.load_result.errors))

    def _errors_text(self) -> str:
        lines = [f"{e.location}: {e.message}" for e in self.load_result.errors]
        lines.extend(self._runtime_warnings)
        return "\n".join(lines) if lines else "no errors"

    def _current_node(self) -> "Node | None":
        if not self.manifest:
            return None
        idx = self.query_one(NodeList).index
        if idx is None:
            return None
        return self.manifest.nodes[idx]

    def _show_detail(self, node: Node) -> None:
        idx = self.query_one(AlternativesPanel).index
        alt = (node.alternatives[idx]
               if idx is not None and node.alternatives else None)
        self.query_one(DetailTabs).show(node, alt)

    def _populate_initial(self) -> None:
        # After the first refresh the TabbedContent panes exist; show detail
        # for the initially-highlighted node (alternatives were already
        # populated by the node list's startup highlight).
        node = self._current_node()
        if node:
            self._show_detail(node)

    # ---- navigation wiring ----------------------------------------------
    async def on_node_list_node_highlighted(
            self, event: NodeList.NodeHighlighted) -> None:
        if not self.manifest:
            return
        node = self.manifest.nodes[event.index]
        sel = self.state.selected(node.name) if self.state else None
        await self.query_one(AlternativesPanel).show(node, sel)
        self._show_detail(node)

    def on_node_list_node_selected(self, event: NodeList.NodeSelected) -> None:
        # Deliberate descent: move focus into the alternatives pane.
        self.query_one(AlternativesPanel).focus()

    def on_alternatives_panel_alternative_highlighted(
            self, event: AlternativesPanel.AlternativeHighlighted) -> None:
        node = self._current_node()
        if node and node.alternatives and event.index is not None:
            self.query_one(DetailTabs).show(node, node.alternatives[event.index])

    async def on_alternatives_panel_alternative_selected(
            self, event: AlternativesPanel.AlternativeSelected) -> None:
        node = self._current_node()
        if node is None or not self.state or event.index is None:
            return
        alt = node.alternatives[event.index]
        self.state.select(node.name, alt.id)
        self.query_one(NodeList).set_selection(self._current_selection())
        self._refresh_header()
        await self.query_one(AlternativesPanel).show(node, alt.id)

    # ---- actions ---------------------------------------------------------
    def action_toggle_errors(self) -> None:
        self.show_errors = not self.show_errors

    def action_focus_nodes(self) -> None:
        self.query_one(NodeList).focus()

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one(DetailTabs).activate(tab_id)

    def action_save_profile(self) -> None:
        if not self.state or not self.store:
            return
        if self.state.active_profile_name:
            name = self.state.active_profile_name
            try:
                self.store.save(self.state.to_profile(name))
            except ValueError as e:
                self._append_warnings([f"could not save profile '{name}': {e}"])
                return
            self.state.mark_saved(name)
            self._refresh_header()
        else:
            self.push_screen(SaveNameModal(), self._on_save_name)

    def _on_save_name(self, name: "str | None") -> None:
        if not name or not self.state or not self.store:
            return
        self.store.save(self.state.to_profile(name))
        self.state.mark_saved(name)
        self._refresh_header()

    def action_load_profile(self) -> None:
        if not self.state or not self.store:
            return
        self.push_screen(LoadModal(self.store.list_profiles()),
                         self._on_load_choice)

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
        self.state.apply(rec.selections, rec.overrides, name,
                         description=result.profile.description)
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
            self._append_warnings(
                [f"'{node.name}': no alternative selected to edit"])
            return
        params = self.state.effective_params(node.name)
        if not params:
            self._append_warnings(
                [f"'{node.name}': selected alternative declares no params"])
            return
        self.push_screen(
            ParamEditorModal(params),
            lambda values: self._on_params(node.name, values))

    def _on_params(self, node_name: str, values: "dict | None") -> None:
        if values is None or not self.state:
            return
        for param, value in values.items():
            self.state.override(node_name, param, value)
        self._refresh_header()

    # ---- errors / rebuild ------------------------------------------------
    def _append_warnings(self, warnings: list) -> None:
        self._runtime_warnings.extend(warnings)
        try:
            self.query_one("#errors", Static).update(self._errors_text())
        except NoMatches:
            pass
        self.show_errors = True

    def _rebuild_after_apply(self) -> None:
        self.query_one(NodeList).set_selection(self._current_selection())
        self._refresh_header()
        node = self._current_node()
        if node:
            self.run_worker(self._reshow(node), exclusive=False)

    async def _reshow(self, node: Node) -> None:
        sel = self.state.selected(node.name) if self.state else None
        await self.query_one(AlternativesPanel).show(node, sel)
        self._show_detail(node)

    def watch_show_errors(self, value: bool) -> None:
        try:
            self.query_one("#errors").display = value
        except NoMatches:
            pass
