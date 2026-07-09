from sheppy.manifest import Manifest, Node, Alternative
from sheppy.profiles import Profile, reconcile
from sheppy.profiles.state import ProfileState
import pytest


def _manifest():
    return Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="mock", kind="process", command="true", params={"fps": 15}),
            Alternative(id="real", kind="process", command="true"),
        ]),
    ])


def test_select_marks_dirty():
    st = ProfileState(_manifest())
    assert st.is_dirty is False
    st.select("camera", "mock")
    assert st.selected("camera") == "mock"
    assert st.is_dirty is True


def test_override_and_effective_params():
    st = ProfileState(_manifest())
    st.select("camera", "mock")
    st.override("camera", "fps", 30)
    assert st.effective_params("camera") == {"fps": 30}


def test_override_equal_to_default_is_dropped():
    st = ProfileState(_manifest())
    st.select("camera", "mock")
    st.override("camera", "fps", 30)
    st.override("camera", "fps", 15)          # back to the manifest default
    assert st.effective_params("camera") == {"fps": 15}
    assert st.to_profile("p").overrides == {}   # nothing stored


def test_override_undeclared_param_raises():
    st = ProfileState(_manifest())
    st.select("camera", "real")               # "real" declares no params
    with pytest.raises(KeyError):
        st.override("camera", "fps", 30)


def test_apply_sets_active_name_and_clears_dirty():
    st = ProfileState(_manifest())
    p = Profile(name="all-mock", selections={"camera": "mock"},
                overrides={"camera": {"fps": 30}})
    r = reconcile(p, _manifest())
    st.apply(r.selections, r.overrides, "all-mock")
    assert st.selected("camera") == "mock"
    assert st.effective_params("camera") == {"fps": 30}
    assert st.active_profile_name == "all-mock"
    assert st.is_dirty is False


def test_mutation_after_apply_sets_dirty():
    st = ProfileState(_manifest())
    st.apply({"camera": "mock"}, {}, "all-mock")
    assert st.is_dirty is False
    st.select("camera", "real")
    assert st.is_dirty is True


def test_to_profile_round_trips_through_reconcile():
    st = ProfileState(_manifest())
    st.select("camera", "mock")
    st.override("camera", "fps", 30)
    p = st.to_profile("snapshot")
    r = reconcile(p, _manifest())
    assert r.selections == {"camera": "mock"}
    assert r.overrides == {"camera": {"fps": 30}}


def test_mark_saved_clears_dirty():
    st = ProfileState(_manifest())
    st.select("camera", "mock")
    assert st.is_dirty is True
    st.mark_saved("all-mock")
    assert st.active_profile_name == "all-mock"
    assert st.is_dirty is False
