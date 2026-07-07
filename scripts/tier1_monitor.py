#!/usr/bin/env python3
"""
21 top-tier Alpha strategy monitor (TradingView Pine-aligned, Apr 2026).

Automated signal + exit monitoring for BTC, ETH, and SOL.
Signals use the last *closed* candle (klines[-2]) to avoid repainting on the open bar.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import requests

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from ai_review import review_enabled, run_review

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
POLL_INTERVAL_SEC = 300  # 5 minutes — use cron */5 * * * * or `run --loop`

Signal = str  # "LONG", "SHORT", "FLAT"
ExitFn = Callable[[object, str], bool]


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


def heikin_ashi_series(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> Tuple[List[float], List[float], List[float], List[float]]:
    n = len(closes)
    ha_o = [0.0] * n
    ha_h = [0.0] * n
    ha_l = [0.0] * n
    ha_c = [0.0] * n
    for i in range(n):
        ha_c[i] = (opens[i] + highs[i] + lows[i] + closes[i]) / 4.0
        ha_o[i] = (opens[i] + closes[i]) / 2.0 if i == 0 else (ha_o[i - 1] + ha_c[i - 1]) / 2.0
        ha_h[i] = max(highs[i], ha_o[i], ha_c[i])
        ha_l[i] = min(lows[i], ha_o[i], ha_c[i])
    return ha_o, ha_h, ha_l, ha_c


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
    """SuperTrend STRATEGY — BTC 1d, ATR SMA 10, multiplier 8.5, bidirectional."""
    if not _need(klines, 50):
        return "FLAT"
    _, highs, lows, closes = ohlc(klines)
    i, j = confirmed_indices()
    st = supertrend_direction(highs, lows, closes, period=10, multiplier=8.5)
    if st[j] <= 0 and st[i] > 0:
        return "LONG"
    if st[j] >= 0 and st[i] < 0:
        return "SHORT"
    if st[i] > 0:
        return "LONG"
    if st[i] < 0:
        return "SHORT"
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


# ===== Position exit checks (TradingView exit rules where known) =====
def _exit_default(klines, side: str, checker: Callable) -> bool:
    sig = checker(klines)
    if side == "LONG":
        return sig != "LONG"
    if side == "SHORT":
        return sig != "SHORT"
    return True


def exit_01_mean_reversion(klines, side: str) -> bool:
    if not _need(klines, 220):
        return False
    _, highs, lows, closes = ohlc(klines)
    i, _ = confirmed_indices()
    rsi = rsi_wilder(closes)
    stoch = stochastic_k(highs, lows, closes)
    ema200 = ema_series(closes, 200)
    if rsi[i] is None or stoch[i] is None or ema200[i] is None:
        return False
    if side == "LONG":
        return rsi[i] > 65 and stoch[i] > 75 and closes[i] < ema200[i]
    if side == "SHORT":
        return rsi[i] < 20 and stoch[i] < 25 and closes[i] > ema200[i]
    return _exit_default(klines, side, check_01_mean_reversion)


def exit_07_macd_zero(klines, side: str) -> bool:
    if side != "LONG" or not _need(klines, 80):
        return _exit_default(klines, side, check_07_macd_zero)
    _, _, _, closes = ohlc(klines)
    i, j = confirmed_indices()
    macd = macd_line_series(closes)
    if macd[i] is None or macd[j] is None:
        return False
    return macd[j] > 0 >= macd[i] or macd[i] <= 0


def exit_08_cdc_macd(klines, side: str) -> bool:
    if side != "LONG" or not _need(klines, 80):
        return _exit_default(klines, side, check_08_cdc_macd)
    _, _, _, closes = ohlc(klines)
    i, j = confirmed_indices()
    line = macd_line_series(closes)
    sig = macd_signal_series(closes)
    if line[i] is None or sig[i] is None or line[j] is None or sig[j] is None:
        return False
    return cross_below(line[j], line[i], sig[j], sig[i]) or line[i] < sig[i]


def exit_12_rsi70(klines, side: str) -> bool:
    if side != "LONG" or not _need(klines, 30):
        return _exit_default(klines, side, check_12_rsi70)
    _, _, _, closes = ohlc(klines)
    i, j = confirmed_indices()
    rsi = rsi_wilder(closes)
    if rsi[i] is None or rsi[j] is None:
        return False
    return cross_below(rsi[j], rsi[i], 70.0, 70.0) or rsi[i] < 70


def exit_11_ema_cross(klines, side: str) -> bool:
    if not _need(klines, 40):
        return _exit_default(klines, side, check_11_ema_cross)
    _, _, _, closes = ohlc(klines)
    i, j = confirmed_indices()
    e7 = ema_series(closes, 7)
    e19 = ema_series(closes, 19)
    if e7[i] is None or e19[i] is None or e7[j] is None or e19[j] is None:
        return False
    if side == "LONG":
        return cross_below(e7[j], e7[i], e19[j], e19[i])
    if side == "SHORT":
        return cross_above(e7[j], e7[i], e19[j], e19[i])
    return True


def exit_13_sma_rsi(klines, side: str) -> bool:
    if side != "LONG" or not _need(klines, 220):
        return _exit_default(klines, side, check_13_sma_rsi)
    _, _, _, closes = ohlc(klines)
    i, _ = confirmed_indices()
    sma50 = sma_series(closes, 50)
    rsi21 = rsi_wilder(closes, 21)
    rsi_avg = sma_series([v if v is not None else 0.0 for v in rsi21], 9)
    if sma50[i] is None or rsi_avg[i] is None:
        return False
    return closes[i] < sma50[i] or rsi_avg[i] < 57


EXIT_BY_ID: Dict[int, ExitFn] = {
    1: exit_01_mean_reversion,
    33: exit_01_mean_reversion,
    7: exit_07_macd_zero,
    8: exit_08_cdc_macd,
    11: exit_11_ema_cross,
    12: exit_12_rsi70,
    13: exit_13_sma_rsi,
}


def should_exit_position(sid: int, klines, side: str, checker: Callable) -> bool:
    fn = EXIT_BY_ID.get(sid)
    if fn:
        return fn(klines, side)
    return _exit_default(klines, side, checker)


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


def _bullish_engulfing(opens, closes, i: int, j: int) -> bool:
    body_i = abs(closes[i] - opens[i])
    body_j = abs(closes[j] - opens[j])
    if body_i <= body_j:
        return False
    return (
        closes[i] > opens[i]
        and closes[i] > opens[j]
        and opens[i] < closes[j]
    )


def _bearish_engulfing(opens, closes, i: int, j: int) -> bool:
    body_i = abs(closes[i] - opens[i])
    body_j = abs(closes[j] - opens[j])
    if body_i <= body_j:
        return False
    return (
        closes[i] < opens[i]
        and closes[i] < opens[j]
        and opens[i] > closes[j]
    )


def check_22_mtf_engulfing_1h(klines) -> Signal:
    """
    BTC MTF Engulfing Flip (1H) — offline proxy for jagadeeshmanne XGqSzuxJ.

    TV entry requires D EMA50 + 4H RSI + 1H engulfing/MACD/RSI/ATR/volume alignment.
    Monitor uses regime (first two TFs + 1H MACD/RSI) for ongoing bias; engulfing
    stack marks the same bar as TV's rare entry trigger. Published Python backtest
    (Apr 2026): BTCUSDT.P 1H, ~6.5y, PF ~5.5, CAGR ~143%.
    """
    if not _need(klines, 60):
        return "FLAT"
    k1d = get_klines("BTCUSDT", "1d", 120)
    k4h = get_klines("BTCUSDT", "4h", 120)
    if not _need(k1d, 55) or not _need(k4h, 20):
        return "FLAT"

    _, _, _, c1d = ohlc(k1d)
    _, _, _, c4h = ohlc(k4h)
    opens, highs, lows, closes = ohlc(klines)
    volumes = [float(k[5]) for k in klines]
    i, j = confirmed_indices()
    id_ = i
    i4 = i

    ema50_d = ema_series(c1d, 50)
    rsi4 = rsi_wilder(c4h, 14)
    rsi1 = rsi_wilder(closes, 14)
    macd_l = macd_line_series(closes, 12, 26)
    macd_s = macd_signal_series(closes, 12, 26, 9)
    if (
        ema50_d[id_] is None
        or rsi4[i4] is None
        or rsi1[i] is None
        or macd_l[i] is None
        or macd_s[i] is None
    ):
        return "FLAT"

    tr = true_range(highs, lows, closes)
    atr = sma_series(tr, 14)
    atr_vals = [x if x is not None else 0.0 for x in atr]
    atr_avg = sma_series(atr_vals, 50)
    vol_avg = sma_series(volumes, 20)

    daily_long = c1d[id_] > ema50_d[id_]
    daily_short = c1d[id_] < ema50_d[id_]
    h4_long = rsi4[i4] > 50
    h4_short = rsi4[i4] < 50
    h1_long = rsi1[i] > 45 and macd_l[i] > macd_s[i]
    h1_short = rsi1[i] < 55 and macd_l[i] < macd_s[i]

    vol_ok = vol_avg[i] is not None and volumes[i] > 1.5 * vol_avg[i]
    atr_ok = atr[i] is not None and atr_avg[i] is not None and atr[i] > atr_avg[i]
    bull_eng = _bullish_engulfing(opens, closes, i, j)
    bear_eng = _bearish_engulfing(opens, closes, i, j)

    regime_long = daily_long and h4_long and h1_long
    regime_short = daily_short and h4_short and h1_short
    entry_long = regime_long and bull_eng and atr_ok and vol_ok
    entry_short = regime_short and bear_eng and atr_ok and vol_ok

    if entry_long or regime_long:
        return "LONG"
    if entry_short or regime_short:
        return "SHORT"
    return "FLAT"


def check_23_momentum_macd_1h(klines) -> Signal:
    """
    Momentum MACD (BTC 1h) — monitor proxy for Drun30 b7zn25L6.

    Uses EMA50 trend filter + MACD(12,26,9) line vs signal (no zero-line gate).
    Open-source TV strategy labeled for BTC/USDT 1h; full Pine port pending.
    """
    if not _need(klines, 80):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, _ = confirmed_indices()
    ema50 = ema_series(closes, 50)
    macd_l = macd_line_series(closes, 12, 26)
    macd_s = macd_signal_series(closes, 12, 26, 9)
    if ema50[i] is None or macd_l[i] is None or macd_s[i] is None:
        return "FLAT"
    if closes[i] > ema50[i] and macd_l[i] > macd_s[i]:
        return "LONG"
    if closes[i] < ema50[i] and macd_l[i] < macd_s[i]:
        return "SHORT"
    return "FLAT"


def check_24_daily_ema_regime(klines) -> Signal:
    """BTC 1d EMA50/200 regime — HTF trend for fusion (bidirectional)."""
    if not _need(klines, 220):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, _ = confirmed_indices()
    ema50 = ema_series(closes, 50)
    ema200 = ema_series(closes, 200)
    if ema50[i] is None or ema200[i] is None:
        return "FLAT"
    if ema50[i] > ema200[i] and closes[i] > ema50[i]:
        return "LONG"
    if ema50[i] < ema200[i] and closes[i] < ema50[i]:
        return "SHORT"
    return "FLAT"


def check_25_btc_ema_cross_30m(klines) -> Signal:
    """7/19 EMA cross — BTC 30m (same Pine as #11, iamqamarali c0dAzn2Q)."""
    return check_11_ema_cross(klines)


def check_26_btc_keltner_4h(klines) -> Signal:
    """Keltner breakout — BTC 4h (LmNV3ZLN logic, same proxy as #15)."""
    return check_15_keltner_breakout(klines)


def check_27_ha_pa_12h(klines) -> Signal:
    """
    Heikin Ashi + Price Action — BTC 12h long bias (SoftKill21 FEJvYRkw).

    Entry: green HA + close > high[1] + high[1] > high[2].
    Exit proxy: red HA + close < low[1] → FLAT.
    """
    if not _need(klines, 10):
        return "FLAT"
    opens, highs, lows, closes = ohlc(klines)
    ha_o, _, _, ha_c = heikin_ashi_series(opens, highs, lows, closes)
    i, j = confirmed_indices()
    if i < 2:
        return "FLAT"
    green = ha_c[i] > ha_o[i]
    red = ha_c[i] < ha_o[i]
    entry = green and closes[i] > highs[j] and highs[j] > highs[i - 2]
    exit_sig = red and closes[i] < lows[j]
    if exit_sig:
        return "FLAT"
    if entry:
        return "LONG"
    if green and closes[i] > lows[j] and ha_c[j] > ha_o[j]:
        return "LONG"
    return "FLAT"


def check_28_supertrend_12h(klines) -> Signal:
    """Hash SuperTrend — BTC 12h bidirectional (6zYF9Xts core logic)."""
    if not _need(klines, 50):
        return "FLAT"
    _, highs, lows, closes = ohlc(klines)
    i, _ = confirmed_indices()
    st = supertrend_direction(highs, lows, closes, period=10, multiplier=3.0)
    if st[i] > 0:
        return "LONG"
    if st[i] < 0:
        return "SHORT"
    return "FLAT"


def check_29_supertrend_1w(klines) -> Signal:
    """Hash SuperTrend — BTC 1w bidirectional (6zYF9Xts core, Issue #15 HTF)."""
    return check_28_supertrend_12h(klines)


def check_30_monthly_ema_regime(klines) -> Signal:
    """BTC 1M EMA regime — EMA50/200 when history allows, else EMA12/36 proxy (#24 extension)."""
    if not _need(klines, 40):
        return "FLAT"
    _, _, _, closes = ohlc(klines)
    i, _ = confirmed_indices()
    fast, slow = (50, 200) if len(closes) >= 220 else (12, 36)
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    if ema_fast[i] is None or ema_slow[i] is None:
        return "FLAT"
    if ema_fast[i] > ema_slow[i] and closes[i] > ema_fast[i]:
        return "LONG"
    if ema_fast[i] < ema_slow[i] and closes[i] < ema_fast[i]:
        return "SHORT"
    return "FLAT"


def check_31_weekly_vs_3m(klines) -> Signal:
    """Weekly close vs ~3M close — witus9719 c8wSnkUA (1M lag-3 proxy; Binance has no 3M)."""
    if not _need(klines, 3):
        return "FLAT"
    _, _, _, closes_w = ohlc(klines)
    i, _ = confirmed_indices()
    weekly_close = closes_w[i]
    k1m = get_klines("BTCUSDT", "1M", 40)
    if not _need(k1m, 4):
        return "FLAT"
    _, _, _, closes_1m = ohlc(k1m)
    j, _ = confirmed_indices()
    ref_idx = j - 3
    if ref_idx < 0:
        return "FLAT"
    q_close = closes_1m[ref_idx]
    if weekly_close > q_close:
        return "LONG"
    if q_close > weekly_close:
        return "SHORT"
    return "FLAT"


# ===== Strategy registry (21 Alpha models) =====
StrategyDef = Tuple[int, str, str, str, Callable, str]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_strategy(sid: int) -> Optional[StrategyDef]:
    for s in STRATEGIES:
        if s[0] == sid:
            return s
    return None

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
    (
        22,
        "BTC MTF Engulfing Flip (1H)",
        "BTCUSDT",
        "1h",
        check_22_mtf_engulfing_1h,
        "https://www.tradingview.com/script/XGqSzuxJ/",
    ),
    (
        23,
        "Momentum MACD (BTC 1H)",
        "BTCUSDT",
        "1h",
        check_23_momentum_macd_1h,
        "https://www.tradingview.com/script/b7zn25L6/",
    ),
    (
        24,
        "Daily EMA50/200 Regime",
        "BTCUSDT",
        "1d",
        check_24_daily_ema_regime,
        "https://www.tradingview.com/support/solutions/43000502589",
    ),
    (
        25,
        "BTC 7/19 EMA Cross (30m)",
        "BTCUSDT",
        "30m",
        check_25_btc_ema_cross_30m,
        "https://www.tradingview.com/script/c0dAzn2Q/",
    ),
    (
        26,
        "BTC Keltner Breakout (4H)",
        "BTCUSDT",
        "4h",
        check_26_btc_keltner_4h,
        "https://www.tradingview.com/script/LmNV3ZLN/",
    ),
    (
        27,
        "BTC Heikin Ashi PA (12H)",
        "BTCUSDT",
        "12h",
        check_27_ha_pa_12h,
        "https://www.tradingview.com/script/FEJvYRkw/",
    ),
    (
        28,
        "BTC SuperTrend (12H)",
        "BTCUSDT",
        "12h",
        check_28_supertrend_12h,
        "https://www.tradingview.com/script/6zYF9Xts/",
    ),
    (
        29,
        "BTC SuperTrend (1W)",
        "BTCUSDT",
        "1w",
        check_29_supertrend_1w,
        "https://www.tradingview.com/script/6zYF9Xts/",
    ),
    (
        30,
        "BTC EMA Regime (1M)",
        "BTCUSDT",
        "1M",
        check_30_monthly_ema_regime,
        "https://www.tradingview.com/support/solutions/43000502589",
    ),
    (
        31,
        "BTC Weekly vs 3M",
        "BTCUSDT",
        "1w",
        check_31_weekly_vs_3m,
        "https://www.tradingview.com/script/c8wSnkUA/",
    ),
    (
        33,
        "BTC Mean Reversion RSI 20/65 (5m)",
        "BTCUSDT",
        "5m",
        check_01_mean_reversion,
        "https://www.tradingview.com/script/pIrgsDpT/",
    ),
]


