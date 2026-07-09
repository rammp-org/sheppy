from dataclasses import dataclass

from sheppy.manifest import Manifest
from sheppy.profiles.models import Profile


@dataclass(frozen=True)
class ReconcileResult:
    selections: dict
    overrides: dict
    warnings: list


def _selected_alt(manifest: Manifest, node_name: str, alt_id: str):
    node = manifest.node(node_name)
    if node is None:
        return None
    for a in node.alternatives:
        if a.id == alt_id:
            return a
    return None


def reconcile(profile: Profile, manifest: Manifest) -> ReconcileResult:
    warnings: list = []
    selections: dict = {}
    for node_name, alt_id in profile.selections.items():
        node = manifest.node(node_name)
        if node is None:
            warnings.append(f"dropped selection: unknown node '{node_name}'")
            continue
        if not any(a.id == alt_id for a in node.alternatives):
            warnings.append(
                f"dropped selection: node '{node_name}' has no alternative '{alt_id}'")
            continue
        selections[node_name] = alt_id

    overrides: dict = {}
    for node_name, params in profile.overrides.items():
        if node_name not in selections:
            warnings.append(
                f"dropped overrides for '{node_name}': node is not selected")
            continue
        alt = _selected_alt(manifest, node_name, selections[node_name])
        declared = alt.params if alt else {}
        kept: dict = {}
        for key, value in params.items():
            if key not in declared:
                warnings.append(
                    f"dropped override '{node_name}.{key}': not a declared param")
                continue
            kept[key] = value
        if kept:
            overrides[node_name] = kept

    return ReconcileResult(selections=selections, overrides=overrides, warnings=warnings)
