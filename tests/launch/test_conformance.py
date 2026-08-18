from sheppy.launch.registry import default_registry


def test_every_registered_launcher_meets_the_contract():
    reg = default_registry()
    assert reg.kinds()                         # discovery found the built-ins
    for kind in reg.kinds():
        launcher = reg.get(kind)
        assert launcher.kind == kind
        assert isinstance(launcher.validate({}), list)      # never raises
        assert callable(launcher.launch) and callable(launcher.summary)