def state_key(sid: int, symbol: str, interval: str) -> str:
    return f"{sid}_{symbol}_{interval}"


def migrate_state(raw) -> dict:
    if isinstance(raw, dict) and raw.get("version") == 2:
        raw.setdefault("meta", {"initialized": True})
        raw["meta"].setdefault("initialized", True)
        return raw
    migrated = {
        "version": 2,
        "last_run": None,
        "meta": {"initialized": False},
        "signals": {},
        "positions": {},
        "review_queue": {},
        "telegram_offset": 0,
    }
    if isinstance(raw, dict):
        for key, val in raw.items():
            if key in ("version", "signals", "positions", "telegram_offset", "last_run"):
                continue
            if isinstance(val, str) and val in ("LONG", "SHORT"):
                migrated["signals"][key] = {
                    "direction": val,
                    "status": "active",
                    "triggered_at": utc_now(),
                    "last_seen_at": utc_now(),
                }
    return migrated


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return migrate_state(json.load(f))
        except Exception:
            pass
    return migrate_state({})


def save_state(state: dict) -> None:
    state["version"] = 2
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def current_signal_direction(sig: Signal) -> Optional[str]:
    return sig if sig in ("LONG", "SHORT") else None


LOGIC_SUMMARY: Dict[int, str] = {
    1: "RSI<20 + Stoch<25 + above EMA200 long; RSI>65 + Stoch>75 + below EMA200 short.",
    5: "SuperTrend SMA-ATR(10)×8.5 long-only on daily close.",
    7: "MACD line above zero long-only.",
    12: "RSI cross above 70 enter; below 70 exit.",
}


