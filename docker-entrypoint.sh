#!/bin/sh
# Starts as root, makes the persistent disk writable by the app user, drops
# privileges, runs the server. A host (Render, Fly) mounts the disk at
# /var/data owned by root; without this step the app user cannot open its
# SQLite files there and every module silently falls back to the container's
# ephemeral disk — the very thing the disk is meant to prevent.
set -e
if [ "$(id -u)" = "0" ]; then
  mkdir -p /var/data
  chown app:app /var/data 2>/dev/null || true
  # files an earlier root-run deploy may have left behind
  find /var/data -maxdepth 1 -type f ! -user app -exec chown app:app {} + 2>/dev/null || true
  if command -v setpriv >/dev/null 2>&1; then
    exec setpriv --reuid=app --regid=app --init-groups "$@"
  fi
  exec su -s /bin/sh app -c 'exec "$0" "$@"' -- "$@"
fi
exec "$@"
