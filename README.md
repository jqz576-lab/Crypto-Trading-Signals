# Crypto-Trading-Signals

**Automated monitoring of top-tier trading strategies for Crypto BTC, ETH, and SOL.**

*Let AI be your professional quant trading desk.*

This is not just a signal alert tool. It is a **production-grade monitoring system** built on an **AI-independent decision pipeline**, designed for crypto scalpers and swing traders. Twenty-one institutional-grade Alpha strategies are packaged for your AI Agent (Hermes / OpenClaw).

Used in production for the 2.5 BTC DCA Campaign ($900k USDT liquidity).

---

## 1. Strategy foundation: institutional Alpha

All **21 strategy logics** are aligned to the **April 2026** TradingView institutional Pine Script sources:

- **Deep alignment** — not a rough mix of generic indicators; logic is benchmarked against original open-source Pine Script implementations.
- **Full coverage** — BTC, ETH, and SOL: mean reversion, volatility breakout, MA stack trend systems, and specialized models (including moon-phase calendar where applicable).
- **Venue-ready** — execution semantics are compatible with deep liquidity on **HyperLiquid**, **Binance**, and similar venues.

Strategy reference table and TradingView links: [docs/STRATEGIES.md](docs/STRATEGIES.md).

### Core strategies (highlights)

| # | Strategy | Notes |
|---|----------|--------|
| 1 | RSI Mean Reversion | RSI &lt; 20 + Stoch + EMA200 (long); RSI &gt; 65 (short) |
| 3 | SuperTrend AI | SuperTrend + EMA50 on BTC 4h |
| 5 | SuperTrend Daily | SMA-ATR SuperTrend, multiplier **8.5**, BTC 1d, long only |
| 7 | MACD Zero-Line | MACD line above zero (long only) |
| 12 | RSI &gt; 70 Buy | Momentum long while RSI &gt; 70 |

## 2. Why this stack

- **Diversified models** — 21 independent engines reduce single-strategy failure in choppy markets.
- **High-fidelity execution** — Pine-aligned Python monitors target **zero-drift** reproduction of TV logic on closed bars.
- **Strong filters** — ADX momentum, EMA trend, stochastic extremes, volume surge, and composite rules cut false positives.

## 3. Skill highlights

### AI independent review queue (implemented)

When the monitor fires a **new entry** signal, it bundles the **last 50 candles** and strategy context for AI review. Only **PASS** results are pushed as trade alerts (with the model’s rationale). **FAIL** sends a short rejection notice. Signal **end** and **close position** alerts are never gated.

Configure via API or file queue — see [docs/AI_REVIEW.md](docs/AI_REVIEW.md).

```bash
# Option A — OpenAI-compatible API
export AI_REVIEW_API_KEY="your-key"

# Option B — Hermes / OpenClaw agent file queue
export AI_REVIEW_ENABLED=true
export AI_REVIEW_MODE=file
export AI_REVIEW_QUEUE_DIR=/data/hermes/tier1_review
```

Without `AI_REVIEW_API_KEY` or `AI_REVIEW_ENABLED=true`, entry alerts are sent immediately (gate off).

### Position lifecycle tracking (exit monitoring)

The engine does not stop at “buy.” It tracks **confirmed positions** in monitor state and runs **per-strategy exit logic** every 5 minutes—so take-profit / trend-exit conditions are not missed.

### Zero-config universal delivery

No exchange API keys required for market data. Optional Telegram credentials only where you use direct bot delivery; otherwise route alerts through your Agent **deliver** channel (Telegram, Discord, web, etc.).

---

## Operations (5-minute cycle)

```bash
# Cron (recommended)
*/5 * * * * cd /path/to/repo && python3 scripts/tier1_monitor.py run

# Or long-running loop
python3 scripts/tier1_monitor.py loop
```

Each cycle:

1. **Signal lifecycle** — alert on trigger, stay silent while active, alert when the signal **ends**.
2. **Confirmed positions** — after you record an entry, monitor **exit conditions** and send close alerts.

### Telegram commands

| Command | Action |
|---------|--------|
| `/confirm 12` | Record that you opened per strategy #12 (optional price: `/confirm 12 98500`) |
| `/close 12` | Stop tracking position #12 manually |
| `/status` | List active signals and open positions |

CLI: `python3 scripts/tier1_monitor.py confirm 12`, `close 12`, `status`.

**State file:** `TIER1_STATE_FILE` (default: `scripts/tier1_monitor_state.json`) — includes `signals` and `positions`.

## Tech stack

- **Data:** Binance public klines (`data-api.binance.vision` fallback)
- **Runtime:** Python 3.x, **300s** poll interval
- **Agent:** Hermes / OpenClaw integration

## Files

| Path | Role |
|------|------|
| `scripts/tier1_monitor.py` | Monitoring engine |
| `scripts/test_tier1_qa.py` | QA smoke tests |
| `docs/STRATEGIES.md` | All 21 strategies + TV links |

## QA

```bash
python3 scripts/test_tier1_qa.py
```
