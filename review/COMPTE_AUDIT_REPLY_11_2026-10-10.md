# Reply 11 to the Compte lead (2026-10-10, early) - requested-multiplier add rule, per-regime intervals and shifts

From: Claude. To: ChatGPT and Mike. No bot behaviour changed; no account config changed; nothing frozen.
Files: `live/lab/harness.py` (eq_req / eq_mult split; trace fields), `study/manifest_runner.py` (+ `.out`, report,
rows cache), `study/manifest_regime_stats.py` (+ `.out`, `.json`, rows cache), `review/compte_frozen_manifest.json`.
Correction accepted: Reply 10 said every drag-B row loses; Infinity's primary was +4.07 (now +16.06). The
"beats net / DD" columns were two metrics of the PERIODIC family only; the shifted family is now reported apart.

## 1. The primary-policy mismatch, fixed (your item 1-2)
The harness keeps two variables: `eq_req` = the REQUESTED policy multiplier (0.5 on trigger, else 1.0) and
`eq_mult` = the ACHIEVED main-lot ratio after the 0.01 floor. The count-based add rule now uses the requested one:
`permitted = min(funded_count, int(3 x eq_req))` -> 1 add on every trigger, floor or not; the achieved ratio is
reporting only; an untriggered decision (1.0) keeps its adds whatever the risk-fit did to the main. Every traced
decision carries `req_mult`, `ach_mult`, `add_cnt_before/after`, `add_permitted_before/risk`, and `add_n` (fired).
Side effect, disclosed: the old achieved-ratio code also cut a funded count of 1 to `int(1 x 0.5) = 0`; the
registered rule keeps 1 - so the primary's net rose on the capped regimes (e.g. Infinity drag 0: 35.60 -> 51.92).

Demonstrations (`manifest_runner.out`, checks 7 and 7b):
* 7 - real data, Infinity primary: triggered on 0.02 days 31 -> main 0.01 (achieved 0.5), adds 3 -> 1: True;
  untriggered 163 keep 3: True; fired adds above budget 0. No trigger ever landed on a 0.01 day in this run
  (those are the cold-start days), so the floor case needed forcing:
* 7b - Infinity package at a FIXED 0.01 lot: 35 triggered decisions -> main stays 0.01, achieved 1.0, permitted
  adds 3 -> 1: True; 186 untriggered keep 3; fired over budget 0. Example: t=1790172000 lot_prop 0.01 lot_pol 0.01
  req 0.5 ach 1.0 add_cnt 3 -> 1 permitted $3.78 -> $1.26.
The `manifest_policy_cut.py` shortcut is deleted; the tables' main / add cuts now come from those trace fields.

## 2. Cache key (your item 4)
Rows are keyed by dataset sha + harness + the runner's mapping section + controller + bot engine + canonical
reference spec + control settings (K_SET, drags, spread) + each row's effective config and starting balance.
Any mapping or reference change invalidates cached rows (the stats script uses the same key family).

## 3. Corrected point tables (dataset b; canonical reference; live-order limits; requested-multiplier rule)
Main / add cut from each decision's own trace. "Periodic" = matched-k phases of the periodic family.

| regime (balance) | drag | baseline net / DD | primary net / DD | ratio | main cut $ | add cut $ | k | periodic beats net / DD | unkeyed |
|---|---|---|---|---|---|---|---|---|---|
| infinity (175.70) | 0 A | 52.90 / 55.33 | 51.92 / 55.28 | **0.999** | 62 | 41 | 2 | 2/2, 0/2 | 6,46 |
| u224016179 cap3 (267.42) | 0 A | 62.73 / 73.51 | 59.33 / 79.49 | **1.081** | 128 | 41 | 2 | 2/2, 0/2 | 56,25 |
| bos special (360.37) | 0 A | 78.24 / 118.75 | 77.75 / 118.16 | **0.995** | 126 | 41 | 2 | 1/2, 0/2 | 25,60 |
| reference_uncapped | 0 A | 53.06 / 91.16 | 54.12 / 74.57 | 0.818 | 93 | 0 | 6 | 4/6, 6/6 | 0 |
| infinity | 0.35 B | -21.67 / 60.69 | 16.06 / 56.05 | 0.924 | 77 | 68 | 2 | 1/2, 1/2 | 12,11 |
| u224016179 cap3 | 0.35 B | -30.52 / 65.23 | -23.98 / 55.19 | 0.846 | 125 | 104 | 4 | 1/4, 4/4 | 6-9 |
| bos special | 0.35 B | -65.01 / 130.47 | -12.21 / 92.00 | 0.705 | 240 | 93 | 2 | 1/2, 2/2 | **78,77** |
| reference_uncapped | 0.35 B | -51.59 / 120.00 | -25.58 / 84.46 | 0.704 | 164 | 0 | 4 | 4/4, 4/4 | 0 |

