# Reply 22 — Valère simulator fidelity: diagnosed, one engine bug fixed, rules + execution now faithful

Resumes `review/VALERE_FIDELITY_HANDOFF.md` (steps 2–4). Account u224016179, his own bid/ask ticks,
2026-09-14 22:46 → 2026-10-12 UTC. No live trading rule was changed.

## 1. Why the open-loop replay could never match (and must not be judged on its total)

The decision table (`study/valere_decision_table.py`, every engine signal with the gate that decided it)
showed the gap is dominated by **state drift**, not rules. Example, 2026-10-08: both sides closed the
same day-crossing winner (real +6.50, engine +5.35). The real bot's in-debt cap had a **zero** bonus
(its real debt-day history) → day limit, stop. The engine's bonus was **$4.27** (its own simulated
history) → it kept trading, 16 more trades, −$22.49, and its debt drifted to 2× the real one. From then
on every state-dependent gate (day cap, debt rule, adds) diverges. Tuning rules against that total
would be tuning to the result.

## 2. The method that works: synchronised replay

Before every signal the engine receives the REAL account's state (debt and pot from the bot's own
WIN/LOSS log lines; day result, streak, open position from the broker ledger; the day cap from the
bot's own "day cap now" lines; the debt-day history rebuilt as the live bot builds it). Decisions are
the engine's own.

`study/valere_sync_decisions.py`: **497 of 505 signals decided identically (98.4%)**.
Residual 8: 3 = the documented 2026-10-12 race on the movement counter (non-deterministic), 1 =
storm threshold at 1.85 by rounding, 4 isolated. 9 real trades had no engine signal: 8 pre-journal
(entry time estimated), 1 internal entry (not modelled).

## 3. Rule history the replay was missing (schedule additions, `study/replay_valere_real.py`)

* the movement gate counted a flip's **own** break until 9ff36ce (2026-10-12 07:09 UTC) — journal: 15
  real FLIP-BOS entries had movement 1–2 where the strict count is 0;
* the nervosity brake was **ON** 2026-09-18 08:45 → 09-22 14:37 (restarts; first/last refusal
  09-19 15:42 / 09-22 02:13);
* the pullback-direction gate was **live** from 2026-10-10 08:49 (2b1a602; first refusal 10:08) —
  previously only a hypothetical arm.

## 4. The engine bug (fixed, tested)

Live: an add at the midpoint risks **half** the stop — `risk001 = 0.5 × dist × 0.01`.
`study/tick_engine.py` and `live/lab/harness.py` used the **full** distance → they bought about half the
bullets and mis-sized `by_debt`. Fixed in both; `study/test_add_sizing.py` checks the engine's add count
against the live formula (5/5).

## 5. Execution fidelity after the fix — `study/valere_sync_exec.py`

Same decision + same state (real lot, real balance) on 87 paired trades:

| | real | engine |
|---|---|---|
| total | +35.89 | +35.84 |
| main legs (76 journal trades) | −21.79 | −24.54 |
| adds | +27.99 | +24.78 |

* same win/loss on **87/87**, same lot 87/87, close time median **0 s** (75 within 5 s);
* per trade |real − engine|: **median $0.10**, 90th pct $0.68, 74/87 within $0.50; main legs off by
  ~$0.04/trade (spread/slippage scale);
* halves: −3.72 / +3.77 — the near-zero total is partly cancellation; the per-trade figures are the
  honest accuracy statement.

Before the fix the adds alone were off by $22.97 (real +27.99 vs engine +5.02).

## 6. Consequences

* Every backtest that used the harness or the tick engine **under-counted recovery adds** in debt. Lab
  proofs, robot tests (Owl +57, Pekos +66) and market tests must be **re-run** (backtest precision plan).
* Product backtests are open-loop by nature: drift is not an error there (the path is self-consistent).
  What had to be proven is that rules and execution match the live bot — §2 and §5.
* Not yet done: handoff step 5 (the filter question) on the fixed baseline.
