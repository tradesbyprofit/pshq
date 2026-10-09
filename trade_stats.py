"""
trade_stats.py — The REAL measure of profitability.

Profit isn't "zero reds" — it's positive EXPECTANCY. This shows win rate, avg win
vs avg loss, profit factor, expectancy/trade, and current streak.

TWO SOURCES, because gold is alert-only:
  oanda   closed trades on the OANDA practice account (forex only — there will
          never be closed GOLD trades here, since XAUUSD cannot be executed on a
          forex-only practice account)
  journal YOUR hand-placed gold trades, from journal.py, measured in R against
          what the bot actually told you to do

Default is "auto": try OANDA, and if it has nothing, read the journal.

Usage:  python3 trade_stats.py                  # auto
        python3 trade_stats.py --source journal # your hand-traded gold, in R
        python3 trade_stats.py --source oanda   # OANDA practice history, in $
"""
import argparse, os
from oanda_feed import _req


def get_closed_trades(limit=500):
    acct = os.getenv("OANDA_ACCOUNT_ID")
    r = _req(f"/accounts/{acct}/trades?state=CLOSED&count={limit}")
    return r.get("trades", [])


def stats(trades):
    if not trades:
        return None
    pl = [float(t.get("realizedPL", 0)) for t in trades]
    wins = [p for p in pl if p > 0]
    losses = [p for p in pl if p < 0]
    n = len(pl)
    win_rate = len(wins) / n * 100 if n else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss else float("inf")
    expectancy = sum(pl) / n  # avg $ per trade
    total = sum(pl)
    # streak (most recent run of wins or losses)
    streak = 0; kind = None
    for p in reversed(pl):
        if kind is None:
            kind = "W" if p > 0 else ("L" if p < 0 else "—")
            streak = 1
        elif (p > 0 and kind == "W") or (p < 0 and kind == "L"):
            streak += 1
        else:
            break
    # avg R:R realized (using each trade's SL distance if available)
    return dict(n=n, win_rate=win_rate, avg_win=avg_win, avg_loss=avg_loss,
                profit_factor=profit_factor, expectancy=expectancy, total=total,
                gross_profit=gross_profit, gross_loss=gross_loss,
                streak=streak, streak_kind=kind, wins=len(wins), losses=len(losses))


def journal_stats():
    """Expectancy in R from hand-placed trades recorded in journal.py."""
    try:
        import journal
    except Exception as e:
        print(f"  (journal unavailable: {e})")
        return None, []
    tr = journal.closed_trades()
    return journal.stats_r(tr), tr


def print_journal(s, trades):
    print("=" * 56)
    print("  YOUR GOLD TRADING  (journal.py, hand-placed)")
    print("  method: ICC 4H markup / 1H entry")
    print("=" * 56)
    if not s:
        print("  Nothing closed in the journal yet.")
        print("  The bot logs every alert automatically; you add the fill and the exit:")
        print("    python3 journal.py fill --last --price <fill> --units <size>")
        print("    python3 journal.py exit --last --price <exit> --reason tp|sl|manual")
        print("  Record SKIPS too — `journal.py skip --last --reason ...`")
        return
    print(f"  Closed trades      : {s['n']}   ({s['wins']}W / {s['losses']}L)")
    print(f"  Win rate           : {s['win_rate']:.1f}%")
    print(f"  Avg win            : +{s['avg_win_r']:.2f}R")
    print(f"  Avg loss           : -{s['avg_loss_r']:.2f}R")
    pf = s['profit_factor']
    print(f"  Win:Loss size      : "
          f"{(s['avg_win_r'] / s['avg_loss_r']) if s['avg_loss_r'] else float('inf'):.2f} : 1")
    print(f"  Profit factor      : {'inf' if pf == float('inf') else f'{pf:.2f}'}   (>1.0 = profitable)")
    print(f"  EXPECTANCY         : {s['expectancy_r']:+.3f}R per trade   (+ = edge)")
    print(f"  Total              : {s['total_r']:+.2f}R  (${s['total_pnl_usd']:+,.2f})")
    print("-" * 56)
    print("  you vs. the bot:")
    sl = s['avg_slippage_r']
    sl_note = ("as advised" if abs(sl) < 0.02 else
               (f"{abs(sl):.2f}R WORSE than the alert" if sl < 0 else
                f"{sl:.2f}R better than the alert"))
    print(f"    entry slippage   : {sl:+.3f}R  ({sl_note})")
    shp = s['stop_honoured_pct']
    print(f"    stop honoured    : "
          + ("n/a (no losers yet)" if shp is None else f"{shp:.0f}% of losing trades"))
    if s['sized_as_advised_pct'] is not None:
        print(f"    sized as advised : {s['sized_as_advised_pct']:.0f}% within +/-10%")
    print("=" * 56)
    if s['n'] < 30:
        noun = "trade is" if s['n'] == 1 else "trades are"
        print(f"  ⚠️  {s['n']} {noun} not a sample yet. Re-read this at 50+ closed.")
    else:
        print("  Feed it forward:  python3 compound_reality.py --from-journal")
    print("  Full breakdown:   python3 journal.py report")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("auto", "oanda", "journal"), default="auto")
    args = ap.parse_args()

    if args.source == "journal":
        js, jt = journal_stats()
        print_journal(js, jt)
        return

    try:
        trades = get_closed_trades()
    except Exception as e:
        msg = str(e)
        if "maintenance" in msg or "503" in msg:
            print("OANDA is under weekend maintenance — run this again later.")
        else:
            print("Could not read OANDA trades:", msg)
        js, jt = journal_stats()
        print()
        print_journal(js, jt)
        return

    s = stats(trades)
    if not s:
        print("No closed OANDA trades yet.\n"
              "(Gold is alert-only on a forex-only practice account, so closed GOLD\n"
              " trades will never appear here — they live in the journal instead.)")
        js, jt = journal_stats()
        print()
        print_journal(js, jt)
        return

    print("=" * 52)
    print("  PAPER ACCOUNT PERFORMANCE  (OANDA demo)")
    print("=" * 52)
    print(f"  Closed trades      : {s['n']}")
    print(f"  Wins / Losses      : {s['wins']}W / {s['losses']}L")
    print(f"  Win rate           : {s['win_rate']:.1f}%")
    print(f"  Avg win            : +${s['avg_win']:.2f}")
    print(f"  Avg loss           : -${s['avg_loss']:.2f}")
    rr = (s['avg_win'] / s['avg_loss']) if s['avg_loss'] else float('inf')
    print(f"  Win:Loss size      : {rr:.2f} : 1   (>1.0 = winners bigger)")
    print(f"  Profit factor      : {s['profit_factor']:.2f}   (>1.0 = profitable)")
    print(f"  Expectancy/trade   : ${s['expectancy']:+.2f}   (+ = edge)")
    print(f"  Current streak     : {s['streak']} {s['streak_kind']}")
    print("-" * 52)
    print(f"  NET P/L            : ${s['total']:+.2f}")
    print("=" * 52)
    print("Remember: small capped reds are the COST of doing business.")
    print("Green over time = win rate x avg win  >  loss rate x avg loss.")
    js, jt = journal_stats()
    if jt:
        print()
        print_journal(js, jt)


if __name__ == "__main__":
    main()
