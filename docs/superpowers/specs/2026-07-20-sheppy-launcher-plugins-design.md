# Sheppy: Launcher Plugins + Docker — Design

Date: 2026-07-20
Status: Approved design (brainstormed with user)

## 1. Overview and goals

Today Sheppy knows three ways to run a node — `executable`, `launch_file`,
`process` — and each is hard-coded in the client-side resolver
(`sheppy/launch/resolve.py`). The demo is moving into Docker, and more launch
types will follow. Rather than bolt on a Docker special case, this phase
introduces **a general, standardized launcher-plugin surface** that every
launch type — the existing ones included — is expressed through, and that
outside developers can extend to add their own launch types. **Docker is the
first non-trivial plugin** built on it.

Governing requirements (user, this session):

- One mechanism for every launch type — "I don't want a different mechanism
  for ROS/Docker/whatever comes next."
- A **standardized plugin surface** we can hand to developers so they add
  support for their own launch types.
- Docker nodes are first-class: correct container lifecycle (not orphaned on
  SIGKILL or daemon restart), reusing docker-compose config so there's nothing
  new to learn, and **ROS node parameters exposed in the Sheppy UI exactly as
  they are for every other kind**.

Non-goals for this phase are listed in §12.

### The load-bearing decision: declarative plugins, client-side

A launcher plugin is **not** code that runs inside the daemon. A plugin is a
function that returns **data** — a `LaunchDescriptor` — and it runs
**client-side** (in the TUI/CLI resolver). The daemon only ever executes the
descriptor; it never loads or runs third-party code.

This preserves Sheppy's core invariant: `sheppyd` supervises the whole robot,
so it must stay stdlib-only, auditable, and rock-stable. A buggy third-party
plugin can produce a bad descriptor (a launch that fails) but can never crash
the supervisor. It also keeps launch-type knowledge exactly where it already
lives — in the smart client — and keeps the dumb daemon dumb.

## 2. Architecture: three layers

```
  ┌─────────────────────────────────────────────┐
  │ Launcher plugins        (client-side)        │   extensible
  │  process · executable · launch_file · docker │   developers add here
  │  each: (alt, params, ctx) → LaunchDescriptor │
  └───────────────────────┬─────────────────────┘
                          │  LaunchDescriptor (JSON)   ← the one contract
                          ▼
  ┌─────────────────────────────────────────────┐
  │ sheppyd execution engine     (fixed, stdlib) │   never changes when
  │  runs a descriptor; knows no kind names      │   a launcher is added
  └─────────────────────────────────────────────┘
```