def format_entry_alert(
    sid: int,
    name: str,
    symbol: str,
    interval: str,
    direction: str,
    tv_url: str,
    title: str = "Signal active",
    ai_note: str = "",
) -> str:
    ai_block = f"\n🧠 AI: {ai_note}" if ai_note else ""
    return (
        f"🟢 <b>{title}</b> #{sid} {name}\n"
        f"{symbol} {interval}: <code>{direction}</code>\n"
        f"Monitoring every 5m until it ends.{ai_block}\n"
        f"<a href=\"{tv_url}\">TradingView</a>\n"
        f"Confirm entry: <code>/confirm {sid}</code>"
    )


def queue_entry_review(
    state: dict,
    key: str,
    sid: int,
    name: str,
    symbol: str,
    interval: str,
    direction: str,
    tv_url: str,
    event: str,
) -> None:
    """Hold entry alert until AI returns PASS."""
    rq = state.setdefault("review_queue", {})
    if key in rq and rq[key].get("status") == "pending":
        return
    rq[key] = {
        "strategy_id": sid,
        "name": name,
        "symbol": symbol,
        "interval": interval,
        "direction": direction,
        "tv_url": tv_url,
        "event": event,
        "status": "pending",
        "submitted_at": utc_now(),
    }
    print(f"  #{sid} {name}: queued for AI review ({direction})")


