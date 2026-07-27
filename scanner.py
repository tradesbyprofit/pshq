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

# OANDA demo offers 68 forex pairs (no metals/crypto yet).
# Watchlist = liquid majors + the most popular volatile cross (great ICC structure).
WATCH = ["EURUSD", "GBPUSD", "USDJPY", "GBPJPY", "BTCUSD", "XAUUSD"]
ALERT_ONLY = {"BTCUSD", "XAUUSD"}     # monitored + alerted, not auto-traded (OANDA demo can't trade them)
HTF = "1H"; LTF = "15M"               # markup TF / entry TF (4H/5M as alternates)
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
def scan_once(feed: DataFeed, notifier: Notifier, gov: Governor, broker=None):
    state = load_state()
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
            if sym in ALERT_ONLY:                # BTC/gold: alert + Kalshi confluence, no execution
                notifier.send_text(
                    f"🟡 ALERT-ONLY SETUP — {sym} {sig.direction.value.upper()}\n"
                    f"entry {sig.entry} | stop {sig.stop} | TP {sig.target} | R:R {sig.rr:.2f}\n"
                    f"{_kalshi_line(sym, htf[-1].c)}\n"
                    f"(monitored via free feed; trade manually. Kalshi = crowd confluence, informational.)")
            elif not gov.can_trade(taken):
                notifier.send(Signal("NO_TRADE", sym, sig.direction,
                    f"setup found but weekly cap reached ({taken}/{gov.max_per_week}) — DO NOT CHASE",
                    when=sig.when, checks={"cap": f"{taken}/{gov.max_per_week}"}))
            else:
                notifier.send(sig)
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

    # --- optional paper broker ---
    broker = None
    if args.paper:
        try:
            from oanda_feed import OANDAPaperBroker
            broker = OANDAPaperBroker(risk_fraction=0.01)
            print("(paper auto-execution ON — OANDA demo, 1% risk/trade)")
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
    print(f"ICC scanner — {mode}{tg}{pap}. Alert-only default. Ctrl+C to stop.")
    scan_once(feed, notifier, gov, broker=broker)
    if args.oanda:
        print("\nLive OANDA scan complete. Schedule scan_once() every 15 min (cron/systemd).")
