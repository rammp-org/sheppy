# Changelog

Per-release notes are generated from pull request titles and published on
the [GitHub releases page](https://github.com/rammp-org/sheppy/releases).
This file records what each major version commits to.

## 1.0.0 (unreleased)

First stable release. The following are frozen for the 1.x series; a change
to any of them is a 2.0:

- **Manifest schema.** The `machines` and `nodes` structure, the alternative
  fields, the core kinds (`executable`, `launch_file`, `process`) and the
  `docker` kind, as described in `docs/manifest-reference.mdx`.
- **Profile schema.** The profile file format under `profiles/`, as
  described in `docs/profiles.mdx`.
- **Plugin API.** The `sheppy.launchers` entry point group, the launcher
  protocol (`kind`, `validate`, `launch`, `summary`), `Alternative`,
  `LaunchDescriptor` and `LaunchContext`, as described in
  `docs/guides/launcher-plugins.mdx`. `Alternative.config` is a deprecated
  alias for `Alternative.raw` and is removed in 2.0.
- **Socket protocol.** The NDJSON protocol between clients and `sheppyd`
  (`"protocol": 2`): the hello event, the request and reply shape, and the
  `launch`, `stop`, `restart`, `status`, `logs`, `subscribe` and `shutdown`
  ops. New ops or fields may be added; existing ones keep their meaning.
- **Config keys.** The keys of `~/.sheppy/sheppyd.json` (`log_dir`,
  `ring_lines`, `keep_runs`, `coredumps`, `usage_interval`, `launch_grace`,
  `stop_grace`, `kill_grace`) and the `SHEPPY_HOME` variable.
- **CLI verbs.** `sheppy up`, `down`, `status`, `logs`, `restart`,
  `daemon status` and `daemon stop`, their arguments and exit codes, as
  described in `docs/cli.mdx`. `woof` is an alias of `restart` and is kept
  as well.

Upgrade note: `sheppyd` is long-lived and keeps running the version it was
started with. After upgrading, run `sheppy daemon stop`; the next command
starts a daemon on the new code. Nodes keep running across the daemon
restart and are re-adopted.
