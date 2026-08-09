# SPEC: Big-brick direction gate on harvest new cycles (user's idea, 2026-08-09)

*Preregistered before any run.*

## Hypothesis

Build a SECOND renko series from the same closes with brick = $100 (the next
size up from the trading $50, fixed here - NO size grid, one shot) and the
same 2-brick reversal. A new 50-brick cycle may only open in the direction of
the big series' CURRENT brick direction at the signal bar's close (no
lookahead - both series read the same closed bars). Before the big series
prints its first brick: block. Recovery adds unchanged.

## Prior, stated honestly

Negative. The HTF EMA trend gate died decisively (M5 gate worse than random
skipping, -393, 0/6), rule 9 bans break-following, and the renko HH/HL gate
died at qualification in the other session. What earns the run: brick-scale
alignment is reversal-based rather than EMA-based (a genuinely different
definition of "the bigger picture agrees"), it is the user's direct question,
and the mask engine makes it cheap.

## Arms and criteria (identical to SPEC_HHLL_ENTRY)

- A0 live rule; F big-brick gate; R rate-matched random (seeds 0/1/2
  averaged), 6 anchors, arm="same", M1/M5/M15. The big series is built from
  the full data as fixed context (it does not shift with the small series'
  anchor).
- Survives only if ALL of: F beats A0 (mean > 2SE, >=5/6 anchors) on >=2 of
  3 timeframes, never losing >2SE on the third; F beats R the same way;
  accept share 20-80% somewhere.

Only same-direction alignment is tested. If it fails, the fade direction is
NOT implied and NOT tested. No re-tuning of the big size or reversal count.

## ADDENDUM (2026-08-09, declared BEFORE the H1 run)

Result of the main run: KILLED overall (M1 −80 vs A0 >2SE) — but M15 beat
BOTH controls 6/6 (+1231 vs A0 / 2SE 182, +881 vs R / 2SE 245), the first
M15 rescue in the search that random thinning does NOT explain, and the
second renko-native direction gate to print this signature (SPEC_HHLL_RENKO's
M15 first half was the first). Slow-timeframe brick alignment may be real.

**Out-of-sample check, preregistered here:** the SAME fixed rule ($100 big
brick, rev 2, same-direction gate) on H1 bars — data no brick-gate hypothesis
has ever touched. Survival: F beats A0 AND R, mean > 2SE and >=5/6 anchors,
on H1. Kill: anything less. One run, no follow-up grid on this data.
(Result: WIPED OUT 6/6 on H1. Killed.)

## ADDENDUM 4 (2026-08-09) — the user's "fresh reversal" tweak

New rule (user's, chosen from three formalizations): a $50-series entry is
allowed ONLY while the $150 series' LATEST brick is a REVERSAL brick, and
only in its direction. As soon as the big series prints its next brick
(continuation or flip back), permission ends until its next reversal.
Parameter-free freshness window. Same battery as addendum 3 (A0 / F / R,
6 anchors, M1/M5/M15 + H1). Deployment of the tweak follows the user's
standing forward-run mandate regardless of outcome; the numbers are for the
record and their later judgment.

## ADDENDUM 3 (2026-08-09) — full battery on the DEPLOYED config ($150 gate)

The user corrected the formulation (normal M1-base harvest, gate 3-4x) and
mandated demo deployment regardless of backtest outcome; $150 won the
declared size pick. This addendum runs the standard battery on that exact
config for the record: A0 / F150 / rate-matched R (seeds 0/1/2), 6 anchors,
M1/M5/M15 + the H1 long-data check (M15-window illusions have hit twice).
Same criteria shape as the parent spec. This is measurement, not a
deployment decision — the demo run continues either way; the user decides
with both numbers in hand.
