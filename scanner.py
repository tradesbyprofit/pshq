"""
scanner.py — Live ICC monitor. Watches XAUUSD & BTCUSD, runs the engine on a
schedule, and ONLY surfaces a trade when a full ICC setup forms. Enforces the
"1 trade/week (max 2), never chase" rule. Logs everything.

This is the "connect to charts & monitor" layer. The actual data feed and the
order/notify routing are PLUGGABLE — see DataFeed and Notifier below.

RUN:   python3 scanner.py            (demo mode uses synthetic data so you can
                                       watch the state machine work end-to-end)
NOT ADVICE. Demo/simulation only until you wire a real feed + paper-trade it.
"""
from __future__ import annotations
import datetime as dt, json, time, os
from dataclasses import dataclass, asdict
from typing import List, Protocol
from icc_engine import Candle, evaluate, Signal, Direction
import trade_manager

try:
    import journal                    # alert-vs-actual trade journal
except Exception:
    journal = None

# ---------------------------------------------------------------------------
# GOLD ONLY. Operator decision 2026-10-08: follow Sci's method, but trade it on
# XAUUSD exclusively even when he shows NASDAQ / BTC / forex examples. Gold is
# the one market he trades most and the one with the cleanest 4H structure.
# To re-add a market: append it here and make sure feeds.py/oanda_feed.py can
# resolve it. Nothing else needs to change.
# ---------------------------------------------------------------------------
WATCH = ["XAUUSD"]

# OANDA *practice* accounts are forex-only (68 pairs, no metals), so XAUUSD
# cannot be paper-executed there yet. Until Metals is enabled on the account or
# you point the bot at a broker that offers spot gold, it stays alert-only.
# Remove "XAUUSD" from this set the moment gold becomes executable.
ALERT_ONLY = {"XAUUSD"}

# MY ICC UPDATE (Trades By Sci, 2026-07-30): markup on 4H, entries on 1H.
# The 15-minute is abandoned entirely — "sometimes the volume is a little bit
# excessive throughout New York session, breaks structure a lot on the
# 15-minute time frame. So a lot of the noise is cleared out by trading on the
# 4 hour and 1 hour time frame." Two timeframes only: "You only need two time
# frames... Don't over complicate it at all."
HTF = "4H"; LTF = "1H"

# ---------------------------------------------------------------------------
# RISK PER TRADE — Sci's stated default, chosen deliberately by the operator
# 2026-10-08 ("trust him"). His 2026-07-30 update pairs this with WIDE 4H
# structural stops and the rule "if you can't put whatever stop-loss you want,
# lower your lot size" — i.e. the stop goes where structure says and the lot
# absorbs the risk. size_position() implements exactly that.
#
# Override at runtime with  --risk <percent>  (e.g. --risk 1).
# NOTE: XAUUSD is in ALERT_ONLY, so with a gold-only watchlist nothing is
# auto-executed at this setting — alerts carry the computed size for manual
# entry instead. This number only goes live if execution is enabled.
# ---------------------------------------------------------------------------
RISK_PER_TRADE = 0.10
DEFAULT_BALANCE = 10_000.0     # used for sizing hints when no live balance is reachable

STATE_FILE = "scanner_state.json"

try:
    import kalshi_feed                 # optional Kalshi crowd-confluence overlay (BTC/gold)
except Exception:
    kalshi_feed = None


def _kalshi_line(sym: str, price: float) -> str:
    """One-line Kalshi crowd lean for an alert message (or honest 'no signal')."""
    if kalshi_feed is None:
        return "Kalshi: (module unavailable)"
    try:
        c = kalshi_feed.confluence(sym, price)
        if c.get("median") is None or c.get("lean") == "n/a":
            return f"Kalshi: no clean signal ({c.get('note')})"
        return (f"Kalshi crowd lean: {c['lean'].upper()} "
                f"(median {c['median']:.2f} vs spot {price:.2f}, "
                f"{c.get('median_vs_spot_pct','?')}% by {str(c.get('resolves',''))[:10]})")
    except Exception as e:
        return f"Kalshi: (unavailable: {str(e)[:30]})"

# ---- 1. trade governor: 1/week default, 2 max --------------------------------
@dataclass
class Governor:
    max_per_week: int = 2
    target_per_week: int = 1

    def _week_key(self, when: dt.datetime) -> str:
        iso = when.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    def can_trade(self, taken_this_week: int) -> bool:
        # stop hard at the weekly ceiling; soft-nudge once target met
        return taken_this_week < self.max_per_week

    def should_keep_trading(self, taken_this_week: int) -> bool:
        # "sometimes we don't trade all week" — once we've hit target, only take
        # A+ setups; here we simply stop at target unless you raise the cap.
        return taken_this_week < self.target_per_week


