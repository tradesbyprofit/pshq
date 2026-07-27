"""
trade_manager.py — Method-faithful trade management for open ICC trades.

Every run it revisits each open trade and applies Trades By Sci's actual management:
  1. Partial profit + breakeven  (Day 3: "collect some partials, then hold long-term")
  2. Trailing runner              (Day 3/4: "keep targeting new highs" while structure holds)
  3. Structure-break exit         (Day 9: "the moment price breaks structure, exit")
  4. Max-hold cap                 (Day 11: most trades 8-12h; don't hold dead money)

Sends Telegram (via notifier) on: partial taken + EVERY close (with realized P/L).
Trail-only moves are console-logged (too frequent to ping). State persists in
open_trades.json across the 15-min GitHub runs.

SAFE-BIASED: the baseline SL + backstop TP (set at entry) always protect; this
layer only ADDS favorable actions. Worst case it behaves like the simple bot.
"""
from __future__ import annotations
import os, json, datetime as dt
from typing import List, Optional
from icc_engine import Candle, Direction, detect_swings

JOURNAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "open_trades.json")

PARTIAL_PCT = 0.5            # close half at tp1
INITIAL_MAX_HOLD_HOURS = 24  # if tp1 not reached by then, close (stalled)
RUNNER_MAX_HOLD_HOURS = 120  # 5-day cap on the runner


def _notify(notifier, text: str):
    if notifier is None:
        return
    try:
        notifier.send_text(text)
    except Exception:
        pass


# ----------------------------- journal --------------------------------------
def load() -> list:
    if os.path.exists(JOURNAL):
        try:
            return json.load(open(JOURNAL)).get("trades", [])
        except Exception:
            return []
    return []

def save(trades: list):
    json.dump({"trades": trades}, open(JOURNAL, "w"), indent=2)

def open_trade(broker, sig) -> dict:
    """Open a managed trade and record it in the journal."""
    res = broker.open_managed(sig)
    if res.get("opened"):
        trades = load()
        trades.append({
            "trade_id": res["trade_id"], "symbol": sig.symbol,
            "instrument": res["instrument"], "direction": sig.direction.value,
            "entry": res["entry"], "stop": res["stop"], "tp1": res["tp1"],
            "tp_final": res["tp_final"], "entry_time": dt.datetime.utcnow().isoformat(),
            "initial_size": res["initial_size"], "partial_taken": False,
        })
        save(trades)
    return res


# ------------------- pure decision helpers (unit-testable) ------------------
def _should_partial(price, tp1, direction, taken) -> bool:
    if taken:
        return False
    return price >= tp1 if direction == Direction.BULL else price <= tp1

def _should_maxhold(elapsed_hours, partial_taken) -> bool:
    cap = RUNNER_MAX_HOLD_HOURS if partial_taken else INITIAL_MAX_HOLD_HOURS
    return elapsed_hours > cap

def _structure_break(candles_1h, direction) -> bool:
    """Long invalidation: close < last 1H higher-low. Short: close > last lower-high."""
    if len(candles_1h) < 6:
        return False
    swings = detect_swings(candles_1h)
    last_close = candles_1h[-1].c
    if direction == Direction.BULL:
        lows = [s for s in swings if s.kind.value == "low"]
        return bool(lows) and last_close < lows[-1].price
    highs = [s for s in swings if s.kind.value == "high"]
    return bool(highs) and last_close > highs[-1].price

def _trailing_sl(candles_15m, direction, current_sl, current_price) -> Optional[float]:
    if len(candles_15m) < 6:
        return None
    swings = detect_swings(candles_15m)
    buf = current_price * 0.0002
    if direction == Direction.BULL:
        lows = [s for s in swings if s.kind.value == "low"]
        if not lows:
            return None
        cand = lows[-1].price - buf
        return cand if (cand > current_sl and cand < current_price) else None
    highs = [s for s in swings if s.kind.value == "high"]
    if not highs:
        return None
    cand = highs[-1].price + buf
    return cand if (cand < current_sl and cand > current_price) else None


def _realized(broker, tid) -> float:
    """Read realized P/L (account currency) of a (possibly just-closed) trade."""
    try:
        return float(broker.get_trade(tid).get("realizedPL", 0))
    except Exception:
        return 0.0


