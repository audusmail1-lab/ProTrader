"""V50 (1s) 9:00 PM WAT Retracement Monitor — unified Streamlit app.

Single-file framework combining two components running in sync:
  * Background Monitor Thread — the asyncio WebSocket engine that watches the
    Deriv tick stream 24/7 and fires Telegram alerts.
  * Streamlit Web UI — the live dashboard rendering session metrics from the
    shared SQLite database.

When Streamlit runs this script it spins up the bot on a daemon thread
automatically (once, via @st.cache_resource) if it isn't already running.

Install:  pip install -r requirements-monitor.txt
Run:      streamlit run app.py
"""

import streamlit as st
import asyncio
import json
import sqlite3
import threading
import websockets
import aiohttp
import pandas as pd
import plotly.express as px
from datetime import datetime, time, timezone, timedelta
from websockets.exceptions import ConnectionClosed, WebSocketException
import os

# --- 1. CONFIGURATION ---
# Replace these with your actual Telegram keys, or set them as environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID_HERE')
APP_ID = '1089'
SYMBOL = '1HZ50V'
WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
MIN_DEVIATION = 0.50

# Enforce West Africa Time (WAT = UTC+1) for server deployments
WAT = timezone(timedelta(hours=1))

# Shared memory state for the bot (persists across WebSocket reconnects)
bot_state = {
    "reference_price": None,
    "has_moved_away": False,
    "alert_triggered_today": False,
    "max_excursion": 0.0,
    "status": "Initializing..."
}

# --- 2. DATABASE SYSTEM ---
def init_db():
    """Initializes the SQLite database."""
    conn = sqlite3.connect('retracement_data.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_metrics (
            date TEXT PRIMARY KEY,
            reference_price REAL,
            max_excursion REAL,
            retracement_time TEXT,
            result TEXT
        )
    ''')
    conn.commit()
    conn.close()

def log_session(date_str, ref_price, max_excursion, r_time, result):
    """Records the outcome of the 9 PM to 9:30 PM session."""
    conn = sqlite3.connect('retracement_data.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO daily_metrics
        (date, reference_price, max_excursion, retracement_time, result)
        VALUES (?, ?, ?, ?, ?)
    ''', (date_str, ref_price, max_excursion, r_time, result))
    conn.commit()
    conn.close()

# --- 3. TELEGRAM ENGINE ---
async def send_telegram_alert(message: str):
    """Fires non-blocking HTTP requests to the Telegram API."""
    if TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        return  # Skip if not configured

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}

    async with aiohttp.ClientSession() as session:
        try:
            await session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5))
        except Exception as e:
            print(f"Telegram Delivery Failed: {e}")

# --- 4. WEBSOCKET ALGO ENGINE ---
async def keep_alive(ws):
    """Prevents Deriv from dropping the connection due to inactivity."""
    while True:
        try:
            await asyncio.sleep(30)
            await ws.send(json.dumps({"ping": 1}))
        except (ConnectionClosed, WebSocketException, asyncio.CancelledError):
            break

async def process_tick_stream(ws):
    """Main pattern recognition and execution loop."""
    await ws.send(json.dumps({"ticks": SYMBOL, "subscribe": 1}))
    bot_state["status"] = f"🟢 Connected & Monitoring {SYMBOL}"

    while True:
        raw_msg = await ws.recv()
        data = json.loads(raw_msg)

        if 'tick' in data:
            price = data['tick']['quote']
            epoch = data['tick']['epoch']

            # Convert tick UTC epoch directly to WAT
            dt_now = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(WAT)
            time_now = dt_now.time()
            today_str = str(dt_now.date())

            # 9:30 PM: Time Expiry & System Reset
            if time_now >= time(21, 30):
                if bot_state["reference_price"] is not None:
                    # Log a loss if we reached 9:30 without a retracement alert
                    if not bot_state["alert_triggered_today"]:
                        log_session(today_str, bot_state["reference_price"], bot_state["max_excursion"], "N/A", "LOSS")

                    bot_state["status"] = "⏳ Waiting for next 9:00 PM session."
                    bot_state["reference_price"] = None
                    bot_state["has_moved_away"] = False
                    bot_state["alert_triggered_today"] = False
                    bot_state["max_excursion"] = 0.0

            # 9:00 PM to 9:30 PM: Active Monitoring Window
            elif time(21, 0) <= time_now < time(21, 30):
                bot_state["status"] = f"🎯 Active Window: Price at {price}"

                # Lock Target
                if bot_state["reference_price"] is None:
                    bot_state["reference_price"] = price
                    bot_state["has_moved_away"] = False
                    bot_state["alert_triggered_today"] = False
                    bot_state["max_excursion"] = 0.0

                    lock_msg = f"🔒 Target Locked: {SYMBOL} at {price:.2f} (9:00 PM WAT)"
                    print(lock_msg)
                    await send_telegram_alert(lock_msg)

                # Track Max Excursion
                ref = bot_state["reference_price"]
                current_deviation = abs(price - ref)
                if current_deviation > bot_state["max_excursion"]:
                    bot_state["max_excursion"] = current_deviation

                # Validate Movement
                if not bot_state["has_moved_away"] and current_deviation >= MIN_DEVIATION:
                    bot_state["has_moved_away"] = True

                # Detect Retracement
                if bot_state["has_moved_away"] and not bot_state["alert_triggered_today"]:
                    if abs(price - ref) < 0.05:  # Allow small slippage tolerance
                        alert_msg = f"⚠️ RETRACEMENT DETECTED! {SYMBOL} returned to {ref:.2f} at {time_now.strftime('%H:%M:%S')}"
                        print(alert_msg)
                        await send_telegram_alert(alert_msg)

                        log_session(today_str, ref, bot_state["max_excursion"], time_now.strftime('%H:%M:%S'), "WIN")
                        bot_state["alert_triggered_today"] = True

