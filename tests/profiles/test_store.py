from sheppy.profiles import Profile
from sheppy.profiles.store import ProfileStore
import pytest


def test_save_then_load_round_trip(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    p = Profile(name="all-mock",
                selections={"camera": "mock_camera"},
                overrides={"camera": {"fps": 30}},
                description="desk testing")
    store.save(p)
    res = store.load("all-mock")
    assert res.errors == []
    assert res.profile == p


def test_list_profiles_sorted_and_empty(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    assert store.list_profiles() == []          # dir does not exist yet
    store.save(Profile(name="zeta"))
    store.save(Profile(name="alpha"))
    assert store.list_profiles() == ["alpha", "zeta"]


def test_load_missing_file_returns_error(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    res = store.load("nope")
    assert res.profile is None
    assert len(res.errors) == 1


def test_load_bad_yaml_returns_error(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    (d / "broken.yaml").write_text("selections: [unclosed\n")
    store = ProfileStore(str(d))
    res = store.load("broken")
    assert res.profile is None
    assert len(res.errors) == 1


def test_save_rejects_bad_name(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    with pytest.raises(ValueError):
        store.save(Profile(name="bad name!"))


def test_delete_is_idempotent(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    store.save(Profile(name="temp"))
    store.delete("temp")
    store.delete("temp")           # second delete must not raise
    assert store.list_profiles() == []


def test_empty_profile_round_trips(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles"))
    store.save(Profile(name="empty"))
    res = store.load("empty")
    assert res.profile == Profile(name="empty")
