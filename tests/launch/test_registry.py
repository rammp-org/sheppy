import pytest
from sheppy.launch.registry import LauncherRegistry, UnknownKind


class FakeLauncher:
    def __init__(self, kind):
        self.kind = kind
    def validate(self, raw_alt): return []
    def launch(self, alt, params, ctx): return None
    def summary(self, alt): return []


def test_register_and_get():
    reg = LauncherRegistry([FakeLauncher("process"), FakeLauncher("docker")])
    assert reg.get("docker").kind == "docker"
    assert reg.kinds() == ["docker", "process"]


def test_unknown_kind_lists_known():
    reg = LauncherRegistry([FakeLauncher("process")])
    with pytest.raises(UnknownKind) as ei:
        reg.get("nope")
    assert "nope" in str(ei.value) and "process" in str(ei.value)


def test_discover_loads_entry_points(monkeypatch):
    class _EP:
        name = "docker"
        def load(self): return lambda: FakeLauncher("docker")
    monkeypatch.setattr("sheppy.launch.registry.entry_points",
                        lambda group: [_EP()])
    reg = LauncherRegistry.discover()
    assert reg.get("docker").kind == "docker"


def test_discover_skips_a_broken_entry_point(monkeypatch):
    class _Good:
        def load(self): return lambda: FakeLauncher("process")
    class _Bad:
        def load(self): raise ImportError("boom")
    monkeypatch.setattr("sheppy.launch.registry.entry_points",
                        lambda group: [_Bad(), _Good()])
    reg = LauncherRegistry.discover()
    assert reg.kinds() == ["process"]           # bad one skipped, not fatal


def test_discover_warns_on_broken_entry_point(monkeypatch, capsys):
    class _Bad:
        name = "boomplugin"
        def load(self): raise ImportError("boom")
    monkeypatch.setattr("sheppy.launch.registry.entry_points",
                        lambda group: [_Bad()])
    LauncherRegistry.discover()
    err = capsys.readouterr().err
    assert "boomplugin" in err and "boom" in err
