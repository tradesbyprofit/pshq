"""
test_sizing.py — offline regression tests for risk-based position sizing.

Covers the two bugs that made a small account untradeable and a JPY account
under-risked:

  1. quote-currency conversion. P/L is paid in the QUOTE currency, so a stop
     distance on USD_JPY is denominated in yen. The old formula divided the
     dollar risk budget by a yen distance and never converted back, which
     under-risked JPY pairs by roughly 150x.
  2. lot rounding. Python's round() is banker's rounding, so round(0.5) == 0.
     Combined with `max(..., 0.01)` this submitted 0-unit orders on small
     balances, which OANDA rejects outright.

Also asserts the new behaviour: when the smallest legal order would risk more
than the budget, size_position() says so and the broker SKIPS the trade rather
than silently over- or under-risking.

Run:  python3 test_sizing.py        (no network, no API keys)
"""
from __future__ import annotations
import sys

import oanda_feed as of
from icc_engine import Signal, Direction

# Seed the JPY rate so these tests never touch the network.
of._QUOTE_CACHE["JPY"] = 1.0 / 150.0

FAILS = []


def check(name, got, want, tol=1e-9):
    ok = (abs(got - want) <= tol) if isinstance(want, float) else (got == want)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILS.append(name)


def approx(name, got, want, tol):
    ok = abs(got - want) <= tol
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got:.6f}, want ~{want} (+-{tol})")
    if not ok:
        FAILS.append(name)


def sig(symbol, direction, entry, stop, target=None):
    import datetime as dt
    return Signal(action="SETUP", symbol=symbol, direction=direction, reason="test",
                  entry=entry, stop=stop,
                  target=target if target is not None else entry + (entry - stop),
                  rr=1.0, when=dt.datetime(2026, 1, 5, 12, 0))


print("\n=== lot rounding (banker's rounding bug) ===")
check("round_half_away(0.5)", of._round_half_away(0.5), 1)
check("round_half_away(1.5)", of._round_half_away(1.5), 2)
check("round_half_away(2.5)", of._round_half_away(2.5), 3)
check("round_half_away(-0.5)", of._round_half_away(-0.5), -1)
check("round_half_away(-2.5)", of._round_half_away(-2.5), -3)
check("legal_units(EUR_USD, -0.5)", of.legal_units("EUR_USD", -0.5), -1.0)
check("legal_units(EUR_USD, 4.2)", of.legal_units("EUR_USD", 4.2), 4.0)
check("fmt_units(EUR_USD, -0.5)", of.fmt_units("EUR_USD", -0.5), "-1")
check("fmt_units(XAU_USD, 0.346)", of.fmt_units("XAU_USD", 0.346), "0.35")
check("fmt_units(BTC_USD, 0.0004)", of.fmt_units("BTC_USD", 0.0004), "0.00")
check("python round(0.5) is 0 (the trap)", int(round(0.5)), 0)

print("\n=== is_forex must NOT swallow metals/crypto ===")
for inst, want in [("EUR_USD", True), ("GBP_JPY", True), ("USD_JPY", True),
                   ("XAU_USD", False), ("XAG_USD", False), ("BTC_USD", False),
                   ("ETH_USD", False)]:
    check(f"is_forex({inst})", of.is_forex(inst), want)
check("price_precision(EUR_USD)", of.price_precision("EUR_USD"), 5)
check("price_precision(USD_JPY)", of.price_precision("USD_JPY"), 3)
check("price_precision(XAU_USD)", of.price_precision("XAU_USD"), 3)
check("price_precision(BTC_USD)", of.price_precision("BTC_USD"), 1)

print("\n=== quote-currency conversion ===")
check("quote_to_usd(EUR_USD)", of.quote_to_usd("EUR_USD"), 1.0)
check("quote_to_usd(XAU_USD)", of.quote_to_usd("XAU_USD"), 1.0)
approx("quote_to_usd(USD_JPY)", of.quote_to_usd("USD_JPY"), 1 / 150.0, 1e-12)
approx("quote_to_usd(GBP_JPY)", of.quote_to_usd("GBP_JPY"), 1 / 150.0, 1e-12)

