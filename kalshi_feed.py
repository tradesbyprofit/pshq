"""
kalshi_feed.py — Read-only Kalshi market-data client (PUBLIC, no auth needed).

Derives the crowd's implied MEDIAN price for a BTC/Gold event from the cleanest
source: the cumulative "price >= strike" tail markets (yes_price = P(price >= strike)).
The median = strike where that probability crosses 50%. This is robust when those
markets exist and are monotonic; otherwise it reports "illiquid" rather than guess.

Kalshi crypto settles on CF Benchmarks reference rates.
"""
from __future__ import annotations
import urllib.request, json
from typing import Optional

BASE = "https://api.elections.kalshi.com/trade-api/v2"

SERIES = {
    "BTCUSD": {"15m": "KXBTC15M", "hourly": "KXBTC", "daily": "BTC", "weekly": "KXBTCMAXW"},
    "XAUUSD": {"15m": "KXGOLD15M", "hourly": "KXGOLDH", "daily": "KXGOLD", "weekly": "KXGOLDW"},
}
DEFAULT_TF = {"BTCUSD": "hourly", "XAUUSD": "weekly"}


def _get(path: str, limit: int = 100) -> dict:
    url = f"{BASE}{path}" + ("&" if "?" in path else "?") + f"limit={limit}"
    return json.load(urllib.request.urlopen(url, timeout=25))


def _yes_price(m) -> Optional[float]:
    last = float(m.get("last_price_dollars") or 0)
    if last > 0:
        return last
    b = float(m.get("yes_bid_dollars") or 0)
    a = float(m.get("yes_ask_dollars") or 0)
    if b > 0 and a > 0:
        return (b + a) / 2
    if a > 0:
        return a
    return None


def _event_markets(series_ticker: str):
    d = _get(f"/markets?series_ticker={series_ticker}&status=open")
    by_event = {}
    for m in d.get("markets", []):
        by_event.setdefault(m["event_ticker"], []).append(m)
    if not by_event:
        return "", []
    ev = min(by_event, key=lambda e: min((m.get("close_time") or "9") for m in by_event[e]))
    return ev, by_event[ev]


def implied_median(series_ticker: str) -> dict:
    """Median from cumulative 'price >= strike' markets (strike_type=='greater').
    yes_price of such a market = P(price >= strike); crossing 0.5 = the median."""
    ev, ms = _event_markets(series_ticker)
    base = {"event": ev, "close": (min((m.get("close_time") or "9") for m in ms) if ms else ""),
            "total_markets": len(ms)}
    if not ms:
        return {**base, "priced_markets": 0, "median": None, "note": "no open markets"}
    cdf = []  # (strike, P(>= strike))
    for m in ms:
        if m.get("strike_type") != "greater":
            continue
        p = _yes_price(m)
        fl = float(m.get("floor_strike") or 0)
        if p is not None and fl > 0:
            cdf.append((fl, p))
    priced = len(cdf)
    if priced < 4:                       # need a real monotonic CDF to interpolate
        return {**base, "priced_markets": priced, "median": None,
                "note": "illiquid (too few cumulative '≥strike' priced markets)"}
    cdf.sort()                           # ascending strike
    median = None
    for i in range(1, len(cdf)):
        s0, p0 = cdf[i-1]; s1, p1 = cdf[i]
        if p0 == p1:
            continue
        if (p0 - 0.5) * (p1 - 0.5) <= 0:   # crosses 50%
            median = s0 + (p0 - 0.5) / (p0 - p1) * (s1 - s0)
            break
    conf = "high" if priced >= 8 else "low"
    return {**base, "priced_markets": priced, "median": median,
            "note": ("ok" if median else "no 50% crossing") + f" ({conf} conf, {priced} cdf pts)"}


def confluence(symbol: str, spot: float, timeframe: str = None) -> dict:
    tf = timeframe or DEFAULT_TF.get(symbol, "daily")
    series = SERIES.get(symbol, {}).get(tf)
    if not series:
        return {"symbol": symbol, "lean": "unknown", "note": f"no Kalshi series for {symbol}/{tf}"}
    info = implied_median(series)
    med = info.get("median")
    res = {"symbol": symbol, "timeframe": tf, "spot": spot,
           "kalshi_event": info.get("event"), "resolves": info.get("close"),
           "priced_markets": info.get("priced_markets"), "median": med, "note": info.get("note")}
    if med is None:
        res["lean"] = "n/a"
        return res
    d = (med - spot) / spot * 100
    res["median_vs_spot_pct"] = round(d, 3)
    res["lean"] = "bullish" if d > 0.15 else ("bearish" if d < -0.15 else "neutral")
    return res


if __name__ == "__main__":
    from feeds import CCXTDataFeed
    f = CCXTDataFeed()
    for sym, tf in [("XAUUSD", "weekly"), ("XAUUSD", "hourly"),
                    ("BTCUSD", "hourly"), ("BTCUSD", "15m")]:
        try:
            spot = f.candles(sym, "1H", 5)[-1].c
            c = confluence(sym, spot, tf)
            print(f"\n{sym} ({tf}) spot {spot:.2f} | event {c.get('kalshi_event')} resolves {str(c.get('resolves'))[:16]}")
            print(f"  Kalshi median {c.get('median')} | priced {c.get('priced_markets')} | "
                  f"lean {c.get('lean')} Δ{c.get('median_vs_spot_pct','n/a')}% | {c.get('note')}")
        except Exception as e:
            print(f"\n{sym} ({tf}): {e}")
