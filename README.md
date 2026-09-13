# Sheppy 🐑🐕

Herds the ROS2 nodes of a distributed robotics project — catalog them, switch
mock vs. real, launch and supervise them from one operator console.

- **Swap alternatives quickly:** mock or real driver, one planner or another,
  different camera configs.
- **Profiles instead of launch-file sprawl:** save the configuration you
  picked and bring it back with `sheppy up <profile>`.
- **See and tune every node:** state, CPU and memory, latest output, and
  parameters, from one TUI.
- **More than `ros2 launch`:** Docker containers and non-ROS commands like
  simulator GUIs, supervised the same way.

**Docs: https://rammp-org.github.io/sheppy**

```mermaid
flowchart TB
  M["sheppy-manifest.yaml<br/>what CAN run"] --> S
  P["profiles/*.yaml<br/>what SHOULD run"] --> S
  S["sheppy<br/>select · launch · supervise · observe"]
  S --> L1["ros2 launch"]
  S --> L2["ros2 run"]
  S --> L3["docker run"]
  S --> L4["any command"]
  L1 --> N["your running system"]
  L2 --> N
  L3 --> N
  L4 --> N
```

Sheppy does not replace `ros2 launch` — it calls it. An alternative of kind
`launch_file` shells out to `ros2 launch`; `executable` shells out to
`ros2 run`. Sheppy is the layer above: it catalogs which launch files are
interchangeable, remembers which set you picked, and supervises the processes
so they outlive your terminal.

## Install

```bash
curl -LsSf https://rammp-org.github.io/sheppy/install.sh | sh
```

Then open the TUI with `sheppy` next to your `sheppy-manifest.yaml`, or follow
[Getting started](https://rammp-org.github.io/sheppy/getting-started/) for a
90-second walkthrough that needs no ROS.

## Headless

```bash
sheppy up <profile>          # converge the running system to a profile
sheppy status                # what's running
sheppy logs <node> -n 50     # tail a node's output
sheppy woof <node>           # restart it 🐕
sheppy down                  # stop everything, then the daemon
```

Flags and exit codes: [CLI reference](https://rammp-org.github.io/sheppy/cli/).

## Development

```bash
git clone git@github.com:rammp-org/sheppy.git
cd sheppy
uv sync
uv run pytest
```

User docs live in [`docs/`](docs/); design records in
[`docs/superpowers/`](docs/superpowers/).
