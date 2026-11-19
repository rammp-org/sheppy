"""One supervised child process: spawn, launch grace, crash detection,
SIGINT→SIGTERM→SIGKILL escalation. stdlib only."""
import asyncio
import os
import resource
import signal
import time

LAUNCHING = "launching"
RUNNING = "running"
STOPPING = "stopping"
CRASHED = "crashed"
STOPPED = "stopped"

_CHILD_ENV = {
    # A log file is not a tty: without these, stdio full-buffers and a
    # crashed node's last lines would be stuck in a userspace buffer.
    "PYTHONUNBUFFERED": "1",
    "RCUTILS_LOGGING_BUFFERED_STREAM": "0",
}


def _unlimited_core() -> None:
    resource.setrlimit(resource.RLIMIT_CORE,
                       (resource.RLIM_INFINITY, resource.RLIM_INFINITY))


try:
    _pidfd_open = os.pidfd_open
except AttributeError:
    # Some CPython builds (e.g. python-build-standalone, as used by uv's
    # managed interpreters) omit os.pidfd_open even on kernels that support
    # the syscall. Fall back to the raw syscall (number 434, stable across
    # x86_64 and aarch64) via ctypes — still stdlib only.
    import ctypes

    _libc = ctypes.CDLL(None, use_errno=True)
    _SYS_PIDFD_OPEN = 434

    def _pidfd_open(pid: int, flags: int = 0) -> int:
        fd = _libc.syscall(_SYS_PIDFD_OPEN, pid, flags)
        if fd < 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
        return fd


