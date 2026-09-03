"""Translate a docker-compose service definition into docker-run arguments.
We reuse compose's config vocabulary but not its orchestrator."""
import difflib
import re
import shlex

import yaml

# Compose keys that docker run spells differently. Everything in _MECHANICAL
# below translates as --kebab-case with no entry here, so most compose keys
# — present and future — need no code at all.
_ALIAS = {
    "environment": "-e", "volumes": "-v", "ports": "-p", "user": "-u",
    "working_dir": "-w", "network_mode": "--network", "devices": "--device",
    "ulimits": "--ulimit", "sysctls": "--sysctl", "labels": "--label",
    "annotations": "--annotation",
    "device_cgroup_rules": "--device-cgroup-rule",
    "extra_hosts": "--add-host", "stdin_open": "--interactive",
    "userns_mode": "--userns", "cgroupns_mode": "--cgroupns",
    "dns_opt": "--dns-option", "mem_limit": "--memory",
    "mem_reservation": "--memory-reservation",
    "memswap_limit": "--memory-swap",
    "mem_swappiness": "--memory-swappiness",
    "cpuset": "--cpuset-cpus", "pull_policy": "--pull",
    "cgroup": "--cgroupns",
}

# Keys whose docker flag is exactly --kebab-case of the key.
_MECHANICAL = frozenset({
    "env_file", "ipc", "pid", "uts", "privileged", "cap_add", "cap_drop",
    "gpus", "entrypoint", "hostname", "domainname", "mac_address", "init",
    "read_only", "tty", "shm_size", "security_opt", "group_add", "tmpfs",
    "dns", "dns_search", "cgroup_parent", "runtime", "platform", "isolation",
    "expose", "volumes_from", "storage_opt", "pids_limit", "oom_kill_disable",
    "oom_score_adj", "cpus", "cpu_shares", "cpu_period", "cpu_quota",
    "cpu_rt_runtime", "cpu_rt_period", "cpu_count", "stop_signal",
    "label_file", "cpu_percent",
})

# Compose vocabulary sheppy deliberately does not act on, and why.
_NOT_APPLICABLE = {
    "restart": "sheppy owns lifecycle",
    "depends_on": "sheppy owns lifecycle",
    "healthcheck": "sheppy owns lifecycle",
    "stop_grace_period": "sheppy owns lifecycle",
    "build": "sheppy runs images, it does not build them",
    "container_name": "sheppy names containers sheppy-<node>",
    "scale": "sheppy runs one container per node",
    "profiles": "sheppy selects alternatives, not compose profiles",
    "networks": "sheppy does not manage container networks",
    "links": "sheppy does not manage container networks",
    "external_links": "sheppy does not manage container networks",
    "configs": "sheppy does not manage compose configs",
    "secrets": "sheppy does not manage compose secrets",
    "extends": "sheppy reads one service, not a compose inheritance tree",
    "develop": "sheppy does not run compose watch",
    "logging": "sheppy captures container logs",
    "attach": "sheppy captures container logs",
    "post_start": "sheppy owns lifecycle",
    "pre_stop": "sheppy owns lifecycle",
    "blkio_config": "sheppy does not translate compose's nested blkio_config",
}

# Handled by their own code below rather than by the generic translation.
_BESPOKE = frozenset({"image", "command", "deploy"})

_KNOWN = frozenset(_ALIAS) | _MECHANICAL | frozenset(_NOT_APPLICABLE) | _BESPOKE

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _interpolate(value, env):
    if isinstance(value, str):
        return _VAR.sub(lambda m: env.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _interpolate(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, env) for v in value]
    return value


def load_service(path: str, service: str, env: dict) -> dict:
    with open(path) as f:
        doc = yaml.safe_load(f) or {}
    services = doc.get("services") or {}
    if service not in services:
        raise KeyError(service)
    return _interpolate(dict(services[service] or {}), dict(env))


