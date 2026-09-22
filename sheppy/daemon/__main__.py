"""sheppyd: take the single-instance lock, adopt survivors, serve."""
import argparse
import asyncio
import fcntl
import os
import signal
import sys
import traceback

from sheppy.daemon.config import (
    daemon_log, load_config, lock_path, sheppy_home, socket_path_error,
)
from sheppy.daemon.server import Server


def _log_unhandled(cfg, context: dict) -> None:
    # Background tasks (_watch, reattach, _usage_loop) have no request to
    # reply to; without this their tracebacks went to stderr, i.e. nowhere.
    text = context.get("message") or "unhandled exception"
    exc = context.get("exception")
    if exc is not None:
        text += "\n" + "".join(traceback.format_exception(exc))
    daemon_log(cfg, text)


async def _amain(cfg, warnings) -> None:
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda loop, ctx: _log_unhandled(cfg, ctx))
    server = Server(cfg)
    adopted = server.table.adopt_from_state()
    await server.start()
    for w in warnings:
        daemon_log(cfg, f"config: {w}")
    daemon_log(cfg, f"started (adopted: {', '.join(adopted) or 'none'})")
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, server._shutdown.set)
    await server.wait_shutdown()
    await server.close()
    daemon_log(cfg, "shut down (children left running)")


def main(argv: "list[str] | None" = None) -> int:
    argparse.ArgumentParser(
        prog="sheppyd",
        description="Run the sheppy daemon in the foreground. sheppy up "
                    "starts it for you; see `sheppy --help`.").parse_args(argv)
    home = sheppy_home()
    os.makedirs(home, mode=0o700, exist_ok=True)
    cfg, warnings = load_config(home)
    err = socket_path_error(home)
    if err:
        print(f"sheppyd: {err}", file=sys.stderr)
        daemon_log(cfg, err)
        return 1
    lock = open(lock_path(home), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("sheppyd: already running", file=sys.stderr)
        return 1
    try:
        asyncio.run(_amain(cfg, warnings))
    except Exception as e:                 # died: say so where it can be read
        daemon_log(cfg, "died\n" + "".join(traceback.format_exception(e)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
