---
name: crypto-trading-signals-zh
description: 当 agent 需要理解、运行、测试或修改本仓库的加密货币交易信号监控系统时使用此中文 skill。
---

# Crypto Trading Signals 仓库中文 Skill

本仓库是一个 Python 加密货币交易信号监控系统，覆盖 BTC、ETH、SOL。
它监控 21 套与 TradingView Pine Script 对齐或近似对齐的策略信号，
管理信号生命周期和用户确认后的持仓退出，支持可选的 AI 二次审核门控，
并在配置 Telegram 后发送告警。

agent 在修改本仓库前，应先阅读本 skill。

## 信息源优先级

按以下顺序阅读文件：

1. `README.md` - 项目概览、运行命令、环境变量。
2. `README.zh-CN.md` - 中文项目概览。
3. `scripts/tier1_monitor.py` - 主监控引擎，绝大多数业务逻辑都在这里。
4. `scripts/ai_review.py` - AI 二次审核门控。
5. `docs/STRATEGIES.md` - 策略表和 TradingView 链接。
6. `docs/AI_REVIEW.md` - AI 审核的 API/file queue 协议。
7. `scripts/test_tier1_qa.py` - 轻量 QA 测试和预期行为。

仓库没有包结构，没有 `requirements.txt`，没有 `pyproject.toml`，也没有 CI
配置。脚本使用的唯一第三方 Python 依赖是 `requests`。

## 仓库结构

```text
.
├── README.md
├── README.zh-CN.md
├── docs/
│   ├── AI_REVIEW.md
│   └── STRATEGIES.md
└── scripts/
    ├── ai_review.py
    ├── test_tier1_qa.py
    └── tier1_monitor.py
```

被忽略的运行时产物：

- `scripts/tier1_monitor_state.json`
- `__pycache__/`
- `*.pyc`

## 主要入口

除非特别说明，命令都从仓库根目录运行。

```bash
# 单次监控周期，适合每 5 分钟由 cron 调用。
python3 scripts/tier1_monitor.py run

# 常驻循环，默认间隔 300 秒。
python3 scripts/tier1_monitor.py loop
python3 scripts/tier1_monitor.py loop --interval 300

# 在活跃信号后记录用户已确认的持仓。
python3 scripts/tier1_monitor.py confirm 12
python3 scripts/tier1_monitor.py confirm 12 98500

# 停止跟踪某个已记录持仓。
python3 scripts/tier1_monitor.py close 12

# 打印活跃信号、待审核 AI 队列、已确认持仓。
python3 scripts/tier1_monitor.py status

# 运行 QA。
python3 scripts/test_tier1_qa.py
```

生产 cron 形态：

```cron
*/5 * * * * cd /path/to/repo && python3 scripts/tier1_monitor.py run
```

## 运行架构

生产入口是 `scripts/tier1_monitor.py`。

一次 `run` 周期的高层流程：

1. `run_once()` 记录当前 UTC 时间。
2. `load_state()` 加载 JSON 状态文件，并调用 `migrate_state()`。
3. 如果配置了 Telegram，`poll_telegram_commands()` 读取 `/confirm`、
   `/close`、`/status` 命令。
4. `run_once()` 遍历 `STRATEGIES`。
5. 每个 `(symbol, interval)` 通过 `get_klines()` 拉取 Binance 公共 K 线，
   并在本轮周期内缓存。
6. 策略 checker 返回 `LONG`、`SHORT` 或 `FLAT`。
7. `process_signal_lifecycle()` 更新 `state["signals"]`，并在需要时产生
   进场或信号结束告警。
8. `process_review_queue()` 处理 AI 门控中的待审核进场信号。
9. `process_positions()` 检查用户确认持仓是否满足退出条件。
10. 监控器设置 `state["meta"]["initialized"] = True`。
11. `save_state()` 写回 JSON 状态。
12. 如果有告警，`send_telegram()` 将多个告警块合并为一条 Telegram 消息；
    未配置 Telegram 时打印 `[TG SKIP]`，不抛异常。

简化数据流：

```text
cron/loop
  -> tier1_monitor.run_once()
    -> load_state() / migrate_state()
    -> poll_telegram_commands()
    -> get_klines() 从 Binance 拉取行情
    -> STRATEGIES checker 函数
    -> process_signal_lifecycle()
      -> deliver_entry_alert()
        -> AI 审核开启时 queue_entry_review()
    -> process_review_queue()
      -> ai_review.run_review()
    -> process_positions()
      -> should_exit_position()
    -> save_state()
    -> send_telegram()
```