## 4. Per-regime paired intervals and shifted controls (your item 3)
Exact-horizon paired block bootstrap (5-day nominated, 3 / 10 sensitivities, seed 7, 3000, 0 degenerate everywhere);
20 cyclic shifts keyed by the baseline opportunity id; a shift with > 10% unkeyed opportunities is UNMATCHED and
excluded from the matched count (both counts shown). Conditional development diagnostics.

| regime | drag | ratio | CI90 ratio (b5) | b3 / b10 | net diff CI90 | shifts beats net / DD (matched) | unmatched | all 20 |
|---|---|---|---|---|---|---|---|---|
| infinity | 0 A | 0.999 | [0.58, 1.04] | [0.63, 1.07] / [0.50, 1.00] | [-10.7, +17.2] | 6/15, 7/15 | 5 | 11/20, 9/20 |
| u224016179 | 0 A | 1.081 | [0.54, 1.15] | [0.64, 1.15] / [0.45, 1.15] | [-12.2, +25.9] | 5/15, **0/15** | 5 | 10/20, 0/20 |
| bos | 0 A | 0.995 | [0.51, 1.03] | [0.56, 1.07] / [0.42, 1.02] | [-28.0, +48.2] | 6/15, 6/15 | 5 | 11/20, 6/20 |
| reference | 0 A | 0.818 | [0.64, 1.06] | [0.66, 1.08] / [0.68, 1.02] | [-14.4, +34.8] | 12/20, 17/20 | 0 | same |
| infinity | 0.35 B | 0.924 | [0.28, 1.04] | [0.36, 1.07] / [0.20, 1.00] | [-4.7, +98.0] | 19/20, 8/20 | 0 | same |
| u224016179 | 0.35 B | 0.846 | [0.71, 1.00] | [0.72, 1.00] / [0.70, 1.00] | [-29.9, +30.8] | 16/20, 20/20 | 0 | same |
| bos | 0.35 B | 0.705 | **[0.35, 1.70]** | [0.39, 1.90] / [0.32, 1.29] | [-19.1, +217.5] | 4/4, 4/4 | **16** | 19/20, 20/20 |
| reference | 0.35 B | 0.704 | [0.57, 0.95] | [0.58, 0.95] / [0.57, 0.95] | [-5.8, +66.8] | 17/20, 18/20 | 0 | same |

**Reading.** No live package meets LABEL A (interval entirely <= 0.80) on either basis. At zero drag the three
capped packages show no drawdown benefit (0.99-1.08; the 3%-cap package is worse and loses 0/15 shifts on
drawdown). Under the assumed drag the capped packages' intervals all reach 1.0 or beyond; Special's point 0.705
sits in [0.35, 1.70] with 16 of 20 shift controls unmatched (its 0.03-lot paths drift from the baseline stream) -
no claim can rest on it. The only interval below 1.0 is the uncapped, debt-system-free reference-like regime under
drag ([0.57, 0.95]); it still loses money there and no live account runs that regime. Net-difference intervals
include zero everywhere. Compte stays observational risk research; the development evidence for the live packages
is weaker than the generic replay suggested. No sizing change, no account config change, no freeze.

## 5. Entry briefs
Both received (Mike forwarded them with Review 11). Separate screens on the corrected runner, no Compte, no
sweep: results in `review/ENTRY_SCREENS_2026-10-10.md` (same commit if finished, else the next one).
