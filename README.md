# Crypto-Trading-Signals (JZ3 Production)

High-fidelity crypto trading signal monitor derived from Minara AI Tier 1 strategies.
Used for monitoring the 2.5 BTC DCA Campaign ($900k USDT liquidity).

## Core Strategies
- **#1 RSI Mean Reversion**: RSI < 20 Buy, RSI > 65 Sell.
- **#3 SuperTrend AI**: Adaptive trend following on BTC 4h.
- **#5 SuperTrend Daily**: Core trend sentinel for long-term holders.
- **#7 MACD Zero-Line**: Trend confirmation for mid-term swings.
- **#12 RSI > 70 Buy**: Momentum breakout strategy.

## Tech Stack
- **Data Source**: Binance Public API (No Key needed).
- **Execution**: Python 3.x hourly polling.
- **Delivery**: Telegram Topic 205 (Hermes Agent).

## Files
- `scripts/tier1_monitor.py`: The engine.
- `docs/STRATEGIES.md`: Detailed logic for all 21 strategies.
