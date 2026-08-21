#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Trading Bot — background server control
#
#    ./server.sh start     launch detached (survives closing the terminal)
#    ./server.sh stop      shut down
#    ./server.sh restart   stop then start
#    ./server.sh status    pid, port, uptime, health, feed check
#    ./server.sh logs      follow the log (Ctrl+C to stop following)
#
#  Unlike start.sh this does NOT hold the terminal open, so it suits everyday
#  use. Default port 8000; pass another as the second argument.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PORT="${2:-8000}"
HOST="${TRADING_BOT_HOST:-0.0.0.0}"   # 0.0.0.0 = reachable from your phone on the same Wi-Fi
PIDFILE="$DIR/.server.pid"
LOGFILE="$DIR/server.log"
UVICORN="$DIR/.venv/bin/uvicorn"

running_pid() {
  if [ -f "$PIDFILE" ]; then
    local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then echo "$pid"; return 0; fi
  fi
  # fall back to whoever holds the port
  lsof -ti tcp:"$PORT" 2>/dev/null | head -1
}

health() { curl -fsS --max-time 10 "http://127.0.0.1:$PORT/api/tickers" >/dev/null 2>&1; }

start() {
  local pid; pid="$(running_pid)"
  if [ -n "$pid" ]; then
    echo "already running (pid $pid) → http://localhost:$PORT/mobile"
    return 0
  fi

  if [ ! -x "$UVICORN" ]; then
    echo "Setting up the virtualenv first..."
    python3 -m venv "$DIR/.venv" || { echo "could not create .venv"; exit 1; }
    "$DIR/.venv/bin/pip" install -q --upgrade pip
    "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt" || { echo "dependency install failed"; exit 1; }
  fi

  echo "Starting on $HOST:$PORT ..."
  nohup "$UVICORN" dashboard:app --host "$HOST" --port "$PORT" --log-level info \
        >> "$LOGFILE" 2>&1 &
  echo $! > "$PIDFILE"
  disown 2>/dev/null || true

  for _ in $(seq 1 30); do
    sleep 1
    if health; then
      echo "✔ up (pid $(cat "$PIDFILE"))"
      echo "   trading app : http://localhost:$PORT/mobile"
      echo "   dashboard   : http://localhost:$PORT/"
      if [ "$HOST" = "0.0.0.0" ]; then
        local ip; ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
        [ -n "$ip" ] && echo "   from phone  : http://$ip:$PORT/mobile   (same Wi-Fi)"
      fi
      return 0
    fi
  done

  echo "✘ did not come up within 30s — last log lines:"
  tail -15 "$LOGFILE"
  return 1
}

stop() {
  local pid; pid="$(running_pid)"
  if [ -z "$pid" ]; then echo "not running"; rm -f "$PIDFILE"; return 0; fi
  kill "$pid" 2>/dev/null
  for _ in $(seq 1 10); do
    sleep 1
    kill -0 "$pid" 2>/dev/null || break
  done
  kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
  # The SSE price stream holds connections open, so uvicorn's graceful
  # shutdown can outlive the kill. Wait for the port to actually free up,
  # otherwise a restart fails to bind.
  for _ in $(seq 1 15); do
    lsof -ti tcp:"$PORT" >/dev/null 2>&1 || break
    sleep 1
  done
  lsof -ti tcp:"$PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null
  rm -f "$PIDFILE"
  echo "✔ stopped (pid $pid)"
}

status() {
  local pid; pid="$(running_pid)"
  if [ -z "$pid" ]; then echo "● stopped"; return 1; fi
  echo "● running   pid $pid   port $PORT"
  ps -o etime=,rss= -p "$pid" 2>/dev/null | awk '{printf "  uptime %s   memory %.0f MB\n",$1,$2/1024}'
  if health; then
    echo "  API       ok"
    local q; q="$(curl -fsS --max-time 20 "http://127.0.0.1:$PORT/api/quotes?tickers=EURUSD" 2>/dev/null || true)"
    [ -n "$q" ] && echo "  EUR/USD   $(echo "$q" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[0].get("price"),"(bot feed)")' 2>/dev/null || echo '—')"
  else
    echo "  API       NOT RESPONDING"
  fi
  echo "  app       http://localhost:$PORT/mobile"
}

case "${1:-start}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; sleep 1; start ;;
  status)  status ;;
  logs)    tail -f "$LOGFILE" ;;
  *) echo "usage: ./server.sh {start|stop|restart|status|logs} [port]"; exit 1 ;;
esac