## 行情数据

`get_klines(symbol, interval, limit=500)` 使用 Binance 公共 K 线接口：

1. `https://api.binance.com/api/v3/klines`
2. `https://data-api.binance.vision/api/v3/klines`

不需要交易所 API key。两个接口都失败时，本周期跳过对应策略。

K 线解析由 `ohlc(klines)` 完成，返回 float 类型的 `opens`、`highs`、
`lows`、`closes`。

## 非重绘规则

所有策略逻辑应使用最后一根已收盘 K 线，而不是当前未收盘 K 线。
对应 helper：

```python
confirmed_indices() -> (-2, -3)
```

其中 `i = -2` 表示最近一根已收盘 K 线，`j = -3` 表示上一根已收盘 K 线。
除非明确要改变非重绘语义，不要用 `klines[-1]` 做策略决策。

## 指标 helper

主要技术指标 helper 位于 `scripts/tier1_monitor.py`：

- `ema_series(values, period)`
- `sma_series(values, period)`
- `true_range(highs, lows, closes)`
- `rsi_wilder(closes, period=14)` - Wilder/TradingView 风格 RSI。
- `stochastic_k(highs, lows, closes, k_period=14, smooth=3)`
- `macd_line_series(closes, fast=12, slow=26)`
- `macd_signal_series(closes, fast=12, slow=26, signal=9)`
- `bollinger(closes, length=20, mult=2.0)`
- `supertrend_direction(highs, lows, closes, period=10, multiplier=3.0, atr_mode="sma")`
- `cross_above(prev_a, curr_a, prev_b, curr_b)`
- `cross_below(prev_a, curr_a, prev_b, curr_b)`

新增或修改策略时，优先复用这些 helper。

## 策略注册表

`scripts/tier1_monitor.py` 中的 `STRATEGIES` 是运行时权威注册表。

每个策略 tuple 的结构：

```python
(strategy_id, name, symbol, interval, checker_fn, tradingview_url)
```

状态 key 生成方式：

```python
state_key(strategy_id, symbol, interval)
# 示例："12_BTCUSDT_4h"
```

### 策略行为表

| ID | 运行名 | 交易对 | 周期 | Checker | 运行逻辑 |
| --- | --- | --- | --- | --- | --- |
| 1 | BTC Mean Reversion RSI 20/65 | BTCUSDT | 15m | `check_01_mean_reversion` | RSI(14)<20、Stoch<25、close>EMA200 时做多；RSI>65、Stoch>75、close<EMA200 时做空。 |
| 2 | Volatility Breakout System | ETHUSDT | 1h | `check_02_volatility_breakout` | Donchian/range breakout proxy：close 突破前 20 根最高价为 LONG，跌破前 20 根最低价为 SHORT。 |
| 3 | SuperTrend AI Adaptive | BTCUSDT | 4h | `check_03_supertrend_ai` | SuperTrend(10,3) 方向 + EMA50 过滤；TradingView 的完整 AI 评分未离线复刻。 |
| 4 | BB Upper Breakout Short +2% | SOLUSDT | 1h | `check_04_bb_short` | close >= Bollinger 上轨(20,2) * 1.02 时 SHORT。 |
| 5 | SuperTrend STRATEGY (Daily) | BTCUSDT | 1d | `check_05_supertrend_daily` | 日线只做多 SuperTrend，SMA ATR(10)，hl2 源，乘数 8.5。 |
| 6 | Penguin Volatility State | BTCUSDT | 1d | `check_06_penguin_volatility` | 简化波动率状态：ATR 分位排名 > 0.7，方向由 close 与 EMA50 决定。 |
| 7 | MACD Zero-Line (Long) | BTCUSDT | 1d | `check_07_macd_zero` | MACD line 在 0 轴上方时 LONG，否则 FLAT。 |
| 8 | CDC MACD Fix | BTCUSDT | 1d | `check_08_cdc_macd` | MACD line/signal crossover proxy；line > signal 时 LONG。 |
| 9 | Hash Momentum | BTCUSDT | 4h | `check_09_hash_momentum` | 12-bar 动量为正且加速时 LONG；动量为负时 SHORT。 |
| 10 | Moon Phases L/S | BTCUSDT | 1h | `check_10_moon_phases` | 始终返回 FLAT，因为月相日历不能从 OHLC 推导。 |
| 11 | 7/19 EMA Cross | ETHUSDT | 30m | `check_11_ema_cross` | EMA7/EMA19 交叉和相对位置：上方 LONG，下方 SHORT。 |
| 12 | RSI > 70 Buy | BTCUSDT | 4h | `check_12_rsi70` | RSI 上穿 70 或维持在 70 上方时做多。 |
| 13 | 50/200 SMA + RSI Avg | ETHUSDT | 1d | `check_13_sma_rsi` | 只做多：close>SMA50、close>SMA200，且 SMA(RSI21,9)>57。 |
| 14 | Pivot SuperTrend | BTCUSDT | 4h | `check_14_pivot_supertrend` | SuperTrend 方向 + close 与当前 bar pivot 的关系。 |
| 15 | Keltner Breakout 4H | ETHUSDT | 4h | `check_15_keltner_breakout` | EMA20 +/- 1.5*ATR(10) 突破；上破 LONG，下破 SHORT。 |
| 16 | Hash Supertrend | SOLUSDT | 4h | `check_16_hash_supertrend` | 标准 SuperTrend(10,3)：多头方向 LONG，空头方向 SHORT。 |
| 17 | Crypto LONG PY | SOLUSDT | 5m | `check_17_crypto_long_py` | RSI 从超卖恢复的代理逻辑：上一根 RSI<30 且当前 RSI>=30 时 LONG。 |
| 18 | Oleg_Aryukov | BTCUSDT | 15m | `check_18_oleg` | EMA stack trend proxy：EMA9>EMA21>EMA55 为 LONG，反向排列为 SHORT。 |
| 19 | Options Daily Long UTC | ETHUSDT | 5m | `check_19_options_daily` | 时间窗口代理逻辑：UTC 08:30 到次日 08:00 期间 LONG。 |
| 20 | Qullamagi EMA Breakout | ETHUSDT | 1h | `check_20_qullamagi` | close 上穿 EMA20 且 EMA50 上升时 LONG；低于 EMA20 且 EMA50 下降时 SHORT。 |
| 21 | Kinetic Kalman Breakout | ETHUSDT | 15m | `check_21_kalman_breakout` | Kalman-style proxy：close 上破 EMA20+ATR 为 LONG，下破 EMA20-ATR 为 SHORT。 |

