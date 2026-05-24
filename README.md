# Crypto-Trading-Signals (JZ3 Production)

High-fidelity crypto trading signal monitor derived from Minara AI Tier 1 strategies.
Used for monitoring the 2.5 BTC DCA Campaign ($900k USDT liquidity).

## Core Strategies
- **#1 RSI Mean Reversion**: RSI < 20 + Stoch + EMA200 (long); RSI > 65 (short).
- **#3 SuperTrend AI**: SuperTrend flip + EMA50 on BTC 4h (see docs for AI-layer limits).
- **#5 SuperTrend Daily**: SMA-ATR SuperTrend, multiplier **8.5**, BTC 1d, long only.
- **#7 MACD Zero-Line**: MACD line above zero (long only).
- **#12 RSI > 70 Buy**: Momentum long while RSI > 70.

Full table + TradingView links: [docs/STRATEGIES.md](docs/STRATEGIES.md).  
Reference: [Minara — 21 Tier-1 TV strategies](https://minara.ai/blog/we-found-21-money-makers-after-backtesting-236-tradingview-strategies/).

## Tech Stack
- **Data Source**: Binance Public API (no key; falls back to `data-api.binance.vision`).
- **Execution**: Python 3.x, **every 5 minutes** (cron or built-in loop).
- **Delivery**: Telegram Topic 205 (Hermes Agent).

## Monitoring (5-minute cycle)

```bash
# Cron (recommended)
*/5 * * * * cd /path/to/repo && python3 scripts/tier1_monitor.py run

# Or long-running loop
python3 scripts/tier1_monitor.py loop
```

Each cycle:

1. **Signal lifecycle** — alerts when a signal turns on, stays active (silent), and when it **disappears**.
2. **Confirmed positions** — after you record an entry, monitors **exit conditions** and sends close alerts.

### Telegram commands

| Command | Action |
|---------|--------|
| `/confirm 12` | Record that you opened per strategy #12 (optional price: `/confirm 12 98500`) |
| `/close 12` | Stop tracking position #12 manually |
| `/status` | List active signals and open positions |

CLI equivalents: `python3 scripts/tier1_monitor.py confirm 12`, `close 12`, `status`.

State file: `TIER1_STATE_FILE` (default: `scripts/tier1_monitor_state.json`).

## Files
- `scripts/tier1_monitor.py`: The engine.
- `docs/STRATEGIES.md`: Detailed logic for all 21 strategies.