print("\n=== sizing on a normal account ($10,000, 1% risk) ===")
# EURUSD: 20-pip stop -> $100 budget / ($0.0020 * 1.0) = 50,000 units
s = of.size_position("EUR_USD", 10_000, 0.01, 1.0850, 1.0830)
check("EUR_USD units", s["units"], 50000.0)
approx("EUR_USD risk is 1% of balance", s["risk_usd"], 100.0, 0.01)
approx("EUR_USD risk_pct", s["risk_pct"], 1.0, 1e-6)

# USDJPY: 50-pip stop = 0.50 yen -> $100 budget / (0.50 * 1/150) = 30,000 units
s = of.size_position("USD_JPY", 10_000, 0.01, 150.00, 149.50)
check("USD_JPY units", s["units"], 30000.0)
approx("USD_JPY risk is 1% of balance", s["risk_usd"], 100.0, 0.01)
# what the OLD formula produced, for contrast:
old_units = max(10_000 * 0.01 / 0.50, 0.01)
old_risk = old_units * 0.50 * (1 / 150.0)
approx("OLD formula under-risked USD_JPY to", old_risk, 0.6667, 0.001)
print(f"        (old: {int(old_units)} units risking ${old_risk:.2f} = "
      f"{old_risk / 10_000 * 100:.4f}% instead of 1%)")

# GBPJPY: 70-pip stop = 0.70 yen
s = of.size_position("GBP_JPY", 10_000, 0.01, 190.00, 189.30)
approx("GBP_JPY risk is 1% of balance", s["risk_usd"], 100.0, 0.5)

# gold: $12 stop, fractional units allowed
s = of.size_position("XAU_USD", 10_000, 0.01, 2000.0, 1988.0)
approx("XAU_USD risk is 1% of balance", s["risk_usd"], 100.0, 1.0)
check("XAU_USD is not too_small", s["too_small"], False)

print("\n=== the $1 account (why the goal is untradeable, not just unlikely) ===")
s = of.size_position("EUR_USD", 1.0, 0.01, 1.0850, 1.0830)
check("EUR_USD $1 units", s["units"], 5.0)
check("EUR_USD $1 not too_small", s["too_small"], False)

# Gold on $1: 0.01 units * $12 stop = $0.12 = 12% of the account, not 1%.
s = of.size_position("XAU_USD", 1.0, 0.01, 2000.0, 1988.0)
check("XAU_USD $1 too_small", s["too_small"], True)
approx("XAU_USD $1 min order would risk", s["risk_pct"], 12.0, 0.01)

# BTC on $1: 0.01 units * $900 stop = $9 = 900% of the account.
s = of.size_position("BTC_USD", 1.0, 0.01, 60_000.0, 59_100.0)
check("BTC_USD $1 too_small", s["too_small"], True)
approx("BTC_USD $1 min order would risk", s["risk_pct"], 900.0, 0.01)

print("\n=== minimum balance that clears a 1% risk budget ===")
for inst, entry, stop, want in [
    ("EUR_USD", 1.0850, 1.0830, 0.20),      # 1 unit * 0.0020 / 0.01
    ("XAU_USD", 2000.0, 1988.0, 12.0),       # 0.01 unit * 12.00 / 0.01
    ("BTC_USD", 60_000.0, 59_100.0, 900.0),  # 0.01 unit * 900.00 / 0.01
]:
    lo = 0.01
    while of.size_position(inst, lo, 0.01, entry, stop)["too_small"] and lo < 1_000_000:
        lo *= 1.02
    approx(f"{inst} min balance", lo, want, want * 0.03)

print("\n=== broker skips an untradeable size instead of firing a bad order ===")


