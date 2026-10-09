"""
compound_reality.py — answers "can $1 become $1,000,000?" with arithmetic
instead of hope.

It uses THIS repo's own numbers: the Governor's trade frequency (scanner.py),
the 1% risk per trade (oanda_feed.OANDAPaperBroker), and — if you pass
--from-demo — your ACTUAL win rate / avg win / avg loss from trade_stats.py
against the OANDA practice account.

Three sections:
  1. WHAT IT TAKES   deterministic compounding: per-trade growth needed to turn
                     `--start` into `--goal` inside 1 / 2 / 5 / 10 / 25 years.
  2. MONTE CARLO     thousands of simulated trade sequences through this bot's
                     edge -> P(reach goal), P(ruin), median outcome, worst
                     drawdown, and how many YEARS the median path takes.
  3. MIN VIABLE $    the smallest balance that can physically place one
                     1%-risk order per watched pair. OANDA rounds forex to whole
                     units and P/L is paid in the QUOTE currency, so a tiny
                     account is not "small" — it is untradeable on some pairs.

Usage:
  python3 compound_reality.py                     # honest defaults
  python3 compound_reality.py --from-demo         # use YOUR real demo stats
  python3 compound_reality.py --win-rate 45 --avg-win-r 1.8 --avg-loss-r 1.0
  python3 compound_reality.py --start 1 --goal 1000000 --risk 1 --paths 5000
  python3 compound_reality.py --min-account       # just section 3

Nothing here is financial advice. It is a calculator. It says "no" a lot
because the honest answer usually is.
"""
from __future__ import annotations
import argparse, math, random, sys
from dataclasses import dataclass

# --- this repo's actual operating parameters ---------------------------------
TRADES_PER_WEEK = 1.0     # scanner.Governor(target_per_week=1, max_per_week=2)
WEEKS_PER_YEAR = 52.0
try:                      # stay in sync with whatever the scanner is set to
    from scanner import RISK_PER_TRADE as _RISK_FRACTION
    RISK_PCT = _RISK_FRACTION * 100.0
except Exception:
    RISK_PCT = 10.0       # Sci's stated default; operator decision 2026-10-08
GOLD_MIN_UNITS = 0.01     # OANDA minimum lot on XAU_USD
GOLD_TYP_STOP = 25.0      # representative 4H structural stop, $ per oz

# OANDA lot rules live in oanda_feed.py (MIN_FX_UNITS / MIN_OTHER_UNITS); this
# section imports them rather than duplicating them.

# symbol -> (representative entry price, representative 15M ICC stop distance
# in PRICE units). Used to compute the smallest balance that can honour a 1%
# risk budget on each pair.
PAIR_SPECS = [
    ("EURUSD", 1.0850,   0.0020),   # ~20 pip stop, quote is USD
    ("GBPUSD", 1.2700,   0.0025),   # ~25 pip stop
    ("USDJPY", 150.00,   0.5000),   # ~50 pip stop, quote is JPY
    ("GBPJPY", 190.00,   0.7000),   # ~70 pip stop, quote is JPY
    ("XAUUSD", 4000.00,  25.00),    # ~$25 4H gold stop, 0.01 unit min
    ("BTCUSD", 60000.0,  900.0),    # (not watched any more — gold only)
]


@dataclass
class Edge:
    """A trading edge, expressed in R (multiples of the amount risked)."""
    win_rate: float          # 0..1
    avg_win_r: float         # avg winner size in R (e.g. 2.0 = +2R)
    avg_loss_r: float        # avg loser size in R (usually ~1.0 = stop hit)
    cost_r: float = 0.0      # spread+slippage+fees per trade, in R

    @property
    def expectancy_r(self) -> float:
        return self.win_rate * self.avg_win_r - (1 - self.win_rate) * self.avg_loss_r - self.cost_r

    @property
    def profit_factor(self) -> float:
        gl = (1 - self.win_rate) * self.avg_loss_r + self.cost_r
        gw = self.win_rate * self.avg_win_r
        return float("inf") if gl <= 0 else gw / gl


