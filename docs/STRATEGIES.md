# 21 Top Alpha Strategies (TradingView-aligned)

Logic benchmarked against **April 2026** open-source TradingView Pine Script strategies on BTC, ETH, and SOL.

Monitor: `scripts/tier1_monitor.py` — uses the **last closed candle** (`klines[-2]`) for non-repainting entries.

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
| 22 | BTC MTF Engulfing Flip (1H) | BTCUSDT | 1h | D EMA50 + 4H RSI + 1H MACD/RSI regime; engulfing+ATR+vol for TV entry bar | [XGqSzuxJ](https://www.tradingview.com/script/XGqSzuxJ/) |
| 23 | Momentum MACD (BTC 1H) | BTCUSDT | 1h | EMA50 + MACD(12,26,9) line/signal + zero-line side (proxy) | [b7zn25L6](https://www.tradingview.com/script/b7zn25L6/) |
| 24 | Daily EMA50/200 Regime | BTCUSDT | 1d | EMA50 vs EMA200 + price side (HTF trend) | built-in |
| 25 | BTC 7/19 EMA Cross | BTCUSDT | 30m | EMA7 vs EMA19 cross / position (same Pine as #11) | [c0dAzn2Q](https://www.tradingview.com/script/c0dAzn2Q/) |
| 26 | BTC Keltner Breakout 4H | BTCUSDT | 4h | EMA20 ± 1.5×ATR(10) breakout (same proxy as #15) | [LmNV3ZLN](https://www.tradingview.com/script/LmNV3ZLN/) |
| 27 | BTC Heikin Ashi PA (12H) | BTCUSDT | 12h | Green HA + close > high[1] > high[2]; exit on red HA + close < low[1] | [FEJvYRkw](https://www.tradingview.com/script/FEJvYRkw/) |
| 28 | BTC SuperTrend (12H) | BTCUSDT | 12h | SuperTrend(10,3) direction (Hash Supertrend core) | [6zYF9Xts](https://www.tradingview.com/script/6zYF9Xts/) |
| 29 | BTC SuperTrend (1W) | BTCUSDT | 1w | SuperTrend(10,3) weekly HTF trend (#28 core) | [6zYF9Xts](https://www.tradingview.com/script/6zYF9Xts/) |
| 30 | BTC EMA Regime (1M) | BTCUSDT | 1M | EMA50/200 when ≥220 bars else EMA12/36 proxy | built-in (#24 extension) |
| 31 | BTC Weekly vs 3M | BTCUSDT | 1w | Weekly close > 3M close → LONG (default weight 0.5) | [c8wSnkUA](https://www.tradingview.com/script/c8wSnkUA/) |

## Notes

- **#25**: TV script is open-source (106+ favorites); same 7/19 EMA logic as ETH #11, ported to BTC 30m for timing gate at `step=2`.
- **#26**: Keltner 4H complements existing BTC 4h pool (#3/#9/#12/#14); breakout-style confirmation on 4h closes.
- **#27**: SoftKill21 HA strategy is **long-biased** (804 favorites, designed for 12/24h). Offline monitor approximates entry/exit; no pyramid/SL from TV.
- **#28**: Bidirectional SuperTrend on 12h — use with #27 so SHORT timing has a 12h strategy match.
- **#29–#31** (Issue #15): 1W/1M HTF votes for fusion scoring only — **not** used by `entry_interval_for_step` timing gate (max interval remains 12h → 1d).
- **#31**: Uses 1M close lagged 3 bars as ~3M proxy (Binance has no `3M` interval); fusion default weight **0.5**.
- **Timing gate**: `entry_interval_for_step(step_bars)` maps scan cadence → strategy interval (15m→15m, 2→30m, 4→1h, 16→4h, 48→12h).
- **#23**: Drun30 open-source MACD momentum script for BTC/USDT 1h; monitor uses simplified EMA50+MACD proxy until full Pine port.

- **#5 multiplier**: Featured TV backtest uses **8.5** (not 3.0) on BTC 1d — see changelog on [VLRj2sG9](https://www.tradingview.com/script/VLRj2sG9/).
- **#3 / #6 / #10 / #17–21**: Complex Pine logic (AI scoring, moon calendar, Kalman) is approximated or marked FLAT where OHLC alone is insufficient.
- **Alignment**: Monitor targets directional parity with TV; trade-for-trade replication requires full Pine port per strategy.

## Runtime: signal + position tracking (5m)

| Phase | Behavior |
|-------|----------|
| Signal **on** | Telegram: signal active; suggests `/confirm {id}` |
| Signal **still on** | No repeat alert; state `last_seen_at` updated |
| Signal **off** | Telegram: signal ended (disappeared) |
| **Confirmed** entry | Stored in `positions`; exit checked every 5m |
| **Exit** hit | Telegram: close position; position removed from state |

Dedicated exit rules (TV-aligned) for: **#1, #7, #8, #11, #12, #13**. Others use “signal no longer in your direction” (e.g. LONG position exits when checker ≠ LONG).

Poll interval: **300 seconds** — `scripts/tier1_monitor.py run` via `*/5` cron, or `loop` subcommand.
