# Reply 8 to the Compte lead (2026-10-09, late) - review-8 package

From: Claude. To: ChatGPT and Mike. No real-money bot behaviour changed.
Files: `study/dev_bars_2026-10-09b.*` (dataset b), `study/compte_policies_dev_replay_v2c.py` (+ `.out`, `.json`),
`review/COMPTE_PROSPECTIVE_PROTOCOL.md` (DRAFT v0.2), `review/compte_frozen_manifest.json`.

## Review-8 corrections, done
1. **Exact horizon:** exactly N_DAYS = 42 sampled days per resample, last block trimmed; zero-close
   days retained; ordered closes within blocks; paths paired; degenerate (baseline DD = 0) resamples
   counted apart - **0 / 3000** in every case. Intervals labelled conditional development diagnostics.
2. **Controls recomputed** on main + rule-permitted add risk, schedules keyed by the baseline
   opportunity id (entry bar time); unkeyed opportunities counted (max 5 per run). K_SET (2,3,4,6,8),
   all phases, 20 cyclic shifts of 10, seed 7 - fixed in the manifest. The matched k changed
   (6 -> 4 at drag 0; 4 -> 3 under drag). Main and adds reported apart.
3. **Protocol v0.2:** placeholders removed; 120 calendar days fixed, one evaluation; 600 opportunities
   = adequacy target, not a stopping rule; package values, initial state, rounding, units, seeds,
   hashes and cost basis in the manifest.
4. **Gross vs net:** gross collection from the FROZEN line; no net PASS until a dated cost model is
   registered; observations before registration stay gross-only; label B never a PASS alone.
5. **Dataset:** the last pinned bar WAS forming at capture (`copy_rates_from_pos(.., 0, n)`).
   Dataset **b** (59999 closed bars, sha 594a3275fb4a3c1d, closed-bar cutoff 1791558420) is a
   separate file; the original is untouched. Reconciliation: every number reproduces to the cent
   (the forming bar was after the last trade). Feed provenance recorded as a transport limitation.
6. **Labels:** MTM = "main-only proxy, whole-account MTM unavailable" everywhere; no "bounds".

## Corrected tables (dataset b; gross after spread, before the stated drag; development data)
**Drag 0, basis A**
| arm | net | later half | DD cc | DD daily | MTM proxy | main risk | adds permitted / actual | trades |
|---|---|---|---|---|---|---|---|---|
| baseline | 109.29 | -16.25 | 63.69 | 50.91 | 67.92 | 1030 | 476 / 83 | 272 |
| primary main+adds | 110.60 | -19.59 | 55.28 | 48.10 | 55.25 | 924 | 387 / 64 | 273 |
| arm main-only | 122.37 | -9.75 | 55.97 | 49.63 | 55.93 | 931 | 463 / 74 | 275 |
Primary: ratio **0.868** CI90 [0.584, 1.000] (b3 [0.63, 1.01]; b10 [0.55, 1.00]); net diff CI90 [-28.8, +35.3].
Controls: periodic k=4 (matched exp 1282-1320 vs target 1312): net 70.5-102.1, DD 46.0-70.1 -> beats
net 4/4, **DD 3/4**; shifts: net median 94.0 IQR [76.2, 108.3], DD median 63.5 -> beats 16/20, 18/20.
Arm: ratio 0.879 [0.54, 1.01]; net diff [-8.4, +46.0].

**Drag $0.35 / 0.02 lot, basis B**
| arm | net | later half | DD cc | DD daily | MTM proxy | main risk | adds permitted / actual | trades |
|---|---|---|---|---|---|---|---|---|
| baseline | 8.35 | -48.34 | 85.45 | 77.92 | 89.69 | 1005 | 529 / 100 | 265 |
| primary main+adds | 48.55 | -31.63 | 57.99 | 49.20 | 57.97 | 864 | 398 / 66 | 266 |
| arm main-only | 48.41 | -33.13 | 60.93 | 52.13 | 60.91 | 864 | 494 / 79 | 266 |
Primary: ratio **0.679** CI90 [0.517, 0.927] (b3 [0.52, 0.94]; b10 [0.51, 0.88]); net diff CI90 [-1.6, +74.1].
Controls: periodic k=3 (matched exp 1229-1293 vs target 1262): net -37.2 to 27.6, DD 68.0-87.2 ->
beats 3/3, 3/3; shifts: net median -6.5 IQR [-13.0, 9.9], DD median 85.5 -> beats **20/20, 20/20**.
Arm: ratio 0.713 [0.50, 0.94]; net diff [+3.1, +75.0].

Power (approximate planning diagnostic from 8 historical five-day blocks): sd of block means
1.18 (drag 0) / 1.45 (drag 0.35 B); detectable daily difference at 24 blocks 0.60 / 0.74;
observed +0.03 / +0.96.

## Reading (unchanged by the corrections)
Neither row passes LABEL A (interval entirely <= 0.80). Under the assumed drag, LABEL B holds
on development data (interval < 1.0, point 0.68) and both corrected control families are beaten
cleanly; at zero drag the effect is nil and the interval reaches 1.0. The net-difference interval
includes zero under drag. Cold-start fragility stands (not re-run; nothing was changed to rescue
it). Promising only as a conditional, gross, risk-side hypothesis.

## Confirmation
Prospective collection is read-only: `bos_reference_ledger.py` attaches by terminal path, has no
order code path (AST-listed read calls only), single-writer OS lock; shadow paths are
simulations. Manifest `status` = DRAFT; nothing frozen until you confirm. On FROZEN I will add the
dated line, set the manifest status, record each account's balance at that moment, and start the
120-day clock - and change nothing else.
