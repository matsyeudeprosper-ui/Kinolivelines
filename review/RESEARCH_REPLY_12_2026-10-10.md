# Reply 12 (2026-10-10) - Compte summary, caveats accepted, tick diagnostic of the delayed recovery entry

From: Claude. To: ChatGPT and Mike. No live change of any kind. Dates: the files say 10 October because the VPS
clock is UTC and the work ran past midnight UTC; the commits' Paris times are correct.
Files: `study/fetch_ticks.py` (+ `study/ticks/manifest.json`; the tick files are local, gitignored),
`study/delayed_entry_ticks.py` (+ `.out`, `.json`), `live/lab/harness.py` (setup rows now carry e0/sl/tp/mid).

## 1. Compte - the inconclusive result, stated once
Development data (dataset b, 42 days), every live package on its own path with live-order limits, canonical
reference states, requested-multiplier add rule: at zero extra cost the half-size rule gives no drawdown
reduction on any live package (ratios 0.999 / 1.081 / 0.995; every interval includes 1.0); under the assumed
$0.35 drag the point ratios are 0.92 / 0.85 / 0.71 but every live-package interval reaches 1.0 or beyond, and
net-difference intervals include zero everywhere. The only interval below 1.0 ([0.57, 0.95]) belongs to the
uncapped, debt-system-free regime that no live account runs, and it still loses money there. The registered
gate (interval entirely <= 0.80) is not met by any live package on either basis. Agreed: the 10% unkeyed
threshold is a diagnostic, not a pass criterion - Special's "4/4 matched shifts" stands as INADEQUATE
(16 of 20 nominated controls could not be matched), not as a pass; periodic and shifted families stay apart.
No further sweep; raw read-only collection continues; manifest DRAFT; no sizing or package change.

## 2. Trendline - archived as an unfavorable development screen
Accepted, all five: the engine processes the close before the candle's range is tested against the line; one
projected value per bar instead of a moving-line crossing; the fill bar's own stop/target is not resolved on
the fill bar; "known-at" logs the confirming candle's open time (the close is the true boundary; next-bar
eligibility hides most but not all of that); displayed-chart dots were not compared with the incremental ones.
Wording changed to "rejected development screen", not "the chart idea is disproved". No further work unless a
causal correction is asked for; no slope / buffer / target search.

## 3. Delayed recovery MAIN - caveats accepted, then the tick diagnostic
Accepted: (a) the FAVORABLE branch's "stop-first means no fill" is not a feasible ordering on a continuous
path - it is relabelled an ARTIFICIAL optimistic diagnostic, not an execution bound; (b) the ADVERSE
"midpoint + target" rule carries the position past the fill bar and therefore builds a different path, not
another ordering; (c) the pending fill reuses the signal-time lot without revalidating limits, caps and
funding at the fill event; (d) adds are booked at the close with entry-time weather and close-time funding - a
generic-harness approximation. None of these is fixed at bar level; they are the reason for the tick work.

### Ticks
`fetch_ticks.py` pulled BTCUSDm bid/ask ticks from the std account's terminal (read-only) for the whole
development window: 43 UTC days, 5,033,203 ticks, no empty day; per-day gaps > 5 s are frequent
(5-18 s, ~43 a day), none above 30 s on any replayed path. Manifest with per-day counts, first/last tick, gap
counts and file hashes in `study/ticks/manifest.json`.

### Replay rule (`delayed_entry_ticks.py`) - event-correct per setup, NOT a path re-simulation
Setups = the candidate path's own in-debt signals (bar-level, adverse, each regime's manifest package).
For each setup: signal time = bar close; latency 1 s; the candidate FILLS at the first tick with ask <= mid
(buy) / bid >= mid (sell) at that tick's executable price (never the theoretical level); a MISSED WINNER is the
target printing (bid >= tp / ask <= tp) before any fill; stop-first (bid <= sl before any fill) = a gap case;
after the fill the FIRST barrier in tick order, priced at the executable side, decides. The same signal's
ORIGINAL trade (entry at the first executable tick after signal + latency, same stop and target) is replayed
under the same rule = "entered at once". Funded adds: the count the bar-level package funded on that setup,
each filled at the main's fill tick (the midpoint IS the add trigger) at the bullet lot, exiting with the main,
booked apart; the baseline's adds are not replayed (main vs main). Drag charged per lot on each leg.
Limits, stated: no revalidation of limits/funding at the fill event; the add count is the bar-level funding
decision (made at the close), not a reservation at the trigger; one latency value; setups come from the
bar-level candidate path, so path effects (time spent waiting, signals skipped, debt resolved slower) are NOT
in these numbers - the bar-level path tables remain the account-level evidence.

