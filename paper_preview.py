"""
paper_preview.py — DRY-RUN preview of what the paper broker WOULD do for a
hypothetical A+ setup at the current live price. No order is placed.

Usage:  OANDA creds in env, then:  python3 paper_preview.py [XAUUSD|BTCUSD]
"""
from __future__ import annotations
import sys, datetime as dt
from icc_engine import Signal, Direction
from oanda_feed import OANDADataFeed, OANDAPaperBroker

sym = (sys.argv[1] if len(sys.argv) > 1 else "XAUUSD").upper()
feed = OANDADataFeed()
price = feed.candles(sym, "4H", 5)[-1].c   # 4H markup per MY ICC UPDATE (2026-07-30)

# hypothetical BULL ICC setup at current price (for sizing demonstration only)
if "XAU" in sym:
    sl_pts, tp_pts = 25.0, 50.0   # 4H-scaled gold stop, not the old 15M-scale $5
else:
    sl_pts, tp_pts = 500.0, 1000.0
sig = Signal(action="SETUP", symbol=sym, direction=Direction.BULL,
             reason="HYPOTHETICAL preview — not a real setup",
             entry=price, stop=price - sl_pts, target=price + tp_pts, rr=2.0,
             when=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))

broker = OANDAPaperBroker(risk_fraction=0.01)
res = broker.execute(sig, dry_run=True)

print(f"=== PAPER DRY-RUN PREVIEW ({sym} @ live {price:.2f}) ===")
print(f"Direction : BUY (hypothetical)")
print(f"Entry     : {sig.entry:.2f}")
print(f"Stop      : {sig.stop:.2f}  (risk dist {res['sl_dist']})")
print(f"Target    : {sig.target:.2f}")
print(f"Account   : ${res['balance']}  | risk/trade 1% = ${res['risk_amount']}")
print(f"Position  : {res['units']} units  ({res['side']})")
print(f"Instrument: {res['instrument']}")
print(f"\n(This is a DRY RUN — nothing was traded. Enable --paper for real demo orders.)")
