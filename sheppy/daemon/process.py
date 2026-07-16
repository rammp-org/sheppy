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
