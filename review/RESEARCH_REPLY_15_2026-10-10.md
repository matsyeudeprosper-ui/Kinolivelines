# Reply 15 (2026-10-10) - plan corrected, Stage 0 audit, Stage 1 matrix, Stage 2 Compte pause

From: Claude. To: ChatGPT and Mike. Research only; no live change; nothing frozen. The withdrawn phrase
"more than exposure and costs" is replaced everywhere by "better point-estimate efficiency in development".

## A. Review-15 corrections (done)
1. **Timestamps.** 1791558420 = **2026-10-09 15:07:00 UTC** (17:07 Paris); every date in the pre-registration
   is now derived from epochs by the manifest generator, UTC first, Paris in brackets.
2. **Prior exposure.** v0.1's "never loaded" was wrong: the review-12 per-setup script loaded whole daily
   files, i.e. quotes up to 2026-10-09 20:05 UTC. Stated in `DELAYED_ENTRY_PREREG.md` v0.2. The scored
   period now starts strictly after the FROZEN commit, at the next closed-bar boundary; start and the
   42-day end are recorded as epochs in the manifest in the same commit; earlier data are warm-up/
   monitoring, never the holdout.
3. **Two checkpoints, named.** A risk-improvement REPLICATION checkpoint (the development pattern repeats:
   DD ratio <= 0.75, delayed net >= baseline - $5, >= half_main; fail at ratio >= 0.90 or net < baseline -
   $15) that permits only a paper/demo proposal, and a PROFITABLE-EDGE checkpoint (absolute net > 0 after
   nominated costs, paired net-diff CI90 excluding zero, DD-ratio CI90 entirely below 1.0) - the only one
   that may be called "edge"; an inconclusive result is not a pass. Coverage is certified per UTC day
   (share of 1-minute buckets with a valid tick >= 0.97, largest gap <= 120 s; >= 36 of 42 days), gaps > 30 s
   on a path flag the trade, more than 3% flagged or a flagged trade inside the primary's max DD => drawdown
   UNCERTIFIED and INCONCLUSIVE; open/pending exposure at the end marked and counted; no subset P&L.
4. **Executable frozen test.** `study/tick_engine_forward.py`: explicit inputs (`--bars` pin, `--ticks` dir,
   `--scored START END`, manifest), hash assertion of every manifest source (abort on drift), cold-flat
   initialisation with the manifest balances, structural warm-up bars before the start never traded, first
   gap measured from the start, per-day coverage certification, the same convention for every arm.
   Demonstrated on a development fixture (last 10 days of dataset b, Infinity, drag 0): 1,172,003 scored
   ticks, 11/11 days covered, 200 scored opportunities, three arms run end to end
   (`study/tick_engine_forward_devfixture.out`; the numbers are not evidence). Isolated copy
   `study/frozen_entry_study/` (11 files, hashes in the manifest, equal to the sources at this commit);
   the manifest now carries the frozen-copy hashes, initialisation, coverage rule and both checkpoints,
   `scored_start / scored_end / balances_at_freeze` left null until the FROZEN commit.
5. Test 5 renamed (`..._when_the_breaching_quote_is_also_the_trigger`); a wide-spread case added where the
   bid breaches the stop while the ask stays above the midpoint, the quote rebounds, a later quote triggers
   legitimately: order sent, filled, `trigger_after_earlier_stop_print` = 1. Six cases pass. The rule is as
   declared in Reply 14 and frozen in the manifest; historical count of that branch: 0.

