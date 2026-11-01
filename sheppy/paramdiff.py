"""Param values and per-key param changes as text, shared by the CLI and
the TUI."""
import json

_MISSING = object()


def fmt(value) -> str:
    """A param value as it reads in YAML flow style: true, 3, "base"."""
    return json.dumps(value, default=str, ensure_ascii=False)


def changes(old: dict, new: dict) -> list:
    """`key: old → new` for each key whose value differs; a key on only one
    side shows — on the other."""
    out = []
    for k in sorted(old.keys() | new.keys()):
        a, b = old.get(k, _MISSING), new.get(k, _MISSING)
        if a is _MISSING or b is _MISSING or a != b:
            out.append(f"{k}: {_side(a)} → {_side(b)}")
    return out


def _side(value) -> str:
    return "—" if value is _MISSING else fmt(value)