# ----------------------------- manage loop ----------------------------------
def manage(feed, broker, notifier=None, now: dt.datetime = None) -> List[str]:
    """Revisit every open trade. Returns console-log lines; pings notifier on key events."""
    now = now or dt.datetime.utcnow()
    trades = load()
    if not trades:
        return []
    log: List[str] = []

    for tr in trades:
        tid, sym = tr["trade_id"], tr["symbol"]
        direction = Direction.BULL if tr["direction"] == "bull" else Direction.BEAR
        t = broker.get_trade(tid)

        # 0) sync: already closed by TP/SL/backstop?
        if not t or t.get("state") != "OPEN":
            pl = float(t.get("realizedPL", 0)) if t else 0.0
            tag = "✅ WIN" if pl >= 0 else "🛑 LOSS"
            msg = f"{tag} — {sym}: closed (TP/SL). P/L ${pl:+.2f}"
            log.append(msg); _notify(notifier, msg)
            tr["_drop"] = True
            continue

        try:
            current_sl = float(t["stopLossOrder"]["price"])
        except Exception:
            current_sl = tr["stop"]
        try:
            c15 = feed.candles(sym, "15M", 120)
            c1h = feed.candles(sym, "1H", 120)
        except Exception as e:
            log.append(f"{sym}: data unavailable ({str(e)[:40]}) — skip this run.")
            continue
        price15 = c15[-1].c
        elapsed = (now - dt.datetime.fromisoformat(tr["entry_time"])).total_seconds() / 3600.0

        # 1) max-hold cap
        if _should_maxhold(elapsed, tr["partial_taken"]):
            broker.close_trade(tid)
            pl = _realized(broker, tid)
            msg = f"⚪ {sym}: max-hold ({elapsed:.0f}h) — closed. P/L ${pl:+.2f}"
            log.append(msg); _notify(notifier, msg)
            tr["_drop"] = True
            continue
        # 2) structure-break exit
        if _structure_break(c1h, direction):
            broker.close_trade(tid)
            pl = _realized(broker, tid)
            msg = f"🔴 {sym}: structure broke → closed early. P/L ${pl:+.2f}"
            log.append(msg); _notify(notifier, msg)
            tr["_drop"] = True
            continue
        # 3) partial + breakeven
        if _should_partial(price15, tr["tp1"], direction, tr["partial_taken"]):
            r = broker.reduce_position(tid, tr["initial_size"] * PARTIAL_PCT)
            if r.get("done"):
                tr["partial_taken"] = True
                be = broker.set_stop_loss(tid, tr["entry"])
                msg = (f"📊 {sym}: banked {PARTIAL_PCT:.0%} @ {tr['tp1']}; "
                       f"SL → breakeven ({'ok' if be.get('done') else be.get('reason')}). Runner risk-free.")
                log.append(msg); _notify(notifier, msg)
            else:
                log.append(f"{sym}: partial failed ({r.get('reason')}).")
        # 4) trail the runner (console only — too frequent to ping)
        if tr["partial_taken"]:
            new_sl = _trailing_sl(c15, direction, current_sl, price15)
            if new_sl is not None:
                r = broker.set_stop_loss(tid, new_sl)
                if r.get("done"):
                    log.append(f"{sym}: trail SL {current_sl:.5f} -> {new_sl:.5f}.")

    remaining = [t for t in trades if not t.get("_drop")]
    for t in remaining:
        t.pop("_drop", None)
    save(remaining)
    return log


if __name__ == "__main__":
    # quick logic self-test (no network)
    import random
    random.seed(1)
    base = dt.datetime(2026, 7, 1)
    def staircase(legs, start, up=0.0060, down=0.0030, j=0.0004):
        out = []; p = start; i = 0
        for _ in range(legs):
            for _ in range(5):
                p += up/5 + random.uniform(-j, j)
                out.append(Candle(base+dt.timedelta(hours=i), p-j, p+j, p-2*j, p)); i += 1
            for _ in range(4):
                p -= down/4 + random.uniform(-j, j)
                out.append(Candle(base+dt.timedelta(hours=i), p-j, p+j, p-2*j, p)); i += 1
        return out
    up = staircase(4, 1.1000)
    print("structure break (clean uptrend):", _structure_break(up, Direction.BULL), "(expect False)")
    lows = [s for s in detect_swings(up) if s.kind.value == "low"]
    broken = up + [Candle(up[-1].time+dt.timedelta(hours=1), 0, 0, 0, lows[-1].price - 0.0100)]
    print("structure break (close < last HL):", _structure_break(broken, Direction.BULL), "(expect True)")
    print("partial (price>=tp1):", _should_partial(1.1050, 1.1050, Direction.BULL, False), "(expect True)")
    print("maxhold 30h:", _should_maxhold(30, False), "(expect True)")
    c15 = staircase(3, 1.1000, j=0.0003)
    tr = _trailing_sl(c15, Direction.BULL, 1.0950, c15[-1].c)
    print("trailing SL:", f"{tr:.5f}" if tr else None)
    print("logic self-test done.")