def _journal_alert(sig, balance: float, risk: float) -> str:
    """Record a fired setup in journal.py so a hand-placed trade can later be
    matched against what the bot actually said. Never raises — a journaling
    failure must not cost you the alert."""
    if journal is None:
        return "(journal unavailable)"
    try:
        sz = position_size(sig, balance, risk) or {}
        aid = journal.log_alert(
            sig, risk_pct=risk * 100.0, balance=balance,
            units=(abs(sz["units"]) if not sz.get("too_small") and sz.get("units") else None),
            risk_usd=sz.get("risk_usd"), too_small=sz.get("reason"))
        return aid
    except Exception as e:
        return f"(journal error: {str(e)[:40]})"


# ---- 1b. position sizing for MANUAL entry (alert-only gold) ------------------
def position_size(sig, balance: float, risk_fraction: float):
    """The sizing dict for a signal, or None if it cannot be computed.

    Split out from position_size_hint() so scanner.py can both format the alert
    AND write the numbers into the journal.
    """
    if sig.action != "SETUP" or sig.entry is None or sig.stop is None:
        return None
    try:
        from oanda_feed import resolve_instrument, size_position
    except Exception:
        return None
    try:
        return size_position(resolve_instrument(sig.symbol), balance,
                             risk_fraction, sig.entry, sig.stop)
    except Exception:
        return None


def position_size_hint(sig, balance: float, risk_fraction: float) -> str:
    """One line telling you exactly what to enter by hand.

    Gold is alert-only, so the bot does not place the order — which means the
    alert has to carry the lot size or it is not actionable. Uses the same
    size_position() the paper broker uses, so the number you type in matches
    what the bot would have sent. Returns '' if it cannot be computed.
    """
    if sig.action != "SETUP" or sig.entry is None or sig.stop is None:
        return ""
    try:
        from oanda_feed import resolve_instrument
    except Exception as e:
        return f"(sizing unavailable: {str(e)[:40]})"
    s = position_size(sig, balance, risk_fraction)
    if s is None:
        return "(sizing unavailable)"
    if s.get("too_small"):
        return (f"⚠️ CANNOT SIZE: {s.get('reason')} — widen the balance or the "
                f"risk %, or skip this setup")
    # size_position() returns an unsigned magnitude; direction comes from the
    # signal, NOT from the sign of units (that sign is applied by the broker).
    side = "BUY" if sig.direction == Direction.BULL else "SELL"
    return (f"📐 {side} {abs(s['units']):.2f} units {resolve_instrument(sig.symbol)}  |  "
            f"risks ${s['risk_usd']:,.2f} = {s['risk_pct']:.1f}% of "
            f"${balance:,.2f}  |  stop width {abs(sig.entry - sig.stop):.2f}")


def risk_ladder_notice(risk_fraction: float) -> str:
    """Print what the chosen risk % actually does over a normal losing streak.

    Not a recommendation — just the arithmetic, so the setting is an informed
    one rather than a number in a config file.
    """
    r = risk_fraction
    rows = "  ".join(f"{n} -> {(1 - r) ** n * 100:.0f}%" for n in (2, 4, 6, 8))
    return (f"risk/trade = {r * 100:.1f}% (--risk to change). "
            f"Account left after N straight losses: {rows}")



# ---- 2. pluggable data feed --------------------------------------------------
class DataFeed(Protocol):
    def candles(self, symbol: str, timeframe: str, limit: int = 120) -> List[Candle]: ...


class DemoFeed:
    """Synthetic feed so you can watch the scanner loop without any keys.
    Replace with TradingView/tvDatafeed, your broker's API, or CCXT (crypto)."""
    def __init__(self):
        import random; self.r = random.Random(42); self._t = {}
    def candles(self, symbol, timeframe, limit=120):
        step = {"1H":3600,"4H":14400,"15M":900,"5M":300}.get(timeframe,3600)
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).replace(minute=0,second=0,microsecond=0)
        base = 2000.0 if "XAU" in symbol else 60000.0
        out=[]; p=base
        key=(symbol,timeframe)
        # gentle uptrend then pullback then reclaim to occasionally form a setup
        for i in range(limit):
            t = now - dt.timedelta(seconds=step*(limit-i))
            drift = 0.4 if i < limit*0.7 else (-0.6 if i < limit*0.9 else 1.2)
            p += drift + self.r.uniform(-1,1)
            o = p - self.r.uniform(0,1); c = p
            out.append(Candle(t, o, max(o,c)+self.r.uniform(0,1),
                              min(o,c)-self.r.uniform(0,1), c))
        return out