def deliver_entry_alert(
    state: dict,
    key: str,
    sid: int,
    name: str,
    symbol: str,
    interval: str,
    direction: str,
    tv_url: str,
    event: str,
    alerts: List[str],
    ai_note: str = "",
) -> None:
    title = "New signal" if event == "flip" else "Signal active"
    if review_enabled():
        queue_entry_review(
            state, key, sid, name, symbol, interval, direction, tv_url, event
        )
    else:
        alerts.append(
            format_entry_alert(
                sid, name, symbol, interval, direction, tv_url, title, ai_note
            )
        )


def cancel_review(state: dict, key: str, reason: str = "") -> None:
    rq = state.get("review_queue", {})
    if key in rq and rq[key].get("status") == "pending":
        rq.pop(key, None)
        if reason:
            print(f"  [AI] cancelled review {key}: {reason}")


def process_review_queue(
    state: dict, klines_cache: dict, alerts: List[str]
) -> None:
    """Process pending AI reviews; push alerts only on PASS."""
    rq = state.get("review_queue", {})
    if not rq:
        return
    for key, item in list(rq.items()):
        if item.get("status") != "pending":
            continue
        sid = item["strategy_id"]
        symbol, interval = item["symbol"], item["interval"]
        cache_key = (symbol, interval)
        klines = klines_cache.get(cache_key)
        if klines is None:
            klines = get_klines(symbol, interval)
            klines_cache[cache_key] = klines
        if not klines:
            continue
        sig = state.get("signals", {}).get(key, {})
        if sig.get("status") != "active" or sig.get("direction") != item.get("direction"):
            cancel_review(state, key, "signal no longer active")
            continue
        logic = LOGIC_SUMMARY.get(sid, item.get("name", ""))
        verdict, rationale = run_review(key, item, klines, logic)
        if verdict is None:
            print(f"  #{sid} AI review pending: {rationale[:60]}")
            continue
        item["status"] = verdict.lower()
        item["rationale"] = rationale
        item["reviewed_at"] = utc_now()
        sig_ref = state.setdefault("signals", {}).setdefault(key, {})
        sig_ref["ai_verdict"] = verdict
        sig_ref["ai_rationale"] = rationale
        if verdict == "PASS":
            title = "New signal (AI PASS)" if item.get("event") == "flip" else "Signal active (AI PASS)"
            alerts.append(
                format_entry_alert(
                    sid,
                    item["name"],
                    symbol,
                    interval,
                    item["direction"],
                    item["tv_url"],
                    title,
                    rationale,
                )
            )
            print(f"  #{sid} AI PASS: {rationale[:80]}")
        else:
            alerts.append(
                f"⛔ <b>AI rejected</b> #{sid} {item['name']}\n"
                f"{symbol} {interval}: <code>{item['direction']}</code>\n"
                f"{rationale}\n"
                f"<a href=\"{item['tv_url']}\">TradingView</a>"
            )
            print(f"  #{sid} AI FAIL: {rationale[:80]}")
        del rq[key]


