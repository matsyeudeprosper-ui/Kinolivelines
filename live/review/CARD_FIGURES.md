# Which figures on the card actually feed a decision? (2026-09-17)

Owner: "we don't need to show the spread if it's not used in our decision
making... are we making use of nervosity in the decision as well or is it
just to fill the card? So far I thought you were only looking at the 0/1."

Honest audit of every figure the weather card shows.

| figure | tested? | feeds a decision? |
|---|---|---|
| petits mouvements 0/1h | yes, both anchors | **yes** — the only one that held on the "avoid" side |
| grands mouvements 0/2h | yes (E007, main trades) | yes, in the BOT's awake gate |
| sens ▲/▼ | yes, both halves + permutation | **yes** — aligned beats counter-aligned |
| nervosité vs 24 h | **tested today** | **yes, as a caution** — see below |
| coût pour entrer | **cannot be tested** | it is a cost, not a signal |

## Nervosity: not decoration, but only on the bad side
`nerv_test.py`, aligned internal trades, both window anchors:

| nervosity | anchor = dot | anchor = break |
|---|---|---|
| calme (<0.8×) | 62, 55%, −0.013 | 55, 40%, −0.280 |
| 0.8–1.0× | 69, 64%, **+0.148** | 59, 58%, **+0.037** |
| 1.0–1.2× | 41, 37%, **−0.341** | 40, 42%, **−0.235** |
| agité (>1.2×) | 49, 51%, **−0.082** | 18, 50%, **−0.100** |

**Above 1.0× is worse under both anchors**, across both buckets that cover
it. Below 1.0× is not reliably good: the 0.8–1.0 band is positive both ways
but with very different sizes, and <0.8 flips sign. One band positive out of
four is what chance produces.

So the threshold moved from 1.2× to **1.0×**, where the measurement puts it.
The 1.2 came from the main badge and had never been tested here. Only the bad
side is flagged; the good side reads a neutral "normal".

## Spread: REMOVED 2026-09-17
The owner: "we should remove the spread because it doesn't help the météo."
Correct. The card asks one question - trade now or not - and the spread
cannot answer it, because whether a fixed cost hurts depends on the stop
distance and the card has no access to the stop. It was the only figure on
there with no bearing on the decision.

It survives where it belongs: the trade panel on the chart, which shows the
cost and the stop together, and the bot's own spread-zone veto.

The freed space promotes the two brakes to an accented top row, with the two
context figures plain underneath.

### (superseded) Spread: kept, but reframed
No historical spread is stored, so it can never be tested as a filter on past
trades. It is however a real cost charged on every entry, and the bot has a
spread-zone veto of its own. It stays on the card labelled "coût pour
entrer", which is what it is — a price, not a prediction.

Whether it hurts depends on the stop distance, which the card cannot know.
The trade panel on the chart shows cost and stop together, which is where the
proportion is visible.