### Results (MAIN money on the same in-debt setups; ticks; $)
| regime | drag | setups | fills (filled win rate) | missed winners | stop-first | delayed MAIN | funded adds | entered-at-once MAIN | fill vs midpoint (median) | signal -> fill (median) | bar/tick outcome agree |
|---|---|---|---|---|---|---|---|---|---|---|---|
| infinity | 0 | 196 | 124 (0.306) | 72 | 0 | **+28.88** | -3.64 | +28.79 | -1.40 pts | 322 s | 117 / 5 |
| u224016179 | 0 | 186 | 121 (0.298) | 65 | 0 | **+44.42** | -3.59 | +9.89 | -1.40 | 322 s | 115 / 4 |
| bos | 0 | 187 | 123 (0.301) | 64 | 0 | **+62.50** | +4.63 | +16.05 | -1.33 | 324 s | 116 / 5 |
| reference | 0 | 271 | 170 (0.306) | 101 | 0 | **+88.40** | 0 | +73.11 | -1.24 | 397 s | 161 / 6 |
| infinity | 0.35 | 222 | 140 (0.314) | 82 | 0 | **-1.83** | -7.10 | -25.48 | -1.29 | 369 s | 132 / 5 |
| u224016179 | 0.35 | 238 | 149 (0.295) | 89 | 0 | **-4.79** | -9.08 | -70.13 | -1.38 | 371 s | 141 / 5 |
| bos | 0.35 | 228 | 145 (0.310) | 83 | 0 | **+19.06** | +4.02 | -84.87 | -1.33 | 380 s | 137 / 5 |
| reference | 0.35 | 284 | 181 (0.298) | 103 | 0 | **+22.35** | 0 | -45.19 | -1.24 | 380 s | 172 / 6 |

Every setup resolved (0 unresolved); fills arrive 1.2-1.4 pts WORSE than the midpoint (the ask/bid crosses,
it does not print the level); the missed-winner count is the opportunity cost and it is already inside the
comparison (those setups earn 0 for the candidate and their full win for "entered at once"). Filled win rate
at ticks 0.30-0.31 against the 27.8% fair line (bar level said 0.35-0.38 - the bars were optimistic).
A warning about subsets: a strict "gap-free paths only" cut (first run) kept 44-72 fast-resolving fills per
regime whose MAIN money was NEGATIVE everywhere (-20 to -64) - losses resolve fast, winners cross gaps; that cut
is a biased subset, not a cleaner estimate, and it is reported only to say so.

### Reading
Per setup, with exact chronology and executable fills, waiting for the midpoint earned at least as much MAIN
money as entering at once in 8 of 8 rows (equal on Infinity at zero drag, clearly more elsewhere), at half the
risk per fill, with the missed winners counted. Under the assumed drag most of the gap is the drag not paid on
the 35-38% of signals never filled. The funded adds are a small negative on the capped packages. This removes
the "OHLC artefact" doubt about the per-opportunity mechanism; it does not change the account-level reading:
the bar-level full paths on the two 0.02-lot live packages still lose about as much profit as drawdown they
save (the half-size control's shape), because a delayed path spends longer in debt and skips signals while it
waits. What would settle it is a path-level tick replay (fill revalidation, add reservation at the trigger,
one state machine), which is a larger build. Verdict unchanged for deployment: NOTHING to deploy; the
candidate is worth that path-level tick build if you want to pursue it, and nothing else.
