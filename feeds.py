"""
feeds.py — Real live data feeds for the ICC engine. No API key needed.

- CCXTDataFeed: pulls OHLC from free public crypto exchanges (OKX default).
  BTC  -> BTC/USDT
  XAUUSD (gold) -> PAXG/USDT  (PAX Gold = 1 troy oz gold, ~1:1 with XAUUSD)
- Symbol map: the engine still calls it "XAUUSD" (so the gold session filter
  applies), but data is fetched from the PAXG/USDT pair.
- Falls back through a list of exchanges automatically.
"""
from __future__ import annotations
import datetime as dt, time
from typing import List
from icc_engine import Candle

SYMBOL_MAP = {
    "XAUUSD": "PAXG/USDT",   # gold proxy
    "BTCUSD": "BTC/USDT",
    "BTC":    "BTC/USDT",
}
EXCHANGES = ["okx", "kucoin", "coinbase", "kraken"]   # tried in order


class CCXTDataFeed:
    def __init__(self, exchanges=None, verbose=False):
        import ccxt
        self._ccxt = ccxt
        self.verbose = verbose
        self.exchanges = exchanges or EXCHANGES

    def _client(self, exid):
        return getattr(self._ccxt, exid)({"enableRateLimit": True})

    def candles(self, symbol: str, timeframe: str, limit: int = 120) -> List[Candle]:
        pair = SYMBOL_MAP.get(symbol.upper(), symbol.upper())
        tf = timeframe.lower().replace("h", "h").replace("m", "m")
        last_err = None
        for exid in self.exchanges:
            try:
                ex = self._client(exid)
                time.sleep(0.5)
                rows = ex.fetch_ohlcv(pair, tf, limit=limit)
                if not rows:
                    continue
                out = [Candle(dt.datetime.fromtimestamp(r[0]/1000, dt.timezone.utc).replace(tzinfo=None),
                              float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
                       for r in rows]
                if self.verbose:
                    print(f"  [{exid}] {pair} {timeframe}: {len(out)} candles, "
                          f"last close {out[-1].c:.2f} @ {out[-1].time:%Y-%m-%d %H:%M} UTC")
                return out
            except Exception as e:
                last_err = e
                if self.verbose:
                    print(f"  [{exid}] {pair} {tf}: {type(e).__name__}")
                time.sleep(0.5)
                continue
        raise RuntimeError(f"No exchange could serve {pair} {timeframe}: {last_err}")


class MultiFeed:
    """Routes symbols to the right backend: forex -> OANDA, BTC/gold -> CCXT.
    Lets the bot watch forex (tradeable on demo) AND BTC/gold (alert-only) together."""
    CRYPTO_SYMBOLS = {"BTCUSD", "BTC", "XAUUSD"}  # served by CCXT (BTC/USDT, PAXG/USDT)

    def __init__(self, primary, verbose=False):
        self.primary = primary                       # e.g., OANDADataFeed (forex)
        self.crypto = CCXTDataFeed(verbose=verbose)  # BTC + gold proxy
        self.verbose = verbose

    def candles(self, symbol, timeframe, limit=120):
        if symbol.upper() in self.CRYPTO_SYMBOLS:
            return self.crypto.candles(symbol, timeframe, limit)
        return self.primary.candles(symbol, timeframe, limit)


if __name__ == "__main__":
    # quick live smoke test
    f = CCXTDataFeed(verbose=True)
    for sym in ["BTCUSD", "XAUUSD"]:
        for tf in ["1H", "15M"]:
            f.candles(sym, tf, 10)
