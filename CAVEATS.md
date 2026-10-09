# CAVEATS.md — read this before funding an account

This repo now implements Sci's **2026-07-30** method on **gold only**. The method
is coherent and worth paper-trading. Separately from the method, there is hard,
checkable evidence about the **performance claims** that you should have before
you put real money in. Both things are true at once: the rules can be worth
following and the numbers can be worth disbelieving.

Everything below was retrieved 2026-10-08 and is sourced so you can check it
yourself. Nothing here is my opinion.

---

## 1. An independent team coded this exact strategy and backtested it on gold

**Revelio Trading — "I Coded Trades By Sci's Trading Strategy. Does It Work?"**
https://www.youtube.com/watch?v=bZzREoCf0z0 (2026-08-15)

> "This video took over a month to make with more than **2,500 backtests across
> 10 years of data and four markets**."

They coded ICC as taught, resolved the ambiguities by testing each one, and
reported the best version they could find.

### Their headline result, at 1% risk per trade — the survivable setting:

| Metric | Value |
|---|---|
| Total return, 10 years | **+45.7%** |
| **Annualized** | **~3.6–3.8%** |
| Max drawdown | **53.8%** |
| Win rate | *"nowhere near the 90% he claims"* |
| Profit factor | *"not around 10"* |

> "The last four years have been profitable, but the strategy also went through
> **four negative years in a row between 2019 and 2022**. Also... if we remove
> 2017, the strategy pretty much breaks even... The equity today is still
> slightly below that line. **The strategy made no real progress in the last 8
> 1/2 years.**"

> "Does this strategy actually work? My opinion is **barely**... the best version
> of the strategy returned about **3.63% a year while sustaining a drawdown of
> 53.8%**. Certainly not a strategy I would insert in my portfolio."

### Feeding that into this repo's own calculator

```
python3 compound_reality.py --measured
```

$1 → $1,000,000 at 3.84%/yr = **367 years**. $10,000 → $1,000,000 = **122 years**.
And you would sit through a 53.8% drawdown on the way, which at 1% risk is a
~54-trade losing stretch.

### Two findings from that study that support what you already decided

This is not all bad news — the backtest independently backs your two calls:

1. **Gold is the best asset.** *"Silver and NASDAQ occupy the entire second half
   of the ranking. NASDAQ is negative in every single configuration and even the
   best silver version only just matches the weakest gold result. So we remove
   silver and NASDAQ from our strategy."* → **Gold-only is the empirically
   correct choice, not just a preference.**
2. **4H beats 1H on quality.** *"the 4hour time frame occupies the first four
   positions... it seems to perform better than the hourly."* → Sci's July 2026
   move to 4H markup points the same direction. (Caveat: 1H took more trades and
   produced some of the highest *total R*, so 4H wins on per-trade quality, not
   on total opportunity.)

### One finding that contradicts Sci's new entry rule

> "The best way to enter the market is **as soon as the price touches the break
> of structure level. No added buffer, no waiting for the candlestick to
> close.**" (Waiting for the LTF close: profit factor **1.032** — "clearly
> worse".)

Sci's update says to wait for a **1H body close** back over the level. They
disagree. Note Revelio tested the *older* LTF (15m/5m) variant, so the new
4H→1H version is **not** what they measured. That gap is a real, testable
question — see "What would actually settle this" below.

---

## 2. ⚠️ Do NOT follow his risk-per-trade advice

This is the one place where "follow his lead" would genuinely hurt you.

Revelio, on Sci's stated sizing:

> "Now, Sai suggests **risking 10% per trade. And when you feel confident,
> increasing the risk to 20% per trade.** Well, this is a problem. How do I tell
> when my algorithm feels more confident? But that's not even the main problem.
> Anyone who has been trading for a few months or has a basic understanding of
> mathematics can tell you that **risking 10 to 20% per trade will inevitably
> blow up your account in the long run.**"

> "As expected, the 10 and 20% risk per trade **get annihilated**. The 2% risk
> per trade is also too much... **that is why 10 and 20% risk per trade are
> mathematical suicide.**"

Four consecutive losses — an ordinary event, not a tail:

