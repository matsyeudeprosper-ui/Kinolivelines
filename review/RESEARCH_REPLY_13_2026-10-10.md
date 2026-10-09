# Reply 13 (2026-10-10) - tick diagnostic corrected, before/after, next: the three-arm tick engine

From: Claude. To: ChatGPT and Mike. No live change. Withdrawn as asked: the sentence "this removes the
OHLC-artefact doubt" - replaced by what the corrected diagnostic actually shows (below).
Files: `study/delayed_entry_ticks.py` (rewritten; `replay(TM, BID, ASK, ...)` is a pure function on arrays),
`study/delayed_entry_ticks_v1_replay.py` (the review-12 function kept verbatim for the comparison),
`live/lab/test_delayed_entry_ticks.py` (9 regression cases, all pass with the plain runner - pytest is not
installed on the VPS), `study/delayed_entry_ticks.out/.json` (per-setup map with the v1 outcome beside each),
`live/lab/harness.py` (OPPHOOK: raw opportunity stream for the tick engine; no behaviour change).

## Corrections (your items 1-4)
1. **Coverage.** The incoming gap of every tick is now accounted BEFORE the tick is evaluated - eligibility ->
   first quote, every wait tick, trigger -> execution ticks, fill -> next tick, every open tick. Your synthetic
   case (quotes at 61,000 and 121,000 ms) now returns `max_gap_ms >= 60,000` for both arms and `resolved: False`
   (test `test_review13_case1_gap_after_fill_is_counted`). Code, docstring and report agree: a path whose largest
   incoming gap exceeds 30 s is UNRESOLVED and excluded from the certified totals; the observed-tick totals are
   printed beside them as a diagnostic; the 5 s flag is a count only. The gap-free-subset claim is gone.
2. **Horizon.** END = the dataset's closed-bar cutoff (1791558420 s). 22,892 ticks after END are loaded for
   nothing and never read; ticks before the first bar are coverage context only. A setup still pending / open at
   END is `pending_at_end` / `open_at_end`, kept, marked at the last in-window quote, reported for both arms
   (tests `test_horizon_*`). Historically: **0** setups were open or pending at END in any row, so no earlier
   resolution had used later prices (the v1 risk existed; it did not bite).
3. **Fill geometry, both arms.** Declared execution model: bot-triggered MARKET orders. Signal-processing delay
   1 s after the bar close; trigger = first tick with ask <= mid (buy) / bid >= mid (sell) for the delayed arm, the
   eligibility tick for the immediate arm; trigger-to-execution delay 1 s; fill at the first tick at/after that,
   on the executable side. At the fill quote, broker geometry: stop not strictly beyond the exit quote or target
   already reached => REJECTED and recorded (`reject_invalid_stop`, `reject_invalid_target`, and
   `reject_after_stop_print` when the stop had printed during the wait). Your second synthetic case (first quote
   89/89.2 against stop 90, then 110/110.2) is now a rejection for BOTH arms, no winner conjured
   (`test_review13_case2_...`). A tick through both barriers after the fill is a loss (stop priority; sell mirror
   tested). Historically: **0** rejections of any kind in any row.
4. **Quotes and files.** bid <= 0, ask < bid or non-finite ticks are dropped and counted (0 dropped); every daily
   file hash is verified against the manifest before loading (43/43). Also stated: the setups, lots and funded
   add counts still come from the bar-level candidate path (close-time funding) - diagnostic only - and the fair
   27.8% line is ideal geometry; the money after costs is the test.

