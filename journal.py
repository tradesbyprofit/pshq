"""
journal.py — records what the bot SAID vs. what you ACTUALLY did.

Gold is alert-only (OANDA practice accounts are forex-only), so you place every
trade by hand. That means the bot has no idea whether you filled it, at what
price, at what size, or whether you honoured the stop. Without that, there is no
way to measure expectancy on the new 4H/1H method — and OANDA will never have
closed gold trades to read, so trade_stats.py has nothing to chew on.

This is the missing record. Append-only JSONL, one file, no dependencies.

  EVENTS
    alert  the bot fired a setup          (written automatically by scanner.py)
    fill   you entered it                 (you write this)
    exit   you closed it                  (you write this)
    skip   you saw the alert and passed   (you write this — see below)

  Recording SKIPS matters as much as fills. If the setups you skipped would have
  won, your discretion is costing you money. If they would have lost, your
  discretion is the edge. You cannot know which without writing them down.

USAGE
  python3 journal.py                        # dashboard: open, recent, expectancy
  python3 journal.py alerts                 # alerts awaiting a decision
  python3 journal.py fill --last --price 4037.2 --units 40
  python3 journal.py fill A0007 --price 4037.2 --units 40 --stop 4061 --tp 3986
  python3 journal.py exit A0007 --price 3990 --reason tp
  python3 journal.py skip A0008 --reason "no NY volume yet"
  python3 journal.py report                 # divergence + expectancy in R

  --last means "the most recent alert that still needs a decision".

Everything computed here is expressed in R (multiples of the amount risked) so
it is comparable across balances and can feed compound_reality.py --from-journal.

Not financial advice. It is a notebook with arithmetic.
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, sys
from typing import Dict, List, Optional

JOURNAL_FILE = os.getenv("ICC_JOURNAL", "journal.jsonl")
METHOD_TAG = "ICC 4H markup / 1H entry (2026-07-30 update)"
EXIT_REASONS = ("tp", "sl", "manual", "partial", "structure")


# --- primitives --------------------------------------------------------------
def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _path(path: Optional[str] = None) -> str:
    return path or JOURNAL_FILE


def append(event: dict, path: Optional[str] = None) -> dict:
    event = {"ts": _now(), **event}
    with open(_path(path), "a") as f:
        f.write(json.dumps(event, default=str) + "\n")
    return event


def load(path: Optional[str] = None) -> List[dict]:
    path = _path(path)
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  ! skipping corrupt journal line: {e}", file=sys.stderr)
    return out


def index(events: Optional[List[dict]] = None, path: Optional[str] = None) -> Dict[str, dict]:
    """Collapse the append-only log into {alert_id: {alert, fill, exit, skip}}."""
    events = load(path) if events is None else events
    out: Dict[str, dict] = {}
    for e in events:
        aid = e.get("id")
        if not aid:
            continue
        rec = out.setdefault(aid, {})
        kind = e.get("ev")
        if kind == "alert":
            rec["alert"] = e
        elif kind in ("fill", "exit", "skip"):
            rec[kind] = e
    return out


def next_id(events: Optional[List[dict]] = None, path: Optional[str] = None) -> str:
    n = sum(1 for e in (load(path) if events is None else events) if e.get("ev") == "alert")
    return f"A{n + 1:04d}"


def _quote_to_usd(instrument: str) -> float:
    """Dollars per unit of the quote currency. Gold is USD-quoted, so this is
    1.0 without any network call; the import is best-effort for other symbols."""
    try:
        from oanda_feed import quote_to_usd
        return quote_to_usd(instrument)
    except Exception:
        return 1.0


# --- writes ------------------------------------------------------------------
def log_alert(sig, risk_pct: float, balance: float,
              units: Optional[float] = None, risk_usd: Optional[float] = None,
              too_small: Optional[str] = None, path: Optional[str] = None) -> str:
    """Record a setup the bot fired. Called automatically by scanner.py."""
    aid = next_id(path=path)
    append({
        "ev": "alert", "id": aid, "symbol": sig.symbol,
        "direction": getattr(getattr(sig, "direction", None), "value", str(sig.direction)),
        "entry": sig.entry, "stop": sig.stop, "target": sig.target,
        "rr": sig.rr, "reason": sig.reason, "checks": getattr(sig, "checks", {}),
        "risk_pct": risk_pct, "balance": balance,
        "units_suggested": units, "risk_usd_suggested": risk_usd,
        "too_small": too_small, "method": METHOD_TAG,
    }, path)
    return aid


def log_fill(aid: str, price: float, units: float, stop: Optional[float] = None,
             target: Optional[float] = None, broker: str = "", note: str = "",
             path: Optional[str] = None) -> dict:
    rec = index(path=path).get(aid)
    if not rec or "alert" not in rec:
        raise KeyError(f"no alert {aid} in {JOURNAL_FILE}")
    if "fill" in rec:
        raise ValueError(f"{aid} already has a fill recorded — use a new alert id "
                         f"if you re-entered")
    a = rec["alert"]
    return append({
        "ev": "fill", "id": aid, "price": price, "units": units,
        # default to the levels the bot gave you; override only if you changed them
        "stop": a["stop"] if stop is None else stop,
        "target": a["target"] if target is None else target,
        "broker": broker, "note": note,
    }, path)


def log_exit(aid: str, price: float, reason: str = "manual", note: str = "",
             path: Optional[str] = None) -> dict:
    rec = index(path=path).get(aid)
    if not rec or "fill" not in rec:
        raise KeyError(f"{aid} has no fill recorded — log the fill first")
    if "exit" in rec:
        raise ValueError(f"{aid} is already closed")
    if reason not in EXIT_REASONS:
        raise ValueError(f"reason must be one of {EXIT_REASONS}")
    return append({"ev": "exit", "id": aid, "price": price,
                   "reason": reason, "note": note}, path)


def log_skip(aid: str, reason: str = "", path: Optional[str] = None) -> dict:
    rec = index(path=path).get(aid)
    if not rec or "alert" not in rec:
        raise KeyError(f"no alert {aid} in {JOURNAL_FILE}")
    if "fill" in rec:
        raise ValueError(f"{aid} was filled, not skipped")
    return append({"ev": "skip", "id": aid, "reason": reason}, path)


# --- reads -------------------------------------------------------------------
def resolve_id(token: Optional[str], path: Optional[str] = None,
               want: str = "pending") -> str:
    """Resolve '--last' to a real alert id.

    'last' is context-dependent, and getting this wrong makes the CLI useless at
    exactly the moment you need it:
      want="pending" (fill/skip) -> newest alert with no fill and no skip
      want="open"    (exit)      -> newest alert WITH a fill but no exit yet
    """
    idx = index(path=path)
    if not idx:
        raise KeyError("journal is empty")
    if token and token.lower() != "last":
        if token not in idx:
            raise KeyError(f"no alert {token}. Try: python3 journal.py alerts")
        return token
    if want == "open":
        cand = [aid for aid, r in idx.items()
                if "fill" in r and "exit" not in r]
        if not cand:
            raise KeyError("no open position to close (nothing filled and still open)")
    else:
        cand = [aid for aid, r in idx.items()
                if "alert" in r and "fill" not in r and "skip" not in r]
        if not cand:
            raise KeyError("no alert is awaiting a decision "
                           "(fill or skip one first — see `journal.py alerts`)")
    return sorted(cand)[-1]


def _direction_sign(d: str) -> int:
    return 1 if str(d).lower() in ("bull", "buy", "long") else -1


def closed_trades(events: Optional[List[dict]] = None, path: Optional[str] = None) -> List[dict]:
    """Every alert with both a fill and an exit, with the arithmetic done."""
    out = []
    for aid, rec in sorted(index(events, path).items()):
        a, f, x = rec.get("alert"), rec.get("fill"), rec.get("exit")
        if not (a and f and x):
            continue
        d = _direction_sign(a["direction"])
        entry, stop, exit_p = f["price"], f["stop"], x["price"]
        # R is measured against YOUR actual risk: the distance from your real
        # fill to the stop you actually used. Chasing an entry widens that
        # distance, so the same target correctly yields fewer R.
        risk_per_unit = abs(entry - stop)
        if risk_per_unit <= 0:
            continue
        q2usd = _quote_to_usd(a["symbol"])
        units = abs(f["units"])
        risk_usd = units * risk_per_unit * q2usd
        pnl_usd = (exit_p - entry) * d * units * q2usd
        r_achieved = (exit_p - entry) * d / risk_per_unit

        # Slippage = how much WORSE your fill was than the alert, in R of the
        # ORIGINAL plan. Negative is a cost. Bull filled higher = worse; bear
        # filled lower = worse (you sold cheaper). Measured against the alert's
        # own stop distance so it stays comparable across trades.
        alert_risk = abs(a["entry"] - a["stop"]) if a.get("entry") and a.get("stop") else None
        slip_r = (-((f["price"] - a["entry"]) * d) / alert_risk) if alert_risk else 0.0

        # "Stop honoured" only means something on a LOSER: when it went against
        # you, did you actually exit at your stop, or did you hold and let it
        # grow? Winners are not a discipline failure, so they are excluded from
        # the denominator in stats_r() rather than counted as passes.
        is_loss = r_achieved <= 0
        near_stop = abs(exit_p - stop) / risk_per_unit <= 0.15
        stop_honoured = (not is_loss) or (x.get("reason") == "sl") or near_stop
        out.append({
            "id": aid, "symbol": a["symbol"], "direction": a["direction"],
            "alerted_at": a["ts"], "filled_at": f["ts"], "exited_at": x["ts"],
            "alert_entry": a.get("entry"), "fill_price": entry, "exit_price": exit_p,
            "stop": stop, "target": f.get("target"), "exit_reason": x.get("reason"),
            "units": units, "units_suggested": a.get("units_suggested"),
            "risk_pct": a.get("risk_pct"),
            "risk_usd": risk_usd, "risk_usd_suggested": a.get("risk_usd_suggested"),
            "pnl_usd": pnl_usd, "r": r_achieved, "rr_suggested": a.get("rr"),
            "slippage_r": slip_r,
            "is_loss": is_loss,
            "stop_honoured": stop_honoured,
            "size_ratio": (units / a["units_suggested"]) if a.get("units_suggested") else None,
            "method": a.get("method"),
        })
    return out


def skipped(events: Optional[List[dict]] = None, path: Optional[str] = None) -> List[dict]:
    return [{"id": aid, **rec["skip"], "alert": rec["alert"]}
            for aid, rec in sorted(index(events, path).items())
            if "skip" in rec and "alert" in rec]


def open_positions(events: Optional[List[dict]] = None, path: Optional[str] = None) -> List[dict]:
    out = []
    for aid, rec in sorted(index(events, path).items()):
        a, f = rec.get("alert"), rec.get("fill")
        if a and f and "exit" not in rec:
            d = _direction_sign(a["direction"])
            risk_per_unit = abs(f["price"] - f["stop"]) or None
            out.append({"id": aid, "symbol": a["symbol"], "direction": a["direction"],
                        "entry": f["price"], "stop": f["stop"], "target": f.get("target"),
                        "units": abs(f["units"]), "filled_at": f["ts"],
                        "risk_usd": (abs(f["units"]) * risk_per_unit * _quote_to_usd(a["symbol"]))
                                    if risk_per_unit else None,
                        "_d": d})
    return out


def pending(events: Optional[List[dict]] = None, path: Optional[str] = None) -> List[dict]:
    return [{"id": aid, **rec["alert"]} for aid, rec in sorted(index(events, path).items())
            if "alert" in rec and "fill" not in rec and "skip" not in rec]


# --- arithmetic --------------------------------------------------------------
def stats_r(trades: List[dict]) -> Optional[dict]:
    """Expectancy in R. This is the number that decides whether the method works
    for YOU, on YOUR broker, with YOUR execution — independent of balance."""
    if not trades:
        return None
    rs = [t["r"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    n = len(rs)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "n": n,
        "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / n * 100.0,
        "avg_win_r": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss_r": (gross_loss / len(losses)) if losses else 0.0,
        "expectancy_r": sum(rs) / n,
        "profit_factor": (gross_win / gross_loss) if gross_loss else float("inf"),
        "total_r": sum(rs),
        "best_r": max(rs), "worst_r": min(rs),
        "total_pnl_usd": sum(t["pnl_usd"] for t in trades),
        "avg_slippage_r": sum(t["slippage_r"] for t in trades) / n,
        # denominator is LOSERS only: "when it went against you, did you use the
        # stop?" is the discipline question. None when there are no losers yet.
        "stop_honoured_pct": (
            sum(1 for t in losses_t if t["stop_honoured"]) / len(losses_t) * 100.0
        ) if (losses_t := [t for t in trades if t.get("is_loss")]) else None,
        "sized_as_advised_pct": (
            sum(1 for t in trades if t["size_ratio"] and 0.9 <= t["size_ratio"] <= 1.1)
            / sum(1 for t in trades if t["size_ratio"]) * 100.0
        ) if any(t["size_ratio"] for t in trades) else None,
    }


# --- reporting ---------------------------------------------------------------
def _hdr(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def print_open() -> None:
    op = open_positions()
    _hdr(f"OPEN POSITIONS ({len(op)})")
    if not op:
        print("  none")
        return
    for t in op:
        risk = f"${t['risk_usd']:,.2f}" if t.get("risk_usd") else "?"
        print(f"  {t['id']}  {t['symbol']} {t['direction'].upper():4s} "
              f"{t['units']:.2f}u @ {t['entry']}  SL {t['stop']}  TP {t['target']}  "
              f"risk {risk}  (filled {t['filled_at'][:16]})")


def print_pending() -> None:
    pd = pending()
    _hdr(f"AWAITING YOUR DECISION ({len(pd)})")
    if not pd:
        print("  nothing outstanding")
        return
    for a in pd:
        d = str(a.get("direction", "?")).upper()
        print(f"  {a['id']}  {a['symbol']} {d:4s}  entry {a.get('entry')}  "
              f"SL {a.get('stop')}  TP {a.get('target')}  R:R {a.get('rr')}")
        print(f"          fired {a['ts'][:16]}  |  {str(a.get('reason',''))[:64]}")
    print("\n  Record what you did, or these never become data:")
    print("    python3 journal.py fill --last --price <fill> --units <size>")
    print("    python3 journal.py skip --last --reason \"<why>\"")


def print_report() -> None:
    tr = closed_trades()
    sk = skipped()
    s = stats_r(tr)
    _hdr(f"EXPECTANCY — {METHOD_TAG}")
    if not s:
        print("  No closed trades in the journal yet.")
        print("  You need a fill AND an exit on the same alert id. Try:")
        print("    python3 journal.py alerts")
        return
    print(f"  Closed trades      : {s['n']}   ({s['wins']}W / {s['losses']}L)")
    print(f"  Win rate           : {s['win_rate']:.1f}%")
    print(f"  Avg win            : +{s['avg_win_r']:.2f}R")
    print(f"  Avg loss           : -{s['avg_loss_r']:.2f}R")
    pf = s['profit_factor']
    print(f"  Profit factor      : {'inf' if pf == float('inf') else f'{pf:.2f}'}   (>1.0 = profitable)")
    print(f"  EXPECTANCY         : {s['expectancy_r']:+.3f}R per trade   (+ = you have an edge)")
    print(f"  Total              : {s['total_r']:+.2f}R  (${s['total_pnl_usd']:+,.2f})")
    print(f"  Best / worst       : {s['best_r']:+.2f}R / {s['worst_r']:+.2f}R")

    _hdr("EXECUTION DISCIPLINE — you vs. the bot")
    sl = s["avg_slippage_r"]
    if abs(sl) < 0.02:
        sl_note = "you fill almost exactly where the bot said"
    elif sl < 0:
        sl_note = f"COST: you fill worse than the alert ({abs(sl):.2f}R given away per trade)"
    else:
        sl_note = "you fill better than the alert (keep doing whatever that is)"
    print(f"  Avg entry slippage : {sl:+.3f}R  ({sl_note})")
    shp = s["stop_honoured_pct"]
    if shp is None:
        print("  Stop honoured      : n/a (no losing trades yet — nothing to measure)")
    else:
        print(f"  Stop honoured      : {shp:.0f}% of LOSING trades exited at/near the stop")
        if shp < 100:
            print("                       ^ the rest you held past your stop. That is where")
            print("                         a working method gets turned into a losing one.")
    if s["sized_as_advised_pct"] is None:
        print("  Size adherence     : n/a (no suggested sizes recorded)")
    else:
        print(f"  Size adherence     : {s['sized_as_advised_pct']:.0f}% within +/-10% of the advised lot")
    print(f"  Skipped alerts     : {len(sk)}")
    if sk:
        print("    " + ", ".join(f"{x['id']}({x.get('reason') or 'no reason given'})"
                                for x in sk[-6:]))
    print()
    if s["n"] < 30:
        noun = "trade is" if s["n"] == 1 else "trades are"
        print(f"  ⚠️  {s['n']} {noun} not a sample. Expectancy this early is noise:")
        print("     at 30 trades a pure coinflip still shows a convincing edge about")
        print("     a third of the time. Keep recording; re-read this at 50+ closed.")
    else:
        verdict = "POSITIVE — the method is paying you" if s["expectancy_r"] > 0 \
            else "NEGATIVE — you are paying the market"
        print(f"  Verdict on {s['n']} trades: expectancy {s['expectancy_r']:+.3f}R -> {verdict}")
    print(f"  Feed it forward:  python3 compound_reality.py --from-journal")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Alert-vs-actual trade journal.")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("alerts", help="alerts awaiting a decision")
    sub.add_parser("open", help="positions with a fill but no exit")
    sub.add_parser("report", help="expectancy in R + execution discipline")
    sub.add_parser("closed", help="dump every closed trade as JSON lines")

    for name in ("fill", "exit", "skip"):
        p = sub.add_parser(name)
        # accept all three: `fill A0007`, `fill --last`, and bare `fill`
        p.add_argument("id", nargs="?", default=None, help="alert id (default: --last)")
        p.add_argument("--last", action="store_true",
                       help="the most recent alert still awaiting a decision")
        if name == "fill":
            p.add_argument("--price", type=float, required=True)
            p.add_argument("--units", type=float, required=True)
            p.add_argument("--stop", type=float, default=None)
            p.add_argument("--tp", type=float, default=None)
            p.add_argument("--broker", default="")
            p.add_argument("--note", default="")
        elif name == "exit":
            p.add_argument("--price", type=float, required=True)
            p.add_argument("--reason", default="manual", choices=EXIT_REASONS)
            p.add_argument("--note", default="")
        else:
            p.add_argument("--reason", default="")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "alerts":
            print_pending()
        elif a.cmd == "open":
            print_open()
        elif a.cmd == "report":
            print_report()
        elif a.cmd == "closed":
            for t in closed_trades():
                print(json.dumps(t, default=str))
        elif a.cmd in ("fill", "exit", "skip"):
            token = "last" if getattr(a, "last", False) else (a.id or "last")
            # `exit` closes an OPEN position; `fill`/`skip` answer a PENDING alert
            aid = resolve_id(token, want=("open" if a.cmd == "exit" else "pending"))
            if a.cmd == "fill":
                e = log_fill(aid, a.price, a.units, stop=a.stop, target=a.tp,
                             broker=a.broker, note=a.note)
                rec = index()[aid]
                d = _direction_sign(rec["alert"]["direction"])
                risk = abs(a.units) * abs(a.price - e["stop"]) * _quote_to_usd(rec["alert"]["symbol"])
                print(f"✅ fill recorded on {aid}: "
                      f"{'BUY' if d > 0 else 'SELL'} {abs(a.units):.2f}u @ {a.price} "
                      f"SL {e['stop']} TP {e['target']} | risks ${risk:,.2f}")
                if rec["alert"].get("units_suggested"):
                    ratio = abs(a.units) / rec["alert"]["units_suggested"]
                    print(f"   advised {rec['alert']['units_suggested']:.2f}u at "
                          f"{rec['alert'].get('risk_pct')}% risk -> you took {ratio:.2f}x that size")
            elif a.cmd == "exit":
                e = log_exit(aid, a.price, reason=a.reason, note=a.note)
                tr = [t for t in closed_trades() if t["id"] == aid]
                if tr:
                    t = tr[0]
                    print(f"✅ {aid} closed at {a.price} ({a.reason}) -> "
                          f"{t['r']:+.2f}R  (${t['pnl_usd']:+,.2f})")
                else:
                    print(f"✅ exit recorded on {aid}")
            else:
                log_skip(aid, reason=a.reason)
                print(f"✅ {aid} marked SKIPPED"
                      f"{' — ' + a.reason if a.reason else ''}")
        else:
            print_pending()
            print_open()
            print_report()
    except (KeyError, ValueError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
