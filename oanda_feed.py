"""
oanda_feed.py — OANDA v20 (Practice/Demo) integration for the ICC bot.

Provides:
  - OANDADataFeed : live spot candles for XAU_USD (gold) and BTC_USD, no proxy.
                   Same `candles(symbol, timeframe, limit)` interface as feeds.py.
  - OANDAPaperBroker : optional auto paper-execution of A+ setups on the demo
                       account (risk-based sizing, SL+TP attached). OFF by default.

DEMO ONLY. Practice environment (api-fxpractice.oanda.com). Never use a live token.

ENV VARS:
  OANDA_API_TOKEN  -> your practice account API token
  OANDA_ACCOUNT_ID -> e.g. 101-001-12345678-001
"""
from __future__ import annotations
import math, os, json, urllib.request, urllib.parse, datetime as dt
from typing import List, Optional
from icc_engine import Candle, Signal, Direction

BASE = "https://api-fxpractice.oanda.com/v3"   # PRACTICE/DEMO only
SYMBOL_MAP = {"XAUUSD": "XAU_USD", "BTCUSD": "BTC_USD", "BTC": "BTC_USD"}
TF_MAP = {"1H": "H1", "4H": "H4", "15M": "M15", "5M": "M5"}

# OANDA lot rules. Forex must be WHOLE units (1 unit = 1 unit of base currency);
# metals/crypto accept fractional sizes.
#
# NOTE: "is this forex?" cannot be answered by counting letters. XAU_USD and
# BTC_USD are also 3+3, and the old letter-count test classified them as forex
# and integer-rounded their size — so any gold position under 0.5 units (about
# $600 of risk budget) submitted "0" and OANDA rejected it. Identify forex by
# currency whitelist instead: OANDA's pairs are fiat x fiat, everything else
# (XAU, XAG, BTC, ETH...) is fractional.
FIAT = {
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SGD", "HKD",
    "DKK", "NOK", "SEK", "PLN", "CZK", "HUF", "RON", "TRY", "ZAR", "MXN",
    "ILS", "SAR", "AED", "CNH", "CNY", "INR", "KRW", "TWD", "THB", "MYR",
    "PHP", "IDR", "RUB", "BRL", "CLP", "COP", "PEN", "ARS",
}
MIN_FX_UNITS = 1
MIN_OTHER_UNITS = 0.01   # verify against /instruments -> minimumTradeSize

# Fallback quote-currency -> USD rates if the live lookup fails (weekend
# maintenance, permissions). Approximate on purpose: sizing still lands inside
# a few percent of the risk budget instead of being off by ~150x.
QUOTE_USD_FALLBACK = {
    "USD": 1.0, "JPY": 1 / 150.0, "CHF": 1 / 0.90, "CAD": 1 / 1.35,
    "GBP": 1 / 0.78, "EUR": 1 / 0.92, "AUD": 1 / 1.50, "NZD": 1 / 1.65,
    "SGD": 1 / 1.35, "HKD": 1 / 7.80, "MXN": 1 / 18.0, "ZAR": 1 / 18.5,
    "PLN": 1 / 4.00, "SEK": 1 / 10.5, "NOK": 1 / 10.5, "TRY": 1 / 32.0,
    "CNH": 1 / 7.20, "CZK": 1 / 23.0, "HUF": 1 / 360.0, "THB": 1 / 33.0,
}
_QUOTE_CACHE: dict = {}


def is_forex(instrument: str) -> bool:
    """True only for fiat-vs-fiat pairs. XAU_USD / BTC_USD are NOT forex."""
    parts = instrument.upper().split("_")
    return len(parts) == 2 and parts[0] in FIAT and parts[1] in FIAT


