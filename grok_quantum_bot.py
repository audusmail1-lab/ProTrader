import warnings
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)


@dataclass
class AnalysisResult:
    ticker: str
    signal: str
    price: float
    confidence: int
    regime: str
    oracle_bias: str
    stop_loss: float | None
    take_profit: float | None
    timestamp: str


class GrokQuantumOracleBot:
    def __init__(self):
        self.name = "Grok Quantum Oracle Trading Bot v∞"
        print(f"🚀 {self.name} initialized. Robust mode loaded.\n")

    def fetch_data(self, ticker="BTC-USD", period="60d", interval="1h"):
        df = yf.download(
            tickers=ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            multi_level_index=False,
        )

        if df.empty:
            raise ValueError(f"No data fetched for {ticker}. Check ticker, internet, or market hours.")

        df = df.copy()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        df = df[required].copy()
        df = df.sort_index()
        df["Returns"] = df["Close"].pct_change()
        return df

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        close = df["Close"]
        high = df["High"]
        low = df["Low"]

        df["SMA_20"] = close.rolling(20, min_periods=20).mean()
        df["SMA_50"] = close.rolling(50, min_periods=50).mean()

        df["EMA_12"] = close.ewm(span=12, adjust=False).mean()
        df["EMA_26"] = close.ewm(span=26, adjust=False).mean()
        df["MACD"] = df["EMA_12"] - df["EMA_26"]
        df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_Hist"] = df["MACD"] - df["Signal"]

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["RSI"] = 100 - (100 / (1 + rs))

        bb_mid = close.rolling(20, min_periods=20).mean()
        bb_std = close.rolling(20, min_periods=20).std()
        df["BB_Mid"] = bb_mid
        df["BB_Upper"] = bb_mid + 2 * bb_std
        df["BB_Lower"] = bb_mid - 2 * bb_std

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["ATR"] = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

        df["Momentum_5"] = close.pct_change(5)
        df["Momentum_20"] = close.pct_change(20)
        df["Volatility_20"] = df["Returns"].rolling(20, min_periods=20).std()

        return df.dropna().copy()

    def score_signal(self, df: pd.DataFrame) -> tuple[int, list[str]]:
        latest = df.iloc[-1]
        score = 0
        reasons = []

        if latest["Close"] > latest["SMA_20"]:
            score += 15
            reasons.append("price > SMA20")
        if latest["SMA_20"] > latest["SMA_50"]:
            score += 20
            reasons.append("SMA20 > SMA50")
        if latest["MACD"] > latest["Signal"]:
            score += 20
            reasons.append("MACD bullish")
        if 45 <= latest["RSI"] <= 65:
            score += 10
            reasons.append("RSI healthy")
        elif latest["RSI"] < 30:
            score += 15
            reasons.append("RSI oversold")
        elif latest["RSI"] > 70:
            score -= 15
            reasons.append("RSI overbought")

        if latest["Close"] < latest["BB_Lower"]:
            score += 10
            reasons.append("below lower Bollinger band")
        elif latest["Close"] > latest["BB_Upper"]:
            score -= 10
            reasons.append("above upper Bollinger band")

        if latest["Momentum_5"] > 0:
            score += 10
            reasons.append("5-bar momentum up")
        else:
            score -= 10
            reasons.append("5-bar momentum down")

        score = max(0, min(100, score + 20))
        return score, reasons

    def oracle_signal(self, df: pd.DataFrame) -> int:
        latest = df.iloc[-1]

        bullish_votes = 0
        bearish_votes = 0

        bullish_votes += int(latest["Close"] > latest["SMA_20"])
        bullish_votes += int(latest["SMA_20"] > latest["SMA_50"])
        bullish_votes += int(latest["MACD"] > latest["Signal"])
        bullish_votes += int(latest["Momentum_5"] > 0)

        bearish_votes += int(latest["Close"] < latest["SMA_20"])
        bearish_votes += int(latest["SMA_20"] < latest["SMA_50"])
        bearish_votes += int(latest["MACD"] < latest["Signal"])
        bearish_votes += int(latest["Momentum_5"] < 0)

        return 1 if bullish_votes >= bearish_votes else -1

    def market_regime(self, df: pd.DataFrame) -> str:
        latest = df.iloc[-1]

        if latest["Close"] > latest["SMA_50"] and latest["Momentum_20"] > 0:
            return "BULLISH"
        if latest["Close"] < latest["SMA_50"] and latest["Momentum_20"] < 0:
            return "BEARISH"
        return "SIDEWAYS"

    def risk_levels(self, price: float, atr: float, signal: str) -> tuple[float | None, float | None]:
        if pd.isna(atr) or atr <= 0:
            return None, None

        if signal == "STRONG BUY":
            stop_loss = price - (1.5 * atr)
            take_profit = price + (3.0 * atr)
        elif signal == "STRONG SELL":
            stop_loss = price + (1.5 * atr)
            take_profit = price - (3.0 * atr)
        else:
            return None, None

        return float(stop_loss), float(take_profit)

    def analyze(self, ticker="BTC-USD", period="60d", interval="1h") -> AnalysisResult:
        print(f"🔮 Analyzing {ticker} with disciplined multiverse engines...\n")

        df = self.fetch_data(ticker=ticker, period=period, interval=interval)
        df = self.calculate_indicators(df)

        if len(df) < 60:
            raise ValueError("Not enough processed rows to analyze reliably.")

        latest = df.iloc[-1]
        current_price = float(latest["Close"])

        confidence, reasons = self.score_signal(df)
        oracle = self.oracle_signal(df)
        regime = self.market_regime(df)

        if (
            latest["Close"] > latest["SMA_20"]
            and latest["SMA_20"] > latest["SMA_50"]
            and latest["MACD"] > latest["Signal"]
            and latest["RSI"] < 70
            and oracle > 0
        ):
            signal = "STRONG BUY"
        elif (
            latest["Close"] < latest["SMA_20"]
            and latest["SMA_20"] < latest["SMA_50"]
            and latest["MACD"] < latest["Signal"]
            and latest["RSI"] > 30
            and oracle < 0
        ):
            signal = "STRONG SELL"
        else:
            signal = "HOLD / WAIT"

        stop_loss, take_profit = self.risk_levels(current_price, float(latest["ATR"]), signal)
        oracle_bias = "BULLISH" if oracle > 0 else "BEARISH"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        print(f"📊 {ticker} @ {current_price:.2f} ({ts})")
        print(f"🚨 TRADE IDEA: {signal}")
        print(f"🔥 Confidence: {confidence}%")
        print(f"🌌 Market Regime: {regime}")
        print(f"🧠 Oracle Bias: {oracle_bias}")
        print(f"📝 Drivers: {', '.join(reasons[:5])}")

        if signal != "HOLD / WAIT":
            print(f"📍 Entry ≈ {current_price:.2f}")
            print(f"🛑 Stop-Loss: {stop_loss:.2f}")
            print(f"🎯 Take-Profit: {take_profit:.2f}")

        print("\n⚠️ For research/education only. Real trading has risk.\n")

        return AnalysisResult(
            ticker=ticker,
            signal=signal,
            price=current_price,
            confidence=confidence,
            regime=regime,
            oracle_bias=oracle_bias,
            stop_loss=stop_loss,
            take_profit=take_profit,
            timestamp=ts,
        )


