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
