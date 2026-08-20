# Sheppy 🐑🐕

A TUI + background supervisor that **herds the ROS2 nodes** of a distributed
assistive-robotics project — catalog them, switch alternatives (mock vs. real),
launch/kill across machines, and introspect message flow.

Sheppy exists because integration sprints kept hitting the same walls: no single
view of what nodes exist or which are interchangeable, hand-managed launch files,
ad-hoc multi-machine SSH, and no easy way to see what each node *expects* vs.
what it's actually *receiving*. The ROS2 primitives exist (`rqt_graph`,
`ros2 launch`, `ros2 topic info -v`, community SSH-launch projects) but nothing
unifies them into one operator console. Sheppy does.

- **CLI:** `sheppy`
- **Daemon:** `sheppyd`
- **Restart a node:** `sheppy woof`
- **Docs:** https://rammp-org.github.io/sheppy

## Getting Started

> Load a manifest, browse nodes and their alternatives, and select one
> alternative (mock vs. real) per node (Phase 1). Save and load those choices —
> plus per-alternative parameter overrides — as named **profiles** (Phase 2a).
> Phase 2b adds `sheppyd`: select, press `space`, and the process is really
> running — locally, surviving TUI detach.

### Install

```bash
curl -LsSf https://rammp-org.github.io/sheppy/install.sh | sh
```

