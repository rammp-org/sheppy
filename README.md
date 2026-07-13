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

## Getting Started

> Load a manifest, browse nodes and their alternatives, and select one
> alternative (mock vs. real) per node (Phase 1). Save and load those choices —
> plus per-alternative parameter overrides — as named **profiles** (Phase 2a).
> Launching, the daemon, and introspection arrive in later phases.

### Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** for environment and dependency management
  — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`

### Install

```bash
git clone <your-remote>/ros2-tooling.git
cd ros2-tooling
uv sync          # creates .venv and installs everything from uv.lock
```

### Run the TUI

```bash
uv run sheppy examples/system.yaml
```

Or point it at your own manifest:

```bash
uv run sheppy path/to/system.yaml      # defaults to ./system.yaml if omitted
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
| `Ctrl+C` | Quit |

A malformed manifest never crashes the app — errors are listed in the overlay
(`e`) and the rest stays browsable. The same holds for profiles: a corrupt
profile file or one that has drifted from the manifest surfaces warnings in the
overlay and the applicable remainder still loads.

Profiles are stored as one YAML file per profile in a `profiles/` directory next
to your manifest (e.g. `examples/profiles/all-mock.yaml`); the filename is the
profile name. They're plain, version-controllable text.

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
┌──────────────┐    gRPC / unix-socket  ┌──────────────────────────────┐
│  TUI client  │◄──────────────────────►│  sheppyd (supervisor, per host)│
│  (Textual)   │                        │  • owns child processes        │
│  reads       │   manifest (shared)    │    (launch / kill / restart)   │
│  system.yaml │◄───────────────────────│  • embeds rclpy node for       │
└──────────────┘                        │    graph introspection         │
                                        └──────────────────────────────┘
  multi-machine = one sheppyd per host; the TUI connects to each;
  SSH bootstraps remote daemons.
```

- **Tech:** Python + [Textual](https://textual.textualize.io/) (TUI), `rclpy` (ROS graph access).
- **Daemon-backed:** the TUI is a thin client; `sheppyd` owns the processes so the
  system survives the TUI detaching or crashing.
- **Manifest is the source of truth:** a curated, version-controlled `system.yaml`.
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
| **2b** | `sheppyd` + local launch | Supervisor daemon + gRPC/socket protocol; launch a profile's processes locally with live status, kill/restart. | ⬜ Planned |
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
