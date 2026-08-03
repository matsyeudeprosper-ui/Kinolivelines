# HANDOFF — read this before proposing anything

You are picking up a systematic trading research project that has tested **~20 ideas to
completion**. Almost all of them are closed. This document exists so you do not spend the
user's time re-running experiments that already have answers.

**Read this file, then `RESEARCH_MAP.md`, then `FINDINGS.md` (13 traps) before suggesting
a strategy.** If your idea appears in the closed list below, it is closed — including
"but with a different indicator/parameter/timeframe."

Repo: https://github.com/matsyeudeprosper-ui/Kinolivelines
Accounts: DEMO Exness 436771046 (research), LIVE Exness 134499778 (small mirror, real money)

---

## 1. The one-paragraph summary

No systematic edge is findable on this account. That is **not** "no edge exists" — it is
that this instrument universe cannot *resolve* one. Three portfolio-level tests each
required an effect several times larger than the strategy family actually delivers in
reality. Two things do measurably work — delta-neutral perp carry, and a diversified hold
basket — and neither is reachable with the user's capital (~$1,000). **Capital, not
strategy, is the binding constraint.**

---

## 2. CLOSED — do not re-open without new information

| hypothesis | verdict | where |
|---|---|---|
| Price/OHLC/indicator timing on BTC (15 tests) | null | `mt5_ohlc_hypothesis_closed` |
| Funding rate as a DIRECTION signal | null | `funding_edge.py`, `funding_phases.py` |
| COT positioning as a direction signal | died out-of-sample on 20 unseen markets | `cot_*.py` |
| Basis / spot-perp spread | null | `basis_edge.py` |
| Broker feed lag / latency arb | null on all 4 preregistered criteria | `broker_lag2.py` |
| DVOL (all 4 preregistered questions) | null; Q2 died out-of-sample | `dvol_*.py` |
| Order-book imbalance | **REAL but 5x too small** — $2.04 move vs $10 cost | `orderflow_concentration.py` |
| Stop/target geometry search (30 shapes) | all tied; loss = the spread | `sim_variants.py` |
| Cross-sectional momentum, 19 US stocks | null, MDE 1.47%/rebalance | `xs_momentum.py` |
| Cross-sectional momentum, 57 crypto perps | null, MDE 3.23%/rebalance | `xs_crypto.py` |
| Trend following, 13 instruments | **underpowered, NOT disproven** — MDE 10.2%/yr | `trend_following.py` |
| **FX cross-sectional momentum 3M-1M V1** | **FAILED** 5/13; −$75.94, PF 0.529, p 0.7286 | `fx_momentum_v1.py` |
| **FX policy-rate differential V2** | **FAILED** 6/16; −$49.93, PF 0.826, p 0.5525 | `fx_policy_differential_v2.py` |
| The demo↔live mirror as a money-maker | arithmetic: costs 2 spreads, cannot win | `KLMirror.mq5` header |

**On the two FX families:** both were preregistered and frozen by the strategy lead, and both
failed on *direction*, not cost — doubling every spread moved V1 by ~$1 and V2 by $5.54. V2
additionally established that **this broker pays exactly 0.00% carry on the side a
policy-differential signal selects**, across all 19 executable pairs, so a carry-shaped
family collects nothing here by construction. Full detail in `FINDINGS.md`.

### The order-book one deserves emphasis
It is the **only** signal in the project that beat its error bar on the Exness feed
(53.5% vs 47.3% up-rate at 30s, non-overlapping windows, 54k samples). It is closed **by
magnitude, not by sample size** — a $2 move cannot pay a $10 round trip. Concentrating on
the most extreme books makes it *worse* (up-rate falls to 47.7% at the top 1%). Cost cannot
be cut: Exness Standard $10, Exness Zero for BTCUSD $8.75, Pepperstone $10–20, OKX perp
$63 (percentage fees on a $63k notional are brutal). **Do not propose "collect more data
and re-test."** That is the answer to a null, not to a measured effect that is 5x too small.

---

## 3. WORKS — but not at this capital

**Delta-neutral perp carry** (`carry_test.py`, 7.25 yrs Deribit BTC+ETH)
- funding alone: BTC +7.82%/yr — *the number people quote*
- naked short (no spot leg — what Exness gives): **−145.74%/yr**
- delta-neutral (short perp + hold spot): **+7.80%/yr**, positive in 7 of 8 years
- **The premium has compressed**: last 12 months +3.13%, last 6 months **+0.73%**
- Needs spot+perp on one venue. **Exness has no spot.** Unmodelled: exchange counterparty
  risk (FTX), liquidation risk, basis tracking error.

**Diversified hold basket** (`portfolio_hold.py`, `portfolio_honesty.py`)
- equal weight 1x: 15.0%/yr, 32% max DD, Sharpe 0.70 — vs BTC alone 19.4%/yr, 78% DD, 0.27
- **The robust part is return-per-drawdown**, which follows from correlations < 1 and does
  not depend on the period.
- **The return is NOT robust.** No holdout, no control. The two halves of the window differ
  by 2x (+8.9% vs +17.7%/yr). 16% of 1-year windows lost money. The Nikkei once took 34
  years to recover and JP225 is the top-ranked instrument here.
