import datetime
import json
import shlex

import pytest
import yaml

from sheppy.launch.builtins import (
    ProcessLauncher, ExecutableLauncher, LaunchFileLauncher, _param_token,
    param_text)
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


@pytest.mark.parametrize("value", [
    None, "007", [1, "two", 3.0], True, False, 30, 1.5, "it's on it", "yes",
    "", "a\nb", "café", "1e3", "inf", ["08", "09"], ["1e3", "x"],
    datetime.date(2024, 1, 1)])
def test_param_token_is_one_shell_word_holding_the_yaml_value(value):
    # #70: ROS parses the value after := as YAML (None, not "None"; "007", not
    # 7). rcl types plain scalars by its own rules (08 and 1e3 are doubles), so
    # every string, nested or not, must be quoted.
    (word,) = shlex.split(_param_token("k", param_text(value)))
    name, _, text = word.partition(":=")
    assert name == "k"
    # YAML loads 2024-01-01 as a date; it goes out as the text "2024-01-01".
    expected = str(value) if isinstance(value, datetime.date) else value
    assert yaml.safe_load(text) == expected
    assert "\n" not in text
    strings = expected if isinstance(expected, list) else [expected]
    for s in strings:
        if isinstance(s, str):
            assert json.dumps(s, ensure_ascii=False) in text


ARGS = {"name": "007", "word": "on it", "nothing": None, "flag": True,
        "gain": 1.5, "ids": ["08", "09"]}


def test_executable_params_are_json(tmp_path):
    desc = ExecutableLauncher().launch(
        Alternative(id="a", kind="executable", package="p", executable="e"),
        ARGS, ctx(tmp_path))
    assert shlex.split(cmd(desc))[6:] == [
        "-p", 'name:="007"', "-p", 'word:="on it"', "-p", "nothing:=null",
        "-p", "flag:=true", "-p", "gain:=1.5", "-p", 'ids:=["08", "09"]']


def test_launch_file_strings_verbatim_other_values_json(tmp_path):
    # ros2 launch takes launch arguments as raw text (quotes would reach the
    # launch file), so strings go through as written.
    desc = LaunchFileLauncher().launch(
        Alternative(id="a", kind="launch_file", package="p", launch_file="f"),
        {**ARGS, "m": {"b": 1}}, ctx(tmp_path))
    assert shlex.split(cmd(desc))[5:] == [
        "name:=007", "word:=on it", "nothing:=null", "flag:=true",
        "gain:=1.5", 'ids:=["08", "09"]', 'm:={"b": 1}']