| Risk/trade | Account left after 4 straight losses |
|---|---|
| 20% (his "confident" setting) | **41.0%** |
| 10% (his stated default) | **65.6%** |
| 2% | 92.2% |
| **1% (this repo's setting)** | **96.1%** |

> **Operator decision 2026-10-08: this repo is wired to Sci's stated 10%**
> (`RISK_PER_TRADE = 0.10` in `scanner.py`, `--risk <pct>` to override). The
> evidence above is retained as the record; the choice is the operator's to make.
> Two things worth knowing about that choice:
> - **It is currently inert.** `XAUUSD` is in `ALERT_ONLY` because OANDA practice
>   accounts are forex-only, so no order is ever sized at 10%. The number only
>   drives the lot size printed in Telegram alerts for manual entry. It goes live
>   the moment gold execution is enabled.
> - His 4H update agrees with the *principle* — *"if you can't put whatever
>   stop-loss you want, lower your lot size"* — and `size_position()` implements
>   it: the stop goes where structure says, the lot absorbs the risk.

---

## 3. The $125M claim and the broker's written response

From the same Revelio video, their due-diligence section:

- Sci published a video titled **`124,785,326.70`** — ~$125M claimed total net
  profit, with an on-screen **profit factor of 8.43** (other videos show ~10+).
- A gold short shown at entry ~4,695 with price ~4,595 displayed **~$6.39M
  floating profit** on **just under €6M used margin**. Four 50-lot positions were
  visible, but the P/L and margin imply **~15 such positions ≈ 750 lots of gold**.
- Revelio contacted **Liquid Brokers** — the broker Sci says he uses — and asked
  about maximum gold size. AI agent: *"The maximum lot size allowed for trading
  gold at Liquid Brokers is 22 lots... refers to the maximum total position size
  per account, not per individual trade."* A human agent confirmed it, and their
  **internal risk management team replied by email**: *"The maximum lot size is
  determined by our trading conditions and risk-management policies and cannot
  be adjusted on an individual basis."*
  → **750 lots is roughly 34x the broker's absolute per-account limit.**
- Margin arithmetic: balance ~€6.3M / used margin ~€6M = **~106% margin level**.
  That broker margin-calls at 100% and **stops out at 70%**, which on those
  figures would have triggered at gold ≈ **4,728**. Sci's displayed stop-loss was
  **4,731** — $3 *beyond* the stop-out. Revelio: *"It's like planning to hit the
  brakes 3 m after the wall. Mathematically, that stop-loss could never have
  been reached."*
- A **court judgment dated 2023-08-24** ruled against him: customers paid him to
  pass FTMO challenges with a promised 110% refund on failure; the judgment says
  he failed them and did not refund ($500 and $1,728). **53 days later**, on
  2023-10-16, he appeared in an interview titled *"20-year-old makes 11 million
  in one trade."*
- On the common defence that "he doesn't sell anything": the description of
  **MY ICC UPDATE itself** contains a broker referral link
  (`i use this to trade : https://tinyurl.com/hideoutsci`), plus a Discord, a
  Telegram (`t.me/iccmafia`) and Snapchat. Referral links pay per funded account.

### Lower-weight allegations (unverified — listed for completeness, not evidence)
- r/Forexstrategy: *"He doesn't live trade, he uses demo accounts and fake profit."*
- *"My $1,000,000 Bet That Trades by Sci is a Fraud"* — TheOneLanceB, 2026-06-20.
- *"Trades By Sci EXPOSED? New Evidence Just Dropped"* — 2026-07-28.
- In **MY ICC UPDATE** he claims *"we are up $1.2 million on gold buys"* on a
  live setup, with no auditable statement.

---

## 4. What this means practically

**Nothing here says the method is worthless.** A 4H-structure, wide-stop,
low-frequency trend-continuation system is a real, sane approach, and Revelio's
data says gold on 4H is the *best* corner of it. Their own conclusion was that
the work "was not wasted... we now know exactly where this strategy struggles
and where the first signs of an edge may be hiding."

What it says is that the **numbers being marketed are not the numbers the
strategy produces**. Roughly 3.8%/yr against a 53.8% drawdown is not "fuck you
money." It is worse than a savings account for a decade, with the volatility of
a leveraged fund.

So, in order:

1. **Do not fund a live account.** The OANDA practice account is free and the
   bot already paper-executes there. Use it.
2. **Know what your risk setting does before it fires.** It is currently 10%
   (Sci's stated default, operator's call). `python3 scanner.py --risk 1` runs
   the identical method at 1%. At 10%, four straight losses leaves 66% of the
   account; at 1% it leaves 96%. The scanner prints this ladder on every start.
3. **Collect 50+ closed 4H gold trades**, then `python3 trade_stats.py`. If
   expectancy is negative there, it will be negative with real money, except
   real money also charges you spread and swap.
4. **Re-run `python3 compound_reality.py --from-demo`** and let your own record
   replace both his claims and Revelio's backtest. Your fills, your broker, your
   execution.
5. **Expect the drawdown.** Four losing years in a row happened to a
   *backtest*. Decide now, before you are in it, whether you would still be
   following the method in year three of losses. Most people discover they
   wouldn't — and that is what actually blows accounts, not the strategy.

## 5. What would actually settle this

The new 4H→1H version is **untested by anyone**, including Revelio (they tested
the older 15m/5m variant). This repo has the detector; it does not yet have a
backtester. The obvious next step is a historical walk-forward on XAUUSD 4H/1H
that answers:

- the swing window (`left`/`right`) he never specifies — **the biggest
  unvalidated parameter in this bot**;
- entry on 1H **body close** (Sci) vs. **touch of the level** (Revelio's winner);
- 4H structural stop vs. tighter 1H stop;
- whether the no-trade-zone gate actually filters anything, or just delays entry.

Say the word and I will build it. That is the only thing that turns this from
"trust him" vs. "trust his critics" into a number you measured yourself.