def quote_to_usd(instrument: str) -> float:
    """USD value of 1 unit of this instrument's QUOTE currency.

    Position P/L is paid in the quote currency, so risk-based sizing must
    convert the stop distance into dollars *before* dividing. Skipping this
    (the old behaviour) under-risked JPY-quoted pairs by ~150x: a "1%" trade
    on USD_JPY actually risked 0.0067%.

    Cached per quote currency for the life of the process.
    """
    parts = instrument.split("_")
    quote = parts[1].upper() if len(parts) == 2 else "USD"
    if quote == "USD":
        return 1.0
    if quote in _QUOTE_CACHE:
        return _QUOTE_CACHE[quote]

    rate = None
    # OANDA lists JPY as USD_JPY, not JPY_USD — try both directions.
    for inst, invert in ((f"{quote}_USD", False), (f"USD_{quote}", True)):
        try:
            r = _req(f"/instruments/{inst}/candles?granularity=M5&count=1&price=M")
            candles = r.get("candles") or []
            if candles:
                rate = float(candles[-1]["mid"]["c"])
                if invert:
                    rate = 1.0 / rate
                break
        except Exception:
            continue

    if not rate or rate <= 0:
        rate = QUOTE_USD_FALLBACK.get(quote)
    if not rate:
        raise ValueError(f"cannot convert quote currency {quote} to USD "
                         f"— add it to QUOTE_USD_FALLBACK")
    _QUOTE_CACHE[quote] = rate
    return rate


def _round_half_away(x: float) -> int:
    """Round half away from zero. Python's round() is banker's rounding, so
    round(0.5) == 0 — which used to submit 0-unit orders that OANDA rejects."""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def legal_units(instrument: str, units: float) -> float:
    """Round a signed unit count to the instrument's lot rules."""
    sign = -1.0 if units < 0 else 1.0
    mag = abs(units)
    if is_forex(instrument):
        return sign * _round_half_away(mag)
    return sign * round(mag, 2)


def size_position(instrument: str, balance: float, risk_fraction: float,
                  entry: float, stop: float) -> dict:
    """Risk-based sizing done correctly.

    Returns a dict with the signed `units` to submit plus the diagnostics the
    caller needs to REJECT a trade instead of firing a bad order:
      too_small  -> the smallest legal order risks more than the budget, so
                    honouring risk_fraction is impossible at this balance.
      clamped    -> rounding moved the actual risk off the target.

    units = (balance * risk_fraction) / (stop_distance * quote_to_usd)
    """
    sl_dist = abs(entry - stop)
    if sl_dist <= 0:
        return {"units": 0.0, "too_small": True, "reason": "invalid SL distance",
                "risk_usd": 0.0, "risk_pct": 0.0}

    q2usd = quote_to_usd(instrument)
    budget = balance * risk_fraction
    raw = budget / (sl_dist * q2usd)
    min_units = MIN_FX_UNITS if is_forex(instrument) else MIN_OTHER_UNITS

    if raw < min_units:
        # Smallest legal order would risk more than the budget -> don't trade.
        actual = min_units * sl_dist * q2usd
        return {"units": 0.0, "too_small": True, "raw_units": raw,
                "min_units": min_units, "risk_usd": actual,
                "risk_pct": (actual / balance * 100.0) if balance else float("inf"),
                "reason": (f"balance ${balance:.2f} too small: {min_units} unit(s) "
                           f"risks ${actual:.2f} "
                           f"({actual / balance * 100:.1f}% > {risk_fraction * 100:.1f}% budget)")}

    units = legal_units(instrument, raw)
    if units == 0:                       # rounding collapsed a fractional lot
        units = min_units if raw > 0 else -min_units
    risk_usd = abs(units) * sl_dist * q2usd
    return {"units": float(units), "too_small": False, "raw_units": raw,
            "clamped": abs(abs(units) - raw) > 1e-9,
            "risk_usd": risk_usd,
            "risk_pct": (risk_usd / balance * 100.0) if balance else float("inf"),
            "quote_to_usd": q2usd, "sl_dist": sl_dist}


def resolve_instrument(symbol: str) -> str:
    """'EURUSD' -> 'EUR_USD'; honors explicit SYMBOL_MAP (XAU/BTC) first."""
    s = symbol.upper().replace("/", "").replace("-", "")
    if s in SYMBOL_MAP:
        return SYMBOL_MAP[s]
    # generic 6-letter forex pair: split into CCC_CCC
    if len(s) == 6 and s.isalpha():
        return f"{s[:3]}_{s[3:]}"
    return s


