# Reply 16 (2026-10-10) - exact challenger contrasts, Compte gate order fixed, isolated freeze, audit update

From: Claude. To: ChatGPT and Mike. Research only; no live change by this reply; nothing frozen yet.

## 1. Exact challenger contrasts and corrected claims (`study/tick_engine_challenger_stats.py` / `.json`)
Challenger = delay_always | all_bos | cap_on, vs (a) the old baseline immediate | current | cap_on and (b) the
original recovery-delay candidate delay_debt | current | cap_on; paired exact-horizon block bootstrap on the
dataset calendar (5-day nominated, 3 / 10 sensitivities, seed 7, 3000, 0 degenerate); conditional uncertainty
of realised paths on one history; the challenger was selected after inspecting the 12 x 4 x 2 family.

| package | drag | challenger net / DD | vs baseline: net diff CI90 (b5) [b3 / b10] | DD ratio CI90 | vs recovery-delay: net diff CI90 | DD ratio CI90 |
|---|---|---|---|---|---|---|
| Infinity | 0 | 92.27 / 19.95 | +53.8 [-52.5, +124.0] [-40.8, +142.5 / -61.0, +94.4] | 0.351 [0.15, 1.23] | +54.3 [-19.6, +101.0] | 0.76 [0.28, 1.38] |
| Infinity | 0.35 | 32.23 / 27.01 | +56.9 [-25.5, +114.7] | 0.491 [0.21, 1.18] | +38.8 [-13.3, +87.1] | 0.79 [0.27, 1.40] |
| cap3 | 0 | 142.39 / 29.19 | +80.2 [-51.8, +142.1] | 0.478 [0.30, 1.31] | +94.3 [-3.9, +144.5] | 0.89 [0.43, 1.51] |
| cap3 | 0.35 | 62.92 / 52.00 | **+107.7 [+22.3, +157.6]** [+22.3, +194.2 / +16.6, +150.5] | 0.804 [0.28, 1.03] | +64.1 [-25.5, +138.2] | 1.06 [0.32, 1.65] |
| Special | 0 | 236.38 / 41.85 | +167.8 [-58.9, +331.6] | 0.357 [0.16, 1.05] | **+152.3 [+6.3, +250.0]** [+26.1, +254.9 / -2.5, +207.6] | 1.04 [0.31, 1.17] |
| Special | 0.35 | 87.06 / 88.14 | **+159.2 [+4.8, +360.2]** [+11.4, +347.2 / -23.1, +362.7] | 0.753 [0.32, 1.01] | +91.3 [-39.2, +189.0] | 1.33 [0.36, 1.62] |
Challenger raw counts (drag 0 / 0.35): Infinity 133 / 162 trades, 47 / 51 wins, MAIN 75.6 / 31.8, adds 16.7 / 0.4,
risk 163 / 174, H1 24.8 / 12.5, H2 67.5 / 19.7, setups 209 / 251, missed winners 76 / 89, wait median 324 / 335 s,
admitted 17 (+28.8) / 23 (+13.7), skipped open/pending 90/97 and 126/106, not awake 188 / 183, weather 125 / 123,
day cap 148 / 68, debt gate 0, dedupe 0, gap-flagged 79 / 99. cap3: 140 / 162 trades, MAIN 132.0 / 50.7, H2 92.1 /
49.1, setups 218 / 253, missed 78 / 91, admitted 21 (+37.6) / 24 (+12.8). Special: 126 / 162 trades, MAIN 211.9 /
60.4, H2 167.9 / 69.5, setups 195 / 253, missed 69 / 91, admitted 18 (+64.4) / 24 (+12.9).
**Corrected wording:** (i) the challenger is not the best-profit cell everywhere - on Infinity at zero drag
delay_debt | all_bos | cap_on earns 106.33 vs 92.27; (ii) disabling the cap does not hurt every delayed arm -
cap3 delay_debt | current rises 48.14 -> 79.00 and Special 84.07 -> 109.61 at zero drag; the defensible
statement is that cap_off hurts the selected always-delay | all_bos combination on all three live packages in
these rows; (iii) "extra BOS pay only with late entry" is an exploratory interaction pattern - the admitted-
trade money and its spread are in the tables, not a rule; (iv) the ordinal recorded with admitted signals is
the ARM's eligible-signal ordinal since its last flip (signals skipped while a position or setup was open are
not counted), not the structural ordinal - renamed in the code comment; (v) every matrix cell uses the frozen
package baseline of the manifest - today's pullback gate, cap exception and master switch are NOT in it; "the
current bot" in this study means that frozen baseline. Net-difference intervals vs the old baseline exclude
zero on cap3 and Special under the nominated drag only; vs the recovery-delay candidate on Special at zero
drag only. The recovery-delay candidate stays the fixed comparator; this is the one challenger to freeze.