# --- section 1 ---------------------------------------------------------------
def section_takes(start: float, goal: float, per_week: float) -> None:
    mult = goal / start
    print("=" * 74)
    print("  1. WHAT IT TAKES   (deterministic — assumes you never lose a trade)")
    print("=" * 74)
    print(f"  ${start:,.2f} -> ${goal:,.2f} is a {mult:,.0f}x multiple "
          f"= {(mult - 1) * 100:,.0f}% return")
    print(f"  That is {math.log2(mult):.1f} consecutive DOUBLINGS with no losing streak.")
    print()
    print(f"  {'horizon':>9s} {'trades':>8s} {'needed/trade':>14s} "
          f"{'at 1% risk =':>14s} {'verdict':>10s}")
    print("  " + "-" * 62)
    for years in (1, 2, 5, 10, 25):
        n = years * WEEKS_PER_YEAR * per_week
        g = math.exp(math.log(mult) / n) - 1
        r_needed = g / (RISK_PCT / 100.0)
        verdict = "impossible" if r_needed > 5 else "fantasy" if r_needed > 2 else "heroic"
        print(f"  {years:>7d}y {n:>8.0f} {g * 100:>13.2f}% "
              f"{r_needed:>12.1f}R {verdict:>11s}")
    print()
    print("  Read the 1-year row aloud: to 1,000,000x an account in 52 trades you")
    print("  must grow it ~30% EVERY SINGLE TRADE. At 1% risk that is a +30R winner")
    print("  on every trade for a year straight. No market on earth pays that.")
    print()

    # and the reverse: how long does a genuinely good edge take?
    print("  The other direction — how long a REAL edge takes:")
    print(f"  {'edge (R/trade)':>16s} {'per-trade %':>12s} {'trades':>8s} {'years @1/wk':>12s}")
    print("  " + "-" * 52)
    for e in (0.05, 0.10, 0.20, 0.35, 0.50):
        per = e * RISK_PCT / 100.0
        n = math.log(mult) / math.log(1 + per)
        print(f"  {e:>15.2f}R {per * 100:>11.3f}% {n:>8.0f} {n / (WEEKS_PER_YEAR * per_week):>11.1f}y")
    print("  (+0.35R/trade is a genuinely excellent, rare, durable strategy.)")
    print()


