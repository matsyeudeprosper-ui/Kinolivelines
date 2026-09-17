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

---

# RETRACTION, same day (2026-09-17)

The owner asked three questions I had not tested: is the break/flip
asymmetry real, does a 1 h window work on the MAIN structure, and do the two
gates combine. Testing them symmetrically broke the finding above.

## The gate does not survive re-anchoring
The internal window's start was never varied. Anchoring it at the main
BREAK's time instead of the main PROTECTED DOT's time, same gate, same
trades (`anchor_check.py`):

| | anchor = protected dot | anchor = break |
|---|---|---|
| reference | 222 trades, −0.043 | 173 trades, −0.147 |
| **gate open, ≥1 break in 1 h** | 54, 63%, **+0.133** | 77, 51%, **−0.088** |
| gate shut (rejected) | 168, 50%, −0.100 | 96, 45%, −0.194 |

A one-parameter change flips the headline number's sign. **The +0.133 R is
not a result.** This is precisely [[feedback_anchor_noise_floor]] and I did
not apply it.

## What actually survives
The **rejected** side is worse under both anchors, with both halves agreeing
in both cases (−0.10/−0.10 and −0.18/−0.21). "No internal break in the last
hour tends to be worse" holds. "With one, you make money" does not.

## The owner's three questions, answered
1. **Break vs flip asymmetry** — not real, an artifact of what I tested
   first. Tested symmetrically, nothing separates them once anchors vary.
2. **A 1 h window on the MAIN structure** — not "bad results", *no trades*:
   main breaks in 1 h keeps 3 of 129, main flips in 1 h keeps 2. Main events
   are too rare for an hour, which is why its gate is 2 h.
3. **Combinations** — five tested, none holds under both anchors:

| combination | anchor = dot | anchor = break |
|---|---|---|
| internal ≥1 AND main ≥1 | 19, +0.137 | 17, −0.153 |
| internal ≥1 only | 35, +0.131 | 60, −0.070 |
| main ≥1 only | 113, −0.124 | 51, −0.153 |
| neither | 55, −0.051 | 45, −0.240 |

Every positive cell under one anchor is negative under the other.

## What was changed in the product
The card claimed "46% success instead of 63%". That number is withdrawn. It
now reads as an activity indicator with a soft caution, which is what the
evidence supports. The badge and the count are unchanged - they report a
fact, not a claim.
