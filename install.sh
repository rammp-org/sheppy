#!/bin/sh
# Sheppy installer — https://rammp-org.github.io/sheppy
#
#   curl -LsSf https://rammp-org.github.io/sheppy/install.sh | sh
#
# Installs uv if missing, then installs `sheppy` + `sheppyd` as a uv tool
# (isolated venv, binaries on ~/.local/bin). Re-run to upgrade.
#
#   SHEPPY_REF=<tag|branch|sha>   install a specific git ref (default: main)
#
# Uninstall:  uv tool uninstall sheppy
set -eu

REPO="https://github.com/rammp-org/sheppy"
REF="${SHEPPY_REF:-}"

say()  { printf '%s\n' "sheppy: $*" >&2; }
fail() { say "error: $*"; exit 1; }

command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 \
  || fail "need curl or wget to download"

# 1. uv
if ! command -v uv >/dev/null 2>&1; then
  say "uv not found — installing it (https://docs.astral.sh/uv/)"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  else
    wget -qO- https://astral.sh/uv/install.sh | sh
  fi
  # uv's installer drops the binary in ~/.local/bin (or $UV_INSTALL_DIR),
  # which may not be on PATH yet in this shell.
  PATH="${UV_INSTALL_DIR:-$HOME/.local/bin}:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv installed but not found on PATH; open a new shell and re-run"
fi

# 2. sheppy
SRC="git+${REPO}"
[ -n "$REF" ] && SRC="${SRC}@${REF}"
say "installing from ${SRC}"
uv tool install --force --quiet "$SRC"

# 3. PATH check
if command -v sheppy >/dev/null 2>&1; then
  say "installed — run: sheppy path/to/sheppy-manifest.yaml"
else
  BIN_DIR="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
  say "installed to ${BIN_DIR}, which is not on your PATH."
  say "run 'uv tool update-shell' (or add ${BIN_DIR} to PATH), then open a new shell."
fi