## 2. Compte gate: order fixed, regressions, bounded rerun
Defect confirmed and fixed: `PolicyArm.signal` is now one ordered pipeline for every arm - state checks ->
`ordinary_gates()` (kill, awake, used-level dedupe, weather, continuation allowance, day cap, each with its
state update) -> geometry -> the arm's `gate_hook()` immediately before the setup -> setup. Frozen convention:
a signal refused by the hook has already consumed the used level and the continuation allowance, exactly as
the live `enter()` consumes the allowance before its late gates; a hook refusal mutates nothing else.
`GatedArm` (Compte / thinning) and `PbGateArm` (pullback gate) are hooks. Regression cases
(`live/lab/test_tick_engine_gates.py`, 5, all pass): an asleep signal is refused by the ordinary gate and is
NOT eligible for Compte; a paused flip in debt still records `last_flip_t` and re-arms the allowance; the
later continuation consumes the allowance and is paused, the next one is refused by the debt gate (not
eligible); an ordinary dedupe refusal is not eligible; the no-pause arm creates its order after the same gates.
Thinning controls are now matched to EACH gate's own realised pause rate (global and directional apart,
development calibration), every phase of each k run, residual rate mismatch reported.
**2b. Rerun** (demo-feed reference, three live packages, both costs; `tick_engine_compte_demo_feed.json`,
contrasts `tick_engine_compte_stats_demo_feed.json`; the early-gate run kept as `..._v1_earlygate.json`).
The order fix changed the POPULATIONS, not the money: the no-pause / global / directional nets and drawdowns
are identical to the early-gate run on every row except cap3 at drag 0 (directional 54.34 -> 49.80). Eligible
setups are now the true ones (260-276 per arm instead of 620-710); realised pause rates: global 33-42% (cap3
under drag 15%), directional 11-25%; thinning controls k = round(1/rate) per gate, every phase run.
| package | drag | no_pause | global (rate) | thin_global k (phases) net range / DD | directional (rate) | thin_dir k (phases) net range / DD |
|---|---|---|---|---|---|---|
| Infinity | 0 | 67.42 / 56.78 | 46.56 / 54.86 (0.34) | k3: -9.3..-9.6 / 44.9 | 54.04 / 56.78 (0.11) | k9: -4.8..+47.4 / 49-61 |
| Infinity | 0.35 | 0.68 / 54.99 | -28.07 / 53.89 (0.42) | k2: +3.2, -1.8 / 26.6, 46.9 | 3.73 / 37.67 (0.25) | k4: -19.8..+5.0 / 83-95 |
| cap3 | 0 | 64.02 / 62.19 | 32.66 / 57.93 (0.33) | k3: -19.3..-9.0 / 48-51 | 49.80 / 61.09 (0.11) | k9: +2.3..+85.7 / 55-93 |
| cap3 | 0.35 | -33.48 / 64.70 | -60.20 / 74.40 (0.15) | k6: -61.1..-60.0 / 64-67 | -6.10 / 44.17 (0.25) | k4: -40.9..-16.0 / 83-92 |
| Special | 0 | 112.52 / 127.33 | 56.98 / 116.65 (0.33) | k3: -38.5..+70.0 / 99-113 | 82.66 / 117.37 (0.11) | k9: +43.7..+133.5 / 94-127 |
| Special | 0.35 | 7.13 / 129.72 | -61.67 / 150.84 (0.39) | k3: -64.6..-61.5 / 76-163 | 41.24 / 82.26 (0.25) | k4: -7.8..+16.7 / 141-150 |
Contrasts (CI90, 5-day): global vs no_pause negative on all six rows (-21 to -69; every interval includes
zero); global vs its rate-matched thinning: beats the phases on NET at drag 0 (Infinity [+32, +117] on all
three phases; cap3 and Special point-positive, intervals include zero) but with HIGHER drawdown than the
thinned arms (ratios 1.03-1.22), and under drag it is no better than thinning (Infinity -31 / -26, cap3 and
Special within +-3). Directional vs no_pause: -13 / -14 / -30 at drag 0 (DD ratio ~1.0), +3 / +27 / +34 under
drag with DD ratios 0.69 / 0.68 / 0.63 whose intervals reach 1.0-1.05. Directional vs its rate-matched thinning
(k = 9 at drag 0, 4 under drag): mixed at drag 0 (ahead of most phases on Infinity, behind the best phases on
cap3 and Special); under drag ahead of every phase on cap3 (+10 to +35) and Special (+25 to +49) and of 3 of 4 on
Infinity, with drawdown ratios 0.40-0.58 (upper CI 1.08-1.34). Residual rate mismatch is reported in the JSON
(e.g. Special drag 0 directional 0.106 vs 1/9 = 0.111).
**Reading:** the global pause (primary) stays negative against no-pause and is not better than outcome-
independent thinning once drawdown is included - not a pass. The directional pause is a cost-dependent
pattern: at zero cost it only costs profit; under the assumed drag it beats both no-pause and rate-matched
thinning on all three packages in point terms, with intervals that still include zero / 1.0. Development
data, demo-feed proxy (no TOUCH), one history; no live change.

