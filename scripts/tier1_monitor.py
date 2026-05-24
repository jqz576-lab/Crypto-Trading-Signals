#!/usr/bin/env python3
"""
21 Tier-1 strategy signal monitor (TradingView-aligned).

Reference: Minara — "We Found 21 Money-Makers After Backtesting 236 TradingView Strategies"
https://minara.ai/blog/we-found-21-money-makers-after-backtesting-236-tradingview-strategies/

Signals use the last *closed* candle (klines[-2]) to avoid repainting on the open bar.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Callable, List, Optional, Sequence, Tuple

import requests

# ===== Configuration =====
DOTENV = os.environ.get("TIER1_DOTENV", "/root/.hermes/.env")
_DEFAULT_STATE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "tier1_monitor_state.json"
)
STATE_FILE = os.environ.get("TIER1_STATE_FILE", _DEFAULT_STATE)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
THREAD_ID = os.environ.get("TELEGRAM_THREAD_ID", "205")
KLINES_LIMIT = 500

Signal = str  # "LONG", "SHORT", "FLAT"


def load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


load_dotenv(DOTENV)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)


# ===== Telegram =====
def send_telegram(msg: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TG SKIP] {msg[:120]}...")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "message_thread_id": THREAD_ID,
        "text": msg,
        "parse_mode": "HTML",
    }
    try:
        requests.post(url, data=data, timeout=15)
    except Exception as exc:
        print(f"[TG ERROR] {exc}")


# ===== Binance =====
BINANCE_KLINE_URLS = (
    "https://api.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",
)


def get_klines(symbol: str, interval: str, limit: int = KLINES_LIMIT):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    last_err = None
    for base in BINANCE_KLINE_URLS:
        try:
            resp = requests.get(base, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                return data
        except Exception as exc:
            last_err = exc
    print(f"[BINANCE ERROR] {symbol} {interval}: {last_err}")
    return None


def ohlc(klines) -> Tuple[List[float], List[float], List[float], List[float]]:
    opens = [float(k[1]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    return opens, highs, lows, closes


# ===== Indicators (Pine-aligned where noted) =====
def ema_series(values: Sequence[float], period: int) -> List[Optional[float]]:
    if len(values) < period:
        return [None] * len(values)
    alpha = 2.0 / (period + 1)
    out: List[Optional[float]] = [None] * (period - 1)
    seed = sum(values[:period]) / period
    out.append(seed)
    prev = seed
    for v in values[period:]:
        prev = v * alpha + prev * (1 - alpha)
        out.append(prev)
    return out


def sma_series(values: Sequence[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    window_sum = sum(values[:period])
    out[period - 1] = window_sum / period
    for i in range(period, len(values)):
        window_sum += values[i] - values[i - period]
        out[i] = window_sum / period
    return out


def true_range(highs, lows, closes) -> List[float]:
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    return tr


def rsi_wilder(closes: Sequence[float], period: int = 14) -> List[Optional[float]]:
    """RSI with Wilder smoothing (ta.rsi)."""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        idx = i + 1
        if avg_loss == 0:
            out[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[idx] = 100.0 - (100.0 / (1.0 + rs))
    return out


def stochastic_k(
    highs, lows, closes, k_period: int = 14, smooth: int = 3
) -> List[Optional[float]]:
    raw: List[Optional[float]] = [None] * len(closes)
    for i in range(k_period - 1, len(closes)):
        hh = max(highs[i - k_period + 1 : i + 1])
        ll = min(lows[i - k_period + 1 : i + 1])
        if hh == ll:
            raw[i] = 50.0
        else:
            raw[i] = 100.0 * (closes[i] - ll) / (hh - ll)
    # %K = SMA of raw over smooth
    valid = [v if v is not None else 0.0 for v in raw]
    return sma_series(valid, smooth)


def macd_line_series(
    closes: Sequence[float], fast: int = 12, slow: int = 26
) -> List[Optional[float]]:
    ef = ema_series(closes, fast)
    es = ema_series(closes, slow)
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(len(closes)):
        if ef[i] is None or es[i] is None:
            continue
        out[i] = ef[i] - es[i]
    return out


def macd_signal_series(
    closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> List[Optional[float]]:
    line = macd_line_series(closes, fast, slow)
    compact = [v if v is not None else 0.0 for v in line]
    sig = ema_series(compact, signal)
    out: List[Optional[float]] = [None] * len(closes)
    for i, s in enumerate(sig):
        if line[i] is None or s is None:
            continue
        out[i] = s
    return out


def bollinger(
    closes: Sequence[float], length: int = 20, mult: float = 2.0
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    mid = sma_series(closes, length)
    upper, lower = [None] * len(closes), [None] * len(closes)
    for i in range(length - 1, len(closes)):
        window = closes[i - length + 1 : i + 1]
        m = mid[i]
        if m is None:
            continue
        var = sum((x - m) ** 2 for x in window) / length
        std = var**0.5
        upper[i] = m + mult * std
        lower[i] = m - mult * std
    return upper, mid, lower


def supertrend_direction(
    highs,
    lows,
    closes,
    period: int = 10,
    multiplier: float = 3.0,
    atr_mode: str = "sma",
) -> List[int]:
    """SuperTrend direction (+1 bull / -1 bear). SMA ATR, source hl2 (TV script VLRj2sG9)."""
    n = len(closes)
    src = [(highs[i] + lows[i]) / 2.0 for i in range(n)]
    tr = true_range(highs, lows, closes)
    if atr_mode == "sma":
        atr = sma_series(tr, period)
    else:
        # Wilder ATR fallback
        atr = [None] * n
        if n >= period:
            first = sum(tr[:period]) / period
            atr[period - 1] = first
            prev = first
            for i in range(period, n):
                prev = (prev * (period - 1) + tr[i]) / period
                atr[i] = prev

    direction = [1] * n
    final_upper = [0.0] * n
    final_lower = [0.0] * n

    for i in range(n):
        if atr[i] is None:
            direction[i] = direction[i - 1] if i else 1
            continue
        basic_upper = src[i] + multiplier * atr[i]
        basic_lower = src[i] - multiplier * atr[i]
        if i == 0:
            final_upper[i] = basic_upper
            final_lower[i] = basic_lower
            direction[i] = 1
            continue
        final_upper[i] = (
            basic_upper
            if basic_upper < final_upper[i - 1] or closes[i - 1] > final_upper[i - 1]
            else final_upper[i - 1]
        )
        final_lower[i] = (
            basic_lower
            if basic_lower > final_lower[i - 1] or closes[i - 1] < final_lower[i - 1]
            else final_lower[i - 1]
        )
        if closes[i] > final_upper[i - 1]:
            direction[i] = 1
        elif closes[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return direction


def cross_above(prev_a, curr_a, prev_b, curr_b) -> bool:
    return prev_a is not None and curr_a is not None and prev_b is not None and curr_b is not None and prev_a <= prev_b and curr_a > curr_b


def cross_below(prev_a, curr_a, prev_b, curr_b) -> bool:
    return prev_a is not None and curr_a is not None and prev_b is not None and curr_b is not None and prev_a >= prev_b and curr_a < curr_b


def confirmed_indices() -> Tuple[int, int]:
    """Index of last closed bar and the one before it."""
    return -2, -3


# ===== Strategy checks =====
def _need(klines, min_bars: int) -> bool:
    return klines is not None and len(klines) >= min_bars


def check_01_mean_reversion(klines) -> Signal:
    """RSI 20/65 + Stochastic + EMA200 filter (malli_007)."""
    if not _need(klines, 220):
        return "FLAT"
    _, highs, lows, closes = ohlc(klines)
    i, j = confirmed_indices()
    rsi = rsi_wilder(closes)
    stoch = stochastic_k(highs, lows, closes)
    ema200 = ema_series(closes, 200)
    if any(x[i] is None for x in (rsi, stoch, ema200)):
        return "FLAT"
    if rsi[i] < 20 and stoch[i] < 25 and closes[i] > ema200[i]:
        return "LONG"
    if rsi[i] > 65 and stoch[i] > 75 and closes[i] < ema200[i]:
        return "SHORT"
    return "FLAT"


def check_02_volatility_breakout(klines) -> Signal:
    """Donchian / range breakout proxy for Volatility Breakout System [ETH 1h]."""
    if not _need(klines, 50):
        return "FLAT"
    _, highs, lows, closes = ohlc(klines)
    i, _ = confirmed_indices()
    lookback = 20
    if i < -lookback:
        return "FLAT"
    slice_end = len(closes) + i
    prev_high = max(highs[slice_end - lookback : slice_end])
    prev_low = min(lows[slice_end - lookback : slice_end])
    if closes[i] > prev_high:
        return "LONG"
    if closes[i] < prev_low:
        return "SHORT"
    return "FLAT"


def check_03_supertrend_ai(klines) -> Signal:
    """
    SuperTrend AI Adaptive [BTC 4h] — monitor layer uses core SuperTrend flip
    with EMA50 trend filter (full AI score/regime engine not replicated offline).
    """
    if not _need(klines, 120):
        return "FLAT"
    _, highs, lows, closes = ohlc(klines)
    i, j = confirmed_indices()
    st = supertrend_direction(highs, lows, closes, period=10, multiplier=3.0)
    ema50 = ema_series(closes, 50)
    if ema50[i] is None:
        return "FLAT"
    if st[j] <= 0 and st[i] > 0 and closes[i] > ema50[i]:
        return "LONG"
    if st[j] >= 0 and st[i] < 0 and closes[i] < ema50[i]:
        return "SHORT"
    if st[i] > 0:
        return "LONG"
    if st[i] < 0:
        return "SHORT"
    return "FLAT"


def check_05_supertrend_daily(klines) -> Signal:
    """SuperTrend STRATEGY — BTC 1d, ATR SMA 10, multiplier 8.5, long only."""
    if not _need(klines, 50):
        return "FLAT"
    _, highs, lows, closes = ohlc(klines)
    i, j = confirmed_indices()
    st = supertrend_direction(highs, lows, closes, period=10, multiplier=8.5)
    if st[i] > 0:
        return "LONG"
    return "FLAT"


def check_07_macd_zero(klines) -> Signal:
    """MACD line cross above/below 0 (long only)."""
    if not _need(klines, 80):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, j = confirmed_indices()
    macd = macd_line_series(closes)
    if macd[i] is None or macd[j] is None:
        return "FLAT"
    if macd[j] <= 0 < macd[i]:
        return "LONG"
    if macd[i] > 0:
        return "LONG"
    return "FLAT"


def check_11_ema_cross(klines) -> Signal:
    """7 EMA cross 19 EMA (ETH 30m)."""
    if not _need(klines, 40):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, j = confirmed_indices()
    e7 = ema_series(closes, 7)
    e19 = ema_series(closes, 19)
    if e7[i] is None or e19[i] is None or e7[j] is None or e19[j] is None:
        return "FLAT"
    if cross_above(e7[j], e7[i], e19[j], e19[i]):
        return "LONG"
    if cross_below(e7[j], e7[i], e19[j], e19[i]):
        return "SHORT"
    if e7[i] > e19[i]:
        return "LONG"
    if e7[i] < e19[i]:
        return "SHORT"
    return "FLAT"


def check_12_rsi70(klines) -> Signal:
    """RSI cross above 70 enter; cross below 70 exit (momentum long)."""
    if not _need(klines, 30):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, j = confirmed_indices()
    rsi = rsi_wilder(closes)
    if rsi[i] is None or rsi[j] is None:
        return "FLAT"
    if cross_above(rsi[j], rsi[i], 70.0, 70.0) or rsi[i] > 70:
        return "LONG"
    return "FLAT"


def check_04_bb_short(klines) -> Signal:
    """BB upper +2% breakout short (SOL 1h)."""
    if not _need(klines, 30):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, _ = confirmed_indices()
    upper, _, _ = bollinger(closes, 20, 2.0)
    if upper[i] is None:
        return "FLAT"
    if closes[i] >= upper[i] * 1.02:
        return "SHORT"
    return "FLAT"


def check_08_cdc_macd(klines) -> Signal:
    """CDC MACD fix — MACD signal cross (proxy: MACD/signal crossover)."""
    if not _need(klines, 80):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, j = confirmed_indices()
    line = macd_line_series(closes)
    sig = macd_signal_series(closes)
    if line[i] is None or sig[i] is None or line[j] is None or sig[j] is None:
        return "FLAT"
    if cross_above(line[j], line[i], sig[j], sig[i]):
        return "LONG"
    if line[i] > sig[i]:
        return "LONG"
    return "FLAT"


def check_09_hash_momentum(klines) -> Signal:
    """12-bar momentum positive & accelerating (long)."""
    if not _need(klines, 20):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, j = confirmed_indices()
    mom = lambda idx: closes[idx] - closes[idx - 12]
    if i < 12 or j < 12:
        return "FLAT"
    m0, m1 = mom(i), mom(j)
    if m0 > 0 and m1 > 0 and m0 > m1:
        return "LONG"
    if m0 < 0 and m1 < 0:
        return "SHORT"
    return "FLAT"


def check_13_sma_rsi(klines) -> Signal:
    """50/200 SMA + smoothed RSI(21) average > 57 (muratkbesiroglu, long only)."""
    if not _need(klines, 220):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, _ = confirmed_indices()
    sma50 = sma_series(closes, 50)
    sma200 = sma_series(closes, 200)
    rsi21 = rsi_wilder(closes, 21)
    rsi_avg = sma_series([v if v is not None else 0.0 for v in rsi21], 9)
    if sma50[i] is None or sma200[i] is None or rsi_avg[i] is None:
        return "FLAT"
    if closes[i] > sma50[i] and closes[i] > sma200[i] and rsi_avg[i] > 57:
        return "LONG"
    return "FLAT"


def check_15_keltner_breakout(klines) -> Signal:
    """Keltner channel breakout proxy (EMA20 +/- 1.5*ATR)."""
    if not _need(klines, 60):
        return "FLAT"
    _, highs, lows, closes = ohlc(klines)
    i, j = confirmed_indices()
    mid = ema_series(closes, 20)
    tr = true_range(highs, lows, closes)
    atr = sma_series(tr, 10)
    if mid[i] is None or atr[i] is None or mid[j] is None or atr[j] is None:
        return "FLAT"
    upper_i = mid[i] + 1.5 * atr[i]
    lower_i = mid[i] - 1.5 * atr[i]
    if closes[j] <= mid[j] + 1.5 * atr[j] and closes[i] > upper_i:
        return "LONG"
    if closes[j] >= mid[j] - 1.5 * atr[j] and closes[i] < lower_i:
        return "SHORT"
    return "FLAT"


def check_16_hash_supertrend(klines) -> Signal:
    """Hash Supertrend — standard SuperTrend on SOL 4h."""
    if not _need(klines, 50):
        return "FLAT"
    _, highs, lows, closes = ohlc(klines)
    i, _ = confirmed_indices()
    st = supertrend_direction(highs, lows, closes, period=10, multiplier=3.0)
    return "LONG" if st[i] > 0 else "SHORT" if st[i] < 0 else "FLAT"


def check_14_pivot_supertrend(klines) -> Signal:
    """Pivot SuperTrend proxy — SuperTrend + price above daily pivot."""
    if not _need(klines, 50):
        return "FLAT"
    _, highs, lows, closes = ohlc(klines)
    i, _ = confirmed_indices()
    st = supertrend_direction(highs, lows, closes, period=10, multiplier=3.0)
    pivot = (highs[i] + lows[i] + closes[i]) / 3.0
    if st[i] > 0 and closes[i] > pivot:
        return "LONG"
    if st[i] < 0 and closes[i] < pivot:
        return "SHORT"
    return "FLAT"


def check_06_penguin_volatility(klines) -> Signal:
    """Volatility state — ATR percentile expansion (simplified)."""
    if not _need(klines, 100):
        return "FLAT"
    _, highs, lows, closes = ohlc(klines)
    i, _ = confirmed_indices()
    tr = true_range(highs, lows, closes)
    atr = sma_series(tr, 14)
    if atr[i] is None:
        return "FLAT"
    hist = [a for a in atr[-60:] if a is not None]
    if len(hist) < 20:
        return "FLAT"
    rank = sum(1 for a in hist if a <= atr[i]) / len(hist)
    ema50 = ema_series(closes, 50)
    if ema50[i] is None:
        return "FLAT"
    if rank > 0.7 and closes[i] > ema50[i]:
        return "LONG"
    if rank > 0.7 and closes[i] < ema50[i]:
        return "SHORT"
    return "FLAT"


def check_10_moon_phases(klines) -> Signal:
    """Moon phase calendar is not reproducible from OHLC — hold FLAT (manual calendar)."""
    return "FLAT"


def check_17_crypto_long_py(klines) -> Signal:
    """Short-term mean reversion long — RSI oversold bounce (proxy)."""
    if not _need(klines, 30):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, j = confirmed_indices()
    rsi = rsi_wilder(closes, 14)
    if rsi[i] is None or rsi[j] is None:
        return "FLAT"
    if rsi[j] < 30 and rsi[i] >= 30:
        return "LONG"
    return "FLAT"


def check_18_oleg(klines) -> Signal:
    """EMA stack trend proxy (BTC 15m)."""
    if not _need(klines, 60):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, _ = confirmed_indices()
    e9 = ema_series(closes, 9)
    e21 = ema_series(closes, 21)
    e55 = ema_series(closes, 55)
    if e9[i] is None or e21[i] is None or e55[i] is None:
        return "FLAT"
    if e9[i] > e21[i] > e55[i]:
        return "LONG"
    if e9[i] < e21[i] < e55[i]:
        return "SHORT"
    return "FLAT"


def check_19_options_daily(klines) -> Signal:
    """Time-based entry — long during UTC 08:30-08:00 window proxy on 5m."""
    if not _need(klines, 5):
        return "FLAT"
    ts_ms = int(klines[-2][0])
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    minutes = dt.hour * 60 + dt.minute
    # Entry window ~08:30 UTC, hold until next day 08:00
    if 8 * 60 + 30 <= minutes < 24 * 60 or minutes < 8 * 60:
        return "LONG"
    return "FLAT"


def check_20_qullamagi(klines) -> Signal:
    """EMA breakout — close above 20 EMA with rising 50 EMA."""
    if not _need(klines, 60):
        return "FLAT"
    _, highs, _, closes = ohlc(klines)
    i, j = confirmed_indices()
    e20 = ema_series(closes, 20)
    e50 = ema_series(closes, 50)
    if e20[i] is None or e50[i] is None or e50[j] is None:
        return "FLAT"
    if closes[j] <= e20[j] and closes[i] > e20[i] and e50[i] > e50[j]:
        return "LONG"
    if closes[i] < e20[i] and e50[i] < e50[j]:
        return "SHORT"
    return "FLAT"


def check_21_kalman_breakout(klines) -> Signal:
    """Kalman-style breakout proxy: price vs EMA20 + ATR band."""
    if not _need(klines, 50):
        return "FLAT"
    _, highs, lows, closes = ohlc(klines)
    i, j = confirmed_indices()
    mid = ema_series(closes, 20)
    tr = true_range(highs, lows, closes)
    atr = sma_series(tr, 14)
    if mid[i] is None or atr[i] is None or mid[j] is None:
        return "FLAT"
    if closes[j] <= mid[j] and closes[i] > mid[i] + atr[i]:
        return "LONG"
    if closes[j] >= mid[j] and closes[i] < mid[i] - atr[i]:
        return "SHORT"
    return "FLAT"


# ===== Strategy registry (Minara Tier 1 table order) =====
StrategyDef = Tuple[int, str, str, str, Callable, str]

STRATEGIES: List[StrategyDef] = [
    (1, "BTC Mean Reversion RSI 20/65", "BTCUSDT", "15m", check_01_mean_reversion, "https://www.tradingview.com/script/pIrgsDpT/"),
    (2, "Volatility Breakout System", "ETHUSDT", "1h", check_02_volatility_breakout, "https://www.tradingview.com/script/36zwwSMa/"),
    (3, "SuperTrend AI Adaptive", "BTCUSDT", "4h", check_03_supertrend_ai, "https://www.tradingview.com/script/kZVrTReu/"),
    (4, "BB Upper Breakout Short +2%", "SOLUSDT", "1h", check_04_bb_short, "https://www.tradingview.com/script/UBGvlIlq/"),
    (5, "SuperTrend STRATEGY (Daily)", "BTCUSDT", "1d", check_05_supertrend_daily, "https://www.tradingview.com/script/VLRj2sG9/"),
    (6, "Penguin Volatility State", "BTCUSDT", "1d", check_06_penguin_volatility, "https://www.tradingview.com/script/skzo4i9e/"),
    (7, "MACD Zero-Line (Long)", "BTCUSDT", "1d", check_07_macd_zero, "https://www.tradingview.com/script/llTXO45e/"),
    (8, "CDC MACD Fix", "BTCUSDT", "1d", check_08_cdc_macd, "https://www.tradingview.com/script/7nv3hTpO/"),
    (9, "Hash Momentum", "BTCUSDT", "4h", check_09_hash_momentum, "https://www.tradingview.com/script/L6VNlhiV/"),
    (10, "Moon Phases L/S", "BTCUSDT", "1h", check_10_moon_phases, "https://www.tradingview.com/script/sl42otOB/"),
    (11, "7/19 EMA Cross", "ETHUSDT", "30m", check_11_ema_cross, "https://www.tradingview.com/script/c0dAzn2Q/"),
    (12, "RSI > 70 Buy", "BTCUSDT", "4h", check_12_rsi70, "https://www.tradingview.com/script/wZIdSrBG/"),
    (13, "50/200 SMA + RSI Avg", "ETHUSDT", "1d", check_13_sma_rsi, "https://www.tradingview.com/script/1x2AawHf/"),
    (14, "Pivot SuperTrend", "BTCUSDT", "4h", check_14_pivot_supertrend, "https://www.tradingview.com/script/b74KzneI/"),
    (15, "Keltner Breakout 4H", "ETHUSDT", "4h", check_15_keltner_breakout, "https://www.tradingview.com/script/LmNV3ZLN/"),
    (16, "Hash Supertrend", "SOLUSDT", "4h", check_16_hash_supertrend, "https://www.tradingview.com/script/6zYF9Xts/"),
    (17, "Crypto LONG PY", "SOLUSDT", "5m", check_17_crypto_long_py, "https://www.tradingview.com/script/3Uel153a/"),
    (18, "Oleg_Aryukov", "BTCUSDT", "15m", check_18_oleg, "https://www.tradingview.com/script/R4mgYcZ5/"),
    (19, "Options Daily Long UTC", "ETHUSDT", "5m", check_19_options_daily, "https://www.tradingview.com/script/DJT1l5tH/"),
    (20, "Qullamagi EMA Breakout", "ETHUSDT", "1h", check_20_qullamagi, "https://www.tradingview.com/script/0rVYn2c4/"),
    (21, "Kinetic Kalman Breakout", "ETHUSDT", "15m", check_21_kalman_breakout, "https://www.tradingview.com/script/nd8EpyQ5/"),
]


def state_key(sid: int, symbol: str, interval: str) -> str:
    return f"{sid}_{symbol}_{interval}"


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def run() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Tier1 monitor run @ {now}")
    state = load_state()
    changes = []

    for sid, name, symbol, interval, checker, tv_url in STRATEGIES:
        klines = get_klines(symbol, interval)
        if not klines:
            print(f"  #{sid} {symbol} {interval}: no data")
            continue
        try:
            signal = checker(klines)
        except Exception as exc:
            print(f"  #{sid} {name}: error {exc}")
            continue
        key = state_key(sid, symbol, interval)
        prev = state.get(key, "FLAT")
        state[key] = signal
        if signal != prev:
            changes.append((sid, name, symbol, interval, prev, signal, tv_url))
            print(f"  #{sid} {name}: {prev} -> {signal}")
        else:
            print(f"  #{sid} {name}: {signal} (unchanged)")

    save_state(state)

    if changes:
        lines = [f"<b>Tier1 signal update</b> ({now})", ""]
        for sid, name, symbol, interval, prev, signal, tv_url in changes:
            lines.append(
                f"#{sid} <b>{name}</b>\n"
                f"{symbol} {interval}: <code>{prev}</code> → <code>{signal}</code>\n"
                f"<a href=\"{tv_url}\">TradingView</a>"
            )
        send_telegram("\n".join(lines))
    else:
        print("No signal changes.")


if __name__ == "__main__":
    run()
