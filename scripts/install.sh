#!/usr/bin/env bash
# DataClaw — one-line installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/REPLACE_WITH_REPO/main/scripts/install.sh | bash
#
# Or, from a local clone:
#   ./scripts/install.sh
#
# The installer prefers `pipx`; falls back to `pip --user` if pipx is unavailable.
# It builds the frontend into a wheel and installs the `dataclaw` CLI on $PATH.

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
RESET='\033[0m'

info()  { printf "%b\n" "${GREEN}==>${RESET} $*"; }
warn()  { printf "%b\n" "${YELLOW}!!${RESET} $*"; }
fatal() { printf "%b\n" "${RED}xx${RESET} $*" >&2; exit 1; }

REPO_URL="${DATACLAW_REPO:-https://github.com/REPLACE_WITH_REPO}"
REF="${DATACLAW_REF:-main}"

require() {
    command -v "$1" >/dev/null 2>&1 || fatal "Missing required command: $1"
}

require python3
require node
require npm

PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
case "$PYVER" in
    3.12|3.13|3.14) ;;
    *) fatal "Python 3.12+ required (found $PYVER)" ;;
esac

if [[ -d "${PWD}/dataclaw/backend" ]]; then
    SRC="${PWD}/dataclaw"
elif [[ -d "${PWD}/backend" && -d "${PWD}/frontend" ]]; then
    SRC="${PWD}"
else
    info "Cloning DataClaw into ./dataclaw"
    require git
    git clone --depth=1 --branch "$REF" "$REPO_URL" dataclaw
    SRC="${PWD}/dataclaw"
fi

info "Building frontend"
( cd "$SRC/frontend" && npm ci --no-audit --no-fund && npm run build )

info "Bundling frontend into backend package"
rm -rf "$SRC/backend/app/static"
mkdir -p "$SRC/backend/app/static"
cp -R "$SRC/frontend/dist/." "$SRC/backend/app/static/"

if command -v pipx >/dev/null 2>&1; then
    info "Installing dataclaw via pipx"
    pipx install --force "$SRC/backend"
else
    warn "pipx not found; installing via pip --user"
    python3 -m pip install --user --upgrade pip
    python3 -m pip install --user "$SRC/backend"
fi

info "Generating fresh secrets"
dataclaw init || true

cat <<EOF

DataClaw is installed.

  dataclaw dashboard       launch the UI in your browser
  dataclaw status          show running state
  dataclaw stop            stop the daemon

Config:    ~/.dataclaw/.env
Data:      ~/.dataclaw/app.sqlite

EOF
