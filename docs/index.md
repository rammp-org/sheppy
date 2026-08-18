# Sheppy documentation

The documentation site lives at **<https://rammp-org.github.io/sheppy>**; its
source is [`website/content/`](../website/content/) (Nextra + MDX). Start
there for install, the TUI, the manifest, and the guides:

- [sheppyd — the launch supervisor](../website/content/guides/sheppyd.mdx)
- [Writing a launcher plugin](../website/content/guides/launcher-plugins.mdx)

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
| Launcher plugins | [design](superpowers/specs/2026-07-20-sheppy-launcher-plugins-design.md) | [plan](superpowers/plans/2026-07-20-sheppy-launcher-plugins.md) |
