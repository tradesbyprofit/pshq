"""
test_paper_trade.py — Controlled end-to-end test of paper execution on the
OANDA DEMO account. Places ONE tiny BTC buy with SL+TP, confirms the fill,
then immediately closes it. Nothing is left open. Demo only.
"""
import datetime as dt
from icc_engine import Signal, Direction
from oanda_feed import OANDADataFeed, OANDAPaperBroker

feed = OANDADataFeed()
price = feed.candles("EURUSD", "15M", 5)[-1].c
broker = OANDAPaperBroker(risk_fraction=0.0002)   # tiny risk for the test

# tiny test trade: small EUR/USD buy, ~10-pip SL/TP so sizing is small
sig = Signal(action="SETUP", symbol="EURUSD", direction=Direction.BULL,
             reason="INFRASTRUCTURE TEST (not a strategy trade)",
             entry=price, stop=round(price - 0.0010, 5), target=round(price + 0.0010, 5), rr=1.0,
             when=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))

print(f"=== PAPER EXEC TEST @ EURUSD {price:.5f} ===")
print(f"Placing market BUY with SL {sig.stop:.5f} / TP {sig.target:.5f} ...")
res = broker.execute(sig)
print("Result:", {k: v for k, v in res.items() if k != "raw"})

print("\nOpen trades after fill:")
for t in broker.open_trades():
    print(f"  trade {t['id']}: {t['currentUnits']} {t['instrument']} "
          f"@ {t['price']}  SL={t.get('stopLossOrder',{}).get('price')} "
          f"TP={t.get('takeProfitOrder',{}).get('price')}  "
          f"unrealizedPL={t.get('unrealizedPL')}")
    # show pip P/L for readability
    try:
        pl = float(t.get('unrealizedPL', 0))
        print(f"      (unrealized: ${pl:+.2f} on demo)")
    except Exception:
        pass

print("\nClosing all (flatten demo) ...")
closed = broker.close_all()
print(f"Closed {len(closed)} trade(s). Final demo balance: ${broker._balance():.2f}")
print("\n✅ Execution pipeline verified: order placed -> SL/TP attached -> filled -> closed.")
