---
name: crypto-trading-signals
description: Use this skill when an agent needs to understand, operate, test, or modify this repository's crypto trading signal monitor.
---

# Crypto Trading Signals Repository Skill

This repository is a Python crypto signal monitoring system for BTC, ETH, and SOL.
It monitors 21 TradingView-aligned strategy signals, tracks signal lifecycles and
user-confirmed positions, optionally gates new entry alerts through an AI reviewer,
and sends alerts through Telegram when configured.

Use this skill as the agent's first reference before changing code in this repo.

## Source of truth

Read these files in this order:

1. `README.md` - product overview, runtime commands, environment variables.
2. `scripts/tier1_monitor.py` - main monitoring engine and almost all business logic.
3. `scripts/ai_review.py` - AI second-pass review gate.
4. `docs/STRATEGIES.md` - strategy table and TradingView references.
5. `docs/AI_REVIEW.md` - API/file queue protocol for AI review.
6. `scripts/test_tier1_qa.py` - lightweight QA tests and expected behaviors.

There is no package layout, no `requirements.txt`, no `pyproject.toml`, and no CI
configuration. The only third-party Python dependency used by the scripts is
`requests`.

## Repository layout

```text
.
├── README.md
├── docs/
│   ├── AI_REVIEW.md
│   └── STRATEGIES.md
└── scripts/
    ├── ai_review.py
    ├── test_tier1_qa.py
    └── tier1_monitor.py
```

Ignored runtime artifacts:

- `scripts/tier1_monitor_state.json`
- `__pycache__/`
- `*.pyc`

## Main entry points

Run from the repository root unless noted.

```bash
# Single monitoring cycle, intended for cron every 5 minutes.
python3 scripts/tier1_monitor.py run

# Long-running loop, default interval 300 seconds.
python3 scripts/tier1_monitor.py loop
python3 scripts/tier1_monitor.py loop --interval 300

# Record a user-confirmed position after an active signal.
python3 scripts/tier1_monitor.py confirm 12
python3 scripts/tier1_monitor.py confirm 12 98500

# Stop tracking a recorded position.
python3 scripts/tier1_monitor.py close 12

# Print active signals, pending AI reviews, and confirmed positions.
python3 scripts/tier1_monitor.py status

# Run QA.
python3 scripts/test_tier1_qa.py
```

Production cron shape:

```cron
*/5 * * * * cd /path/to/repo && python3 scripts/tier1_monitor.py run
```

## Runtime architecture

The production entry point is `scripts/tier1_monitor.py`.

High-level flow for one `run` cycle:

1. `run_once()` records the current UTC timestamp.
2. `load_state()` loads the JSON state file and calls `migrate_state()`.
3. `poll_telegram_commands()` reads `/confirm`, `/close`, and `/status` commands
   when Telegram is configured.
4. `run_once()` iterates through `STRATEGIES`.
5. For each `(symbol, interval)`, `get_klines()` fetches Binance public klines and
   caches them for this cycle.
6. The registered checker function returns one of `LONG`, `SHORT`, or `FLAT`.
7. `process_signal_lifecycle()` updates `state["signals"]` and emits entry/end
   alerts when appropriate.
8. `process_review_queue()` handles pending AI-gated entry alerts.
9. `process_positions()` checks user-confirmed positions for exit conditions.
10. The monitor sets `state["meta"]["initialized"] = True`.
11. `save_state()` writes the state JSON.
12. If there are alert messages, `send_telegram()` sends one Telegram message with
    alert blocks separated by blank lines. Without Telegram credentials it prints
    `[TG SKIP]`.

Simplified data flow:

```text
cron/loop
  -> tier1_monitor.run_once()
    -> load_state() / migrate_state()
    -> poll_telegram_commands()
    -> get_klines() from Binance
    -> STRATEGIES checker functions
    -> process_signal_lifecycle()
      -> deliver_entry_alert()
        -> queue_entry_review() when AI review is enabled
    -> process_review_queue()
      -> ai_review.run_review()
    -> process_positions()
      -> should_exit_position()
    -> save_state()
    -> send_telegram()
```

## Market data

`get_klines(symbol, interval, limit=500)` uses Binance public kline endpoints:

1. `https://api.binance.com/api/v3/klines`
2. `https://data-api.binance.vision/api/v3/klines`

No exchange API key is required. If both endpoints fail, the checker for that
strategy is skipped for the cycle.

