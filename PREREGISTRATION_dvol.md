# Pre-registration — DVOL / variance risk premium (H6)

**Written 2026-08-01, before any outcome was examined.**

## The distinction this test must not blur

The variance risk premium is an **options** phenomenon. That implied volatility exceeds
realised volatility on average is well documented and almost certainly true here too —
and it is **not** by itself a directional edge on a BTCUSDm CFD. Harvesting the premium
requires selling options, which this bot cannot do.

So four separate questions are asked, and they have different bars. Only Q1 could produce
a directional edge. Q2 is expected to succeed and would prove nothing on its own. Q3 and
Q4 can only count if they improve an **implementable BTCUSDm rule**.

If the only surviving effect requires selling options, it is recorded as **economically
real but outside the executable universe** — not as a strategy.

---

## Frozen definitions

| term | definition |
|---|---|
| **DVOL** | Deribit 30-day implied volatility index, hourly close, annualised % (`dvol_BTC.csv`, `dvol_ETH.csv`) |
| **RV_trail** | annualised stdev of hourly log returns over the trailing **720 hours**, matching DVOL's 30-day horizon |
| **VRP** | `DVOL(t) − RV_trail(t)` — the **ex-ante** premium, fully known at time *t*. The realised premium `DVOL(t) − RV_forward(t, t+30d)` is the true quantity but is unknowable at entry and is therefore never used as a signal |
| **VRP rank** | trailing **720-hour** percentile of VRP. Never full-sample |
| **extreme** | rank ≤ 5% or ≥ 95% |
| **normal** | rank between 20% and 80% |
| **entry** | the hourly close **after** the signal hour has closed |
| **horizons** | 4h, 24h, 72h |
| **costs** | BTCUSDm $10 spread + $2/side slippage; ETH $1.00 spread + $0.20/side |
| **holdout** | **2025-08-01 onward**, never inspected during development |

---

## The four questions and their pass/fail rules

### Q1 — does VRP predict BTC **direction**?
The only question that could yield a directional edge.

Passes only if **all**: beats a **volatility-matched** random-entry control by >2SE; same
sign in ≥4 of 5 entry-volatility quintiles; replicates on ETH; holds on the untouched
holdout; stable at neighbouring thresholds (3% and 10% as well as 5%); and the capturable
move exceeds **$14** by a clear margin.

*Prior: low.* Every directional test in this project has failed, and there is no strong
reason a volatility quote should carry directional information.

### Q2 — does VRP predict future **realised volatility**?
Expected to pass, and worth almost nothing alone.

Bar is therefore **incremental**: DVOL must beat `RV_trail` as a predictor of forward
realised volatility by >2SE. Simply correlating with forward vol is not a result — trailing
vol does that too.

### Q3 — does VRP predict **adverse excursion / stop-out risk**?
The most plausible useful outcome, and the same shape as the crowding finding.

Passes only if: stratified by entry volatility (unstratified comparisons of ATR-normalised
excursions have inverted their own sign in this project before); >2SE; ≥4 of 5 quintiles;
replicates on ETH; holds on holdout. **And** it must change an implementable rule — a
stop-out difference under ~2pp cannot move sizing or stop placement enough to matter.

### Q4 — does VRP identify **regimes** where trend or mean-reversion behaves differently?
Passes only if the momentum-versus-fade difference **flips sign or differs by >2SE**
between high and low VRP, on **both** instruments, in development **and** holdout. A
difference visible on one instrument is that instrument's history.

---

## Global controls (all questions)

- volatility-matched random controls — an unmatched control produced a false positive on
  both mirror arms earlier in this project
- non-overlapping windows, all phases pooled
- two-sided rotation nulls
- mirror-arm sanity: fade and follow cannot both look good
- chronological holdout, never touched during development
- ETH as the replication universe. **No equity, metal, agricultural or FX proof is owed** —
  this is a crypto options mechanism

## Economic gate

A volatility-only result is **not** a strategy edge unless it demonstrably improves
position sizing, stop placement, trade selection or exposure timing on BTCUSDm. Anything
requiring options execution is logged as real-but-not-executable.

## Amendments

*(none — any change after outcomes are seen must be logged here with date and reason)*
