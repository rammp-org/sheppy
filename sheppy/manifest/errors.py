from dataclasses import dataclass, field
from sheppy.manifest.models import Manifest


@dataclass(frozen=True)
class ValidationError:
    location: str
    message: str


@dataclass(frozen=True)
class LoadResult:
    manifest: Manifest | None
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def errors_for(self, node, alt) -> list:
        """The load errors located at this alternative or at its node (#61,
        #170). The loader keeps every node and alternative, valid or not,
        at its manifest index, so `nodes[i].alternatives[j]` maps straight
        back. Errors at `nodes[i]` or `nodes[i].<field>` apply to every
        alternative of that node."""
        i = next(k for k, n in enumerate(self.manifest.nodes) if n is node)
        j = next(k for k, a in enumerate(node.alternatives) if a is alt)
        node_loc = f"nodes[{i}]"
        alt_loc = f"{node_loc}.alternatives[{j}]"
        other_alts = f"{node_loc}.alternatives["
        return [e for e in self.errors
                if e.location in (node_loc, alt_loc)
                or e.location.startswith(alt_loc + ".")
                or (e.location.startswith(node_loc + ".")
                    and not e.location.startswith(other_alts))]