Installs [uv](https://docs.astral.sh/uv/) if missing, then puts `sheppy` and
`sheppyd` on your `PATH` (`~/.local/bin`) in an isolated environment. Re-run to
upgrade; `SHEPPY_REF=<ref>` pins a branch/tag/commit; `uv tool uninstall sheppy`
removes it. (Already have uv? `uv tool install git+https://github.com/rammp-org/sheppy`.)

### Run the TUI

```bash
sheppy path/to/sheppy-manifest.yaml      # defaults to ./sheppy-manifest.yaml if omitted
```

### From source (development)

Requires **Python 3.10+** and uv:

```bash
git clone git@github.com:rammp-org/sheppy.git
cd sheppy
uv sync                               # creates .venv and installs everything from uv.lock
uv run sheppy examples/sheppy-manifest.yaml    # run from the checkout
```

**Keys:**

| Key | Action |
|-----|--------|
| `↑` / `↓` | Move through the node list (left pane) |
| `Enter` (on a node) | Descend into that node's alternatives (right pane) |
| `↑` / `↓` | Move through alternatives; the detail pane updates |
| `Enter` (on an alternative) | Select it for the node (mock vs. real) |
| `Esc` | Return focus to the node list |
| `s` | Save the current selections + overrides as a profile |
| `l` | Load a profile (Enter to load, `d` to delete) |
| `p` | Edit the highlighted node's declared parameters |
| `e` | Toggle the validation-error overlay |
| `1`–`4` | Switch detail tab (Detail / Topics / Process / YAML) |
| `Space` | Launch/converge the highlighted node to its selected alternative |
| `x` / `r` | Stop / restart the highlighted node |
| `L` | Converge everything to the current selection (shows a plan first) |
| `X` | Stop all running nodes (confirmation; includes orphans) |
| `!` | Snapshot: copy what's running into the selection (then save-as) |
| `Ctrl+C` | Quit |

The TUI uses an operator-cockpit layout: a header bar (profile · source ·
errors · clock), a machines strip, the three-pane body (nodes · alternatives ·
tabbed detail), and a footer of key hints. Process status is live via
`sheppyd`; live machine connections (phase 3) and the topics "live" column
(phase 4) remain placeholders.

A malformed manifest never crashes the app — errors are listed in the overlay
(`e`) and the rest stays browsable. The same holds for profiles: a corrupt
profile file or one that has drifted from the manifest surfaces warnings in the
overlay and the applicable remainder still loads.

Profiles are stored as one YAML file per profile in a `profiles/` directory next
to your manifest (e.g. `examples/profiles/all-mock.yaml`); the filename is the
profile name. They're plain, version-controllable text.

### Launching for real: `sheppyd`

The first launch action auto-starts `sheppyd`, a tiny supervisor daemon
(stdlib-only, ~zero idle CPU) that owns the child processes — quit the TUI
and everything keeps running. Reconnect and it's all still there; even if
`sheppyd` itself dies, a restarted daemon re-adopts the survivors.

Headless verbs (no TUI needed):

```bash
sheppy up <profile> --manifest sheppy-manifest.yaml   # converge to a profile
sheppy status                                # what's running
sheppy logs <node> -n 50                     # tail a node's output
sheppy woof <node>                           # restart it 🐕
sheppy down                                  # stop everything + daemon
sheppy --version                             # print the installed version
```

Node output goes to `~/.sheppy/logs/<node>/<timestamp>-<id>.log` (last 5 runs
kept). Optional flat-JSON config at `~/.sheppy/sheppyd.json`:

```json
{"ring_lines": 300, "keep_runs": 5, "coredumps": false,
 "usage_interval": 2.0, "launch_grace": 2.0,
 "stop_grace": 5.0, "kill_grace": 5.0}
```

Try it without ROS: `sheppy examples/local-demo.yaml` (from a checkout).

For the full picture — architecture, node states, re-adoption, the wire
protocol, and troubleshooting — see the **[sheppyd guide](https://rammp-org.github.io/sheppy/guides/sheppyd/)**
(and the [docs index](https://rammp-org.github.io/sheppy)). Want to add your own launch `kind`
(a custom process wrapper, systemd, Kubernetes, ...)? See
**[writing a launcher plugin](https://rammp-org.github.io/sheppy/guides/launcher-plugins/)**.

### Colors washed out over SSH?

Sheppy's palette needs 24-bit color. The decision is made on the machine
*running* sheppy: with `COLORTERM` unset (SSH does not forward it by default)
and `TERM=xterm-256color`, Textual quantizes every color to the 256-color
palette and the subtle background layering collapses. On the remote machine:

```bash
export COLORTERM=truecolor   # add to your remote ~/.bashrc / ~/.zshrc
```

(or forward it: `SendEnv COLORTERM` in your local `~/.ssh/config` plus
`AcceptEnv COLORTERM` in the server's `sshd_config`). If you use tmux on the
remote, also add `set -as terminal-overrides ',*:Tc'` to `~/.tmux.conf`.

### Run the tests

```bash
uv run pytest          # full suite
uv run pytest -v       # verbose
uv run pytest tests/manifest        # just the manifest/loader tests
```

The model, loader/validator, and selection logic are pure Python and tested
without the UI; the TUI is exercised end-to-end with Textual's async pilot.

## Architecture

```
┌────────────────────────┐    gRPC / unix-socket  ┌──────────────────────────────┐
│  TUI client            │◄──────────────────────►│  sheppyd (supervisor, per host)│
│  (Textual)             │                        │  • owns child processes        │
│  reads                 │   manifest (shared)    │    (launch / kill / restart)   │
│  sheppy-manifest.yaml  │◄───────────────────────│  • embeds rclpy node for       │
└────────────────────────┘                        │    graph introspection         │
                                        └──────────────────────────────┘
  multi-machine = one sheppyd per host; the TUI connects to each;
  SSH bootstraps remote daemons.
```

- **Tech:** Python + [Textual](https://textual.textualize.io/) (TUI), `rclpy` (ROS graph access).
- **Daemon-backed:** the TUI is a thin client; `sheppyd` owns the processes so the
  system survives the TUI detaching or crashing.
- **Manifest is the source of truth:** a curated, version-controlled `sheppy-manifest.yaml`.
- **Introspection is graph-API only:** no custom node base class. The manifest's
  declared `publishes`/`subscribes` is the *expected* contract; the live ROS graph
  is the *actual*. A declared subscription with zero matching publishers = starved.

## Project Phases

Each phase builds on the shared manifest data model and ships with its own
spec → plan → implementation cycle.

| Phase | Name | Scope | Status |
|------:|------|-------|--------|
| **1** | Manifest schema + Catalog browser TUI | YAML schema for machines/nodes/alternatives; Textual app to load, validate, and browse it; single-select an alternative per node (mock vs. real). No launching, no daemon. | ✅ Done |
| **2a** | Profiles | Save/load named selection sets + declared-param overrides as per-profile YAML, managed in the TUI. No launching. | ✅ Done |
| **2b** | `sheppyd` + local launch | Supervisor daemon + gRPC/socket protocol; launch a profile's processes locally with live status, kill/restart. | ✅ Done |
| **3** | Multi-machine launch / kill via SSH | One `sheppyd` per host; TUI connects to each; SSH bootstraps remote daemons; live process status, kill/restart/restart-on-crash. | ⬜ Planned |
| **4** | Live introspection | Graph-API comparison of each node's declared contract vs. the live graph; flag starved subscriptions. | ⬜ Planned |

## Manifest at a glance

A **node** is a *logical* unit (e.g. "camera"). It has interchangeable
**alternatives**; `select: single` means exactly one runs at a time. An
alternative declares how to bring the unit up via `kind`:
`executable` (`ros2 run`), `launch_file` (`ros2 launch`), or `process`
(arbitrary command, e.g. a non-ROS GUI).

```yaml
nodes:
  - name: camera
    select: single
    alternatives:
      - id: realsense
        kind: launch_file
        package: realsense2_camera
        launch_file: rs_launch.py
        publishes: [/camera/color/image_raw]
      - id: mock_camera
        kind: executable
        package: our_mocks
        executable: mock_camera
        publishes: [/camera/color/image_raw]
```

See the full design in
[`docs/superpowers/specs/2026-06-25-sheppy-design.md`](docs/superpowers/specs/2026-06-25-sheppy-design.md).
