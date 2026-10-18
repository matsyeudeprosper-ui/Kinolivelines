# Owl on Bitcoin vs random entries — 2026-10-17

Owner question: "the $51 of BTC is already random control?" — it was not. The 42-day Bitcoin proof had never been
checked against chance (only E011, the old frozen rules on independent years, had random-direction percentiles).

## Run
`python study/random_control_market.py BTCUSD owl 40` through `study/when_free.py` (oct17b), started 20:49 UTC once
the ChatGPT/Codex desktop apps were closed (free RAM 2.5 -> 5.0 GB), 7 320 s. Same bench as the other markets:
`study/markets_tick/BTCUSD` = 60 days of recorded Exness ticks (17 Aug -> 15 Oct 2026), no drag on either side,
each random seed replaces the Owl's opportunities with the same number of random bars / random direction, copying a
real opportunity's stop distance and gate fields. Result file: `study/random_control_owl_BTCUSD.json`.

## Result
| | Owl | 40 random seeds |
|---|---|---|
| net (60 d, before drag) | **+201.49** | median +2.09, p95 +88.61, best +163.45, worst −65.44 |
| trades | 131 | median 100 |
| profit factor | 1.68 | median 1.01 |
| halves | +123.96 / +77.52 | — |
| percentile | **100 of 40 seeds** (p < 1/41 ≈ 2.4 %) | 52 % of seeds positive |

Verdict: **beats chance** on this window. First market to pass the 95th line. Gold (80th / 90th), Nasdaq (85th) and
Dow (80th) remain "within luck".

## Caveats (audit the good result hardest)
- 40 seeds resolve 2.5 %: "100th" means none of 40 beat it, not a p-value of zero. One seed reached +163.
- One 60-day window. E011 showed the old rules losing over independent years; this says the CURRENT rules beat
  random entries over Aug–Oct 2026, nothing about 2024.
- Engine dollars are not account dollars: +201 is the bench before the 0.35 drag (131 × 0.35 = −46) and the engine
  earns about half of what the real account does on the same trades.
- The control's seeds take fewer trades (100 vs 131); same risk per trade, slightly narrower spread for the control.

## In the app
The Robots page attaches `test.ctl` / `test.parent_ctl` from the control file; the Zone de test now shows Bitcoin
"Solide — bat le hasard et gagne sur les deux moitiés", sheet tiles "Contre le hasard 100 / 100", "Hasard, résultat
médian +$2,09". Owner order (verbatim): "no matter what the results comes, we don't change a thing, we don't stop it
from trading." — nothing live was touched.
