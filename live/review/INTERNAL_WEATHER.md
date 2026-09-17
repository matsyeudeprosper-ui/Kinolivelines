# Internal weather — measured, not copied (2026-09-17)

Owner: "do you think the internal structure could have its own weather" —
then: "build it that way, but please measure the distribution first and set
boundaries like you suggested."

## The main gauge was misleading a half-manual trader
Walking the chart every 2 h for 46 h (`int_weather.py`):

| | |
|---|---|
| samples where the MAIN weather said "endormie" | 22 of 23 |
| of those, the internal structure was active | 12 |
| the two disagree | 13 of 23 (57%) |

The badge said "not worth trading" for two days while the structure the
trade tool actually uses was flipping.

## The obvious metric fails
A rate gauge copied from the main one does not work. Over 13.4 days, 641
samples (`int_flip_dist.py`, `int_metric.py`):

| metric, per 2 h | zero | median | p90 | max |
|---|---|---|---|---|
| internal flips | 86% | 0 | 1 | 3 |
| all internal events | 83% | 0 | 3 | 7 |
| internal breaks (dots) | 82% | 0 | 2 | 5 |

Every candidate reads "asleep" four times out of five — the same failure as
the main gauge, for the same reason. My guess beforehand was that internal
flips would be MORE frequent than main ones. They are not.

## What works is a state, not a rate
For a half-manual trader the question is "is there something to trade right
now". Measured over the same 641 samples (`int_state_dist.py`):

| state | share |
|---|---|
| cassure en vue (break anticipated, pullback confirmed) | 7% |
| bascule armée (CHoCH fired, waiting on its BOS) | 9% |
| en formation | 5% |
| rien à trader | 78% |

21% actionable. The 78% is honest and it is the point: it stops the chart
being watched for nothing.

## Why the two gauges are complements by construction
The internal window is anchored at the MAIN protected dot, which moves on
every main break — about hourly when the main structure is working. So the
internal window keeps resetting and holds no structure. When the main goes
quiet the window stretches and the internal structure fills out. Each gauge
is loudest when the other is silent.

## Shipped
`int_state` is published by the feed, so the chart and the app read one
value. The chart badge appends it only when it has something to say
(🎯 cassure / ⚖️ bascule); the card carries the full wording on its own row.
Verified live: feed and card both `ready`, main gauge `endormie`.
