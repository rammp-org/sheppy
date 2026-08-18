import asyncio
import os

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config
from sheppy.daemon.logs import NodeLog


def make(tmp_path, descriptor, **cfg_kw):
    cfg_kw.setdefault("launch_grace", 0.15)
    cfg = Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"), **cfg_kw)
    log = NodeLog(cfg.log_dir, "n", cfg.ring_lines, cfg.keep_runs)
    states = []
    spec = {"node": "n", "alt_id": "a", "params": {}, "descriptor": descriptor}
    sup = pr.DetachedSupervisor(spec, cfg, log,
                                on_state=lambda s: states.append(s.state))
    return sup, states, log


def sh(script):
    return ["sh", "-c", script]


async def wait_for(cond, timeout=5.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def test_runs_then_stops_clean(tmp_path):
    state = str(tmp_path / "STATE")
    desc = {"supervise": "detached", "name": "n",
            "start": sh(f"echo up > {state}"),
            "watch": sh(f"while [ -f {state} ]; do sleep 0.02; done; echo 0"),
            "stop":  sh(f"rm -f {state}"),
            "logs":  sh("echo hello-from-unit")}
    sup, states, log = make(tmp_path, desc)
    await sup.start()
    assert sup.state == pr.LAUNCHING
    await wait_for(lambda: sup.state == pr.RUNNING)
    await sup.stop()
    assert sup.state == pr.STOPPED
    assert states == [pr.LAUNCHING, pr.RUNNING, pr.STOPPING, pr.STOPPED]


async def test_start_failure_is_crashed(tmp_path):
    desc = {"supervise": "detached", "name": "n",
            "start": sh("exit 3"), "watch": sh("echo 0")}
    sup, _, _ = make(tmp_path, desc)
    await sup.start()
    await sup.wait()
    assert sup.state == pr.CRASHED


async def test_crash_via_watch_exit_carries_code(tmp_path):
    desc = {"supervise": "detached", "name": "n",
            "start": sh("true"),
            "watch": sh("sleep 0.25; echo 5"),
            "stop":  sh("true")}
    sup, states, _ = make(tmp_path, desc, launch_grace=0.1)
    await sup.start()
    await sup.wait()
    assert states == [pr.LAUNCHING, pr.RUNNING, pr.CRASHED]
    assert sup.exit_code == 5


async def test_logs_reach_the_ring(tmp_path):
    state = str(tmp_path / "S")
    desc = {"supervise": "detached", "name": "n",
            "start": sh(f"echo up > {state}"),
            "watch": sh(f"while [ -f {state} ]; do sleep 0.02; done; echo 0"),
            "stop":  sh(f"rm -f {state}"),
            "logs":  sh("echo container-says-hi")}
    sup, _, log = make(tmp_path, desc)
    await sup.start()
    await wait_for(lambda: "container-says-hi" in (log.read_new() or log.tail()))
    await sup.stop()
    assert "container-says-hi" in log.tail()


async def test_reset_runs_before_start(tmp_path):
    order = str(tmp_path / "ORDER")
    desc = {"supervise": "detached", "name": "n",
            "reset": sh(f"echo reset >> {order}"),
            "start": sh(f"echo start >> {order}"),
            "watch": sh("sleep 0.3; echo 0"), "stop": sh("true")}
    sup, _, _ = make(tmp_path, desc, launch_grace=0.05)
    await sup.start()
    await wait_for(lambda: os.path.exists(order))
    assert open(order).read().split() == ["reset", "start"]
    await sup.stop()


async def test_poll_mode_without_watch(tmp_path):
    state = str(tmp_path / "P")
    desc = {"supervise": "detached", "name": "n",
            "start": sh(f"echo up > {state}"),
            "poll":  sh(f"test -f {state}"),
            "stop":  sh(f"rm -f {state}"),
            "grace": {"poll": 0.05}}
    sup, _, _ = make(tmp_path, desc, launch_grace=0.05)
    await sup.start()
    await wait_for(lambda: sup.state == pr.RUNNING)
    await sup.stop()
    assert sup.state == pr.STOPPED


async def test_stop_completes_when_descriptor_has_no_stop_cmd(tmp_path):
    # A detached descriptor may legally omit 'stop'. The watch command below
    # blocks on the state file forever (nothing ever removes it, since
    # there's no stop command to do so) -- stop() must not hang waiting on
    # a unit it has no way to command into exiting.
    state = str(tmp_path / "S")
    desc = {"supervise": "detached", "name": "n",
            "start": sh(f"echo up > {state}"),
            "watch": sh(f"while [ -f {state} ]; do sleep 0.02; done; echo 0"),
            "logs":  sh("while true; do echo tick; sleep 0.05; done")}
    sup, _, _ = make(tmp_path, desc)
    await sup.start()
    await wait_for(lambda: sup.state == pr.RUNNING)
    assert sup._logs_proc is not None and sup._logs_proc.returncode is None
    await asyncio.wait_for(sup.stop(), 3)     # regression hangs -> test hangs, not the suite
    assert sup.state == pr.STOPPED
    # the logs follower must still be reaped even without a stop command
    await asyncio.wait_for(sup._logs_proc.wait(), 2)
    assert sup._logs_proc.returncode is not None


async def test_logs_follower_is_reaped_on_stop(tmp_path):
    state = str(tmp_path / "S")
    desc = {"supervise": "detached", "name": "n",
            "start": sh(f"echo up > {state}"),
            "watch": sh(f"while [ -f {state} ]; do sleep 0.02; done; echo 0"),
            "stop":  sh(f"rm -f {state}"),
            "logs":  sh("while true; do echo tick; sleep 0.05; done")}
    sup, _, _ = make(tmp_path, desc)
    await sup.start()
    await wait_for(lambda: sup.state == pr.RUNNING)
    assert sup._logs_proc is not None and sup._logs_proc.returncode is None
    await sup.stop()
    # the follower must be terminated, not left running
    await asyncio.wait_for(sup._logs_proc.wait(), 2)
    assert sup._logs_proc.returncode is not None
