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
import os, json, urllib.request, urllib.parse, datetime as dt
from typing import List, Optional
from icc_engine import Candle, Signal, Direction

BASE = "https://api-fxpractice.oanda.com/v3"   # PRACTICE/DEMO only
SYMBOL_MAP = {"XAUUSD": "XAU_USD", "BTCUSD": "BTC_USD", "BTC": "BTC_USD"}
TF_MAP = {"1H": "H1", "4H": "H4", "15M": "M15", "5M": "M5"}


def resolve_instrument(symbol: str) -> str:
    """'EURUSD' -> 'EUR_USD'; honors explicit SYMBOL_MAP (XAU/BTC) first."""
    s = symbol.upper().replace("/", "").replace("-", "")
    if s in SYMBOL_MAP:
        return SYMBOL_MAP[s]
    # generic 6-letter forex pair: split into CCC_CCC
    if len(s) == 6 and s.isalpha():
        return f"{s[:3]}_{s[3:]}"
    return s


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

    def execute(self, sig: Signal, dry_run: bool = False) -> dict:
        if sig.action != "SETUP" or sig.entry is None:
            return {"executed": False, "reason": "not a setup"}
        inst = resolve_instrument(sig.symbol)
        is_buy = sig.direction == Direction.BULL
        # risk-based sizing: contract size 1 for both XAU_USD & BTC_USD
        bal = self._balance()
        risk_amount = bal * self.risk
        sl_dist = abs(sig.entry - sig.stop)
        if sl_dist <= 0:
            return {"executed": False, "reason": "invalid SL distance"}
        units = max(risk_amount / sl_dist, 0.01)
        units = units if is_buy else -units
        # forex pairs require integer units; metals/crypto allow fractional
        parts = inst.split("_")
        is_fx = len(parts) == 2 and len(parts[0]) == 3 and len(parts[1]) == 3
        units_str = str(int(round(units))) if is_fx else f"{units:.2f}"
        # price precision: forex ~5 decimals (JPY pairs 3), metals/crypto ~2-4
        pp = 3 if inst.endswith("_JPY") else (5 if is_fx else 2)
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
