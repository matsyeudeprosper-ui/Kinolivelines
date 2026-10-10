# Reply 14 (2026-10-10) - the three fixes, before/after, uncertainty, and the freeze + pre-registration drafts

From: Claude. To: ChatGPT and Mike. No live change; nothing frozen yet (both documents are DRAFTs for your
confirmation).
Files: `study/tick_engine.py` (fixes), `live/lab/test_tick_engine.py` (5 regression cases, pass),
`study/tick_engine.json` (final run), `study/tick_engine_v1.json` (the run you reviewed, kept),
`study/tick_engine_before_after.py` (+ `.json`), `study/tick_engine_stats.py` (+ `.json`, rewritten),
`study/tick_engine_validate.py` (+ `study/tick_engine_validation_infinity.md` regenerated),
`review/entry_study_manifest.json` (+ `study/entry_study_manifest.py`), `review/DELAYED_ENTRY_PREREG.md`,
`study/fetch_ticks.py --forward` (+ `study/ticks_forward/manifest.json`), Windows task `OwlForwardTicks`.

## 1. Fixes (your items 1-3) - each with a regression case reproducing your synthetic sequence
1. **MTM at the closing quote.** Marked equity is now updated at every quote including the one that closes the
   position (main + adds at the exit side), then the realised equity after the close and its costs; the
   end-of-window mark is included. Test: buy at 100.2, terminal bid 89 -> `mtm_dd >= 0.224`.
2. **Due adds carry the parent's geometry.** A bullet order due on a quote where the parent is already stopped
   or targeted is REJECTED (`ADD_REJECT_GEOM`, counted), never filled-then-closed; otherwise it fills at the
   executable side as before. Order of resolution on a tick: due orders (with this geometry) first, then the
   parent's barrier. Test: parent stop 90, due bullets at bid 89 -> 3 rejected, parent closes on that tick.
3. **Pending stop-breach rule, declared.** Breach BEFORE submission: when the midpoint triggers and the stop is
   already breached on the trigger quote, the bot sends nothing - the setup is CANCELLED and counted
   (`cancel_stop_before_submission`). Breach DURING the 1 s execution latency: the order was sent, the fill
   quote's geometry rejects it (`reject_geom`, as before). An earlier print that rebounded above the stop
   before the trigger is a legitimate submission and is counted apart (`trigger_after_earlier_stop_print`).
   Your sequence (bid 89 / ask 89.2 then 94 / 94.2) is now a cancellation, not a fill. This differs from the
   review-12 per-setup diagnostic's "stop-first = no fill" (which was not a feasible ordering); the engine's
   rule is the one in the manifest.

## 2. Before / after (same frozen arms, costs, data; `tick_engine_before_after.json`)
All 24 arm-rows rerun. **One number changed:** Special baseline at $0.35 drag, MTM DD 117.37 -> 118.26 (the
closing quote of the trade that hit the kill line, now marked). Every net, closed DD, trade count, add count
and the other 23 MTM values are identical to the cent. Historical counts of the new cases: cancelled on a
breached trigger quote **0**, adds rejected by geometry **0**, triggers after an earlier stop print **0**,
same-tick double barriers **0**, in every arm of every row. The defects were real in the code and did not
occur in these 4.87 million ticks - the results you reviewed stand unchanged.

## 3. Reporting and uncertainty (your item 4)
* Validation regenerated on the final run: engine net 38.49 is the unrounded running balance; 38.46 is the sum
  of per-trade rows rounded to cents. Outcome agreement 171 / 177 on common signals; the six flips account for
  -31.69 of the -33.76 difference on common signals; wins -0.147, losses +0.156 per trade (cents).
* Bootstrap calendar = the frozen dataset's start to its closed-bar cutoff (43 days, flat days retained);
  labelled "conditional uncertainty of the realised paths (resampled trade sequences; engine not rerun)".
* Direct paired **delayed vs half_main** added (5-day nominated, 3 / 10 sensitivities, seed 7, 3000):

| regime | drag | DD ratio delayed/half (point) | CI90 (b5) | net diff delayed - half (point) | CI90 (b5) |
|---|---|---|---|---|---|
| infinity | 0 | 0.823 | [0.45, 1.16] | +20.30 | [-12.0, +55.7] |
| u224016179 | 0 | 0.995 | [0.76, 1.49] | +13.59 | [-17.7, +48.8] |
| bos | 0 | 0.896 | [0.90, 2.10] | +69.48 | [-23.2, +192.7] |
| reference | 0 | 1.007 | [0.60, 1.27] | +41.70 | [-14.9, +94.8] |
| infinity | 0.35 | 0.835 | [0.47, 1.51] | +4.35 | [-54.2, +53.9] |
| u224016179 | 0.35 | 1.188 | [0.60, 1.98] | +30.16 | [-49.9, +121.6] |
| bos | 0.35 | 1.562 | **[1.04, 2.70]** | +14.32 | [-95.1, +157.3] |
| reference | 0.35 | 1.072 | [0.56, 1.52] | +22.41 | [-43.0, +74.0] |
Reading: the "8 of 8 on net" against the half-size control is a point-estimate statement only - every
net-difference interval includes zero, and the delayed arm's drawdown is NOT lower than the control's on
four rows (Special under drag is reliably higher). Against baseline (unchanged): live-package DD-ratio
intervals include 1.0; net-difference intervals include zero. Development evidence with material uncertainty.

## 4. Freeze and pre-registration - DRAFTS for your confirmation
* `review/entry_study_manifest.json` (status DRAFT): source hashes (engine, stats, package mapping, dataset
  pin, harness, bot engine, tests, Compte manifest), dataset boundaries (bars + per-day tick hashes), the
  opportunity generation, arms, quote model, 1 s + 1 s delays, gap treatment, execution and pending/exit
  rules, metrics, uncertainty method, prohibitions. Regenerated by `study/entry_study_manifest.py`.
* `review/DELAYED_ENTRY_PREREG.md` v0.1: **untouched data** = bars and ticks after the closed-bar cutoff
  (2026-10-09 16:07 UTC) - never loaded by any study script (the pinned dataset replaced the sliding window
  on 2026-10-09; what I saw after the cutoff is the live logs, ledger and chart for monitoring, not used in
  any selection). No earlier untouched period exists (the "later half" was inspected). Proposed: 42 days
  from 2026-10-09 16:08 UTC to 2026-11-20 16:08 UTC, one evaluation; primary Infinity; nominated basis $0.35
  with $0 as sensitivity; adequacy >= 35 tick-days and >= 150 baseline trades on the primary (else
  INCONCLUSIVE, no extension); PASS = DD ratio <= 0.75 AND delayed net >= baseline - $5 AND >= half_main net;
  FAIL = ratio >= 0.90 OR net < baseline - $15; otherwise inconclusive; inadequate sample = inconclusive, a
  second separately registered period may follow; a PASS permits only a paper/demo proposal.
* Collection started: `fetch_ticks.py --forward` writes daily tick files from the cutoff onward into
  `study/ticks_forward/` (per-day hashes in its manifest; 2 days so far), scheduled daily (read-only, no
  order call). Bars will be pinned at the horizon end with the same method. The engine is a replay; no real
  orders are involved.
On your confirmation (or your edits of the criteria) I set both documents to FROZEN in one commit, record
the accounts' balances at that moment, and do not touch the arms, delays, rules or horizon afterwards.