def fmt_units(instrument: str, units: float) -> str:
    """Forex -> integer units; metals/crypto -> 2 decimals."""
    return str(int(legal_units(instrument, units))) if is_forex(instrument) \
        else f"{legal_units(instrument, units):.2f}"


# OANDA rejects a price carrying more decimals than the instrument's
# displayPrecision, so metals/crypto need their own table (the old code gave
# every "_" instrument 5 places, which is wrong for XAU_USD and BTC_USD).
NON_FX_PRICE_PRECISION = {"XAU_USD": 3, "XAG_USD": 3, "BTC_USD": 1, "ETH_USD": 2}


def price_precision(instrument: str) -> int:
    """Decimal places for price fields: JPY pairs 3, other FX 5, metals/crypto per table."""
    inst = instrument.upper()
    if not is_forex(inst):
        return NON_FX_PRICE_PRECISION.get(inst, 2)
    return 3 if inst.endswith("_JPY") else 5



def _req(path: str, method="GET", token=None, body=None):
    token = token or os.getenv("OANDA_API_TOKEN")
    if not token:
        raise RuntimeError("Set OANDA_API_TOKEN env var.")
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    q = ""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept-Datetime-Format": "RFC3339",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # surface OANDA's actual error message instead of a generic code
        try:
            body = json.load(e)
            msg = body.get("errorMessage") or body.get("message") or str(body)[:200]
        except Exception:
            msg = e.read().decode()[:200] if e.fp else str(e)
        raise RuntimeError(f"OANDA {e.code} {e.reason}: {msg}") from None


class OANDADataFeed:
    """Live spot candles from OANDA practice. Drop-in for feeds.CCXTDataFeed."""
    def __init__(self, verbose=False):
        if not os.getenv("OANDA_API_TOKEN"):
            raise RuntimeError("Set OANDA_API_TOKEN env var.")
        self.verbose = verbose

    def candles(self, symbol: str, timeframe: str, limit: int = 120) -> List[Candle]:
        inst = resolve_instrument(symbol)
        g = TF_MAP.get(timeframe.upper(), timeframe.upper())
        path = f"/instruments/{inst}/candles?price=M&granularity={g}&count={limit}"
        data = _req(path)
        out = []
        for c in data.get("candles", []):
            if not c.get("complete"):
                continue
            m = c["mid"]
            t = c["time"].split(".")[0]  # drop fractional seconds
            out.append(Candle(
                dt.datetime.fromisoformat(t),
                float(m["o"]), float(m["h"]), float(m["l"]), float(m["c"]),
                float(c.get("volume", 0))))
        if self.verbose and out:
            print(f"  [oanda] {inst} {timeframe}: {len(out)} candles, "
                  f"last close {out[-1].c:.2f} @ {out[-1].time:%Y-%m-%d %H:%M} UTC")
        if not out:
            raise RuntimeError(f"No candles for {inst} {g} (check instrument/permissions)")
        return out


