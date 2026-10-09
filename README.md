# ICC Day-Trading Bot — Trades By Sci method
*A patient, setup-only alert bot. **GOLD (XAUUSD) ONLY.** Markup on **4H**, entries on **1H**. Target **1 trade/week** (2 max), often **zero**. Never chases. Auto paper-execution on the OANDA demo.*

> **Updated 2026-10-08 to Sci's "MY ICC UPDATE" (2026-07-30).** The 15-minute
> timeframe is gone; markup moved 1H→4H; entries moved 15M→1H; and the
> no-trade zone now has an explicit construction rule. Full extraction with
> verbatim quotes: **`transcripts/ICC_Update_2026-07-30.md`**.

## 🚨 Read CAVEATS.md before funding anything
`CAVEATS.md` collects sourced evidence about the **performance claims** (not the
method). Headline: Revelio Trading coded this exact strategy and ran **2,500+
backtests over 10 years**; the best version, on **gold + 4H at 1% risk**, returned
**+45.7% total ≈ 3.8%/yr with a 53.8% max drawdown**, and *"the strategy made no
real progress in the last 8½ years."* Their verdict: *"barely"* works.

Two findings from that study **support** how this repo is now configured:
- **Gold is the best of the four assets** — NASDAQ was negative in *every* configuration. Gold-only is the empirically correct call, not just a preference.
- **4H ranked top-four**, ahead of 1H — the same direction Sci moved in July 2026.

**Risk per trade is set to Sci's stated 10%** (`RISK_PER_TRADE` in `scanner.py`,
operator decision 2026-10-08; `--risk <pct>` overrides). For the record, Revelio's
study calls 10–20% *"mathematical suicide"* that *"gets annihilated"*, and found
1% was the only survivable setting — that evidence stays in `CAVEATS.md`. The
setting is yours to make; `python3 scanner.py --risk 1` changes it without a code
edit. Note that **because gold is alert-only, nothing auto-executes at 10%** —
the figure only drives the lot size printed in your alerts.

## 📈 Markets — gold only
| | |
|---|---|
| **Traded** | `XAUUSD` only (`WATCH` in `scanner.py`) |
| **Dropped** | EUR/USD, GBP/USD, USD/JPY, GBP/JPY, BTC — even though Sci still shows NASDAQ/BTC examples |
| **Markup TF** | **4H** |
| **Entry TF** | **1H** |
| **Abandoned** | **15M** — *"volume is excessive throughout New York session, breaks structure a lot on the 15-minute"* |

> ⚠️ **Blocker to paper-trading gold:** your OANDA **practice** account is
> forex-only (68 pairs, no metals), so `XAUUSD` is in `ALERT_ONLY` and the bot
> will **alert but not execute**. To paper-trade gold you must either enable
> Metals on the OANDA account or point `oanda_feed.py` at a broker offering spot
> gold. Until then: alerts on Telegram, no orders. Gold also needs a balance of
> roughly **$25+** before a 0.01-lot minimum fits inside a 1% risk budget at
> 4H stop widths — `python3 compound_reality.py --min-account`.

> ⏰ **Market hours:** spot gold trades nearly 24h but closes **Fri 21:00 UTC**
> and reopens **Sun 22:00 UTC**. Orders outside that window return
> `MARKET_HALTED`. Sci also skips **Sunday open gaps** — *"I need New York
> session to bring some volume"* — though he refuses to make it a hard rule, so
> this repo logs it rather than enforcing it.

## ⚙️ Your confirmed setup
| Choice | Selected | How it's wired |
|---|---|---|
| Execution | **Alert-only** (gold cannot auto-exec on a forex-only practice acct) | `notifier_telegram.py`; `--paper` available once gold is executable |
| Risk/trade | **10%** — Sci's stated default (operator decision) | `RISK_PER_TRADE` in `scanner.py`, `--risk <pct>` to override |
| Connection | **OANDA paper account** | `oanda_feed.py` — real spot XAU_USD + BTC_USD |
| Accounts | **OANDA demo** | Free practice account, real-time data, API key |
| Notify | **Telegram** | `--telegram` flag |

**Why OANDA:** free demo, real **spot gold** (not a crypto proxy) + BTC, clean REST API, and it can place **paper orders** so the bot can build a real track record safely. Set `src=OANDA` with `--oanda`; add `--paper` to auto-execute setups on the demo (1% risk/trade).

**⚠️ Security:** use the **Practice/Demo** token only (`api-fxpractice.oanda.com`), never Live. I read it from env vars — don't commit it. Rotate it after testing if you like.

