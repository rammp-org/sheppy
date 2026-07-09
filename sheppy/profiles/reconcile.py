from dataclasses import dataclass

from sheppy.manifest import Manifest
from sheppy.profiles.models import Profile


@dataclass(frozen=True)
class ReconcileResult:
    selections: dict[str, str]
    overrides: dict[str, dict[str, object]]
    warnings: list[str]


def reconcile(profile: Profile, manifest: Manifest) -> ReconcileResult:
    warnings: list[str] = []
    selections: dict[str, str] = {}
    selected_alts: dict = {}  # node_name -> resolved selected Alternative
    raw_selections = profile.selections if isinstance(profile.selections, dict) else {}
    for node_name, alt_id in raw_selections.items():
        node = manifest.node(node_name)
        if node is None:
            warnings.append(f"dropped selection: unknown node '{node_name}'")
            continue
        alt = next((a for a in node.alternatives if a.id == alt_id), None)
        if alt is None:
            warnings.append(
                f"dropped selection: node '{node_name}' has no alternative '{alt_id}'")
            continue
        selections[node_name] = alt_id
        selected_alts[node_name] = alt

    overrides: dict[str, dict[str, object]] = {}
    raw_overrides = profile.overrides if isinstance(profile.overrides, dict) else {}
    for node_name, params in raw_overrides.items():
        if node_name not in selections:
            warnings.append(
                f"dropped overrides for '{node_name}': node is not selected")
            continue
        if not isinstance(params, dict):
            warnings.append(
                f"dropped overrides for '{node_name}': not a mapping")
            continue
        declared = selected_alts[node_name].params
        kept: dict[str, object] = {}
        for key, value in params.items():
            if key not in declared:
                warnings.append(
                    f"dropped override '{node_name}.{key}': not a declared param")
                continue
            kept[key] = value
        if kept:
            overrides[node_name] = kept

    return ReconcileResult(selections=selections, overrides=overrides, warnings=warnings)
