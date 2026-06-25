# Sheppy — Design Spec

**Date:** 2026-06-25
**Status:** Approved for sub-project #1
**One-liner:** A TUI + background supervisor that herds the ROS2 nodes of a distributed assistive-robotics project — catalog them, switch alternatives (mock vs. real), launch/kill across machines, and introspect message flow.

---

## 1. Problem & Context

A distributed team of researchers builds ROS2 nodes for an assistive-research project. Integration sprints are painful because:

- Nobody has a single view of **what nodes exist**, and which ones are **interchangeable alternatives** (e.g. real driver vs. mock).
- Launch files are hand-managed and hard to compose, including messy real-world cases (timed launches to dodge sensor conflicts, a non-ROS Unreal GUI).
- Launching/killing across multiple computers is ad-hoc (manual SSH).
- When integration fails, there's no easy way to see, per node, **what messages it expects, what it's receiving, and what it's missing**.

No existing tool stitches these together. The primitives exist (`rqt_graph`, `ros2 launch`, community SSH-launch projects like `launch_remote`/`ssh_machine`, `ros2 topic info -v`), but nothing unifies them into one operator console. Sheppy fills that gap.

## 2. Decomposition (build order)

All four capabilities sit on top of one shared data model (the manifest), so they build in sequence. Each sub-project gets its own spec → plan → implementation cycle.

1. **Manifest schema + Catalog browser TUI** ← *this spec details this sub-project*
   YAML schema for machines/nodes/alternatives; a Textual app to load, validate, and browse it; single-select of an alternative per node. **No launching, no daemon yet.**
2. **Profiles + launch-config generation** — save/load named sets of node→alternative selections (+ params); introduces the supervisor daemon.
3. **Multi-machine launch / kill via SSH** — one supervisor daemon per host; TUI connects to each; SSH bootstraps remote daemons; live process status, kill/restart/restart-on-crash.
4. **Live introspection** — graph-API comparison of each node's declared contract vs. the live graph; flag starved subscriptions.

## 3. Overall Architecture

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

**Key architectural decisions (apply to the whole tool):**