## Files
| File | Purpose |
|---|---|
| **CAVEATS.md** | 🚨 Sourced evidence on the *performance claims*, incl. the only independent backtest. **Read before funding anything.** |
| **METHOD.md** | The original 14-video course synthesized. ⚠️ **Superseded on timeframes** by the 2026-07-30 update — still correct on the ICC concept. |
| **transcripts/ICC_Update_2026-07-30.md** | ⭐ **The current method.** Full extraction of "MY ICC UPDATE" with verbatim quotes + a diff vs. METHOD.md. |
| **icc_engine.py** | The ICC detector → `SETUP`/`NO_TRADE` + entry/stop/target/R:R + checklist. Now includes `no_trade_zone()`. Self-tested. |
| **oanda_feed.py** | ⭐ OANDA practice feed (real spot gold + BTC) + optional paper broker. |
| **feeds.py** | Backup data via CCXT (OKX/Kucoin) — no key, crypto-only. |
| **scanner.py** | Live monitor. Weekly cap (1 target/2 max) + "don't chase" guard. State persists. |
| **notifier_telegram.py** | Telegram alerts on A+ setups only. |
| **icc_tv.pine** | Optional TradingView indicator (visual; labels swings + indications). |
| **journal.py** | ⭐ **Your hand-placed gold trades** — what the bot said vs. what you did → **expectancy in R**. Gold is alert-only, so this is the only real record that exists. |
| **trade_stats.py** | Expectancy from OANDA closed trades *or* `--source journal`. |
| **compound_reality.py** | ⭐ "Can $1 become $1,000,000?" answered with arithmetic + Monte Carlo. |
| **test_sizing.py** | 69 offline checks: position sizing, lot rules, quote-currency conversion, manual-entry hints. Run in CI. |
| **test_no_trade_zone.py** | 34 offline checks for the zone gate + the tied-extreme swing bug. Run in CI. |
| **test_journal.py** | Offline checks for the journal's R arithmetic + slippage sign convention. Run in CI. |
| transcripts/ | Per-video extraction notes (Day 1 + the 2026-07 update). |

## Run it
```bash
# 0) set OANDA demo creds (Practice token + account id)
export OANDA_API_TOKEN="........"
export OANDA_ACCOUNT_ID="101-xxx-xxxxxxxx-xxx"

python3 oanda_feed.py --test        # verify live gold + BTC candles + balance
python3 scanner.py --oanda          # LIVE scan on real spot data (alert-only)

# Telegram (one-time): @BotFather → token ; @userinfobot → chat id
export TG_BOT_TOKEN="..." ; export TG_CHAT_ID="..."
python3 scanner.py --oanda --telegram          # live + alerts (gold, 10% risk sizing)
python3 scanner.py --oanda --telegram --risk 1 # same, but size alerts at 1% risk
python3 scanner.py --oanda --telegram --balance 2500   # size against a $2,500 account
python3 scanner.py --oanda --telegram --paper  # auto paper-execute (needs gold enabled)

# other modes
python3 scanner.py                   # CCXT crypto data (no key)
python3 scanner.py --demo            # synthetic, offline
python3 icc_engine.py                # engine self-test

# is any of this actually going to work?
python3 journal.py                   # your gold record: open, awaiting decision, expectancy
python3 trade_stats.py               # expectancy (OANDA history, or the journal if empty)
python3 trade_stats.py --source journal   # your hand-traded gold, measured in R
python3 compound_reality.py          # what $1 -> $1,000,000 really costs
python3 compound_reality.py --from-journal # ...using YOUR measured edge, not an assumption
python3 test_sizing.py               # offline sizing/lot-rule regression tests
python3 test_journal.py              # offline journal arithmetic tests
```
In production, schedule `scanner.py --oanda --telegram` every 15 min (cron/systemd) so it runs unattended.

## The method in one breath (2026-07-30 version)
**ICC = Indication → Correction → Continuation.** No indicators. **Two timeframes only.**
1. **Mark up the 4H from candle CLOSES** — never wicks: *"a wick is price attempted to but failed."*
2. **Draw the NO-TRADE ZONE:** from current price go up to the last swing **high**, then back to the swing **low that created it**. Price between them = buyers *and* sellers in control = **wait**. *"A no trade zone should be looked at as good."*
3. **Indication:** a 4H body **closes outside** the zone → bias + target. *"The moment price comes above this blue line, I press buy. Below it, I press sell."* Don't trade it yet.
4. **Correction:** 1–2 candles back toward the broken level on the 4H. That extreme is your **invalidation** — also check what would go *against* you.
5. **Continuation:** drop to the **1H** and enter only when 1H structure **matches** the 4H (lower highs + lower lows under the level for a sell). *"Because now the 1 hour and 4 hour match."* A **2nd reclaim** still counts: *"especially if price has already repeated it once before, just take it."*
6. **Stop:** beyond 4H structure, **deliberately wide**. *"If you can't put whatever stop-loss you want, lower your lot size."* The trade is valid until a **4H level breaks** — *"just because price sold off doesn't make it invalid."*
7. **Target:** the opposite zone edge — *"price moves zone to zone."* At the target, partials or runner: *"it's up to me at that point."*

