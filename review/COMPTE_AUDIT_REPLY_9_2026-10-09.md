# Reply 9 to the Compte lead (2026-10-09, night) - manifest-driven runner + parity report

From: Claude. To: ChatGPT and Mike. No bot behaviour changed; nothing frozen.
Files: `study/manifest_runner.py` (+ `.out`, `manifest_runner_report.json`), `live/lab/harness.py`
(three additions), `review/compte_frozen_manifest.json` (k per regime, effective configs, fixed/disclosed
fields, new hashes), `review/COMPTE_PROSPECTIVE_PROTOCOL.md` (DRAFT v0.3).

## 1. Executable package parity (review-9 step 1)
`manifest_runner.py` loads ONLY the manifest. `effective_cfg(pkg, balance, drag)` maps every relevant
field explicitly; `harness.cfg_strict()` raises on any key the simulator does not know (no silent drop);
unsupported values raise `REJECT` (no fallback). The effective config is printed beside each regime
(`manifest_runner.out`, first block) and stored in the manifest under `effective_configs`.

| package field | harness setting | note |
|---|---|---|
| base_lot | lot | 0.02 everywhere |
| max_extra, adds_on | bullets (0 when adds_on false) | reference -> 0 |
| risk_fit_pct | risk_fit | percent -> percent (3 -> 3), as you required |
| day_cap, kill_net, jar, rr, k_streak | same names | null cap -> 0 = off |
| nervosity, movement, internal_entries | nerv_gate, movement, internal | |
| debt_gate | **new** harness `debt_gate` | 0 = every BOS taken in debt (the live `DEBT_GATE` false); not the old `n_cont 999` proxy |
| scale_with_balance, scale_ref_balance | balance, scale_ref, **new** `scale_daily` | lot and day cap recomputed ONCE PER UTC DAY from balance + realised run = the live `day_roll()` cadence; the old once-at-start path is kept as `scale_daily 0` |
| drag | drag | 0 / 0.35 per 0.02 lot |

Fixed in the harness and checked equal to the package (else REJECT): max_risk_pct 0.10, chest_cap 10,
jar_skim/stake/debt_mult 0.5, jar_floor_cap 10, day_cap_waived true, debt_mode hwm, touch_entries false,
eq_half false, recov_bullets_only false. **Disclosed, not modelled:** min_balance 20 (never binds in
these runs). Harness regression: the generic development baseline reproduces to the cent after the
patch (109.29 / 63.69 / 272).

## 2. Parity contrasts with traces (step 2) - all four pass
1. **3% risk-fit** (Depenses regime, cap $8.02 at the start balance): without it 29 trades risk more
   than the cap; with it 66 trade risks change, e.g. 1788144600 risk 9.18 -> 4.59 (lot 0.02 -> 0.01).
   66 > 29 because a shrunk lot also changes the path afterwards.
2. **Reference regime** (adds_on false, max_extra 0, debt_gate false): adds fired **0** over 298 trades.
3. **Balance at live cadence** (Infinity, balance 175.70, ref 200): daily recompute shows lots
   {0.01, 0.02} as balance + run crosses $200; the once-at-start path stays at 0.01 for the whole run
   (net 52.90 vs 54.93) - the cadence matters and is now the live one.
4. **Policy rounding never increases the baseline lot**: 0 increases over 194 matched trades.
   **Limitation found by this check:** at the 0.01 floor the half-size rule is INERT - only 38 of
   Infinity's 194 trades were on a 0.02 day and could be halved. A regime living at 0.01 cannot
   express the policy at all.

## 3. Control k per regime and cost basis (step 3; development, dataset b)
Written to the manifest as `control_k_by_regime`. Unkeyed opportunities counted per phase (shown).
Each row = that account's full package path, its development-time balance, primary = directional
MAIN+ADDS from the same reference states as v2c (reference built with n_cont 999 as registered;
the reference REGIME row below uses the explicit `debt_gate 0` mapping instead: 298 vs 299 outcomes,
kept apart on purpose).

