import os
import threading

import yaml
from sheppy.launch.base import LaunchContext
from sheppy.manifest import Manifest


def ctx(tmp_path, node="camera"):
    return LaunchContext(node, Manifest(machines=[], nodes=[]),
                         home=str(tmp_path))


def test_scratch_dir_is_created_under_home(tmp_path):
    d = ctx(tmp_path).scratch_dir()
    assert os.path.isdir(d) and str(tmp_path) in d and "camera" in d


def test_write_params_file_wildcard(tmp_path):
    path = ctx(tmp_path).write_params_file({"max_range": 5.0, "frame": "cam"})
    data = yaml.safe_load(open(path))
    assert data == {"/**": {"ros__parameters": {"max_range": 5.0,
                                                "frame": "cam"}}}


def test_write_params_file_named_node(tmp_path):
    path = ctx(tmp_path).write_params_file({"x": 1}, ros_node_name="percep")
    data = yaml.safe_load(open(path))
    assert data == {"percep": {"ros__parameters": {"x": 1}}}


def test_write_params_file_new_params_never_touch_an_earlier_file(tmp_path):
    # #182: a later resolve with other params must not rewrite the file an
    # earlier descriptor (a running container) mounts
    c = ctx(tmp_path)
    first = c.write_params_file({"x": 1})
    second = c.write_params_file({"x": 2})
    assert first != second
    assert yaml.safe_load(open(first))["/**"]["ros__parameters"]["x"] == 1
    assert yaml.safe_load(open(second))["/**"]["ros__parameters"]["x"] == 2


def test_write_params_file_same_params_same_file_not_rewritten(tmp_path):
    c = ctx(tmp_path)
    first = c.write_params_file({"x": 1})
    before = os.stat(first)
    second = c.write_params_file({"x": 1})
    after = os.stat(second)
    assert first == second
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino,
                                                   after.st_mtime_ns)
    assert after.st_mode & 0o044 == 0o044      # readable by a container user


def test_write_params_file_concurrent_writers_leave_a_valid_file(tmp_path):
    params = {f"k{i}": "v" * 200 for i in range(200)}
    paths, seen = [], []

    def write():
        path = ctx(tmp_path).write_params_file(params)
        paths.append(path)
        seen.append(yaml.safe_load(open(path)))  # as a launch right after would

    threads = [threading.Thread(target=write) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(paths)) == 1
    assert seen == [{"/**": {"ros__parameters": params}}] * len(threads)
    assert os.listdir(os.path.dirname(paths[0])) == [
        os.path.basename(paths[0])]            # no temp files left behind


def test_warnings_accumulate(tmp_path):
    c = ctx(tmp_path)
    assert c.warnings == []
    c.warn("params ignored")
    c.warn("second")
    assert c.warnings == ["params ignored", "second"]