**Alerts, not staring:** one alert on each zone edge, *crossing up* and *crossing down*, trigger every time. *"I live off of alerts... literally cannot function without them."* That is exactly what `scanner.py` + Telegram already do.

> ⚠️ **Disagreement worth knowing:** Sci enters on a **1H body close** back over
> the level. Revelio's backtest found the best entry was **as soon as price
> touches the break-of-structure level** — *"no added buffer, no waiting for the
> candlestick to close"* (waiting for the close: profit factor **1.032**). They
> tested the older 15m/5m variant, so the new 4H→1H version is untested by
> anyone. This is the most valuable thing left to measure — see CAVEATS.md §5.

## ⚠️ Reality check
- Creator claims >90% win rate — treat as **unverified**. Validate on **demo/paper** for weeks before risking real money (his own Day-13 advice).
- **"$1 → $1,000,000" is not a plan.** Run `python3 compound_reality.py` — it uses this repo's own Governor (1 trade/week) and 1% risk to show what the multiple actually costs. At 1 trade/week, 1,000,000x needs **~20 consecutive doublings**. Even a genuinely excellent **+0.21R/trade** edge gets there in **0%** of simulated careers inside 60 years, because 60 years only contains ~3,120 trades and the multiple needs ~6,600. The discipline that makes this method sane (never chase, 1/week) is the same thing that caps the multiple.
- **Gold and BTC have a real minimum balance.** One minimum OANDA lot risks ~$0.12 on XAU and ~$9 on BTC, so honouring a 1% budget needs **~$12 (gold)** / **~$900 (BTC)**. Below that the bot now **skips with `TOO_SMALL`** instead of submitting an order it cannot size. `python3 compound_reality.py --min-account` prints the floor for every watched pair.
- The gold feed uses **PAXG** (crypto gold token) as a close proxy — prices track XAUUSD but aren't identical to your broker's spot quote. Confirm execution levels on your actual broker chart.
- **Not financial advice.** Markets lose money. Start tiny.

## The journal — measuring YOUR execution, not just the method's

Gold is alert-only, so OANDA never holds a closed gold trade and the broker has
nothing to report. `journal.py` is the record instead: **the scanner writes every
alert automatically**, and you add what you actually did.

```bash
python3 journal.py                    # dashboard: open, awaiting decision, expectancy
python3 journal.py fill --last --price 4037.2 --units 40
python3 journal.py exit --last --price 3990 --reason tp
python3 journal.py skip --last --reason "Sunday gap, no NY volume yet"
python3 journal.py report             # expectancy in R + you vs. the bot
python3 compound_reality.py --from-journal   # project forward from YOUR measured edge
```

Everything is measured in **R** (multiples of the amount risked), so it stays
comparable as your balance moves. The report deliberately separates two things
that are easy to conflate:

- **Does the method work?** — win rate, avg win/loss in R, profit factor,
  expectancy per trade.
- **Do you execute it?** — average entry slippage vs. the alert price (negative =
  a real cost), whether you sized as advised, and whether you actually exited at
  your stop when a trade went against you. A positive-expectancy method held past
  its stop still loses money, and only this second column shows it.

Recording **skips** matters as much as fills. If the setups you passed on would
have won, your discretion is costing you; if they would have lost, your
discretion *is* the edge. There is no way to tell which without writing them down.

`journal.jsonl` is gitignored — it is your personal execution data. Point
`ICC_JOURNAL` at a synced path to back it up. Under 10 closed trades
`--from-journal` refuses to build an edge; under 30 the report warns you the
number is noise.

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
- `scanner.py`: `WATCH` (**gold only** — add a symbol here to re-add a market), `HTF="4H"`/`LTF="1H"`, `ALERT_ONLY`, `RISK_PER_TRADE` (**10%**), `DEFAULT_BALANCE`, `Governor(target_per_week=1, max_per_week=2)`, `min_rr`.
- `icc_engine.py`: swing sensitivity (`left`/`right`), `min_rr`, session hours, trend lookback, `no_trade_zone()`.
- ⚠️ **`left`/`right` is the single biggest unvalidated parameter in this bot.** Sci has never stated a fractal window, and Reddit flags the same gap: *"Sci doesn't tell us the rules for marking the structure points."* The repo uses `left=2, right=2`. Backtest it before trusting it.
- Add markets later: just add to `WATCH` + a `SYMBOL_MAP` entry in `feeds.py` (e.g. ETH, NAS100).