async def bot_supervisor():
    """Manages reconnects and exponential backoff."""
    retry_delay = 2
    max_delay = 60

    await send_telegram_alert(f"⚙️ Algorithmic Subsystem Booted for {SYMBOL}.")

    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=None) as ws:
                retry_delay = 2  # Reset delay on success

                ping_task = asyncio.create_task(keep_alive(ws))
                stream_task = asyncio.create_task(process_tick_stream(ws))

                done, pending = await asyncio.wait([ping_task, stream_task], return_when=asyncio.FIRST_EXCEPTION)
                for task in pending:
                    task.cancel()
                # Surface the failed task's exception so the reconnect path runs
                for task in done:
                    exc = task.exception()
                    if exc is not None:
                        raise exc

        except (ConnectionClosed, WebSocketException, OSError) as e:
            bot_state["status"] = f"⚠️ Connection Lost. Retrying in {retry_delay}s..."
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_delay)
        except Exception as e:
            bot_state["status"] = f"❌ Fatal Error: {e}"
            await asyncio.sleep(max_delay)

# --- 5. THREAD LAUNCHER ---
@st.cache_resource
def start_background_bot():
    """Runs the asyncio loop in a daemon thread so Streamlit doesn't block."""
    init_db()
    def run_async():
        asyncio.run(bot_supervisor())

    thread = threading.Thread(target=run_async, daemon=True)
    thread.start()
    return thread

# Boot the bot thread if it isn't running already
start_background_bot()

# --- 6. STREAMLIT DASHBOARD UI ---
st.set_page_config(page_title="V50 Algo Monitor", layout="wide")
st.title(f"⚡ {SYMBOL} - 9:00 PM WAT Retracement Monitor")

# Live Bot Status Banner
st.info(f"**Bot Engine Status:** {bot_state['status']}")

# Load Database Stats
def load_data():
    try:
        conn = sqlite3.connect('retracement_data.db')
        df = pd.read_sql_query("SELECT * FROM daily_metrics", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

df = load_data()

if df.empty:
    st.warning("Database is empty. Leave this running to collect data tonight.")
else:
    total_days = len(df)
    wins = len(df[df['result'] == 'WIN'])
    win_rate = (wins / total_days) * 100 if total_days > 0 else 0
    avg_excursion = df['max_excursion'].mean()

    # Top Metrics Cards
    col1, col2, col3 = st.columns(3)
    col1.metric("Tracked Sessions", total_days)
    col2.metric("System Win Rate", f"{win_rate:.1f}%")
    col3.metric("Avg Max Excursion", f"{avg_excursion:.2f}")

    st.markdown("---")

    # Data Visualization
    col_chart, col_table = st.columns([1, 1])

    with col_chart:
        st.subheader("Maximum Excursion by Day")
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        fig = px.bar(
            df, x='date', y='max_excursion', color='result',
            color_discrete_map={'WIN': '#00CC96', 'LOSS': '#EF553B'},
            labels={'max_excursion': 'Max Move from 9 PM Open', 'date': 'Session Date'}
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_table:
        st.subheader("Execution Log")
        display_df = df.copy()
        display_df['date'] = display_df['date'].dt.strftime('%Y-%m-%d')
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Manual Refresh Button
    if st.button("🔄 Refresh Data"):
        st.rerun()