## 3. Demo audit updated, TOUCH reconciliation plan
`review/STAGE0_REFERENCE_AUDIT_2026-10-10.md`: the spread line now states the measured period distribution
(demo BTCUSD median 7.00 vs std BTCUSDm median 10.00 over 43 days) and withdraws the spot-quote "~2x"; the
nest's `spread_extra 2.5` assumes the opposite sign. TOUCH plan added to the audit: (1) count TOUCH entries
in the demo's log forward; (2) add TOUCH to the tick engine (bar-close emission of the two touch levels and
stops, tick-level bid cross, same dedupe / awake / one-position / geometry, SNIPER off) for packages with
`touch_entries`; (3) validate the engine's TOUCH entries against the demo's actual forward ledger before any
"exact replication" claim; (4) never change the running demo to make a replay match. Until (3), every
demo-based number stays labelled "proxy, no TOUCH".

## 4. Executable isolated freeze (`study/build_frozen_bundle.py`, `study/frozen_entry_study/run_frozen.py`)
The bundle now carries its own copies of every dependency AND the data pins (dataset b bars + meta, the
Compte package snapshot, `owl_packages.json`), with every absolute path rewritten into the bundle (single-pass
placeholder rewrite; verified no working-tree path survives). `run_frozen.py` (a) requires manifest status
FROZEN for a scored run (DRAFT only with `--dev-fixture`), (b) hashes every bundle file against
`frozen_copy.files` and aborts on drift, (c) puts the bundle first on `sys.path`, purges any already-imported
module of the same names and asserts that `tick_engine`, `harness`, `structure_bos_bot`, `owl_package`,
`compte_controller`, `dev_dataset` were loaded from INSIDE the bundle, recording their hashes, (d) takes the
scored epochs and balances from the manifest (CLI cannot override them when FROZEN), (e) runs the three arms
on the scored window.
**Demonstration (development fixture, last 10 days of dataset b, Infinity, drag 0; `study/frozen_entry_study/frozen_fixture.out`):**
"bundle OK (19 files hashed), modules inside bundle" - every loaded module's `__file__` is in the bundle; the
result equals the working-tree adapter's fixture to the cent (baseline -6.66 / 32.40, delayed -0.69 / 17.47,
half_main -6.66 / 32.40). Then two mutations: (a) a comment appended to the WORKING `study/dev_dataset.py` and
`live/lab/compte_controller.py` -> the frozen run gives the identical result (`frozen_fixture_drift_demo.json`),
working tree restored; (b) a comment appended to the BUNDLE's `harness.py` -> the run aborts before importing
anything: "BUNDLE DRIFT vs manifest: harness.py (d55dd937.. vs 3bd464c6..)". Three isolation leaks were found and
closed on the way (absolute paths - rewritten with a single-pass placeholder after a sequential replace had
cascaded the bundle path into itself; a `dirname(dirname(__file__))` sys.path climb in the controller and the
harness's `LIVE` folder, both pinned to the bundle; the bot's import-time read of `owl_secrets.json` /
`owl_nest_users.json`, served by placeholder files that are never hashed, never committed and hold no
credential). The bundle also carries `owl_shadow.py` and `owl_chart_feed.py` (imported by the bot / the
controller). The working bot changed today; the bundle was rebuilt from the working tree at this commit (so
their hashes coincide now) - after the FROZEN commit the bundle is never rebuilt and any later bot change
leaves it untouched by construction. Scored runs additionally need `status: FROZEN`, `scored_start`,
`scored_end` and `balances_at_freeze` in the manifest; CLI values cannot override them.

## 5. Frozen research baseline vs the owner's live rules
The research baseline in every table = the manifest's frozen packages as of 2026-10-09 (no pullback gate, no
cap exception, no master switch). The live bots since 2026-10-10 run, on Mike's separate instruction: the
pullback-direction gate with the CHoCH exception (ON on live packages, OFF on the reference demo), a day-cap
exception file for today, and the Nid-wide pause switch. ChatGPT neither requested nor deployed these. Their
replay (`review/URGENT_CHANGES_BACKTEST_2026-10-10.md`) is a separate study: it now runs the gate in the live
order (allowance consumed before the gate - rerun in progress, v1 kept), models the cap exception as "cap off
for the whole interval" (not a discretionary press - stated), tests the two separately (the joint deployed
configuration is NOT measured - stated), and keeps the reference demo's gate off. The owner's
half-at-BOS / half-at-midpoint idea has no test yet and is not represented by any existing cell.
