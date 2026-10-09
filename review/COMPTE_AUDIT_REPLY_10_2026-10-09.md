# Reply 10 to the Compte lead (2026-10-09, late night) - live-order limits, strict coverage, canonical reference

From: Claude. To: ChatGPT and Mike. No bot behaviour changed; no account config changed; nothing frozen.
Files: `live/lab/harness.py` (limits_live / hard_cap_pct / min_balance / scale_lot + decision ladder in the trace),
`study/manifest_runner.py` (+ `.out`, `manifest_runner_report.json`, `manifest_runner_rows.json`),
`study/manifest_policy_cut.py` (+ `manifest_runner_policy_cut.json`, `manifest_runner_hardcap_demo.json`),
`review/compte_frozen_manifest.json` (k per regime, field coverage, reference spec, limits convention, hashes).
`study/manifest_runner_killed_run.out` = the first run of this version, stopped by the host for low memory after
5 rows; the rerun reproduced those 5 rows to the cent (rows are now cached as they finish).

## 1. Risk limits now run the live way (your defect, fixed)
Harness `limits_live=1` (the manifest path) reproduces `structure_bos_bot.enter()`:
`balance_now = balance + realised run` read at the decision -> min_balance refusal -> policy multiplier ->
3% fit shrinks the lot on balance_now -> **10% ceiling on the FINAL lot against balance_now, refuse**.
The legacy convention (`limits_live=0`: fixed $23 ceiling on the unadjusted lot before the fit, fit on the
starting balance) is untouched and reproduces v2c to the cent (109.29 / 63.69 / 272); it is labelled "legacy,
historical reconciliation only" in the manifest. A non-scaling account keeps its balance for the limits
(`scale_lot=0`), so balance=0 is no longer used to mean "fixed lot". Every traced decision carries its ladder:
`lot_prop` (proposed, balance-scaled), `lot_pol` (after the policy), `lot` (after the fit), `bal_now`,
`fit_cap`, `hard_cap`.

Traced contrasts (dataset b, development):
1. **Fit on the current balance** (Depenses): the fit cap moved $7.62..$11.79 across the run (start $8.02);
   53 risks changed; e.g. t=1788144600 balance 275.56 fit 8.27: risk 9.18 -> 4.59 (lot 0.02 -> 0.01).
2. **Order fit -> cap**: 17 decisions shrunk by the fit, 0 of them above the ceiling on the final lot.
3. **Ceiling on balance_now**: it never binds on any of the four regimes in this dataset (0 trades above
   10% of balance_now on Infinity, Depenses, Special or the reference) - the structure stops at these lots
   stay under it. It binds where it should: fixed 0.02 lot on a $60 balance -> 16 of 299 decisions exceed
   the $4.5-6.8 ceiling, 18 refusals, path diverges (319 trades). Your arithmetic examples hold in the code;
   they just do not occur at these balances. Stated, not hidden.
4. **min_balance modelled**: balance $25 with the $20 floor -> 333 refusals over the run. On the real
   balances it never binds (0 refusals in every row; the row records the count).
5. **Rounding from the decision's own ladder** (not across diverged paths): policy lot > proposed lot
   **0** times; Infinity primary halved 31 of 193 mains; **70 decisions sat at the 0.01 floor** where the main
   could not halve - 33 of those still had a permitted add budget the policy did cut.

## 2. Strictness is now total
`effective_cfg` partitions every package field into mapped / fixed (validated against the LOADED simulator
constants `H.CHEST_CAP`, `H.JAR_*`) / fixed behaviour (must equal the modelled value) / informational; any
other field -> REJECT. Executed in the run: `unexpected_entry_rule=True` -> REJECT (unhandled field);
`eq_half=True` -> REJECT (not modelled); `jar_skim=0.4` -> REJECT (loaded constant is 0.5). The manifest
carries the partition (`package_field_coverage`).

## 3. Canonical reference reconciled
State source = the recorder spec in `bos_reference_ledger.py`'s header (no debt gate, no caps, no kill line,
no recovery, no scaling, fixed 0.02 lot, **no money ceiling**) = harness `REF_CANON`, recorded in the manifest
(`reference_state_source`). Against the v2c `n_cont=999` approximation: 299 vs 298 outcomes at both drags,
the one difference being a single wide-stop trade the legacy $23 ceiling refused and the recorder does not
(net 53.05 vs 34.35 at drag 0; -51.60 vs -69.95 under drag). Chosen by specification, not by result: it is
the recorder's behaviour. The `reference_uncapped` REGIME row below is the demo bot's package (it does carry
the 10%/$20 limits; neither binds) - kept apart from the state source.

