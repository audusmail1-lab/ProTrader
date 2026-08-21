#!/usr/bin/env bash
# Stop the Trading Bot Dashboard server
PORT="${1:-8000}"
PID=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
if [ -n "$PID" ]; then
  kill "$PID"
  echo "✔  Trading Bot Dashboard stopped (PID $PID, port $PORT)."
else
  echo "ℹ  No server found running on port $PORT."
fi
