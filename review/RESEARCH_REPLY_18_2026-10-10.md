# Reply 18 - the owner's trend-following filter, replayed on Valère / Infinity (2026-10-10, evening)

From: Claude. To: ChatGPT and Mike. Development test only - nothing here touches a live setting or the frozen 42-day
delayed-entry study. Script `study/tick_engine_pbgate_sticky.py`, results `study/tick_engine_pbgate_sticky.json`.

## 1. The live change (request 1) - done before this test
`live/pb_gate.py` mode `trend`: an unknown pullback trend or a missing last BOS now PAUSES entries (codes `no_structure`,
`no_last_bos`), no permissive fallback; entries resume when a valid structure exists. The older modes keep their old
behaviour for the replay record. Reference demo unchanged (gate off). Live since the bot restart at 17:35 UTC
(commit `f2fc49c`). The replay below uses exactly this function.

## 2. What was replayed
* **Data**: dataset b, 42 days (2026-08-28 22:54 -> 2026-10-09 15:07 UTC), 4,869,156 valid bid/ask ticks, 59,999 M1
  bars; the three-arm tick engine (signal 1 s, execution 1 s, fill at the first executable quote, MTM at every quote).
* **Regime**: Infinity ("Valère - $3 par jour"), development balance 175.70, package snapshot from
  `compte_frozen_manifest.json`: base lot 0.02 scaled with balance (ref 200), **daily cap $3 ON with its adaptive
  recovery rules** (waived in debt as the package says; the manual "continue today" override does not exist in the
  engine), debt gate ON with the CURRENT allowance (FLIP + 1 continuation in debt, dot-touch re-arm), kill -60,
  nervosity brake OFF, movement brake ON, adds ON (max 3), jar ON, RR 0.8, series 2, internal entries OFF, risk fit 0,
  max risk 10 %, recovery bullets OFF, eq_half OFF. Both arms identical except the filter.
* **Costs**: the actual bid/ask at the fill (drag 0.00), and the same plus $0.35 per 0.02 lot (drag 0.35).
* **Structure, causal and sticky**: a bar-by-bar walk of the whole dataset; at each bar the feed's own build -> engine
  runs over the 8000 bars ending there, its structure times join the sticky set (closed candles only, pruned to the
  window), and at each of the 857 opportunity bars the pullback view is built from that set - the same code path the
  live feed runs since this evening. States: 690 of 857 opportunities had a pullback trend, 683 a last BOS.
* **Gate order**: the live one (review 16 pipeline) - kill, awake, used-level dedupe, weather, continuation allowance,
  day cap, geometry, THEN the pullback filter; a refusal by the filter has already consumed the level and the allowance
  as the live `enter()` does.
* **Arms**: `filter_off` = the package as is; `trend` = the live rule (buys only with a bullish pullback trend AND above
  its last BOS, sells the mirror, pause on wrong side / unknown trend / missing last BOS); `trend_nopause` = sensitivity
  only (the same rule with the old permissive fallback on unknown / missing structure).
* NOT the morning's numbers: those were strict-direction without the last-BOS condition, on a rebuilt (non-sticky)
  structure. They are not comparable and are not used here.

## 3. Results (Infinity, 42 days, $ at the development balance)
| cost | arm | trades | win rate | profit factor | net | closed DD | floating DD | 1st half | 2nd half |
|---|---|---|---|---|---|---|---|---|---|
| spread only | filter OFF | 202 | 54.5% | 1.14 | **38.49** | 56.78 | 58.30 | 36.60 | 1.86 |
| spread only | **trend (live rule)** | 50 | 68.0% | 1.61 | **24.46** | **14.43** | **19.24** | 14.48 | 9.99 |
| spread only | trend, no pause (sensitivity) | 102 | 61.8% | 1.36 | 33.09 | 14.99 | 20.01 | 16.19 | 16.88 |
| + $0.35 / 0.02 lot | filter OFF | 239 | 55.2% | 0.91 | **-24.66** | 54.99 | 56.12 | 19.53 | -44.16 |
| + $0.35 / 0.02 lot | **trend (live rule)** | 52 | 69.2% | 1.44 | **+21.27** | **18.93** | **21.03** | 7.11 | 14.18 |
| + $0.35 / 0.02 lot | trend, no pause (sensitivity) | 111 | 63.1% | 1.14 | 15.45 | 18.93 | 21.08 | 0.35 | 15.09 |

Refusals by the filter (signals that reached it after every ordinary gate), `trend` arm:
| cost | against the direction | right direction, wrong side of the last BOS | no pullback trend | no last BOS |
|---|---|---|---|---|
| spread only | 119 | 67 | 120 | 2 |
| + $0.35 | 120 | 70 | 118 | 2 |
(the no-pause arm refuses 125 / 71 and 115 / 68 on direction / wrong side and lets the 120 / 118 "no trend" signals through)

## 4. Reading
* **Risk**: the filter cuts the closed drawdown by three quarters (56.8 -> 14.4 and 55.0 -> 18.9) and the floating
  drawdown by two thirds, at both costs.
* **Money**: at spread only it gives up a third of the net (38.5 -> 24.5) for that; under the nominated cost it turns a
  loss into a gain (-24.7 -> +21.3) because it removes most of the cost-paying trades. Per trade: $0.19 -> $0.49
  (spread only), -$0.10 -> +$0.41 (with drag).
* **Halves**: both halves positive in both cost cases for the live rule; the unfiltered account made almost nothing
  (+1.86) or lost (-44.16) in the second half.
* **The pause on missing structure** (the owner's "no permissive fallback"): it removes ~120 signals. At spread only
  those signals were worth +8.6 net (33.09 vs 24.46) - so the pause costs money when trading is cheap; with drag they
  were worth -5.8 (15.45 vs 21.27) - the pause helps when trading costs. Drawdown is the same either way. The pause is a
  cost-dependent choice, not a risk choice.
* **Activity**: 50 trades in 42 days, about 36 a month - a quarter of the unfiltered count and below the owner's own
  100-trades-a-month bar for a NEW strategy. Here it is a filter on an existing one, but the forward verdict will need
  patience: at this rate 100 filtered trades take about three months.

## 5. Verdict - B (keeps what it promised on development data; confirm forward)
The rule does what the owner asked for: it trades with the pullback structure only, beyond its last break, and the
replay says that costs profit when trading is cheap and makes profit when trading costs, with a drawdown a quarter of
the size either way. Caveats that keep it at B rather than A: 50 trades (one bad week moves every figure); one
development window that has been used for every decision this week; the structure is the sticky one the feed adopted
only this evening, so the forward data will be the first real test of it. It is already live by the owner's decision;
nothing in this replay argues against that, and the forward observation should run as it is, without retuning.

## 6. Next (GPT's second request)
The four-variant comparison (recovery allowance current / all eligible BOS x daily cap ON / OFF, trend filter in all
four) is running on the same saved structure: `study/tick_engine_pbgate_allowance.py`.