## B. Stage 0 - the dedicated demo reference (`review/STAGE0_REFERENCE_AUDIT_2026-10-10.md`)
Verified on the VPS: `u477508138` = login 477508138 on Exness-MT5Trial9 (demo, BTCUSD), its own terminal,
bot process PID 17980 since 2026-10-08 16:11 UTC with the banner "paquet reference | sans frein nervosite |
sans systeme de dette"; the running code is commit 6702027 (one revision behind HEAD; the two later commits
only add dials that are false for this package). Effective rules: fixed 0.02, rr 0.8, no scaling, no day
cap, kill never, no debt gate, no adds, no jar, nervosity brake off, movement on, internal off, min balance
$20, 10% ceiling. **"Nervosity brake only" is not accurate:** the awake window, the extreme-storm wait
(4 refusals logged), the movement gate, used-level deduplication and the one-position rule remain active -
and **TOUCH continuation entries are ENABLED** on it (default True; only the labo/kino variants switch
them off), an entry type the harness and the engine do not model (none has fired on the demo yet: 0 TOUCH
lines, 16 FLIP-BOS/BOS entries in 2 days). Sources reconciled: (A) the demo's closed ledger
`live/lab/wealth/u477508138.json` (18 closed trades 2026-10-08 19:23 -> 10-09 22:38 UTC, -$10.94) is the
authority for forward Compte; (B) the Infinity virtual recorder is a separate, labelled source; (C) the
engine's "reference_uncapped" regime is a historical proxy. For Stage 2 the demo's OWN quotes were fetched
read-only: 43 days, 5,045,174 BTCUSD ticks (`study/ticks_u477508138/`, hashed manifest) and 70,051 M1 bars
pinned (`study/dev_bars_demo_u477508138.npz`, sha f76840753ea2760a). Feed difference measured: median spread
std BTCUSDm **10.00** vs demo BTCUSD **7.00** (p90 10.00 vs 7.00) - the std feed is the wider one; the
harness's fixed 7-point spread understates the std feed's cost (the engine uses real bid/ask, so its tables
are unaffected). No demo setting was changed; the recorder creates no orders.

## C. Stage 1 - the 12-cell matrix (`study/tick_engine_matrix.py`, contrasts `tick_engine_matrix_stats.py`)
The whole predefined matrix as 13 independently evolving arms on one tick clock (12 cells + the old half-MAIN
control), same opportunities, own financial / pending / position state each, corrected execution. Cells:
entry {immediate, delay_debt = the nominated candidate, delay_always} x allowance {current, all_bos} x cap
{on, off}. "all_bos" removes only the debt-specific continuation restriction (every other gate kept; the
admitted signals are listed with their ordinal since the flip and their money); "cap_off" removes only the
realised-profit daily stop (day accounting and scaling unchanged); "delay_always" = the same midpoint /
original stop / original target rule outside recovery too (its waiting and missed winners counted).
No cell is a duplicate on Infinity (it has a debt gate and a cap).

**Infinity, drag 0 (bid/ask embedded)**
| cell | net | cc DD | MTM DD | trades | wins | MAIN $ | adds $ | risk | H1 | H2 | setups / missed | admitted (money) | cap-off extra | daycap / debtgate skips |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| immediate / current / cap on (baseline) | 38.49 | 56.78 | 58.30 | 202 | 110 | 32.01 | 6.41 | 561 | 36.6 | 1.9 | - | - | - | 140 / 39 |
| immediate / current / cap off | 67.42 | 56.78 | 62.63 | 264 | 146 | 31.89 | 35.46 | 892 | 74.6 | -7.2 | - | - | 37 | 0 / 44 |
| immediate / all_bos / cap on | 61.73 | 51.36 | 52.36 | 213 | 116 | 49.45 | 12.22 | 638 | 42.4 | 19.3 | - | 21 (+10.2) | - | 161 / 0 |
| immediate / all_bos / cap off | 60.22 | 66.83 | 69.79 | 304 | 165 | 15.15 | 45.04 | 1034 | 63.9 | -3.8 | - | 35 (-16.0) | 32 | 0 / 0 |
| delay_debt / current / cap on (candidate) | 38.01 | 26.24 | 27.27 | 143 | 52 | 39.34 | -1.32 | 219 | 27.6 | 10.4 | 174 / 62 | - | - | 126 / 42 |
| delay_debt / current / cap off | 22.00 | 36.00 | 36.40 | 171 | 58 | 22.16 | -0.17 | 258 | 25.5 | -3.5 | 226 / 84 | - | 17 | 0 / 50 |
| delay_debt / all_bos / cap on | **106.33** | **23.47** | 25.15 | 135 | 58 | 83.62 | 22.72 | 242 | 36.8 | 69.5 | 147 / 53 | 21 (+16.7) | - | 187 / 0 |
| delay_debt / all_bos / cap off | 41.99 | 23.33 | 25.19 | 192 | 61 | 40.44 | 1.54 | 278 | 23.1 | 18.9 | 264 / 97 | 36 (+11.1) | 16 | 0 / 0 |
| delay_always / current / cap on | 41.92 | 33.29 | 33.37 | 144 | 46 | 42.94 | -1.02 | 175 | 24.3 | 17.6 | 227 / 83 | - | - | 89 / 36 |
| delay_always / current / cap off | 42.06 | 33.29 | 33.37 | 160 | 48 | 43.49 | -1.45 | 243 | 39.0 | 3.0 | 254 / 94 | - | 20 | 0 / 45 |
| delay_always / all_bos / cap on | 92.27 | **19.95** | 20.92 | 133 | 47 | 75.59 | 16.66 | 163 | 24.8 | 67.5 | 209 / - | see json | - | see json |
| delay_always / all_bos / cap off | 45.10 | 36.41 | 40.73 | 182 | 53 | 41.62 | 3.44 | 293 | 42.7 | 2.4 | 287 / - | see json | see json | 0 / 0 |
| half_main control (cap on, current) | 17.71 | 31.90 | 33.33 | 218 | 117 | 6.93 | 10.73 | 416 | 28.7 | -11.0 | - | - | - | 106 / 39 |

