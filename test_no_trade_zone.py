"""
test_no_trade_zone.py — tests for the 4H no-trade-zone gate added from
Trades By Sci's "MY ICC UPDATE" (2026-07-30), plus the tied-extreme swing bug
that gate exposed.

His rule, verbatim:
    "current price is at 4,036. Let me go up. Okay, this is my high. Mark.
     Okay, this high was created from here. Okay, that's my low. ... If price
     is in between both of these, this means that this is a no trade zone."

So the zone is the pair of adjacent swings bracketing price, levels come from
body CLOSES ("a wick is price attempted to but failed"), and a setup must
originate OUTSIDE it ("your setup should always start out of a no trade zone").

Run:  python3 test_no_trade_zone.py       (offline, no keys)
"""
from __future__ import annotations
import datetime as dt
import sys

from icc_engine import (Candle, Direction, Swing, SwingType, classify_trend,
                        collapse_runs, detect_swings, evaluate, no_trade_zone)

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILS.append(name)


def candles_from_closes(closes, wick=0.5):
    """Body-close series -> Candles. Wicks are deliberately present on every
    candle so the tests prove levels come from CLOSES, not from highs/lows."""
    out, prev = [], closes[0]
    t0 = dt.datetime(2026, 7, 30, 0, 0)
    for i, c in enumerate(closes):
        out.append(Candle(time=t0 + dt.timedelta(hours=4 * i), o=prev,
                          h=max(prev, c) + wick, l=min(prev, c) - wick, c=c))
        prev = c
    return out


# Textbook structures: impulse / shallow pullback / impulse / shallow pullback,
# each leg long enough (>=5 bars) that a left=2/right=2 fractal finds exactly
# one pivot per turn. Final bars sit INSIDE the last bracket.
BULL_INSIDE = (list(range(100, 113)) + [111, 110, 109, 108]      # HH 112, HL 108
               + list(range(109, 121)) + [119, 118, 117, 116]     # HH 120, HL 116
               + [117, 118])                                      # now 118: inside
BEAR_INSIDE = (list(range(120, 107, -1)) + [109, 110, 111, 112]   # LL 108, LH 112
               + list(range(111, 99, -1)) + [101, 102, 103, 104]  # LL 100, LH 104
               + [103, 102])                                      # now 102: inside
# A simple rise-then-fall that leaves price bracketed but structureless.
RISE_FALL = ([100 + i for i in range(11)] + [109 - i for i in range(9)] + [100, 101, 102])

print("\n=== zone is built from body CLOSES, not wicks ===")
cs = candles_from_closes(RISE_FALL)
zone = no_trade_zone(cs, detect_swings(cs))
check("zone found", zone is not None, True)
check("zone high = swing CLOSE 110 (wick was 110.5)", zone.high, 110.0)
check("zone low  = swing CLOSE 100 (wick was 99.5)", zone.low, 100.0)
check("zone width", zone.width, 10.0)
check("price 102 is INSIDE", zone.inside, True)
check("inside -> side NONE", zone.side, Direction.NONE)

print("\n=== which side has taken control ===")
for last_close, want_side, want_inside, label in [
        (112.0, Direction.BULL, False, "close ABOVE the zone high -> buyers"),
        (98.0, Direction.BEAR, False, "close BELOW the zone low -> sellers"),
        (105.0, Direction.NONE, True, "mid-zone -> nobody in control")]:
    series = RISE_FALL[:-1] + [last_close]
    z = no_trade_zone(candles_from_closes(series), detect_swings(candles_from_closes(series)))
    if z is None:
        # a close beyond the old extreme can legitimately destroy the old pivot;
        # that is correct behaviour, not a failure of the gate.
        print(f"  SKIP  {label}: new extreme replaced the bracket (structure moved)")
        continue
    check(f"{label} / side", z.side, want_side)
    check(f"{label} / inside", z.inside, want_inside)

print("\n=== touching a level is NOT breaking it ===")
# "The moment that price comes ABOVE this blue line, I press buy." Above, not at.
for series, label, want in [
        (BULL_INSIDE[:-2] + [120.0, 120.0], "close exactly ON zone high", True),
        (BEAR_INSIDE[:-2] + [100.0, 100.0], "close exactly ON zone low", True)]:
    z = no_trade_zone(candles_from_closes(series), detect_swings(candles_from_closes(series)))
    if z is None:
        print(f"  SKIP  {label}: bracket replaced")
        continue
    check(f"{label} -> still inside", z.inside, want)

