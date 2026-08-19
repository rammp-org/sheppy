# Docs overhaul — design

**Date:** 2026-08-19
**Issue:** [#5 — Docs review: first-run experience from a ROS user's perspective](https://github.com/rammp-org/sheppy/issues/5)
**Status:** approved, ready for implementation planning

## Goal

Close the gaps in issue #5 while holding two constraints the maintainer set:

1. **Docs are as succinct as possible.** Total prose should *drop*, not grow.
2. **Pictures speak 10,000 words.** Diagrams carry structure that prose currently narrates.

Plus one thing the review implied and the maintainer named directly: the docs must
teach the **mental model** — profiles vs live launching, desired vs actual — rather
than leaving it buried in a guide.

## The core problem

A ROS-literate newcomer can install sheppy and run the demo in two minutes, then
stalls. Three things block them:

- Nothing says how sheppy relates to `ros2 launch`, so they can't place it against
  what they know.
- There is no schema, so they cannot write their own manifest.
- The clearest explanation of sheppy's model (desired vs actual) sits at
  `guides/sheppyd.mdx:236-248`, four clicks deep.

Everything below serves those three.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Manifest reference | Annotated example is primary; field tables on a separate page | Example teaches, tables answer lookups. Splitting keeps each page short. |
| Kind documentation | Core kinds and plugin-contributed kinds explicitly delineated | `process`/`executable`/`launch_file` are builtins; `docker` ships as a plugin. Invisible today. |
| Diagram medium | Mermaid everywhere | Nextra already bundles `@theguild/remark-mermaid`; GitHub renders it natively. One source, both surfaces, zero new deps. Revisit if it proves too limiting. |
| Landing page | "Basics of everything you need to know", Concepts page follows | Reader is oriented before clicking anything. |
| Manifest filename | `sheppy-manifest.yaml` | "manifest" is overloaded in ROS (ROS1 `manifest.xml`, ROS2 `package.xml`). Branded name is unambiguous. `.yaml` retained so editor tooling and schema validation keep working. |
| Enforcement | Convention + escape hatch | Bare `sheppy` finds `./sheppy-manifest.yaml`; explicit paths still load anything. Mirrors `docker build` / `-f`. |
| Non-docs findings | Filed as issues, not fixed here | Keeps this focused. |

### Verified compatibility

Both Dojo repos invoke sheppy with an **explicit** manifest path
(`dojo/README.md:79`, `dojo/docs/cameras.md:35-36`, `dojo-env/README.md:34-35`).
The escape hatch means the arm cell keeps working with no change. Renaming Dojo's
own `system.yaml` for consistency is a separate, optional follow-up in that repo.

## Page structure

Each page gets exactly one job. Vocabulary is defined once, in Concepts, and linked
from everywhere else instead of re-explained — that is where the prose savings come
from.

| Page | Owns | Action |
|---|---|---|
| Introduction | What sheppy is; relation to `ros2 launch`; install; the four words | Rewrite |
| **Concepts** *(new)* | Desired vs actual; live-launch vs converge; manifest node ≠ ROS node | Create |
| Getting started | One 90-second walkthrough, expected output at each step | Rewrite |
| The TUI | Keys, glyphs, panes, SSH colours | Light edits |
| The manifest | The annotated `sheppy-manifest.yaml` | Rewrite |
| **Manifest reference** *(new)* | Field tables per level; core vs plugin kinds | Create |
| Guides → sheppyd | Daemon behaviour and its consequences | Trim + correct |
| Guides → launcher plugins | Writing a launcher | Correct |
| Architecture & roadmap | What exists, and what is planned | Correct |
| Design records | Unchanged | — |

Nav order follows that table.

**README** is reduced to pitch + install + the layer diagram + a link to the site.
It stops being a second copy of the docs, which is what let it drift (review m2).

**`docs/index.md`** duplicates the design-records table from `design-records.mdx`.
Deduplicate to a pointer.

## Diagrams

Four Mermaid diagrams, each replacing prose or a broken ASCII drawing.

1. **Layers** — manifest → sheppy → `ros2 launch` / `ros2 run` / docker → processes.
   Answers "why not just a bringup package?" in the first screenful.
   *Lands on:* Introduction, README.
2. **Desired vs actual** *(hero)* — manifest + profile = desired; daemon table =
   actual; the `Δ`; `space` pushes, `!` pulls. *Lands on:* Concepts.
3. **Architecture** — TUI/CLI → unix socket + NDJSON → `sheppyd` → children.
   Replaces the ASCII box that is both misaligned and describes an unimplemented
   rclpy design. *Lands on:* Architecture.
4. **Manifest anatomy** — manifest → nodes → alternatives; a profile selects one
   alternative per node. *Lands on:* Concepts, The manifest.

## Content corrections (from #5)

- `architecture.mdx` — diagram describes an unimplemented rclpy/graph-introspection
  design and contradicts the sheppyd guide. Redraw to reality; move rclpy to the
  roadmap row, marked planned.
- `guides/sheppyd.mdx` — the wire-protocol example is stale. Verified against source:
  `sheppy/launch/resolve.py:21-23` serialises `descriptor`, not `argv`, and
  `sheppy/daemon/server.py:18` rejects a spec without one. Copy-pasting the documented
  example fails. Fix the example and the `LaunchSpec` description at `:38-41`.
- `guides/sheppyd.mdx` — launch-resolution section omits `docker` and predates the
  plugin registry.
- `manifest.mdx` — stops at one snippet and punts to a design record for the schema.
- Terminology — add a callout that a manifest node is a *logical unit*, not a ROS node.
- Consistency — one invocation style throughout (bare `sheppy`, matching the installer).
- `select:` is presented as if it has options; it has exactly one.
- Phase numbers leak into user-facing copy.
- `sheppy woof` is shown without its required argument.

## Code changes (minimal)

1. `sheppy/cli.py` — `build_app` default and the `--manifest` default become
   `sheppy-manifest.yaml`.
2. `install.sh:45` — closing message names the new file.
3. `examples/system.yaml` → `examples/sheppy-manifest.yaml`, rewritten as the
   annotated reference example covering every field and all four kinds.
4. Tests — assert the new default resolves, and assert
   `examples/sheppy-manifest.yaml` loads with no errors, so the reference example
   cannot silently rot (the failure mode behind review finding M4).

No other behaviour changes. Explicit paths keep working.

## Out of scope — file as issues

- LICENSE and CONTRIBUTING (licence choice is the maintainer's).
- Missing/malformed manifest opens a blank TUI with no explanation; should print to
  stderr and exit.
- `examples/profiles/all-mock.yaml` is referenced by `tui.mdx` but does not exist.
- `examples/launchers/echo_launcher.py` cannot be run end to end as the guide claims.
- Demo run writes `profiles/` into the checked-out `examples/` dir; wants a
  `.gitignore` entry.

## Verification

- `npm run build` in `website/` passes; all four diagrams render; no broken internal
  links.
- `pytest` green, including the two new tests.
- The Getting started walkthrough is executed literally, start to finish, and the
  documented output is confirmed to match what the tool actually prints.
- Prose check: total non-diagram line count across README + `website/content/`
  should not exceed today's. Growth means the dedup failed.

## Success criteria

A ROS-literate reader who has never seen sheppy can, from the docs alone:

1. Say what sheppy does and how it relates to `ros2 launch`, within one screenful.
2. Run the demo and see a node launch, crash, and get restarted.
3. Write a valid `sheppy-manifest.yaml` for their own system without reading source.
4. Explain the difference between launching something live and converging a profile.
