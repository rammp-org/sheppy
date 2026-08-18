"""Discover launcher plugins via entry points (group 'sheppy.launchers').
Built-ins and third-party launchers register identically."""
from importlib.metadata import entry_points


class UnknownKind(Exception):
    pass


class LauncherRegistry:
    def __init__(self, launchers=None):
        self._by_kind = {}
        for launcher in (launchers or []):
            self.register(launcher)

    def register(self, launcher) -> None:
        self._by_kind[launcher.kind] = launcher

    def get(self, kind: str):
        try:
            return self._by_kind[kind]
        except KeyError:
            known = ", ".join(self.kinds()) or "(none)"
            raise UnknownKind(
                f"no launcher registered for kind {kind!r}; known: {known}")

    def kinds(self) -> list:
        return sorted(self._by_kind)

    @classmethod
    def discover(cls) -> "LauncherRegistry":
        reg = cls()
        for ep in entry_points(group="sheppy.launchers"):
            try:
                reg.register(ep.load()())
            except Exception:
                continue                        # a broken plugin never breaks discovery
        return reg


_DEFAULT = None


def default_registry() -> "LauncherRegistry":
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = LauncherRegistry.discover()
    return _DEFAULT