def _boot_ticks() -> int:
    """Now, in the units of a process's start time (/proc/<pid>/stat
    field 22): clock ticks since boot."""
    return (time.clock_gettime_ns(time.CLOCK_BOOTTIME)
            // (10**9 // os.sysconf("SC_CLK_TCK")))


class Supervised:
    """Common supervision surface: state, stop escalation, exit event."""

    def __init__(self, spec: dict, cfg, log, on_state) -> None:
        self.spec = spec
        self.state = STOPPED
        self.pid: "int | None" = None
        self.started_at: "float | None" = None
        self.exit_code: "int | None" = None
        self._cfg = cfg
        self.log = log
        self._on_state = on_state
        self._stop_requested = False
        self._exited = asyncio.Event()
        self._exit_ticks = 0           # when the leader's exit was seen
        self.adopted = False

    def _set(self, state: str) -> None:
        self.state = state
        self._on_state(self)

    async def stop(self) -> None:
        if self.pid is None:
            return
        if self._exited.is_set():
            # The leader is gone, but a helper in its group may have
            # outlived a crash and still hold the hardware (#163). Clear it
            # out with the same escalation; the run's state stays as it is.
            if not self._old_group_alive():
                return
        else:
            self._stop_requested = True
            self._set(STOPPING)
        escalation = ((signal.SIGINT, self._cfg.stop_grace),
                      (signal.SIGTERM, self._cfg.kill_grace))
        for sig, grace in escalation:
            self._signal_group(sig)
            if await self._group_gone_within(grace):
                return
        self._signal_group(signal.SIGKILL)
        await self._exited.wait()
        # SIGKILL can't be ignored; anything left is only waiting to be
        # reaped. Don't hold the node's lock forever if that never happens.
        await self._group_gone_within(self._cfg.kill_grace)

    def cancel_start(self) -> None:
        """Abort a start still in progress. Spawning a child returns at
        once, so only DetachedSupervisor has one to abort."""

    async def wait(self) -> None:
        await self._exited.wait()

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(self.pid, sig)       # pgid == pid (new session)
        except (ProcessLookupError, PermissionError):
            pass

    async def _exited_within(self, grace: float) -> bool:
        try:
            await asyncio.wait_for(asyncio.shield(self._exited.wait()), grace)
            return True
        except asyncio.TimeoutError:
            return False

    def _group_alive(self) -> bool:
        try:
            os.killpg(self.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # EPERM: every remaining member belongs to another uid (a helper
            # started via sudo). It exists but we can't signal it; treat it
            # as alive and let the escalation run out its grace.
            return True

    def _old_group_alive(self) -> bool:
        """A process in the exited leader's group started before that exit.
        Once the group empties, the kernel may give its pid to a new process
        whose own group has the same pgid; everything in that group started
        after our leader exited, so it is never signalled (#163). A group
        whose pre-exit members are all gone is left alone, even if a process
        they forked later is still in it."""
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/stat", "rb") as f:
                    fields = f.read().rsplit(b")", 1)[1].split()
            except OSError:            # it just exited
                continue
            pgid, started = int(fields[2]), int(fields[19])
            if pgid == self.pid and started <= self._exit_ticks:
                return True
        return False

    async def _group_gone_within(self, grace: float) -> bool:
        """True once the leader has exited *and* its process group is
        empty. The leader dying is not enough: a helper it spawned (same
        group) may have ignored the signal and still hold the hardware
        (#89)."""
        deadline = time.monotonic() + grace
        if not await self._exited_within(grace):
            return False
        while self._group_alive():
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)
        return True


class ManagedProcess(Supervised):
    def __init__(self, spec: dict, cfg, log, on_state) -> None:
        super().__init__(spec, cfg, log, on_state)
        self._watch_task: "asyncio.Task | None" = None

    async def start(self) -> None:
        fd = self.log.open_run()
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.spec["descriptor"]["start"],
                stdout=fd, stderr=fd, stdin=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                env={**os.environ, **_CHILD_ENV},
                preexec_fn=_unlimited_core if self._cfg.coredumps else None)
        except (OSError, ValueError, TypeError) as e:
            # Not found, not executable, a non-string argv element
            # (TypeError): the node never ran. Say why where the operator
            # looks (#93); if even that write fails, the state still tells.
            try:
                os.write(fd, f"sheppyd: cannot start: {e}\n".encode())
            except OSError:
                pass
            proc = None
        finally:
            os.close(fd)                   # the child holds its own copy
        if proc is None:
            self.started_at = time.time()
            self.log.read_new()            # the reason, into the ring
            self._exited.set()
            self._set(CRASHED)
            return
        self.pid = proc.pid
        self.started_at = time.time()
        self._stop_requested = False
        self._exited = asyncio.Event()
        self.exit_code = None
        # The loop holds only weak refs to tasks; dropping this reference
        # could GC a live watcher and silently kill supervision. Created
        # before the state report so a failing report (#86) can't either.
        self._watch_task = asyncio.ensure_future(self._watch(proc))
        self._set(LAUNCHING)

    async def _watch(self, proc) -> None:
        try:
            rc = await asyncio.wait_for(
                asyncio.shield(proc.wait()), self._cfg.launch_grace)
        except asyncio.TimeoutError:
            if not self._stop_requested:
                self._set(RUNNING)
            rc = await proc.wait()
        self.exit_code = rc
        self.log.read_new()                # capture dying words in the ring
        self._exit_ticks = _boot_ticks()
        self._exited.set()
        self._set(STOPPED if self._stop_requested else CRASHED)


class AdoptedProcess(Supervised):
    """A previous daemon's child, re-owned via pidfd. Not our child: exit
    codes are unknowable (None); exit is observed event-driven through the
    pidfd becoming readable — no polling."""

    def __init__(self, spec: dict, cfg, log, on_state,
                 pid: int, started_at: float) -> None:
        super().__init__(spec, cfg, log, on_state)
        self.pid = pid
        self.started_at = started_at
        self.adopted = True
        self._pidfd = _pidfd_open(pid)
        asyncio.get_running_loop().add_reader(self._pidfd, self._pidfd_ready)
        self.state = RUNNING           # it survived at least one daemon

    def _pidfd_ready(self) -> None:
        loop = asyncio.get_running_loop()
        loop.remove_reader(self._pidfd)
        os.close(self._pidfd)
        self.log.read_new()
        self._exit_ticks = _boot_ticks()
        self._exited.set()
        self._set(STOPPED if self._stop_requested else CRASHED)