def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _volume_str(vol):
    if isinstance(vol, str):
        return vol
    src, tgt = vol.get("source", ""), vol.get("target", "")
    s = f"{src}:{tgt}"
    if vol.get("read_only"):
        s += ":ro"
    return s


def _command_list(cmd):
    if cmd is None:
        return []
    return list(cmd) if isinstance(cmd, (list, tuple)) else shlex.split(cmd)


def _ulimit_pair(name, limit):
    if isinstance(limit, dict):
        return f"{name}={limit.get('soft')}:{limit.get('hard')}"
    return f"{name}={limit}"


# How one entry of a mapping-valued key becomes a single flag argument.
_PAIR = {
    "ulimits": _ulimit_pair,
    "extra_hosts": lambda host, addr: f"{host}:{addr}",
}


def _check_environment(value, errors):
    if isinstance(value, (dict, list, tuple)):
        return value
    errors.append("'environment' must be a mapping or a list "
                  "of KEY=VALUE strings")
    return None


def _check_volumes(value, errors):
    out = []
    for vol in _as_list(value):
        try:
            out.append(_volume_str(vol))
        except AttributeError:
            errors.append(f"'volumes' entries must be a string or mapping, "
                          f"got {type(vol).__name__}")
    return out


def _check_ports(value, errors):
    out = []
    for port in _as_list(value):
        if isinstance(port, (str, int)):
            out.append(port)
        else:
            errors.append("compose long-form 'ports' is not supported; "
                          "use the 'host:container' short string form")
    return out


def _check_gpus(value, errors):
    if isinstance(value, (str, int)):
        return value
    errors.append("compose long-form 'gpus' is not supported; "
                  "use e.g. gpus: all")
    return None


def _check_entrypoint(value, errors):
    return value if isinstance(value, str) else " ".join(str(v) for v in value)


_CHECK = {
    "environment": _check_environment, "volumes": _check_volumes,
    "ports": _check_ports, "gpus": _check_gpus,
    "entrypoint": _check_entrypoint,
}


def _flag(key):
    return _ALIAS.get(key) or "--" + key.replace("_", "-")


def _emit(key, value):
    """One compose key/value pair as docker run flags. The value's YAML type
    decides the shape: bool is a bare flag, a mapping or list repeats."""
    flag = _flag(key)
    if isinstance(value, bool):
        return [flag] if value else []
    if isinstance(value, dict):
        pair = _PAIR.get(key, lambda k, v: f"{k}={v}")
        return [a for k, v in value.items() for a in (flag, pair(k, v))]
    if isinstance(value, (list, tuple)):
        return [a for item in value for a in (flag, str(item))]
    return [flag, str(value)]


def _unknown_key_error(key):
    near = difflib.get_close_matches(key, _KNOWN, n=1)
    hint = f"; did you mean '{near[0]}'?" if near else ""
    return f"sheppy does not translate compose key '{key}'{hint}"


def service_to_docker_args(service: dict):
    errors, warnings = [], []
    if not isinstance(service, dict):
        return [], "", [], [f"docker service definition must be a mapping, "
                            f"got {type(service).__name__}"], []
    deploy = service.get("deploy") or {}
    if int(deploy.get("replicas") or 1) > 1:
        errors.append("compose 'replicas > 1' is not supported by sheppy")
    image = service.get("image")
    if not image:
        errors.append("docker service needs an 'image' "
                      "(build-only services are unsupported)")

    flags = []
    for key, value in service.items():
        if key in _BESPOKE:
            continue
        if key in _NOT_APPLICABLE:
            warnings.append(f"compose '{key}' is ignored "
                            f"({_NOT_APPLICABLE[key]})")
            continue
        if key not in _KNOWN:
            errors.append(_unknown_key_error(key))
            continue
        if key in _CHECK:
            value = _CHECK[key](value, errors)
        if value is None:
            continue
        flags += _emit(key, value)

    return flags, image or "", _command_list(service.get("command")), errors, warnings
