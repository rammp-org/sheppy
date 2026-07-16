import asyncio
import json
import sys

import pytest

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config, state_path
from sheppy.daemon.table import ProcessTable

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]
CRASH = [sys.executable, "-c", "raise SystemExit(7)"]


def make_table(tmp_path, events=None):
    cfg = Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"),
                 launch_grace=0.1, stop_grace=0.3, kill_grace=0.3)
    sink = events if events is not None else []
    return ProcessTable(cfg, on_event=lambda n, p: sink.append((n, p))), cfg


def spec(node, argv=SLEEP, alt="a"):
    return {"node": node, "alt_id": alt, "argv": argv, "params": {}}


async def wait_state(table, node, state, timeout=5.0):
    async def poll():
        while table.status().get(node, {}).get("state") != state:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def test_launch_two_nodes_and_status(tmp_path):
    table, _ = make_table(tmp_path)
    await table.launch(spec("camera"))
    await table.launch(spec("lidar"))
    await wait_state(table, "camera", pr.RUNNING)
    await wait_state(table, "lidar", pr.RUNNING)
    st = table.status()
    assert st["camera"]["pid"] and st["camera"]["spec"]["alt_id"] == "a"
    await table.stop_all()


async def test_relaunch_same_node_replaces(tmp_path):
    table, _ = make_table(tmp_path)
    await table.launch(spec("camera", alt="real"))
    await wait_state(table, "camera", pr.RUNNING)
    old_pid = table.status()["camera"]["pid"]
    await table.launch(spec("camera", alt="mock"))
    await wait_state(table, "camera", pr.RUNNING)
    st = table.status()["camera"]
    assert st["spec"]["alt_id"] == "mock" and st["pid"] != old_pid
    await table.stop_all()


async def test_crash_is_retained_with_exit_code(tmp_path):
    table, _ = make_table(tmp_path)
    await table.launch(spec("flaky", CRASH))
    await wait_state(table, "flaky", pr.CRASHED)
    assert table.status()["flaky"]["exit_code"] == 7


async def test_restart_relaunches_same_spec(tmp_path):
    table, _ = make_table(tmp_path)
    await table.launch(spec("flaky", CRASH))
    await wait_state(table, "flaky", pr.CRASHED)
    await table.restart("flaky")
    await wait_state(table, "flaky", pr.CRASHED)   # crashes again — same spec
    assert table.status()["flaky"]["spec"]["argv"] == CRASH


async def test_unknown_node_raises(tmp_path):
    table, _ = make_table(tmp_path)
    with pytest.raises(KeyError):
        await table.stop("ghost")
    with pytest.raises(KeyError):
        table.logs("ghost", 10)


async def test_state_file_tracks_live_entries(tmp_path):
    table, cfg = make_table(tmp_path)
    await table.launch(spec("camera"))
    await wait_state(table, "camera", pr.RUNNING)
    data = json.loads(open(state_path(cfg.home)).read())
    assert "camera" in data["nodes"]
    assert data["nodes"]["camera"]["proc_start"] > 0
    await table.stop("camera")
    data = json.loads(open(state_path(cfg.home)).read())
    assert data["nodes"] == {}


async def test_readoption_controls_previous_daemons_child(tmp_path):
    table_a, cfg = make_table(tmp_path)
    await table_a.launch(spec("camera"))
    await wait_state(table_a, "camera", pr.RUNNING)
    pid = table_a.status()["camera"]["pid"]
    # "daemon dies": table_a is dropped without stopping the child
    table_b, _ = make_table(tmp_path)
    assert table_b.adopt_from_state() == ["camera"]
    st = table_b.status()["camera"]
    assert st["pid"] == pid and st["adopted"] is True
    assert st["state"] == pr.RUNNING
    await table_b.stop("camera")            # really kills the orphan
    assert table_b.status()["camera"]["state"] == pr.STOPPED
    assert table_b.status()["camera"]["exit_code"] is None  # not our child


async def test_adoption_survives_pid_dying_mid_adopt(tmp_path, monkeypatch):
    table_a, cfg = make_table(tmp_path)
    await table_a.launch(spec("camera"))
    await table_a.launch(spec("lidar"))
    await wait_state(table_a, "camera", pr.RUNNING)
    await wait_state(table_a, "lidar", pr.RUNNING)
    # first-adopted node's pidfd_open blows up as if the pid died mid-adopt
    real = pr._pidfd_open
    failed = []

    def flaky(pid, flags=0):
        if not failed:
            failed.append(pid)
            raise ProcessLookupError("gone")
        return real(pid)

    monkeypatch.setattr(pr, "_pidfd_open", flaky)
    table_b, _ = make_table(tmp_path)
    adopted = table_b.adopt_from_state()
    assert len(adopted) == 1               # one skipped, one adopted
    # the trailing _persist() ran: state file holds only the adopted node
    data = json.loads(open(state_path(cfg.home)).read())
    assert set(data["nodes"]) == set(adopted)
    await table_b.stop_all()
    # clean up the never-adopted survivor via the still-live first table
    skipped = [n for n in ("camera", "lidar") if n not in adopted][0]
    await table_a.stop(skipped)


async def test_persist_skips_entry_with_no_proc_start(tmp_path):
    table, cfg = make_table(tmp_path)
    await table.launch(spec("camera"))
    await wait_state(table, "camera", pr.RUNNING)
    entry = table.entry("camera")
    real_pid = entry.pid
    entry.pid = 2 ** 22 - 1                # simulate ticks lookup failing
    table._persist()
    entry.pid = real_pid
    data = json.loads(open(state_path(cfg.home)).read())
    assert "camera" not in data["nodes"]   # not written with proc_start null
    await table.stop_all()


async def test_adoption_skips_dead_and_recycled_pids(tmp_path):
    _, cfg = make_table(tmp_path)
    import os
    os.makedirs(cfg.home, exist_ok=True)
    with open(state_path(cfg.home), "w") as f:
        json.dump({"nodes": {"ghost": {
            "spec": spec("ghost"), "pid": 2 ** 22 - 1,
            "started_at": 0.0, "proc_start": 1}}}, f)
    table_b, _ = make_table(tmp_path)
    assert table_b.adopt_from_state() == []
    assert table_b.status() == {}
