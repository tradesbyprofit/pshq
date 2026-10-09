"""
watch.py — "What is the bot eyeing right now?" A live read across the watchlist:
trend, the key swing levels price is sitting between, whether an indication is
already in, and how close price is to a break. Run anytime.
"""
import os, datetime as dt
from icc_engine import detect_swings, classify_trend, find_indication, Direction, in_session
from oanda_feed import OANDADataFeed

WATCH = ["XAUUSD"]          # GOLD ONLY — see scanner.py
HTF = "4H"                  # MY ICC UPDATE (2026-07-30): markup moved 1H -> 4H
feed = OANDADataFeed()


def nearest_above(values, price):
    above = [v for v in values if v > price]
    return min(above) if above else None

def nearest_below(values, price):
    below = [v for v in values if v < price]
    return max(below) if below else None


def read(sym):
    h = feed.candles(sym, HTF, 120)
    price = h[-1].c
    swings = detect_swings(h)
    highs = [s.price for s in swings if s.kind.value == "high"]
    lows = [s.price for s in swings if s.kind.value == "low"]
    trend = classify_trend(swings)
    ind = find_indication(h, swings)
    res = nearest_above(highs, price)        # nearest swing high above (bull break target)
    sup = nearest_below(lows, price)         # nearest swing low below (bear break target)

    # status
    if ind:
        status = f"INDICATION ({ind.direction.value}) — bias set, waiting for correction+continuation"
    elif trend == Direction.NONE:
        status = "ranging / no-trade zone (no clean structure)"
    elif res and abs(res - price) / price < 0.0015:
        status = f"coiling just under resistance {res:.5f} — a break = bullish indication"
    elif sup and abs(sup - price) / price < 0.0015:
        status = f"coiling just above support {sup:.5f} — a break = bearish indication"
    else:
        status = "mid-range, no level nearby — waiting"

    sess = "in London/NY" if in_session(sym, h[-1].time) else "off-session (Asian/weekend)"
    return sym, price, trend.value, res, sup, status, sess


print(f"=== LIVE READ @ {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC ===\n")
for sym in WATCH:
    try:
        s, price, trend, res, sup, status, sess = read(sym)
        print(f"{s}  ({sess})")
        print(f"   price : {price:.5f}   trend: {trend}")
        print(f"   res   : {res:.5f}  (bull break)" if res else "   res   : none above")
        print(f"   sup   : {sup:.5f}  (bear break)" if sup else "   sup   : none below")
        print(f"   => {status}\n")
    except Exception as e:
        print(f"{sym}: {str(e)[:60]}\n")