**Infinity, drag $0.35 / 0.02 lot**
| cell | net | cc DD | MTM DD | trades | MAIN $ | adds $ | H1 | H2 | setups / missed | admitted (money) |
|---|---|---|---|---|---|---|---|---|---|---|
| immediate / current / cap on (baseline) | -24.66 | 54.99 | 56.12 | 239 | -19.09 | -5.54 | 19.5 | -44.2 | - | - |
| immediate / current / cap off | 0.68 | 54.99 | 56.12 | 260 | -10.57 | 11.30 | 23.7 | -23.0 | - | - |
| immediate / all_bos / cap on | -15.56 | 48.24 | 51.50 | 264 | -22.91 | 7.40 | 20.3 | -35.9 | - | 35 (-18.9) |
| immediate / all_bos / cap off | -12.03 | 64.76 | 68.73 | 296 | -28.67 | 16.65 | 20.4 | -32.5 | - | 36 (-18.2) |
| delay_debt / current / cap on (candidate) | -6.54 | 34.41 | 35.46 | 165 | 5.47 | -12.03 | 5.6 | -12.1 | 229 / 81 | - |
| delay_debt / current / cap off | -3.26 | 29.64 | 30.83 | 165 | 5.16 | -8.43 | 12.0 | -15.2 | 238 / 89 | - |
| delay_debt / all_bos / cap on | 4.61 | 27.52 | 29.08 | 181 | 8.21 | -3.65 | 6.6 | -2.1 | 237 / 82 | 25 (-0.8) |
| delay_debt / all_bos / cap off | -6.42 | 27.52 | 29.08 | 189 | -0.70 | -5.73 | 8.8 | -15.2 | 272 / 100 | 38 (-8.2) |
| delay_always / current / cap on | 1.98 | 32.59 | 34.78 | 155 | 10.20 | -8.24 | 10.2 | -8.2 | 240 / 85 | - |
| delay_always / current / cap off | -1.64 | 41.07 | 42.39 | 159 | 5.39 | -7.06 | 17.8 | -19.5 | 253 / 94 | - |
| delay_always / all_bos / cap on | **32.23** | **27.01** | 28.95 | 162 | 31.83 | 0.36 | see json | see json | see json | see json |
| delay_always / all_bos / cap off | 2.57 | 27.01 | see json | | | | | | | |
| half_main control | -10.89 | 41.22 | 42.35 | 239 | -6.40 | -4.46 | see json | -30.4 | - | - |
(every value is in `tick_engine_matrix.json`; the console capture truncated a few cells)

**Paired contrasts, Infinity (point; CI90 5-day blocks; `tick_engine_matrix_stats.json`)**
1. Always-delay vs recovery-only delay (allowance, cap identical): drag 0: +3.9 / +20.1 / -14.1 / +3.1 net,
   DD ratios 1.27 / 0.92 / 0.85 / 1.56; drag 0.35: +8.5 / +1.6 / +27.6 / +9.0, DD ratios 0.95 / 1.39 / 0.98 /
   0.98 - every net interval includes zero except all_bos + cap_off under drag [+2.2, +15.4] (DD ratio
   CI [0.82, 1.0]). Reading: outside recovery, delaying costs more missed winners (83-94 vs 62-84) for about
   the same money; no reliable gain.
