#!/usr/bin/env python3
"""Lightweight QA for tier1_monitor (no pytest required)."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tier1_monitor as m

PASS, FAIL = 0, 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def test_rsi_wilder_bounds():
    closes = [100 + (i % 5) - 2 for i in range(50)]
    series = m.rsi_wilder(closes, 14)
    valid = [x for x in series if x is not None]
    ok("RSI produces values", len(valid) > 0)
    ok("RSI in 0-100", all(0 <= x <= 100 for x in valid))


def test_supertrend_direction_values():
    n = 80
    closes = [100 + i * 0.5 for i in range(n)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    st = m.supertrend_direction(highs, lows, closes, 10, 3.0)
    ok("SuperTrend values in {-1,1}", set(st) <= {-1, 1})


def test_migrate_state_v1():
    old = {"12_BTCUSDT_4h": "LONG", "3_BTCUSDT_4h": "SHORT"}
    new = m.migrate_state(old)
    ok("migrate version", new.get("version") == 2)
    ok("migrate signals", "12_BTCUSDT_4h" in new["signals"])
    ok("migrate direction", new["signals"]["12_BTCUSDT_4h"]["direction"] == "LONG")


def test_signal_lifecycle_disappear():
    state = m.migrate_state({})
    alerts = []
    key = "99_BTCUSDT_1h"
    state["signals"][key] = {
        "direction": "LONG",
        "status": "active",
        "triggered_at": "t0",
        "last_seen_at": "t0",
    }
    m.process_signal_lifecycle(
        state, key, 99, "Test", "BTCUSDT", "1h", "FLAT", "http://tv", alerts
    )
    ok("disappear alert", len(alerts) == 1 and "Signal ended" in alerts[0])
    ok("status disappeared", state["signals"][key]["status"] == "disappeared")


def test_signal_lifecycle_persist():
    state = m.migrate_state({})
    alerts = []
    key = "99_BTCUSDT_1h"
    state["signals"][key] = {
        "direction": "LONG",
        "status": "active",
        "triggered_at": "t0",
        "last_seen_at": "t0",
    }
    m.process_signal_lifecycle(
        state, key, 99, "Test", "BTCUSDT", "1h", "LONG", "http://tv", alerts
    )
    ok("persist no alert", len(alerts) == 0)
    ok("last_seen updated", state["signals"][key]["last_seen_at"] != "t0")


def test_signal_lifecycle_flip():
    state = m.migrate_state({})
    alerts = []
    key = "99_BTCUSDT_1h"
    state["signals"][key] = {
        "direction": "LONG",
        "status": "active",
        "triggered_at": "t0",
        "last_seen_at": "t0",
    }
    m.process_signal_lifecycle(
        state, key, 99, "Test", "BTCUSDT", "1h", "SHORT", "http://tv", alerts
    )
    ok("flip: ended + new", len(alerts) == 2)
    ok("flip: now active SHORT", state["signals"][key]["direction"] == "SHORT")


def test_confirm_reject_no_signal():
    state = m.migrate_state({})
    # strategy 10 always FLAT
    ok_confirm, _ = m.cmd_confirm(state, 10)
    ok("confirm rejects #10 moon", not ok_confirm)


def test_confirm_with_active_signal():
    state = m.migrate_state({})
    strat = m.get_strategy(12)
    sid, _, symbol, interval, checker, _ = strat
    key = m.state_key(sid, symbol, interval)
    state["signals"][key] = {
        "direction": "LONG",
        "status": "active",
        "triggered_at": "t",
        "last_seen_at": "t",
    }
    ok_confirm, msg = m.cmd_confirm(state, 12, 100000.0)
    ok("confirm ok", ok_confirm)
    ok("position stored", key in state["positions"])
    ok("entry price", state["positions"][key]["entry_price"] == 100000.0)


def test_close_position():
    state = m.migrate_state({})
    strat = m.get_strategy(12)
    sid, _, symbol, interval, _, _ = strat
    key = m.state_key(sid, symbol, interval)
    state["positions"][key] = {"strategy_id": 12, "side": "LONG", "symbol": symbol, "interval": interval}
    ok_close, _ = m.cmd_close(state, 12)
    ok("close ok", ok_close)
    ok("position removed", key not in state["positions"])


def test_exit_12_rsi_below_70():
    # Build synthetic klines: rising closes -> high RSI
    rows = []
    price = 50000.0
    for i in range(60):
        price *= 1.008
        t = 1700000000000 + i * 14400000
        rows.append([t, str(price), str(price * 1.01), str(price * 0.99), str(price), "0", t + 1, "0", 0, "0", "0", "0"])
    # Force exit path with checker returning FLAT after high run
    sig = m.check_12_rsi70(rows)
    exited = m.exit_12_rsi70(rows, "LONG")
    ok("check_12 runs", sig in ("LONG", "FLAT"))
    ok("exit_12 runs", isinstance(exited, bool))


def test_all_strategies_live():
    """Integration: each strategy returns valid signal from Binance."""
    bad = []
    for sid, name, symbol, interval, checker, _ in m.STRATEGIES:
        kl = m.get_klines(symbol, interval, limit=200)
        if not kl:
            bad.append(f"#{sid} no klines")
            continue
        try:
            sig = checker(kl)
            if sig not in ("LONG", "SHORT", "FLAT"):
                bad.append(f"#{sid} bad signal {sig!r}")
        except Exception as e:
            bad.append(f"#{sid} {e}")
    ok("all 21 strategies run", len(bad) == 0, "; ".join(bad[:5]))


def test_first_run_no_spam():
    state = m.migrate_state({})
    state["meta"]["initialized"] = False
    alerts = []
    m.process_signal_lifecycle(
        state, "k", 1, "T", "BTCUSDT", "1h", "LONG", "http://x", alerts
    )
    ok("first run seeds without alert", len(alerts) == 0)
    state["meta"]["initialized"] = True
    alerts.clear()
    m.process_signal_lifecycle(
        state, "k2", 2, "T", "BTCUSDT", "1h", "LONG", "http://x", alerts
    )
    ok("after init new signal alerts", len(alerts) == 1)


def test_state_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "st.json")
        old = m.STATE_FILE
        m.STATE_FILE = path
        try:
            s = m.migrate_state({})
            s["signals"]["1_BTCUSDT_15m"] = {
                "direction": "LONG",
                "status": "active",
                "triggered_at": "x",
                "last_seen_at": "x",
            }
            m.save_state(s)
            loaded = m.load_state()
            ok("state roundtrip", loaded["signals"]["1_BTCUSDT_15m"]["direction"] == "LONG")
        finally:
            m.STATE_FILE = old


def main():
    print("=== tier1_monitor QA ===\n")
    print("Unit / logic:")
    test_rsi_wilder_bounds()
    test_supertrend_direction_values()
    test_migrate_state_v1()
    test_signal_lifecycle_disappear()
    test_signal_lifecycle_persist()
    test_signal_lifecycle_flip()
    test_confirm_reject_no_signal()
    test_confirm_with_active_signal()
    test_close_position()
    test_exit_12_rsi_below_70()
    test_state_roundtrip()
    print("\nIntegration (Binance):")
    test_all_strategies_live()
    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
