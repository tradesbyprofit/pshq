# ICC Day-Trading Bot — Trades By Sci method
*A patient, setup-only alert bot. Target **1 trade/week** (2 max), often **zero**. Never chases. Auto paper-execution on the OANDA demo.*

## 📈 Markets (current base)
Your OANDA **demo is forex-only** (68 pairs, no metals/crypto yet), so the bot currently trades these — all excellent for the ICC method (clean trends, London/NY volume):
- **EUR/USD, GBP/USD, USD/JPY, GBP/JPY** (`WATCH` in `scanner.py` — edit freely)
- **Gold (XAU) & BTC:** data feeds are built; we'll enable trading for them later (gold = enable Metals on the account; BTC = a crypto testnet).

> ⏰ **Forex hours:** the market closes **Fri 21:00 UTC** and reopens **Sun 22:00 UTC**. Orders outside that window return `MARKET_HALTED` (the bot logs this clearly). Run scans only during open hours.

## ⚙️ Your confirmed setup
| Choice | Selected | How it's wired |
|---|---|---|
| Execution | **Alert-only** (+ optional paper auto-exec) | `notifier_telegram.py` + `--paper` flag |
| Connection | **OANDA paper account** | `oanda_feed.py` — real spot XAU_USD + BTC_USD |
| Accounts | **OANDA demo** | Free practice account, real-time data, API key |
| Notify | **Telegram** | `--telegram` flag |

**Why OANDA:** free demo, real **spot gold** (not a crypto proxy) + BTC, clean REST API, and it can place **paper orders** so the bot can build a real track record safely. Set `src=OANDA` with `--oanda`; add `--paper` to auto-execute setups on the demo (1% risk/trade).

**⚠️ Security:** use the **Practice/Demo** token only (`api-fxpractice.oanda.com`), never Live. I read it from env vars — don't commit it. Rotate it after testing if you like.

## Files
| File | Purpose |
|---|---|
| **METHOD.md** | ⭐ The full method (all 14 videos synthesized) — the bot's brain. Read first. |
| **icc_engine.py** | The ICC detector → `SETUP`/`NO_TRADE` + entry/stop/target/R:R + checklist. Self-tested. |
| **oanda_feed.py** | ⭐ OANDA practice feed (real spot gold + BTC) + optional paper broker. |
| **feeds.py** | Backup data via CCXT (OKX/Kucoin) — no key, crypto-only. |
| **scanner.py** | Live monitor. Weekly cap (1 target/2 max) + "don't chase" guard. State persists. |
| **notifier_telegram.py** | Telegram alerts on A+ setups only. |
| **icc_tv.pine** | Optional TradingView indicator (visual; labels swings + indications). |
| **trade_stats.py** | Your real demo record → win rate, profit factor, **expectancy/trade**. |
| **compound_reality.py** | ⭐ "Can $1 become $1,000,000?" answered with arithmetic + Monte Carlo. |
| **test_sizing.py** | Offline regression tests for position sizing / lot rules. Run in CI. |
| transcripts/ | Per-video extraction notes. |

## Run it
```bash
# 0) set OANDA demo creds (Practice token + account id)
export OANDA_API_TOKEN="........"
export OANDA_ACCOUNT_ID="101-xxx-xxxxxxxx-xxx"

python3 oanda_feed.py --test        # verify live gold + BTC candles + balance
python3 scanner.py --oanda          # LIVE scan on real spot data (alert-only)

# Telegram (one-time): @BotFather → token ; @userinfobot → chat id
export TG_BOT_TOKEN="..." ; export TG_CHAT_ID="..."
python3 scanner.py --oanda --telegram          # live + alerts
python3 scanner.py --oanda --telegram --paper  # ...and auto paper-execute setups

# other modes
python3 scanner.py                   # CCXT crypto data (no key)
python3 scanner.py --demo            # synthetic, offline
python3 icc_engine.py                # engine self-test

# is any of this actually going to work?
python3 trade_stats.py               # your real demo expectancy (needs closed trades)
python3 compound_reality.py          # what $1 -> $1,000,000 really costs
python3 compound_reality.py --from-demo   # ...using YOUR measured edge, not an assumption
python3 test_sizing.py               # offline sizing/lot-rule regression tests
```
In production, schedule `scanner.py --oanda --telegram` every 15 min (cron/systemd) so it runs unattended.

