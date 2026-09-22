#!/bin/sh
# Sheppy installer — https://rammp-org.github.io/sheppy
#
#   curl -LsSf https://rammp-org.github.io/sheppy/install.sh | sh
#
# Installs uv if missing, then installs `sheppy` + `sheppyd` as a uv tool
# (isolated venv, binaries on ~/.local/bin). Re-run to upgrade, then run
# `sheppy daemon stop` so the next command starts sheppyd on the new version.
#
#   SHEPPY_REF=<tag|branch|sha>   what to install (default: the latest release)
#   SHEPPY_REF=dev                the development branch
#
# Uninstall:  uv tool uninstall sheppy
set -eu

REPO="https://github.com/rammp-org/sheppy"
API="https://api.github.com/repos/rammp-org/sheppy/releases/latest"

say()  { printf '%s\n' "sheppy: $*" >&2; }
fail() { say "error: $*"; exit 1; }

command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 \
  || fail "need curl or wget to download"

fetch() {
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1"; else wget -qO- "$1"; fi
}

# 0. which ref: an explicit SHEPPY_REF, else the latest release tag, else main
REF="${SHEPPY_REF:-}"
if [ -z "$REF" ]; then
  REF="$(fetch "$API" 2>/dev/null | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)" || true
  if [ -z "$REF" ]; then
    REF=main
    say "could not look up the latest release; installing from main"
  fi
fi

# 1. uv
if ! command -v uv >/dev/null 2>&1; then
  say "uv not found — installing it (https://docs.astral.sh/uv/)"
  fetch https://astral.sh/uv/install.sh | sh
  # uv's installer drops the binary in ~/.local/bin (or $UV_INSTALL_DIR),
  # which may not be on PATH yet in this shell.
  PATH="${UV_INSTALL_DIR:-$HOME/.local/bin}:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv installed but not found on PATH; open a new shell and re-run"
fi

# 2. sheppy
SRC="git+${REPO}@${REF}"
say "installing ${REF} from ${SRC}"
uv tool install --force --quiet "$SRC"

# 3. PATH check
if command -v sheppy >/dev/null 2>&1; then
  say "installed $(sheppy --version 2>/dev/null || echo sheppy) — run: sheppy path/to/sheppy-manifest.yaml"
  say "upgrading? run 'sheppy daemon stop' so the next command starts sheppyd on this version"
else
  BIN_DIR="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
  say "installed to ${BIN_DIR}, which is not on your PATH."
  say "run 'uv tool update-shell' (or add ${BIN_DIR} to PATH), then open a new shell."
fi
