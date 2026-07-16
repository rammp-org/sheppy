"""Status vocabulary — the single source of truth for status glyphs and
their colors. NONE/SELECTED are used in phase 2a.5; RUNNING/LAUNCHING/
STOPPING/CRASHED/WARN/UNKNOWN carry phase 2b runtime process state, reported
by the daemon and mapped through runtime()."""
from enum import Enum


class Status(Enum):
    NONE = "none"          # no runtime state (stopped / not supervised)
    SELECTED = "selected"  # 2a-era: kept for AlternativesPanel radio rows
    RUNNING = "running"
    LAUNCHING = "launching"
    STOPPING = "stopping"
    CRASHED = "crashed"
    WARN = "warn"
    UNKNOWN = "unknown"    # daemon absent — NOT the same as stopped


_GLYPH = {
    Status.NONE: "○",
    Status.SELECTED: "◆",
    Status.RUNNING: "●",
    Status.LAUNCHING: "◐",
    Status.STOPPING: "◐",
    Status.CRASHED: "✕",
    Status.WARN: "⚠",
    Status.UNKNOWN: "?",
}

_COLOR = {
    Status.NONE: "muted",
    Status.SELECTED: "green",
    Status.RUNNING: "green",
    Status.LAUNCHING: "yellow",
    Status.STOPPING: "yellow",
    Status.CRASHED: "red",
    Status.WARN: "yellow",
    Status.UNKNOWN: "muted",
}

_RUNTIME = {"running": Status.RUNNING, "launching": Status.LAUNCHING,
            "stopping": Status.STOPPING, "crashed": Status.CRASHED,
            "stopped": Status.NONE}


def glyph(status: Status) -> str:
    return _GLYPH[status]


def color_key(status: Status) -> str:
    return _COLOR[status]


def runtime(state: "str | None") -> Status:
    if state is None:
        return Status.NONE
    return _RUNTIME.get(state, Status.WARN)
