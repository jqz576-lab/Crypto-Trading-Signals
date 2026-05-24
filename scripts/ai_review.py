#!/usr/bin/env python3
"""AI second-pass gate for Tier1 entry signals (PASS / FAIL)."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

REVIEW_CANDLES = int(os.environ.get("AI_REVIEW_CANDLES", "50"))
def _env_mode() -> str:
    return os.environ.get("AI_REVIEW_MODE", "auto").lower()
REVIEW_QUEUE_DIR = os.environ.get(
    "AI_REVIEW_QUEUE_DIR", "/data/hermes/tier1_review"
)
def _default_api_url() -> str:
    explicit = os.environ.get("AI_REVIEW_API_URL", "")
    if explicit:
        return explicit
    base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    return f"{base}/chat/completions"


API_URL = _default_api_url()
API_KEY = os.environ.get("AI_REVIEW_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("AI_REVIEW_MODEL", "gpt-4o-mini")
API_TIMEOUT = int(os.environ.get("AI_REVIEW_TIMEOUT", "90"))
FILE_MAX_AGE_SEC = int(os.environ.get("AI_REVIEW_FILE_MAX_WAIT", "600"))


def review_enabled() -> bool:
    mode = _env_mode()
    if mode == "off":
        return False
    if mode == "file":
        return True
    if mode == "api":
        return bool(API_KEY)
    # auto: need API key, existing queue dir, or explicit opt-in
    if API_KEY:
        return True
    if os.path.isdir(REVIEW_QUEUE_DIR):
        return True
    return os.environ.get("AI_REVIEW_ENABLED", "").lower() in ("1", "true", "yes")


def _resolve_mode() -> str:
    mode = _env_mode()
    if mode in ("api", "file", "off"):
        return mode
    if API_KEY:
        return "api"
    if os.path.isdir(REVIEW_QUEUE_DIR):
        return "file"
    return "off"


def compact_klines(klines: List, n: int = REVIEW_CANDLES) -> List[Dict[str, Any]]:
    tail = klines[-n:] if len(klines) >= n else klines
    out = []
    for k in tail:
        out.append(
            {
                "t": int(k[0]),
                "o": float(k[1]),
                "h": float(k[2]),
                "l": float(k[3]),
                "c": float(k[4]),
                "v": float(k[5]),
            }
        )
    return out


def build_prompt(payload: Dict[str, Any]) -> str:
    return f"""You are an independent quant reviewer for a crypto signal monitor.

Strategy #{payload['strategy_id']}: {payload['name']}
Pair: {payload['symbol']}  Timeframe: {payload['interval']}
Candidate direction: {payload['direction']}
Event: {payload.get('event', 'new')}
Monitor logic summary: {payload.get('logic_summary', 'See TradingView script.')}

Last {len(payload['candles'])} closed candles (oldest first):
{json.dumps(payload['candles'], separators=(',', ':'))}

Task:
1. Re-check whether {payload['direction']} is justified from price action and the stated logic.
2. Flag obvious false positives (chop, conflicting trend, stale breakout, wrong regime).

Reply with JSON only, no markdown:
{{"verdict":"PASS" or "FAIL", "rationale":"one or two sentences"}}
"""


def parse_verdict(text: str) -> Tuple[Optional[str], str]:
    text = text.strip()
    try:
        data = json.loads(text)
        v = str(data.get("verdict", "")).upper()
        if v in ("PASS", "FAIL"):
            return v, str(data.get("rationale", ""))[:500]
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[^{}]*\"verdict\"\s*:\s*\"(PASS|FAIL)\"[^{}]*\}", text, re.I | re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            return data["verdict"].upper(), str(data.get("rationale", ""))[:500]
        except json.JSONDecodeError:
            pass
    upper = text.upper()
    if "PASS" in upper and "FAIL" not in upper:
        return "PASS", text[:500]
    if "FAIL" in upper:
        return "FAIL", text[:500]
    return None, text[:500]


def review_via_api(payload: Dict[str, Any]) -> Tuple[Optional[str], str]:
    if not API_KEY:
        return None, "AI_REVIEW_API_KEY not set"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": MODEL,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": "You are a strict trading signal auditor. Output JSON only.",
            },
            {"role": "user", "content": build_prompt(payload)},
        ],
    }
    try:
        resp = requests.post(API_URL, headers=headers, json=body, timeout=API_TIMEOUT)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return parse_verdict(content)
    except Exception as exc:
        return None, f"API error: {exc}"


def _queue_paths(key: str) -> Tuple[str, str, str]:
    safe = re.sub(r"[^\w.-]", "_", key)
    pending = os.path.join(REVIEW_QUEUE_DIR, "pending", f"{safe}.json")
    done = os.path.join(REVIEW_QUEUE_DIR, "done", f"{safe}.response.json")
    return pending, done, safe


def review_via_file(payload: Dict[str, Any], key: str, submitted_at: str) -> Tuple[Optional[str], str]:
    os.makedirs(os.path.join(REVIEW_QUEUE_DIR, "pending"), exist_ok=True)
    os.makedirs(os.path.join(REVIEW_QUEUE_DIR, "done"), exist_ok=True)
    pending_path, done_path, _ = _queue_paths(key)

    if not os.path.exists(pending_path):
        with open(pending_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    **payload,
                    "state_key": key,
                    "prompt": build_prompt(payload),
                    "submitted_at": submitted_at,
                },
                f,
                indent=2,
            )
        return None, "waiting for agent response file"

    if os.path.exists(done_path):
        try:
            with open(done_path, encoding="utf-8") as f:
                data = json.load(f)
            v = str(data.get("verdict", "")).upper()
            rationale = str(data.get("rationale", ""))[:500]
            if v in ("PASS", "FAIL"):
                os.remove(pending_path)
                return v, rationale
        except Exception as exc:
            return None, f"bad response file: {exc}"

    # timeout → fail safe
    try:
        age = time.time() - os.path.getmtime(pending_path)
        if age > FILE_MAX_AGE_SEC:
            return "FAIL", f"review timeout after {FILE_MAX_AGE_SEC}s"
    except OSError:
        pass
    return None, "waiting for agent response file"


def run_review(
    key: str,
    item: Dict[str, Any],
    klines: List,
    logic_summary: str = "",
) -> Tuple[Optional[str], str]:
    """
    Returns (verdict, rationale).
    verdict None = still pending (retry next 5m cycle).
    """
    if not review_enabled():
        return "PASS", "AI review disabled"

    payload = {
        "strategy_id": item["strategy_id"],
        "name": item["name"],
        "symbol": item["symbol"],
        "interval": item["interval"],
        "direction": item["direction"],
        "event": item.get("event", "new"),
        "logic_summary": logic_summary or item.get("logic_summary", ""),
        "candles": compact_klines(klines),
    }

    mode = _resolve_mode()
    if mode == "off":
        return "PASS", "AI review off"
    if mode == "api":
        return review_via_api(payload)
    return review_via_file(payload, key, item.get("submitted_at", ""))