- **BLOCKED BY MINIMUM LOT SIZES** (`portfolio_feasibility.py`): JP225 min lot is 3.00 =
  **$188,684** notional. The 8-name basket ex-JP225 needs **~$13,200** at 1x. At $1,000
  exactly ONE name fits — UK100, which returned 0.2%/yr.

---

## 4. STILL OPEN — the only genuinely live question

**Liquidation cascades.** Preregistered in `PREREGISTRATION_liquidations.md`, gated at
**≥400 independent cascades in development AND ≥100 in untouched holdout**. The gate exists
specifically so an underpowered null cannot be mistaken for a finding — the error already
made once on the crowding branch. **Do not run the outcome test before the gate.** The two
recorders collecting it are IRREPLACEABLE; their history cannot be backfilled.

**Status at 2026-08-03** (task 006 read-only audit, no outcomes examined): 2,947 events over
3.22 days → **5 independent cascades**, split **4 development / 1 holdout**. Remaining:
**396 development, 99 holdout**.

**An earlier version of this file said "roughly 85 days out at 42.6 events/hour". That was
wrong on two counts** and is corrected here:

- it used the **event** rate, not the independent-**cascade** rate. A cascade is a top-5%
  5-minute *bucket* ranked on a trailing 30-day window, and after 4-hour independence they
  arrive at ~**1.55/day**, not 42.6/hour;
- it ignored the **holdout arm**. Satisfying both arms under the 75-25 split needs ~533
  independent cascades, not 400.

At the current pace that is **several hundred days**, not 85. Pace is regime-dependent and
the trailing threshold moves with it, so no date is promised — **the trigger is the count.**

**Feed caveat:** the OKX endpoint returns at most 100 events per poll and four minutes have
already carried ≥90. Cascades are precisely the busiest minutes, so the feed may be
truncating the episodes the hypothesis is about. Flagged in task 006, not fixed (task 006
was forbidden from changing recorder settings).

---

## 5. METHODOLOGY — the standards this project holds to

These were all earned by getting something wrong first. `FINDINGS.md` has 13 traps in full.

1. **Non-overlapping windows.** Overlapping shrank standard errors 5.3x here.
2. **Random controls, and trust them over the textbook.** On the 19-stock panel, random
   ranking produced |t| up to **4.1** at the 95th percentile — the usual |t| > 2 bar would
   have manufactured findings that coin-flip ranking beats 30% of the time.
3. **Compute the MDE before interpreting a null.** Three of the tests above are
   underpowered rather than negative, and saying so is the difference between honesty and
   a false verdict.
4. **Costs in from the start, never bolted on.** A fixed-dollar spread scales inversely
   with ATR; assuming a constant ATR-cost invents edge in quiet regimes.
5. **Judge money per trade, not win rate**, whenever stop/target distances vary. A 71.6%
   win rate in this journal LOST $20 over 116 trades.
6. **Two-sided rotation nulls**, split-half or date-split validation, never shuffled.
7. **UNITS.** Three separate 100x errors in one session: swap is per LOT while ranges are
   per SHARE (stock lot = 100 shares); `swap_mode` is POINTS not currency (multiply by
   `point * contract_size`); and `symbols_get()` returns **356** symbols while filtering on
   `visible` returns 174. Always convert explicitly and sanity-check the magnitude.

---

## 6. LIVE SYSTEM — what is running and must not be broken

- `live/daemon.py` — decision loop on the DEMO account. **`KL_PROVIDER=session`** is a
  USER environment variable so it survives restarts; the attached AI session is the
  primary decider, GPT-5 is fallback after 20 min of silence. **This requires a Monitor
  armed on `daemon.log` for `DECISION NEEDED|AWAIT_SESSION|ALL PROVIDERS FAILED`**, or
  handoffs are written and nobody reads them while every heartbeat stays green.
- `live/act.py` — the ONLY path that touches the demo. Hard demo-only guard; **never
  remove it**. `MAX_LOTS = 0.01`.
- `live/mirror_publisher.py` + `KLMirror.mq5` — mirrors demo trades to the LIVE account
  reversed, barriers matched by price and **shifted one spread** so both sides close on the
  same tick. Costs ~$0.20/pair at 0.01 lots. It is an execution log, not a strategy.
- `recorder/` — microstructure + derivs recorders. **IRREPLACEABLE.**
- Restart procedures: `RESTORE.md`. Restart the daemon via
  `Start-ScheduledTask "KinoliveLines Daemon"`, never a bare `Start-Process` — that drops
  the environment. Match `pythonw.exe` as well as `python.exe` when killing it.

---

## 7. Things NOT to do

- Do not propose a 21st indicator or strategy family for this account. The constraint is
  breadth and cost, not the signal.
- Do not present a backtest CAGR as an expectation.
- Do not point the user at copy-trading, signal groups or prop-firm challenges. They asked
  once; that request profile is what those operations target, and it was declined.
- Do not tell the user a strategy is guaranteed. Nothing here is.
- Do not remove the demo-only guard in `act.py`.

---

## 8. Communication

The user is not a native English speaker and has asked **three times** for plain, short,
summarised answers. Lead with the answer. Numbers over prose. Compress the explanation,
never the substance — a short answer that hides a problem is worse than a long one.