## Before / after (same setups, review-12 function vs corrected function)
| regime | drag | setups | kind changed (cand / base) | outcome flipped | price-only changes | largest per-setup $ change | newly unresolved |
|---|---|---|---|---|---|---|---|
| infinity | 0 | 196 | 0 / 0 | 0 | 182 | 0.67 | 0 |
| u224016179 | 0 | 186 | 0 / 0 | 0 | 176 | 1.32 | 0 |
| bos | 0 | 187 | 0 / 0 | 0 | 176 | 2.64 | 0 |
| reference | 0 | 271 | 0 / 0 | 0 | 255 | 1.33 | 0 |
| infinity | 0.35 | 222 | 0 / 0 | 0 | 201 | 0.66 | 0 |
| u224016179 | 0.35 | 238 | 0 / 0 | 0 | 222 | 1.32 | 0 |
| bos | 0.35 | 228 | 0 / 0 | 0 | 212 | 2.64 | 0 |
| reference | 0.35 | 284 | 0 / 0 | 0 | 268 | 1.33 | 0 |
Every change is the 1 s trigger-to-execution delay moving the fill to the next quote (cents to a few dollars);
no kind or outcome changed; no path exceeds a 30 s gap (largest incoming gaps on paths: 5-18 s, on about half of
them, flagged). The two defects you reproduced were real in the code and absent in the data.

## Corrected table (MAIN money on the candidate's in-debt setups; certified = observed, since nothing is unresolved)
| regime | drag | setups | fills (win rate) | missed winners | rejects | open/pending at END | delayed MAIN | funded adds | entered-at-once MAIN | fill vs line (median) | signal -> fill (median) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| infinity | 0 | 196 | 124 (0.306) | 72 | 0 | 0 | +31.89 | -3.93 | +29.45 | -2.16 pts | 323 s |
| u224016179 | 0 | 186 | 121 (0.298) | 65 | 0 | 0 | +48.31 | -3.97 | +11.35 | -2.04 | 323 s |
| bos | 0 | 187 | 123 (0.301) | 64 | 0 | 0 | +69.41 | +4.26 | +20.71 | -1.82 | 325 s |
| reference | 0 | 271 | 170 (0.306) | 101 | 0 | 0 | +90.15 | 0 | +74.19 | -2.16 | 398 s |
| infinity | 0.35 | 222 | 140 (0.314) | 82 | 0 | 0 | +0.89 | -7.33 | -25.05 | -2.14 | 370 s |
| u224016179 | 0.35 | 238 | 149 (0.295) | 89 | 0 | 0 | +1.90 | -9.13 | -68.02 | -2.37 | 372 s |
| bos | 0.35 | 228 | 145 (0.310) | 83 | 0 | 0 | +25.88 | +3.64 | -80.27 | -2.16 | 381 s |
| reference | 0.35 | 284 | 181 (0.298) | 103 | 0 | 0 | +24.59 | 0 | -44.43 | -2.16 | 381 s |
Reading, unchanged in direction and now with the corrections in: on the candidate's own in-debt setups, with
executable fills and the missed winners counted, the delayed MAIN earned more than the immediate MAIN in 7 rows
and about the same on Infinity at zero drag. Still selected-setup MAIN totals on one overlapping history; not
account returns; not independent confirmations; nothing to deploy.

## Next: one chronological tick engine, three independently evolving arms (your brief)
Building now as `study/tick_engine.py`: baseline / delayed recovery MAIN / original-entry half-MAIN control;
each arm owns debt, jar, balance, pending setup, position, funded adds, caps, kill; signals from confirmed
closed bars via the harness's raw opportunity stream (path-independent facts: awake, nervosity, movement, flip,
level) with the path gates applied per arm in the harness's order; lots / limits / caps revalidated at the
execution quote; adds funded and reserved at their actual trigger tick (jar / debt / streak / weather at that
moment), filled at the next executable quote, exiting on the same barrier; one pending setup; pending
cancellation on the target print; fill-quote barriers; same-tick stop priority; end-of-window exposure marked
for every arm; coverage flags on every state. Outputs per arm as you listed, event traces for the four cases,
Infinity validated end to end first (immediate arm vs the harness's bar-level baseline, differences accounted
for by tick fills), then the other three regimes at both costs. Day/block uncertainty on shared history, rows
not treated as independent. No Compte, no trendline, no sweep; frozen before any later untouched period is
read; no live deployment on this evidence.
