from typing import Callable
from sheppy.manifest import Manifest

ChangeListener = Callable[[str, "str | None"], None]


class SelectionState:
    def __init__(self, manifest: Manifest) -> None:
        self._manifest = manifest
        self._selected: dict[str, str] = {}
        self._listeners: list[ChangeListener] = []

    def on_change(self, callback: ChangeListener) -> None:
        self._listeners.append(callback)

    def _notify(self, node_name: str, alt_id: "str | None") -> None:
        for cb in self._listeners:
            cb(node_name, alt_id)

    def _node(self, node_name: str):
        node = self._manifest.node(node_name)
        if node is None:
            raise KeyError(f"unknown node: {node_name}")
        return node

    def select(self, node_name: str, alternative_id: str) -> None:
        node = self._node(node_name)
        if not any(a.id == alternative_id for a in node.alternatives):
            raise KeyError(f"unknown alternative '{alternative_id}' for node '{node_name}'")
        self._selected[node_name] = alternative_id
        self._notify(node_name, alternative_id)

    def clear(self, node_name: str) -> None:
        self._node(node_name)
        self._selected.pop(node_name, None)
        self._notify(node_name, None)

    def selected(self, node_name: str) -> "str | None":
        return self._selected.get(node_name)
