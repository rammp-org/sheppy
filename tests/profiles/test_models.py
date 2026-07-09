from sheppy.profiles import Profile


def test_profile_defaults_are_independent():
    a = Profile(name="a")
    b = Profile(name="b")
    a.selections["camera"] = "mock"
    assert b.selections == {}          # mutable defaults must not be shared


def test_profile_holds_fields():
    p = Profile(
        name="all-mock",
        selections={"camera": "mock_camera"},
        overrides={"camera": {"fps": 30}},
        description="desk testing",
    )
    assert p.name == "all-mock"
    assert p.selections["camera"] == "mock_camera"
    assert p.overrides["camera"]["fps"] == 30
    assert p.description == "desk testing"
