# Tick engine - three arms on one clock (review 13 brief), development results 2026-10-10

From: Claude. To: ChatGPT and Mike. Development evidence only (the window already guided research); no live
change; nothing frozen for a later period yet.
Files: `study/tick_engine.py` (engine), `study/tick_engine.json` (per arm: trades, events, counts),
`study/tick_engine.out`, `study/tick_engine_validation_infinity.md`, `study/tick_engine_stats.py` (+ `.json`),
`live/lab/harness.py` (OPPHOOK / BARHOOK: raw opportunity and per-bar facts, no behaviour change - generic
baseline still 109.29 / 63.69 / 272).

## What the engine is
One chronological pass over 4,869,156 in-window bid/ask ticks (dataset b window, 43 days, hashes verified,
0 invalid quotes). Three arms evolve independently on the same opportunity clock, each with its own debt
(high-water), jar, balance, day cap, kill line, used-level dedupe, continuation allowance, pending setup,
position and funded adds:
* **baseline** - the account's frozen manifest package, market order at the signal;
* **delayed** - the nominated candidate: in debt (> $0.50) the MAIN waits at the recovery midpoint of the setup
  frozen at the signal quote (original stop / target / lot); one pending setup; no other signal while waiting;
  cancelled with a MISSED WINNER when the target prints first;
