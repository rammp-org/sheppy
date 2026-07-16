# sheppy/tui/app.py
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Static

from sheppy.launch import resolve
from sheppy.manifest import LoadResult, Node
from sheppy.profiles import ProfileState, ProfileStore, reconcile
from sheppy.tui.profile_modals import (
    SaveNameModal, LoadModal, ConfirmModal, ParamEditorModal,
)
from sheppy.tui.widgets.theme import SHEPPY_DARK, c
from sheppy.tui.widgets.header_bar import HeaderBar
from sheppy.tui.widgets.machines_strip import MachinesStrip
from sheppy.tui.widgets.status_footer import StatusFooter
from sheppy.tui.widgets.node_list import NodeList, NodeListHeader, RuntimeCell
from sheppy.tui.widgets.alternatives_panel import AlternativesPanel
from sheppy.tui.widgets.detail_tabs import DetailTabs, format_detail  # re-export
from sheppy.tui.widgets import status as st

__all__ = ["SheppyApp", "format_detail"]


class SheppyApp(App):
    CSS = """
    Screen { background: $background; }
    #body { height: 1fr; }
    /* max-width keeps the mockup's proportions on very wide terminals —
       otherwise the 1fr name column pushes ALTERNATIVE/HOST far right. */
    #nodes-pane { width: 34%; max-width: 66; height: 1fr; border-right: solid $divider; }
    #alts-pane { width: 26%; max-width: 46; height: 1fr; border-right: solid $divider; }
    #alts-head { height: 1; background: $subhead-bg; padding: 0 2; }
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
        ("space", "converge_node", "Apply"),
        ("x", "stop_node", "Stop"),
        ("r", "restart_node", "Restart"),
    ]
    show_errors = reactive(False)

    def __init__(self, load_result: LoadResult, path: str | None = None,
                 profiles_dir: str | None = None, client=None) -> None:
        super().__init__()
        self.load_result = load_result
        self.path = path
        self.manifest = load_result.manifest
        self.state: "ProfileState | None" = (
            ProfileState(self.manifest) if self.manifest else None)
        self.store: "ProfileStore | None" = (
            ProfileStore(profiles_dir) if profiles_dir else None)
        self._runtime_warnings: list = []
        self._client = client
        self.actual: dict = {}
        self.daemon_connected = False
        # Register/select the theme in __init__ so its custom CSS variables
        # ($sel-bg, $chip-border, $divider, …) are defined before the widget
        # DEFAULT_CSS is parsed at mount time.
        self.register_theme(SHEPPY_DARK)
        self.theme = "sheppy-dark"

    # ---- composition -----------------------------------------------------
    def compose(self) -> ComposeResult:
        yield HeaderBar()
        yield MachinesStrip(self.manifest.machines if self.manifest else [])
        nodes = self.manifest.nodes if self.manifest else []
        yield Horizontal(
            Vertical(
                NodeListHeader(),
                NodeList(nodes, self._current_selection()),
                id="nodes-pane",
            ),
            Vertical(
                Static(c("muted", "ALTERNATIVES"), id="alts-head"),
                AlternativesPanel(),
                id="alts-pane",
            ),
            DetailTabs(),
            id="body",
        )
        yield StatusFooter()
        errors = Static(self._errors_text(), id="errors", markup=False)
        errors.display = False
        yield errors

    def on_mount(self) -> None:
        self._refresh_header()
        # call_after_refresh defers _populate_initial until the currently-queued
        # mount/compose messages have been processed, so TabbedContent's inner
        # panes (and #detail) are guaranteed to exist by the time it runs.
        self.call_after_refresh(self._populate_initial)
        self.run_worker(self._daemon_connect(spawn=False), exclusive=False)

    # ---- daemon connection -------------------------------------------------
    async def _daemon_connect(self, spawn: bool) -> bool:
        if self._client is None:
            from sheppy.daemon.client import DaemonClient
            self._client = DaemonClient()
        if not await self._client.connect(spawn=spawn):
            self._refresh_runtime()
            return False
        from sheppy.daemon.client import DaemonError
        try:
            self._client.on_event(self._on_daemon_event)
            await self._client.subscribe()
            reply = await self._client.request("status")
        except DaemonError:
            self.daemon_connected = False
            self._refresh_runtime()
            return False
        if not reply.get("ok"):
            self.daemon_connected = False
            self._refresh_runtime()
            return False
        self.actual = reply["nodes"]
        self.daemon_connected = True
        self._refresh_runtime()
        return True

    async def _ensure_daemon(self) -> bool:
        if self.daemon_connected:
            return True
        if not await self._daemon_connect(spawn=True):
            self._append_warnings(["could not start sheppyd"])
            return False
        return True

    def _on_daemon_event(self, event: dict) -> None:
        if event.get("event") != "status":
            return
        self.actual[event["node"]] = event
        self._refresh_runtime()

    # ---- runtime view -------------------------------------------------------
    def _running_count(self) -> int:
        if not self.manifest:
            return 0
        return sum(1 for n in self.manifest.nodes
                   if self.actual.get(n.name, {}).get("state") == "running")

    def _refresh_runtime(self) -> None:
        if not self.manifest:
            return
        cells = {}
        for node in self.manifest.nodes:
            payload = self.actual.get(node.name)
            if not self.daemon_connected:
                cells[node.name] = RuntimeCell(st.Status.UNKNOWN)
                continue
            state = payload["state"] if payload else None
            cell = RuntimeCell(
                st.runtime(state), drift=self._drift(node, payload),
                usage=_fmt_usage(payload.get("usage") if payload else None))
            if payload and payload["state"] in ("launching", "running") \
                    and not any(a.id == payload["spec"]["alt_id"]
                                for a in node.alternatives):
                cell.usage = "alt?"      # running an alt this manifest lacks
            cells[node.name] = cell
        try:
            self.query_one(NodeList).set_runtime(cells)
            self.query_one(StatusFooter).set_daemon(
                self.daemon_connected, self._running_count(),
                len(self.manifest.nodes))
        except NoMatches:
            pass
        self._refresh_header()

    def _drift(self, node, payload) -> bool:
        alive = payload is not None and payload["state"] in ("launching",
                                                             "running")
        alt = self.state.selected_alt(node.name) if self.state else None
        if not alive:
            return alt is not None          # desired but not running
        if alt is None:
            return True                     # running but nothing desired
        spec, _ = resolve(self.manifest, node.name, alt,
                          self.state.effective_params(node.name))
        return payload["spec"]["argv"] != list(spec.argv)

    # ---- daemon actions -------------------------------------------------------
    async def action_converge_node(self) -> None:
        node = self._current_node()
        if node is None or not self.state:
            return
        alt = self.state.selected_alt(node.name)
        payload = self.actual.get(node.name)
        alive = payload and payload["state"] in ("launching", "running")
        if alt is None and not alive:
            self._append_warnings(
                [f"'{node.name}': no alternative selected"])
            return
        if not await self._ensure_daemon():
            return
        if alt is None:                     # converge-to-nothing = stop
            await self._request_safely("stop", node=node.name)
            return
        spec, warns = resolve(self.manifest, node.name, alt,
                              self.state.effective_params(node.name))
        if warns:
            self._append_warnings(warns)
        await self._request_safely("launch", spec=spec.to_wire())

    async def action_stop_node(self) -> None:
        node = self._current_node()
        if node and self.daemon_connected:
            await self._request_safely("stop", node=node.name)

    async def action_restart_node(self) -> None:
        node = self._current_node()
        if node and self.daemon_connected:
            await self._request_safely("restart", node=node.name)

    async def _request_safely(self, op: str, **kw) -> "dict | None":
        from sheppy.daemon.client import DaemonError
        try:
            reply = await self._client.request(op, **kw)
        except DaemonError as e:
            self.daemon_connected = False
            self._append_warnings([str(e)])
            self._refresh_runtime()
            return None
        if not reply.get("ok"):
            self._append_warnings([f"{op}: {reply.get('error')}"])
        return reply

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
        running = self._running_count() if self.daemon_connected else None
        hb.update_state(name, dirty, self.path, node_count,
                        len(self.load_result.errors), running=running)

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

    def _update_alts_head(self, node: Node) -> None:
        try:
            # NodeList's initial highlight can fire while sibling panes are
            # still mounting; _populate_initial re-drives this after refresh.
            self.query_one("#alts-head", Static).update(
                f"{c('muted', 'ALTERNATIVES ·')} {c('green', node.name)}"
                f" {c('muted', '· ' + node.select)}")
        except NoMatches:
            pass

    def _populate_initial(self) -> None:
        # After the first refresh the TabbedContent panes exist; show detail
        # and the alternatives subheader for the initially-highlighted node
        # (alternatives were already populated by the startup highlight).
        node = self._current_node()
        if node:
            self._update_alts_head(node)
            self._show_detail(node)

    # ---- navigation wiring ----------------------------------------------
    async def on_node_list_node_highlighted(
            self, event: NodeList.NodeHighlighted) -> None:
        if not self.manifest:
            return
        node = self.manifest.nodes[event.index]
        sel = self.state.selected(node.name) if self.state else None
        self._update_alts_head(node)
        await self.query_one(AlternativesPanel).show(node, sel)
        self._show_detail(node)

    def on_node_list_node_selected(self, event: NodeList.NodeSelected) -> None:
        # Deliberate descent: move focus into the alternatives pane, and
        # highlight the current selection (or the first alternative) so a
        # second Enter can select it immediately.
        panel = self.query_one(AlternativesPanel)
        panel.focus()
        node = self._current_node()
        if node and node.alternatives:
            sel = self.state.selected(node.name) if self.state else None
            panel.index = next(
                (i for i, a in enumerate(node.alternatives) if a.id == sel), 0)

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
        self._refresh_runtime()   # selection changed -> drift may too
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
        self._refresh_runtime()   # params changed -> drift may too

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
        self._refresh_runtime()   # selections changed -> drift may too
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


def _fmt_usage(usage: "dict | None") -> str:
    if not usage:
        return ""
    return f"{usage['cpu_pct']:.0f}% {usage['rss_mb']:.0f}M"
