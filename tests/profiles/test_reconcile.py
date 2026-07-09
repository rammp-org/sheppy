from sheppy.manifest import Manifest, Node, Alternative
from sheppy.profiles import Profile
from sheppy.profiles.reconcile import reconcile


def _manifest():
    return Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="mock", kind="process", command="true", params={"fps": 15}),
            Alternative(id="real", kind="process", command="true"),
        ]),
    ])


def test_clean_profile_passes_through():
    p = Profile(name="p", selections={"camera": "mock"},
                overrides={"camera": {"fps": 30}})
    r = reconcile(p, _manifest())
    assert r.selections == {"camera": "mock"}
    assert r.overrides == {"camera": {"fps": 30}}
    assert r.warnings == []


def test_unknown_node_selection_dropped():
    p = Profile(name="p", selections={"ghost": "x"})
    r = reconcile(p, _manifest())
    assert r.selections == {}
    assert len(r.warnings) == 1


def test_unknown_alternative_dropped():
    p = Profile(name="p", selections={"camera": "nope"})
    r = reconcile(p, _manifest())
    assert r.selections == {}
    assert len(r.warnings) == 1


def test_override_on_unselected_node_dropped():
    p = Profile(name="p", selections={}, overrides={"camera": {"fps": 30}})
    r = reconcile(p, _manifest())
    assert r.overrides == {}
    assert len(r.warnings) == 1


def test_undeclared_override_key_dropped():
    # "real" declares no params, so fps is undeclared for it
    p = Profile(name="p", selections={"camera": "real"},
                overrides={"camera": {"fps": 30}})
    r = reconcile(p, _manifest())
    assert r.selections == {"camera": "real"}
    assert r.overrides == {}
    assert len(r.warnings) == 1
