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
        """The load errors located at this alternative (#61). The loader
        keeps every node and alternative, valid or not, at its manifest
        index, so `nodes[i].alternatives[j]` maps straight back."""
        i = next(k for k, n in enumerate(self.manifest.nodes) if n is node)
        j = next(k for k, a in enumerate(node.alternatives) if a is alt)
        loc = f"nodes[{i}].alternatives[{j}]"
        return [e for e in self.errors
                if e.location == loc or e.location.startswith(loc + ".")]