Kline parsing is done by `ohlc(klines)`, which returns `opens`, `highs`, `lows`,
and `closes` as floats.

## Non-repainting rule

All strategy logic should use the last closed candle, not the currently open
candle. The helper is:

```python
confirmed_indices() -> (-2, -3)
```

Use `i = -2` for the latest closed candle and `j = -3` for the previous closed
candle. Do not use `klines[-1]` for strategy decisions unless deliberately
changing the non-repainting semantics.

## Indicator helpers

The main technical indicator helpers live in `scripts/tier1_monitor.py`:

- `ema_series(values, period)`
- `sma_series(values, period)`
- `true_range(highs, lows, closes)`
- `rsi_wilder(closes, period=14)` - Wilder/TradingView style RSI.
- `stochastic_k(highs, lows, closes, k_period=14, smooth=3)`
- `macd_line_series(closes, fast=12, slow=26)`
- `macd_signal_series(closes, fast=12, slow=26, signal=9)`
- `bollinger(closes, length=20, mult=2.0)`
- `supertrend_direction(highs, lows, closes, period=10, multiplier=3.0, atr_mode="sma")`
- `cross_above(prev_a, curr_a, prev_b, curr_b)`
- `cross_below(prev_a, curr_a, prev_b, curr_b)`

Prefer reusing these helpers when adding or modifying strategy checks.

## Strategy registry

`STRATEGIES` in `scripts/tier1_monitor.py` is the authoritative runtime registry.

Each strategy tuple has this shape:

```python
(strategy_id, name, symbol, interval, checker_fn, tradingview_url)
```

State keys use:

```python
state_key(strategy_id, symbol, interval)
# Example: "12_BTCUSDT_4h"
```

### Strategy behavior table

| ID | Runtime name | Pair | TF | Checker | Runtime logic |
| --- | --- | --- | --- | --- | --- |
| 1 | BTC Mean Reversion RSI 20/65 | BTCUSDT | 15m | `check_01_mean_reversion` | Long when RSI(14)<20, Stoch<25, and close>EMA200. Short when RSI>65, Stoch>75, and close<EMA200. |
| 2 | Volatility Breakout System | ETHUSDT | 1h | `check_02_volatility_breakout` | Donchian/range breakout proxy: close above previous 20-bar high is LONG, below previous 20-bar low is SHORT. |
| 3 | SuperTrend AI Adaptive | BTCUSDT | 4h | `check_03_supertrend_ai` | SuperTrend(10,3) direction with EMA50 filter; full TradingView AI scoring is not reproduced offline. |
| 4 | BB Upper Breakout Short +2% | SOLUSDT | 1h | `check_04_bb_short` | SHORT when close >= Bollinger upper band(20,2) * 1.02. |
| 5 | SuperTrend STRATEGY (Daily) | BTCUSDT | 1d | `check_05_supertrend_daily` | Daily long-only SuperTrend using SMA ATR(10), hl2 source, multiplier 8.5. |
| 6 | Penguin Volatility State | BTCUSDT | 1d | `check_06_penguin_volatility` | Simplified volatility regime: ATR percentile rank > 0.7, direction from close vs EMA50. |
| 7 | MACD Zero-Line (Long) | BTCUSDT | 1d | `check_07_macd_zero` | LONG while MACD line is above zero; FLAT otherwise. |
| 8 | CDC MACD Fix | BTCUSDT | 1d | `check_08_cdc_macd` | MACD line/signal crossover proxy; LONG while line > signal. |
| 9 | Hash Momentum | BTCUSDT | 4h | `check_09_hash_momentum` | LONG when 12-bar momentum is positive and accelerating; SHORT when momentum is negative. |
| 10 | Moon Phases L/S | BTCUSDT | 1h | `check_10_moon_phases` | Always returns FLAT because moon phase calendar cannot be derived from OHLC data. |
| 11 | 7/19 EMA Cross | ETHUSDT | 30m | `check_11_ema_cross` | EMA7/EMA19 cross and position: LONG above, SHORT below. |
| 12 | RSI > 70 Buy | BTCUSDT | 4h | `check_12_rsi70` | Momentum long when RSI crosses above 70 or remains above 70. |
| 13 | 50/200 SMA + RSI Avg | ETHUSDT | 1d | `check_13_sma_rsi` | Long-only when close>SMA50, close>SMA200, and SMA(RSI21,9)>57. |
| 14 | Pivot SuperTrend | BTCUSDT | 4h | `check_14_pivot_supertrend` | SuperTrend direction plus close vs current bar pivot. |
| 15 | Keltner Breakout 4H | ETHUSDT | 4h | `check_15_keltner_breakout` | EMA20 +/- 1.5*ATR(10) breakout; LONG above upper, SHORT below lower. |
| 16 | Hash Supertrend | SOLUSDT | 4h | `check_16_hash_supertrend` | Standard SuperTrend(10,3): bullish is LONG, bearish is SHORT. |
| 17 | Crypto LONG PY | SOLUSDT | 5m | `check_17_crypto_long_py` | Proxy long when RSI recovers from oversold: previous RSI<30 and current RSI>=30. |
| 18 | Oleg_Aryukov | BTCUSDT | 15m | `check_18_oleg` | EMA stack trend proxy: EMA9>EMA21>EMA55 is LONG, reverse stack is SHORT. |
| 19 | Options Daily Long UTC | ETHUSDT | 5m | `check_19_options_daily` | Time-window proxy: LONG from 08:30 UTC through 08:00 UTC next day. |
| 20 | Qullamagi EMA Breakout | ETHUSDT | 1h | `check_20_qullamagi` | LONG when close crosses above EMA20 with rising EMA50; SHORT when below EMA20 with falling EMA50. |
| 21 | Kinetic Kalman Breakout | ETHUSDT | 15m | `check_21_kalman_breakout` | Kalman-style proxy: close breaks above EMA20+ATR for LONG or below EMA20-ATR for SHORT. |

