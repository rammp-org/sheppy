import pytest
from sheppy.launch.descriptor import LaunchDescriptor as LD


def test_inherit_roundtrips_and_validates():
    d = LD.inherit(("bash", "-c", "echo hi"))
    assert d.supervise == "inherit" and d.start == ("bash", "-c", "echo hi")
    assert d.validate() == []
    assert d.to_wire() == {"supervise": "inherit",
                           "start": ["bash", "-c", "echo hi"]}
    assert LD.from_wire(d.to_wire()) == d


def test_detached_with_watch_roundtrips():
    d = LD.detached("sheppy-cam",
                    start=("docker", "run", "-d", "--name", "sheppy-cam", "img"),
                    watch=("docker", "wait", "sheppy-cam"),
                    stop=("docker", "stop", "sheppy-cam"),
                    logs=("docker", "logs", "-f", "sheppy-cam"))
    assert d.validate() == []
    assert LD.from_wire(d.to_wire()) == d
    assert d.to_wire()["name"] == "sheppy-cam"


def test_detached_requires_name_and_exit_detection():
    no_name = LD.detached("", start=("x",), watch=("w",))
    assert any("name" in e for e in no_name.validate())
    neither = LD.detached("n", start=("x",))
    assert any("watch" in e and "poll" in e for e in neither.validate())
    both = LD.detached("n", start=("x",), watch=("w",), poll=("p",))
    assert any("watch" in e and "poll" in e for e in both.validate())
    poll_ok = LD.detached("n", start=("x",), poll=("p",))
    assert poll_ok.validate() == []


def test_start_required_and_supervise_valid():
    assert any("start" in e for e in LD.inherit(()).validate())
    bad = LD(supervise="weird", start=("x",))
    assert any("supervise" in e for e in bad.validate())


def test_from_wire_tolerates_lists_and_missing_optionals():
    wire = {"supervise": "detached", "name": "n",
            "start": ["a", "b"], "poll": ["p"]}
    d = LD.from_wire(wire)
    assert d.start == ("a", "b") and d.poll == ("p",) and d.watch is None
