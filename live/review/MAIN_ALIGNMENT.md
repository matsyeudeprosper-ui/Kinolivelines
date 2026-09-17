# Should the main trend gate internal trades? (2026-09-17)

Owner: "if the main structure is bearish or bullish should it influence our
internal trades in any way, like only take sells when main structure is
bearish?"

## Method, stated before looking
Simulate the owner's own rule on internal breaks: enter at the close that
confirms the break plus one spread (7 pts), stop at the protected level that
break creates, target 0.8R, exits walked on raw M1 with the stop checked
first on any bar touching both. Split by whether the internal direction
agrees with the main trend. **Pass = aligned beats counter-aligned in BOTH
halves.** Script `align_test3.py`.

First attempt caught only flip breaks (33 trades) and the halves reversed -
noise. Capturing every break, flips and continuations, over 28 days gives
221.

## Result

| | n | win rate | expectancy |
|---|---|---|---|
| all internal trades | 221 | 52% | −0.063 R ±0.121 |
| **aligned with the main trend** | 145 | **57%** | **+0.018 R ±0.149** |
| **against the main trend** | 76 | **43%** | **−0.218 R ±0.206** |

Both halves agree: aligned +0.005 then +0.032, counter −0.400 then −0.079.

Permutation control, 2000 shuffles of the aligned label: the real gap of
+0.236 R is matched by chance **3.5%** of the time.

## Reading it honestly
- **Aligned is not proven profitable.** +0.018 R with a 2-SE band of ±0.149
  is indistinguishable from zero. Break-even at 0.8R needs a 55.6% win rate
  and aligned sits at 57%, i.e. on the line.
- **Counter-aligned is clearly worse.** −0.218 R, 43% win rate, and the
  worse side in both halves.
- The gap survives a permutation control at 3.5%, but its 2-SE band
  (±0.254) still straddles the point estimate. Suggestive, not settled.

## Verdict: the gate is a FILTER, not an edge
Taking only internal trades aligned with the main trend removes a losing
subset (76 trades at −0.218 R, about −17 R over 28 days). It does not create
a winning one. This is the same shape as every other result on this account:
things that remove bad trades, nothing that adds good ones.

Consistent with [[mt5_e022_h1_direction_gate]] (a direction gate cut volume
without improving per-trade quality) and [[mt5_e012_htf_context]] (higher
timeframe alignment carried no out-of-sample information) - but unlike those,
this one is measured on the structure the owner actually trades and the
counter side is distinctly bad rather than merely equal.
