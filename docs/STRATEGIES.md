# 21 Tier-1 Strategies (Minara × TradingView)

Source article: [We Found 21 Money-Makers After Backtesting 236 TradingView Strategies](https://minara.ai/blog/we-found-21-money-makers-after-backtesting-236-tradingview-strategies/)

Monitor implementation: `scripts/tier1_monitor.py` — uses the **last closed candle** (`klines[-2]`) to match non-repainting TV entries.

| # | Strategy | Pair | TF | Core logic (monitor) | TradingView |
|---|----------|------|-----|----------------------|-------------|
| 1 | Optimized BTC Mean Reversion | BTCUSDT | 15m | Long: RSI(14)&lt;20, Stoch&lt;25, price&gt;EMA200; Short: RSI&gt;65, Stoch&gt;75, price&lt;EMA200 | [pIrgsDpT](https://www.tradingview.com/script/pIrgsDpT/) |
| 2 | Volatility Breakout System | ETHUSDT | 1h | Donchian 20 breakout (proxy) | [36zwwSMa](https://www.tradingview.com/script/36zwwSMa/) |
| 3 | SuperTrend AI Adaptive | BTCUSDT | 4h | SuperTrend(10,3) flip + EMA50 filter; full AI score not replicated offline | [kZVrTReu](https://www.tradingview.com/script/kZVrTReu/) |
| 4 | BB Upper breakout Short +2% | SOLUSDT | 1h | Short when close ≥ upper BB(20,2)×1.02 | [UBGvlIlq](https://www.tradingview.com/script/UBGvlIlq/) |
| 5 | SuperTrend STRATEGY | BTCUSDT | 1d | Long only: SuperTrend SMA-ATR(10)×**8.5**, hl2 | [VLRj2sG9](https://www.tradingview.com/script/VLRj2sG9/) |
| 6 | Penguin Volatility State | BTCUSDT | 1d | High ATR percentile + EMA50 side (simplified) | [skzo4i9e](https://www.tradingview.com/script/skzo4i9e/) |
| 7 | MACD Zero-Line (Long) | BTCUSDT | 1d | Long while MACD line &gt; 0; flat when ≤0 | [llTXO45e](https://www.tradingview.com/script/llTXO45e/) |
| 8 | CDC MACD Fix | BTCUSDT | 1d | MACD line cross above signal (proxy) | [7nv3hTpO](https://www.tradingview.com/script/7nv3hTpO/) |
| 9 | Hash Momentum | BTCUSDT | 4h | 12-bar momentum positive &amp; accelerating | [L6VNlhiV](https://www.tradingview.com/script/L6VNlhiV/) |
| 10 | Moon Phases L/S | BTCUSDT | 1h | **Not OHLC-derived** — returns FLAT (needs calendar) | [sl42otOB](https://www.tradingview.com/script/sl42otOB/) |
| 11 | 7/19 EMA Cross | ETHUSDT | 30m | EMA7 vs EMA19 cross / position | [c0dAzn2Q](https://www.tradingview.com/script/c0dAzn2Q/) |
| 12 | RSI &gt; 70 Buy | BTCUSDT | 4h | Long on RSI cross above 70 or RSI&gt;70 | [wZIdSrBG](https://www.tradingview.com/script/wZIdSrBG/) |
| 13 | 50/200 SMA + RSI Avg | ETHUSDT | 1d | Long: price above SMA50 &amp; SMA200, SMA(RSI21,9)&gt;57 | [1x2AawHf](https://www.tradingview.com/script/1x2AawHf/) |
| 14 | Pivot SuperTrend | BTCUSDT | 4h | SuperTrend + close vs bar pivot | [b74KzneI](https://www.tradingview.com/script/b74KzneI/) |
| 15 | Keltner Breakout 4H | ETHUSDT | 4h | EMA20 ± 1.5×ATR(10) breakout | [LmNV3ZLN](https://www.tradingview.com/script/LmNV3ZLN/) |
| 16 | Hash Supertrend | SOLUSDT | 4h | SuperTrend(10,3) direction | [6zYF9Xts](https://www.tradingview.com/script/6zYF9Xts/) |
| 17 | Crypto LONG PY | SOLUSDT | 5m | RSI oversold bounce proxy | [3Uel153a](https://www.tradingview.com/script/3Uel153a/) |
| 18 | Oleg_Aryukov | BTCUSDT | 15m | EMA 9&gt;21&gt;55 stack | [R4mgYcZ5](https://www.tradingview.com/script/R4mgYcZ5/) |
| 19 | Options Daily Long UTC | ETHUSDT | 5m | Time window proxy 08:30–08:00 UTC | [DJT1l5tH](https://www.tradingview.com/script/DJT1l5tH/) |
| 20 | Qullamagi EMA Breakout | ETHUSDT | 1h | Close cross EMA20 with rising EMA50 | [0rVYn2c4](https://www.tradingview.com/script/0rVYn2c4/) |
| 21 | Kinetic Kalman Breakout | ETHUSDT | 15m | EMA20 ± ATR band breakout proxy | [nd8EpyQ5](https://www.tradingview.com/script/nd8EpyQ5/) |

## Notes

- **#5 multiplier**: Minara’s featured backtest uses **8.5** (not 3.0) on BTC 1d — see TV script changelog on [VLRj2sG9](https://www.tradingview.com/script/VLRj2sG9/).
- **#3 / #6 / #10 / #17–21**: Complex Pine logic (AI scoring, moon calendar, Kalman) is approximated or marked FLAT where OHLC alone is insufficient.
- **Alignment target**: Minara replicated TV with ≥90% trade match; offline monitor is for **directional alerts**, not trade-for-trade parity.