def process_signal_lifecycle(
    state: dict,
    key: str,
    sid: int,
    name: str,
    symbol: str,
    interval: str,
    signal: Signal,
    tv_url: str,
    alerts: List[str],
) -> None:
    """Track active signals; alert on new trigger, persistence, and disappearance."""
    signals = state.setdefault("signals", {})
    tracked = signals.get(key)
    active_dir = current_signal_direction(signal)
    now = utc_now()

    if tracked and tracked.get("status") == "active":
        prev_dir = tracked.get("direction")
        if active_dir == prev_dir:
            tracked["last_seen_at"] = now
            print(f"  #{sid} {name}: {signal} (active, still valid)")
            return
        # Signal disappeared or flipped
        signals[key] = {
            "direction": prev_dir,
            "status": "disappeared",
            "triggered_at": tracked.get("triggered_at"),
            "disappeared_at": now,
            "last_seen_at": now,
        }
        cancel_review(state, key, "signal ended")
        alerts.append(
            f"⚠️ <b>Signal ended</b> #{sid} {name}\n"
            f"{symbol} {interval}: <code>{prev_dir}</code> no longer active "
            f"(now <code>{signal}</code>)\n"
            f"<a href=\"{tv_url}\">TradingView</a>"
        )
        print(f"  #{sid} {name}: {prev_dir} disappeared -> {signal}")
        if active_dir and active_dir != prev_dir:
            signals[key] = {
                "direction": active_dir,
                "status": "active",
                "triggered_at": now,
                "last_seen_at": now,
            }
            deliver_entry_alert(
                state, key, sid, name, symbol, interval, active_dir, tv_url, "flip", alerts
            )
            print(f"  #{sid} {name}: new {active_dir}")
        return

    initialized = state.get("meta", {}).get("initialized", False)

    if active_dir:
        signals[key] = {
            "direction": active_dir,
            "status": "active",
            "triggered_at": now,
            "last_seen_at": now,
        }
        if initialized:
            deliver_entry_alert(
                state, key, sid, name, symbol, interval, active_dir, tv_url, "new", alerts
            )
        print(f"  #{sid} {name}: triggered {active_dir}" + ("" if initialized else " (seed, no alert)"))
        return

    if tracked and tracked.get("status") == "disappeared":
        if active_dir:
            signals[key] = {
                "direction": active_dir,
                "status": "active",
                "triggered_at": now,
                "last_seen_at": now,
            }
            if initialized:
                deliver_entry_alert(
                    state, key, sid, name, symbol, interval, active_dir, tv_url, "new", alerts
                )
            print(f"  #{sid} {name}: re-triggered {active_dir}")
        else:
            print(f"  #{sid} {name}: FLAT (idle)")
        return
    print(f"  #{sid} {name}: FLAT (idle)")


