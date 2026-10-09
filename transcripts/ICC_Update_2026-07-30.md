# MY ICC UPDATE — Full Method Extraction (Trades By Sci)
Source: https://www.youtube.com/watch?v=p7NKipnkvnU
Channel: Trades By Sci (566K subs) · Uploaded **2026-07-30** · Length **31:11** · 163K views
Chapters: 0:00 Introduction and mindset · 3:51 Defining the no-trade zone · 11:07 Setup execution strategy · 16:14 Trade analysis and intuition
Transcript pulled 2026-10-08. He states this is **part two** of the same material; part one was posted "the other day" and he says "part one might be the same as part two."

> Context in-video: recorded from Turks and Caicos at 2:05pm with the market
> closing in 2 hours, "currently we are in a gold setup... we are up $1.2
> million on gold buys." **That P/L claim is unverified — see CAVEATS.md.**

---

## ⚡ THE HEADLINE CHANGE: 15-MINUTE IS GONE

This is the single biggest difference from the Day-1..Day-14 course this repo was
built on. The old method (METHOD.md) was **markup 1H → correction/entry 15M**.
The new method is **markup 4H → entry 1H**, with only two timeframes total.

> "a lot of people know that now I do not use the 15-minute time frame for
> entries anymore."

> "The reason why I don't use 15-minute time frames for entries is because
> sometimes the volume is a little bit excessive throughout New York session,
> breaks structure a lot on the 15-minute time frame. So a lot of the noise is
> cleared out by trading on the 4 hour and 1 hour time frame."

> "You only need two time frames... Don't confuse yourself with trading. Don't
> over complicate it at all. Like literally don't over complicate it."

**Repo impact:** `scanner.py` `HTF` 1H→**4H**, `LTF` 15M→**1H**.

---

## 1. MARKUP — always 4H, always candle CLOSES

> "I will always go off 4 hour time frame for markup. Still. That has never
> changed."

> "I use candle closes from when I'm marking up because that means to me it's a
> closed deal... A wick to me is not really the same because a wick is like
> price attempted to but failed to do so. I like when everything is certain."

Levels are drawn from **body closes**, not wicks. (`detect_swings(use_body=True)`
in this repo already does exactly this — no change needed.)

## 2. THE NO-TRADE ZONE — his exact construction rule

This is now stated far more precisely than in the original course. Verbatim:

> "current price is at 4,036. Let me go up. Okay, this is my high. Mark. Okay,
> this high was created from here. Okay, that's my low. Boom. And that's it.
> That's literally all I do."

> "Where did it buy from? That's our low. Where did this low create from? This
> high. So once you find the low, go find out where that high was. Vice versa."

**The algorithm:**
1. Start at current price on the 4H.
2. Move to the most recent swing **high** above price → mark it.
3. Trace back to the swing **low** that *originated the move into* that high → mark it.
4. The band between them is the **no-trade zone**.
5. Mirror it for down-moves: price → nearest swing low → the high that pushed it down.

> "If price is in between both of these, this means that this is a no trade
> zone... and I can't trade anything. So now all I got to do is wait."

**Reframing — a no-trade zone is GOOD, not bad:**

> "A no trade zone should not be looked at as bad. A no trade zone should be
> looked at as good because it makes it easier for you to understand where
> price is trying to go."

**Why it works (his buyer/seller model):**

> "When it's in a no trade zone, that means buyers and sellers are in control.
> But when price is breaking above a zone, it's just moving zone to zone to
> zone... In order to place a trade, it has to break past either buyers or
> sellers. Once it breaks past something that lets you know that price has full
> control until it reaches that level again."

**Repo impact:** new `NoTradeZone` dataclass + `no_trade_zone()` in
`icc_engine.py`, wired into `evaluate()` as gate **A2b**.

## 3. SETUPS MUST ORIGINATE FROM A NO-TRADE ZONE

> "Your setup should always start out of a no trade zone." … "Your setup should
> always come out of a no trade zone, whichever way makes sense to you."