重要策略注意事项：

- 多个策略是复杂 Pine 逻辑的 proxy。除非完整移植 Pine，否则不要承诺与
  TradingView 逐笔完全一致。
- `#10` 故意保持 `FLAT`。
- `#5` 使用乘数 `8.5`，不是常见 SuperTrend 默认值 `3.0`。
- 只有 `#1`、`#7`、`#8`、`#11`、`#12`、`#13` 有专用退出规则。
  其他策略在 checker 不再返回持仓方向时退出。

## 信号生命周期逻辑

信号状态位于 `state["signals"][key]`。

典型 active 记录：

```json
{
  "direction": "LONG",
  "status": "active",
  "triggered_at": "YYYY-MM-DD HH:MM:SS UTC",
  "last_seen_at": "YYYY-MM-DD HH:MM:SS UTC"
}
```

`process_signal_lifecycle()` 规则：

- 同方向信号持续有效时，只更新 `last_seen_at`，不重复告警。
- 活跃信号变为 `FLAT` 时，标记为 `disappeared`，取消待处理 AI 审核，
  并发送 `Signal ended` 告警。
- 活跃信号方向翻转时，先告警旧信号结束，再记录新方向，并发送或排队新进场告警。
- 新状态首次运行时，`meta.initialized` 为 false。活跃信号只写入状态，不发送进场告警。
  这是为了避免历史已激活信号在首次运行时刷屏。

## 进场告警和 AI 审核门控

进场告警由 `deliver_entry_alert()` 处理。

- `ai_review.review_enabled()` 为 false 时，告警立即追加到 alerts。
- AI 审核开启时，`queue_entry_review()` 将待审项放入
  `state["review_queue"][key]`。
- 退出告警和信号结束告警不经过 AI 审核门控。

`process_review_queue()`：

1. 如有需要，为待审策略拉取 klines。
2. 如果信号不再 active 或方向发生变化，取消审核。
3. 调用 `ai_review.run_review(key, item, klines, logic_summary)`。
4. verdict 为 `None` 时保持 pending。
5. `PASS` 时发送原进场告警并附带 AI rationale。
6. `FAIL` 时发送 AI rejected 告警。
7. 将 `ai_verdict` 和 `ai_rationale` 写入对应 signal 记录。

`LOGIC_SUMMARY` 当前只对 `#1`、`#5`、`#7`、`#12` 有明确摘要；
其他策略回退到策略名称。

## AI review 模块

`scripts/ai_review.py` 通过 `AI_REVIEW_MODE` 支持四种模式：

