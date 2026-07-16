import asyncio
import os
import sys

import pytest

from sheppy.daemon.config import Config
from sheppy.daemon.logs import NodeLog
from sheppy.daemon import process as pr


def make_cfg(tmp_path, **kw):
    kw.setdefault("launch_grace", 0.2)
    kw.setdefault("stop_grace", 0.3)
    kw.setdefault("kill_grace", 0.3)
    return Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"), **kw)


def make_mp(tmp_path, code, **cfg_kw):
    cfg = make_cfg(tmp_path, **cfg_kw)
    log = NodeLog(cfg.log_dir, "n", cfg.ring_lines, cfg.keep_runs)
    states = []
    mp = pr.ManagedProcess(
        {"node": "n", "alt_id": "a", "argv": [sys.executable, "-c", code],
         "params": {}},
        cfg, log, on_state=lambda m: states.append(m.state))
    return mp, states, log


async def wait_for(cond, timeout=5.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def test_survives_grace_becomes_running_then_stops_clean(tmp_path):
    mp, states, _ = make_mp(tmp_path, "import time; time.sleep(30)")
    await mp.start()
    assert mp.state == pr.LAUNCHING and mp.pid
    await wait_for(lambda: mp.state == pr.RUNNING)
    await mp.stop()
    assert mp.state == pr.STOPPED          # stop requested ⇒ not a crash
    assert states == [pr.LAUNCHING, pr.RUNNING, pr.STOPPING, pr.STOPPED]


async def test_instant_failure_is_crashed_with_exit_code(tmp_path):
    mp, _, _ = make_mp(tmp_path, "raise SystemExit(3)")
    await mp.start()
    await mp.wait()
    assert mp.state == pr.CRASHED and mp.exit_code == 3


async def test_late_crash_after_running(tmp_path):
    mp, states, _ = make_mp(
        tmp_path, "import time; time.sleep(0.5); raise SystemExit(2)",
        launch_grace=0.1)
    await mp.start()
    await mp.wait()
    assert states == [pr.LAUNCHING, pr.RUNNING, pr.CRASHED]
    assert mp.exit_code == 2


async def test_sigint_ignorer_is_escalated(tmp_path):
    code = ("import signal, time\n"
            "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "time.sleep(30)\n")
    mp, _, _ = make_mp(tmp_path, code)
    await mp.start()
    await wait_for(lambda: mp.state == pr.RUNNING)
    await mp.stop()                        # SIGINT ignored → SIGTERM lands
    assert mp.state == pr.STOPPED


async def test_dying_words_reach_the_ring(tmp_path):
    mp, _, log = make_mp(tmp_path,
                         "print('goodbye cruel world'); raise SystemExit(1)")
    await mp.start()
    await mp.wait()
    assert "goodbye cruel world" in log.tail()


async def test_process_group_kills_grandchildren(tmp_path):
    code = ("import subprocess, sys\n"
            "p = subprocess.Popen(['sleep', '30'])\n"
            "print(p.pid, flush=True)\n"
            "p.wait()\n")
    mp, _, log = make_mp(tmp_path, code)
    await mp.start()
    await wait_for(lambda: log.read_new() is not None and log.tail())
    grandchild = int(log.tail()[0])
    await mp.stop()
    await asyncio.sleep(0.1)               # give the kernel a beat to reap
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild, 0)
