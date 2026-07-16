# Sheppy Phase 2b: `sheppyd` + Local Launch — Design

Date: 2026-07-16
Status: Approved design (brainstormed with user; paradigm exploration + rosmon/nav2 gap analysis)

## 1. Overview and goals

Phase 2b turns sheppy from a catalog/profile editor into an operator console: a
local supervisor daemon (`sheppyd`) that spawns, watches, stops, and restarts
the processes behind the manifest's nodes, and reports live status to the TUI
and CLI.

Governing constraint (user, verbatim): *"This needs to be super light-weight.
It's going to be running on a system that is resource starved. It should do
its job, get out of the way, and be very stable. It will be handling running
the whole system after all!"*

Goals:

- Launch/stop/restart individual nodes and converge to whole profiles, locally.
- Live per-node status (launching / running / stopping / crashed + exit code),
  log tails, and CPU/RAM usage in the existing cockpit UI slots.
- Headless operation: `sheppy up <profile>` works with no TUI.
- The system survives the TUI detaching, and survives `sheppyd` itself dying.
- Daemon: stdlib-only, zero idle CPU, bounded memory, auditable line-by-line.

## 2. Non-goals (out of scope for 2b)

- Multi-machine anything (phase 3). The `machine:` field on alternatives is
  **ignored** in 2b — every launch is local (user decision).
- Graph introspection, node-readiness checks, bond-style liveness (phase 4).
  `running` means *process alive*, nothing more.
- Auto-restart on crash. Crashes are flagged, never respawned (user decision);
  see §13 for the policy hook.
- Ordered bringup / dependencies between nodes (see §13).
- Adopting processes sheppy didn't start. They are invisible (documented
  limitation shared with rosmon/nav2-style supervisors).

## 3. State model: Desired vs Actual

Two independent layers per logical node, one screen (paradigm chosen by user
after a four-way exploration: terraform-style, mixing-desk, IDE run-config,
story-derived hybrid — the hybrid won):

