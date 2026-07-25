"""
trade_stats.py — The REAL measure of profitability from your OANDA demo history.

Profit isn't "zero reds" — it's positive EXPECTANCY. This pulls every closed
trade and shows: win rate, avg win vs avg loss, profit factor, expectancy/trade,
and current streak. Run it anytime to see how the bot is actually doing.

Usage:  OANDA creds in env, then:  python3 trade_stats.py
"""
import os
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


def main():
    try:
        trades = get_closed_trades()
    except Exception as e:
        msg = str(e)
        if "maintenance" in msg or "503" in msg:
            print("OANDA is under weekend maintenance — run this again later.")
        else:
            print("Could not read trades:", msg)
        return

    s = stats(trades)
    if not s:
        print("No closed trades yet. Stats will appear once the bot takes its first paper trades.\n"
              "(Profitability = positive expectancy, not 'zero reds' — losses are normal and capped.)")
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


if __name__ == "__main__":
    main()
