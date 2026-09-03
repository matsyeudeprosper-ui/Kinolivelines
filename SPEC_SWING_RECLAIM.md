# SPEC: Swing Reclaim entry — user's idea, 2026-08-13

*Not preregistered before the first run (first-pass exploratory measurement,
done at the user's request) — recorded here after the fact for the closed-
idea record, same as the other SPEC_*.md files.*

## Hypothesis (user's own words)

"Buy when price pulled back at least 1 brick, then return to hit the last
high. For sell, mirror the buy setup."

## Definition used

Same renko walk as the rest of the harvest family (price-scaled 50-point-
equivalent brick, reversal = 2 bricks, from `study/renko_clean.py`). A swing
HIGH is the last brick close of an up-run, confirmed the instant the
down-reversal brick prints — which by construction has already pulled back
>=2 bricks (satisfies "at least 1, could be more" for free). From
confirmation on, the first bar whose intrabar high touches back up to that
swing high fires a BUY. Swing LOW is the mirror, fires SELL. Signal is
consumed on firing (won't refire until a fresh swing forms and gets
retested again).

This is a different mechanism from `SPEC_HHLL_RENKO` (a FILTER that gates
whether to take the day's reversal-brick trade) and from
`MEASURE_BOS_RETRACE` (raw continuation-after-break statistics). This is a
standalone entry trigger that generally fires several bars after the
reversal that created the swing, once price has round-tripped back to it.
Code: `study/pullback_retest.py`.

## Test

Same engine as `study/renko_clean.py` (TP 5 bricks, recovery trigger 3
bricks, cap 4, 0.01 lots, $1,000 start), BTCUSDm H1, 2022-01-01 onward
(4.6 years — same data-availability floor as the rest of the harvest
family; M1 only covers ~55 days of broker history).

Three arms: **A0** (live bot, every reversal brick), **F** (Swing Reclaim),
**R** (random entries, rate-matched to F's signal count, 3 seeds averaged).

## Result

| | A0 | **F (Swing Reclaim)** | R (random, matched count) |
|---|---|---|---|
| Ended ($1,000 start) | $584.10 | **$590.89** | $164.83 (2 of 3 seeds died) |
| Worst drawdown | 66.7% | **86.1%** | 101-103% |
| Worst single cycle | −$160.96 | **−$316.90** | −$159 to −$363 |
| Cap-out (loss) cycles | 7%, avg −$27.61 | 4%, avg **−$46.83** | 6-7% |
| Signals | 10,638 | 9,380 | 9,380 |

F ends $6.79 ahead of A0 on $1,000 over 4.6 years — noise, not an edge.
Both comfortably beat rate-matched random timing, which just confirms the
underlying reversal structure isn't pure noise (already known from A0
alone). Waiting for the retest trades a few more losses for fewer, bigger
ones: 20 points deeper max drawdown, worst single cycle nearly double A0's.

**VERDICT: KILL.** Same family as `SPEC_HHLL_RENKO` and
`MEASURE_BOS_RETRACE` — a third independent death for "wait for structure
to agree before entering" on this instrument.

## Observational notes (raw entry characteristics, not part of the P&L
verdict above — these describe the SIGNAL, not the money-managed strategy)

Measured on all 9,384 Swing Reclaim signals with a forward window
available, entry priced at the next bar's open (same alignment as the
engine above), no TP/SL applied — pure price-path measurement.

**How far it runs before it turns (peak favorable move, 72h window):**
mean $20.45, median $13.15, reached in ~30h on average.

**How far it gives back after the peak (same 72h window):** giveback ≈
100% of the peak on average; **90.3%** of trades fall all the way back to
breakeven or worse within 72h of peaking. This is why a small, fast target
outperforms holding for the bigger move — matches `HARVEST_SPEC.md`
section 8 (every larger TP size already tested loses money).

**Reaches at least $1 favorable, at some point (500h window):** 98.3% of
trades (161 of 9,384 never do). Median time to $1: <1h. Worst case ever
seen in the whole 4.6 years: one trade peaked at exactly $0.00.

**Max adverse move endured BEFORE reaching that $1** (for the 9,223 trades
that did reach it): mean **$4.26**, median **$1.86** — bigger than the $1
target itself. Only 32% of trades reach $1 having endured less than $1 of
adverse move first; only 0.5% go straight there with zero drawdown. The 161
trades that never reached $1 endured a much larger adverse move first
(median $85.87) before the window ran out.

**Reading these together:** the entry usually eventually works (98% reach
$1, most within an hour), but the typical path there is choppier than the
$1 target itself — you're often underwater for more than $1 before the
trade turns your way. Consistent with the P&L verdict above: nothing here
implies the entry is low-risk, only that it's not *directionless* noise.

**Max adverse move before reaching $2.50** (the live bot's actual TP,
5 bricks) — same 500h window, same 9,384 signals:

| | reaches $2.50 | never reaches $2.50 (window runs out) |
|---|---|---|
| count | 8,962 (95.5%) | 422 (4.5%) |
| avg adverse move first | **$6.82** | $89.53 |
| median adverse move first | **$2.80** | $77.53 |
| worst ever | $169.49 | — |
| reaches $2.50 with < $2 of pain first | 41.0% | — |
| reaches $2.50 with zero drawdown first | 0.4% | — |

Same shape as the $1 case, scaled up: reaching the bot's actual $2.50
target usually costs more pain ($2.80 median) than the target is worth
before it turns. Bigger target, bigger typical drawdown first — consistent
with why this project's earlier TP-size sweep (`HARVEST_SPEC.md` section 8)
found every size loses money the same way.