# ---- 3. pluggable notifier (TV webhook / Telegram / broker stub) -------------
class Notifier(Protocol):
    def send(self, sig: Signal): ...

class ConsoleNotifier:
    def send(self, sig: Signal):
        tag = "🟢 SETUP" if sig.action=="SETUP" else "⚪ no-trade"
        print(f"[{sig.when:%Y-%m-%d %H:%M} UTC] {tag} {sig.symbol} "
              f"{sig.direction.value} — {sig.reason}")
        if sig.action=="SETUP":
            print(f"     entry={sig.entry} stop={sig.stop} target={sig.target} R:R={sig.rr}")
    def send_text(self, text: str):
        print(f"  [lifecycle] {text}")


# ---- 4. persistence (so the weekly counter survives restarts) ---------------
def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {"taken": {}}   # week_key -> count

def save_state(st):
    json.dump(st, open(STATE_FILE,"w"), indent=2)


# ---- 5. the scan -------------------------------------------------------------
def scan_once(feed: DataFeed, notifier: Notifier, gov: Governor, broker=None,
              risk: float = RISK_PER_TRADE, balance: float = None):
    state = load_state()
    # a live balance beats the configured default for manual-entry sizing hints
    if balance is None and broker is not None:
        try:
            balance = broker._balance()
        except Exception:
            balance = None
    if balance is None:
        balance = DEFAULT_BALANCE
    wk = gov._week_key(dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    taken = state["taken"].get(wk, 0)
    print(f"\n=== SCAN @ {dt.datetime.now(dt.timezone.utc).replace(tzinfo=None):%H:%M:%S} UTC | week {wk}: "
          f"{taken}/{gov.target_per_week} target ({gov.max_per_week} hard cap) ===")
    # manage already-open trades FIRST (partials, breakeven, trail, structure exit, max-hold)
    if broker is not None:
        for a in trade_manager.manage(feed, broker, notifier):
            print(f"  [manage] {a}")
    for sym in WATCH:
        try:
            htf = feed.candles(sym, HTF, 120)
            ltf = feed.candles(sym, LTF, 120)
        except Exception as e:
            msg = str(e)
            if "maintenance" in msg or "503" in msg:
                print(f"  {sym}: OANDA under maintenance — will retry next run.")
            else:
                print(f"  {sym}: data error {e}")
            continue
        sig = evaluate(sym, htf, ltf, when=htf[-1].time if htf else dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
        if sig.action == "SETUP":
            if sym in ALERT_ONLY:                # gold: alert + size + Kalshi confluence, no execution
                size_line = position_size_hint(sig, balance, risk)
                aid = _journal_alert(sig, balance, risk)
                print(f"  [journal] logged {aid} — record your fill with: "
                      f"python3 journal.py fill {aid} --price <fill> --units <size>")
                notifier.send_text(
                    f"🟡 ALERT-ONLY SETUP — {sym} {sig.direction.value.upper()}\n"
                    f"entry {sig.entry} | stop {sig.stop} | TP {sig.target} | R:R {sig.rr:.2f}\n"
                    f"{size_line}\n"
                    f"{_kalshi_line(sym, htf[-1].c)}\n"
                    f"(gold is alert-only: place this manually. Size computed at "
                    f"{risk * 100:.1f}% risk. Kalshi = crowd confluence, informational.)\n"
                    f"journal id {aid} -> python3 journal.py fill {aid} --price <fill> "
                    f"--units <size>")
            elif not gov.can_trade(taken):
                notifier.send(Signal("NO_TRADE", sym, sig.direction,
                    f"setup found but weekly cap reached ({taken}/{gov.max_per_week}) — DO NOT CHASE",
                    when=sig.when, checks={"cap": f"{taken}/{gov.max_per_week}"}))
            else:
                notifier.send(sig)
                aid = _journal_alert(sig, balance, risk)
                print(f"  [journal] logged {aid}")
                if broker is not None:           # managed paper auto-execution
                    res = trade_manager.open_trade(broker, sig)
                    print(f"  [paper] {sym}: {res}")
                taken += 1
                state["taken"][wk] = taken
                save_state(state)
        else:
            notifier.send(sig)
    print(f"    -> week {wk} now {taken}/{gov.max_per_week}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="synthetic data (no internet)")
    ap.add_argument("--oanda", action="store_true", help="use OANDA practice spot data (EUR/USD etc.)")
    ap.add_argument("--paper", action="store_true", help="auto paper-execute A+ setups on OANDA demo")
    ap.add_argument("--telegram", action="store_true", help="also send A+ setups to Telegram")
    ap.add_argument("--market-hours-only", action="store_true",
                    help="exit early if forex is closed (for scheduled/CI runs)")
    ap.add_argument("--risk", type=float, default=RISK_PER_TRADE * 100.0,
                    help="%% of balance risked per trade (default: Sci's stated 10%%)")
    ap.add_argument("--balance", type=float, default=None,
                    help="balance used for manual-entry sizing hints when no live "
                         "account is reachable (default: %(default)s -> 10000)")
    args = ap.parse_args()

    # market-hours guard (skip weekend/rollover so CI runs don't waste time)
    if args.market_hours_only:
        from market_hours import is_forex_open
        if not is_forex_open():
            print(f"Forex closed now ({dt.datetime.now(dt.timezone.utc).replace(tzinfo=None):%a %H:%M} UTC). Skipping.")
            raise SystemExit(0)

    # --- choose data feed ---
    feed = None; src = None
    try:
        if args.oanda:
            from oanda_feed import OANDADataFeed
            feed = OANDADataFeed(verbose=True)
            src = "OANDA practice (real spot)"
        elif args.demo:
            feed = DemoFeed(); src = "DEMO (synthetic)"
        else:
            feed = __import__("feeds").CCXTDataFeed(verbose=False); src = "CCXT (OKX/Kucoin)"
    except Exception as e:
        print(f"Feed unavailable: {e}")
        if args.oanda:
            print("Set env vars first:  export OANDA_API_TOKEN=... ; export OANDA_ACCOUNT_ID=...")
        raise SystemExit(1)
    notifiers = [ConsoleNotifier()]
    gov = Governor(target_per_week=1, max_per_week=2)

    # --- risk configuration (single source of truth) ---
    risk_frac = max(args.risk, 0.0) / 100.0
    if risk_frac <= 0:
        print("--risk must be greater than 0"); raise SystemExit(2)
    if risk_frac > 1.0:
        print(f"--risk {args.risk}% means more than the whole balance per trade; "
              f"did you pass a fraction instead of a percent?"); raise SystemExit(2)
    print(f"⚠️  {risk_ladder_notice(risk_frac)}")
    if WATCH and set(WATCH) <= ALERT_ONLY:
        print(f"   watchlist {WATCH} is all ALERT_ONLY -> nothing auto-executes at "
              f"this setting; alerts carry the computed size for manual entry.")

    # --- optional paper broker ---
    broker = None
    if args.paper:
        try:
            from oanda_feed import OANDAPaperBroker
            broker = OANDAPaperBroker(risk_fraction=risk_frac)
            print(f"(paper auto-execution ON — OANDA demo, {risk_frac * 100:.1f}% risk/trade)")
        except Exception as e:
            print(f"(paper broker not active: {e})")

    # --- chain Telegram notifier ---
    use_tg = args.telegram
    if use_tg:
        try:
            from notifier_telegram import TelegramNotifier
            notifiers.append(TelegramNotifier())
        except Exception as e:
            print(f"(Telegram not active: {e})")

    class Multi:
        def __init__(self, ns): self.ns = ns
        def send(self, sig):
            for n in self.ns:
                try: n.send(sig)
                except Exception as e: print(f"notifier error: {e}")
        def send_text(self, text):
            for n in self.ns:
                try: n.send_text(text)
                except Exception as e: print(f"notifier error: {e}")
    notifier = Multi(notifiers)

    mode = src
    tg = " + Telegram" if use_tg else ""
    pap = " + PAPER AUTO-EXEC" if broker else ""
    print(f"ICC scanner — {mode}{tg}{pap}. GOLD ONLY, {HTF} markup / {LTF} entry, "
          f"{risk_frac * 100:.1f}% risk/trade. Alert-only default. Ctrl+C to stop.")
    scan_once(feed, notifier, gov, broker=broker, risk=risk_frac, balance=args.balance)
    if args.oanda:
        print("\nLive OANDA scan complete. Schedule scan_once() every 15 min (cron/systemd).")
