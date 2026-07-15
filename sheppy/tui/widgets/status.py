"""Status vocabulary — the single source of truth for status glyphs and
their colors. NONE/SELECTED are used in phase 2a.5; RUNNING/LAUNCHING/
CRASHED/WARN are reserved for phase 2b (runtime process state) and defined
now so later phases extend a table rather than restructure the UI."""
from enum import Enum


class Status(Enum):
    NONE = "none"
    SELECTED = "selected"
    RUNNING = "running"        # reserved — phase 2b
    LAUNCHING = "launching"    # reserved — phase 2b
    CRASHED = "crashed"        # reserved — phase 2b
    WARN = "warn"              # reserved — phase 2b


_GLYPH = {
    Status.NONE: "○",
    Status.SELECTED: "◆",
    Status.RUNNING: "●",
    Status.LAUNCHING: "◐",
    Status.CRASHED: "✕",
    Status.WARN: "⚠",
}

_COLOR = {
    Status.NONE: "muted",
    Status.SELECTED: "green",
    Status.RUNNING: "green",
    Status.LAUNCHING: "yellow",
    Status.CRASHED: "red",
    Status.WARN: "yellow",
}


def glyph(status: Status) -> str:
    return _GLYPH[status]


def color_key(status: Status) -> str:
    return _COLOR[status]
