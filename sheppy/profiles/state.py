from sheppy.manifest import Manifest
from sheppy.profiles.models import Profile
from sheppy.selection import SelectionState


class ProfileState:
    def __init__(self, manifest: Manifest) -> None:
        self._manifest = manifest
        self._selection = SelectionState(manifest)
        self._overrides: dict = {}
        self._description: str = ""
        self.active_profile_name: "str | None" = None
        self.is_dirty: bool = False

    # --- selection passthroughs ---
    def select(self, node_name: str, alternative_id: str) -> None:
        self._selection.select(node_name, alternative_id)
        self.is_dirty = True

    def clear(self, node_name: str) -> None:
        self._selection.clear(node_name)
        self.is_dirty = True

    def selected(self, node_name: str) -> "str | None":
        return self._selection.selected(node_name)

    def selected_alt(self, node_name: str):
        alt_id = self._selection.selected(node_name)
        if alt_id is None:
            return None
        node = self._manifest.node(node_name)
        if node is None:
            return None
        for a in node.alternatives:
            if a.id == alt_id:
                return a
        return None

    # --- overrides ---
    def override(self, node_name: str, param: str, value: object) -> None:
        alt = self.selected_alt(node_name)
        if alt is None or param not in alt.params:
            raise KeyError(
                f"param '{param}' is not declared on the selected alternative "
                f"for node '{node_name}'")
        if value == alt.params[param]:
            self.clear_override(node_name, param)
            return
        self._overrides.setdefault(node_name, {})[param] = value
        self.is_dirty = True

    def clear_override(self, node_name: str, param: str) -> None:
        node_overrides = self._overrides.get(node_name)
        if node_overrides is not None:
            node_overrides.pop(param, None)
            if not node_overrides:
                self._overrides.pop(node_name, None)
        self.is_dirty = True

    def effective_params(self, node_name: str) -> dict:
        alt = self.selected_alt(node_name)
        if alt is None:
            return {}
        merged = dict(alt.params)
        merged.update(self._overrides.get(node_name, {}))
        return merged

    # --- lifecycle ---
    def apply(self, selections: dict, overrides: dict,
              profile_name: "str | None", description: str = "") -> None:
        self._selection = SelectionState(self._manifest)
        for node_name, alt_id in selections.items():
            self._selection.select(node_name, alt_id)
        self._overrides = {n: dict(p) for n, p in overrides.items()}
        self._description = description
        self.active_profile_name = profile_name
        self.is_dirty = False

    def to_profile(self, name: str) -> Profile:
        selections: dict = {}
        for node in self._manifest.nodes:
            sel = self._selection.selected(node.name)
            if sel is not None:
                selections[node.name] = sel
        overrides = {n: dict(p) for n, p in self._overrides.items() if p}
        return Profile(name=name, selections=selections, overrides=overrides,
                        description=self._description)

    def mark_saved(self, name: str) -> None:
        self.active_profile_name = name
        self.is_dirty = False
