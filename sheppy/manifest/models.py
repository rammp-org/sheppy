from dataclasses import dataclass, field


@dataclass(frozen=True)
class Machine:
    name: str
    host: str
    user: str
    ros_setup: str | None = None


@dataclass(frozen=True)
class Alternative:
    id: str
    kind: str  # "executable" | "launch_file" | "process"
    machine: str | None = None
    package: str | None = None
    executable: str | None = None
    launch_file: str | None = None
    command: str | None = None
    params: dict = field(default_factory=dict)
    publishes: list[str] = field(default_factory=list)
    subscribes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Node:
    name: str
    alternatives: list[Alternative]
    description: str = ""
    select: str = "single"


@dataclass(frozen=True)
class Manifest:
    machines: list[Machine]
    nodes: list[Node]

    def node(self, name: str) -> "Node | None":
        for n in self.nodes:
            if n.name == name:
                return n
        return None