- **Tech stack:** Python + [Textual](https://textual.textualize.io/) for the TUI; `rclpy` for ROS graph access.
- **TUI is a thin client to a background daemon (`sheppyd`).** The daemon owns child processes so the system survives the TUI detaching or crashing; multiple operators can attach; multi-machine is "a daemon per host."
- **Transport:** standalone daemon (one process per machine) exposing **gRPC/unix-socket**, embedding an `rclpy` node only for graph reads. Chosen over a ROS-native daemon so the control plane stays alive even when ROS/DDS is unhealthy — exactly when debugging is needed.
- **Manifest is the single source of truth**, curated and version-controlled. No auto-discovery in the catalog itself (avoids noise); a future "browse installed executables → add to manifest" helper is a convenience, not the source of truth.
- **Introspection is graph-API only** — no custom node base class / wrapper. The manifest's declared `publishes`/`subscribes` is the *expected contract*; the live graph (`ros2 topic info -v` / `rclpy` graph queries) is the *actual*. A declared subscription with zero matching publishers = starved. Works uniformly for first-party nodes, third-party drivers, rosbags, and the Unreal GUI's ROS bridge.

## 4. Manifest Schema

A single declarative YAML file (`system.yaml`), team-maintained and version-controlled.

- A **node** is a *logical* unit of the system (e.g. "camera"). (Disambiguation: a "manifest node" is this logical entry; a "ROS node" is a runtime process. Docs always qualify which.)
- Each node has interchangeable **alternatives**; `select: single` means exactly one alternative is active at a time (the core mock-vs-real switch).
- An alternative declares **how to bring the unit up** via `kind`:
  - `executable` — `ros2 run <package> <executable>`
  - `launch_file` — `ros2 launch <package> <launch_file>` (reuses existing timed-launch logic, multi-node subsystems)
  - `process` — arbitrary `command` (non-ROS, e.g. the Unreal GUI)
- `publishes` / `subscribes` describe the unit's **external** topic contract (the boundary it presents, regardless of how many ROS nodes hide inside). Optional and inert in sub-project #1; the backbone of introspection in #4.
- `machine` references a name from the `machines` block; just a label in #1, used for real in #3.

```yaml
machines:                       # referenced now, used for real in sub-project #3
  - name: robot
    host: 10.0.0.20
    user: researcher
    ros_setup: /opt/ros/humble/setup.bash   # + workspace overlay sourced on launch

nodes:
  - name: camera
    description: "RGB-D source"
    select: single
    alternatives:
      - id: realsense
        kind: launch_file       # reuses existing timed-launch logic
        package: realsense2_camera
        launch_file: rs_launch.py
        machine: robot
        params: { enable_depth: true }
        publishes: [/camera/color/image_raw, /camera/depth/points]
        subscribes: []
      - id: mock_camera
        kind: executable
        package: our_mocks
        executable: mock_camera
        machine: workstation
        publishes: [/camera/color/image_raw]

  - name: sim_gui
    select: single
    alternatives:
      - id: unreal
        kind: process           # arbitrary command, non-ROS
        command: "/opt/sim/UnrealEditor MyProject -game"
        machine: workstation
```

**Validation (run on load):**

- YAML parse errors.
- Unknown `machine` reference.
- Duplicate node `name` or alternative `id`.
- Missing field required by the declared `kind` (`executable` needs `package`+`executable`; `launch_file` needs `package`+`launch_file`; `process` needs `command`).
- `select` value other than `single` (only value supported now).

## 5. Sub-Project #1 — Catalog Browser TUI (detailed)

**Goal:** Load, validate, and browse the manifest; single-select an alternative per node (in-memory). Pure TUI, **no daemon, no launching**. The model/state layer is kept cleanly separate from widgets so the TUI becomes a thin `sheppyd` client in #2 with no rewrite.

### Components

- **`manifest` (model + loader)** — pure Python, no UI. Parses `system.yaml` into typed objects (`Machine`, `Node`, `Alternative`); runs validation (§4); returns either a model or a structured list of errors. Fully unit-testable without the TUI.
- **`SelectionState`** — in-memory; holds the chosen alternative per node; enforces single-select; emits change events. No persistence (that's profiles, #2). Pure logic, fully unit-testable.
- **TUI widgets** (thin shells over the above):
  - *Node list* (left pane) — all manifest nodes, each showing its currently-selected alternative (or "— none —").
  - *Detail pane* (right) — for the focused node: its alternatives; for the selected one, its `kind`, package/executable/launch_file/command, params, machine, and `publishes`/`subscribes`.
  - *Status bar* — manifest path, validation status, error count.
- **Interaction:** arrow / `j` / `k` to move; `enter` / space to pick an alternative for the focused node.

### Data flow

`system.yaml` → `manifest.load()` → model → render node list. User picks → `SelectionState` updates → detail pane re-renders. One-directional, easy to reason about.

### Error handling

Invalid manifest → an error overlay lists every problem; the app stays browsable where possible; it never crashes on a bad manifest.

### Testing

- `manifest` loader/validator: unit tests for a valid manifest and for **each** malformed case in §4.
- `SelectionState`: unit tests for single-select enforcement and change events.
- Widgets: Textual pilot / snapshot tests for the core navigation + selection flows.

### Out of scope for #1

Daemon (`sheppyd`), launching anything, profiles/persistence, SSH/multi-machine, live introspection, and the "add from installed executables" helper.

## 6. Naming

- Tool: **Sheppy** (short for "sheepdog" — herds nodes, keeps strays in line, fetches wanderers).
- CLI: `sheppy`; daemon: `sheppyd`; restart command: `sheppy woof`.

## 7. Deferred decisions (captured, not yet specced)

- Exact gRPC/socket protocol + schema for TUI↔`sheppyd` (decide in #2).
- Profile file format and storage location (#2).
- Remote `sheppyd` bootstrap mechanics over SSH (#3).
- Crash/restart policy and backoff (#3).
- Introspection refresh cadence and how starvation is surfaced in the UI (#4).
