"""
account_preflight.py — Checks your OANDA demo: balance + which watch instruments
(XAU_USD, BTC_USD) are tradeable. Run after enabling products on the account.

Usage:  OANDA creds in env, then:  python3 account_preflight.py
"""
from oanda_feed import _req, SYMBOL_MAP
import os

acct = os.getenv("OANDA_ACCOUNT_ID")
insts = {i["name"]: i for i in _req(f"/accounts/{acct}/instruments").get("instruments", [])}
bal = _req(f"/accounts/{acct}/summary")["account"]["balance"]
print(f"Account {acct}:  balance ${float(bal):.2f}  |  {len(insts)} instruments enabled\n")

watch = ["XAU_USD", "BTC_USD"]
for s in watch:
    in_list = s in insts
    print(f"  {s:8} {'✅ tradeable' if in_list else '❌ NOT enabled on this account'}")
print("\nTo trade gold: OANDA practice web → account settings/products → enable Metals (XAU/USD).")
print("Crypto (BTC) may not be offered on your demo/region — keep BTC alert-only if so.")
