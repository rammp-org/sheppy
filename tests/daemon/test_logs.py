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


def test_attach_latest_holds_back_incomplete_last_line(tmp_path):
    log = make_log(tmp_path)
    fd = log.open_run()
    os.write(fd, b"a\nb\nc")            # 'c...' still being written
    fresh = make_log(tmp_path)
    assert fresh.attach_latest() is True
    assert fresh.tail() == ["a", "b"]    # fragment held back, not a line
    os.write(fd, b"onclusion\n")
    os.close(fd)
    assert fresh.read_new() == ["conclusion"]
    assert fresh.tail() == ["a", "b", "conclusion"]


def test_attach_latest_with_no_runs_returns_false(tmp_path):
    assert make_log(tmp_path).attach_latest() is False


def write_burst(fd, n=1000):
    """n lines of exactly 1000 bytes: a 64 KiB window opens mid-line."""
    os.write(fd, b"".join(b"line %05d " % i + b"x" * 989 + b"\n"
                          for i in range(n)))


def test_read_new_is_bounded_to_the_tail_window(tmp_path):
    # A chatty node that logged unwatched for hours must not make the
    # daemon decode the whole file to keep ring_lines of it (#87). The
    # ring is large enough that a fragment at the window's edge would
    # survive in it; none may.
    log = make_log(tmp_path, ring_lines=300)
    fd = log.open_run()
    os.write(fd, b"hal")                    # a fragment from before the burst
    assert log.read_new() == []
    write_burst(fd)                         # ~1 MB
    os.close(fd)
    lines = log.read_new()
    assert 0 < len(lines) < 100             # a window, not the whole file
    assert lines[-1].startswith("line 00999 ")
    assert all(len(line) == 1000 and line.startswith("line ")
               for line in log.tail())      # no fragment, no stale "hal"
    assert log.read_new() == []             # offset is at EOF


def test_attach_latest_drops_the_fragment_at_the_window_edge(tmp_path):
    log = make_log(tmp_path, ring_lines=300)
    fd = log.open_run()
    write_burst(fd)
    os.close(fd)
    fresh = make_log(tmp_path, ring_lines=300)
    assert fresh.attach_latest() is True
    assert all(len(line) == 1000 for line in fresh.tail())
    assert fresh.tail()[-1].startswith("line 00999 ")
    assert fresh.read_new() == []


def test_tail_of_zero_or_negative_is_empty(tmp_path):
    # lines[-0:] is everything and lines[5:] drops the head (#104)
    log = make_log(tmp_path)
    fd = log.open_run()
    os.write(fd, b"a\nb\nc\n")
    os.close(fd)
    log.read_new()
    assert log.tail(0) == []
    assert log.tail(-2) == []
