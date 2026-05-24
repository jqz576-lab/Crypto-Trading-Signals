# AI second-pass gate (PASS / FAIL)

Entry signals (`Signal active`, `New signal`) are held until an AI reviewer returns **PASS**. Exit / disappear alerts are **not** gated.

## Modes

| `AI_REVIEW_MODE` | Behavior |
|------------------|----------|
| `auto` (default) | Use OpenAI-compatible API if `AI_REVIEW_API_KEY` is set; else file queue under `AI_REVIEW_QUEUE_DIR` |
| `api` | Call chat completions API every cycle until verdict |
| `file` | Write `pending/{key}.json`; Hermes/agent writes `done/{key}.response.json` |
| `off` | Skip gate (immediate Telegram like before) |

## API mode

```bash
export AI_REVIEW_API_KEY="sk-..."
export AI_REVIEW_MODEL="gpt-4o-mini"          # optional
export AI_REVIEW_API_URL="https://api.openai.com/v1/chat/completions"  # optional
export AI_REVIEW_CANDLES=50
```

## File mode (Hermes / OpenClaw agent)

```bash
export AI_REVIEW_MODE=file
export AI_REVIEW_QUEUE_DIR=/data/hermes/tier1_review
```

1. Monitor writes `pending/12_BTCUSDT_4h.json` (includes `prompt` + candles).
2. Your agent reads it, runs the main model, writes:

`done/12_BTCUSDT_4h.response.json`:

```json
{
  "verdict": "PASS",
  "rationale": "RSI holds above 70 with rising structure; momentum intact."
}
```

3. Next `run` cycle delivers the signal alert (or rejection if `FAIL`).

Pending reviews older than `AI_REVIEW_FILE_MAX_WAIT` (default 600s) auto-**FAIL**.

## State

- `review_queue` — in-flight reviews
- `signals.{key}.ai_verdict` — `PASS` / `FAIL` after completion

Check pending: `python3 scripts/tier1_monitor.py status`
