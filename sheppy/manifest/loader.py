import re

from sheppy.manifest.models import Machine, Alternative, Node, Manifest
from sheppy.manifest.errors import ValidationError, LoadResult

# Node names and alternative ids become docker container names and scratch
# directory paths, so they are restricted to a safe identifier.
_NAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
_NAME = re.compile(_NAME_PATTERN)


def json_safe(value):
    """value as it reads back from JSON. Params go to sheppyd as JSON, which
    has no date, so a YAML date such as 2024-01-01 becomes its text (#188)."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float)):
        return value
    return str(value)


def _check_name(value, what: str, loc: str, errors: list) -> None:
    if not (isinstance(value, str) and _NAME.fullmatch(value)):
        errors.append(ValidationError(
            loc, f"{what} {value!r} must be a string matching {_NAME_PATTERN}"))


def _duplicates(names: list) -> set:
    """The non-empty names that occur more than once."""
    return {n for n in names if n and names.count(n) > 1}


def _build_alternative(raw: dict, loc: str, machine_names: set,
                       dup_machines: set, errors: list) -> Alternative:
    from sheppy.launch.registry import UnknownKind, default_registry

    if not isinstance(raw, dict):
        errors.append(ValidationError(loc, "alternative entry must be a mapping"))
        return Alternative(id="", kind="")
    alt_id = raw.get("id")
    if not alt_id:
        errors.append(ValidationError(loc, "alternative is missing 'id'"))
    else:
        _check_name(alt_id, "alternative id", f"{loc}.id", errors)
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
        try:
            msgs = launcher.validate(raw)
        except Exception as e:
            msgs = [f"launcher {kind!r} validate() raised: {type(e).__name__}: {e}"]
        for msg in msgs:
            errors.append(ValidationError(loc, f"alternative '{alt_id}': {msg}"))
    machine = raw.get("machine")
    if machine is not None and machine not in machine_names:
        errors.append(ValidationError(
            loc, f"alternative '{alt_id}' references unknown machine '{machine}'"))
    elif machine in dup_machines:       # which definition it means is a guess (#231)
        errors.append(ValidationError(
            loc, f"alternative '{alt_id}' references machine '{machine}', "
                 f"which is defined more than once"))
    params = raw.get("params")
    if params is not None and not isinstance(params, dict):
        errors.append(ValidationError(
            f"{loc}.params", f"alternative '{alt_id}': 'params' must be a mapping, "
                             f"got {type(params).__name__}"))
        params = None
    topics = {}
    for key in ("publishes", "subscribes"):
        value = raw.get(key)
        if value is not None and not (isinstance(value, list)
                                      and all(isinstance(v, str) for v in value)):
            errors.append(ValidationError(
                f"{loc}.{key}", f"alternative '{alt_id}': '{key}' must be a list "
                                f"of strings, got {type(value).__name__}"))
            value = None
        topics[key] = value or []
    return Alternative(
        id=alt_id or "", kind=kind or "", machine=machine,
        package=raw.get("package"), executable=raw.get("executable"),
        launch_file=raw.get("launch_file"), command=raw.get("command"),
        params=json_safe(params or {}),
        publishes=topics["publishes"], subscribes=topics["subscribes"],
        raw=dict(raw))


def _build_node(raw: dict, loc: str, machine_names: set, dup_machines: set,
                errors: list) -> Node:
    if not isinstance(raw, dict):
        errors.append(ValidationError(loc, "node entry must be a mapping"))
        return Node(name="", alternatives=[])
    name = raw.get("name")
    if not name:
        errors.append(ValidationError(loc, "node is missing 'name'"))
    else:
        _check_name(name, "node name", f"{loc}.name", errors)
    select = raw.get("select", "single")
    if select != "single":
        errors.append(ValidationError(loc, f"node 'select' must be 'single', got {select!r}"))
    raw_alts = raw.get("alternatives")
    alternatives = []
    if not isinstance(raw_alts, list) or not raw_alts:
        errors.append(ValidationError(loc, f"node '{name}' must have a non-empty 'alternatives' list"))
        raw_alts = raw_alts if isinstance(raw_alts, list) else []
    for j, raw_alt in enumerate(raw_alts):
        alternatives.append(_build_alternative(
            raw_alt, f"{loc}.alternatives[{j}]", machine_names, dup_machines, errors))
    # Filed at every copy, not just the later ones, so none of them launches:
    # which one was meant is a guess (#231).
    ids = [a.id for a in alternatives]
    dup_ids = _duplicates(ids)
    for j, alt_id in enumerate(ids):
        if alt_id in dup_ids:
            errors.append(ValidationError(
                f"{loc}.alternatives[{j}]", f"duplicate alternative id '{alt_id}'"))
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
    dup_machines = _duplicates([m.name for m in machines])
    for i, m in enumerate(machines):
        if m.name in dup_machines:
            errors.append(ValidationError(f"machines[{i}]", f"duplicate machine name '{m.name}'"))

    raw_nodes = data.get("nodes", [])
    if not isinstance(raw_nodes, list):
        errors.append(ValidationError("nodes", "'nodes' must be a list"))
        raw_nodes = []
    nodes = [_build_node(rn, f"nodes[{i}]", machine_names, dup_machines, errors)
             for i, rn in enumerate(raw_nodes)]
    names = [n.name for n in nodes]
    dup_names = _duplicates(names)
    for i, name in enumerate(names):
        if name in dup_names:      # at every copy, as for alternative ids (#231)
            errors.append(ValidationError(f"nodes[{i}]", f"duplicate node name '{name}'"))

    return LoadResult(Manifest(machines=machines, nodes=nodes), errors)


def load_manifest(path: str) -> LoadResult:
    import yaml
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        return LoadResult(None, [ValidationError("<file>", f"manifest not found: {path}")])
    except OSError as exc:              # a directory, no read permission (#100)
        return LoadResult(None, [ValidationError("<file>", f"cannot read manifest: {exc}")])
    except yaml.YAMLError as exc:
        return LoadResult(None, [ValidationError("<file>", f"invalid YAML: {exc}")])
    return parse_manifest(raw)