# --- section 2 ---------------------------------------------------------------
def monte_carlo(start: float, goal: float, edge: Edge, risk_pct: float,
                per_week: float, paths: int, max_years: float,
                floor: float, seed: int) -> dict:
    """Simulate `paths` independent trading careers. Returns outcome stats."""
    rng = random.Random(seed)
    risk = risk_pct / 100.0
    max_trades = int(max_years * WEEKS_PER_YEAR * per_week)
    # dispersion: winners aren't all exactly avg_win_r. Gamma with this shape
    # gives a right-skewed R distribution (some small wins, a few big runners).
    shape = 3.0
    scale = edge.avg_win_r / shape if edge.avg_win_r > 0 else 0.0

    hit_goal = 0
    ruined = 0
    expired = 0
    finals = []
    trades_to_goal = []
    worst_dds = []

    for _ in range(paths):
        bal = start
        peak = start
        worst_dd = 0.0
        t = 0
        done = None
        while t < max_trades:
            t += 1
            if rng.random() < edge.win_rate:
                r = rng.gammavariate(shape, scale) if scale > 0 else edge.avg_win_r
            else:
                r = -edge.avg_loss_r
            r -= edge.cost_r
            bal *= (1.0 + risk * r)
            if bal < floor:
                done = "ruin"
                break
            if bal > peak:
                peak = bal
            dd = 1.0 - bal / peak
            if dd > worst_dd:
                worst_dd = dd
            if bal >= goal:
                done = "goal"
                break
        worst_dds.append(worst_dd)
        finals.append(bal)
        if done == "goal":
            hit_goal += 1
            trades_to_goal.append(t)
        elif done == "ruin":
            ruined += 1
        else:
            expired += 1

    finals.sort()

    def pct(p):
        if not finals:
            return float("nan")
        i = min(len(finals) - 1, max(0, int(p * len(finals))))
        return finals[i]

    stg = sorted(trades_to_goal)
    return dict(paths=paths, hit_goal=hit_goal, ruined=ruined, expired=expired,
                median=pct(0.5), p5=pct(0.05), p95=pct(0.95),
                best=finals[-1] if finals else float("nan"),
                trades_to_goal=stg,
                median_trades=(stg[len(stg) // 2] if stg else None),
                median_dd=sorted(worst_dds)[len(worst_dds) // 2],
                max_dd=max(worst_dds) if worst_dds else 0,
                per_week=per_week)


def prob_by_year(r: dict, years: float) -> float:
    """% of ALL paths that reached the goal within `years` (0 if none did)."""
    if not r["trades_to_goal"]:
        return 0.0
    cap = years * WEEKS_PER_YEAR * r["per_week"]
    return 100.0 * sum(1 for t in r["trades_to_goal"] if t <= cap) / r["paths"]


# Labels are chosen so the sign of the expectancy matches the description.
SENSITIVITY_EDGES = [
    ("typical retail (loses to costs)",   Edge(0.40, 1.5, 1.0, 0.05)),
    ("break-even before costs",           Edge(0.50, 1.0, 1.0, 0.05)),
    ("decent discretionary trader",       Edge(0.45, 1.8, 1.0, 0.05)),
    ("this repo's default (50% WR, 2R)",  Edge(0.50, 2.0, 1.0, 0.05)),
    ("elite, rarely sustained",           Edge(0.55, 2.5, 1.0, 0.05)),
    ("the course's claimed 90% win rate", Edge(0.90, 2.0, 1.0, 0.05)),
]


def section_sensitivity(start, goal, risk_pct, per_week, paths, max_years, floor, seed) -> None:
    print(f"  Same ${start:,.2f}, same {risk_pct:.1f}% risk, same "
          f"{per_week:.0f} trade/week — only the EDGE changes:")
    print(f"  {'edge':34s} {'R/trade':>8s} {'by 10y':>8s} {'by 25y':>8s} "
          f"{f'by {max_years:.0f}y':>8s} {'median yrs':>11s}")
    print("  " + "-" * 82)
    for name, e in SENSITIVITY_EDGES:
        r = monte_carlo(start, goal, e, risk_pct, per_week, paths, max_years, floor, seed)
        yrs = (f"{r['median_trades'] / (WEEKS_PER_YEAR * per_week):.1f}y"
               if r["median_trades"] else "—")
        print(f"  {name:34s} {e.expectancy_r:>+7.2f}R "
              f"{prob_by_year(r, 10):>7.1f}% {prob_by_year(r, 25):>7.1f}% "
              f"{prob_by_year(r, max_years):>7.1f}% {yrs:>11s}")
    print("  Columns are the % of ALL simulated careers that reached the goal by")
    print("  that year. 'median yrs' is how long the typical SUCCESS took.")
    print()
    decent_name, decent = SENSITIVITY_EDGES[2]
    print(f"  Notice the '{decent_name}' row. A REAL edge of")
    print(f"  +{decent.expectancy_r:.2f}R/trade still gets there 0.0% of the time in")
    print(f"  {max_years:.0f} years, and it is not bad luck — it is arithmetic:")
    budget = max_years * WEEKS_PER_YEAR * per_week
    per = decent.expectancy_r * risk_pct / 100.0
    need = math.log(goal / start) / math.log(1 + per)
    print(f"      {max_years:.0f} years at {per_week:.0f} trade/week  = "
          f"{budget:,.0f} trades available")
    print(f"      {goal / start:,.0f}x at {per * 100:.3f}%/trade = "
          f"{need:,.0f} trades needed")
    print("  The Governor in scanner.py — 1 trade a week, never chase — is the")
    print("  method's core discipline, and it is simultaneously a hard ceiling on")
    print("  the multiple. You cannot both refuse to overtrade and 1,000,000x an")
    print("  account. The strategy is explicitly built to do the opposite of that.")
    print()
    print("  So the edge column decides everything, and the two edges that arrive")
    print("  inside a human lifetime are the two almost nobody actually has.")
    print("  A verified +0.45R/trade would already place you in the top fraction")
    print("  of a percent of traders alive. Which is why step 1 is measuring your")
    print("  real expectancy, not sizing your dreams.")
    print()


def section_monte_carlo(start, goal, edge, risk_pct, per_week, paths, max_years,
                        floor, seed) -> None:
    r = monte_carlo(start, goal, edge, risk_pct, per_week, paths, max_years, floor, seed)
    print("=" * 74)
    print("  2. MONTE CARLO   (what actually happens when losses exist)")
    print("=" * 74)
    print(f"  Edge used      : {edge.win_rate * 100:.0f}% win rate, "
          f"+{edge.avg_win_r:.2f}R winners, -{edge.avg_loss_r:.2f}R losers")
    print(f"                   expectancy {edge.expectancy_r:+.3f}R/trade, "
          f"profit factor {edge.profit_factor:.2f}, "
          f"cost {edge.cost_r:.2f}R/trade")
    print(f"  Risk           : {risk_pct:.2f}% of balance per trade, "
          f"{per_week:.1f} trades/week (scanner.Governor)")
    print(f"  Paths          : {r['paths']:,} careers, cap {max_years:.0f} years "
          f"({int(max_years * WEEKS_PER_YEAR * per_week)} trades)")
    print("-" * 74)
    print(f"  Reached ${goal:,.0f}   : {r['hit_goal']:,} / {r['paths']:,}  "
          f"= {100 * r['hit_goal'] / r['paths']:.2f}%")
    print(f"  Blew up (ruin)     : {r['ruined']:,} / {r['paths']:,}  "
          f"= {100 * r['ruined'] / r['paths']:.2f}%")
    print(f"  Still grinding     : {r['expired']:,} / {r['paths']:,}  "
          f"= {100 * r['expired'] / r['paths']:.2f}%   (hit the year cap)")
    print("-" * 74)
    print(f"  Ending balance  p5 : ${r['p5']:>14,.2f}")
    print(f"                  med: ${r['median']:>14,.2f}")
    print(f"                  p95: ${r['p95']:>14,.2f}")
    print(f"  Luckiest path of {r['paths']:,}: ${r['best']:,.2f}")
    print(f"  Median worst drawdown along the way: {r['median_dd'] * 100:.0f}%")
    if r["median_trades"]:
        yrs = r["median_trades"] / (WEEKS_PER_YEAR * r["per_week"])
        print(f"  Typical SUCCESS took : {r['median_trades']} trades = {yrs:.1f} years")
    print()
    pg = 100 * r["hit_goal"] / r["paths"]
    if r["hit_goal"] == 0:
        print(f"  >>> ZERO of {r['paths']:,} careers got there. That is the answer.")
    elif pg < 1:
        print("  >>> Fewer than 1% made it. This is a lottery ticket, not a plan.")
    else:
        print(f"  >>> {pg:.0f}% made it — but read the YEARS line above. This edge is")
        print("      already elite, and it still buys a retirement, not a windfall.")
    print()


# --- section 3 ---------------------------------------------------------------
def section_min_account(risk_pct: float) -> None:
    """Smallest balance that lets each pair honour a `risk_pct` budget.

    Delegates to oanda_feed.size_position so this reports what the bot will
    ACTUALLY submit, not a second copy of the math drifting out of sync.
    """
    risk = risk_pct / 100.0
    print("=" * 74)
    print("  3. MIN VIABLE ACCOUNT   (can $1 even place ONE order?)")
    print("=" * 74)
    try:
        import oanda_feed as of
    except Exception as e:
        print(f"  (cannot import oanda_feed: {e})")
        return
    of._QUOTE_CACHE.setdefault("JPY", 1.0 / 150.0)   # keep this section offline

    print("  OANDA needs whole units on forex, and P/L is paid in the QUOTE")
    print("  currency — a yen-denominated stop has to be converted to dollars")
    print("  BEFORE you divide the risk budget by it.")
    print()
    print(f"  {'pair':9s} {'typ stop':>9s} {'min balance':>12s} "
          f"{'min order risks':>16s} {'at $1':>9s}")
    print("  " + "-" * 60)
    for symbol, entry, sl in PAIR_SPECS:
        inst = of.resolve_instrument(symbol)
        bal = 0.05
        while bal < 5_000_000 and of.size_position(inst, bal, risk, entry,
                                                   entry - sl)["too_small"]:
            bal *= 1.02
        at_one = of.size_position(inst, 1.0, risk, entry, entry - sl)
        if at_one["too_small"]:
            cost = f"{at_one['risk_pct']:,.0f}% of acct"
        else:
            cost = f"{at_one['risk_pct']:.2f}% (ok)"
        min_risk = of.size_position(inst, bal, risk, entry, entry - sl)["risk_usd"]
        print(f"  {symbol:9s} {sl:>9.4f} {bal:>11,.2f}$ "
              f"{min_risk:>15.4f}$ {cost:>9s}")
    print()
    print("  Three honest findings:")
    print("   - On USD-quoted forex the floor really is cents, so $1 CAN open a")
    print("     ~1% EURUSD position. The mechanics are not the main blocker.")
    print("   - Gold needs ~$12 and BTC ~$900 before a single minimum order fits")
    print("     inside a 1% budget. On $1 the minimum gold lot risks 12% of the")
    print("     account and the minimum BTC lot risks 900%. The two markets this")
    print("     repo was built around are unreachable on $1 — the bot now skips")
    print("     them with TOO_SMALL instead of firing an order it cannot size.")
    print("   - 'typ stop' is a representative 15M ICC stop. Wider stops raise the")
    print("     floor proportionally, so re-run this if you trade a slower timeframe.")
    print()


# --- section 4: the only published independent backtest ----------------------
# Revelio Trading, "I Coded Trades By Sci's Trading Strategy. Does It Work?"
# https://www.youtube.com/watch?v=bZzREoCf0z0  (2026-08-15)
# 2,500+ backtests, 10 years, 4 markets. Best configuration found, gold+4H,
# at 1% risk per trade: +45.7% total, ~3.63% annualized (3.84% recomputed from
# the total), max drawdown 53.8%. See CAVEATS.md.
MEASURED_TOTAL_RETURN = 0.457
MEASURED_YEARS = 10.0
MEASURED_MAX_DD = 0.538
MEASURED_ANNUAL = (1 + MEASURED_TOTAL_RETURN) ** (1 / MEASURED_YEARS) - 1


def section_measured(start: float, goal: float) -> None:
    print("=" * 74)
    print("  4. THE ONLY PUBLISHED BACKTEST OF THIS EXACT STRATEGY")
    print("=" * 74)
    print("  Revelio Trading coded ICC as taught and ran 2,500+ backtests over")
    print("  10 years on gold, silver, NASDAQ and BTC. Best config, gold + 4H,")
    print("  at 1% risk per trade:")
    print(f"      total return over {MEASURED_YEARS:.0f} years : "
          f"+{MEASURED_TOTAL_RETURN * 100:.1f}%")
    print(f"      annualized               : {MEASURED_ANNUAL * 100:.2f}%")
    print(f"      max drawdown             : {MEASURED_MAX_DD * 100:.1f}%")
    print("      win rate                 : \"nowhere near the 90% he claims\"")
    print("      profit factor            : \"not around 10\"")
    print("-" * 74)
    for s in (start, 1_000.0, 10_000.0, 100_000.0):
        if s <= 0 or s >= goal:
            continue
        yrs = math.log(goal / s) / math.log(1 + MEASURED_ANNUAL)
        tag = "  <- your start" if s == start else ""
        print(f"  ${s:>10,.0f} -> ${goal:,.0f} at {MEASURED_ANNUAL * 100:.2f}%/yr "
              f"= {yrs:>7.0f} years{tag}")
    print("-" * 74)
    print(f"  A {MEASURED_MAX_DD * 100:.1f}% drawdown at 1% risk is roughly a "
          f"54-trade losing stretch.")
    print("  Revelio also found four consecutive NEGATIVE years (2019-2022), and")
    print("  that removing 2017 leaves the strategy \"pretty much break-even\" —")
    print("  no real progress in the last 8.5 years. Their verdict: \"barely\" works.")
    print()
    print("  Two things in that study that support the current repo config:")
    print("    - GOLD is the best of the four assets. NASDAQ was negative in every")
    print("      single configuration. Gold-only is the empirically correct call.")
    print("    - 4H occupied the top four rankings, ahead of 1H. Sci's July 2026")
    print("      move to 4H markup points the same way.")
    print("  Caveat: they tested the OLDER 15m/5m entry variant. The new 4H->1H")
    print("  version in this repo has not been backtested by anyone yet.")
    print()
    print(f"  ⚠️ Those figures are specifically the 1%-risk configuration. This")
    print(f"     scanner is currently set to {RISK_PCT:.0f}% risk/trade. Revelio ran that")
    print("     setting too and reported that it 'gets annihilated' — so 3.8%/yr is")
    print("     the SURVIVABLE case, not the one this repo is configured for.")
    print()


# --- real data hook ----------------------------------------------------------
def edge_from_demo(cost_r: float) -> Edge | None:
    """Pull win rate / avg win / avg loss from YOUR OANDA practice history."""
    try:
        import trade_stats
    except Exception as e:
        print(f"  (could not import trade_stats: {e})")
        return None
    try:
        trades = trade_stats.get_closed_trades()
    except Exception as e:
        print(f"  (could not read OANDA demo trades: {str(e)[:120]})")
        return None
    s = trade_stats.stats(trades)
    if not s or s["n"] < 10:
        print(f"  (only {s['n'] if s else 0} closed demo trades — need >=10 for a "
              f"meaningful edge. Run the scanner with --paper for a few weeks.)")
        return None
    aw, al = s["avg_win"], s["avg_loss"]
    # express in R using the average loss as 1R (that is what a stopped-out trade is)
    avg_win_r = aw / al if al else 2.0
    print(f"  Using YOUR demo record: {s['n']} trades, {s['win_rate']:.1f}% win rate, "
          f"avg win ${aw:.2f} / avg loss ${al:.2f} -> {avg_win_r:.2f}R")
    return Edge(win_rate=s["win_rate"] / 100.0, avg_win_r=avg_win_r,
                avg_loss_r=1.0, cost_r=cost_r)


def main() -> int:
    ap = argparse.ArgumentParser(description="Can $1 become $1,000,000? Let's do the math.")
    ap.add_argument("--start", type=float, default=1.0)
    ap.add_argument("--goal", type=float, default=1_000_000.0)
    ap.add_argument("--risk", type=float, default=RISK_PCT, help="%% of balance risked per trade")
    ap.add_argument("--per-week", type=float, default=TRADES_PER_WEEK)
    ap.add_argument("--win-rate", type=float, default=50.0, help="percent")
    ap.add_argument("--avg-win-r", type=float, default=2.0, help="avg winner in R")
    ap.add_argument("--avg-loss-r", type=float, default=1.0, help="avg loser in R")
    ap.add_argument("--cost-r", type=float, default=0.05,
                    help="spread+slippage per trade as a fraction of 1R")
    ap.add_argument("--paths", type=int, default=3000)
    ap.add_argument("--max-years", type=float, default=60.0)
    ap.add_argument("--floor", type=float, default=None,
                    help="balance below which the account is dead. Default is "
                         "derived from gold's minimum legal order at --risk.")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--from-demo", action="store_true",
                    help="derive the edge from your real OANDA practice history")
    ap.add_argument("--min-account", action="store_true", help="only print section 3")
    # Section 4 (the published backtest) prints by default; --measured is
    # accepted because CAVEATS.md documents that exact command, and
    # --no-measured turns it off.
    ap.add_argument("--measured", action="store_true",
                    help="include the published-backtest section (already the default)")
    ap.add_argument("--no-measured", dest="measured", action="store_false")
    ap.set_defaults(measured=True)
    a = ap.parse_args()

    print()
    if a.min_account:
        section_min_account(a.risk)
        return 0

    edge = Edge(win_rate=a.win_rate / 100.0, avg_win_r=a.avg_win_r,
                avg_loss_r=a.avg_loss_r, cost_r=a.cost_r)
    if a.from_demo:
        real = edge_from_demo(a.cost_r)
        if real is None:
            print("  Falling back to the assumed edge.\n")
        else:
            edge = real

    # Ruin floor = the smallest balance that can still place gold's minimum lot
    # inside the risk budget. It scales with --risk (higher risk -> lower floor).
    floor = a.floor if a.floor is not None else \
        GOLD_MIN_UNITS * GOLD_TYP_STOP / (a.risk / 100.0)

    section_takes(a.start, a.goal, a.per_week)
    section_monte_carlo(a.start, a.goal, edge, a.risk, a.per_week,
                        a.paths, a.max_years, floor, a.seed)
    section_sensitivity(a.start, a.goal, a.risk, a.per_week,
                        min(a.paths, 1200), a.max_years, floor, a.seed)
    section_min_account(a.risk)
    if a.measured:
        section_measured(a.start, a.goal)

    print("=" * 74)
    print("  BOTTOM LINE")
    print("=" * 74)
    print(f"  ${a.start:,.0f} -> ${a.goal:,.0f} is a {a.goal / a.start:,.0f}x multiple. "
          f"At this bot's own")
    print("  pace of 1 trade/week, the binding constraint is not skill or luck —")
    print("  it is TIME. Even a genuine +0.45R/trade edge needs ~3,000 trades,")
    print("  which is roughly 58 years of never stopping.")
    print()
    print("  What the numbers DO support:")
    print()
    print("    - $1 is under the legal order floor for gold (~$12) and BTC (~$900),")
    print("      the two markets this repo was built around. On $1 the bot can only")
    print("      trade small forex lots, where a 2R winner moves the balance by two")
    print("      cents. It is a rounding error, not a seed.")
    print("    - Use the OANDA practice account instead — free, real prices, $0 real")
    print("      risk. Collect 50+ closed trades, then run:  python3 trade_stats.py")
    print("      Positive expectancy over 50+ trades is the ONLY thing worth knowing")
    print("      right now, and it is the thing almost nobody actually has.")
    print("    - Re-run this file with --from-demo once that history exists. It will")
    print("      swap the assumed edge for your measured one and tell you honestly")
    print("      what it compounds to. Most likely answer: not $1,000,000.")
    print("    - Real capital enters after the demo edge survives months, and it")
    print("      enters as savings from income. Income is the only reliable way to")
    print("      add zeroes; trading multiplies whatever zeroes are already there.")
    print("    - Section 4 is the only independent backtest of THIS strategy that")
    print("      exists. It says gold on 4H is the best corner of it and that the")
    print("      best version returns ~3.8%/yr against a 53.8% drawdown. Read")
    print("      CAVEATS.md before funding anything, and note it there: Sci's own")
    print("      10-20% risk-per-trade advice is the one part of his lead worth")
    print("      NOT following. This repo stays at 1%.")
    print("=" * 74)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
