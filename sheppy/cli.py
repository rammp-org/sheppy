"""Entry point: `sheppy <manifest>` opens the TUI; verbs (up/down/status/
logs/restart/daemon) are headless and never import textual."""
import argparse
import asyncio
import os
import sys
import time

COMMANDS = {"up", "down", "status", "logs", "restart", "woof", "daemon"}
VERSION_FLAGS = {"--version", "-V"}
HELP_FLAGS = {"--help", "-h"}

DEFAULT_MANIFEST = "sheppy-manifest.yaml"

# ANSI colors for the headless verbs (#39): plain escape codes, no rich.
_ANSI = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33"}
# Same colors the TUI gives each state (sheppy/tui/widgets/status.py).
_STATE_STYLE = {"running": "green", "launching": "yellow",
                "stopping": "yellow", "crashed": "red", "stopped": "dim"}
_ACTION_STYLE = {"start": "green", "restart": "yellow", "stop": "yellow"}


def _style(text: str, style: "str | None", stream=None) -> str:
    """Wrap text in an ANSI color, but only for a terminal with NO_COLOR
    unset, so pipes and redirects get plain text."""
    stream = sys.stdout if stream is None else stream
    if style is None or os.environ.get("NO_COLOR") or not stream.isatty():
        return text
    return f"\033[{_ANSI[style]}m{text}\033[0m"


def _warn(msg: str) -> None:
    print(f"{_style('warning:', 'yellow', sys.stderr)} {msg}", file=sys.stderr)


def _error(msg: str) -> None:
    print(_style(msg, "red", sys.stderr), file=sys.stderr)


def _warn_stale_daemon(client) -> None:
    msg = client.version_mismatch()
    if msg:
        print(f"sheppy: {msg}", file=sys.stderr)


# ---- TUI path (unchanged behavior) ----------------------------------------
def build_app(argv: list[str]):
    from sheppy.manifest import load_manifest
    from sheppy.tui.app import SheppyApp
    path = argv[0] if argv else DEFAULT_MANIFEST
    result = load_manifest(path)
    profiles_dir = os.path.join(os.path.dirname(os.path.abspath(path)),
                                "profiles")
    return SheppyApp(result, path=path, profiles_dir=profiles_dir)


def main(argv: "list[str] | None" = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in VERSION_FLAGS:
        from sheppy import __version__
        print(f"sheppy {__version__}")
        return 0
    if argv and argv[0] in HELP_FLAGS:    # else it's taken as a manifest (#76)
        _build_parser().print_help()
        return 0
    if argv and argv[0] in COMMANDS:
        return _run_verb(argv)
    app = build_app(argv)
    if app.manifest is None:            # nothing to browse, so say why (#27)
        for e in app.load_result.errors:
            _error(f"sheppy: {e.message}")
        return 1
    app.run()
    return 0


# ---- headless verbs --------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sheppy",
        usage="sheppy [MANIFEST]\n       sheppy <verb> [...]\n       sheppy --version\n       sheppy --help",
        description="With a manifest path (or nothing) sheppy opens the TUI; "
                    f"MANIFEST defaults to ./{DEFAULT_MANIFEST}. With a verb "
                    "it runs headless.")
    sub = p.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up", help="converge to a profile")
    up.add_argument("profile")
    up.add_argument("--manifest", default=DEFAULT_MANIFEST)
    sub.add_parser("down", help="stop everything, then stop sheppyd")
    sub.add_parser("status", help="one line per supervised node")
    lg = sub.add_parser("logs", help="tail a node's output")
    lg.add_argument("node")
    lg.add_argument("-n", type=int, default=50)
    rs = sub.add_parser("restart", help="restart a node")
    rs.add_argument("node")
    dm = sub.add_parser("daemon", help="daemon lifecycle")
    dm.add_argument("action", choices=["status", "stop"])
    return p


def _run_verb(argv: list[str]) -> int:
    if argv[0] == "woof":                # restart's old name (#21)
        argv = ["restart", *argv[1:]]
    args = _build_parser().parse_args(argv)
    from sheppy.daemon.client import DaemonError
    try:
        return asyncio.run(_dispatch(args))
    except DaemonError as e:            # sheppyd died mid-command (#99)
        _error(f"sheppy: sheppyd: {e}")
        return 1
    except KeyboardInterrupt:
        return 130


async def _dispatch(args) -> int:
    if args.cmd == "up":
        return await _up(args)
    from sheppy.daemon.client import DaemonClient
    client = DaemonClient()
    if not await client.connect(spawn=False):
        print(f"sheppyd: {_style('not running', 'dim')}")
        return 0 if args.cmd in ("down", "status", "daemon") else 1
    _warn_stale_daemon(client)
    try:
        if args.cmd == "down":
            nodes = (await client.request("status"))["nodes"]
            await asyncio.gather(*(client.request("stop", node=n)
                                   for n in nodes))
            for node in sorted(nodes):
                print(f"{_style('stopped', 'dim')} {node}")
            await client.request("shutdown")
            print("sheppyd stopped")
            return 0
        if args.cmd == "status":
            _print_status((await client.request("status"))["nodes"])
            return 0
        if args.cmd == "logs":
            reply = await client.request("logs", node=args.node, n=args.n)
            if not reply["ok"]:
                _error(reply["error"])
                return 1
            for line in reply["lines"]:
                print(line)
            return 0
        if args.cmd == "restart":
            reply = await client.request("restart", node=args.node)
            if not reply["ok"]:
                _error(reply["error"])
                return 1
            print(f"{_style('restarted', 'yellow')} {args.node}")
            return 0
        # daemon status|stop
        if args.action == "status":
            nodes = (await client.request("status"))["nodes"]
            print(f"sheppyd: {_style('running', 'green')} "
                  f"({len(nodes)} nodes supervised)")
            return 0
        await client.request("shutdown")
        print("sheppyd stopped (children left running)")
        return 0
    finally:
        await client.close()


