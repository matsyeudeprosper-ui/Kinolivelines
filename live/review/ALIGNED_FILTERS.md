# Filters on aligned internal trades (2026-09-17)

Owner: "any other filters that increase their win rate? Like the trading
session London New York Asia". 223 aligned internal trades over 42 days,
same simulation as `main_vs_int.py`. Script `filters.py`.

**Sixteen buckets were tested, so some will look good by luck. Every one is
reported, and the survivors were put through two controls: a permutation
against the same trade pool, and a RANDOM-DIRECTION control at the same
instants with the same stop widths — because the market rose 18.7% over
these 42 days and a long bias reads as edge.**

## Reference
223 trades, 53% win, −0.048 R. Halves disagree (−0.12 / +0.03).

## What the raw numbers said

| bucket | n | win | expectancy | halves agree |
|---|---|---|---|---|
| Londres 07-12 UTC | 65 | 65% | **+0.163** | yes |
| NY 16-21 UTC | 44 | 41% | −0.264 | yes |
| Asie 00-07 UTC | 61 | 49% | −0.115 | no |
| achats | 115 | 61% | +0.096 | yes |
| ventes | 108 | 44% | −0.200 | yes |
| jeudi | 29 | 79% | +0.428 | yes |
| samedi | 21 | 29% | −0.486 | yes |

## What survived the controls

| candidate | permutation | random-direction control | verdict |
|---|---|---|---|
| **Londres 07-12** | top 1.4% | real +0.163 vs random median −0.031, **0 of 12** reached it | **SURVIVES** |
| achats | top 0.6% | real gap +0.296 vs random median **+0.298**, 6 of 12 reached it | pure drift |
| NY 16-21 (bad) | bottom 3.5% | 12 of 12 random draws matched it | not structural |
| Asie 00-07 (bad) | — | 7 of 12 matched it | not structural |
| jeudi | top 0.1% | not run; n=29 across 7 day-tests | treat as noise |

The buy bias is the cleanest negative result here: random directions
reproduce the buy-minus-sell gap to within 0.002 R. All of it is the +18.7%
market move.

## The one filter that stands
**London, 07:00–12:00 UTC (09:00–14:00 Paris).** 65 trades, 65% win,
+0.163 R, positive in both halves, and no random-direction draw came close.

Cost: frequency falls from 5.3 to 1.5 aligned trades a day.

## Caveats that must travel with it
- 65 trades is a small sample; the 2-SE band is ±0.215, so +0.163 does not
  clear zero on its own.
- 42 days is one regime, and a strongly rising one.
- Sixteen buckets were tested. Surviving three controls is meaningful but
  not the same as a preregistered single test.
- **Nothing here is deployed.** It is a lead to watch forward, not a rule.
