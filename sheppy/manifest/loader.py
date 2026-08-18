from sheppy.manifest.models import Machine, Alternative, Node, Manifest
from sheppy.manifest.errors import ValidationError, LoadResult


def _build_alternative(raw: dict, loc: str, machine_names: set, errors: list) -> Alternative:
    from sheppy.launch.registry import UnknownKind, default_registry

    if not isinstance(raw, dict):
        errors.append(ValidationError(loc, "alternative entry must be a mapping"))
        return Alternative(id="", kind="")
    alt_id = raw.get("id")
    if not alt_id:
        errors.append(ValidationError(loc, "alternative is missing 'id'"))
    kind = raw.get("kind")
    registry = default_registry()
    try:
        launcher = registry.get(kind)
    except UnknownKind:
        launcher = None
        errors.append(ValidationError(
            loc, f"alternative '{alt_id}' has unknown kind {kind!r}; "
                 f"known kinds: {', '.join(registry.kinds()) or '(none)'}"))
    if launcher is not None:
        for msg in launcher.validate(raw):
            errors.append(ValidationError(loc, f"alternative '{alt_id}': {msg}"))
    machine = raw.get("machine")
    if machine is not None and machine not in machine_names:
        errors.append(ValidationError(
            loc, f"alternative '{alt_id}' references unknown machine '{machine}'"))
    return Alternative(
        id=alt_id or "", kind=kind or "", machine=machine,
        package=raw.get("package"), executable=raw.get("executable"),
        launch_file=raw.get("launch_file"), command=raw.get("command"),
        params=raw.get("params") or {},
        publishes=raw.get("publishes") or [], subscribes=raw.get("subscribes") or [],
        config=dict(raw))


def _build_node(raw: dict, loc: str, machine_names: set, errors: list) -> Node:
    if not isinstance(raw, dict):
        errors.append(ValidationError(loc, "node entry must be a mapping"))
        return Node(name="", alternatives=[])
    name = raw.get("name")
    if not name:
        errors.append(ValidationError(loc, "node is missing 'name'"))
    select = raw.get("select", "single")
    if select != "single":
        errors.append(ValidationError(loc, f"node 'select' must be 'single', got {select!r}"))
    raw_alts = raw.get("alternatives")
    alternatives = []
    if not isinstance(raw_alts, list) or not raw_alts:
        errors.append(ValidationError(loc, f"node '{name}' must have a non-empty 'alternatives' list"))
        raw_alts = raw_alts if isinstance(raw_alts, list) else []
    seen_ids = set()
    for j, raw_alt in enumerate(raw_alts):
        alt = _build_alternative(raw_alt, f"{loc}.alternatives[{j}]", machine_names, errors)
        if alt.id and alt.id in seen_ids:
            errors.append(ValidationError(
                f"{loc}.alternatives[{j}]", f"duplicate alternative id '{alt.id}'"))
        seen_ids.add(alt.id)
        alternatives.append(alt)
    return Node(name=name or "", alternatives=alternatives,
                description=raw.get("description", ""), select=select)


def parse_manifest(data: object) -> LoadResult:
    errors: list[ValidationError] = []
    if not isinstance(data, dict):
        return LoadResult(None, [ValidationError("<root>", "manifest must be a mapping")])

    raw_machines = data.get("machines", [])
    if not isinstance(raw_machines, list):
        errors.append(ValidationError("machines", "'machines' must be a list"))
        raw_machines = []
    machines = []
    for i, rm in enumerate(raw_machines):
        if not isinstance(rm, dict):
            errors.append(ValidationError(f"machines[{i}]", "machine entry must be a mapping"))
            continue
        for required in ("name", "host", "user"):
            if not rm.get(required):
                errors.append(ValidationError(f"machines[{i}]", f"machine missing '{required}'"))
        machines.append(Machine(name=rm.get("name", ""), host=rm.get("host", ""),
                                user=rm.get("user", ""), ros_setup=rm.get("ros_setup")))
    machine_names = {m.name for m in machines}

    raw_nodes = data.get("nodes", [])
    if not isinstance(raw_nodes, list):
        errors.append(ValidationError("nodes", "'nodes' must be a list"))
        raw_nodes = []
    nodes = []
    seen_names = set()
    for i, rn in enumerate(raw_nodes):
        node = _build_node(rn, f"nodes[{i}]", machine_names, errors)
        if node.name and node.name in seen_names:
            errors.append(ValidationError(f"nodes[{i}]", f"duplicate node name '{node.name}'"))
        seen_names.add(node.name)
        nodes.append(node)

    return LoadResult(Manifest(machines=machines, nodes=nodes), errors)


def load_manifest(path: str) -> LoadResult:
    import yaml
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        return LoadResult(None, [ValidationError("<file>", f"manifest not found: {path}")])
    except yaml.YAMLError as exc:
        return LoadResult(None, [ValidationError("<file>", f"invalid YAML: {exc}")])
    return parse_manifest(raw)
