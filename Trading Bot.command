#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Trading Bot Dashboard — macOS Double-Click Launcher
#  Make executable once:  chmod +x "Trading Bot.command"
#  Then just double-click it in Finder to start the dashboard.
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/start.sh"