2. All-BOS recovery vs current allowance (entry, cap identical): drag 0: immediate +23.2 (cap on) / -7.2
   (cap off); delay_debt **+68.3** (cap on) / +20.0 (cap off); delay_always +50.4 / +3.0. Drag 0.35:
   immediate +9.1 / -12.7; delay_debt +11.2 / -3.2; delay_always +30.3 / +4.2. The admitted signals
   themselves: +10 to +17 at drag 0 with delayed entry, -16 to -19 with immediate entry at drag 0, and
   -18.9 immediate / -0.8 delayed under drag - the extra recovery BOS pay only when entered late at the
   midpoint. All intervals include zero.
3. Cap off vs cap on (entry, allowance identical): helps immediate entry (+28.9 at drag 0, +25.3 under
   drag, same DD) and HURTS every delayed cell (-16 to -64 at drag 0; -3 to -30 under drag): the cap ends the
   day after a target the delayed paths reach more often with less risk; without it they keep paying waits.
   All intervals include zero.
4. Interactions: admitting more recovery BOS helps only with delayed entry (+68 / +50 vs +23 at drag 0 with
   the cap on); disabling the cap reverses most of that (+20 / +3 / -7). The best cell, delay_debt +
   all_bos + cap on (106.33 / DD 23.47 at drag 0; +4.61 / 27.52 under drag), is ONE point estimate inside a
   12-cell family on one history; its H2 (+69.5) is where the whole gain sits.
5. Attribution kept: recovery delay vs half_main +20.3 [-12.0, +55.7], DD ratio 0.82 [0.45, 1.16] (drag 0).
Challenger nominated for a later registered comparison (at most one): **delay_debt + all_bos + cap on** -
the nominated recovery-delay candidate stays the fixed reference; the challenger is development-selected.

## D. Stage 2 - Compte pause / resume gate (`study/tick_engine_compte.py`, `tick_engine_compte_stats.py`)
Reference source for this run: **the demo package replayed on the demo's OWN quotes** (`demo_feed`:
`study/ticks_u477508138/` + `dev_bars_demo_u477508138.npz`): 296 closed outcomes, net +66.31 at drag 0 /
-37.32 under drag (the std-feed proxy gave +60.59 / -43.01: tighter demo spread). Only closes strictly before
the follower's MAIN signal eligibility feed the pinned controller (compte-ctl-2; global / buy / sell);
status "invalid" pauses (0 occurrences); "warming / no direction" = no information (go). Follower config
declared, not selected: immediate entry, current allowance, cap OFF. Weak predicate fixed: trend -1 and no
CHoCH up. Thinning control: every k-th eligible setup paused, k = round(1 / global pause rate) = 2 (rates
0.41 at drag 0, 0.45 under drag), both phases; it thins 50% while the directional gate pauses ~31%, so it
is matched to the GLOBAL arm only (the directional comparison against it is not rate-matched).

| Infinity | drag | net | cc DD | MTM DD | trades | eligible | paused | H1 | H2 |
|---|---|---|---|---|---|---|---|---|---|
| no_pause | 0 | 67.42 | 56.78 | 62.63 | 264 | 622 | 0 | 74.6 | -7.2 |
| global_pause | 0 | 46.56 | 54.86 | 55.63 | 192 | 693 | 282 | 74.6 | -28.1 |
| dir_pause | 0 | 54.04 | 56.78 | 62.90 | 244 | 644 | 96 | 74.6 | -20.6 |
| thin k=2 (2 phases) | 0 | -20.62 / -19.00 | 38.84 | 42.03 | 177 / 178 | ~746 | 374 / 373 | 8.5 / 10.1 | -29.1 |
| no_pause | 0.35 | 0.68 | 54.99 | 56.12 | 260 | 623 | 0 | 23.7 | -23.0 |
| global_pause | 0.35 | -28.07 | 53.89 | 54.45 | 168 | 708 | 315 | -2.0 | -26.1 |
| dir_pause | 0.35 | 3.73 | 37.67 | 38.04 | 212 | 681 | 211 | 23.7 | -19.9 |
| thin k=2 (2 phases) | 0.35 | -61.54 / -63.08 | 63.71 / 65.74 | 65.8 / 66.5 | 140 / 142 | ~575 | 288 / 287 | -22.6 / -24.2 | -38.9 |
Contrasts (CI90, 5-day): global vs none: drag 0 -20.9 [-95.8, +51.2], DD ratio 0.97 [0.38, 1.04]; drag 0.35
-28.8 [-112.0, +20.2], 0.98 [0.52, 1.79]. Directional vs none: drag 0 -13.4 [-60.1, +22.8], 1.00; drag
0.35 +3.1 [-39.5, +23.6], DD 0.69 [0.57, 1.05]. Both gates beat the 50% thinning control on net (global
+67 / +34, directional +75 / +65) but the control's drawdown is LOWER than the global gate's at drag 0.
**Reading:** the primary hypothesis (global pause) is negative on development data - it pauses 41-45% of
the eligible setups, costs profit at both cost bases and buys no drawdown. The directional version is
neutral on profit and cuts the drawdown by a third under the assumed drag only; its control is not rate-
matched, so that attribution is inadequate as it stands. The reference curve was positive early and weak
late, so every pause acted in the second half (H1 identical for no_pause and dir_pause). Source table:
every number above = demo package on the demo's own quotes (proxy for the demo's actual history: no TOUCH
path, bar-close signals); the std-feed transfer check and the two other live packages follow in the next
commit. Existing weather gates already refused 121-129 opportunities per arm before Compte saw them.

