# Does a break's own character predict whether it runs?

**Question (owner, 2026-09-29).** "How do I know a BOS has the power to push?
In chop we hit the stop before the target. Is there an indicator, a sign in
my own data, or news to watch?"

**Answer: no.** Nothing measured here clears a proper control. Details below,
including two near-misses that are worth re-checking when the sample grows.

Script: `review/bos_break_character.py`. Engine hook: `lab/harness.py` `TRACE`
(None by default, so the nightly battery pays nothing for it).

## What was measured

Everything about a break's *context* was already closed on this account:
higher-timeframe alignment, hourly direction, room to target, order book,
funding, positioning, implied volatility, and economic events (E012 separated
winners from losers at AUC 0.50, a coin toss). So this looked at the break
*itself*, over the 42-day replay, 252 closed trades, deployed rules unchanged:

| Feature | Meaning |
|---|---|
| `power` | the breaking candle's range divided by the median minute of the last hour |
| `age` | minutes the broken level had stood, read *before* the engine moves it |
| `touch` | times price came within a tenth of a candle of that level without breaking it |

## Why the control decides everything

A first pass showed a **random number** producing a bucket that wins in both
halves of the period at **+1.26 per trade**. With 84 trades per bucket that
happens by luck. So each feature is scored against **200 random features** put
through identical machinery, and only counts if it beats ~95 % of them.

## Result

| Feature | Best agreeing bucket | Beats random | Verdict |
|---|---|---|---|
| age, oldest levels (23 to 145 min) | +1.82 /trade | 89 % | noise |
| power, on changes of direction only | +1.77 /trade | 92 % | worth another look |
| touch, never approached | +1.60 /trade | 81 % | noise |
| power, all trades | +1.18 /trade | 39 % | noise |
| **a random number** | +1.26 /trade | 52 % | — |

Two things point away from a real mechanism:

* **Power is U-shaped.** Quiet breaks (+1.18) and violent breaks (+0.98) both
  did fine, while the middle lost (-0.10). A real effect is monotone; a U is
  what noise looks like when you cut three buckets.
* **Age points the wrong way.** The *older* levels did better, not the fresher
  ones. That is the opposite of the freshness edge confirmed on the other
  strategy, so it is not a shared mechanism, it is this sample.

## Two facts that are solid and useful anyway

* **Changes of direction:** 122 trades, 68.0 % won, +0.61 per trade.
* **Continuations:** 130 trades, 53.8 % won, +0.76 per trade.

The two halves of the strategy earn in different ways: flips win often and
small, continuations win less often and bigger. This is why removing either
one destroys the edge (see `only_kind` in `lab/CHERCHEUR.md`).

## Traps found while doing this

1. **Two clocks.** The engine's `hi_i` / `lo_i` count *Renko bricks*, not
   minutes. Subtracting them from a minute index produced level ages of 8 to
   25 days and a feature that was really just a clock. Age is now taken from
   the wall time at which the level value last changed.
2. **Reading the level too late.** `step()` moves the level on the very bar
   that breaks it, so the level must be read *before* the call or every age is
   zero.

## What would change the answer

More trades. At 252 trades and 84 per bucket, an effect has to be very large
to clear the control. The two near-misses (age 89 %, power-on-flips 92 %) are
worth re-running when the window holds twice as many trades. Nothing should be
deployed on them today.