- **Desired** — what the operator wants: chosen alternative + param overrides
  per node. Owned by the TUI/CLI session (today's `ProfileState`). Profiles
  are the Desired layer serialized to YAML — unchanged format.
- **Actual** — what is really running: state, pid, exit code, uptime, usage,
  and the exact `LaunchSpec` each process was launched with. Owned by
  `sheppyd`, mirrored read-only by clients.

Operations and their exact semantics:

| Operation | Effect on Desired | Effect on processes |
|---|---|---|
| pick alternative / edit params | updates it | none (`Δ` drift marker appears) |
| save / load profile | serialize / replace | **never any** |
| `Space` converge node | — | start/restart node to match Desired; stop it if Desired has no selection |
| `x` stop node / `r` restart node | — | that node only |
| `L` converge all | — | diff overlay → confirm → per-node actions |
| `X` stop all / `sheppy down` | — | stops everything sheppyd owns, orphans included |
| `!` snapshot | Desired := the running set | none |

Converge rules (client-side pure function `diff(desired, actual) → actions`):
start missing nodes, restart nodes whose running spec ≠ Desired, stop nodes
running without a Desired selection, **never touch a node that already
matches**. Used identically by the TUI overlay and `sheppy up`.

Snapshot (`!`): for each manifest node with a live process whose alternative
exists in the manifest, Desired takes the *actually launched* alternative +
params; nodes not running — crashed ones included — get their selection
cleared. Orphans (below) are
skipped with a visible warning. Then save-as captures "what's running now" —
the user's craft-a-profile-by-running-things flow.

### Orphans (running nodes unknown to the open manifest)

`sheppyd` outlives TUI sessions, so the TUI may connect and find processes
whose node names aren't in the currently open manifest. Reality is always
shown: such nodes render at the bottom of the node list under a muted
`─ not in this manifest ─` divider, as Actual-only rows (glyph, name, alt id,
straight from the daemon's spec echo). `x` and logs work (they only need the
node name); `Space` and `!` don't apply. **Converge-all leaves orphans
running** (user decision) — only `X`/`sheppy down` stops them. A running
*alternative id* unknown to the manifest (same node name) is a normal row
with an "unknown alt" badge and `Δ`.

## 4. Architecture: dumb daemon, smart client

```
sheppy TUI ──┐                             ┌─────────────────────────────┐
             ├── client lib ──── unix ─────│ sheppyd                     │
sheppy CLI ──┘   (resolver +    socket     │  process table + spawner    │
                  protocol)     NDJSON     │  stdlib only; no yaml, no   │
                                           │  manifest, no textual       │
                                           └─────────────────────────────┘
```

The load-bearing decision: **`sheppyd` never sees a manifest, profile, or
YAML.** Clients resolve everything to a `LaunchSpec`; the daemon is a dumb,
durable process table. Consequences: stdlib-only imports (not even PyYAML),
manifest schema evolution never touches the daemon, trivially testable
without ROS, and `kind → command` resolution stays client-side — which is
exactly where the future launcher/capability plugin split wants it.

`LaunchSpec` (JSON object, stored and echoed verbatim by the daemon):

```json
{
  "node": "camera",
  "alt_id": "realsense",
  "argv": ["bash", "-c", "source /opt/ros/humble/setup.bash && exec ros2 run ..."],
  "params": {"pointcloud.enable": true}
}
```

`argv` is final — the daemon runs exactly `Popen(argv)`. `params` is
echo-only (display). The resolver (client-side) builds `argv`:

| kind | command inside `bash -c` |
|---|---|
| `executable` | `exec ros2 run <pkg> <exe> --ros-args -p k:=v ...` |
| `launch_file` | `exec ros2 launch <pkg> <file> k:=v ...` |
| `process` | `<command>` verbatim (no `exec` — the command may be a pipeline; the process group covers the tree) |

If the machine's `ros_setup` is set, `source <ros_setup> && ` is prefixed.
Params on `process`-kind alternatives are warned-and-ignored in 2b.

## 5. `sheppyd` internals

- **One process, one thread, one asyncio event loop.** Purely event-driven:
  unix-socket traffic and child-exit events. No timers exist while no client
  is subscribed → **zero idle CPU**.
- **Spawning:** `Popen(argv, start_new_session=True, stdout=log_fd,
  stderr=log_fd, stdin=DEVNULL)`. Each child leads its own process group.
- **Child output goes directly to its log file, never through a pipe into
  the daemon.** This is a stability invariant: if the daemon holds the pipe
  and dies, children take SIGPIPE on their next write — the supervisor's
  crash would kill the robot. With a file fd, daemon death is invisible to
  children. The ring buffer is a *view*: the daemon tails each file
  (tracked offset), reading only on demand — on subscriber ticks, on a
  `logs` request, and on child exit (to capture dying words).
- **Launching → running:** a spawned node is `launching` until it survives
  `launch_grace` (default 2 s); exiting within the grace ⇒ `crashed`
  (catches bad-package-name instant failures visibly).
- **Stop escalation:** SIGINT to the process group (`ros2 launch` shuts down
  cleanly on SIGINT), SIGTERM after `stop_grace` (5 s), SIGKILL after
  `kill_grace` (5 s more). State `stopping` while in progress.
- **Crash handling:** child exit without a stop request ⇒ `crashed`, exit
  code (or signal) recorded, ring buffer frozen, log file preserved. All
  exits flow through a single `_on_exit(entry)` policy point so per-node
  lifecycle config (auto-restart etc.) can drop in later without surgery.
- **Resource usage (rosmon-inspired, user-approved):** while ≥1 client is
  subscribed, a 2 s tick (`usage_interval`) scans `/proc`, sums RSS and
  CPU-time deltas over each child's process group, and attaches
  `{cpu_pct, rss_mb}` to status events. No subscribers ⇒ no tick.
- **Core dumps (rosmon-inspired, user-approved):** `coredumps: true` raises
  `RLIMIT_CORE` to unlimited in the child (via `preexec_fn`); crash status
  reports where cores land. Default false.
- **Logging:** always to files (they are the crash-safe sink):
  `<log_dir>/<node>/<timestamp>.log`, one per launch, so "restart perception
  30×" gives 30 tidy files; `keep_runs` (default 5) prunes old ones per
  node. Ring buffer keeps the last `ring_lines` (default 300) lines per node
  in memory, hard-capped. Known limitation (documented): a single run's
  file is uncapped — same behavior as `ros2 launch`.
- **Survivability / re-adoption:** the process table is mirrored to
  `~/.sheppy/sheppyd.state.json` (atomic tmp+rename) on every change. On
  startup, entries whose pid still exists *and* whose `/proc` start-time
  matches are re-adopted: status, stop, restart, and usage keep working;
  their ring buffers rebuild from the log-file tail. Stale entries are
  dropped. Daemon death therefore loses nothing but live subscriptions.
- **Config:** flat JSON at `~/.sheppy/sheppyd.json`, read once at startup,
  all keys optional: `log_dir`, `ring_lines`, `keep_runs`, `coredumps`,
  `usage_interval`, `launch_grace`, `stop_grace`, `kill_grace`. JSON (not
  YAML) because the daemon has no YAML parser by design; the file is flat,
  plain-word keys, defaults documented in the README. (User asked for
  configs "easy to parse/understand" — one flat file, no nesting, no env-var
  maze.)
- **Socket & identity:** `$XDG_RUNTIME_DIR/sheppy/sheppyd.sock`, falling
  back to `~/.sheppy/sheppyd.sock`; directory mode 0700, socket 0600.
  Single instance enforced with an `fcntl.flock` lock file; a dead socket
  file is removed and replaced.
- **Auto-spawn (user decision):** any client that can't connect takes the
  spawn lock, launches `[sys.executable, "-m", "sheppy.daemon"]` detached
  (`start_new_session=True`, stdio → `<log_dir>/sheppyd.log`), and waits up
  to ~3 s for the socket. `sheppy daemon stop` shuts it down.

## 6. Protocol

Newline-delimited JSON (NDJSON) over the unix socket — debuggable with
`nc -U`. On connect the server sends
`{"event": "hello", "sheppyd": "<version>", "protocol": 1}`.

Requests carry `id`; responses echo it: `{"id": 3, "op": "launch",
"spec": {...}}` → `{"id": 3, "ok": true}` or `{"id": 3, "ok": false,
"error": "..."}`.

| op | args | effect |
|---|---|---|
| `launch` | `spec` | spawn (stops a different running alt of the same node first — invariant: ≤1 process per node) |
| `stop` | `node` | begin stop escalation |
| `restart` | `node` | stop, then relaunch the same spec |
| `status` | — | full table: per node `{state, pid, exit_code, started_at, usage, spec}` |
| `logs` | `node`, `n` | last *n* ring-buffer lines |
| `subscribe` | — | this connection receives pushed events until it closes |
| `shutdown` | — | daemon exits; children keep running (the state file lets the next daemon re-adopt them). `sheppy down` = stop-all *then* shutdown. |

Pushed events: `{"event": "status", "node": ..., "state": ..., "pid": ...,
"exit_code": ..., "usage": {...}}` on every change plus usage ticks.

Errors never kill the daemon: every connection is wrapped; malformed JSON
gets an error reply; an unknown op gets an error reply; a client vanishing
mid-request is a non-event.

## 7. Client library

`sheppy/daemon/client.py` — async `DaemonClient` used by both TUI and CLI:
connect (with auto-spawn), request/response, event subscription with
reconnect-and-resync backoff. `sheppy/launch/resolve.py` — pure functions:
`resolve(manifest, node, alt, params) → LaunchSpec` and
`diff(desired, actual) → [actions]`.

## 8. CLI verbs

- `sheppy <manifest>` — the TUI, as today.
- `sheppy up <profile> [--manifest PATH]` — resolve, print the action list,
  converge, stream status until stable; exit non-zero if anything crashed.
- `sheppy down` — stop everything, then stop the daemon.
- `sheppy status` — one line per node from the daemon table.
- `sheppy logs <node> [-n N]` — ring-buffer tail.
- `sheppy woof <node>` — restart it. 🐕
- `sheppy daemon status|stop` — daemon lifecycle.

Manifest defaults to `./system.yaml`; profiles resolve from `profiles/` next
to the manifest, as today.

## 9. TUI changes

- **Node rows:** the status glyph column goes live — ○ stopped / ◐ launching
  or stopping / ● running / ✖ crashed (glyphs already reserved in
  `status.py`) — plus a `Δ` drift marker when the running spec ≠ Desired and
  a compact usage readout (e.g. `3% 142M`) while connected.
- **Keys:** `Space` converge node · `x` stop · `r` restart · `L` converge
  all (diff overlay: `start 2 · restart 1 · stop 1`, Enter/Esc) · `X` stop
  all (confirm) · `!` snapshot. Existing keys unchanged. Footer hints
  `Δ space to apply` when drift exists.
- **PROCESS tab goes live:** state, pid, uptime, exit code, cpu/rss, log
  tail (refreshed from status events + a 1 s timer only while the tab is
  visible).
- **Header:** running count (`● 4/12`). **Footer:** `sheppyd ● connected` /
  `○ offline`.
- **Daemon absent:** Actual column renders grey `?` glyphs — visually
  distinct from "all stopped" — and every 2a feature (browse, edit, save,
  load) works exactly as today. The TUI never blocks on the daemon.
- **Orphan rows** as in §3.
- Never-crash ethos holds: daemon errors and disconnects render as status,
  never exceptions.

## 10. Package layout

```
sheppy/daemon/            stdlib-only (enforced by test)
  __main__.py             entry point (sheppyd console script too)
  server.py               socket accept/dispatch loop
  table.py                process table + states + state file
  process.py              spawn / signal escalation / reap
  logs.py                 log files, offsets, ring buffers, pruning
  usage.py                /proc sampling per process group
  config.py               flat-JSON config with defaults
  protocol.py             message encode/decode (shared with client)
  client.py               async DaemonClient + auto-spawn (client side)
sheppy/launch/
  resolve.py              LaunchSpec resolver + converge diff (pure)
```

`pyproject.toml` gains `sheppyd = "sheppy.daemon.__main__:main"`.

## 11. Testing strategy

No ROS anywhere in tests — the daemon only knows `argv`, so children are
plain `python3 -c` scripts:

- **Daemon integration (the core suite):** start a real daemon on a temp
  socket; launch/stop/restart/crash real child processes; assert states,
  exit codes, ring buffers, log files, state-file re-adoption (kill daemon,
  restart, re-adopt), stop escalation (child that ignores SIGINT), orphan
  reporting. Event-driven waits, not sleeps.
- **Resolver:** pure-function tests for every kind × params × ros_setup
  combination, and converge `diff()` truth tables (incl. orphans).
- **Protocol:** malformed JSON, unknown ops, mid-request disconnects — the
  daemon must answer errors and stay up.
- **Stdlib purity:** a test imports `sheppy.daemon.*` and asserts no
  third-party module (textual, yaml, rich, …) lands in `sys.modules`.
- **TUI:** existing pilot harness + a fake `DaemonClient` injected; tests
  for glyph rendering, `Δ`, orphan rows, diff overlay, daemon-absent grey
  state.
- **End-to-end (one test):** auto-spawn daemon → `sheppy up` a toy profile
  → status shows running → crash one → ✖ + exit code → `sheppy down`.

## 12. Lightweight budget (success criteria)

- `sheppyd` RSS < 35 MB with 12 idle children under supervision.
- Idle CPU (no subscribers): 0% — verifiable with `pidstat`; no periodic
  timers exist in that state.
- Stdlib-only import set for `sheppy/daemon/` (tested).
- A crashed daemon loses no processes and a restarted daemon re-adopts them.

## 13. Forward compatibility

- **Lifecycle policy (user request):** all child exits route through one
  `_on_exit` hook; a later per-alternative `lifecycle:`/`restart:` manifest
  field plugs in there. Not in 2b's schema (only one legal value today).
- **Ordered bringup (nav2 lesson):** converge is "compute action list →
  execute"; a later `after:` field orders the execute step. No redesign.
- **Readiness ≠ aliveness (lifecycle-nodes lesson):** `running` is
  process-level; WARN glyph and the status vocabulary leave room for a
  phase-4 readiness check (graph/bond/lifecycle-state) to refine status
  without touching the daemon.
- **Launcher/capability plugins (memory: sheppy-plugin-capability-direction):**
  kind→argv resolution is already client-side and pure; a plugin registry
  can replace the `kind` dispatch table without daemon changes.
- **Phase 3:** the protocol is transport-agnostic NDJSON; pointing the
  client at a TCP/SSH-forwarded stream instead of a unix socket is the
  planned extension, and `machine:` awareness lands in the converge diff.

## 14. Decisions log (from brainstorm)

- Auto-spawn daemon on demand; `sheppy daemon stop` to end it.
- Desired/Actual hybrid model; load/save never touch processes; per-node
  actions immediate; whole-profile converge shows a diff first.
- Crash ⇒ flag only (✖ + exit code); no auto-restart in 2b.
- Logs: ros2-launch-like (files + live tail) with a flat, readable config.
- `machine:` ignored in 2b.
- Converge-all leaves orphans; only `X`/`down` stops them.
- Adopt from rosmon: per-node CPU/RAM usage, core-dumps flag.