## E. Appendix - Stage 2 on the two other live packages (demo-feed reference; same rules; development)
| package | drag | no_pause net / DD | global_pause net / DD (paused) | dir_pause net / DD (paused) | thinning k (phases) net / DD | global vs none CI90 net | dir vs none CI90 net / DD ratio |
|---|---|---|---|---|---|---|---|
| u224016179 | 0 | 64.02 / 62.19 | 32.66 / 57.93 (282 of 709) | 54.34 / 61.10 (107) | k=3: -1.3, -11.2, +0.9 / 55, 46, 57 | [-101, +39] | [-58, +28] / 0.98 [0.79, 1.11] |
| u224016179 | 0.35 | -33.48 / 64.70 | -60.20 / 74.40 | -6.10 / 44.17 (211) | k=8: -47, -38, -39, -33 / ~74 | [-133, +18] | [-24, +65] / 0.68 [0.46, 1.05] |
| bos | 0 | 112.52 / 127.33 | 56.98 / 116.65 | 82.66 / 117.37 (96) | k=3: +57, -8, +57 / 90, 100, 90 | [-213, +87] | [-111, +11] / 0.92 [0.84, 1.13] |
| bos | 0.35 | 7.13 / 129.72 | -61.67 / 150.84 | 41.24 / 82.26 (211) | k=2: -68, -62 / 78, 81 | [-293, +73] | [-58, +111] / 0.63 [0.47, 1.00] |
Reading across the three live packages: the GLOBAL pause (primary hypothesis) is negative on every row at
both cost bases - it pauses 40-45% of eligible setups (13% on Depenses under drag, where the demo curve
was weak less often from that follower's clock) and never buys drawdown. The DIRECTIONAL pause costs profit at
zero drag on all three and, under the assumed drag, raises the net on all three (+3 / +27 / +34) with
drawdown ratios 0.63-0.69 whose intervals touch 1.0; its thinning control is matched to the global rate,
not to its own ~31% rate, so that attribution is INADEQUATE (a rate-matched control is the obvious next
control - not run here, so as not to search). Every net interval includes zero. Compte as a pause gate:
primary = negative; directional = a conditional, cost-dependent, unmatched point pattern - not a pass.

**Transfer check (Infinity, reference replayed on the STD feed instead of the demo's own quotes; same rule,
same follower):** reference 296 outcomes +60.61 / -43.01. global_pause 7.43 / DD 53.72 at drag 0 (demo-feed
source gave 46.56) and -37.48 / 63.31 under drag (demo: -28.07 / 53.89); dir_pause 56.62 / 56.78 (demo 54.04)
and 6.13 / 35.27 (demo 3.73 / 37.67). The same strategy on a different quote feed builds a different outcome
curve and the global pause's decisions move with it (-21 vs -60 against no-pause at drag 0): the gate does
not transfer robustly across feeds; the directional one moved less. Both source histories are labelled
apart in `tick_engine_compte_demo_feed.json` / `tick_engine_compte_std_feed.json`.
