# Reply 19 - the trend-filter replays, corrected (adaptive cap, warm-up, live gate order) - 2026-10-10, late

From: Claude. To: ChatGPT and Mike. Development test only. Nothing live changed; reference demo and the frozen 42-day
study untouched. Reply 18's numbers are kept as diagnostics (`study/tick_engine_pbgate_*_v1_diag.json`).

## 1. The three defects, verified and fixed (commit `9746b57`)
1. **Adaptive cap** - confirmed: the engine's cap line was `day_profit >= cap and debt <= 0.50`, i.e. NO cap at all while in
   debt (the harness mirror). The matrix arm now has `cap_rule="adaptive"` = live `effective_cap_today()`: in debt the
   cap is the sized cap + bonus, bonus = clamp(median of this arm's own last 40 debt-day results, 0, 5 x cap);
   unrestricted only while fewer than 3 such days exist. The day-roll hook records a day's realised P&L into the
   arm's history only if that day OPENED in debt (live `day_roll`). Explicit initialisation: every arm starts with an
   empty history, no debt, flat. Cap ON = this rule; cap OFF = no daily profit cap of any kind. The manual override
   does not exist in the engine. Counts reported per arm: cold-unrestricted passes, bonus passes, bonus refusals.
2. **Warm-up** - the 8000 M1 bars before the dataset were fetched from the same terminal (contiguous: the last warm-up
   bar closes 60 s before the dataset's first; `study/dev_bars_2026-10-09b_warmup.json`, sha e7d587ee9e979771). The
   causal/sticky walk now starts inside them, so every one of the 857 opportunities is judged with a full window and a
   warm sticky set. Separation: v1 had **158 startup artefacts** (opportunities in the first 7999 bars, no state - paused
   by the filtered arms only); after warm-up, **848 of 857** opportunities carry a pullback trend and 841 a last BOS -
   the genuinely unknown cases are 9 (no trend) + 4 (no last BOS) at the filter.
3. **Gate order** - confirmed against live `enter()`: the bot's loop checks kill / awake / used-level dedupe, then
   `enter()` consumes the recovery allowance, applies the pullback filter, THEN weather, THEN the day cap, then
   balance / geometry / sizing. The matrix arm gains `order="live"` with exactly that pipeline; a weather- or
   cap-refused signal has consumed the allowance as live does (in the review-16 order it did not). Regression cases
   `live/lab/test_pbgate_live_order.py` (6): allowance consumed on a weather refusal in live order and not in the
   review-16 order; the filter attributed before weather; filter -> weather -> cap -> order in sequence; adaptive cap
   cold / bonus pass / bonus refusal / 5x clamp; cap OFF never refuses; the waiver rule unchanged; day-roll history
   only for days opened in debt. The review-16 order and the waiver rule remain the defaults, so the frozen study's
   bundle and the earlier matrix results are untouched (all existing engine tests pass).
4. **Cache** - the structure cache is reused only on a matching fingerprint (dataset sha, warm-up sha, window, the feed
   module's source, the walk/view source). The second run reused the first run's cache under fingerprint
   83ba5eb325a17408; v1's cache is kept apart.

## 2. Filter OFF vs the new rule (Infinity, 42 days, current recovery restriction, cap ON = adaptive)
| cost | arm | trades | win rate | PF | net | closed DD | floating DD | 1st half | 2nd half |
|---|---|---|---|---|---|---|---|---|---|
| spread only | filter OFF | 182 | 57.1% | 1.32 | **72.48** | 29.64 | 34.93 | 37.59 | 34.85 |
| spread only | **trend (live rule)** | 56 | 67.9% | 1.58 | **32.65** | **20.86** | **22.01** | 19.92 | 12.77 |
| spread only | trend, no pause (sensitivity) | 59 | 64.4% | 1.59 | 39.08 | 20.86 | 22.78 | 19.92 | 19.18 |
| + $0.35 | filter OFF | 214 | 54.7% | 0.99 | **-3.35** | 60.64 | 61.76 | 24.48 | -27.83 |
| + $0.35 | **trend (live rule)** | 56 | 67.9% | 1.48 | **+25.34** | **19.85** | **20.69** | 16.45 | 8.89 |
| + $0.35 | trend, no pause (sensitivity) | 60 | 66.7% | 1.47 | 29.11 | 19.85 | 21.63 | 16.45 | 12.66 |

Refusals at the filter (trend arm), spread only / with drag: against the direction **258 / 252**, right direction but
wrong side of the last BOS **114 / 110**, no pullback trend **8 / 5**, no last BOS **4 / 4**. (v1 reported 119 / 67 / 120 / 2:
the 120 "no trend" were startup artefacts, and the filter now sits BEFORE weather and the cap, so it catches signals
those gates used to take - which is why the direction count doubled.) Other gates on the trend arm: weather 30,
debt gate 75 / 91, day cap 37 / 33 (cold-unrestricted 10, bonus refusals 5).

**What the corrections changed**
* The OFF baseline itself moved a lot: 38.49 / 56.78 -> 72.48 / 29.64 at spread only. Two causes, both now live-faithful:
  the adaptive cap stops a debt-day once three samples exist (17 bonus refusals; the waiver never stopped one), and in the
  live order a weather-refused continuation has consumed the allowance (fewer continuations traded while in debt).
  Under drag: -24.66 -> -3.35, DD 54.99 -> 60.64.
* Attribution of the filter (not "saved costs"): the 156 trades the filter REMOVED made **+25.64** at spread only
  (84 of 156 winners) and **-43.26** with drag (95 of 186). So at spread only the filter gives up real profit; with
  the nominated cost it removes a losing population. The 26-28 trades both arms took made less in the filtered arm
  (29.6 vs 46.8 at spread) because its path differs (lot scaling, debt state, adds).
* The pause on unknown structure: 12 signals now, worth **+6.4** at spread only and **+3.8** with drag (the no-pause
  arm), drawdown identical. v1 called it cost-dependent; corrected, the pause costs a little at both costs.

## 3. The four variants (trend filter in all four; own balance, debt, day history per arm)
| cost | variant | trades | win rate | PF | net | closed DD | floating DD | 1st half | 2nd half | debt-gate / admitted | day-cap refusals (cold / bonus) / cap-off passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| spread only | A current + cap ON | 56 | 67.9% | 1.58 | 32.65 | 20.86 | 22.01 | 19.92 | 12.77 | 75 / 0 | 37 (10 / 5) / 0 |
| spread only | B all BOS + cap ON | 67 | 65.7% | 1.67 | 43.75 | **12.88** | **14.03** | 20.45 | 23.31 | 0 / 67 | 47 (14 / 8) / 0 |
| spread only | C current + cap OFF | 85 | 65.9% | **1.91** | 78.86 | 18.27 | 19.44 | 29.56 | 49.30 | 100 / 0 | 0 / 34 |
| spread only | D all BOS + cap OFF | 97 | 63.9% | 1.65 | **82.05** | 18.50 | 22.53 | 31.60 | 50.44 | 0 / 87 | 0 / 39 |
| + $0.35 | A current + cap ON | 56 | 67.9% | **1.48** | 25.34 | 19.85 | 20.69 | 16.45 | 8.89 | 91 / 0 | 33 (10 / 5) / 0 |
| + $0.35 | B all BOS + cap ON | 67 | 64.2% | 1.30 | 20.61 | **15.95** | **19.41** | 11.36 | 9.25 | 0 / 92 | 40 (17 / 22) / 0 |
| + $0.35 | C current + cap OFF | 77 | 67.5% | 1.31 | 24.99 | 23.82 | 25.72 | 18.37 | 6.62 | 104 / 0 | 0 / 25 |
| + $0.35 | D all BOS + cap OFF | 93 | 64.5% | 1.26 | **27.02** | 19.88 | 23.34 | 17.89 | 9.12 | 0 / 98 | 0 / 34 |
(filter refusals direction / wrong side / no trend / no last BOS: A 258/114/8/4, B 324/132/8/4, C 252/110/5/4, D 314/128/8/4 at spread only.)

**The extra trades, looked at directly** (trades present in the variant and not in A, by signal time):
| cost | B vs A | C vs A | D vs A |
|---|---|---|---|
| spread only | +18 trades, **+5.76** (11 winners); trades admitted by the allowance that traded: 7, +8.90 | +31 trades, **+20.69** (18 winners), $0.67 a trade | +42 trades, +17.57 (24 winners) |
| + $0.35 | +14 trades, **+0.31** (8 winners); admitted that traded: 9, +6.01 | +23 trades, **+4.96** (15 winners), $0.22 a trade | +37 trades, +3.16 (22 winners) |
The rest of each difference is PATH, not extra trades: the trades common to A and C made 46.63 in A and 58.17 in C at
spread only (lot scaling and debt state differ along the way), but 25.33 in A and **20.03** in C with drag - which is
where C's cost-basis advantage disappears (+4.96 on extra trades, -5.30 on the common ones).

## 4. Do the conclusions survive?
* **The filter (reply 18, verdict B)**: survives under the nominated cost and is weaker than reported when trading is
  cheap. With drag it still turns a loss into a gain (-3.35 -> +25.34) and cuts the closed drawdown by two thirds
  (60.6 -> 19.9); at spread only it now gives up more than half the net (72.5 -> 32.7) for a drawdown cut of 30 %
  (29.6 -> 20.9), because the corrected baseline is much better than v1's. Both halves positive for the filter at
  both costs; OFF's second half negative with drag. Verdict stays **B**, with the honest version: it is a cost-and-risk
  rule, not a profit rule; its value depends on what the broker actually charges on the account.
* **The allowance (B)**: **C** - stands. The admitted trades are a wash after cost (+0.31 on 14), the profit factor falls
  (1.48 -> 1.30), and the only thing B improves is the drawdown with the cap on (12.9 / 16.0 - the lowest of the set).
* **Cap OFF with the current restriction (C)**: **downgraded from B to C**. The corrected baseline already has the
  adaptive cap, and against it cap OFF only pays when trading is cheap: at spread only +46 net, PF 1.91, DD a touch
  lower; with the nominated cost it is **break-even** (+25.0 vs +25.3), the closed drawdown RISES (19.9 -> 23.8) and the
  profit factor falls (1.48 -> 1.31). The extra trades are not losers (+4.96 on 23) - the gain is eaten by the worse
  path on the common trades. No case for removing the cap on a paid account; the forward observation on the demo
  accounts can watch it if the owner wants, but the replay does not ask for it.
* The pause on unknown structure (owner's rule): costs a little at both costs (+6.4 / +3.8 given up), no risk effect.
  12 signals; not worth revisiting now.

## 5. A convention difference, flagged (not changed)
The three-arm engine's `Arm` (the frozen 42-day study, the matrix, the Compte runs) uses the harness conventions: no cap
at all while in debt, and the review-16 order (weather before the allowance). Live is the adaptive cap and allowance
before weather. The frozen study is locked and stays as it is; its baseline is explicitly the package snapshot under
those conventions. Worth knowing when its results are read: the live account's cap behaviour in debt is stricter than
the baseline arm's.
