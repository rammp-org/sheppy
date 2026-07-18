"""CPU%% and RSS per process group, from /proc. stdlib only.

Called only while a client is subscribed — sampling is the single
periodic cost sheppyd ever incurs, and it's off when nobody watches."""
import os
import time

_CLK = os.sysconf("SC_CLK_TCK")
_PAGE = os.sysconf("SC_PAGESIZE")


def _scan() -> dict:
    """pgid -> [cpu_ticks_total, rss_pages_total] over all live processes."""
    by_pgid: dict = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", "rb") as f:
                after = f.read().rsplit(b")", 1)[1].split()
            pgrp = int(after[2])               # stat field 5
            ticks = int(after[11]) + int(after[12])   # utime + stime
            with open(f"/proc/{entry}/statm", "rb") as f:
                rss_pages = int(f.read().split()[1])
        except (OSError, ValueError, IndexError):
            continue                           # process vanished mid-read
        acc = by_pgid.setdefault(pgrp, [0, 0])
        acc[0] += ticks
        acc[1] += rss_pages
    return by_pgid


def sample(pgids: dict, prev: dict) -> "tuple[dict, dict]":
    by_pgid = _scan()
    now = time.monotonic()
    usage: dict = {}
    new_prev: dict = {}
    for node, pgid in pgids.items():
        if pgid not in by_pgid:
            continue
        ticks, pages = by_pgid[pgid]
        cpu = 0.0
        if node in prev:
            prev_ticks, prev_now = prev[node]
            dt = now - prev_now
            if dt > 0:
                cpu = max(0.0, (ticks - prev_ticks) / _CLK / dt * 100)
        new_prev[node] = (ticks, now)
        usage[node] = {"cpu_pct": round(cpu, 1),
                       "rss_mb": round(pages * _PAGE / 1048576, 1)}
    return usage, new_prev
