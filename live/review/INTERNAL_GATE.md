# The internal structure's awake gate (2026-09-17)

Owner: "find the best weather of internal structure - for the main structure
we found that at least one flip per 2 hours gave best results."

Same 223 aligned internal trades, 42 days. `int_gate.py`.

## The gate: at least one INTERNAL BREAK in the recent past

| | n | win | expectancy | halves |
|---|---|---|---|---|
| reference, all aligned | 223 | 53% | −0.048 | −0.12 / +0.03 |
| **≥1 internal break in 1 h** | 89 | **63%** | **+0.133** | −0.10 / +0.36 |
| none in 1 h (rejected) | 134 | 46% | **−0.167** | −0.19 / −0.14 ✓ |

The window barely matters, which is the reassuring part - it is not tuned:

| window | kept | expectancy kept | rejected |
|---|---|---|---|
| 1 h | 89 | +0.133 | −0.167 |
| 2 h | 100 | +0.116 | −0.180 |
| 4 h | 103 | +0.118 | −0.190 |

## Controls
- **Random direction**, same instants and stop widths: real +0.133 against a
  random median of −0.009, and **0 of 12** draws reached it.
- **Permutation** against the same trade pool: **1.0%**.

## What it really does
Its strength is on the REJECTED side. "No internal break in the last hour"
gives −0.167 R with both halves agreeing (−0.19 / −0.14). The kept side's
halves disagree (−0.10 / +0.36), so the gate is reliable at naming bad
trades and less so at naming good ones — exactly the shape of the main
structure's own awake gate in [[mt5_e007_awake_gate]].

Note the flip-based version fails: "at least one internal FLIP in 2 h" keeps
only 22 trades. Internal flips are too rare (86% of 2 h windows have none).
The internal equivalent of a main flip is a **break**, not a flip.

## Stacking with London
| | n | win | expectancy |
|---|---|---|---|
| London 07-12 alone | 65 | 65% | +0.163 |
| London + the 1 h gate | 29 | 66% | +0.179 |

Barely better, halves disagree, 29 trades. Not worth stacking at this size.

## Status
Not deployed. Two independent controls passed and the rejected side is
consistent, which is more than anything else tested on this account has
managed - but 89 trades over one rising regime is a lead to watch forward.
