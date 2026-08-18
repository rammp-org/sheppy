from sheppy.launch.descriptor import LaunchDescriptor
from sheppy.launch.resolve import LaunchSpec, diff, resolve
from sheppy.manifest import Alternative, Machine, Manifest, Node


def manifest(machines=(), nodes=()):
    return Manifest(machines=list(machines), nodes=list(nodes))


ROBOT = Machine(name="robot", host="10.0.0.2", user="ros",
                ros_setup="/opt/ros/humble/setup.bash")


def cmd(spec):
    assert spec.argv[0] == "bash" and spec.argv[1] == "-c"
    return spec.argv[2]


def test_executable_kind_with_params_and_setup():
    alt = Alternative(id="real", kind="executable", machine="robot",
                      package="cam_pkg", executable="cam_node")
    spec, warnings = resolve(manifest([ROBOT]), "camera", alt,
                             {"fps": 30, "pointcloud.enable": True})
    assert warnings == []
    text = cmd(spec)
    assert text.startswith("source /opt/ros/humble/setup.bash && ")
    assert "exec ros2 run cam_pkg cam_node --ros-args" in text
    assert "-p 'fps:=30'" in text and "-p 'pointcloud.enable:=true'" in text
    assert spec.to_wire() == {"node": "camera", "alt_id": "real",
                              "argv": list(spec.argv),
                              "params": {"fps": 30,
                                         "pointcloud.enable": True}}


def test_launch_file_kind_arguments():
    alt = Alternative(id="rs", kind="launch_file", package="realsense2_camera",
                      launch_file="rs_launch.py")
    spec, _ = resolve(manifest(), "camera", alt, {"depth": "on it"})
    text = cmd(spec)
    assert "exec ros2 launch realsense2_camera rs_launch.py" in text
    assert "'depth:=on it'" in text          # value with a space is quoted
    assert "source" not in text              # no machine ⇒ no setup prefix


def test_process_kind_verbatim_and_params_warn():
    alt = Alternative(id="gui", kind="process",
                      command="rviz2 -d cfg.rviz | tee /tmp/log")
    spec, warnings = resolve(manifest(), "viz", alt, {"x": 1})
    assert cmd(spec) == "rviz2 -d cfg.rviz | tee /tmp/log"   # no exec, no -p
    assert any("ignored" in w for w in warnings)


def test_quoting_hostile_names():
    alt = Alternative(id="odd", kind="executable",
                      package="pkg; rm -rf /", executable="exe")
    spec, _ = resolve(manifest(), "n", alt, {})
    assert "'pkg; rm -rf /'" in cmd(spec)


def test_param_value_with_single_quote_is_escaped():
    alt = Alternative(id="x", kind="executable", package="p", executable="e")
    spec, _ = resolve(manifest(), "n", alt,
                      {"msg": "x'; touch /tmp/PWNED; echo '"})
    text = cmd(spec)
    assert "touch /tmp/PWNED" in text          # present only as data...
    # ...never as an executable token: the injected bytes stay inside quotes
    assert "'\\''" in text                      # POSIX escape sequence emitted
    # the injected ';' must not create new shell tokens: the whole command
    # still parses to exactly [exec, ros2, run, p, e, --ros-args, -p, k:=v]
    import shlex as _shlex
    tokens = _shlex.split(text)
    assert tokens == ["exec", "ros2", "run", "p", "e", "--ros-args", "-p",
                      "msg:=x'; touch /tmp/PWNED; echo '"]


def test_launch_file_param_with_single_quote_is_escaped():
    alt = Alternative(id="rs", kind="launch_file", package="pkg",
                      launch_file="f.py")
    spec, _ = resolve(manifest(), "n", alt, {"k": "a'b"})
    # whole k:=v token is single-quoted, embedded ' escaped as '\'' :
    assert "'k:=a'\\''b'" in cmd(spec)


def make_spec(node, alt="a", argv=("bash", "-c", "x")):
    return LaunchSpec(node=node, alt_id=alt,
                      descriptor=LaunchDescriptor.inherit(argv), params={})


def actual(node, state, argv=("bash", "-c", "x")):
    return {"node": node, "state": state,
            "spec": {"node": node, "alt_id": "a", "argv": list(argv),
                     "params": {}}}


def test_diff_truth_table():
    desired = {"a": make_spec("a"), "b": make_spec("b"),
               "c": make_spec("c", argv=("bash", "-c", "new"))}
    live = {"b": actual("b", "running"),                  # matches → untouched
            "c": actual("c", "running"),                  # differs → restart
            "d": actual("d", "running"),                  # undesired → stop
            "e": actual("e", "crashed")}                  # dead, undesired → nothing
    actions = diff(desired, live)
    assert actions == [("stop", "d"), ("restart", "c"), ("start", "a")]


def test_diff_crashed_desired_node_restarts_via_start():
    desired = {"a": make_spec("a")}
    assert diff(desired, {"a": actual("a", "crashed")}) == [("start", "a")]


def test_diff_empty_when_converged():
    desired = {"a": make_spec("a")}
    assert diff(desired, {"a": actual("a", "running")}) == []


def test_resolve_still_emits_argv_wire(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    from sheppy.launch import resolve
    from sheppy.manifest import Alternative, Manifest
    alt = Alternative(id="a", kind="executable", package="p", executable="e")
    spec, warns = resolve(Manifest(machines=[], nodes=[]), "n", alt, {})
    wire = spec.to_wire()
    assert wire["argv"][0] == "bash" and "ros2 run p e" in wire["argv"][2]
    assert "descriptor" not in wire            # still argv-shaped in Task 4
