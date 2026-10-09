"""
icc_engine.py — Trades By Sci "ICC" method, codified as a deterministic engine.

ICC = Indication -> Correction -> Continuation.
Pure price action, no indicators. Detects swing structure on a higher timeframe,
waits for an indication (a swing break), waits for the correction, and only emits
a SETUP when the continuation confirms on the lower timeframe (the "second time
around"). If any rule fails -> NO_TRADE. This implements the "1-2 trades/week,
never chase" philosophy: the default is to do nothing.

Data-source agnostic: feed it OHLC candles for an HTF (1H/4H) and an LTF (15M/5M)
via the `fetch_candles` interface you wire up later (TradingView, broker, CCXT...).

This is educational/tooling code, NOT financial advice. Validate thoroughly on
DEMO before any live use. (The method's own author insists on demo first.)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Callable, Dict, Tuple
import datetime as dt

# ---------------------------------------------------------------------------
# 1. Core data types
# ---------------------------------------------------------------------------
@dataclass
class Candle:
    time: dt.datetime
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0

    @property
    def body(self) -> float:
        return abs(self.c - self.o)

    @property
    def bullish(self) -> bool:
        return self.c >= self.o


class Direction(Enum):
    BULL = "bull"
    BEAR = "bear"
    NONE = "none"


class SwingType(Enum):
    HIGH = "high"
    LOW = "low"


@dataclass
class Swing:
    index: int            # candle index where confirmed
    time: dt.datetime
    price: float          # body-close price of the pivot
    kind: SwingType
    hh: Optional[bool] = None   # higher-high than previous swing high?
    hl: Optional[bool] = None   # higher-low ...
    lh: Optional[bool] = None
    ll: Optional[bool] = None


# ---------------------------------------------------------------------------
# 2. Swing detection (body-close fractals, left/right window)
# ---------------------------------------------------------------------------
def detect_swings(candles: List[Candle], left: int = 2, right: int = 2,
                  use_body: bool = True) -> List[Swing]:
    """
    A swing high pivot at i: the body-close of candle i is the highest among
    [i-left, i+right]. Swing low = lowest. Sci marks body closes ("closed deals"),
    so use_body=True by default. right>0 means a swing is only *confirmed* after
    `right` candles have closed (realistic, no lookahead in live mode).
    """
    vals = [c.c if use_body else c.h if False else c.c for c in candles]
    highs = [c.h for c in candles]
    lows = [c.l for c in candles]
    pivot_price = [c.c for c in candles] if use_body else [c.h for c in candles]
    # For highs we still want to confirm the candle's high was the extreme, but
    # mark the body close as the level (Sci's rule). Use high for the *test*,
    # body close for the *price*.
    sw: List[Swing] = []
    n = len(candles)
    last_high: Optional[Swing] = None
    last_low: Optional[Swing] = None
    for i in range(left, n - right):
        # swing HIGH test (use candle highs for the comparison)
        is_high = all(highs[i] >= highs[k] for k in range(i - left, i + right + 1) if k != i)
        is_low = all(lows[i] <= lows[k] for k in range(i - left, i + right + 1) if k != i)
        if is_high:
            price = candles[i].c  # body close as the level
            hh = (last_high is not None and price > last_high.price)
            s = Swing(i, candles[i].time, price, SwingType.HIGH,
                      hh=hh, lh=(not hh and last_high is not None) or None)
            sw.append(s)
            last_high = s
        elif is_low:
            price = candles[i].c
            ll = (last_low is not None and price < last_low.price)
            s = Swing(i, candles[i].time, price, SwingType.LOW,
                      ll=ll, hl=(not ll and last_low is not None) or None)
            sw.append(s)
            last_low = s
    # Collapse adjacent same-kind pivots before returning. The `>=`/`<=` tests
    # above register BOTH candles when two share an extreme, and equal highs /
    # equal lows are common on real 4H gold (they are exactly the liquidity this
    # method hunts). Left in, the duplicate makes the later, less extreme pivot
    # look like a reversal — so a clean HH+HL uptrend read as LH+HL and
    # classify_trend() returned NONE. The bot then refused valid setups with
    # "HTF is ranging/consolidating". See collapse_runs() and test_no_trade_zone.
    return collapse_runs(sw)


# ---------------------------------------------------------------------------
# 3. Trend / structure classification
# ---------------------------------------------------------------------------
def classify_trend(swings: List[Swing], lookback: int = 6) -> Direction:
    """
    Look at the most recent swing highs & lows to decide trend.
    HH+HL -> BULL, LH+LL -> BEAR, else NONE (consolidation / unclear).
    """
    highs = [s for s in swings if s.kind == SwingType.HIGH][-lookback:]
    lows = [s for s in swings if s.kind == SwingType.LOW][-lookback:]
    if len(highs) < 2 or len(lows) < 2:
        return Direction.NONE
    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price
    if hh and hl:
        return Direction.BULL
    if lh and ll:
        return Direction.BEAR
    return Direction.NONE


# ---------------------------------------------------------------------------
# 3.5  No-trade zone  —  "MY ICC UPDATE", Trades By Sci, 2026-07-30
# ---------------------------------------------------------------------------
@dataclass
class NoTradeZone:
    high: float                 # the swing high price is currently under
    low: float                  # the opposite swing that CREATED that high
    high_swing: Swing
    low_swing: Swing
    inside: bool                # price between the two -> no trade
    side: Direction             # BULL above high, BEAR below low, NONE inside

    @property
    def width(self) -> float:
        return self.high - self.low


def collapse_runs(swings: List[Swing]) -> List[Swing]:
    """Collapse adjacent same-kind swings into the one true structural extreme.

    detect_swings() tests pivots with `>=` / `<=`, so two candles that share an
    extreme BOTH register as swings. That is not a corner case here: *equal
    highs and equal lows* are precisely what this method hunts for as liquidity,
    and they are common on real 4H gold.

    Left uncollapsed they cause two concrete failures:
      - a run of two highs in a row is not a bracket, so no_trade_zone() bails
        out and the gate silently stops gating;
      - the LATER, lower high is treated as the swing high, so the indication
        level and the stop sit inside the real structure.

    Keeps whichever swing in the run holds the more extreme price, so index,
    time and price stay internally consistent.
    """
    out: List[Swing] = []
    for s in swings:
        if out and out[-1].kind == s.kind:
            prev = out[-1]
            more_extreme = (s.price > prev.price) if s.kind == SwingType.HIGH \
                else (s.price < prev.price)
            if more_extreme:
                out[-1] = s
        else:
            out.append(s)
    return out


def no_trade_zone(candles: List[Candle], swings: List[Swing]) -> Optional[NoTradeZone]:
    """Sci's 4H markup rule, verbatim from "MY ICC UPDATE" (2026-07-30):

        "current price is at 4,036. let me go up. okay, this is my high. mark.
         this high was created from here. okay, that's my low. ... If price is
         in between both of these, this means that this is a no trade zone."

    The zone is therefore a PAIR of adjacent swings: the most recent extreme,
    and the opposite swing that originated the move into it. Price inside the
    pair is a no-trade zone — "buyers and sellers are in control". A body close
    OUTSIDE it is the indication, and tells you which side has taken over:
    "once it breaks past something that lets you know that price has full
    control until it reaches that level again."

    Body closes only, per "I use candle closes when I'm marking up because that
    means to me it's a closed deal. A wick to me is price attempted to but
    failed to do so. I like when everything is certain."
    """
    if not candles:
        return None
    swings = collapse_runs(swings)
    if len(swings) < 2:
        return None
    last_close = candles[-1].c
    # The two most recent confirmed swings bracket current price: one extreme
    # and the swing that created it. (right>0 in detect_swings means these are
    # already confirmed by later closes, so there is no lookahead here.)
    a, b = swings[-2], swings[-1]
    if a.kind == b.kind:                      # two of a kind -> not a bracket
        return None
    hi, lo = (a, b) if a.kind == SwingType.HIGH else (b, a)
    # TOUCHING a level is not breaking it. Sci's trigger is a close PAST the
    # line: "The moment that price comes above this blue line, I press buy. The
    # moment price comes below this blue line, I press sell." A close sitting
    # exactly on the level is still inside the zone. (Strict `<` on both ends
    # used to misfile that case as BEAR.)
    if last_close > hi.price:
        inside, side = False, Direction.BULL
    elif last_close < lo.price:
        inside, side = False, Direction.BEAR
    else:
        inside, side = True, Direction.NONE
    return NoTradeZone(high=hi.price, low=lo.price, high_swing=hi, low_swing=lo,
                       inside=inside, side=side)


# ---------------------------------------------------------------------------
# 4. Indication detection (a swing was broken -> new extreme -> bias)
# ---------------------------------------------------------------------------
@dataclass
class Indication:
    direction: Direction          # BULL if swing high broken up, BEAR if swing low broken down
    broken_swing: Swing
    broken_level: float
    confirmed_at: Candle          # the candle that body-closed beyond the level
    target: float                 # origin to target = the broken swing's prior extreme region


def find_indication(candles: List[Candle], swings: List[Swing],
                    lookback: int = 10) -> Optional[Indication]:
    """
    The most recent swing high/low that price has body-closed beyond = an indication.
    Per Sci: "indications always create a new high or new low."
    """
    if not swings or not candles:
        return None
    last = candles[-1]
    # consider the most recent unbroken-then-broken swing high and swing low
    recent_highs = [s for s in swings if s.kind == SwingType.HIGH][-lookback:]
    recent_lows = [s for s in swings if s.kind == SwingType.LOW][-lookback:]

    bull = None
    if recent_highs:
        sh = recent_highs[-1]
        if last.c > sh.price:  # body close above swing high -> bullish indication
            # TP = the NEW HIGH the indication made (recent extreme close)
            target = max(c.c for c in candles[-lookback:])
            bull = Indication(Direction.BULL, sh, sh.price, last, target)
    bear = None
    if recent_lows:
        sl = recent_lows[-1]
        if last.c < sl.price:  # body close below swing low -> bearish indication
            # TP = the NEW LOW the indication made
            target = min(c.c for c in candles[-lookback:])
            bear = Indication(Direction.BEAR, sl, sl.price, last, target)
    # prefer the one whose confirmation is most recent / both can't be true long
    return bull or bear


# ---------------------------------------------------------------------------
# 5. Continuation confirmation on the LTF (the "second time around")
# ---------------------------------------------------------------------------
@dataclass
class Continuation:
    direction: Direction
    confirmed_at: Candle
    entry: float
    stop: float
    target: float
    note: str


def check_continuation(ltf_candles: List[Candle], indication: Indication,
                       max_correction_room: float = 0.0) -> Optional[Continuation]:
    """
    On the LTF, after the indication, we want the SECOND break back through the
    level (continuation), with internal structure flipping against the correction.

    For a BULL indication (above a swing high):
      - correction = pullback down; want a HL formed, then price body-closes back
        ABOVE that swing high level again = continuation.
    For a BEAR indication (below a swing low): mirror.

    Stop goes beyond the correction's extreme. Target = indication.target.
    """
    if not ltf_candles:
        return None
    level = indication.broken_level
    last = ltf_candles[-1]
    swings = detect_swings(ltf_candles, left=2, right=1)

    if indication.direction == Direction.BULL:
        # need a correction low (a swing low after the indication) then reclaim
        lows = [s for s in swings if s.kind == SwingType.LOW]
        if not lows:
            return None
        corr_low = min(s.price for s in lows)
        # continuation: last body closes above the broken swing-high level
        if last.c > level and last.bullish:
            entry = level
            stop = corr_low - max_correction_room
            if stop >= entry:
                return None  # invalid: stop above entry
            rr = (indication.target - entry) / (entry - stop)
            if rr < 1.0:
                return None  # poor R:R, skip (don't chase)
            return Continuation(Direction.BULL, last, entry, stop,
                                indication.target,
                                f"2nd-time reclaim of swing high {level:.2f}; R:R {rr:.2f}")

    elif indication.direction == Direction.BEAR:
        highs = [s for s in swings if s.kind == SwingType.HIGH]
        if not highs:
            return None
        corr_high = max(s.price for s in highs)
        if last.c < level and not last.bullish:
            entry = level
            stop = corr_high + max_correction_room
            if stop <= entry:
                return None
            rr = (entry - indication.target) / (stop - entry)
            if rr < 1.0:
                return None
            return Continuation(Direction.BEAR, last, entry, stop,
                                indication.target,
                                f"2nd-time reclaim of swing low {level:.2f}; R:R {rr:.2f}")
    return None


# ---------------------------------------------------------------------------
# 6. Session filter (London / New York for gold; always-on for BTC)
# ---------------------------------------------------------------------------
GOLD_SESSIONS_UTC = {
    # (start_hour_utc, end_hour_utc)
    "London": (7, 16),
    "NewYork": (12, 21),   # 12:00 UTC = 8am ET; NY bell 9:30 ET ~ 13:30 UTC
}
def in_session(symbol: str, when: dt.datetime) -> bool:
    s = symbol.upper()
    if "BTC" in s or "BTCUSD" in s:
        return True  # crypto 24/7
    # gold AND forex: only trade in London or New York (the method's volume windows)
    h = when.hour
    for _, (a, b) in GOLD_SESSIONS_UTC.items():
        if a <= h < b:
            return True
    return False


# ---------------------------------------------------------------------------
# 7. The top-level decision engine
# ---------------------------------------------------------------------------
@dataclass
class Signal:
    action: str               # "SETUP" or "NO_TRADE"
    symbol: str
    direction: Direction
    reason: str
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    rr: Optional[float] = None
    when: Optional[dt.datetime] = None
    checks: Dict[str, str] = field(default_factory=dict)


def evaluate(symbol: str,
             htf: List[Candle],
             ltf: List[Candle],
             when: Optional[dt.datetime] = None,
             min_rr: float = 1.0) -> Signal:
    """
    Run the full ICC checklist on (HTF markup + LTF entry) candles.
    Returns SETUP only when every rule passes; otherwise NO_TRADE with reasons.
    """
    when = when or (htf[-1].time if htf else dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    checks: Dict[str, str] = {}
    direction = Direction.NONE

    # A1. enough data
    if len(htf) < 20 or len(ltf) < 20:
        return Signal("NO_TRADE", symbol, Direction.NONE,
                      "insufficient candle history", when=when,
                      checks={"data": "need >=20 candles on HTF and LTF"})

    # A2. trend, not consolidation
    swings = detect_swings(htf)
    trend = classify_trend(swings)
    checks["htf_trend"] = trend.value
    if trend == Direction.NONE:
        return Signal("NO_TRADE", symbol, Direction.NONE,
                      "HTF is ranging/consolidating -> no trade", when=when, checks=checks)

    # A2b. NO-TRADE ZONE (MY ICC UPDATE, 2026-07-30). "your setup should always
    # start out of a no trade zone." Price bracketed by the two most recent
    # swings = buyers AND sellers in control = stand aside. A 4H body close
    # outside the bracket is what flips it into an indication.
    zone = no_trade_zone(htf, swings)
    if zone is None:
        checks["no_trade_zone"] = "cannot bracket price with two adjacent swings"
    elif zone.inside:
        checks["no_trade_zone"] = f"INSIDE {zone.low:.2f}-{zone.high:.2f} -> wait"
        return Signal("NO_TRADE", symbol, Direction.NONE,
                      f"price inside no-trade zone {zone.low:.2f}-{zone.high:.2f} "
                      f"(buyers and sellers both in control) -> wait for a 4H close out",
                      when=when, checks=checks)
    else:
        checks["no_trade_zone"] = (f"OUTSIDE {zone.side.value} "
                                   f"({zone.low:.2f}-{zone.high:.2f})")

    # A3. indication present (a swing broken, new extreme)
    ind = find_indication(htf, swings)
    if ind is None:
        checks["indication"] = "none — NO TRADE ZONE (high/low but no break)"
        return Signal("NO_TRADE", symbol, Direction.NONE,
                      "no indication (swing not broken) -> NO TRADE ZONE",
                      when=when, checks=checks)
    checks["indication"] = f"{ind.direction.value} @ {ind.broken_level:.2f}"
    direction = ind.direction

    # consistency: indication must align with HTF trend
    if direction != trend:
        checks["alignment"] = f"indication {direction.value} != trend {trend.value}"
        return Signal("NO_TRADE", symbol, direction,
                      "indication contradicts HTF trend -> wait", when=when, checks=checks)
    checks["alignment"] = "ok"

    # B. session
    ok_session = in_session(symbol, when)
    checks["session"] = "in-session" if ok_session else "out-of-session (gold)"
    # don't hard-block out-of-session; flag it (entry timing matters for gold)
    if not ok_session:
        return Signal("NO_TRADE", symbol, direction,
                      "outside London/NY session (gold) -> wait", when=when, checks=checks)

    # C. continuation on LTF (the second-time confirmation)
    cont = check_continuation(ltf, ind)
    if cont is None:
        checks["continuation"] = "not confirmed yet (still correcting / R:R too low)"
        return Signal("NO_TRADE", symbol, direction,
                      "no continuation confirmation yet -> WAIT, do not chase",
                      when=when, checks=checks)
    checks["continuation"] = cont.note

    rr = (abs(cont.target - cont.entry) / abs(cont.entry - cont.stop)) if cont else None
    checks["rr"] = f"{rr:.2f}" if rr else "n/a"
    if rr is not None and rr < min_rr:
        return Signal("NO_TRADE", symbol, direction,
                      f"R:R {rr:.2f} below min {min_rr} -> skip", when=when, checks=checks)

    return Signal("SETUP", symbol, direction,
                  "All ICC checks passed: Indication + Correction + Continuation.",
                  entry=cont.entry, stop=cont.stop, target=cont.target,
                  rr=rr, when=when, checks=checks)


# ---------------------------------------------------------------------------
# 8. Demo / self-test on synthetic data (sanity check the logic)
# ---------------------------------------------------------------------------
def _demo():
    import random
    random.seed(7)
    t0 = dt.datetime(2026, 7, 1, 9, 30)

    def leg(candles, a, b, n, jitter=2.0):
        """append n candles smoothly moving price from a to b (body closes)."""
        for k in range(1, n + 1):
            frac = k / n
            c = a + (b - a) * frac + random.uniform(-jitter, jitter)
            o = c - (b - a) / n * 0.3
            candles.append(Candle(
                t0 + dt.timedelta(hours=len(candles)), o,
                max(o, c) + random.uniform(0, 1.5),
                min(o, c) - random.uniform(0, 1.5), c))

    htf: List[Candle] = []
    # clean stair-step uptrend: each high higher, each pullback low higher (HL)
    leg(htf, 2000, 2050, 6)   # up to high1
    leg(htf, 2050, 2025, 4)   # pullback to HL
    leg(htf, 2025, 2068, 6)   # up to HH
    leg(htf, 2068, 2042, 4)   # pullback to HL
    leg(htf, 2042, 2090, 6)   # up to HH (last swing high)
    leg(htf, 2090, 2075, 3)   # small pullback
    leg(htf, 2075, 2102, 3)   # break to new high -> INDICATION

    swing_high = max(c.c for c in htf[-14:-3])  # the recently-broken swing high
    price = htf[-1].c

    # LTF: deeper correction down, then body-close reclaim above swing_high
    ltf: List[Candle] = []
    def ltf_leg(a, b, n, jitter=1.2):
        for k in range(1, n + 1):
            frac = k / n
            c = a + (b - a) * frac + random.uniform(-jitter, jitter)
            o = c - (b - a) / n * 0.3
            ltf.append(Candle(
                t0 + dt.timedelta(minutes=15 * len(ltf)), o,
                max(o, c) + random.uniform(0, 0.8),
                min(o, c) - random.uniform(0, 0.8), c))
    ltf_leg(price, price - 22, 14)            # correction down
    ltf_leg(price - 22, swing_high + 3, 10)   # reclaim above swing_high -> CONTINUATION

    sig = evaluate("XAUUSD", htf, ltf, when=ltf[-1].time)
    print("=== DEMO SIGNAL ===")
    print(f"action    : {sig.action}")
    print(f"direction : {sig.direction.value}")
    print(f"reason    : {sig.reason}")
    if sig.entry:
        print(f"entry     : {sig.entry:.2f}")
        print(f"stop      : {sig.stop:.2f}")
        print(f"target    : {sig.target:.2f}")
        print(f"R:R       : {sig.rr:.2f}")
    print("checks    :", sig.checks)


if __name__ == "__main__":
    _demo()
