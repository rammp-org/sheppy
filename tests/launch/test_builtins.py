from sheppy.launch.builtins import (
    ProcessLauncher, ExecutableLauncher, LaunchFileLauncher)
from sheppy.launch.base import LaunchContext
from sheppy.manifest import Alternative, Machine, Manifest

ROBOT = Machine(name="robot", host="h", user="u",
                ros_setup="/opt/ros/humble/setup.bash")


def ctx(tmp_path, manifest=None):
    return LaunchContext("n", manifest or Manifest(machines=[], nodes=[]),
                         home=str(tmp_path))


def cmd(desc):
    assert desc.supervise == "inherit"
    assert desc.start[:2] == ("bash", "-c")
    return desc.start[2]


def test_executable_matches_legacy_command(tmp_path):
    alt = Alternative(id="real", kind="executable", machine="robot",
                      package="cam_pkg", executable="cam_node")
    c = ctx(tmp_path, Manifest(machines=[ROBOT], nodes=[]))
    desc = ExecutableLauncher().launch(alt, {"fps": 30}, c)
    text = cmd(desc)
    assert text.startswith("source /opt/ros/humble/setup.bash && ")
    assert "exec ros2 run cam_pkg cam_node --ros-args -p 'fps:=30'" in text
    assert c.warnings == []


def test_launch_file_matches_legacy(tmp_path):
    alt = Alternative(id="rs", kind="launch_file", package="p",
                      launch_file="rs.py")
    desc = LaunchFileLauncher().launch(alt, {"depth": "on it"}, ctx(tmp_path))
    assert "exec ros2 launch p rs.py 'depth:=on it'" in cmd(desc)


def test_process_verbatim_and_warns(tmp_path):
    alt = Alternative(id="gui", kind="process", command="rviz2 | tee /tmp/l")
    c = ctx(tmp_path)
    desc = ProcessLauncher().launch(alt, {"x": 1}, c)
    assert cmd(desc) == "rviz2 | tee /tmp/l"
    assert any("ignored" in w for w in c.warnings)


def test_injection_still_escaped(tmp_path):
    alt = Alternative(id="x", kind="executable", package="p", executable="e")
    desc = ExecutableLauncher().launch(
        alt, {"msg": "x'; touch /tmp/PWNED; echo '"}, ctx(tmp_path))
    import shlex
    tokens = shlex.split(cmd(desc))
    assert "touch" not in tokens                # trapped inside one quoted token


def test_ros_setup_expands_home(tmp_path, monkeypatch):
    # A quoted '~' is never expanded by bash, so sheppy must do it (#32).
    monkeypatch.setenv("HOME", "/home/me")
    ws = Machine(name="ws", host="h", user="u", ros_setup="~/ws/install/setup.bash")
    alt = Alternative(id="a", kind="executable", machine="ws",
                      package="p", executable="e")
    c = ctx(tmp_path, Manifest(machines=[ws], nodes=[]))
    text = cmd(ExecutableLauncher().launch(alt, {}, c))
    assert text.startswith("source /home/me/ws/install/setup.bash && ")


def test_relative_ros_setup_resolves_against_manifest_dir(tmp_path):
    # The command runs in sheppyd, whose cwd is wherever it was first
    # spawned, so a relative path must be made absolute here (#68).
    ws = Machine(name="ws", host="h", user="u", ros_setup="install/setup.bash")
    alt = Alternative(id="a", kind="process", machine="ws", command="true")
    c = LaunchContext("n", Manifest(machines=[ws], nodes=[]),
                      home=str(tmp_path), manifest_dir="/proj/ws")
    text = cmd(ProcessLauncher().launch(alt, {}, c))
    assert text.startswith("source /proj/ws/install/setup.bash && ")


def test_relative_ros_setup_with_default_manifest_dir_uses_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ws = Machine(name="ws", host="h", user="u", ros_setup="install/setup.bash")
    alt = Alternative(id="a", kind="process", machine="ws", command="true")
    text = cmd(ProcessLauncher().launch(alt, {}, ctx(tmp_path, Manifest(machines=[ws], nodes=[]))))
    assert text.startswith(f"source {tmp_path}/install/setup.bash && ")
