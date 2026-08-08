# SPEC: Higher-timeframe trend gate on harvest new cycles (user's idea, 2026-08-08)

*Preregistered before any run.*

## Hypothesis

The classic "trade the lower timeframe in the higher timeframe's direction":
new cycles only open in the direction of the higher timeframe's trend.
Trend = last CLOSED higher-TF bar's close vs its EMA(21). Above -> BUY cycles
only; below -> SELL cycles only; recovery adds unchanged. Timeframe mapping,
fixed: M1 entries gate on H1, M5 on H4, M15 on D1.

No-lookahead rule: the HTF bar counts only once fully closed by the time the
entry-TF signal bar closes.

## Prior, stated honestly

Low-to-negative. H1-vs-EMA21 is 0.497 on all bars as a predictor (only 0.645
on outcome-selected big moves, unknowable ex ante); GPT's chart-direction
filter scored 0/11 months on this family. What earns the run: this exact
gate-on-cycles form with the rate-matched random control has not been tested,
it is the user's direct question, and the mask engine makes it cheap.

## Arms and criteria (identical to SPEC_HHLL_ENTRY)

- A0 live rule; F trend gate; R rate-matched random (seeds 0/1/2 averaged).
- Survives only if ALL of: F beats A0 (mean > 2SE, >=5/6 anchors) on >=2 of 3
  timeframes, never losing >2SE on the third; F beats R the same way; accept
  share 20-80% somewhere.

Only the trend-FOLLOWING direction is tested. If it fails, the fade direction
is NOT implied and is NOT tested (that would be a second hypothesis).
One shot, no re-tuning of the EMA length or TF mapping.
