import yaml
from sheppy.launch.docker import DockerLauncher
from sheppy.launch.base import LaunchContext
from sheppy.manifest import Alternative, Manifest


def ctx(tmp_path):
    return LaunchContext("perception", Manifest(machines=[], nodes=[]),
                         home=str(tmp_path), manifest_dir=str(tmp_path))


def test_params_are_written_mounted_and_referenced(tmp_path):
    a = Alternative(id="real", kind="docker",
                    config={"container": {"image": "img",
                                          "command": "ros2 launch p up.py"}})
    d = DockerLauncher().launch(a, {"max_range": 5.0}, ctx(tmp_path))
    start = list(d.start)
    # a read-only mount of the host params file at the fixed container path
    mount = next(s for s in start if s.endswith(":/sheppy/params.yaml:ro"))
    host_path = mount.split(":")[0]
    assert yaml.safe_load(open(host_path)) == {
        "/**": {"ros__parameters": {"max_range": 5.0}}}
    # command carries the --params-file arg
    tail = start[start.index("img") + 1:]
    assert tail[-3:] == ["--ros-args", "--params-file", "/sheppy/params.yaml"]


def test_ros_node_name_targets_the_params_file(tmp_path):
    a = Alternative(id="real", kind="docker",
                    config={"container": {"image": "img"},
                            "ros_node_name": "percep"})
    d = DockerLauncher().launch(a, {"x": 1}, ctx(tmp_path))
    mount = next(s for s in d.start if s.endswith(":/sheppy/params.yaml:ro"))
    data = yaml.safe_load(open(mount.split(":")[0]))
    assert data == {"percep": {"ros__parameters": {"x": 1}}}


def test_no_params_no_mount(tmp_path):
    a = Alternative(id="real", kind="docker",
                    config={"container": {"image": "img", "command": "run"}})
    d = DockerLauncher().launch(a, {}, ctx(tmp_path))
    assert not any(":/sheppy/params.yaml:ro" in s for s in d.start)
    assert "--params-file" not in d.start
