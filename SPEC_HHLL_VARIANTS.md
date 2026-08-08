# SPEC: HH/LL definition variants (user's request, 2026-08-08)

*Preregistered before any run. Follows SPEC_HHLL_ENTRY, which the plain
3-bar version failed (1/3 timeframes, worse than random thinning on M15).
The user asked to try other definitions of "structure agrees", including
swing/reversal-candle points on the normal candle chart.*

## Design: selection then validation — the multiple-comparisons tax

Five definitions is five chances to get lucky. So: **selection on the FIRST
half** of each timeframe's bars, one winner picked by a fixed rule, then
**one-shot validation on the untouched SECOND half**. No definition sees the
validation data before the pick. No re-picking after validation.

## Definitions (fixed here; numbers are not tunable afterwards)

All computed on the trade timeframe's own CLOSED candles at the signal bar j,
using only bars <= j. Pivots use strict k-bar fractals (unique extreme in the
window) and count as known only from bar i+k (confirmation lag — no lookahead).
New cycles only; recovery adds unchanged; arm="same".

- **D2 pivotHH k=1** — last two confirmed 3-bar pivot highs ascending -> BUY;
  last two pivot lows descending -> SELL. (The user's HH/LL read off swings.)
- **D3 pivotHL k=1** — last two confirmed pivot LOWS ascending (higher lows)
  -> BUY; last two pivot HIGHS descending (lower highs) -> SELL. (The
  "reversal candle" version: a pivot IS a reversal candle.)
- **D4 pivotHL k=2** — D3 with 5-bar fractals (stronger reversal candles).
- **D5 trend k=1** — BUY needs D2-buy AND D3-buy (HH and HL); SELL needs
  LL and LH. Full trend structure.
- **D6 donch10** — BUY if h[j] is the 10-bar high; SELL if l[j] is the
  10-bar low. (Structure agreement as raw extremes, no pivot logic.)

D1 (plain 3-bar, already killed) is printed for reference only and cannot be
picked.

## Selection rule (fixed)

On the first halves of M1/M5/M15, each definition runs 6 anchors vs A0 and vs
a rate-matched random filter (its own measured accept share, seed 0).
**Qualify:** (F − R) mean > 0 on at least 2 of 3 halves.
**Pick:** the qualifier with the largest sum over the three halves of
(F − A0) mean. Ties -> the earlier definition in the list above.
No qualifier -> the spec CLOSES with no validation run.

## Validation (one shot, untouched second halves)

Same survival criteria as SPEC_HHLL_ENTRY, all required:
1. winner beats A0: mean > 2SE and >=5/6 anchors on >=2 of 3 timeframes,
   never losing >2SE on the third;
2. winner beats R (3 seeds averaged) the same way;
3. accept share 20–80% somewhere.

Kill: anything less. One validation run, no second pick.