| 模式 | 行为 |
| --- | --- |
| `auto` | 有 API key 时使用 API；否则如果 queue dir 存在则使用 file；否则关闭，除非显式开启。 |
| `api` | 调用 OpenAI-compatible chat completions endpoint。需要 `AI_REVIEW_API_KEY` 或 `OPENAI_API_KEY`。 |
| `file` | 写 pending JSON 文件，并等待 agent 写 response 文件。 |
| `off` | 跳过 AI 审核；`run_review()` 返回 PASS。 |

API prompt 生成：

- `compact_klines()` 默认带最近 `AI_REVIEW_CANDLES=50` 根 K 线。
- `build_prompt()` 要求只返回 JSON：
  `{"verdict":"PASS" or "FAIL","rationale":"one or two sentences"}`。
- `parse_verdict()` 优先解析严格 JSON，然后尝试从文本中恢复 JSON 对象，
  最后使用 PASS/FAIL 关键词兜底。
- API 错误会 fail safe，返回 `FAIL`。

File queue 协议：

```bash
export AI_REVIEW_MODE=file
export AI_REVIEW_QUEUE_DIR=/data/hermes/tier1_review
```

监控器写入：

```text
${AI_REVIEW_QUEUE_DIR}/pending/{state_key}.json
```

审核 agent 需要写入：

```text
${AI_REVIEW_QUEUE_DIR}/done/{state_key}.response.json
```

响应体：

```json
{
  "verdict": "PASS",
  "rationale": "Momentum and market structure confirm the signal."
}
```

pending file 超过 `AI_REVIEW_FILE_MAX_WAIT` 秒后默认 FAIL。默认超时为 600 秒。

## 持仓跟踪

系统不会自动开仓。用户必须确认信号。

CLI 确认：

```bash
python3 scripts/tier1_monitor.py confirm 12
python3 scripts/tier1_monitor.py confirm 12 98500
```

Telegram 确认：

```text
/confirm 12
/confirm 12 98500
```

确认后的记录位于 `state["positions"][key]`：

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

`process_positions()` 每个周期检查退出：

- 通过 ID 加载策略。
- 拉取或复用当前 klines。
- 调用 `should_exit_position()`。
- 如果应退出，发送 `Close position` 告警，并从 state 中删除持仓。

专用退出函数：

- `exit_01_mean_reversion`
- `exit_07_macd_zero`
- `exit_08_cdc_macd`
- `exit_11_ema_cross`
- `exit_12_rsi70`
- `exit_13_sma_rsi`

默认退出规则：

```text
LONG 在 checker(klines) != "LONG" 时退出
SHORT 在 checker(klines) != "SHORT" 时退出
```

手动关闭：

```bash
python3 scripts/tier1_monitor.py close 12
```

Telegram：

```text
/close 12
```

## 状态文件

默认路径：

```text
scripts/tier1_monitor_state.json
```

覆盖路径：

```bash
export TIER1_STATE_FILE=/stable/path/tier1_monitor_state.json
```

Version 2 状态结构：

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

`migrate_state()` 接受旧 v1 风格状态：任意 key 直接映射到 `LONG` 或
`SHORT`，并将其迁移到 `signals`。

生产环境应将 state 放到持久化路径。默认 state 文件已被 git 忽略。

## Telegram 行为

环境变量：

```bash
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export TELEGRAM_THREAD_ID=205
```

`send_telegram()` 发送到：

```text
https://api.telegram.org/bot{token}/sendMessage
```

token 或 chat ID 缺失时，只打印 `[TG SKIP]`，不抛异常。

`poll_telegram_commands()` 通过同一告警管道发送回复，并在 state 中记录
`telegram_offset`，避免重复处理 update。

支持的 Telegram 命令：

| 命令 | 含义 |
| --- | --- |
| `/confirm {id}` | 确认活跃信号并开始退出监控。 |
| `/confirm {id} {price}` | 使用显式 entry price 确认。 |
| `/close {id}` | 停止跟踪某个确认持仓。 |
| `/status` | 展示活跃信号、AI 待审项和 open positions。 |

## 环境变量

Monitor 变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `TIER1_DOTENV` | `/root/.hermes/.env` | 启动时加载的 dotenv 路径。 |
| `TIER1_STATE_FILE` | `scripts/tier1_monitor_state.json` | JSON 状态路径。 |
| `TELEGRAM_BOT_TOKEN` | 空 | Telegram bot token。 |
| `TELEGRAM_CHAT_ID` | 空 | Telegram 目标 chat。 |
| `TELEGRAM_THREAD_ID` | `205` | Telegram forum topic/thread ID。 |