def process_positions(
    state: dict,
    klines_cache: dict,
    alerts: List[str],
) -> None:
    """Monitor user-confirmed positions for exit conditions."""
    positions = state.get("positions", {})
    if not positions:
        return
    to_remove = []
    for key, pos in list(positions.items()):
        sid = pos.get("strategy_id")
        side = pos.get("side")
        symbol = pos.get("symbol")
        interval = pos.get("interval")
        strat = get_strategy(sid) if sid else None
        if not strat or not side:
            to_remove.append(key)
            continue
        _, name, _, _, checker, tv_url = strat
        cache_key = (symbol, interval)
        klines = klines_cache.get(cache_key)
        if klines is None:
            klines = get_klines(symbol, interval)
            klines_cache[cache_key] = klines
        if not klines:
            print(f"  [position] #{sid} no klines")
            continue
        try:
            exit_now = should_exit_position(sid, klines, side, checker)
            still_in = checker(klines) == side
        except Exception as exc:
            print(f"  [position] #{sid} error: {exc}")
            continue
        if exit_now:
            entry = pos.get("entry_price")
            entry_s = f" @ {entry}" if entry else ""
            alerts.append(
                f"🔴 <b>Close position</b> #{sid} {name}\n"
                f"{symbol} {interval}: exit <code>{side}</code>{entry_s}\n"
                f"Strategy exit condition met.\n"
                f"<a href=\"{tv_url}\">TradingView</a>"
            )
            print(f"  [position] #{sid} EXIT alert ({side})")
            to_remove.append(key)
        else:
            print(
                f"  [position] #{sid} {side} held "
                f"(signal={checker(klines)}, in_direction={still_in})"
            )
    for key in to_remove:
        positions.pop(key, None)


