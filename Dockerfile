# ─────────────────────────────────────────────────────────────────────────────
#  Trading Bot — container image
#
#  Runs the FastAPI dashboard + PROTrader mobile terminal. Portable to any
#  host that runs containers: Render, Fly.io, Railway, a VPS, your own NAS.
#
#    docker build -t trading-bot .
#    docker run -p 8000:8000 trading-bot
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Fail fast, no .pyc litter, unbuffered logs so the host captures them live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# curl is only for the health check below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Dependencies first so they cache separately from the app source.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App source. .dockerignore keeps logs, venv and pid files out.
COPY dashboard.py mt5_bridge.py grok_quantum_bot.py protrader_mobile.html chart_lab.html ./
COPY vendor ./vendor
COPY static ./static

# Run as a non-root user.
RUN useradd --create-home --shell /usr/sbin/nologin app && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/tickers" || exit 1

# Hosts like Render/Railway inject $PORT — honour it. Single worker on purpose:
# in-memory state (quote cache, alerts, history cache) lives in one process.
CMD ["sh", "-c", "uvicorn dashboard:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
