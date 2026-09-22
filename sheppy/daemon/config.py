"""Flat-JSON daemon config and all sheppyd filesystem paths. stdlib only.

The config file is deliberately one flat object of plain-word keys
(user request: configs must be easy to understand). JSON, not YAML,
because the daemon has no YAML parser by design."""
import dataclasses
import json
import os
import time
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
        typ = _TUNABLE[key]
        if typ is float and type(value) is int:
            value = float(value)           # 5 is a fine float
        # bool is an int subclass; a JSON true is still not a count (#91).
        if not isinstance(value, typ) or (typ is int and type(value) is bool):
            warnings.append(f"{path}: '{key}' expects {typ.__name__}, "
                            f"got {value!r}; using the default")
            continue
        kwargs[key] = value
    log_dir = os.path.expanduser(
        kwargs.pop("log_dir", None) or os.path.join(home, "logs"))
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


# sun_path holds 108 bytes on Linux, including the terminating NUL.
MAX_SOCKET_PATH = 107


def socket_path_error(home: str) -> "str | None":
    """Why the daemon socket can't be bound here, or None. Binding an
    over-long path fails before sheppyd can log anything (#35)."""
    path = socket_path(home)
    size = len(os.fsencode(path))
    if size <= MAX_SOCKET_PATH:
        return None
    return (f"socket path is {size} bytes, over the {MAX_SOCKET_PATH}-byte "
            f"limit for unix sockets: {path} (use a shorter SHEPPY_HOME)")


def state_path(home: str) -> str:
    return os.path.join(home, "sheppyd.state.json")


def lock_path(home: str) -> str:
    return os.path.join(home, "sheppyd.lock")


def daemon_log_path(cfg: Config) -> str:
    return os.path.join(cfg.log_dir, "sheppyd.log")


def daemon_log(cfg: Config, text: str) -> None:
    """Append one timestamped line to sheppyd.log. A logging failure (disk
    full, unwritable log dir) must never take supervision down with it."""
    try:
        os.makedirs(cfg.log_dir, exist_ok=True)
        # backslashreplace: a lone surrogate (a non-UTF-8 byte in a path,
        # carried in an OSError's filename) must not make the log line raise.
        with open(daemon_log_path(cfg), "a", errors="backslashreplace") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
    except OSError:
        pass
