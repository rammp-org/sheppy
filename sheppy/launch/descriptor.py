"""The one client<->daemon contract: how to start, watch, stop, and read
logs for a supervised unit. Pure, JSON-serializable data."""
from dataclasses import dataclass, field

INHERIT = "inherit"
DETACHED = "detached"
_CMD_FIELDS = ("start", "watch", "poll", "stop", "logs", "stats", "reset")


def _t(v):
    return tuple(v) if v else None


@dataclass(frozen=True)
class LaunchDescriptor:
    supervise: str
    start: tuple
    name: "str | None" = None
    watch: "tuple | None" = None
    poll: "tuple | None" = None
    stop: "tuple | None" = None
    logs: "tuple | None" = None
    stats: "tuple | None" = None
    reset: "tuple | None" = None
    grace: dict = field(default_factory=dict)

    @classmethod
    def inherit(cls, start) -> "LaunchDescriptor":
        return cls(supervise=INHERIT, start=tuple(start))

    @classmethod
    def detached(cls, name, start, *, watch=None, poll=None, stop=None,
                 logs=None, stats=None, reset=None, grace=None):
        return cls(supervise=DETACHED, name=name or None, start=tuple(start),
                   watch=_t(watch), poll=_t(poll), stop=_t(stop),
                   logs=_t(logs), stats=_t(stats), reset=_t(reset),
                   grace=dict(grace or {}))

    def validate(self) -> list:
        errs = []
        if self.supervise not in (INHERIT, DETACHED):
            errs.append(f"supervise must be {INHERIT!r} or {DETACHED!r}, "
                        f"got {self.supervise!r}")
        if not self.start:
            errs.append("descriptor needs a non-empty 'start'")
        if self.supervise == DETACHED:
            if not self.name:
                errs.append("detached descriptor needs a 'name'")
            if bool(self.watch) == bool(self.poll):
                errs.append("detached descriptor needs exactly one of "
                            "'watch' or 'poll'")
        return errs

    def to_wire(self) -> dict:
        out = {"supervise": self.supervise, "start": list(self.start)}
        if self.name:
            out["name"] = self.name
        for f in _CMD_FIELDS:
            if f == "start":
                continue
            v = getattr(self, f)
            if v:
                out[f] = list(v)
        if self.grace:
            out["grace"] = dict(self.grace)
        return out

    @classmethod
    def from_wire(cls, d: dict) -> "LaunchDescriptor":
        return cls(
            supervise=d.get("supervise", ""), start=tuple(d.get("start") or ()),
            name=d.get("name"), watch=_t(d.get("watch")), poll=_t(d.get("poll")),
            stop=_t(d.get("stop")), logs=_t(d.get("logs")),
            stats=_t(d.get("stats")), reset=_t(d.get("reset")),
            grace=dict(d.get("grace") or {}))
