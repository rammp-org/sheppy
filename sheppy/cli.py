"""Entry point: `sheppy <manifest>` opens the TUI; verbs (up/down/status/
logs/woof/daemon) are headless and never import textual."""
import argparse
import asyncio
import os
import sys
import time

COMMANDS = {"up", "down", "status", "logs", "woof", "daemon"}
VERSION_FLAGS = {"--version", "-V"}


# ---- TUI path (unchanged behavior) ----------------------------------------
def build_app(argv: list[str]):
    from sheppy.manifest import load_manifest
    from sheppy.tui.app import SheppyApp
    path = argv[0] if argv else "system.yaml"
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
    if argv and argv[0] in COMMANDS:
        return _run_verb(argv)
    app = build_app(argv)
    app.run()
    return 0


# ---- headless verbs --------------------------------------------------------
def _run_verb(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="sheppy")
    sub = p.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up", help="converge to a profile")
    up.add_argument("profile")
    up.add_argument("--manifest", default="system.yaml")
    sub.add_parser("down", help="stop everything, then stop sheppyd")
    sub.add_parser("status", help="one line per supervised node")
    lg = sub.add_parser("logs", help="tail a node's output")
    lg.add_argument("node")
    lg.add_argument("-n", type=int, default=50)
    wf = sub.add_parser("woof", help="restart a node")
    wf.add_argument("node")
    dm = sub.add_parser("daemon", help="daemon lifecycle")
    dm.add_argument("action", choices=["status", "stop"])
    args = p.parse_args(argv)
    return asyncio.run(_dispatch(args))


async def _dispatch(args) -> int:
    if args.cmd == "up":
        return await _up(args)
    from sheppy.daemon.client import DaemonClient
    client = DaemonClient()
    if not await client.connect(spawn=False):
        print("sheppyd: not running")
        return 0 if args.cmd in ("down", "status", "daemon") else 1
    try:
        if args.cmd == "down":
            nodes = (await client.request("status"))["nodes"]
            for node in sorted(nodes):
                await client.request("stop", node=node)
                print(f"stopped {node}")
            await client.request("shutdown")
            print("sheppyd stopped")
            return 0
        if args.cmd == "status":
            _print_status((await client.request("status"))["nodes"])
            return 0
        if args.cmd == "logs":
            reply = await client.request("logs", node=args.node, n=args.n)
            if not reply["ok"]:
                print(reply["error"], file=sys.stderr)
                return 1
            for line in reply["lines"]:
                print(line)
            return 0
        if args.cmd == "woof":
            reply = await client.request("restart", node=args.node)
            if not reply["ok"]:
                print(reply["error"], file=sys.stderr)
                return 1
            print(f"woof! restarted {args.node} 🐕")
            return 0
        # daemon status|stop
        if args.action == "status":
            nodes = (await client.request("status"))["nodes"]
            print(f"sheppyd: running ({len(nodes)} nodes supervised)")
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
            extra = f" exit={p['exit_code']}"
        elif p["started_at"] and p["state"] == "running":
            extra = f" up {int(time.time() - p['started_at'])}s"
        print(f"{node:<20} {p['state']:<10} "
              f"{p['spec']['alt_id']:<14} pid={p['pid']}{extra}")


async def _up(args) -> int:
    from sheppy.daemon.client import DaemonClient
    from sheppy.launch import diff, resolve
    from sheppy.manifest import load_manifest
    from sheppy.profiles import ProfileState, ProfileStore, reconcile

    result = load_manifest(args.manifest)
    if result.manifest is None:
        for e in result.errors:
            print(f"{e.location}: {e.message}", file=sys.stderr)
        return 1
    for e in result.errors:
        print(f"warning: {e.location}: {e.message}", file=sys.stderr)
    profiles_dir = os.path.join(
        os.path.dirname(os.path.abspath(args.manifest)), "profiles")
    loaded = ProfileStore(profiles_dir).load(args.profile)
    if loaded.profile is None:
        for err in loaded.errors:
            print(err, file=sys.stderr)
        return 1
    rec = reconcile(loaded.profile, result.manifest)
    for w in rec.warnings:
        print(f"warning: {w}", file=sys.stderr)
    state = ProfileState(result.manifest)
    state.apply(rec.selections, rec.overrides, args.profile)

    desired = {}
    for node in result.manifest.nodes:
        alt = state.selected_alt(node.name)
        if alt is None:
            continue
        spec, warns = resolve(result.manifest, node.name, alt,
                              state.effective_params(node.name),
                              manifest_dir=os.path.dirname(
                                  os.path.abspath(args.manifest)))
        for w in warns:
            print(f"warning: {w}", file=sys.stderr)
        if spec is None:
            continue
        desired[node.name] = spec

    client = DaemonClient()
    if not await client.connect(spawn=True):
        print("could not start sheppyd", file=sys.stderr)
        return 1
    try:
        nodes = (await client.request("status"))["nodes"]
        actual = {n: p for n, p in nodes.items()
                  if result.manifest.node(n) is not None}   # orphans untouched
        actions = diff(desired, actual)
        if not actions:
            print("already converged")
            return 0
        for verb, node in actions:
            print(f"{verb} {node}")
        for verb, node in actions:
            if verb == "stop":
                await client.request("stop", node=node)
            else:   # start and restart both go through launch: the daemon
                # replaces a live process of the same node with the NEW spec
                await client.request("launch", spec=desired[node].to_wire())
        return await _wait_stable(client, desired)
    finally:
        await client.close()


async def _wait_stable(client, desired: dict, timeout: float = 30.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        nodes = (await client.request("status"))["nodes"]
        states = {n: nodes.get(n, {}).get("state") for n in desired}
        if not any(s in ("launching", "stopping") for s in states.values()):
            for n in sorted(states):
                print(f"{n}: {states[n]}")
            return 1 if "crashed" in states.values() else 0
        await asyncio.sleep(0.2)
    print("timed out waiting for nodes to settle", file=sys.stderr)
    return 1