1. **Launcher plugins** — each owns one `kind`. A launcher validates an
   alternative's manifest fields and turns `(alternative, effective params,
   context)` into a `LaunchDescriptor`. This is the developer-facing surface.
2. **`LaunchDescriptor`** — pure, JSON-serializable data describing how to
   start, watch, stop, and read logs for a unit. It is the single interface
   between the client and the daemon, replacing today's bare `argv` on the
   wire.
3. **The daemon engine** — executes a descriptor. It gains no knowledge of
   Docker, ROS, or any kind name, and does not change when launchers are
   added or removed.

## 3. The `LaunchDescriptor`

One structure, two shapes chosen by `supervise`. All command fields are argv
lists (no shell), JSON-serializable.

```jsonc
{
  "supervise": "inherit" | "detached",
  "name": "sheppy-perception",          // detached: stable identity
  "start": ["...argv..."],              // both: command that brings the unit up
  "watch": ["...argv..."],              // detached: blocks until exit; stdout = exit code
  "poll":  ["...argv..."],              // detached alt to watch: liveness probe on an interval
  "stop":  ["...argv..."],              // detached: command that stops the unit
  "logs":  ["...argv..."],              // detached: follower streaming unit output
  "stats": ["...argv..."],              // detached, optional: one-shot sampler that
                                        //   prints exactly "<cpu_pct> <rss_mb>"
  "reset": ["...argv..."],              // detached, optional: pre-start cleanup
  "grace": { "launch": 2.0, "stop": 10.0 }   // optional per-unit overrides
}
```

### `inherit` — the started process *is* the unit

Only `start` is meaningful. The daemon runs `start` as a long-lived child,
watches its PID for exit, stops it with the existing SIGINT→SIGTERM→SIGKILL
escalation, and streams the child's own stdout/stderr to the log file. **This
is byte-for-byte today's process behavior.** `executable`, `launch_file`, and
`process` all emit `inherit` descriptors.

### `detached` — the unit outlives the starter

`start` is transient (e.g. `docker run -d` returns immediately). The daemon:

- runs `reset` (if present) then `start`; a non-zero `start` exit ⇒ the unit
  failed to launch (**crashed**);
- detects exit via **`watch`** — a blocking command whose own exit means the
  unit exited, and whose stdout carries the unit's exit code (e.g.
  `docker wait <name>`). `watch` is preferred because it costs **zero idle
  CPU** (it blocks, no polling). For runtimes without a blocking wait, a
  launcher may instead supply **`poll`** — a liveness command the daemon runs
  on a fixed poll interval while that unit is up (a bounded, per-running-node
  cost, only while it runs; exit code is then unavailable → `None`);
- streams `logs` (a follower like `docker logs -f`) into the node's existing
  `NodeLog`;
- stops via the `stop` command (the runtime performs its own signal
  escalation, e.g. `docker stop --time`);
- samples usage via `stats` if present, else usage is blank;
- re-adopts by **`name`** (see §6).

### Exactly one of `watch` / `poll`

A `detached` descriptor must supply `watch` or `poll`, not both and not
neither. Validation rejects a `detached` descriptor missing exit detection.

## 4. The Launcher contract (what a developer writes)

```python
class Launcher(Protocol):
    kind: str                                           # "docker", "process", ...

    def validate(self, raw_alt: dict) -> list[str]:
        """Manifest-time field validation; returns human-readable errors
        (empty = valid). Never raises."""

    def launch(self, alt: Alternative, params: dict,
               ctx: "LaunchContext") -> "LaunchDescriptor":
        """Turn a validated alternative + already-merged effective params
        into a descriptor. Pure except for side effects mediated by ctx."""

    def summary(self, alt: Alternative) -> list[tuple[str, str]]:
        """Optional: (label, value) rows for the DETAIL tab. Default []."""
```

`LaunchContext` mediates the side effects a launcher legitimately needs, so
plugins never do ad-hoc I/O:

```python
class LaunchContext:
    node_name: str
    manifest: Manifest                    # for machine ros_setup, etc.
    def scratch_dir(self) -> str: ...     # a per-node dir the launcher may write to
    def write_params_file(self, params: dict,
                          ros_node_name: str | None = None) -> str:
        """Write a ROS2 params YAML (keyed by ros_node_name or /**) and
        return its host path. Used by the docker launcher; available to any."""
