# Sheppy documentation

Sheppy 🐑🐕 herds the ROS2 nodes of a distributed robotics project — catalog
them, switch alternatives (mock vs. real), launch/kill them, and (later)
introspect message flow. See the [project README](../README.md) for install
and a quick tour.

> This directory is the content root for the eventual documentation site. For
> now it's plain Markdown you can read directly on GitHub.

## Guides

- **[sheppyd — the launch supervisor](sheppyd.md)** — the daemon that runs
  your nodes: architecture, lifecycle, node states, logs, configuration, the
  CLI and TUI controls, the wire protocol, and troubleshooting.
- **[Writing a launcher plugin](launcher-plugins.md)** — add your own `kind`
  (a custom process wrapper, systemd, Kubernetes, ...): the `Launcher`
  contract, the `LaunchDescriptor` vocabulary, and a worked example.

## Design records

The per-phase specs and implementation plans live under
[`superpowers/`](superpowers/) — one spec and one plan per phase. They capture
*why* each phase is shaped the way it is, and are the reference for anyone
extending Sheppy.

| Phase | Spec | Plan |
|------:|------|------|
| 1 — Catalog TUI | [design](superpowers/specs/2026-06-25-sheppy-design.md) | [plan](superpowers/plans/2026-06-25-sheppy-phase1-catalog-tui.md) |
| 2a — Profiles | [design](superpowers/specs/2026-06-26-sheppy-phase2a-profiles-design.md) | [plan](superpowers/plans/2026-07-09-sheppy-phase2a-profiles.md) |
| 2a.5 — Cockpit shell | [design](superpowers/specs/2026-07-13-sheppy-phase2a5-cockpit-shell-design.md) | [plan](superpowers/plans/2026-07-13-sheppy-phase2a5-cockpit-shell.md) |
| 2b — sheppyd + local launch | [design](superpowers/specs/2026-07-16-sheppy-phase2b-sheppyd-design.md) | [plan](superpowers/plans/2026-07-16-sheppy-phase2b-sheppyd.md) |
