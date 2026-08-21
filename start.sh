#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Trading Bot Dashboard — Launcher
#  Usage:  ./start.sh          (default port 8000)
#          ./start.sh 8080     (custom port)
# ─────────────────────────────────────────────────────────────────────────────

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${1:-8000}"
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON=""

# ── 1. Locate Python 3.9+ ─────────────────────────────────────────────────
for cmd in python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
  if command -v "$cmd" &>/dev/null; then
    ver=$("$cmd" -c "import sys; print(sys.version_info >= (3,9))" 2>/dev/null)
    if [ "$ver" = "True" ]; then
      PYTHON="$cmd"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "❌  Python 3.9+ not found. Install it from https://python.org and try again."
  exit 1
fi

echo "✔  Python: $($PYTHON --version)"

# ── 2. Create virtualenv if missing ───────────────────────────────────────
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "⚙   Creating virtual environment..."
  "$PYTHON" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# ── 3. Install / upgrade dependencies ─────────────────────────────────────
echo "📦  Checking dependencies..."
pip install -q --upgrade pip
pip install -q -r "$SCRIPT_DIR/requirements.txt"

# ── 4. Kill any previous instance on the same port ────────────────────────
OLD_PID=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
if [ -n "$OLD_PID" ]; then
  echo "⚠   Stopping previous server on port $PORT (PID $OLD_PID)..."
  kill "$OLD_PID" 2>/dev/null || true
  sleep 1
fi

# ── 5. Start the server ───────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   🤖  Trading Bot Dashboard                  ║"
echo "╠══════════════════════════════════════════════╣"
echo "║   URL  →  http://localhost:$PORT             ║"
echo "║   Stop →  Ctrl + C                           ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Open browser after a short delay (background)
(sleep 2 && open "http://localhost:$PORT" 2>/dev/null || \
           xdg-open "http://localhost:$PORT" 2>/dev/null || true) &

# Run uvicorn (foreground so Ctrl+C kills it cleanly)
exec uvicorn dashboard:app --host 0.0.0.0 --port "$PORT"
