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
        self.adopted = False

    def _set(self, state: str) -> None:
        self.state = state
        self._on_state(self)

    async def stop(self) -> None:
        if self.pid is None or self._exited.is_set():
            return
        self._stop_requested = True
        self._set(STOPPING)
        escalation = ((signal.SIGINT, self._cfg.stop_grace),
                      (signal.SIGTERM, self._cfg.kill_grace))
        for sig, grace in escalation:
            self._signal_group(sig)
            if await self._exited_within(grace):
                return
        self._signal_group(signal.SIGKILL)
        await self._exited.wait()

    async def wait(self) -> None:
        await self._exited.wait()

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(self.pid, sig)       # pgid == pid (new session)
        except ProcessLookupError:
            pass

    async def _exited_within(self, grace: float) -> bool:
        try:
            await asyncio.wait_for(asyncio.shield(self._exited.wait()), grace)
            return True
        except asyncio.TimeoutError:
            return False


class ManagedProcess(Supervised):
    def __init__(self, spec: dict, cfg, log, on_state) -> None:
        super().__init__(spec, cfg, log, on_state)
        self._watch_task: "asyncio.Task | None" = None

    async def start(self) -> None:
        fd = self.log.open_run()
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.spec["argv"],
                stdout=fd, stderr=fd, stdin=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                env={**os.environ, **_CHILD_ENV},
                preexec_fn=_unlimited_core if self._cfg.coredumps else None)
        finally:
            os.close(fd)                   # the child holds its own copy
        self.pid = proc.pid
        self.started_at = time.time()
        self._stop_requested = False
        self._exited = asyncio.Event()
        self.exit_code = None
        self._set(LAUNCHING)
        # The loop holds only weak refs to tasks; dropping this reference
        # could GC a live watcher and silently kill supervision.
        self._watch_task = asyncio.ensure_future(self._watch(proc))

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
        self._stop_cmd = d.get("stop")
        self._logs_cmd = d.get("logs")
        self._stats_cmd = d.get("stats")
        grace = d.get("grace") or {}
        self._launch_grace = grace.get("launch", cfg.launch_grace)
        self._poll_interval = grace.get("poll", 1.0)
        self._watch_task = None
        self._logs_proc = None
        self.adopted = False

    async def _run_once(self, argv, capture=False):
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=(asyncio.subprocess.PIPE if capture
                        else asyncio.subprocess.DEVNULL),
                stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.DEVNULL)
        except (OSError, ValueError):
            return 127, b""
        out, _ = await proc.communicate()
        return proc.returncode, (out or b"")

    async def _open_logs(self):
        if not self._logs_cmd:
            return
        fd = self.log.open_run()
        try:
            self._logs_proc = await asyncio.create_subprocess_exec(
                *self._logs_cmd, stdout=fd, stderr=fd,
                stdin=asyncio.subprocess.DEVNULL)
        except (OSError, ValueError):
            self._logs_proc = None
        finally:
            os.close(fd)

    async def start(self) -> None:
        self._stop_requested = False
        self._exited = asyncio.Event()
        self.exit_code = None
        self.started_at = time.time()
        if self._reset_cmd:
            await self._run_once(self._reset_cmd)          # best-effort cleanup
        rc, _ = await self._run_once(self._start_cmd)
        if rc != 0:
            self._set(CRASHED)                             # launch failed
            self._exited.set()
            return
        await self._open_logs()
        self._set(LAUNCHING)
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
        self._finish(_parse_exit(out))

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
            await self._run_once(self._stop_cmd)
        await self._exited.wait()

    def mark_adopted(self, started_at) -> None:
        self._stop_requested = False
        self._exited = asyncio.Event()
        self.exit_code = None
        self.adopted = True
        self.started_at = started_at
        self.state = RUNNING

    async def reattach(self) -> None:
        await self._open_logs()
        self._watch_task = asyncio.ensure_future(
            self._watch() if self._watch_cmd else self._poll())
