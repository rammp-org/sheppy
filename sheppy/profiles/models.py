from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    name: str
    selections: dict[str, str] = field(default_factory=dict)
    overrides: dict[str, dict[str, object]] = field(default_factory=dict)
    description: str = ""
