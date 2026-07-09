import os
import re
from dataclasses import dataclass

import yaml

from sheppy.profiles.models import Profile

NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class ProfileLoadResult:
    profile: "Profile | None"
    errors: list


class ProfileStore:
    def __init__(self, profiles_dir: str) -> None:
        self._dir = profiles_dir

    def _path(self, name: str) -> str:
        return os.path.join(self._dir, f"{name}.yaml")

    def list_profiles(self) -> list:
        if not os.path.isdir(self._dir):
            return []
        stems = [fn[:-5] for fn in os.listdir(self._dir) if fn.endswith(".yaml")]
        return sorted(stems)

    def load(self, name: str) -> ProfileLoadResult:
        path = self._path(name)
        if not os.path.isfile(path):
            return ProfileLoadResult(None, [f"profile not found: {name}"])
        try:
            with open(path) as f:
                raw = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return ProfileLoadResult(None, [f"invalid YAML in profile '{name}': {e}"])
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            return ProfileLoadResult(None, [f"profile '{name}' is not a mapping"])
        errors: list = []
        selections = raw.get("selections") or {}
        overrides = raw.get("overrides") or {}
        description = raw.get("description") or ""
        if not isinstance(selections, dict):
            errors.append(f"profile '{name}': 'selections' is not a mapping; ignored")
            selections = {}
        if not isinstance(overrides, dict):
            errors.append(f"profile '{name}': 'overrides' is not a mapping; ignored")
            overrides = {}
        profile = Profile(
            name=name,
            selections=dict(selections),
            overrides={k: dict(v) for k, v in overrides.items() if isinstance(v, dict)},
            description=str(description),
        )
        return ProfileLoadResult(profile, errors)

    def save(self, profile: Profile) -> None:
        if not NAME_RE.match(profile.name):
            raise ValueError(f"invalid profile name: {profile.name!r}")
        os.makedirs(self._dir, exist_ok=True)
        data: dict = {}
        if profile.description:
            data["description"] = profile.description
        if profile.selections:
            data["selections"] = dict(profile.selections)
        if profile.overrides:
            data["overrides"] = {k: dict(v) for k, v in profile.overrides.items()}
        with open(self._path(profile.name), "w") as f:
            yaml.safe_dump(data, f, sort_keys=True, default_flow_style=False)

    def delete(self, name: str) -> None:
        try:
            os.remove(self._path(name))
        except FileNotFoundError:
            pass