## The method in one breath
**ICC = Indication → Correction → Continuation.** No indicators.
1. **Mark up HTF (1H/4H):** swings → trend (HH/HL bull, LH/LL bear). Range = no-trade.
2. **Indication:** a swing *breaks* (new extreme) → bias + TP. Don't trade it.
3. **Correction:** pullback that grabs liquidity (watch 15M).
4. **Continuation:** price reclaims the level a **2nd time** → **enter**. SL past correction extreme; TP = indication's new extreme; hold runner while structure holds.
Gate rules: **buy only above a broken swing high; sell only below a broken swing low.** No break = **NO TRADE ZONE.**

## ⚠️ Reality check
- Creator claims >90% win rate — treat as **unverified**. Validate on **demo/paper** for weeks before risking real money (his own Day-13 advice).
- **"$1 → $1,000,000" is not a plan.** Run `python3 compound_reality.py` — it uses this repo's own Governor (1 trade/week) and 1% risk to show what the multiple actually costs. At 1 trade/week, 1,000,000x needs **~20 consecutive doublings**. Even a genuinely excellent **+0.21R/trade** edge gets there in **0%** of simulated careers inside 60 years, because 60 years only contains ~3,120 trades and the multiple needs ~6,600. The discipline that makes this method sane (never chase, 1/week) is the same thing that caps the multiple.
- **Gold and BTC have a real minimum balance.** One minimum OANDA lot risks ~$0.12 on XAU and ~$9 on BTC, so honouring a 1% budget needs **~$12 (gold)** / **~$900 (BTC)**. Below that the bot now **skips with `TOO_SMALL`** instead of submitting an order it cannot size. `python3 compound_reality.py --min-account` prints the floor for every watched pair.
- The gold feed uses **PAXG** (crypto gold token) as a close proxy — prices track XAUUSD but aren't identical to your broker's spot quote. Confirm execution levels on your actual broker chart.
- **Not financial advice.** Markets lose money. Start tiny.

## Position sizing (fixed)
Sizing lives in `oanda_feed.size_position()` and is covered by `test_sizing.py`. Three bugs that used to make small accounts untradeable and JPY accounts under-risked:

| Bug | Before | After |
|---|---|---|
| **Quote currency ignored** | `units = risk / sl_dist` divided a **dollar** budget by a **yen** distance on USD_JPY/GBP_JPY → risked ~0.0067% instead of 1% (~150x under) | `quote_to_usd()` converts the stop to dollars first (live rate, cached, fallback table) |
| **Banker's rounding** | `int(round(0.5)) == 0` → submitted **0-unit** orders that OANDA rejects | `_round_half_away()` + a `legal_units()` floor |
| **Metals/crypto treated as forex** | `XAU_USD`/`BTC_USD` are also 3+3 letters, so gold got integer-rounded → any lot under 0.5 units sent **0** | `is_forex()` uses a fiat whitelist; `price_precision()` per-asset |

> ⚠️ **Behaviour change:** JPY positions are now sized ~150x larger than before — which is the *correct* 1% risk, but it is a visible jump on the demo. Check your margin headroom before the next `--paper` run.

Tests are offline (no keys, no network) and run on every push via `.github/workflows/tests.yml`:
```bash
python3 test_sizing.py      # 50 offline checks: lot rules, JPY conversion, $1 floors, TOO_SMALL skip
```

## Tuning knobs (edit the files)
- `scanner.py`: `WATCH`, `HTF`/`LTF`, `Governor(target_per_week=1, max_per_week=2)`, `min_rr`.
- `icc_engine.py`: swing sensitivity (`left`/`right`), `min_rr`, session hours, trend lookback.
- Add markets later: just add to `WATCH` + a `SYMBOL_MAP` entry in `feeds.py` (e.g. ETH, NAS100).