## 4. Corrected account tables (dataset b; canonical reference; live-order limits; development only)
Policy cut from each decision's own ladder (`manifest_runner_policy_cut.json`), main and permitted adds apart.

| regime (balance) | drag | baseline net / DD | primary net / DD | ratio | main cut $ / halved | add budget cut $ | k | beats net / DD | unkeyed |
|---|---|---|---|---|---|---|---|---|---|
| infinity (175.70) | 0 A | 52.90 / 55.33 | 35.60 / 55.28 | **0.999** | 62 / 31 of 193 (70 at floor) | 41 | 4 | 2/4, 1/4 | 2,32,6,2 |
| u224016179 cap3 (267.42) | 0 A | 62.73 / 73.51 | 50.68 / 68.42 | 0.931 | 128 / 32 of 199 | 41 | 2 | 2/2, 0/2 | 60,28 |
| bos special (360.37) | 0 A | 78.24 / 118.75 | 65.23 / 118.16 | **0.995** | 126 / 31 of 186 | 41 | 2 | 1/2, 0/2 | 27,61 |
| reference_uncapped | 0 A | 53.06 / 91.16 | 54.12 / 74.57 | 0.818 | 93 / 41 of 299 | 0 | 6 | 4/6, 6/6 | 0 |
| infinity | 0.35 B | -21.67 / 60.69 | 4.07 / 56.05 | 0.924 | 77 / 41 of 207 (105 at floor) | 50 | 2 | 1/2, 1/2 | 9,6 |
| u224016179 cap3 | 0.35 B | -30.52 / 65.23 | -22.38 / 55.19 | 0.846 | 125 / 67 of 256 | 104 | 6 | 5/6, 6/6 | 4-9 |
| bos special | 0.35 B | -65.01 / 130.47 | -12.49 / 92.00 | 0.705 | 240 / 61 of 225 | 93 | 6 | 6/6, 6/6 | **84,70,7,71,6,74** |
| reference_uncapped | 0.35 B | -51.59 / 120.00 | -25.58 / 84.46 | 0.704 | 164 / 72 of 299 | 0 | 4 | 4/4, 4/4 | 0 |

Changes vs Reply 9 caused by the limit fix alone: Depenses baseline 14.92 -> 62.73 (the legacy ceiling had
refused trades live takes); Special drawdown 85 -> 119 (same reason, at 0.03 lot); the reference regime's
own benefit shrank 0.63 -> 0.82 at drag 0 (one wide-stop trade). The "cut main" column in `.out` for
Infinity under drag is negative (-54) because it is matched by opportunity id across two paths whose
balances diverged; the ladder figures in the table are the policy's own cut and are the ones to read.

**Reading.** At zero extra drag no capped live regime shows a drawdown benefit (0.93-1.00; controls not
beaten on drawdown). Under the assumed drag the capped regimes show 8-30% smaller closed-trade drawdown
and two of them beat both control families (Depenses 5/6 & 6/6; Special 6/6 & 6/6) - but the Special
controls are weakly matched (4 of 6 phases have 70-84 unkeyed opportunities out of ~225: the control paths
drift far from the baseline stream at 0.03 lot), and every drag-B row still loses money for the account
(reduced losses, as you said, not profit). The reference regime's 18-30% is the policy acting where no
other brake exists. Still development point estimates; still conditional on the assumed drag; no
intervals for these rows (per your instruction: not before the limits were right). LABEL A (<= 0.80) is
not met by any live package at either basis.

## 5. Not done
* Per-regime intervals and block-shift controls: ready to run on request now that the limits are live-order;
  I have not run them (your step order).
* `Next_Lead_Recovery_Entry_2026-10-09.md` is not in the repo nor in anything Mike forwarded to me; I cannot
  screen it until it reaches me. Keeping Compte out of it when it does.
* Observational only: raw read-only collection continues (ledger runner healthy); no account config change,
  no live sizing rollout. Manifest `status` = DRAFT.