* **half_main** - original-entry MAIN at half lot in debt (floored 0.01; 67% cut on Special's 0.03): control.
Signals = the harness's own engine on confirmed closed bars (857 raw opportunities, identical for every arm),
with the harness's path gates applied per arm in the harness's order (awake, dedupe, storm / movement,
debt allowance re-armed by the flip itself or a protected-dot touch, day cap waived in debt, kill).
Execution = declared market-order model: eligibility at bar close + 1 s; trigger (midpoint for the delayed
arm, eligibility tick for the others); fill at the first tick >= trigger + 1 s on the executable side; broker
geometry checked at the fill quote (0 rejects occurred); lots / limits / caps revalidated at the fill quote
(live `enter()` order: min balance, 3% fit on the current balance, 10% ceiling on the final lot); barriers =
first tick whose exit side crosses, stop priority on a double cross. Adds = funded AND reserved at their actual
trigger tick (debt / jar / streak / that bar's nervosity, harness arithmetic), filled at the next executable
quote after 1 s, exiting with the main, booked apart. Costs: bid/ask embed the spread; drag per lot per leg.
End of window: open positions marked (none were open or pending at END in any row). Coverage: largest incoming
gap per trade recorded; no trade crossed a gap > 30 s; 5-18 s gaps touched ~half of them (flagged).

## Validation (Infinity end to end, drag 0) - `study/tick_engine_validation_infinity.md`
Engine baseline vs harness bar-level baseline: 177 common signals, outcome agreement 171 / 177 (96.6%);
the $14 net gap (52.90 -> 38.46) is six outcome flips from the live ask-based target geometry (~-$32),
cents of fill realism (~-$2), and offsetting path divergence (17 vs 25 different trades). A second,
independent check recomputed every engine trade from the ticks: all 1,206 Infinity trades exit on a real
barrier crossing of the executable side with the money exact to the cent.

## Results (full account paths; $; closed-trade DD and mark-to-market DD with open exposure)
| regime | drag | arm | net | cc DD | MTM DD | trades | wins | MAIN $ | adds $ (n) | main risk | later half | setups / missed winners | median wait | gap-flagged |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| infinity | 0 | baseline | 38.49 | 56.78 | 58.30 | 202 | 110 | 32.01 | 6.41 (69) | 561 | +1.86 | - | - | 97 |
| infinity | 0 | **delayed** | 38.01 | **26.24** | 27.27 | 143 | 52 | 39.34 | -1.32 (53) | 219 | +10.44 | 174 / 62 | 322 s | 78 |
| infinity | 0 | half_main | 17.71 | 31.90 | 33.33 | 218 | 117 | 6.93 | 10.73 (72) | 416 | -11.03 | - | - | 106 |
| u224016179 | 0 | baseline | 62.24 | 61.10 | 63.83 | 206 | 112 | 54.47 | 7.78 (84) | 840 | +13.90 | - | - | 100 |
| u224016179 | 0 | **delayed** | 48.14 | **32.86** | 34.44 | 141 | 49 | 53.38 | -5.22 (51) | 343 | +4.75 | 167 / 54 | 295 s | 81 |
| u224016179 | 0 | half_main | 34.55 | 33.03 | 34.98 | 229 | 123 | 18.31 | 16.19 (95) | 466 | +2.40 | - | - | 113 |
| bos | 0 | baseline | 68.60 | 117.37 | 120.82 | 181 | 96 | 52.10 | 16.45 (75) | 1268 | +0.30 | - | - | 87 |
| bos | 0 | **delayed** | 84.07 | **40.41** | 46.98 | 146 | 51 | 74.89 | 9.14 (60) | 534 | +24.37 | 181 / 61 | 294 s | 84 |
| bos | 0 | half_main | 14.59 | 45.09 | 47.57 | 224 | 124 | -0.01 | 14.53 (85) | 526 | -19.83 | - | - | 112 |
| reference | 0 | baseline | 60.59 | 84.72 | 89.42 | 296 | 161 | 60.60 | 0 | 1220 | -32.48 | - | - | 146 |
| reference | 0 | **delayed** | 53.75 | **45.97** | 48.20 | 191 | 60 | 53.75 | 0 | 409 | +11.48 | 262 / 98 | 398 s | 111 |
| reference | 0 | half_main | 12.05 | 45.64 | 49.05 | 296 | 161 | 12.04 | 0 | 653 | -16.22 | - | - | 146 |
| infinity | 0.35 | baseline | -24.66 | 54.99 | 56.12 | 239 | 132 | -19.09 | -5.54 (84) | 487 | -44.16 | - | - | 115 |
| infinity | 0.35 | **delayed** | -6.54 | **34.41** | 35.46 | 165 | 54 | 5.47 | -12.03 (69) | 172 | -12.09 | 229 / 81 | 329 s | 100 |
| infinity | 0.35 | half_main | -10.89 | 41.22 | 42.35 | 239 | 132 | -6.40 | -4.46 (83) | 465 | -30.39 | - | - | 115 |
| u224016179 | 0.35 | baseline | -44.82 | 64.69 | 66.30 | 268 | 147 | -53.92 | 9.09 (140) | 892 | -26.13 | - | - | 133 |
| u224016179 | 0.35 | **delayed** | -1.14 | 48.98 | 50.54 | 157 | 50 | 4.28 | -5.43 (69) | 309 | -10.13 | 216 / 77 | 335 s | 91 |
| u224016179 | 0.35 | half_main | -31.30 | **41.22** | 42.35 | 259 | 144 | -23.33 | -7.96 (120) | 498 | -30.29 | - | - | 133 |
| bos | 0.35 | baseline | -72.13 (kill) | 117.02 | 117.37 | 162 | 89 | -80.99 | 8.86 (65) | 902 | -86.02 | - | - | 78 |
| bos | 0.35 | **delayed** | -4.23 | 66.41 | 72.17 | 158 | 49 | -1.85 | -2.37 (82) | 482 | -9.37 | 222 / 78 | 335 s | 96 |
| bos | 0.35 | half_main | -18.55 | **42.52** | 44.17 | 248 | 140 | -26.38 | 7.86 (93) | 535 | -26.36 | - | - | 126 |
| reference | 0.35 | (all three) | not available - the host stopped the run for low memory on this last row; rerun pending | | | | | | | | | | | |
Counts per arm (signals skipped while open / pending, not awake, weather, debt allowance, day cap, rejects,
kills, gap flags) are in `tick_engine.json`; e.g. Infinity delayed at drag 0: 857 signals, 78 skipped with a
position open, 80 while a setup waited, 201 not awake, 125 weather, 42 debt allowance, 126 day cap, 0 rejects.

## Paired block-bootstrap intervals (`tick_engine_stats.py`: 5-day blocks exact horizon, 3 / 10 sensitivities, seed 7, 3000, 0 degenerate; 42 days of SHARED history - rows are not independent)
| regime | drag | arm vs baseline | DD ratio point | CI90 (b5) | b3 / b10 | net diff point | net diff CI90 |
|---|---|---|---|---|---|---|---|
| infinity | 0 | delayed | 0.462 | [0.43, 1.32] | [0.42, 1.24] / [0.45, 1.42] | -0.5 | [-49.2, +34.7] |
| infinity | 0 | half_main | 0.562 | [0.49, 2.14] | | -20.8 | [-77.9, +19.5] |
| u224016179 | 0 | delayed | 0.538 | [0.49, 1.48] | [0.48, 1.38] / [0.50, 1.63] | -14.1 | [-78.4, +25.7] |
| u224016179 | 0 | half_main | 0.541 | [0.47, 1.53] | | -27.7 | [-106.1, +24.8] |
| bos | 0 | delayed | 0.344 | [0.34, 1.52] | [0.33, 1.35] / [0.36, 1.90] | +15.5 | [-117.8, +123.2] |
| bos | 0 | half_main | 0.384 | [0.31, 1.01] | | -54.0 | [-182.4, +61.3] |
| reference | 0 | delayed | 0.543 | **[0.33, 0.73]** | [0.31, 0.76] / [0.34, 0.68] | -6.8 | [-108.9, +81.8] |
| reference | 0 | half_main | 0.539 | [0.50, 0.69] | | -48.5 | [-124.4, +25.4] |
| infinity | 0.35 | delayed | 0.626 | [0.46, 1.17] | [0.46, 1.13] / [0.45, 0.97] | +18.1 | [-38.0, +59.3] |
| infinity | 0.35 | half_main | 0.750 | [0.64, 1.00] | | +13.8 | [0.0, +27.5] |
| u224016179 | 0.35 | delayed | 0.757 | [0.43, 1.17] | [0.43, 1.21] / [0.43, 0.90] | +43.7 | [-17.7, +91.8] |
| u224016179 | 0.35 | half_main | 0.637 | [0.39, 0.89] | | +13.5 | [-47.1, +65.7] |
| bos | 0.35 | delayed | 0.568 | [0.31, 1.80] | [0.35, 1.87] / [0.28, 1.14] | +67.9 | [-71.0, +280.6] |
| bos | 0.35 | half_main | 0.363 | [0.20, 0.91] | | +53.6 | [-18.0, +173.9] |

## Event traces (Infinity, delayed arm, drag 0; `tick_engine.json` "events")
* **Delayed fill:** setup at signal 1787962140 - PENDING mid 77822.56, stop 77774.76, target 77946.84, lot 0.01;
  FILL at 1787962330375 (190 s later) at 77822.78 (the executable ask, 0.22 above the line), debt 0.72.
* **Missed winner:** setup 1788091380 - PENDING mid 78229.41, target 78396.10; MISSED_WIN at 1788091531344:
  the bid printed the target 151 s after the signal without the ask ever reaching the midpoint; 0 money.
* **Funding at the trigger:** ADD_RESERVED for setup 1788090600 at tick 1788091201848: n = 2 bullets with
  debt 0.76, chest 6.64, that bar's nervosity 0.90 - decided and reserved at the trigger tick, filled 1 s later.
  (Debt cannot change while a setup waits - one pending setup blocks every other signal and no position is
  open - so "funding change while waiting" has no instance by construction; what changes is the jar and the
  nervosity between the signal and the trigger, and the reservation reads them at the trigger.)
* **Same-tick double barrier:** counted per arm (`same_tick_both_barriers`); a tick through both the stop and
  the target is a loss. Infinity's delayed arm had none inside its first 400 events; the count is in the JSON.

## Reading
On ticks, full paths, the delayed MAIN cut the closed-trade drawdown by 34-66% at zero drag and 24-43% under
the assumed drag against the baseline, kept the net within -23% / +23% at zero drag (-0.5 / -14 / +15 /
-7), and under drag turned losses of -25 / -45 / -72 (kill) into -7 / -1 / -4. Against the half-size control it
earned more net on every row (7 / 7) at a lower or similar drawdown on 5 and a higher one on 2 (Depenses and
Special under drag, where the control's cut is 50-67% of the lot on every trade and the candidate still risks
half the distance on the fills it takes). The later calendar half is positive for the candidate on all four
regimes at zero drag and the least negative of the three arms under drag. The bootstrap says what 42 days of
one history can say: the drawdown-ratio intervals cross 1.0 on every live package (only the reference regime
at zero drag stays below, [0.33, 0.73]) and every net-difference interval includes zero. Rows share the same
market history; they are not independent confirmations.
**Verdict: the mechanism survives the complete bot replay on ticks - it is more than lower exposure and
costs on these paths - but it is development evidence on a window that guided the research. Nothing to
deploy. If you agree, the next step is the one you named: freeze this implementation (hashes, execution
model, 1 s delays, gap rules, arms, regimes, both cost bases) and evaluate it once on a later untouched
period with a registered horizon, cost model and adequacy rule.**

## Limits
* The reference regime's drag row is missing (host killed the run for memory on the 24th of 24 arm-rows).
* Weather at the add trigger = that bar's nervosity reading (known at the bar's open); the harness's entry
  nervosity is the fallback.
* Signals remain bar-close events (the live bot's cadence); the bullet and main executions are tick events.
* One latency value (1 s + 1 s); the gap flag is a count, no trade needed exclusion (> 30 s never occurred).