Caveat he adds: "this is for beginners, cuz you don't always have to trade out
of it. You can trade the continuation of something." The repo implements the
strict version (must be outside the zone).

## 4. ALERTS ON BOTH EDGES — he trades by alert, not by watching

> "I set a lot of alerts. I live off of alerts... I can't function without them.
> Literally cannot function without them. So everything I see, if I want it,
> I'mma set an alert on it."

Setup: right-click the level → *crossing up* / *crossing down* → **trigger every
time**. One alert at the support of the zone, one at the resistance.

**Repo impact:** this is already the bot's whole design (`scanner.py` on a
15-min cron + Telegram). No change needed — the bot is a better alert engine
than TradingView free tier.

## 5. ENTRY — drop from 4H to 1H and require the two to correlate

> "The 4 hour is going to give me that indication, give me the correction. When
> it comes to entries... if the 4 hour is doing this, it's going to be one
> candle, two candles, three, then coming back is going to be one or two. And
> as it comes down, all I'm doing is when I start to see price back under that
> level, all I'm doing is switching from the 4 hour to the 1 hour."

> "All I'm doing on the 1 hour is making sure the 1 hour looks like this...
> verifying if I see some lower highs and lower lows under this blue line, I'm
> entering a sell **because now the 1 hour and 4 hour match**."

> "As long as the one hour and 4 hour... correlate, I know that the 1 hour is
> building up into the 4 hour."

**The entry trigger, stripped to nothing:**

> "It's literally nothing. All you're doing is going to that 1 hour time frame.
> Oh, price made a new high. It broke above this high. I see that it's bullish.
> It's going back above here. That's it. Nothing else."

> "**The moment that price comes above this blue line, I press buy. The moment
> price comes below this blue line, I press sell. That's it. Nothing else.**"

**The repeat rule survives from the original course:**

> "If price is breaking above a high, take it. If price is breaking below a low,
> take it. **Especially if price has already repeated it once before**, just
> take it."

## 6. STOP LOSS — deliberately WIDE. Size down, don't tighten.

This is a direct reversal of conventional retail advice and he argues it at length:

> "You're so used to traders telling you you got to have the smallest stop-loss
> to be profitable... and they call me a high risk or whatever the case might.
> **I'm protecting my capital regardless because I'm using proper risk
> management for myself.** Right? **If you can't put whatever lot size you want,
> lower your lot. Or you can't put whatever stop-loss you want, lower your lot
> size.**"

> "They're so fixated on having the smallest stop-loss and tight stops... where
> they don't even allow room for their trades to even breathe. They don't even
> allow price to do what it needs to do, because **price can fluctuate as much
> as it wants. As long as it doesn't break structure, it's still valid.**"

> "Nothing makes this invalid. Just because price sold off, that doesn't make it
> invalid. Because remember that 4 hour time frame is where price is trying to
> pick up at."

**Consequence for this repo:** risk stays a fixed **fraction of balance** and the
stop goes where *structure* says, however wide that is. That is exactly what
`size_position()` does — position size is derived from the stop distance, never
the other way round. A wider 4H stop now yields a smaller lot automatically.

**⚠️ Real consequence for gold:** a 4H structural stop on XAUUSD is roughly
**$20–40 wide**, versus the ~$5 a 15M stop used to be. At OANDA's 0.01-unit
minimum, honouring a 1% budget therefore needs a balance of roughly **$25–40**,
not the $12 the old 15M-scale stop implied. `compound_reality.py --min-account`
computes this from the live `size_position()` code.

## 7. INVALIDATION — only a 4H structure break

> "As long as price does not break the levels on the 4 hour time frame,
> everything is a-okay."

He also stresses checking the *opposite* case, which the original course didn't:

> "If I'm looking for an entry point, if I'm looking for a setup, I also have to
> look at the things that could be going against my setup... that correction,
> this level can no longer get broken and I have to pay attention to that
> because that is the level that I need to make sure that my trade is validated.
> **A lot of people only look at what they're looking for and never look at what
> could go against them.**"

