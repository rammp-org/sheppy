"""The daemon's heart: node -> supervised process, mirrored to a state
file so a restarted daemon re-adopts still-live children. stdlib only."""
import json
import os

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config, state_path
from sheppy.daemon.logs import NodeLog


def _proc_start_ticks(pid: int) -> "int | None":
    """Field 22 of /proc/<pid>/stat — guards against recycled pids."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read()
        return int(data.rsplit(b")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


class ProcessTable:
    def __init__(self, cfg: Config, on_event) -> None:
        self._cfg = cfg
        self._on_event = on_event
        self._entries: dict = {}

    # ---- operations -------------------------------------------------------
    async def launch(self, spec: dict) -> None:
        node = spec["node"]
        old = self._entries.get(node)
        if old is not None and not old._exited.is_set() \
                and old.state != pr.STOPPED:
            await old.stop()
        log = NodeLog(self._cfg.log_dir, node,
                      self._cfg.ring_lines, self._cfg.keep_runs)
        descriptor = spec.get("descriptor") or {}
        supervise = descriptor.get("supervise")
        if supervise == "inherit":
            mp_spec = {**spec, "argv": list(descriptor["start"])}
            proc = pr.ManagedProcess(mp_spec, self._cfg, log, self._on_state)
        elif supervise == "detached":
            proc = pr.DetachedSupervisor(spec, self._cfg, log, self._on_state)
        else:
            raise ValueError(f"unknown supervise: {supervise!r}")
        self._entries[node] = proc
        await proc.start()

    async def stop(self, node: str) -> None:
        await self._entries[node].stop()

    async def restart(self, node: str) -> None:
        entry = self._entries[node]
        await entry.stop()
        await self.launch(entry.spec)

    async def stop_all(self) -> None:
        for node in list(self._entries):
            await self.stop(node)

    # ---- views ------------------------------------------------------------
    def status(self) -> dict:
        return {n: self._payload(e) for n, e in self._entries.items()}

    def logs(self, node: str, n: int) -> list[str]:
        entry = self._entries[node]
        entry.log.read_new()
        return entry.log.tail(n)

    def entry(self, node: str):
        return self._entries[node]

    # ---- persistence ------------------------------------------------------
    def adopt_from_state(self) -> list[str]:
        try:
            with open(state_path(self._cfg.home)) as f:
                nodes = json.load(f).get("nodes", {})
        except (OSError, json.JSONDecodeError):
            return []
        adopted = []
        for node, rec in nodes.items():
            ticks = _proc_start_ticks(rec["pid"])
            if ticks is None or rec["proc_start"] is None \
                    or ticks != rec["proc_start"]:
                continue                       # dead, or a recycled pid
            log = NodeLog(self._cfg.log_dir, node,
                          self._cfg.ring_lines, self._cfg.keep_runs)
            log.attach_latest()
            try:
                self._entries[node] = pr.AdoptedProcess(
                    rec["spec"], self._cfg, log, self._on_state,
                    pid=rec["pid"], started_at=rec["started_at"])
            except OSError:                    # died between check and pidfd
                continue
            adopted.append(node)
        self._persist()
        return adopted

    def _on_state(self, proc) -> None:
        self._persist()
        self._on_event(proc.spec["node"], self._payload(proc))

    def _payload(self, e) -> dict:
        return {"node": e.spec["node"], "state": e.state, "pid": e.pid,
                "exit_code": e.exit_code, "started_at": e.started_at,
                "adopted": getattr(e, "adopted", False), "spec": e.spec}

    def _persist(self) -> None:
        live = {}
        for node, e in self._entries.items():
            if e.pid is None or e._exited.is_set():
                continue
            if e.state in (pr.STOPPED, pr.CRASHED):
                continue
            ticks = _proc_start_ticks(e.pid)
            if ticks is None:                  # already gone: not live
                continue
            live[node] = {"spec": e.spec, "pid": e.pid,
                          "started_at": e.started_at,
                          "proc_start": ticks}
        os.makedirs(self._cfg.home, exist_ok=True)
        path = state_path(self._cfg.home)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"nodes": live}, f)
        os.replace(tmp, path)                  # atomic on POSIX