AI review 变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AI_REVIEW_MODE` | `auto` | `auto`、`api`、`file` 或 `off`。 |
| `AI_REVIEW_ENABLED` | 空 | 在 auto mode 下显式开启；值为 `1`、`true`、`yes`。 |
| `AI_REVIEW_API_KEY` | 空 | OpenAI-compatible chat completions API key。 |
| `OPENAI_API_KEY` | 空 | 备用 API key。 |
| `AI_REVIEW_API_URL` | 派生 | 显式 chat completions URL。 |
| `OPENAI_API_BASE` | `https://api.openai.com/v1` | 未设置显式 URL 时使用的 base URL。 |
| `AI_REVIEW_MODEL` | `gpt-4o-mini` | Chat model。 |
| `AI_REVIEW_CANDLES` | `50` | review payload 中附带的 K 线数量。 |
| `AI_REVIEW_TIMEOUT` | `90` | API 请求超时秒数。 |
| `AI_REVIEW_QUEUE_DIR` | `/data/hermes/tier1_review` | File queue 根目录。 |
| `AI_REVIEW_FILE_MAX_WAIT` | `600` | File review 超时秒数。 |

## 测试和验证

主要 QA 命令：

```bash
python3 scripts/test_tier1_qa.py
```

测试脚本覆盖：

- RSI 和 SuperTrend helper 的单元检查。
- 状态迁移和读写 round-trip。
- 信号消失、持续、翻转、首次运行不刷屏。
- confirm/close position。
- 策略退出行为 smoke test。
- AI verdict 解析和 file queue 行为。
- 使用 Binance live public klines 跑 21 个策略的集成测试。

Binance 集成测试需要外网。如果失败原因是 Binance 不可达，先单独确认纯
unit 行为，再修改策略逻辑。

## 修改 playbook

### 新增或修改策略

1. 编辑 `scripts/tier1_monitor.py`。
2. 新增或更新 `check_XX_*` 函数。
3. 确保函数只返回 `LONG`、`SHORT` 或 `FLAT`。
4. 使用 `confirmed_indices()` 和已收盘 K 线。
5. 在 `STRATEGIES` 注册策略。
6. 如果 AI review 需要更清晰摘要，更新 `LOGIC_SUMMARY`。
7. 只有当退出逻辑不同于默认规则时，才新增 `exit_XX_*` 并加入 `EXIT_BY_ID`。
8. 更新 `docs/STRATEGIES.md`。
9. 运行 `python3 scripts/test_tier1_qa.py`。

### 修改 AI review 行为

1. 如需修改 mode resolution、prompt、parser、API 或 file queue 行为，
   编辑 `scripts/ai_review.py`。
2. 同时检查 `scripts/tier1_monitor.py` 中的 `deliver_entry_alert()`、
   `queue_entry_review()`、`process_review_queue()`。
3. 除非产品行为明确改变，否则保持退出告警和信号结束告警不经过 AI 门控。
4. 更新 `docs/AI_REVIEW.md`。
5. 运行 `python3 scripts/test_tier1_qa.py`。

### 修改 state 行为

1. 编辑 `scripts/tier1_monitor.py` 中的 `migrate_state()`、`load_state()`、
   `save_state()`。
2. 尽量保留已部署 state 的兼容性。
3. 更新 `scripts/test_tier1_qa.py` 中 state 相关测试。
4. 保持 `TIER1_STATE_FILE` 覆盖行为。

### 修改 Telegram 命令行为

1. 编辑 `scripts/tier1_monitor.py` 中的 `poll_telegram_commands()`、
   `cmd_confirm()`、`cmd_close()` 或 `cmd_status_text()`。
2. 尽量保持 CLI 与 Telegram 语义一致。
3. 添加或更新 `scripts/test_tier1_qa.py` 测试。

## 本仓库 agent 操作规则

- 保持改动精简。本仓库刻意采用小型脚本架构。
- 除非明确要求，不要引入包结构、框架、后台服务或新依赖。
- 不要自动开仓。本系统只生成信号并跟踪用户确认后的持仓。
- 不要要求交易所 API key 才能获取行情。
- 保留首次运行不刷屏行为。
- 保留已收盘 K 线/非重绘语义。
- 注意 live network 测试：`test_all_strategies_live()` 会访问 Binance。
- 不要提交生成的 state 文件或 AI queue 文件。
- 如果新增运行时文件，必要时同步更新 `.gitignore`。