def _print_status(nodes: dict) -> None:
    if not nodes:
        print("(nothing supervised)")
        return
    for node, p in sorted(nodes.items()):
        extra = ""
        if p["state"] == "crashed" and p["exit_code"] is not None:
            extra = " " + _style(f"exit={p['exit_code']}", "red")
        elif p["started_at"] and p["state"] == "running":
            extra = " " + _style(
                f"up {int(time.time() - p['started_at'])}s", "dim")
        # pad before styling so the escape codes don't skew the columns
        name = _style(f"{node:<20}", "bold")
        state = _style(f"{p['state']:<10}", _STATE_STYLE.get(p["state"]))
        pid = _style(f"pid={p['pid']}", "dim")
        print(f"{name} {state} {p['spec']['alt_id']:<14} {pid}{extra}")


async def _up(args) -> int:
    from sheppy.daemon.client import DaemonClient
    from sheppy.launch import diff, resolve
    from sheppy.manifest import load_manifest
    from sheppy.profiles import ProfileState, ProfileStore, reconcile

    result = load_manifest(args.manifest)
    if result.manifest is None:
        for e in result.errors:
            _error(f"{e.location}: {e.message}")
        return 1
    for e in result.errors:
        _warn(f"{e.location}: {e.message}")
    profiles_dir = os.path.join(
        os.path.dirname(os.path.abspath(args.manifest)), "profiles")
    loaded = ProfileStore(profiles_dir).load(args.profile)
    if loaded.profile is None:
        for err in loaded.errors:
            _error(str(err))
        return 1
    rec = reconcile(loaded.profile, result.manifest)
    for w in rec.warnings:
        _warn(w)
    state = ProfileState(result.manifest)
    state.apply(rec.selections, rec.overrides, args.profile)

    desired, unresolved = {}, set()
    for node in result.manifest.nodes:
        alt = state.selected_alt(node.name)
        if alt is None:
            continue
        spec, warns = resolve(result.manifest, node.name, alt,
                              state.effective_params(node.name),
                              manifest_dir=os.path.dirname(
                                  os.path.abspath(args.manifest)))
        for w in warns:
            _warn(w)
        if spec is None:
            # Absent from `desired` would read as "stop it" (#98): keep
            # the node out of the diff entirely so it is left as it is.
            _error(f"{node.name}: left as is, launcher failed to resolve")
            unresolved.add(node.name)
            continue
        desired[node.name] = spec

    from sheppy.daemon.config import sheppy_home, socket_path_error
    reason = socket_path_error(sheppy_home())
    if reason:                          # the daemon couldn't bind it (#35)
        _error(f"could not start sheppyd: {reason}")
        return 1
    client = DaemonClient()
    if not await client.connect(spawn=True):
        _error("could not start sheppyd")
        return 1
    _warn_stale_daemon(client)
    try:
        nodes = (await client.request("status"))["nodes"]
        actual = {n: p for n, p in nodes.items()
                  if result.manifest.node(n) is not None    # orphans untouched
                  and n not in unresolved}
        actions = diff(desired, actual)
        if not actions:
            print(_style("already converged", "green"))
            return 1 if unresolved else 0
        for verb, node in actions:
            print(f"{_style(verb, _ACTION_STYLE.get(verb))} {node}")
        # start and restart both go through launch: the daemon replaces a
        # live process of the same node with the NEW spec. All actions run
        # at once (#48); diff() never yields two for the same node.
        replies = await asyncio.gather(*(
            client.request("stop", node=node) if verb == "stop"
            else client.request("launch", spec=desired[node].to_wire())
            for verb, node in actions))
        rejected = False                    # e.g. the command couldn't exec (#97)
        for (_, node), reply in zip(actions, replies):
            if not reply["ok"]:
                _error(f"{node}: {reply['error']}")
                rejected = True
        rc = await _wait_stable(client, desired)
        return 1 if (rejected or unresolved) else rc
    finally:
        await client.close()


async def _wait_stable(client, desired: dict, timeout: float = 30.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        nodes = (await client.request("status"))["nodes"]
        states = {n: nodes.get(n, {}).get("state") for n in desired}
        if not any(s in ("launching", "stopping") for s in states.values()):
            for n in sorted(states):
                style = _STATE_STYLE.get(states[n])
                print(f"{n}: {_style(str(states[n]), style)}")
                if states[n] == "crashed":  # its dying words, if any
                    reply = await client.request("logs", node=n, n=1)
                    for line in reply.get("lines") or []:
                        if line.strip():
                            print(f"  {_style(line, 'dim')}")
            # Every desired node was started, restarted, or already running,
            # so anything but `running` (crashed, stopped, absent) is a
            # failure (#97).
            return 0 if all(s == "running" for s in states.values()) else 1
        await asyncio.sleep(0.2)
    _error("timed out waiting for nodes to settle")
    return 1
