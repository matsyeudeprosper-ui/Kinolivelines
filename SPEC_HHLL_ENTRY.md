# SPEC: Higher-high / lower-low entry filter (user's idea, 2026-08-08)

*Preregistered before any run.*

## Hypothesis

New cycles only: at the reversal signal, require the last 3 CLOSED bars to show
structure agreeing with the trade — BUY needs `high[j] > high[j-1] > high[j-2]`,
SELL needs `low[j] < low[j-1] < low[j-2]` (j = the signal bar, closed by
definition since bricks build from closes). Recovery adds unchanged.

On the M1 run this is exactly the user's formulation. On M5/M15 the same
structure test runs on that timeframe's own bars — M1 history (~55 days)
cannot cover the 27-month stretch (same amendment as the ATR spec).

## Prior, stated honestly

Low. Nearest relatives: GPT's chart-direction filter (0/11 months close-only
over a year) and the 14-null OHLC family. What earns the test: it is the
user's call, it is cheap, and the observer will collect the live version of
the same evidence either way.

## Arms and the control that decides it

- A0 — live rule
- F — HH/LL filter on new cycles
- R — **rate-matched random filter**: accept each new-cycle signal with
  probability equal to F's measured accept share (per timeframe), seeds 0/1/2
  averaged per anchor. If R matches F, the filter is just trading less.

## Survival criteria (all required)

1. F beats A0: mean > 2SE and ≥5/6 anchors on at least two of three
   timeframes, never losing >2SE on the third;
2. F beats R the same way — otherwise it is thinning, not selecting;
3. accept share within 20–80% somewhere (a filter that accepts ~everything or
   ~nothing is untestable and closes as such).

Kill: anything less. No re-tuning the lookback (3 bars is fixed by this spec).
One shot.