def poll_telegram_commands(state: dict) -> List[str]:
    """Parse /confirm and /close from Telegram updates."""
    if not TELEGRAM_BOT_TOKEN:
        return []
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = state.get("telegram_offset", 0)
    try:
        resp = requests.get(
            url, params={"offset": offset, "timeout": 0, "limit": 20}, timeout=10
        )
        data = resp.json()
    except Exception as exc:
        print(f"[TG POLL ERROR] {exc}")
        return []
    if not data.get("ok"):
        return []
    replies = []
    for upd in data.get("result", []):
        state["telegram_offset"] = upd["update_id"] + 1
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            continue
        text = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        thread = str(msg.get("message_thread_id", ""))
        if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
            continue
        if THREAD_ID and thread and thread != str(THREAD_ID):
            continue
        m_confirm = re.match(
            r"^/confirm(?:@\w+)?\s+(\d+)(?:\s+([\d.]+))?\s*$", text, re.I
        )
        m_close = re.match(r"^/close(?:@\w+)?\s+(\d+)\s*$", text, re.I)
        m_status = re.match(r"^/status(?:@\w+)?\s*$", text, re.I)
        if m_confirm:
            sid = int(m_confirm.group(1))
            price = float(m_confirm.group(2)) if m_confirm.group(2) else None
            ok, info = cmd_confirm(state, sid, price)
            replies.append(info)
        elif m_close:
            ok, info = cmd_close(state, int(m_close.group(1)))
            replies.append(info)
        elif m_status:
            replies.append(cmd_status_text(state))
    return replies


def cmd_confirm(
    state: dict, sid: int, entry_price: Optional[float] = None
) -> Tuple[bool, str]:
    strat = get_strategy(sid)
    if not strat:
        return False, f"Unknown strategy #{sid}"
    _, name, symbol, interval, checker, tv_url = strat
    key = state_key(sid, symbol, interval)
    sig = state.get("signals", {}).get(key, {})
    direction = sig.get("direction") if sig.get("status") == "active" else None
    klines = get_klines(symbol, interval)
    if not direction and klines:
        direction = current_signal_direction(checker(klines))
    if not direction:
        return (
            False,
            f"#{sid} has no active signal — cannot confirm. Wait for a signal first.",
        )
    existing = state.get("positions", {}).get(key)
    if existing and existing.get("side") == direction:
        return (
            False,
            f"#{sid} already tracked as <code>{direction}</code> since {existing.get('confirmed_at', '?')}",
        )
    if entry_price is None and klines:
        entry_price = float(ohlc(klines)[3][-2])
    state.setdefault("positions", {})[key] = {
        "strategy_id": sid,
        "name": name,
        "side": direction,
        "symbol": symbol,
        "interval": interval,
        "confirmed_at": utc_now(),
        "entry_price": entry_price,
        "tv_url": tv_url,
    }
    px = f" @ <code>{entry_price}</code>" if entry_price else ""
    return (
        True,
        f"✅ Recorded <b>#{sid} {name}</b>\n"
        f"{symbol} {interval} <code>{direction}</code>{px}\n"
        f"Exit alerts every 5m. Manual close: <code>/close {sid}</code>",
    )


