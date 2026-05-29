# Crypto-Trading-Signals

**自动监控 BTC、ETH、SOL 顶级交易策略信号。**

*让 AI 成为你的专业量化交易台。*

这不只是一个信号提醒工具。它是一个建立在 **AI 独立决策流程** 之上的
**生产级监控系统**，面向加密货币 scalper 和 swing trader。仓库内打包了
21 套机构级 Alpha 策略，可供你的 AI Agent（Hermes / OpenClaw）使用。

该系统已用于 2.5 BTC DCA Campaign（90 万 USDT 流动性）的生产环境。

---

## 1. 策略基础：机构级 Alpha

全部 **21 套策略逻辑** 对齐 2026 年 4 月版本的 TradingView 机构级 Pine
Script 来源：

- **深度对齐**：不是通用指标的粗略拼接；逻辑以原始开源 Pine Script 实现为基准。
- **覆盖完整**：BTC、ETH、SOL 均覆盖；包括均值回归、波动率突破、均线堆叠趋势系统，
  以及特殊模型（包括适用场景下的月相日历）。
- **可接入交易场景**：执行语义兼容 **HyperLiquid**、**Binance** 等深度流动性场所。

策略参考表和 TradingView 链接见：[docs/STRATEGIES.md](docs/STRATEGIES.md)。

### 核心策略示例

| # | 策略 | 说明 |
|---|------|------|
| 1 | RSI Mean Reversion | RSI &lt; 20 + Stoch + EMA200 做多；RSI &gt; 65 做空 |
| 3 | SuperTrend AI | BTC 4h 上的 SuperTrend + EMA50 |
| 5 | SuperTrend Daily | SMA-ATR SuperTrend，乘数 **8.5**，BTC 1d，只做多 |
| 7 | MACD Zero-Line | MACD line 高于 0 轴时只做多 |
| 12 | RSI &gt; 70 Buy | RSI &gt; 70 时的动量做多 |

## 2. 为什么使用这套系统

- **模型多样化**：21 个独立引擎降低单策略在震荡行情中失效的风险。
- **高保真执行**：Python monitor 对齐 Pine 逻辑，并基于已收盘 K 线运行，目标是降低与
  TradingView 逻辑的偏移。
- **强过滤条件**：ADX momentum、EMA trend、stochastic extremes、volume surge 和复合规则
  用于减少误报。

## 3. 功能亮点

### AI 独立审核队列（已实现）

当 monitor 触发 **新进场** 信号时，会将 **最近 50 根 K 线** 和策略上下文打包交给
AI 审核。只有返回 **PASS** 的结果才会作为交易告警推送，并附带模型理由。
**FAIL** 会发送一条简短的拒绝通知。信号 **结束** 和 **平仓/关闭持仓** 告警不会经过
AI 门控。

可通过 API 或文件队列配置，详见 [docs/AI_REVIEW.md](docs/AI_REVIEW.md)。

```bash
# 方案 A：OpenAI-compatible API
export AI_REVIEW_API_KEY="your-key"

# 方案 B：Hermes / OpenClaw agent 文件队列
export AI_REVIEW_ENABLED=true
export AI_REVIEW_MODE=file
export AI_REVIEW_QUEUE_DIR=/data/hermes/tier1_review
```

如果没有设置 `AI_REVIEW_API_KEY`，也没有设置 `AI_REVIEW_ENABLED=true`，
进场告警会直接发送（AI gate 关闭）。

### 持仓生命周期跟踪（退出监控）

引擎不会停留在“买入信号”阶段。它会在 monitor state 中跟踪 **已确认持仓**，
并每 5 分钟运行 **按策略划分的退出逻辑**，避免错过止盈或趋势退出条件。

### 零配置通用投递

行情数据不需要交易所 API key。只有直接使用 Telegram bot 投递时才需要可选的
Telegram 凭据；否则可以把告警路由到 Agent 的 **deliver** 通道，例如 Telegram、
Discord、Web 等。

---

## 运行方式（5 分钟周期）

```bash
# Cron（推荐）
*/5 * * * * cd /path/to/repo && python3 scripts/tier1_monitor.py run

# 或常驻循环
python3 scripts/tier1_monitor.py loop
```

每个周期执行：

1. **信号生命周期**：信号触发时告警；信号持续时保持静默；信号 **结束** 时告警。
2. **已确认持仓**：记录入场后，持续监控 **退出条件** 并发送关闭持仓告警。

### Telegram 命令

| 命令 | 动作 |
|------|------|
| `/confirm 12` | 记录你已根据 #12 策略开仓；可选价格：`/confirm 12 98500` |
| `/close 12` | 手动停止跟踪 #12 持仓 |
| `/status` | 列出活跃信号和 open positions |

CLI 对应命令：

```bash
python3 scripts/tier1_monitor.py confirm 12
python3 scripts/tier1_monitor.py close 12
python3 scripts/tier1_monitor.py status
```

**状态文件：** `TIER1_STATE_FILE`，默认 `scripts/tier1_monitor_state.json`，
其中包含 `signals` 和 `positions`。

## 技术栈

- **数据源：** Binance public klines（`data-api.binance.vision` fallback）
- **运行时：** Python 3.x，**300s** 轮询间隔
- **Agent：** Hermes / OpenClaw 集成

## 文件说明

| 路径 | 作用 |
|------|------|
| `scripts/tier1_monitor.py` | 主监控引擎 |
| `scripts/ai_review.py` | AI 二次审核门控 |
| `scripts/test_tier1_qa.py` | QA smoke tests |
| `docs/STRATEGIES.md` | 21 套策略和 TradingView 链接 |
| `docs/AI_REVIEW.md` | AI review 配置和文件队列协议 |
| `.cursor/skills/crypto-trading-signals/SKILL.md` | 英文 agent skill |
| `.cursor/skills/crypto-trading-signals-zh/SKILL.md` | 中文 agent skill |

## QA

```bash
python3 scripts/test_tier1_qa.py
```

该 QA 脚本包含轻量逻辑测试，并会使用 Binance live public klines 对 21 个策略做集成检查。
