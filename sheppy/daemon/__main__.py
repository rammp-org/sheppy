"""sheppyd: take the single-instance lock, adopt survivors, serve."""
import asyncio
import fcntl
import os
import signal
import sys
import time

from sheppy.daemon.config import (
    daemon_log_path, load_config, lock_path, sheppy_home,
)
from sheppy.daemon.server import Server


def _log(cfg, text: str) -> None:
    os.makedirs(cfg.log_dir, exist_ok=True)
    with open(daemon_log_path(cfg), "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")


async def _amain(cfg, warnings) -> None:
    server = Server(cfg)
    adopted = server.table.adopt_from_state()
    await server.start()
    for w in warnings:
        _log(cfg, f"config: {w}")
    _log(cfg, f"started (adopted: {', '.join(adopted) or 'none'})")
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, server._shutdown.set)
    await server.wait_shutdown()
    await server.close()
    _log(cfg, "shut down (children left running)")


def main(argv: "list[str] | None" = None) -> int:
    home = sheppy_home()
    os.makedirs(home, mode=0o700, exist_ok=True)
    cfg, warnings = load_config(home)
    lock = open(lock_path(home), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("sheppyd: already running", file=sys.stderr)
        return 1
    asyncio.run(_amain(cfg, warnings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
