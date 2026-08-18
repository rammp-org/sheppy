"""Translate a docker-compose service definition into docker-run arguments.
We reuse compose's config vocabulary but not its orchestrator."""
import shlex

_WARN_KEYS = ("restart", "depends_on", "healthcheck")


def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _env_pairs(env):
    if not env:
        return []
    if isinstance(env, dict):
        return [(str(k), str(v)) for k, v in env.items()]
    out = []
    for item in env:
        k, _, v = str(item).partition("=")
        out.append((k, v))
    return out


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


def service_to_docker_args(service: dict):
    errors, warnings = [], []
    deploy = service.get("deploy") or {}
    if int(deploy.get("replicas") or 1) > 1:
        errors.append("compose 'replicas > 1' is not supported by sheppy")
    image = service.get("image")
    if not image:
        errors.append("docker service needs an 'image' "
                      "(build-only services are unsupported)")
    for key in _WARN_KEYS:
        if key in service:
            warnings.append(f"compose '{key}' is ignored (sheppy owns lifecycle)")

    flags = []
    for k, v in _env_pairs(service.get("environment")):
        flags += ["-e", f"{k}={v}"]
    for ef in _as_list(service.get("env_file")):
        flags += ["--env-file", str(ef)]
    if service.get("network_mode"):
        flags += ["--network", str(service["network_mode"])]
    if service.get("ipc"):
        flags += ["--ipc", str(service["ipc"])]
    if service.get("pid"):
        flags += ["--pid", str(service["pid"])]
    for vol in _as_list(service.get("volumes")):
        flags += ["-v", _volume_str(vol)]
    for dev in _as_list(service.get("devices")):
        flags += ["--device", str(dev)]
    if service.get("privileged"):
        flags += ["--privileged"]
    for cap in _as_list(service.get("cap_add")):
        flags += ["--cap-add", str(cap)]
    for cap in _as_list(service.get("cap_drop")):
        flags += ["--cap-drop", str(cap)]
    for port in _as_list(service.get("ports")):
        if not isinstance(port, (str, int)):
            errors.append("compose long-form 'ports' is not supported; "
                          "use the 'host:container' short string form")
            continue
        flags += ["-p", str(port)]
    if service.get("user"):
        flags += ["-u", str(service["user"])]
    if service.get("working_dir"):
        flags += ["-w", str(service["working_dir"])]
    if service.get("entrypoint"):
        ep = service["entrypoint"]
        flags += ["--entrypoint", ep if isinstance(ep, str) else " ".join(ep)]
    gpus = service.get("gpus")
    if gpus is not None:
        if not isinstance(gpus, (str, int)):
            errors.append("compose long-form 'gpus' is not supported; "
                          "use e.g. gpus: all")
        else:
            flags += ["--gpus", str(gpus)]

    return flags, image or "", _command_list(service.get("command")), errors, warnings