## 8. TARGETS & MANAGEMENT — zone to zone, partials optional

> "We'll have our stop loss above here and then we'll target down here where
> that low is."

> "Sellers are always going to be at highs... So price is always going to go
> [zone] here to here. It's going to move a zone to zone."

> "Right now price is stalling at this high. But that's okay. Because at this
> point I could either take partials or I could look for price to push for more.
> **It's up to me at that point.**"

Management is discretionary, not mechanical — the repo keeps `trade_manager.py`
(partials at TP1, runner to the backstop) as the codified version of this.

## 9. FILTERS HE ACTUALLY APPLIED

**Sunday gaps — skipped.** He passed on a valid-looking breakout:

> "The reason why I didn't place this trade is because it was a Sunday. Price
> just opened. It gapped all the way up off of the 6:00 opening on Sunday.
> That's not something I want to get into. **I need New York session to bring
> some volume.**"

Note he explicitly refuses to turn this into a rule: "that's not what I'm
saying. It's just I didn't feel 100% confident... So I stayed out of the
markets. No specific reason of why." → **The repo does NOT hard-code this.** It
is logged as discretionary. `in_session()` already restricts gold to
London/NY windows.

**FOMC.** He entered a trade during an FOMC-driven push, "was floating in profit
for a bit before it sold off pretty heavy," and held because structure didn't
break. No news filter is stated.

## 10. PSYCHOLOGY — "you're going to be the ending factor"

> "I can tell you everything, but you're going to be the ending factor of
> pretty much everything. LeBron James can teach you how to play basketball, but
> doesn't mean that you'll be as good as LeBron James because your work ethic
> might not be the same as his."

> "In order to trade like this, you have to trust the higher time frame. You
> have to trust the basic fundamentals of price doing what it needs to do. If
> price makes a high, you have to trust that it's going to make a higher low.
> **A lot of people can't even trade this way because they don't trust the
> higher time frame and they're rushing to make money.**"

> "Once you place the trade, your money is already on the line regardless. So
> you might as well just put your trust into the whole chart at that point."

> "If I lose, I lose. That's a part of the game... I'm not going to sit here and
> be so scared where I don't take trades or I don't take a risk."

---

## DIFF vs. METHOD.md (what actually changed)

| | Old (Day 1–14 course) | **New (2026-07-30 update)** |
|---|---|---|
| Markup TF | 1H (4H when choppy) | **4H, always** |
| Entry TF | 15M | **1H** |
| 15M | correction + entry | **abandoned entirely** |
| Timeframes used | 3 (4H/1H/15M) | **2 (4H/1H)** |
| No-trade zone | "range = no trade" | **explicit pair: last extreme + the opposite swing that created it** |
| Levels from | swings | **4H candle CLOSES, never wicks** |
| Stop | past correction extreme (15M) | **past 4H structure — deliberately wide; cut lot size, not stop width** |
| Invalidation | structure break | **4H structure break ONLY; "just because price sold off doesn't make it invalid"** |
| Entry confirm | 2nd-time reclaim on 15M | **1H break + 1H/4H correlation + 2nd-time reclaim still honoured** |
| Unchanged | ICC 3-step, alert-driven, partials+runner, patience, "don't chase" | |

## Still OPEN — not answerable from this video

1. **Swing definition.** He never states a fractal window (how many candles each
   side). Reddit's r/Forexstrategy independently flags this as the method's main
   ambiguity: *"Sci doesn't tell us the rules for marking the structure
   points."* The repo keeps `detect_swings(left=2, right=2)`. **This is the
   single biggest unvalidated parameter in the bot.**
2. **How far back to look** for "the low that created that high" when the
   impulse is old. Repo uses the two most recent confirmed swings.
3. **Partial-taking levels.** Explicitly discretionary ("it's up to me").
4. **Position sizing numbers.** He says "proper risk management for myself" and
   never states a percentage. The repo's 1% is our choice, not his.
5. **Whether part one adds anything.** He says it may be identical.