```

Notes:

- `params` handed to `launch()` is the **effective** params (declared merged
  with profile overrides) — the launcher does not re-implement merging.
- A launcher is a small, pure-ish unit: given the same inputs it produces the
  same descriptor (side effects limited to `ctx`). This makes launchers
  golden-testable without a daemon, Docker, or ROS.

## 5. Discovery and the registry

Launchers register via Python **entry points**, group `sheppy.launchers`:

```toml
# a third-party package's pyproject.toml
[project.entry-points."sheppy.launchers"]
myruntime = "my_pkg.launcher:MyLauncher"
```

Sheppy's **built-in launchers register through the identical mechanism** (in
Sheppy's own `pyproject.toml`), so nothing is special-cased — `process` is
discovered exactly the way a third-party `myruntime` is. A `LauncherRegistry`
loads all entry points at client startup, maps `kind → Launcher`, and reports
a clear error for a manifest `kind` with no registered launcher.

Because a `LaunchDescriptor` is pure data, a future door stays open for
**language-agnostic** launchers (any executable that reads an alternative on
stdin and writes a descriptor on stdout). That path is documented as
forward-compat and **not built now** (YAGNI until a non-Python launcher
appears).

The registry lives client-side only. The daemon has no registry and no
launcher imports.

## 6. Daemon: the `detached` execution strategy

The Phase 2b daemon already has a `Supervised` base class with two
subclasses (`ManagedProcess`, `AdoptedProcess`). This phase adds a third
sibling, `DetachedSupervisor`, selected when the incoming descriptor's
`supervise == "detached"`. `inherit` descriptors continue to use
`ManagedProcess`. The daemon selects the strategy purely from the descriptor —
no kind names reach the daemon.

`DetachedSupervisor` lifecycle:

- **start**: run `reset` (best-effort), then `start`. Non-zero `start` ⇒
  `crashed`. On success, spawn the `logs` follower (→ `NodeLog`) and the
  `watch` process (or begin `poll` on `usage_interval`-style ticks).
- **launching → running**: same launch-grace rule as processes.
- **exit**: `watch` exiting (or a `poll` reporting dead) ⇒ `stopped` if a stop
  was requested, else `crashed`; the exit code comes from `watch` stdout when
  available (else `None`, as for adopted processes).
- **stop**: run `stop`; the `watch` then returns. State `stopping` meanwhile.
- **usage**: if `stats` is present and a client is subscribed, run it on the
  usage tick and read two whitespace-separated numbers (`cpu_pct rss_mb`) from
  its stdout; else blank. The daemon parser is fixed and generic — turning a
  runtime's native stats output into those two numbers is the launcher's job
  (e.g. the docker launcher wraps `docker stats` in a small reformatting
  command), so the daemon never learns any runtime's stat format.

**Identity and re-adoption.** A `detached` unit's identity is its `name`, not
a PID — more stable, with no recycling. The state file persists the descriptor
for live units (as it already persists specs). On daemon restart, for each
`detached` entry the daemon simply re-spawns `watch` (and `logs`) against the
`name`: if the unit is already gone, `watch` returns immediately (or errors →
treated as gone), resolving the node to stopped/crashed. This is *simpler*
than the process re-adoption path (no `/proc` start-ticks recycled-pid guard
needed).

**Zero-idle-CPU** is preserved: `watch` blocks rather than polls, and `stats`
runs only while a client is subscribed. The only new periodic cost is `poll`,
which exists solely for runtimes lacking a blocking wait and runs only while
that specific node is up.

**Stdlib-only** is preserved: the daemon shells out to whatever `start`/
`watch`/`stop`/`logs` name (e.g. `docker`) via `subprocess`; it imports
nothing new.

### Wire change

Today `LaunchSpec.to_wire()` sends `{node, alt_id, argv, params}`. It becomes
`{node, alt_id, params, descriptor}` where `descriptor` is §3. `params` stays
echo-only (for display). The daemon reads `descriptor.supervise` to pick a
strategy. The protocol's hello `protocol` version is bumped; the daemon
rejects a descriptor it cannot interpret with a clear error reply (never a
crash).

## 7. Built-in launchers (migration)

`process`, `executable`, and `launch_file` are rewritten as launchers emitting
`inherit` descriptors whose `start` argv is **identical to today's resolved
command** (`bash -c "<same command>"`, same `shlex` quoting, same params
handling, same `ros_setup` prefix). The current test suite — the resolver
tests and the end-to-end launch test — is the safety net: behavior is
preserved exactly; only the internal path changes (resolver → registry →
launcher). The old `resolve()` is refactored into the `process`/`executable`/
`launch_file` launchers plus shared helpers (`_param_token`, quoting).

This migration is what makes "one mechanism, no special case" true rather than
aspirational.

## 8. Docker launcher

The first non-trivial plugin, delivered as `kind: docker`.

### Manifest

Container config comes from **exactly one** of `compose` (reference an
existing service) or `container` (inline compose-style block):

```yaml
- id: perception_real
  kind: docker
  compose: { file: docker/demo.compose.yml, service: perception }   # (a)
  # --- or ---
  container:                                                        # (b)
    image: myorg/perception:latest
    command: ros2 launch perception bringup.launch.py
    environment: { RMW_IMPLEMENTATION: rmw_cyclonedds_cpp }
    network_mode: host
    ipc: host
    devices: ["/dev/video0:/dev/video0"]
    volumes: ["/opt/maps:/maps:ro"]
  ros_node_name: perception            # optional; params-file target (default /**)
  params: { max_range: 5.0, frame_id: camera_link }   # the existing field
  publishes: [/points]
  subscribes: [/tf]