def _parse_exit(out: bytes) -> "int | None":
    try:
        return int(out.strip().split()[-1])
    except (ValueError, IndexError):
        return None


class DetachedSupervisor(Supervised):
    """Supervises a unit that outlives the process that started it (a
    container, a transient service). Driven entirely by the descriptor's
    command-set; the daemon learns no runtime specifics."""

    def __init__(self, spec, cfg, log, on_state) -> None:
        super().__init__(spec, cfg, log, on_state)
        d = spec["descriptor"]
        self._name = d.get("name")
        self._start_cmd = list(d["start"])
        self._reset_cmd = d.get("reset")
        self._watch_cmd = d.get("watch")
        self._poll_cmd = d.get("poll")
        self._alive_cmd = d.get("alive")
        self._stop_cmd = d.get("stop")
        self._logs_cmd = d.get("logs")
        self._stats_cmd = d.get("stats")
        grace = d.get("grace") or {}
        self._launch_grace = grace.get("launch", cfg.launch_grace)
        self._poll_interval = grace.get("poll", 1.0)
        self._watch_task = None
        self._watch_proc = None
        self._logs_proc = None
        self._starting = False
        self._start_proc = None
        self.adopted = False

    async def _run_once(self, argv, capture=False,
                        stderr=asyncio.subprocess.DEVNULL):
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=(asyncio.subprocess.PIPE if capture
                        else asyncio.subprocess.DEVNULL),
                stderr=stderr,
                stdin=asyncio.subprocess.DEVNULL)
        except (OSError, ValueError):
            return 127, b""
        out, _ = await proc.communicate()
        return proc.returncode, (out or b"")

    async def _run_start(self, fd) -> int:
        # Its own session, so cancel_start() can kill the whole group: a
        # `sh -c` and the `docker pull` under it.
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._start_cmd, stdout=asyncio.subprocess.DEVNULL,
                stderr=fd, stdin=asyncio.subprocess.DEVNULL,
                start_new_session=True)
        except (OSError, ValueError):
            return 127
        self._start_proc = proc
        if self._stop_requested:           # cancelled while spawning
            self._kill_start()
        try:
            return await proc.wait()
        finally:
            self._start_proc = None

    def cancel_start(self) -> None:
        """Kill a `start` that is still running; start() then cleans up and
        ends STOPPED (#189)."""
        if not self._starting or self._stop_requested:
            return
        self._stop_requested = True
        self._set(STOPPING)
        self._kill_start()

    def _kill_start(self) -> None:
        proc = self._start_proc
        if proc is not None and proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    async def _open_logs(self, fd) -> None:
        if not self._logs_cmd:
            return
        try:
            self._logs_proc = await asyncio.create_subprocess_exec(
                *self._logs_cmd, stdout=fd, stderr=fd,
                stdin=asyncio.subprocess.DEVNULL)
        except (OSError, ValueError):
            self._logs_proc = None

    async def start(self) -> None:
        self._stop_requested = False
        self._exited = asyncio.Event()
        self.exit_code = None
        self.started_at = time.time()
        # Launching from here, not after `start` returns: a `docker run`
        # may pull for minutes, and status and the state file must show
        # the unit as pending so a daemon death mid-start can re-adopt it.
        self._set(LAUNCHING)
        # The run log opens before `start` so a failed launch (image
        # missing, port in use) leaves the runtime's error in `sheppy logs`.
        fd = self.log.open_run()
        self._starting = True
        try:
            if self._reset_cmd:                            # best-effort cleanup
                await self._run_once(self._reset_cmd, stderr=fd)
            rc = None if self._stop_requested else await self._run_start(fd)
            if self._stop_requested:
                # Stopped mid-start: clear whatever the start left behind (a
                # created container, or a unit it finished bringing up).
                cleanup = self._reset_cmd or self._stop_cmd
                if rc is not None and cleanup:
                    await self._run_once(cleanup, stderr=fd)
                self._finish(None)
                return
            if rc != 0:
                self.log.read_new()
                self._set(CRASHED)                         # launch failed
                self._exited.set()
                return
            await self._open_logs(fd)
        finally:
            self._starting = False
            os.close(fd)
        self._watch_task = asyncio.ensure_future(
            self._watch() if self._watch_cmd else self._poll())

    async def _watch(self) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._watch_cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.DEVNULL)
        except (OSError, ValueError):
            self._finish(None)
            return
        self._watch_proc = proc
        # communicate() may only be awaited once; shield the same task so a
        # launch-grace timeout doesn't force a second, concurrent read.
        comm = asyncio.ensure_future(proc.communicate())
        try:
            out, _ = await asyncio.wait_for(
                asyncio.shield(comm), self._launch_grace)
        except asyncio.TimeoutError:
            if not self._stop_requested:
                self._set(RUNNING)
            out, _ = await comm
        if await self._up_again():
            # Restarted outside sheppy (`docker restart`, #220): follow it.
            self.log.read_new()
            self._reap_logs()
            await self.reattach()
            return
        self._finish(_parse_exit(out))

    async def _up_again(self) -> bool:
        if self._stop_requested or not self._alive_cmd:
            return False
        rc, _ = await self._run_once(self._alive_cmd)
        return rc == 0 and not self._stop_requested    # stop may land meanwhile

    async def _poll(self) -> None:
        try:
            await asyncio.wait_for(self._exited.wait(), self._launch_grace)
            return
        except asyncio.TimeoutError:
            pass
        if not self._stop_requested:
            self._set(RUNNING)
        while not self._stop_requested:
            await asyncio.sleep(self._poll_interval)
            rc, _ = await self._run_once(self._poll_cmd)
            if rc != 0:
                break
        self._finish(None)

    def _finish(self, code) -> None:
        if self._exited.is_set():
            return
        self.exit_code = code
        self.log.read_new()
        self._reap_logs()
        self._exited.set()
        self._set(STOPPED if self._stop_requested else CRASHED)

    def _reap_logs(self) -> None:
        proc = self._logs_proc
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

    async def stop(self) -> None:
        if self._exited.is_set():
            return
        self._stop_requested = True
        self._set(STOPPING)
        if self._stop_cmd:
            rc, _ = await self._run_once(self._stop_cmd)
            if rc == 0 and await self._exited_within(
                    self._cfg.stop_grace + self._cfg.kill_grace):
                return
        # No stop command, or it failed / the unit outlived the grace: we
        # have no way to tell the unit to exit, so don't block forever on a
        # watch/poll loop that may never observe that. Force the transition
        # and reap the watcher ourselves.
        if self._watch_task is not None:
            self._watch_task.cancel()
        # Cancelling the task only stops us awaiting it; a long-running
        # watch subprocess (e.g. `docker wait`) is a separate OS process
        # that keeps running unless killed directly.
        if self._watch_proc is not None and self._watch_proc.returncode is None:
            try:
                self._watch_proc.kill()
            except ProcessLookupError:
                pass
        self._finish(None)

    def release(self) -> None:
        """Kill the watch and logs followers but leave the unit running."""
        for proc in (self._watch_proc, self._logs_proc):
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    def mark_adopted(self, started_at) -> None:
        self._stop_requested = False
        self._exited = asyncio.Event()
        self.exit_code = None
        self.adopted = True
        self.started_at = started_at
        self.state = RUNNING

    async def reattach(self) -> None:
        if self._logs_cmd:
            fd = self.log.open_run()
            try:
                await self._open_logs(fd)
            finally:
                os.close(fd)
        self._watch_task = asyncio.ensure_future(
            self._watch() if self._watch_cmd else self._poll())
