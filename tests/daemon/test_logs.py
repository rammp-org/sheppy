import os
from sheppy.daemon.logs import NodeLog


def make_log(tmp_path, **kw):
    kw.setdefault("ring_lines", 5)
    kw.setdefault("keep_runs", 3)
    return NodeLog(str(tmp_path), "camera", **kw)


def test_open_run_creates_file_and_child_can_write(tmp_path):
    log = make_log(tmp_path)
    fd = log.open_run()
    os.write(fd, b"hello\nworld\n")
    os.close(fd)
    assert log.read_new() == ["hello", "world"]
    assert log.tail() == ["hello", "world"]
    assert log.path and log.path.endswith(".log")


def test_partial_line_held_until_newline(tmp_path):
    log = make_log(tmp_path)
    fd = log.open_run()
    os.write(fd, b"first\nhal")
    assert log.read_new() == ["first"]
    os.write(fd, b"f second\n")
    os.close(fd)
    assert log.read_new() == ["half second"]


def test_ring_is_capped(tmp_path):
    log = make_log(tmp_path, ring_lines=3)
    fd = log.open_run()
    os.write(fd, b"".join(b"line %d\n" % i for i in range(10)))
    os.close(fd)
    log.read_new()
    assert log.tail() == ["line 7", "line 8", "line 9"]
    assert log.tail(2) == ["line 8", "line 9"]


def test_prune_keeps_keep_runs_files(tmp_path):
    log = make_log(tmp_path, keep_runs=3)
    for _ in range(5):
        os.close(log.open_run())
    node_dir = tmp_path / "camera"
    assert len(list(node_dir.glob("*.log"))) == 3


def test_attach_latest_rebuilds_tail(tmp_path):
    log = make_log(tmp_path, ring_lines=2)
    fd = log.open_run()
    os.write(fd, b"a\nb\nc\n")
    os.close(fd)
    # a fresh NodeLog (new daemon) re-adopts the same node dir
    fresh = make_log(tmp_path, ring_lines=2)
    assert fresh.attach_latest() is True
    assert fresh.tail() == ["b", "c"]
    assert fresh.read_new() == []      # offset is at EOF


def test_attach_latest_with_no_runs_returns_false(tmp_path):
    assert make_log(tmp_path).attach_latest() is False