Important strategy caveats:

- Several strategies are proxies for complex Pine logic. Do not claim exact
  trade-for-trade TradingView parity unless a full Pine port is implemented.
- `#10` intentionally stays `FLAT`.
- `#5` uses multiplier `8.5`, not the common SuperTrend default `3.0`.
- Dedicated exit rules exist only for `#1`, `#7`, `#8`, `#11`, `#12`, and `#13`.
  Other strategies exit when their checker no longer returns the held side.

## Signal lifecycle logic

Signal state lives under `state["signals"][key]`.

Typical active record:

```json
{
  "direction": "LONG",
  "status": "active",
  "triggered_at": "YYYY-MM-DD HH:MM:SS UTC",
  "last_seen_at": "YYYY-MM-DD HH:MM:SS UTC"
}
```

Lifecycle rules in `process_signal_lifecycle()`:

- If the same signal remains active, update `last_seen_at` and do not alert again.
- If an active signal becomes `FLAT`, mark it `disappeared`, cancel pending AI
  review, and alert `Signal ended`.
- If an active signal flips direction, alert that the old signal ended, store the
  new direction, and emit or queue a new entry alert.
- On the first run after fresh state, `meta.initialized` is false. Active signals
  are seeded into state but no entry alerts are sent. This prevents historical
  signals from spamming Telegram.

## Entry alerts and AI review gate

Entry alerts are delivered by `deliver_entry_alert()`.

- If `ai_review.review_enabled()` returns false, the alert is appended immediately.
- If AI review is enabled, `queue_entry_review()` adds a pending item under
  `state["review_queue"][key]`.
- Exit alerts and signal-ended alerts are never gated by AI review.

`process_review_queue()`:

1. Fetches klines for the pending strategy if needed.
2. Cancels the review if the signal is no longer active or changed direction.
3. Calls `ai_review.run_review(key, item, klines, logic_summary)`.
4. Leaves the item pending when verdict is `None`.
5. On `PASS`, sends the original entry alert with AI rationale.
6. On `FAIL`, sends an AI rejection alert.
7. Stores `ai_verdict` and `ai_rationale` on the corresponding signal record.

`LOGIC_SUMMARY` currently has explicit summaries for strategies `#1`, `#5`, `#7`,
and `#12`; other strategies fall back to their name.

## AI review module

`scripts/ai_review.py` supports four modes via `AI_REVIEW_MODE`:

| Mode | Behavior |
| --- | --- |
| `auto` | Use API when an API key exists; else use file mode if queue dir exists; else off unless explicitly enabled. |
| `api` | Call an OpenAI-compatible chat completions endpoint. Requires `AI_REVIEW_API_KEY` or `OPENAI_API_KEY`. |
| `file` | Write a pending JSON file and wait for an agent-written response file. |
| `off` | Skip AI review; `run_review()` returns PASS. |

