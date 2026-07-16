"""Flat-JSON daemon config and all sheppyd filesystem paths. stdlib only.

The config file is deliberately one flat object of plain-word keys
(user request: configs must be easy to understand). JSON, not YAML,
because the daemon has no YAML parser by design."""
import dataclasses
import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    home: str
    log_dir: str
    ring_lines: int = 300
    keep_runs: int = 5
    coredumps: bool = False
    usage_interval: float = 2.0
    launch_grace: float = 2.0
    stop_grace: float = 5.0
    kill_grace: float = 5.0


_TUNABLE = {f.name: f.type for f in dataclasses.fields(Config)
            if f.name not in ("home",)}


def sheppy_home() -> str:
    return os.environ.get("SHEPPY_HOME") or os.path.expanduser("~/.sheppy")


def load_config(home: "str | None" = None) -> "tuple[Config, list[str]]":
    home = home or sheppy_home()
    warnings: list[str] = []
    raw: dict = {}
    path = os.path.join(home, "sheppyd.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw = loaded
            else:
                warnings.append(f"{path}: expected a JSON object; using defaults")
        except (json.JSONDecodeError, OSError) as e:
            warnings.append(f"{path}: {e}; using defaults")
    kwargs: dict = {}
    for key, value in raw.items():
        if key not in _TUNABLE:
            warnings.append(f"{path}: unknown key '{key}' ignored")
            continue
        kwargs[key] = value
    log_dir = kwargs.pop("log_dir", None) or os.path.join(home, "logs")
    try:
        cfg = Config(home=home, log_dir=log_dir, **kwargs)
    except TypeError as e:
        warnings.append(f"{path}: {e}; using defaults")
        cfg = Config(home=home, log_dir=os.path.join(home, "logs"))
    return cfg, warnings


def socket_path(home: str) -> str:
    # SHEPPY_HOME pins everything under home (test isolation); otherwise
    # prefer XDG_RUNTIME_DIR (tmpfs, correct perms, cleared on logout).
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if not os.environ.get("SHEPPY_HOME") and xdg:
        return os.path.join(xdg, "sheppy", "sheppyd.sock")
    return os.path.join(home, "sheppyd.sock")


def state_path(home: str) -> str:
    return os.path.join(home, "sheppyd.state.json")


def lock_path(home: str) -> str:
    return os.path.join(home, "sheppyd.lock")


def daemon_log_path(cfg: Config) -> str:
    return os.path.join(cfg.log_dir, "sheppyd.log")