def cmd_close(state: dict, sid: int) -> Tuple[bool, str]:
    strat = get_strategy(sid)
    if not strat:
        return False, f"Unknown strategy #{sid}"
    _, name, symbol, interval, _, _ = strat
    key = state_key(sid, symbol, interval)
    if key not in state.get("positions", {}):
        return False, f"No open recorded position for #{sid}"
    state["positions"].pop(key)
    return True, f"✅ Closed tracking for <b>#{sid} {name}</b> (manual)"


def cmd_status_text(state: dict) -> str:
    lines = ["<b>Tier1 status</b>", ""]
    act = [
        (k, v)
        for k, v in state.get("signals", {}).items()
        if v.get("status") == "active"
    ]
    if act:
        lines.append("<b>Active signals</b>")
        for k, v in act:
            lines.append(f"• {k}: <code>{v.get('direction')}</code>")
    else:
        lines.append("No active signals.")
    pending = [
        (k, v)
        for k, v in state.get("review_queue", {}).items()
        if v.get("status") == "pending"
    ]
    lines.append("")
    if pending:
        lines.append("<b>AI review pending</b>")
        for k, v in pending:
            lines.append(f"• {k}: <code>{v.get('direction')}</code>")
    else:
        lines.append("No AI reviews pending.")
    pos = state.get("positions", {})
    lines.append("")
    if pos:
        lines.append("<b>Open positions (confirmed)</b>")
        for k, p in pos.items():
            px = p.get("entry_price")
            px_s = f" @ {px}" if px else ""
            lines.append(
                f"• #{p.get('strategy_id')} {p.get('symbol')} "
                f"<code>{p.get('side')}</code>{px_s}"
            )
    else:
        lines.append("No confirmed positions.")
    return "\n".join(lines)


def run_once() -> None:
    now = utc_now()
    print(f"Tier1 monitor @ {now} (poll every {POLL_INTERVAL_SEC}s)")
    state = load_state()
    state["last_run"] = now
    alerts: List[str] = []
    klines_cache: dict = {}

    for reply in poll_telegram_commands(state):
        alerts.append(reply)

    for sid, name, symbol, interval, checker, tv_url in STRATEGIES:
        cache_key = (symbol, interval)
        klines = klines_cache.get(cache_key)
        if klines is None:
            klines = get_klines(symbol, interval)
            klines_cache[cache_key] = klines
        if not klines:
            print(f"  #{sid} {symbol} {interval}: no data")
            continue
        key = state_key(sid, symbol, interval)
        try:
            signal = checker(klines)
            process_signal_lifecycle(
                state, key, sid, name, symbol, interval, signal, tv_url, alerts
            )
        except Exception as exc:
            print(f"  #{sid} {name}: error {exc}")

    process_review_queue(state, klines_cache, alerts)
    process_positions(state, klines_cache, alerts)
    state.setdefault("meta", {})["initialized"] = True
    save_state(state)

    if alerts:
        send_telegram("\n\n".join(alerts))
    else:
        print("No alerts this cycle.")


def run_loop(interval_sec: int = POLL_INTERVAL_SEC) -> None:
    import time

    print(f"Loop mode: every {interval_sec}s")
    while True:
        run_once()
        time.sleep(interval_sec)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tier1 strategy monitor (5m)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Single monitoring cycle (for cron */5)")

    p_loop = sub.add_parser("loop", help="Run forever every 5 minutes")
    p_loop.add_argument(
        "--interval",
        type=int,
        default=POLL_INTERVAL_SEC,
        help="Seconds between cycles (default 300)",
    )

    p_confirm = sub.add_parser("confirm", help="Record that you opened a position")
    p_confirm.add_argument("strategy_id", type=int)
    p_confirm.add_argument("entry_price", type=float, nargs="?", default=None)

    p_close = sub.add_parser("close", help="Stop tracking a position manually")
    p_close.add_argument("strategy_id", type=int)

    sub.add_parser("status", help="Print active signals and positions")

    args = parser.parse_args()
    cmd = args.command or "run"

    if cmd == "run":
        run_once()
    elif cmd == "loop":
        run_loop(args.interval)
    elif cmd == "confirm":
        state = load_state()
        ok, msg = cmd_confirm(state, args.strategy_id, args.entry_price)
        save_state(state)
        print(msg)
        if ok:
            send_telegram(msg)
        sys.exit(0 if ok else 1)
    elif cmd == "close":
        state = load_state()
        ok, msg = cmd_close(state, args.strategy_id)
        save_state(state)
        print(msg)
        if ok:
            send_telegram(msg)
        sys.exit(0 if ok else 1)
    elif cmd == "status":
        state = load_state()
        text = cmd_status_text(state)
        print(text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))
        sys.exit(0)


if __name__ == "__main__":
    main()
