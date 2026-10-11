# Valère simulator-fidelity diagnostic - handoff (saved 2026-10-11 04:30 UTC)

Scheduled resume: **Friday 2026-10-16 14:00 Europe/Paris = 12:00 UTC = 07:00 VPS local (Central)**. A one-shot
reminder exists in the Claude session that saved this file (session-only: it fires only if that session is still open).
The durable part is THIS file plus the memory note `mt5_valere_fidelity_diagnostic`. If no session is open then, the
owner starts one in `C:\Projects\KinoliveLines` and says "resume the Valère fidelity diagnostic".

No live trading-rule change is part of this work.

## 1. Question (GPT, 2026-10-11)
Why does the tick engine still differ from Valère's real bot? Compare actual vs simulated DECISIONS trade by trade.
Do not tune the model to match total profit. First establish baseline fidelity WITHOUT the filter, then rerun WITH it.

## 2. Inputs (all on the VPS, nothing proxied)
| what | where |
|---|---|
| Valère's own ticks (Exness-MT5Real30 BTCUSD), 2026-08-28 -> 2026-10-11 03:20 UTC | `study/ticks_u224016179/`, `study/ticks_u224016179_forward/` (+ manifests, committed); refresh with `python study/fetch_ticks.py --forward --uid u224016179` |
| Valère's own M1 bars 2026-09-08 -> | `study/bars_u224016179.npz` (+ `.json` meta, committed); refresh with `python study/fetch_bars_uid.py --uid u224016179 --from 2026-09-08T00:00:00` |
| real closed legs (broker deals) | `live/lab/wealth/u224016179.json` (`trades`: [t_close, pnl, lot, dir, minutes]) ; grouped copy `review/valere_actual_ledger_grouped.csv` |
| real trade-context journal (from 2026-09-24): kind, is_add, lot, entry/exit UTC, entry price, sl, tp, nervosity, movement, trend, debt_at_entry, balance_at_entry, outcome, profit | `live/bos_journal_valere.csv` (84 rows: FLIP-BOS 40, BOS 27, INT 1, ADD 16) |
| bot log (every decision and refusal, restarts, the override) | `live/bos_bot_valere.log` |
| rule timeline (git-dated) | `study/replay_valere_real.py` SCHEDULE; `git log --since=2026-09-13 -- live/structure_bos_bot.py live/owl_packages.json` |
| engine | `study/tick_engine.py`, `study/tick_engine_matrix.py` (PolicyArm: order="live", cap_rule adaptive/waiver/off), `study/tick_engine_pbgate.py`, `live/pb_gate.py` |
| replay script + results | `study/replay_valere_real.py` -> `study/replay_valere_real.json`, `review/valere_replay_<arm>_drag<0|035>.csv`; sticky structure cache `study/pb_state_sticky_cache_valere_own.pkl` (fingerprint = bars sha + feed source + walk source; reused when unchanged) |
| report so far | `review/RESEARCH_REPLY_21_2026-10-11.md` (corrected 10-11: balance arithmetic, pairing claim) |

## 3. Findings so far (baseline = actual rules, no filter, Valère's own quotes, 09-14 22:46 -> 10-11 03:20 UTC)
* Engine +0.81 (spread only) vs real +48.39. 85 engine trades vs 87 real grouped trades (110 legs).
* Pairing by side + close time (10 min): 57 pairs - 48 within 1 s, 53 within 60 s, worst 380 s. On the pairs: engine
  +21.58 vs real +44.59. Engine-only 28 trades: -20.79. Real-only 30: +3.80.
* Adds: real adds (15 legs at 0.03-0.05 lot) +32.72; engine adds -3.05 on 38 adds (spread only). THE largest gap.
* Defect found by GPT and fixed 2026-10-11 (commit after this file): `cap_rule="off"` (the recorded manual override)
  still applied the normal cap outside recovery; now a lifted cap is lifted everywhere. The override window is only
  2026-10-10 07:05 -> 10-11 03:20 UTC. RERUN DONE (`study/replay_valere_real_v2.out`, structure cache reused): every
  figure identical to reply 21 - no signal in the override window met the cap outside recovery, so the defect had no
  effect on these numbers. The fix stands for any future run.
* Proof-page $200 test: daily balance scaling of lot and cap was missing; fixed (`study/proof_current_rules.py`,
  scale_lot/scale_daily on) and rerun (`live/lab/proof_current.json`).
* Known model gaps (not yet quantified per trade): live add/bullet sizing and funding (jar budget, by_debt, BLOT),
  live main-lot arithmetic (scaling floor, 3 % fit, 10 % cap), the real bot's gate state at the moments of the 28
  engine-only trades, dedupe (the engine marks a close-BOS level used; the live close-BOS path does not), internal
  entries 09-19 -> 09-30 (1 real trade), adds at the BOS entry before 09-20, the nervosity-brake package history.

## 4. Resume - exact steps (estimated 3 h)
1. `cd C:\Projects\KinoliveLines`; refresh data if wanted (commands above); confirm the bots are untouched
   (`git status`, no live edits).
2. Build the decision table: `study/valere_decision_table.py` (TO WRITE): for every real journal row (entries incl.
   adds) and every engine trade/event of `actual_rules` (drag 0.00 - his own spread), one line per entry with
   entry UTC, kind, side, lot (real vs engine), adds (count, lot, price real vs engine), debt / balance at entry (real
   journal vs engine state), outcome and P&L; plus every engine-only entry with the bot log lines of that minute
   (grep the log +/- 2 min for "refuse", "skipped", "asleep", "dette", "LIMITE", "repli", "position") and every
   real-only entry with the engine's gate counter at that signal (why it did not fire: not_awake / dedupe / weather /
   debt_gate / day_cap / skipped_open / bot_down).
3. Quantify the gap by cause, in dollars, without touching the model: (a) sizing on paired trades (same entry, real lot
   vs engine lot, real adds vs engine adds), (b) engine-only entries by refusal reason, (c) real-only entries by engine
   gate. Then and only then decide which model difference is a BUG (fix) and which is a known simplification (document).
   Candidates: the live bullet funding (`structure_bos_bot.py` try-adds / jar arithmetic vs `tick_engine.Arm.try_adds`),
   the live lot at entry (`sized lot` with scaling floor and the 3 % fit) vs `size_at_fill`, the close-BOS dedupe.
4. Fix only confirmed bugs (unit test each), rerun `python study/replay_valere_real.py` (cache reused, ~10 min if the
   walk source is unchanged), re-pair, report baseline fidelity (paired / engine-only / real-only, by cause).
5. Only then the filter: same script already runs `actual_rules_filter`; report old vs filtered on the fixed baseline
   and the filter applied to the real trades (selection on real P&L, no multiplication).
6. Reply 22 for GPT in `review/`, commit, push; update the memory note.