```

`params`, `publishes`, `subscribes` are the **existing** `Alternative` fields —
so the param editor, profile overrides, and the topics view work unchanged.
Container config uses **compose field names** so there's nothing new to learn.

### Compose translation (in the launcher)

The launcher reads the service (from the file, or inline) and translates it to
a `docker run`. Supported subset (honored): `image`, `command`, `entrypoint`,
`environment`, `env_file`, `volumes`, `network_mode`, `ipc`, `pid`, `devices`,
`privileged`, `cap_add`, `cap_drop`, `ports`, `user`, `working_dir`, `gpus`.
Basic `${VAR}` / `${VAR:-default}` interpolation from the environment (plus an
optional `env_file`) is supported.

- **Correctness-affecting keys we cannot honor** — `replicas > 1`,
  `build:`-only services (no `image`), etc. — are **hard validation errors**.
- **Keys that don't apply to Sheppy's per-node model** — `restart:`,
  `depends_on:`, `healthcheck:` — are **warned-and-ignored** in the errors
  overlay.

Sheppy does **not** run `docker compose up`: Sheppy owns lifecycle, and
compose's orchestrator would fight it. We translate one service to one
supervised `docker run`.

### Params → params-file

Via `ctx.write_params_file(effective_params, ros_node_name)`, the launcher
writes a ROS2 params YAML (keyed by `ros_node_name` or `/**`) to the node's
scratch dir, bind-mounts it read-only into the container at
`/sheppy/params.yaml`, and appends `--ros-args --params-file
/sheppy/params.yaml` to the container command. Editing a param in the UI and
re-launching rewrites the file — no UI or schema change. (Shared-filesystem
assumption between client and daemon holds locally; flagged for phase 3.)

### Descriptor emitted

```jsonc
{
  "supervise": "detached",
  "name":  "sheppy-perception",
  "reset": ["docker", "rm", "-f", "sheppy-perception"],
  "start": ["docker", "run", "-d", "--name", "sheppy-perception",
            "-v", "<host params>:/sheppy/params.yaml:ro", /* run flags */,
            "<image>", /* command */, "--ros-args", "--params-file",
            "/sheppy/params.yaml"],
  "watch": ["docker", "wait", "sheppy-perception"],
  "stop":  ["docker", "stop", "--time", "10", "sheppy-perception"],
  "logs":  ["docker", "logs", "-f", "--tail", "300", "sheppy-perception"],
  "stats": ["docker", "stats", "--no-stream", "--format",
            "{{.CPUPerc}} {{.MemUsage}}", "sheppy-perception"]
}
```

Container name `sheppy-<node>` is the re-adoption identity.

### Docker availability

A missing `docker` CLI or a down Docker daemon is a **runtime** error: the node
goes **crashed** with the docker error in its log (never-crash holds). Manifest
validation does **not** require Docker to be installed — you can browse and
edit a Docker manifest with no Docker present (café-editing holds); only
launching needs it.

## 9. UI

No structural UI change. A Docker node is just another supervised node: same
glyphs, PROCESS tab, orphan handling, and — crucially — the **same param
editor**, because Docker nodes use the same `params` field. The DETAIL tab uses
the launcher's `summary()` to show kind-appropriate rows (image, resolved run
config for Docker; package/executable for the others). The YAML tab shows the
resolved descriptor.

## 10. Error handling

Consistent with Sheppy's never-crash ethos:

- Unknown `kind` (no registered launcher) → manifest error in the overlay.
- Launcher `validate()` errors → manifest errors in the overlay.
- A launcher raising during `launch()` → surfaced as a warning; that node is
  not launchable, the rest of the app is unaffected.
- Daemon receiving a descriptor it cannot interpret → error reply, no crash.
- Runtime failures (docker missing, image not found) → node **crashed** with
  the error in its log.

## 11. Testing

No Docker and no ROS required for the core suite.

- **Launcher golden tests**: each launcher's `launch()` output asserted
  against an expected descriptor, across kinds/params/compose-subset/quoting
  (the hostile-quoting and injection tests carry over to the docker command
  build).
- **Launcher-contract conformance test**: a shared test every registered
  launcher passes (validates its own sample, emits a well-formed descriptor,
  `watch xor poll` for detached, JSON-serializable).
- **Daemon `detached` engine**: driven by trivial shell stand-ins — `start` =
  `sh -c 'echo id'`, `watch` = `sh -c 'sleep 0.2; exit 0'`, `stop` = a script
  that makes `watch` return — exactly as the process engine is tested with
  `python -c`. Covers launch/running/stop/crash, re-adoption by name, `poll`
  fallback, and `stats` parsing.
- **Registry tests**: entry-point discovery, unknown-kind error, built-ins
  present.
- **Migration safety net**: the existing resolver + e2e launch tests must stay
  green through the built-in migration (behavior unchanged).
- **Opt-in Docker integration test**: one test behind a `docker`-available
  marker that actually runs a tiny container end-to-end.

## 12. Non-goals (this phase)

- Building images (run only).
- Full docker-compose orchestration — networks as a unit, `depends_on`
  ordering across services, running a whole compose project. We translate one
  service to one supervised container.
- Multi-machine. The params-file shared-filesystem assumption is local-only;
  flagged for phase 3, where the descriptor/params must land on the daemon's
  host.
- Language-agnostic (non-Python) launchers — the descriptor-as-data door is
  left open but not built.
- Container resource usage beyond the optional `stats` command.

## 13. Forward compatibility

- **New runtimes are new launchers** (podman, nerdctl, `systemd-run`,
  `kubectl`), each emitting a `detached` descriptor — **zero daemon change**.
  This is the whole point.
- **Language-agnostic launchers**: descriptors are pure data; an executable
  emitting descriptor JSON slots into discovery later.
- **Phase 3 (multi-machine)**: the descriptor is transport-agnostic; params
  files and referenced compose files must be made available on the daemon's
  host, and container names may need namespacing per host.
- **`poll` liveness**: already in the vocabulary for runtimes without a
  blocking wait, so exotic launchers don't force a daemon change.

## 14. Decisions log (from brainstorm)

- Generalize to a launcher-plugin surface; do not special-case Docker.
- Plugins are **declarative** (emit a `LaunchDescriptor`), run **client-side**;
  no third-party code in the daemon (stability of the supervisor is paramount).
- One `LaunchDescriptor` contract with `inherit` / `detached` shapes; `watch`
  preferred, `poll` fallback.
- Discovery via Python entry points; built-ins register identically.
- **Migrate all three existing kinds** to launchers now (no special case).
- Docker: run only; `compose` reference or inline `container`; translate one
  service to a supervised `docker run` (no `docker compose up`); container-name
  lifecycle; params via bind-mounted ROS2 params-file; same `params` field as
  every kind so the UI is unchanged.
- Ship a developer-facing plugin guide (the point is handing this to devs).