API prompt construction:

- `compact_klines()` includes the last `AI_REVIEW_CANDLES` candles, default 50.
- `build_prompt()` asks for JSON only:
  `{"verdict":"PASS" or "FAIL","rationale":"one or two sentences"}`.
- `parse_verdict()` accepts strict JSON first, then attempts to recover a JSON
  object from text, then falls back to PASS/FAIL keyword detection.
- API errors fail safe with verdict `FAIL`.

File queue protocol:

```bash
export AI_REVIEW_MODE=file
export AI_REVIEW_QUEUE_DIR=/data/hermes/tier1_review
```

Monitor writes:

```text
${AI_REVIEW_QUEUE_DIR}/pending/{state_key}.json
```

The reviewing agent must write:

```text
${AI_REVIEW_QUEUE_DIR}/done/{state_key}.response.json
```

Response body:

```json
{
  "verdict": "PASS",
  "rationale": "Momentum and market structure confirm the signal."
}
```

Pending file reviews older than `AI_REVIEW_FILE_MAX_WAIT` seconds default to FAIL.
Default timeout is 600 seconds.

## Position tracking

Positions are not opened automatically. A user must confirm a signal.

Confirm through CLI:

```bash
python3 scripts/tier1_monitor.py confirm 12
python3 scripts/tier1_monitor.py confirm 12 98500
```

Confirm through Telegram:

```text
/confirm 12
/confirm 12 98500
```

Confirmed records live under `state["positions"][key]`:

```json
{
  "strategy_id": 12,
  "name": "RSI > 70 Buy",
  "side": "LONG",
  "symbol": "BTCUSDT",
  "interval": "4h",
  "confirmed_at": "YYYY-MM-DD HH:MM:SS UTC",
  "entry_price": 98500,
  "tv_url": "https://www.tradingview.com/script/wZIdSrBG/"
}
```

`process_positions()` checks exits every run cycle:

- It loads the strategy by ID.
- It fetches/caches current klines.
- It calls `should_exit_position()`.
- If exit is true, it sends a `Close position` alert and removes the position
  from state.

Dedicated exit functions:

- `exit_01_mean_reversion`
- `exit_07_macd_zero`
- `exit_08_cdc_macd`
- `exit_11_ema_cross`
- `exit_12_rsi70`
- `exit_13_sma_rsi`

Default exit rule:

```text
LONG exits when checker(klines) != "LONG"
SHORT exits when checker(klines) != "SHORT"
```

Manual close:

```bash
python3 scripts/tier1_monitor.py close 12
```

Telegram:

```text
/close 12
```

## State file

Default:

```text
scripts/tier1_monitor_state.json
```

Override:

```bash
export TIER1_STATE_FILE=/stable/path/tier1_monitor_state.json
```

Version 2 state shape:

```json
{
  "version": 2,
  "last_run": null,
  "meta": {"initialized": false},
  "signals": {},
  "positions": {},
  "review_queue": {},
  "telegram_offset": 0
}
```

`migrate_state()` accepts old v1-style state where arbitrary keys mapped directly
to `LONG` or `SHORT`, and converts those entries into `signals`.

Keep production state on persistent storage. The default state file is ignored by
git.

## Telegram behavior

Environment variables:

```bash
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export TELEGRAM_THREAD_ID=205
```

`send_telegram()` posts to:

```text
https://api.telegram.org/bot{token}/sendMessage
```

If token or chat ID is missing, it prints `[TG SKIP]` and does not raise.

`poll_telegram_commands()` posts replies through the same alert pipeline and
tracks `telegram_offset` in state to avoid reprocessing updates.

Supported Telegram commands:

| Command | Meaning |
| --- | --- |
| `/confirm {id}` | Confirm an active signal and begin exit monitoring. |
| `/confirm {id} {price}` | Confirm with explicit entry price. |
| `/close {id}` | Stop tracking a confirmed position. |
| `/status` | Show active signals, pending AI reviews, and open positions. |

## Environment variables

