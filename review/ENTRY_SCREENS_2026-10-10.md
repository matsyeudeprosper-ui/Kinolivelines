# Entry screens, development only (2026-10-10) - two briefs, one table each

From: Claude. To: ChatGPT and Mike. Research only; no live change; no Compte; no sweep.
Code: `live/lab/harness.py` (modes `delay_main_mid`, `delay_order`, `entry_mode tl / tl_h`; `pnl_main` / `pnl_add`
in every trace; `DEBT_MAIN_MULT` floored to the 0.01 step), `study/entry_screens.py` (+ `.out`, `.json`, rows cache).
Data: dataset b (closed M1 bars, sha 594a3275fb4a3c1d), spread 7, drag $0 / $0.35 per 0.02 lot. Each arm = the
account's full manifest package path (live-order limits, own debt/jar/caps/balance), 4 regimes. Generic harness
baseline unchanged after the patch (109.29 / 63.69 / 272). Bar-level fills: a bar touching a level is the fill
quote (or the open when the bar gapped through it); no ticks.

## Brief A - delayed recovery MAIN, original stop and target kept
Candidate: in debt (> $0.50) the MAIN waits for the recovery midpoint (entry - stop)/2; original SL/TP; one
virtual setup at a time; no other signal while it waits; cancelled with a "missed winner" if the target prints
first. Same-bar ambiguity: ADVERSE = the fill counts and the same bar's stop counts / the same bar's target does
not; FAVORABLE (diagnostic) = stop-first means no fill, target-first a win. Control = recovery MAIN half-sized at
the original entry, floored to 0.01 (achieved cut: 50% on 0.02-lot regimes, **67% on Special's 0.03**).

| regime | drag | baseline net / DD | delayed ADVERSE net / DD | delayed FAVORABLE | half-size control | later half: base -> delayed |
|---|---|---|---|---|---|---|
| infinity (0.02 lot) | 0 | 52.90 / 55.33 | 27.36 / 32.01 | 30.20 / 32.01 | 21.73 / 30.69 | +2.9 -> -1.8 |
| u224016179 cap3 (0.02) | 0 | 62.73 / 73.51 | 38.57 / 39.94 | 34.90 / 39.94 | 41.84 / 31.79 | -3.3 -> -1.9 |
| bos special (0.03) | 0 | 78.24 / 118.75 | 69.38 / 52.31 | 73.72 / 52.31 | 19.14 / 43.62 | -12.5 -> +15.5 |
| reference (0.02, no adds) | 0 | 53.06 / 91.16 | 52.56 / 50.73 | 57.31 / 48.02 | 19.37 / 46.60 | -39.9 -> +14.1 |
| infinity | 0.35 | -21.67 / 60.69 | -10.07 / 37.10 | -3.59 / 27.62 | -12.93 / 44.96 | -52.8 -> -24.7 |
| u224016179 cap3 | 0.35 | -30.52 / 65.23 | -11.99 / 55.01 | -9.20 / 52.10 | -11.61 / 40.83 | -34.2 -> -22.2 |
| bos special | 0.35 | -65.01 / 130.47 | **-12.93** / 85.07 | **+7.63** / 79.75 | -19.46 / 51.56 | -93.7 -> -31.0 |
| reference | 0.35 | -51.59 / 120.00 | **-0.56** / 66.13 | **+9.49** / 62.37 | -27.98 / 60.77 | -85.0 -> -10.8 |

Opportunity attribution (adverse reading; setups = eligible signals met in debt):

| regime | drag | setups | fills | missed winners | ambiguous (mid+stop / mid+tp) | filled win rate (fair 27.8%) | mean MAIN $ per fill | $ gained at fill vs original entry |
|---|---|---|---|---|---|---|---|---|
| infinity | 0 | 196 | 124 | 72 | 5 | 0.36 | +0.23 | 149.85 |
| u224016179 | 0 | 186 | 121 | 65 | 5 | 0.35 | +0.33 | 237.86 |
| bos | 0 | 187 | 123 | 64 | 5 | 0.36 | +0.60 | 365.66 |
| reference | 0 | 271 | 168 | 103 | 8 | 0.35 | +0.54 | 334.83 |
| infinity | 0.35 | 222 | 139 | 83 | 6 | 0.37 | -0.00 | 137.11 |
| u224016179 | 0.35 | 238 | 149 | 89 | 7 | 0.35 | +0.01 | 251.05 |
| bos | 0.35 | 228 | 144 | 84 | 7 | 0.36 | +0.20 | 414.05 |
| reference | 0.35 | 284 | 179 | 105 | 9 | 0.34 | +0.13 | 352.92 |

No setup was still waiting at the end; no stop-first cancellation exists at bar level (a bar at the stop has
passed the midpoint), so "no-fill losers" = 0 under the adverse reading and 4-9 under the favorable one.
Main and add money are booked apart in `entry_screens.json` (adds fire at the same midpoint under unchanged rules).

**Reading.** Filled midpoint trades win 34-38% against the 27.8% fair line, so the conditional expectancy is
positive but small (+$0.0 to +$0.6 of MAIN per fill), and 35-38% of setups run to the target without a fill. On
the two 0.02-lot live packages the candidate is the half-size control in disguise: ~-45% net for ~-40%
drawdown at drag 0, and under drag the control has the smaller drawdown. On Special and the reference regime
it beats the control on net at drag 0 (69 vs 19; 53 vs 19) at a similar drawdown - but the Special control
over-cuts (67%), and under drag both rows FLIP SIGN between the adverse and favorable readings (-12.9 / +7.6;
-0.6 / +9.5). Later halves are negative everywhere except those two regimes at drag 0.
**Verdict: on the live 0.02-lot packages, a risk-reduction technique, not an entry edge. On the larger-lot /
uncapped regimes: NEEDS TICK EVIDENCE before any economic conclusion (sign depends on intrabar order). No
fresh-data test proposed yet; no live change.**

## Brief B - protected-dot projected line, first touch from the trend side
Anchors = the last two confirmed protected dots of the same uninterrupted segment, each logged with candle time,
price and known-at (the confirming bar); segment reset on flip or opposing CHoCH; armed after the second
anchor, touch eligible from the next bar once a close sits on the trend side; first touch only, one trade per
pair; stop = the latest dot; target = package RR x distance; package rules unchanged; the touch is a continuation
opportunity (the debt allowance re-arms on the flip itself). Control = the same line frozen horizontal at arming.

| regime | drag | baseline net / DD | projected line net / DD (trades) | horizontal control net / DD (trades) |
|---|---|---|---|---|
| infinity | 0 | 52.90 / 55.33 | -24.87 / 28.46 (115) | -0.90 / 8.54 (98) |
| u224016179 | 0 | 62.73 / 73.51 | -44.46 / 49.18 (114) | +6.24 / 11.82 (98) |
| bos | 0 | 78.24 / 118.75 | -67.25 / 70.53 (114) | +12.55 / 15.57 (98) |
| reference | 0 | 53.06 / 91.16 | -51.57 / 51.54 (149) | +7.19 / 10.39 (105) |
| infinity | 0.35 | -21.67 / 60.69 | -56.25 / 56.27 (119) | -25.28 / 25.49 (97) |
| u224016179 | 0.35 | -30.52 / 65.23 | -61.55 / 61.59 (93) | -41.97 / 42.30 (97) |
| bos | 0.35 | -65.01 / 130.47 | -65.00 / 65.01 (57, **kill line**) | -50.01 / 50.60 (97) |
| reference | 0.35 | -51.59 / 120.00 | -103.72 / 103.69 (149) | -29.56 / 29.93 (105) |

Diagnostics (same stream for every regime): 857 confirmed anchors, 479 pairs (254 rising, 225 falling, 0 flat),
300 first touches, 4 geometry rejects, 28 gap fills, arming-to-touch median 6 min (2 min .. 2.6 h), line
displacement since arming median +8 pts (-317 .. +1112), stop / spread median 12.8 (min 1.5). Horizontal control:
244 touches, 34 geometry rejects, stop / spread median 7.8. **Causality trap measured: in 307 of 479 pairs the
finished chart shows a touch of the line between the second dot's candle and its confirmation - a touch that
could not be traded; the screen never uses those.** Causal examples with dot time and known-at in
`entry_screens.json["tl_events"]`, e.g. pair (1787962440, 1787962980): anchors known at 1787962860 and
1787963160, armed 1787963160, touched 1787963280 at L 77886.25, stop 77857.15; pre-confirmation touch: yes.
The engine's dots are the live `Struct` itself (the harness steps the same class), so no display-vs-engine
comparison was needed for the screen; the chart feed's batch dots were not compared here.
**Verdict: rejected. The projected line loses on all 4 regimes at both costs (kill line on Special under
drag); the horizontal control only adds that waiting for a flat pullback with a tiny stop is not an edge
either (small plus at zero cost, negative under drag).**

## Not done / limits
Bar-level fills throughout (no bid/ask ticks); no bootstrap intervals on these screens (not asked; rejected
or ambiguous rows do not need them); the display chart's batch dots were not cross-checked against the engine.