class _FakeBroker(of.OANDAPaperBroker):
    """Bypass the env-var/credential check so we can test the skip path."""
    def __init__(self, balance):
        self.acct = "000-000-0000000-000"
        self.risk = 0.01
        self._bal = balance

    def _balance(self):
        return self._bal


b = _FakeBroker(1.0)
res = b.execute(sig("XAUUSD", Direction.BULL, 2000.0, 1988.0))
check("gold on $1 is not executed", res.get("executed"), False)
check("gold on $1 is skipped TOO_SMALL", res.get("skipped"), "TOO_SMALL")
print(f"        reason: {res.get('reason')}")

res = b.execute(sig("BTCUSD", Direction.BEAR, 60_000.0, 60_900.0))
check("btc on $1 is not executed", res.get("executed"), False)
check("btc on $1 is skipped TOO_SMALL", res.get("skipped"), "TOO_SMALL")

res = b.execute(sig("EURUSD", Direction.BULL, 1.0850, 1.0830), dry_run=True)
check("eurusd on $1 is sized", res.get("units"), "5")
check("eurusd on $1 risk_pct", res.get("risk_pct"), "1.000%")

print("\n=== scanner risk config + manual-entry sizing hints ===")
import scanner

check("RISK_PER_TRADE is Sci's stated 10%", scanner.RISK_PER_TRADE, 0.10)
check("WATCH is gold only", scanner.WATCH, ["XAUUSD"])
check("XAUUSD is ALERT_ONLY (nothing auto-executes)", "XAUUSD" in scanner.ALERT_ONLY, True)
check("markup TF is 4H", scanner.HTF, "4H")
check("entry TF is 1H", scanner.LTF, "1H")
check("15M is gone from the scanner", "15M" in (scanner.HTF, scanner.LTF), False)

g = sig("XAUUSD", Direction.BULL, 4036.0, 4011.0, 4086.0)   # $25 4H stop
h10 = scanner.position_size_hint(g, 10_000.0, 0.10)
check("$10k at 10% sizes 40 units", "40.00 units XAU_USD" in h10, True)
check("$10k at 10% risks $1,000", "risks $1,000.00 = 10.0%" in h10, True)
h1 = scanner.position_size_hint(g, 10_000.0, 0.01)
check("$10k at 1% sizes 4 units (10x smaller)", "4.00 units XAU_USD" in h1, True)
check("10% risk is exactly 10x the 1% size", 40.0 / 4.0, 10.0)

sell = sig("XAUUSD", Direction.BEAR, 4036.0, 4061.0, 3986.0)
hs = scanner.position_size_hint(sell, 500.0, 0.10)
check("bear hint says SELL", "SELL" in hs, True)
check("bear hint does NOT say BUY", "BUY" in hs, False)
check("bull hint says BUY", "BUY" in h10 and "SELL" not in h10, True)
# direction must come from the signal, not the sign of size_position()'s magnitude
check("bear hint still sizes 2 units of a $500 acct at 10%", "2.00 units XAU_USD" in hs, True)
check("unsizeable balance is reported, not silently zero",
      "CANNOT SIZE" in scanner.position_size_hint(g, 1.0, 0.10), True)
no_setup = Signal(action="NO_TRADE", symbol="XAUUSD", direction=Direction.NONE,
                  reason="x", entry=None, stop=None, target=None, rr=None, when=None)
check("non-setup signals produce no hint",
      scanner.position_size_hint(no_setup, 10_000.0, 0.10), "")

lad = scanner.risk_ladder_notice(0.10)
check("ladder notice states the setting", "10.0%" in lad, True)
check("ladder notice shows 4-loss survival (66%)", "4 -> 66%" in lad, True)
check("1% ladder shows 4-loss survival (96%)",
      "4 -> 96%" in scanner.risk_ladder_notice(0.01), True)

print()
if FAILS:
    print(f"❌ {len(FAILS)} check(s) failed: {', '.join(FAILS)}")
    sys.exit(1)
print("✅ all sizing checks passed")
sys.exit(0)