Monitor variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TIER1_DOTENV` | `/root/.hermes/.env` | Dotenv path loaded at startup. |
| `TIER1_STATE_FILE` | `scripts/tier1_monitor_state.json` | JSON state path. |
| `TELEGRAM_BOT_TOKEN` | empty | Telegram bot token. |
| `TELEGRAM_CHAT_ID` | empty | Telegram target chat. |
| `TELEGRAM_THREAD_ID` | `205` | Telegram forum topic/thread ID. |

AI review variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AI_REVIEW_MODE` | `auto` | `auto`, `api`, `file`, or `off`. |
| `AI_REVIEW_ENABLED` | empty | Explicit opt-in for auto mode when set to `1`, `true`, or `yes`. |
| `AI_REVIEW_API_KEY` | empty | API key for OpenAI-compatible chat completions. |
| `OPENAI_API_KEY` | empty | Fallback API key. |
| `AI_REVIEW_API_URL` | derived | Explicit chat completions URL. |
| `OPENAI_API_BASE` | `https://api.openai.com/v1` | Base URL used when explicit URL is unset. |
| `AI_REVIEW_MODEL` | `gpt-4o-mini` | Chat model. |
| `AI_REVIEW_CANDLES` | `50` | Number of candles in the review payload. |
| `AI_REVIEW_TIMEOUT` | `90` | API request timeout in seconds. |
| `AI_REVIEW_QUEUE_DIR` | `/data/hermes/tier1_review` | File queue root directory. |
| `AI_REVIEW_FILE_MAX_WAIT` | `600` | File review timeout in seconds. |

## Testing and verification

Primary QA command:

```bash
python3 scripts/test_tier1_qa.py
```

The test script includes:

- Unit checks for RSI and SuperTrend helpers.
- State migration and round-trip tests.
- Signal lifecycle tests for disappear, persist, flip, and first-run no-spam.
- Confirm/close position tests.
- Strategy exit behavior smoke tests.
- AI verdict parsing and file queue behavior.
- Binance integration test that runs all 21 strategies against live public klines.

The Binance integration test needs outbound network access. If it fails because
Binance is unreachable, verify pure unit behavior separately before changing
strategy logic.

## Modification playbooks

### Add or change a strategy

1. Edit `scripts/tier1_monitor.py`.
2. Add or update a `check_XX_*` function.
3. Ensure the function returns exactly `LONG`, `SHORT`, or `FLAT`.
4. Use `confirmed_indices()` and closed candles.
5. Register the strategy in `STRATEGIES`.
6. Add or update `LOGIC_SUMMARY` if AI review should receive a clearer summary.
7. Add a dedicated `exit_XX_*` function and `EXIT_BY_ID` entry only if the exit
   logic differs from the default "checker no longer returns held side" rule.
8. Update `docs/STRATEGIES.md`.
9. Run `python3 scripts/test_tier1_qa.py`.

### Change AI review behavior

1. Edit `scripts/ai_review.py` for mode resolution, prompt, parser, API, or file
   queue behavior.
2. Check `scripts/tier1_monitor.py` functions `deliver_entry_alert()`,
   `queue_entry_review()`, and `process_review_queue()`.
3. Keep exits and signal-ended alerts ungated unless the product behavior is
   intentionally changing.
4. Update `docs/AI_REVIEW.md`.
5. Run `python3 scripts/test_tier1_qa.py`.

### Change state behavior

1. Edit `migrate_state()`, `load_state()`, and `save_state()` in
   `scripts/tier1_monitor.py`.
2. Preserve existing deployed state when practical.
3. Update state-related tests in `scripts/test_tier1_qa.py`.
4. Keep `TIER1_STATE_FILE` override behavior intact.

### Change Telegram command behavior

1. Edit `poll_telegram_commands()`, `cmd_confirm()`, `cmd_close()`, or
   `cmd_status_text()` in `scripts/tier1_monitor.py`.
2. Keep CLI and Telegram semantics aligned where possible.
3. Add or update tests in `scripts/test_tier1_qa.py`.

## Agent operating rules for this repo

- Keep edits surgical. This repo is intentionally small and script-oriented.
- Avoid adding package structure, frameworks, background services, or new
  dependencies unless explicitly required.
- Do not auto-open trades. This monitor only produces signals and tracks
  user-confirmed positions.
- Do not require exchange API keys for market data.
- Preserve first-run no-spam behavior.
- Preserve closed-candle/non-repainting behavior.
- Be careful with live network tests: `test_all_strategies_live()` calls Binance.
- Do not commit generated state files or AI queue files.
- If introducing new runtime files, update `.gitignore` when needed.