class OANDAPaperBroker:
    """Optional: auto-execute A+ setups on the OANDA DEMO account with SL+TP.
    Risk-based position sizing. PAPER ONLY."""
    def __init__(self, risk_fraction: float = 0.01):
        if not (os.getenv("OANDA_API_TOKEN") and os.getenv("OANDA_ACCOUNT_ID")):
            raise RuntimeError("Set OANDA_API_TOKEN and OANDA_ACCOUNT_ID env vars.")
        self.acct = os.getenv("OANDA_ACCOUNT_ID")
        self.risk = risk_fraction

    def _balance(self) -> float:
        return float(_req(f"/accounts/{self.acct}/summary")["account"]["balance"])

    def open_trades(self) -> list:
        return _req(f"/accounts/{self.acct}/openTrades").get("trades", [])

    def close_trade(self, trade_id: str) -> dict:
        return _req(f"/accounts/{self.acct}/trades/{trade_id}/close", method="PUT")

    def close_all(self) -> list:
        """Flatten everything on the demo account. Returns close results."""
        results = []
        for t in self.open_trades():
            results.append(self.close_trade(t["id"]))
        return results

    # ---------- trade management methods (partials / trailing / SL moves) ----------
    def get_trade(self, trade_id: str):
        """Return the trade object (open or closed) or None if unknown.
        OANDA wraps the response as {"trade": {...}, "lastTransactionID": ...}."""
        try:
            return _req(f"/accounts/{self.acct}/trades/{trade_id}")["trade"]
        except Exception:
            return None

    def reduce_position(self, trade_id: str, units_to_close: float) -> dict:
        """Partially close a trade. units_to_close = magnitude (positive)."""
        t = self.get_trade(trade_id)
        if not t or t.get("state") != "OPEN":
            return {"done": False, "reason": "trade not open"}
        pos = float(t.get("currentUnits", 0))
        if pos == 0:
            return {"done": False, "reason": "no position"}
        close_u = -abs(units_to_close) if pos > 0 else abs(units_to_close)
        if abs(close_u) >= abs(pos):      # don't over-close
            close_u = -pos
        us = fmt_units(t["instrument"], close_u)
        order = {"order": {"type": "MARKET", "instrument": t["instrument"], "units": us}}
        try:
            r = _req(f"/accounts/{self.acct}/orders", method="POST", body=order)
            ok = bool(r.get("orderFillTransaction"))
            return {"done": ok, "closed_units": us,
                    "reason": "" if ok else (r.get("orderCancelTransaction", {}).get("reason", "no fill"))}
        except Exception as e:
            return {"done": False, "reason": str(e)}

    def set_stop_loss(self, trade_id: str, new_price: float) -> dict:
        """Move a trade's stop loss by replacing its dependent SL order.
        Only call with a FAVORABLE, valid level (caller validates)."""
        t = self.get_trade(trade_id)
        if not t or t.get("state") != "OPEN":
            return {"done": False, "reason": "trade not open"}
        inst = t["instrument"]
        pp = price_precision(inst)
        try:
            _req(f"/accounts/{self.acct}/trades/{trade_id}/orders", method="PUT",
                 body={"stopLoss": {"price": f"{new_price:.{pp}f}", "timeInForce": "GTC"}})
            return {"done": True, "sl": new_price}
        except Exception as e:
            return {"done": False, "reason": str(e)}

    def open_managed(self, sig: Signal, tp_final_mult: float = 2.0) -> dict:
        """Open a trade managed by trade_manager: SL at sig.stop, backstop TP far out,
        and (for partials) tp1 = sig.target. Returns trade_id + the management plan."""
        if sig.action != "SETUP" or sig.entry is None:
            return {"opened": False, "reason": "not a setup"}
        inst = resolve_instrument(sig.symbol)
        is_buy = sig.direction == Direction.BULL
        bal = self._balance()
        size = size_position(inst, bal, self.risk, sig.entry, sig.stop)
        if size.get("reason") == "invalid SL distance":
            return {"opened": False, "reason": "invalid SL distance"}
        if size["too_small"]:
            return {"opened": False, "reason": size["reason"], "skipped": "TOO_SMALL"}
        units = abs(size["units"]) if is_buy else -abs(size["units"])
        d = 1 if is_buy else -1
        tp1 = sig.target                                  # partial target (method TP)
        tp_final = sig.entry + d * abs(sig.target - sig.entry) * tp_final_mult  # backstop
        pp = price_precision(inst)
        order = {"order": {
            "type": "MARKET", "instrument": inst,
            "units": fmt_units(inst, units),
            "stopLossOnFill": {"price": f"{sig.stop:.{pp}f}", "timeInForce": "GTC"},
            "takeProfitOnFill": {"price": f"{tp_final:.{pp}f}", "timeInForce": "GTC"},
        }}
        try:
            r = _req(f"/accounts/{self.acct}/orders", method="POST", body=order)
            fill = r.get("orderFillTransaction", {})
            tid = (fill.get("tradeOpened") or {}).get("tradeID")
            if not tid:
                reason = (r.get("orderCancelTransaction") or {}).get("reason") \
                         or (r.get("orderRejectTransaction") or {}).get("rejectReason") or "no fill"
                return {"opened": False, "reason": str(reason)}
            return {"opened": True, "trade_id": tid, "instrument": inst,
                    "units": fmt_units(inst, units), "side": "buy" if is_buy else "sell",
                    "entry": float(fill.get("price", sig.entry)),
                    "stop": sig.stop, "tp1": tp1, "tp_final": tp_final,
                    "initial_size": abs(units)}
        except Exception as e:
            return {"opened": False, "reason": str(e)}

    def execute(self, sig: Signal, dry_run: bool = False) -> dict:
        if sig.action != "SETUP" or sig.entry is None:
            return {"executed": False, "reason": "not a setup"}
        inst = resolve_instrument(sig.symbol)
        is_buy = sig.direction == Direction.BULL
        # risk-based sizing, converted to dollars and clamped to lot rules
        bal = self._balance()
        size = size_position(inst, bal, self.risk, sig.entry, sig.stop)
        if size.get("reason") == "invalid SL distance":
            return {"executed": False, "reason": "invalid SL distance"}
        if size["too_small"]:
            return {"executed": False, "skipped": "TOO_SMALL",
                    "reason": size["reason"], "balance": f"{bal:.2f}"}
        units = abs(size["units"]) if is_buy else -abs(size["units"])
        risk_amount = size["risk_usd"]
        sl_dist = size["sl_dist"]
        units_str = fmt_units(inst, units)
        # price precision: forex ~5 decimals (JPY pairs 3), metals/crypto ~2-4
        pp = price_precision(inst)
        order = {
            "order": {
                "type": "MARKET",
                "instrument": inst,
                "units": units_str,
                "stopLossOnFill": {"price": f"{sig.stop:.{pp}f}", "timeInForce": "GTC"},
                "takeProfitOnFill": {"price": f"{sig.target:.{pp}f}", "timeInForce": "GTC"},
            }
        }
        if dry_run:
            return {"executed": False, "dry_run": True, "instrument": inst,
                    "side": "buy" if is_buy else "sell", "units": units_str,
                    "risk_amount": f"{risk_amount:.2f}", "sl_dist": f"{sl_dist:.4f}",
                    "risk_pct": f"{size['risk_pct']:.3f}%",
                    "balance": f"{bal:.2f}", "order": order}
        try:
            r = _req(f"/accounts/{self.acct}/orders", method="POST", body=order)
            if r.get("orderFillTransaction"):
                return {"executed": True, "units": units_str,
                        "side": "buy" if is_buy else "sell",
                        "fill": r["orderFillTransaction"].get("id")}
            if r.get("orderCancelTransaction"):
                reason = r["orderCancelTransaction"].get("reason", "?")
                hint = " (market closed — forex shuts Fri 21:00 UTC, reopens Sun 22:00 UTC)" \
                       if reason == "MARKET_HALTED" else ""
                return {"executed": False, "units": units_str,
                        "side": "buy" if is_buy else "sell",
                        "reason": f"ORDER_CANCELLED: {reason}{hint}"}
            if r.get("orderRejectTransaction"):
                return {"executed": False, "reason":
                        f"REJECTED: {r['orderRejectTransaction'].get('rejectReason')}"}
            return {"executed": False, "reason": f"unexpected response: {list(r.keys())}"}
        except Exception as e:
            return {"executed": False, "reason": str(e)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    f = OANDADataFeed(verbose=True)
    for sym in ["XAUUSD", "BTCUSD"]:
        for tf in ["1H", "15M"]:
            f.candles(sym, tf, 5)
    print("\nBalance:")
    try:
        b = OANDAPaperBroker(); print(f"  ${b._balance():.2f} (demo)")
    except Exception as e:
        print(f"  set OANDA_ACCOUNT_ID to see balance: {e}")
