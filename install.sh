#!/usr/bin/env sh
# Claude2Antigravity installer for macOS / Linux. Passes every argument to install.py.
#   ./install.sh          # install the skill for Claude Code and Antigravity, preview the first sync
#   ./install.sh --sync   # ...and run the first sync
set -e
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then echo "Python 3.10+ is needed: https://www.python.org/downloads/"; exit 1; fi
exec "$PY" "$(dirname "$0")/install.py" "$@"
