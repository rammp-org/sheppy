import subprocess
import sys
import time

from sheppy.daemon.usage import sample


def spawn(code):
    return subprocess.Popen([sys.executable, "-c", code],
                            start_new_session=True)   # pgid == pid


def test_rss_is_positive_for_live_group():
    child = spawn("import time; time.sleep(30)")
    try:
        usage, prev = sample({"n": child.pid}, {})
        assert usage["n"]["rss_mb"] > 0
        assert usage["n"]["cpu_pct"] == 0.0            # first sample
        assert prev["n"]
    finally:
        child.kill(); child.wait()


def test_busy_group_shows_cpu_between_samples():
    child = spawn("while True: pass")
    try:
        _, prev = sample({"n": child.pid}, {})
        time.sleep(0.3)
        usage, _ = sample({"n": child.pid}, prev)
        assert usage["n"]["cpu_pct"] > 20
    finally:
        child.kill(); child.wait()


def test_group_sums_children():
    code = ("import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c',"
            " 'import time; time.sleep(30)'])\n"
            "time.sleep(30)\n")
    child = spawn(code)
    try:
        time.sleep(0.5)                                # let the child fork
        solo = spawn("import time; time.sleep(30)")
        usage, _ = sample({"pair": child.pid, "solo": solo.pid}, {})
        assert usage["pair"]["rss_mb"] > usage["solo"]["rss_mb"]
        solo.kill(); solo.wait()
    finally:
        import os, signal
        os.killpg(child.pid, signal.SIGKILL); child.wait()


def test_dead_group_is_omitted():
    child = spawn("pass")
    child.wait()
    usage, prev = sample({"gone": child.pid}, {})
    assert usage == {} and prev == {}