class TradingBot:
    """
    Engine used by the dashboard API (dashboard.py).

    Same maths as GrokQuantumOracleBot, but exposes the column names and
    helper methods the API layer expects: Signal_Line / Momentum columns,
    plus momentum_signal, generate_signal and calculate_stops.
    """

    # yfinance has no native 4h bar — fetch 1h and resample.
    RESAMPLE_FROM = {"4h": ("1h", "4h")}

    def __init__(self):
        self.name = "Trading Bot Engine"

    @staticmethod
    def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
        out = df.resample(rule).agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        })
        return out.dropna(subset=["Open", "High", "Low", "Close"])

    def fetch_data(self, ticker="BTC-USD", period="60d", interval="1h") -> pd.DataFrame:
        fetch_interval, rule = self.RESAMPLE_FROM.get(interval, (interval, None))

        df = yf.download(
            tickers=ticker,
            period=period,
            interval=fetch_interval,
            auto_adjust=False,
            progress=False,
            multi_level_index=False,
        )

        if df is None or df.empty:
            raise ValueError(f"No data fetched for {ticker}. Check ticker, internet, or market hours.")

        df = df.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        df = df[required].copy().sort_index()

        if rule:
            df = self._resample(df, rule)

        df["Returns"] = df["Close"].pct_change()
        return df

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        close, high, low = df["Close"], df["High"], df["Low"]

        df["SMA_20"] = close.rolling(20, min_periods=20).mean()
        df["SMA_50"] = close.rolling(50, min_periods=50).mean()

        df["EMA_12"] = close.ewm(span=12, adjust=False).mean()
        df["EMA_26"] = close.ewm(span=26, adjust=False).mean()
        df["MACD"] = df["EMA_12"] - df["EMA_26"]
        df["Signal_Line"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_Hist"] = df["MACD"] - df["Signal_Line"]

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["RSI"] = (100 - (100 / (1 + rs))).fillna(50)

        bb_mid = close.rolling(20, min_periods=20).mean()
        bb_std = close.rolling(20, min_periods=20).std()
        df["BB_Mid"] = bb_mid
        df["BB_Upper"] = bb_mid + 2 * bb_std
        df["BB_Lower"] = bb_mid - 2 * bb_std

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        df["ATR"] = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()

        # Fractional 5-bar momentum — the API multiplies this by 100 for display
        # and thresholds it at ±0.02.
        df["Momentum"] = close.pct_change(5)
        df["Momentum_20"] = close.pct_change(20)
        df["Volatility_20"] = df["Returns"].rolling(20, min_periods=20).std()

        return df.dropna().copy()

    def momentum_signal(self, df: pd.DataFrame) -> int:
        """Directional momentum vote: +1 bullish, -1 bearish, 0 flat."""
        if df.empty:
            return 0
        latest = df.iloc[-1]
        mom = float(latest["Momentum"])
        if mom > 0.02:
            return 1
        if mom < -0.02:
            return -1
        # Weak momentum — break the tie on the 20-bar trend
        mom20 = float(latest["Momentum_20"])
        if mom20 > 0:
            return 1
        if mom20 < 0:
            return -1
        return 0

    def generate_signal(self, latest, momentum: int = 0) -> str:
        """Returns 'STRONG BUY', 'STRONG SELL' or 'HOLD'."""
        close = float(latest["Close"])
        sma20 = float(latest["SMA_20"])
        sma50 = float(latest["SMA_50"])
        macd = float(latest["MACD"])
        sig_line = float(latest["Signal_Line"])
        rsi = float(latest["RSI"])

        if close > sma20 > sma50 and macd > sig_line and rsi < 70 and momentum >= 0:
            return "STRONG BUY"
        if close < sma20 < sma50 and macd < sig_line and rsi > 30 and momentum <= 0:
            return "STRONG SELL"
        return "HOLD"

    def calculate_stops(self, price: float, atr: float, signal: str):
        """1.5x ATR stop, 3x ATR target. (None, None) on HOLD."""
        if atr is None or pd.isna(atr) or atr <= 0:
            return None, None
        if "BUY" in signal:
            return round(price - 1.5 * atr, 4), round(price + 3.0 * atr, 4)
        if "SELL" in signal:
            return round(price + 1.5 * atr, 4), round(price - 3.0 * atr, 4)
        return None, None


if __name__ == "__main__":
    bot = GrokQuantumOracleBot()
    result = bot.analyze("BTC-USD", period="60d", interval="1h")
    print(result)