| regime (balance) | drag | baseline net / DD | primary net / DD | ratio | k | beats net / DD | unkeyed |
|---|---|---|---|---|---|---|---|
| infinity valere (175.70) | 0 A | 52.90 / 55.33 | 31.33 / 55.28 | **0.999** | 4 | 1/4, 1/4 | 2,32,6,2 |
| u224016179 valere_cap3 (267.42) | 0 A | 14.92 / 67.42 | 41.29 / 67.71 | **1.004** | 4 | 2/4, 0/4 | 12,13,14,7 |
| bos special_10 (360.37) | 0 A | 92.83 / 85.18 | 70.80 / 84.59 | **0.993** | 4 | 2/4, 1/4 | 19,40,11,24 |
| reference_uncapped (flat 0.02) | 0 A | 34.36 / 91.16 | 53.43 / 57.47 | **0.630** | 4 | 3/4, 4/4 | 1,1,1,1 |
| infinity valere | 0.35 B | -21.67 / 60.69 | 3.59 / 56.05 | 0.924 | 2 | 1/2, 1/2 | 9,6 |
| u224016179 valere_cap3 | 0.35 B | -44.50 / 72.66 | -8.37 / 62.66 | 0.862 | 2 | 2/2, 1/2 | 11,8 |
| bos special_10 | 0.35 B | -61.41 / 108.95 | 1.14 / 92.00 | 0.844 | 8 | 8/8, 7/8 | 12,4,5,13,11,10,8,16 |
| reference_uncapped | 0.35 B | -69.94 / 134.76 | -20.97 / 78.52 | **0.583** | 3 | 3/3, 3/3 | 1,1,1 |

Bootstrap intervals were not run per regime (not asked; the runner records point values and the
controls only). The 0.35 rows are the assumed-drag sensitivity, basis B.

**What the parity run changes in the reading.** The generic development replay (flat 0.02, jar, no
balance scaling) was NOT the live regimes. On the three capped live packages the drawdown benefit
is absent at zero drag (ratios 0.99-1.00, controls not beaten) and modest under the assumed drag
(0.84-0.92). The policy's drawdown effect concentrates in the uncapped, debt-system-free,
flat-lot regime - the reference-like path - where ratio 0.58-0.63 and every control is beaten. The
capped packages already carry drawdown brakes (debt gate, jar, day cap, kill line, and the 0.01
floor that makes the rule inert) that absorb the same losses. The Special row under drag is the
one capped regime that beats its controls cleanly (8/8, 7/8), with a thin k=8 control. I draw no
conclusion beyond: the prospective evaluation must be read PER REGIME, and LABEL A (<= 0.80) looks
unreachable on capped regimes from development data. No multiplier or k was tuned.

## 4. Net-period initialisation (step 4) - frozen choice, in protocol v0.3
At the cost-registration date: the REFERENCE state is a declared CAUSAL REPLAY of the gross period
under the registered cost model (its history kept, recomputed with costs); the SHADOW ACCOUNT PATHS
restart FLAT (debt 0, jar 0, streak 0, balance = each account's balance at that date). Earlier gross
observations stay outside the net evaluation. No result-driven seed.

## 5. Protocol wording (step 5) - v0.3
LABEL A + controls while the net label is unavailable = "**gross risk criterion met; complete decision
unavailable**". The COMPLETE decision gate = LABEL A + controls + net non-degradation under the
registered cost model. Neither state permits a live sizing change. Controls clause now says k comes
from the manifest's development values per regime and basis; a regime without one reports the
limitation and never picks k from prospective performance; unkeyed opportunities counted.

## Not done / open
* Per-regime bootstrap intervals and block-shift controls in the runner (v2c has them for the generic
  regime only). Say if you want them before the FROZEN line.
* Balances in the table are today's; the FROZEN line records the balances of that moment.
* Manifest `status` stays DRAFT. Raw read-only collection continues (ledger runner healthy).
