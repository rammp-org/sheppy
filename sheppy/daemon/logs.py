"""Per-node log files and the in-memory ring-buffer view. stdlib only.

Children write straight into the run file (they get the fd at spawn);
sheppyd never sits between a child and its output. The ring buffer is a
tail-view rebuilt by incremental reads of that file."""
import os
import time
from collections import deque


class NodeLog:
    def __init__(self, log_dir: str, node: str, ring_lines: int,
                 keep_runs: int) -> None:
        self._dir = os.path.join(log_dir, node)
        self._ring_lines = ring_lines
        self._keep_runs = keep_runs
        self._ring: deque = deque(maxlen=ring_lines)
        self._offset = 0
        self._partial = b""
        self.path: "str | None" = None

    def open_run(self) -> int:
        os.makedirs(self._dir, exist_ok=True)
        self._prune(self._keep_runs - 1)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        suffix = f"{time.time_ns() % 1_000_000:06d}"   # uniquify fast restarts
        self.path = os.path.join(self._dir, f"{stamp}-{suffix}.log")
        self._ring.clear()
        self._offset = 0
        self._partial = b""
        return os.open(self.path,
                       os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)

    def attach_latest(self) -> bool:
        runs = self._runs()
        if not runs:
            return False
        self.path = runs[-1]
        size = os.path.getsize(self.path)
        with open(self.path, "rb") as f:
            f.seek(max(0, size - 64 * 1024))     # tail window is plenty
            lines = f.read().decode(errors="replace").splitlines()
        self._ring.clear()
        self._ring.extend(lines[-self._ring_lines:])
        self._offset = size
        self._partial = b""
        return True

    def read_new(self) -> list[str]:
        if not self.path:
            return []
        try:
            with open(self.path, "rb") as f:
                f.seek(self._offset)
                data = f.read()
        except OSError:
            return []
        self._offset += len(data)
        data = self._partial + data
        *complete, self._partial = data.split(b"\n")
        lines = [c.decode(errors="replace") for c in complete]
        self._ring.extend(lines)
        return lines

    def tail(self, n: "int | None" = None) -> list[str]:
        lines = list(self._ring)
        return lines if n is None else lines[-n:]

    def _runs(self) -> list[str]:
        if not os.path.isdir(self._dir):
            return []
        return sorted(os.path.join(self._dir, f)
                      for f in os.listdir(self._dir) if f.endswith(".log"))

    def _prune(self, keep: int) -> None:
        runs = self._runs()
        for stale in runs[:max(0, len(runs) - keep)] if keep >= 0 else runs:
            try:
                os.unlink(stale)
            except OSError:
                pass