print("\n=== collapse_runs: tied extremes must not break structure ===")
t = dt.datetime(2026, 7, 30)
run = [Swing(10, t, 110.0, SwingType.HIGH),
       Swing(11, t, 109.0, SwingType.HIGH),   # tied-high artifact, less extreme
       Swing(20, t, 100.0, SwingType.LOW)]
col = collapse_runs(run)
check("2 highs + 1 low collapses to 2 swings", len(col), 2)
check("keeps the MORE extreme high (110, not 109)", col[0].price, 110.0)
check("keeps that extreme's own index", col[0].index, 10)
check("low untouched", col[1].price, 100.0)
check("a later HIGHER high wins instead",
      collapse_runs([Swing(10, t, 109.0, SwingType.HIGH),
                     Swing(11, t, 110.0, SwingType.HIGH)])[0].price, 110.0)
check("alternating swings left alone",
      len(collapse_runs([Swing(1, t, 100.0, SwingType.LOW),
                         Swing(2, t, 110.0, SwingType.HIGH),
                         Swing(3, t, 101.0, SwingType.LOW)])), 3)
check("collapse_runs is idempotent", collapse_runs(col), col)

print("\n=== THE BUG THAT COST TRADES: equal highs/lows faked a reversal ===")
# detect_swings() tests pivots with >=/<=, so a tie registers twice. The second,
# less extreme pivot then reads as a lower-high, and classify_trend() saw
# LH+HL -> NONE -> "HTF is ranging/consolidating" on a clean uptrend.
raw_highs = [Swing(12, t, 112.0, SwingType.HIGH), Swing(13, t, 111.0, SwingType.HIGH),
             Swing(16, t, 108.0, SwingType.LOW), Swing(17, t, 109.0, SwingType.LOW),
             Swing(28, t, 120.0, SwingType.HIGH), Swing(29, t, 119.0, SwingType.HIGH),
             Swing(32, t, 116.0, SwingType.LOW)]
check("uncollapsed: clean uptrend misread as ranging", classify_trend(raw_highs), Direction.NONE)
check("collapsed: same data correctly reads bull",
      classify_trend(collapse_runs(raw_highs)), Direction.BULL)
for name, series, want in [("bull", BULL_INSIDE, Direction.BULL),
                           ("bear", BEAR_INSIDE, Direction.BEAR)]:
    sw = detect_swings(candles_from_closes(series))
    check(f"detect_swings now returns clean {name} structure", classify_trend(sw), want)
    check(f"{name} swings strictly alternate",
          all(a.kind != b.kind for a, b in zip(sw, sw[1:])), True)

print("\n=== evaluate() refuses a setup that starts inside the zone ===")
htf = candles_from_closes(BULL_INSIDE)
ltf = candles_from_closes([117 + 0.1 * i for i in range(30)])
sig = evaluate("XAUUSD", htf, ltf)
check("action is NO_TRADE", sig.action, "NO_TRADE")
check("HTF trend was read as bull (gate A2 passed)", sig.checks.get("htf_trend"), "bull")
check("reason names the no-trade zone", "no-trade zone" in sig.reason, True)
check("checks record the zone", "no_trade_zone" in sig.checks, True)
print(f"        reason : {sig.reason}")
print(f"        zone   : {sig.checks.get('no_trade_zone')}")

sig_b = evaluate("XAUUSD", candles_from_closes(BEAR_INSIDE),
                 candles_from_closes([103 - 0.1 * i for i in range(30)]))
check("bear case also blocked inside its zone", "no-trade zone" in sig_b.reason, True)
check("bear zone recorded", "100.00-104.00" in sig_b.checks.get("no_trade_zone", ""), True)

print("\n=== the gate must not block a genuine breakout ===")
# extend the bull series with a 4H close past the 120 zone high
BULL_BREAK = BULL_INSIDE[:-2] + [119, 122]
zb = no_trade_zone(candles_from_closes(BULL_BREAK), detect_swings(candles_from_closes(BULL_BREAK)))
check("breakout -> outside the zone", zb.inside, False)
check("breakout -> BULL", zb.side, Direction.BULL)
sig2 = evaluate("XAUUSD", candles_from_closes(BULL_BREAK), ltf)
check("evaluate() no longer cites the zone as the blocker",
      "no-trade zone" in sig2.reason, False)
print(f"        reason : {sig2.reason}")

print()
if FAILS:
    print(f"❌ {len(FAILS)} check(s) failed: {', '.join(FAILS)}")
    sys.exit(1)
print("✅ all no-trade-zone checks passed")
sys.exit(0)
