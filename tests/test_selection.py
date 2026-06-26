import pytest
from sheppy.manifest import Manifest, Node, Alternative
from sheppy.selection import SelectionState


def _manifest():
    return Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="realsense", kind="process", command="true"),
            Alternative(id="mock", kind="process", command="true"),
        ]),
    ])


def test_starts_unselected():
    state = SelectionState(_manifest())
    assert state.selected("camera") is None


def test_select_is_single():
    state = SelectionState(_manifest())
    state.select("camera", "realsense")
    assert state.selected("camera") == "realsense"
    state.select("camera", "mock")  # replaces — single-select
    assert state.selected("camera") == "mock"


def test_clear():
    state = SelectionState(_manifest())
    state.select("camera", "mock")
    state.clear("camera")
    assert state.selected("camera") is None


def test_unknown_node_or_alt_raises():
    state = SelectionState(_manifest())
    with pytest.raises(KeyError):
        state.select("ghost", "mock")
    with pytest.raises(KeyError):
        state.select("camera", "ghost")
    with pytest.raises(KeyError):
        state.clear("ghost")


def test_change_listener_fires():
    state = SelectionState(_manifest())
    events = []
    state.on_change(lambda node, alt: events.append((node, alt)))
    state.select("camera", "mock")
    state.clear("camera")
    assert events == [("camera", "mock"), ("camera", None)]
