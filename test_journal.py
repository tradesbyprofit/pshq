"""
test_journal.py — tests for journal.py, the alert-vs-actual record.

The R arithmetic is checked against hand-computed values on gold with a $25 4H
stop, so a sign flip or a quote-concurrency mistake cannot slip through:
    bull  entry 4000, stop 3975, exit 4050  ->  +50 / 25 = +2.00R
    bear  entry 4000, stop 4025, exit 3950  ->  +50 / 25 = +2.00R
    bear  entry 4000, stop 4025, exit 4025  ->  -25 / 25 = -1.00R

Run:  python3 test_journal.py       (offline, no keys, temp files only)
"""
from __future__ import annotations
import datetime as dt
import os
import sys
import tempfile

import journal
from icc_engine import Direction, Signal

FAILS = []


def check(name, got, want):
    ok = (abs(got - want) < 1e-9) if isinstance(want, float) and isinstance(got, float) else got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILS.append(name)


def approx(name, got, want, tol=1e-6):
    ok = got is not None and abs(got - want) <= tol
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got!r}, want ~{want}")
    if not ok:
        FAILS.append(name)


def raises(name, exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        print(f"  PASS  {name}: raised {type(e).__name__}")
        return
    except Exception as e:
        print(f"  FAIL  {name}: raised {type(e).__name__}, wanted {exc.__name__}")
        FAILS.append(name)
        return
    print(f"  FAIL  {name}: did not raise {exc.__name__}")
    FAILS.append(name)


def sig(symbol="XAUUSD", direction=Direction.BULL, entry=4000.0, stop=3975.0,
        target=4050.0, rr=2.0):
    return Signal(action="SETUP", symbol=symbol, direction=direction, reason="test setup",
                  entry=entry, stop=stop, target=target, rr=rr,
                  when=dt.datetime(2026, 10, 8, 12, 0))


tmp = tempfile.mkdtemp()
J = os.path.join(tmp, "journal.jsonl")

print("\n=== alert logging + ids ===")
a1 = journal.log_alert(sig(), risk_pct=10.0, balance=10_000.0,
                       units=40.0, risk_usd=1_000.0, path=J)
a2 = journal.log_alert(sig(direction=Direction.BEAR, entry=4000.0, stop=4025.0,
                           target=3950.0), risk_pct=10.0, balance=10_000.0,
                       units=40.0, risk_usd=1_000.0, path=J)
check("first id", a1, "A0001")
check("second id", a2, "A0002")
check("journal has 2 events", len(journal.load(J)), 2)
check("method tag recorded", journal.load(J)[0]["method"], journal.METHOD_TAG)
check("risk % recorded", journal.load(J)[0]["risk_pct"], 10.0)

print("\n=== index / pending / resolve_id ===")
idx = journal.index(path=J)
check("indexed both alerts", sorted(idx), ["A0001", "A0002"])
check("both are pending", [p["id"] for p in journal.pending(path=J)], ["A0001", "A0002"])
check("--last resolves to newest pending", journal.resolve_id("last", J), "A0002")
check("explicit id passes through", journal.resolve_id("A0001", J), "A0001")
raises("unknown id raises KeyError", KeyError, journal.resolve_id, "A9999", J)

print("\n=== fills default to the levels the bot gave ===")
f1 = journal.log_fill(a1, price=4000.0, units=40.0, path=J)
check("stop inherited from the alert", f1["stop"], 3975.0)
check("target inherited from the alert", f1["target"], 4050.0)
check("pending drops to 1", len(journal.pending(path=J)), 1)
check("--last now resolves to A0002", journal.resolve_id("last", J), "A0002")
check("open positions shows A0001", [o["id"] for o in journal.open_positions(path=J)], ["A0001"])
raises("double fill raises ValueError", ValueError, journal.log_fill, a1, 4001.0, 40.0, path=J)
raises("exit before fill raises KeyError", KeyError, journal.log_exit, a2, 3990.0, path=J)

print("\n=== skip ===")
journal.log_skip(a2, reason="Sunday gap, no NY volume", path=J)
check("skipped records the reason", journal.skipped(path=J)[0]["reason"],
      "Sunday gap, no NY volume")
check("nothing pending after a fill and a skip", journal.pending(path=J), [])
raises("--last with nothing pending raises KeyError", KeyError, journal.resolve_id, "last", J)
raises("skipping a filled alert raises ValueError", ValueError, journal.log_skip, a1, path=J)

print("\n=== R arithmetic, hand-verified ===")
journal.log_exit(a1, price=4050.0, reason="tp", path=J)     # bull 4000->4050, $25 risk
tr = journal.closed_trades(path=J)
check("one closed trade", len(tr), 1)
t = tr[0]
approx("bull winner = +2.00R", t["r"], 2.0)
approx("risk = 40u x $25 = $1,000", t["risk_usd"], 1_000.0)
approx("pnl = +2R x $1,000 = $2,000", t["pnl_usd"], 2_000.0)
approx("no slippage (filled at the alert price)", t["slippage_r"], 0.0)
check("exit reason recorded", t["exit_reason"], "tp")
check("size ratio 1.0 (took the advised lot)", t["size_ratio"], 1.0)
check("a winner is not a discipline failure", t["stop_honoured"], True)
check("winner is not counted as a loss", t["is_loss"], False)
# a bad reason must be rejected on an alert that actually has a fill
Jbad = os.path.join(tmp, "badreason.jsonl")
z = journal.log_alert(sig(), risk_pct=10.0, balance=10_000.0, units=40.0,
                      risk_usd=1_000.0, path=Jbad)
journal.log_fill(z, price=4000.0, units=40.0, path=Jbad)
raises("bad exit reason raises ValueError", ValueError,
       journal.log_exit, z, 4010.0, "yolo", "", Jbad)
raises("unknown alert id raises KeyError", KeyError,
       journal.log_exit, "A9999", 1.0, "manual", "", J)

print("\n=== bear direction must not be sign-flipped ===")
J2 = os.path.join(tmp, "bear.jsonl")
b = journal.log_alert(sig(direction=Direction.BEAR, entry=4000.0, stop=4025.0,
                          target=3950.0), risk_pct=10.0, balance=10_000.0,
                      units=40.0, risk_usd=1_000.0, path=J2)
journal.log_fill(b, price=4000.0, units=40.0, path=J2)
journal.log_exit(b, price=3950.0, reason="tp", path=J2)
tb = journal.closed_trades(path=J2)[0]
approx("bear winner = +2.00R (not -2.00R)", tb["r"], 2.0)
approx("bear pnl positive", tb["pnl_usd"], 2_000.0)

J3 = os.path.join(tmp, "bearloss.jsonl")
b2 = journal.log_alert(sig(direction=Direction.BEAR, entry=4000.0, stop=4025.0,
                           target=3950.0), risk_pct=10.0, balance=10_000.0,
                       units=40.0, risk_usd=1_000.0, path=J3)
journal.log_fill(b2, price=4000.0, units=40.0, path=J3)
journal.log_exit(b2, price=4025.0, reason="sl", path=J3)
tb2 = journal.closed_trades(path=J3)[0]
approx("bear stopped out = -1.00R", tb2["r"], -1.0)
approx("bear loss = -$1,000", tb2["pnl_usd"], -1_000.0)
check("sl exit counts as stop honoured", tb2["stop_honoured"], True)

print("\n=== slippage: filling worse than the alert costs R ===")
J4 = os.path.join(tmp, "slip.jsonl")
c = journal.log_alert(sig(entry=4000.0, stop=3975.0), risk_pct=10.0, balance=10_000.0,
                      units=40.0, risk_usd=1_000.0, path=J4)
journal.log_fill(c, price=4005.0, units=40.0, path=J4)      # chased 5 dollars higher
journal.log_exit(c, price=4050.0, reason="tp", path=J4)
tc = journal.closed_trades(path=J4)[0]
approx("chasing +$5 on a $25 stop costs -0.20R", tc["slippage_r"], -0.2)
# R is measured against the risk you ACTUALLY took: fill 4005 / stop 3975 = $30,
# so exiting at 4050 is +45/30 = +1.50R, not the +2.00R the alert promised.
# Chasing widened the stop and quietly cost half an R on a WINNER.
approx("chasing cut the winner from +2.00R to +1.50R", tc["r"], 1.5)
approx("dollar pnl reflects the wider risk", tc["pnl_usd"], 45.0 * 40.0)

print("\n=== oversizing is recorded, not hidden ===")
J5 = os.path.join(tmp, "size.jsonl")
d = journal.log_alert(sig(), risk_pct=10.0, balance=10_000.0,
                      units=40.0, risk_usd=1_000.0, path=J5)
journal.log_fill(d, price=4000.0, units=120.0, path=J5)     # 3x the advised lot
journal.log_exit(d, price=3975.0, reason="sl", path=J5)
td = journal.closed_trades(path=J5)[0]
check("size ratio flags 3x", td["size_ratio"], 3.0)
approx("risk scales with the lot: $3,000", td["risk_usd"], 3_000.0)
approx("R is still -1.00 (R is size-independent)", td["r"], -1.0)
approx("but the dollar loss tripled", td["pnl_usd"], -3_000.0)

print("\n=== stats_r: expectancy across a mixed record ===")
J6 = os.path.join(tmp, "mixed.jsonl")
# 2 winners at +2R, 1 loser at -1R  ->  66.7% WR, expectancy +1.0R, PF 4.0
for i, (dr, entry, stop, target, exit_p, reason) in enumerate([
        (Direction.BULL, 4000.0, 3975.0, 4050.0, 4050.0, "tp"),
        (Direction.BEAR, 4000.0, 4025.0, 3950.0, 3950.0, "tp"),
        (Direction.BULL, 4000.0, 3975.0, 4050.0, 3975.0, "sl")]):
    aid = journal.log_alert(sig(direction=dr, entry=entry, stop=stop, target=target),
                            risk_pct=10.0, balance=10_000.0, units=40.0,
                            risk_usd=1_000.0, path=J6)
    journal.log_fill(aid, price=entry, units=40.0, path=J6)
    journal.log_exit(aid, price=exit_p, reason=reason, path=J6)
s = journal.stats_r(journal.closed_trades(path=J6))
check("n", s["n"], 3)
check("wins", s["wins"], 2)
check("losses", s["losses"], 1)
approx("win rate 66.7%", s["win_rate"], 200 / 3, 1e-9)
approx("avg win +2.00R", s["avg_win_r"], 2.0)
approx("avg loss -1.00R", s["avg_loss_r"], 1.0)
approx("expectancy = (2*2 - 1*1)/3 = +1.00R", s["expectancy_r"], 1.0)
approx("profit factor = 4/1 = 4.00", s["profit_factor"], 4.0)
approx("total = +3.00R", s["total_r"], 3.0)
approx("total pnl = +$3,000", s["total_pnl_usd"], 3_000.0)
check("the single loser exited at its stop -> 100% honoured", s["stop_honoured_pct"], 100.0)
check("all sized as advised", s["sized_as_advised_pct"], 100.0)
check("stats_r on nothing is None", journal.stats_r([]), None)

print("\n=== robustness: corrupt lines are skipped, not fatal ===")
J7 = os.path.join(tmp, "corrupt.jsonl")
journal.log_alert(sig(), risk_pct=10.0, balance=10_000.0, units=40.0,
                  risk_usd=1_000.0, path=J7)
with open(J7, "a") as f:
    f.write("{not json at all\n")
    f.write("\n")
check("good event survives the corrupt one", len(journal.load(J7)), 1)

print("\n=== empty journal ===")
check("load on a missing file is []", journal.load(os.path.join(tmp, "nope.jsonl")), [])
check("stats_r on an empty journal is None", journal.stats_r([]), None)
check("closed_trades on empty is []", journal.closed_trades(path=os.path.join(tmp, "nope.jsonl")), [])

print("\n=== slippage sign convention: NEGATIVE always means a cost ===")
# Selling higher than the alert is BETTER on a short; selling lower is WORSE.
# Buying lower is BETTER on a long; buying higher is WORSE. All four must agree
# on one convention or the discipline report tells you the opposite of the truth.
J9 = os.path.join(tmp, "slipsign.jsonl")
cases = [
    # (direction, alert entry, fill, expected slippage R, why)
    (Direction.BEAR, 4000.0, 4005.0, +0.20, "short filled $5 HIGHER = better price"),
    (Direction.BEAR, 4000.0, 3995.0, -0.20, "short filled $5 LOWER  = worse price"),
    (Direction.BULL, 4000.0, 3995.0, +0.20, "long  filled $5 LOWER  = better price"),
    (Direction.BULL, 4000.0, 4005.0, -0.20, "long  filled $5 HIGHER = worse price"),
]
for dr, ae, fp, want_r, why in cases:
    aid = journal.log_alert(sig(direction=dr, entry=ae, stop=ae - 25.0 * (1 if dr == Direction.BULL else -1),
                                target=ae), risk_pct=10.0, balance=10_000.0,
                            units=40.0, risk_usd=1_000.0, path=J9)
    journal.log_fill(aid, price=fp, units=40.0, path=J9)
    journal.log_exit(aid, price=fp, reason="manual", path=J9)   # flat exit isolates slippage
    got = journal.closed_trades(path=J9)[-1]["slippage_r"]
    approx(f"{why} -> {want_r:+.2f}R", got, want_r)

s9 = journal.stats_r(journal.closed_trades(path=J9))
approx("two better fills and two worse fills net to 0.00R", s9["avg_slippage_r"], 0.0)

print("\n=== compound_reality can consume a journal edge ===")
import compound_reality as cr
# edge_from_journal refuses anything under 10 trades, so build a real sample:
# 8 winners at +2R and 4 losers at -1R -> 66.7% WR, expectancy +1.0R, PF 4.0
J8 = os.path.join(tmp, "sample12.jsonl")
for dr, entry, stop, target, exit_p, reason in (
        [(Direction.BULL, 4000.0, 3975.0, 4050.0, 4050.0, "tp")] * 4
      + [(Direction.BEAR, 4000.0, 4025.0, 3950.0, 3950.0, "tp")] * 4
      + [(Direction.BULL, 4000.0, 3975.0, 4050.0, 3975.0, "sl")] * 2
      + [(Direction.BEAR, 4000.0, 4025.0, 3950.0, 4025.0, "sl")] * 2):
    aid = journal.log_alert(sig(direction=dr, entry=entry, stop=stop, target=target),
                            risk_pct=10.0, balance=10_000.0, units=40.0,
                            risk_usd=1_000.0, path=J8)
    journal.log_fill(aid, price=entry, units=40.0, path=J8)
    journal.log_exit(aid, price=exit_p, reason=reason, path=J8)
s12 = journal.stats_r(journal.closed_trades(path=J8))
check("12-trade sample built", s12["n"], 12)
approx("sample expectancy +1.00R", s12["expectancy_r"], 1.0)

old_default = journal.JOURNAL_FILE
journal.JOURNAL_FILE = J8          # edge_from_journal reads the default path
try:
    e = cr.edge_from_journal()
    check("edge built from the journal", e is not None, True)
    approx("journal win rate -> Edge", e.win_rate, 2 / 3, 1e-9)
    approx("journal avg win R -> Edge", e.avg_win_r, 2.0)
    approx("journal avg loss R -> Edge", e.avg_loss_r, 1.0)
    check("cost_r is 0 (measured R already includes real costs)", e.cost_r, 0.0)
    approx("Edge expectancy reproduces the measured +1.00R", e.expectancy_r, 1.0)
finally:
    journal.JOURNAL_FILE = old_default

journal.JOURNAL_FILE = os.path.join(tmp, "small.jsonl")
e_small = cr.edge_from_journal()
check("<10 trades refuses to build an edge", e_small, None)

print()
if FAILS:
    print(f"❌ {len(FAILS)} check(s) failed: {', '.join(FAILS)}")
    sys.exit(1)
print("✅ all journal checks passed")
sys.exit(0)
