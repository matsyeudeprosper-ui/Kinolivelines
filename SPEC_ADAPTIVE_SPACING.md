# SPEC: Adaptive spacing for harvest (the "custom chart" idea)

*Preregistered 2026-08-07, before any code. The idea came from the KLCustomChart
breakout candles: their trigger distance scales with volatility by construction,
while renko's 50-point brick is fixed and drifts (brick watcher: ideal 50.7 vs
50 in use). This spec turns that observation into a testable claim without
repeating the traps already catalogued in FINDINGS.md.*

---

## 0. The claim being tested

**H:** The harvest rule's fixed distances (100-pt reversal, 150-pt recovery
trigger, 250-pt TP, ~100-pt add geometry) are mis-sized whenever volatility is
far from the level they were tuned at. Scaling those distances to current ATR
should reduce whipsaw adds in loud regimes and stop over-trading micro-noise in
quiet ones.

**What would make H true in the data:** the adaptive arm beats a *mean-matched*
fixed arm, paired anchor by anchor, and a *shuffled-ATR* control does NOT.

**What we already know that bears on this (do not re-derive):**

| prior finding | consequence for this spec |
|---|---|
| Entry has no edge vs random (many nulls; OHLC search CLOSED) | we do NOT test new entries; only spacing/geometry of the EXISTING rule |
| Duration/spacing control beat every directional idea | spacing is the one knob with a track record — this is why the idea earns a test at all |
| Spread is fixed $10–18 → cost share rises as ATR falls | adaptive spacing SHRINKS distances in quiet markets = more triggers exactly where cost bites hardest → Phase 0 gate below |
| Anchor noise floor ~$240 on $1,000/0.01 for renko variants | must be re-measured for each variant here; no single-run conclusions |
| Trap 16 (control gate never read), Trap 14/15 | every gate instrumented; identical outputs across settings = dead code, abort |

---

## 1. Definitions (exact, so no re-implementation drifts)

- **ATR_t** = ATR(14) on **closed** M1 bars at the signal bar (`last_closed_before`
  semantics — the entry bar is NOT included; that bug already happened once in
  the journal and is fixed there).
- **Adaptive unit** `S_t = clamp(k · ATR_t, 25, 100)` price units. The clamp
  stops quiet weekends producing 8-point spacing (pure spread churn) and news
  spikes producing 400-point spacing (never adds at all).
- **Mean-matching:** for each knob, `k` is set ONCE, on the full M5 stretch,
  such that `mean(S_t over signal bars) = the fixed value it replaces`
  (150 for the trigger, 250 for TP, etc.). k is then FROZEN for every
  timeframe and anchor. **No sweep. No per-stretch re-fit.** This makes the
  comparison "same average distances, scaled vs not" — the cleanest version of
  the question.
- **Event stream is unchanged:** 50-pt renko, 2-brick reversal, same anchor
  (2026-07-17). We are NOT changing what generates signals in the primary
  test — only what the rule does with them. (The full breakout-candle engine
  is Phase 3, and only if Phase 2 survives.)

## 2. The four preregistered arms (primary experiment)

All in `hedge_engine.py` as parameters — extend the ONE engine (Trap: the 4th
re-implementation gave −$24 vs −$64 for the same July).

| arm | what scales | what stays fixed |
|---|---|---|
| A0 (control) | nothing | everything (this is the live rule) |
| A1 | recovery trigger: `3 bricks → S_t` (k mean-matched to 150) | TP, add geometry |
| A2 | TP: `250 → S_t` (k mean-matched to 250) | trigger, adds |
| A3 | add acceptance: same-direction reversal must ALSO be ≥ `S_t` from the nearest basket entry (k mean-matched to the observed median add distance, measured first) | trigger, TP |

A3 is the one the brainstorm actually proposed and my prior is highest on: it
directly limits clustering of adds, which is the recovery rule's failure mode
(four adds inside 200 points = quadruple exposure to the same move).

Combined arm A1+A2+A3 runs ONLY if at least one single arm survives §5.

## 3. The two controls that can kill a fake win

1. **Rate-matched fixed control.** If A3 takes fewer adds, run A0 with a fixed
   minimum add distance chosen to match A3's add COUNT (±5%) on each stretch.
   If that matches A3's P&L, the win was "fewer adds", not "adaptive adds" —
   and "fewer adds" is already a known, simpler result.
2. **Shuffled-ATR control.** Re-run the winning arm with the ATR series
   day-shuffled (day n's ATR path applied to day π(n)'s prices, fixed seed,
   3 shuffles). If shuffled ATR wins too, the benefit is spacing VARIANCE, not
   volatility TRACKING, and H is false even if the arm beat A0.

Plus the standing controls: ≥6 paired anchors per stretch, M1 + M5 + M15,
both invariants, trade-count cross-check between arms (identical counts across
different k = dead gate = Trap 16, abort and fix).

## 4. Phase 0 — the cost gate (run FIRST, no P&L involved)

Before any equity curve: for A3's candidate spacing distribution, compute the
share of accepted adds whose `S_t < 20 × spread_cost_in_price` (i.e. trigger
distance under $2.00-equivalent when spread costs $0.10/position). Compare to
A0's observed add-distance distribution.

- **Gate:** if the adaptive rule raises the sub-cost share at all after the
  25-pt clamp, the clamp is wrong or the idea is unaffordable → stop, record,
  done in one session. This is the "measure cost before hunting edge" rule;
  skipping it invented edge in quiet regimes once already.

## 5. Success / kill criteria (written before results, judged after)

An arm **survives** only if ALL of:
- beats A0 on **≥5/6 anchors on M15** (the only stretch long enough to matter)
  AND mean improvement > 2SE AND > the re-measured anchor noise floor;
- does not LOSE >2SE on M1 or M5 (a brake that costs money in normal regimes
  needs the monthly-trail justification, which it won't have);
- beats the rate-matched control (§3.1) on ≥4/6 anchors;
- the shuffled-ATR control does NOT reproduce ≥half its improvement.

**Kill immediately if:** Phase 0 gate fails; or any arm's improvement flips
sign between two adjacent anchor sets; or results require loosening the clamp
or re-fitting k to look good (that is the sweep this spec forbids).

**Expectation, stated honestly:** low. Best prior outcome is "A3 reduces
drawdown like the trails do, without their out-of-sample instability". Making
money was never on the table for the base rule; nothing here changes the entry.

## 6. Phases and effort caps

| phase | content | cap |
|---|---|---|
| 0 | cost gate on A3 distances | 1 session |
| 1 | engine params + invariants + k calibration (frozen) | same session |
| 2 | A1/A2/A3 vs A0, all anchors/stretches + both controls | 1 session |
| 3 | ONLY if an arm survives: full breakout-candle event engine (chain-filtered M5 closes as events; kept-bar high/low as levels) with its own Phase 0, because its triggers shrink in quiet markets by construction | 1 session, new preregistration |
| — | live/demo deployment | NOT in this spec; requires the two-questions rule and its own decision |

## 7. What this spec refuses to do

- No new entry signals (closed by 14 nulls).
- No parameter sweeps — one mean-matched k per knob, frozen.
- No "it looked good on the live anchor" conclusions (that path selected the
  $20/$20 caps, which failed 1/8 unseen).
- No trusting a result that arrives implausibly good — audit BEFORE reporting
  (the +263% retraction is section 7 of FINDINGS.md).
- No estimating: every number re-simulated, trade logs from the one engine.

---

## AMENDMENTS (2026-08-07, before Phase 0 ran — no results existed)

a. **§4 gate metric was internally inconsistent** (20×spread = 200 pts exceeds
   the 100-pt clamp ceiling, making every add "sub-cost" in every arm).
   Enforceable replacement: A3 must hold the subset property (it may only
   REJECT adds the fixed rule takes — the renko trigger is untouched), spread
   at the clamp floor must stay ≤ 40% of spacing, and rejection share ≤ 80%.
b. **ATR per run-timeframe, not M1** — M1 history reaches ~55 days, the M15
   stretch is 27 months. k is mean-matched per timeframe from the ATR series
   alone (never P&L), then frozen across anchors. Clamp = [T/2, 2T].

## PHASE 0 RESULT (2026-08-07) — PASS, all timeframes

`study/phase0_adaptive.py`. A0 add distances pooled over 6 anchors:

| tf | n adds | median | p10 | A3 rejects | rejected med | kept med | spread@floor |
|---|---|---|---|---|---|---|---|
| M1 | 2,056 | 140 | **16** | 58% | 69 | 346 | 14% |
| M5 | 10,586 | 253 | **32** | 55% | 109 | 589 | 8% |
| M15 | 15,869 | 430 | **47** | 54% | 170 | 1000 | 5% |

- Clustering confirmed: ~10% of A0's adds land within ~50 pts of an existing
  entry — near-duplicate exposure for an extra spread payment.
- A3 rejects the clustered half and keeps the distant half: the intended
  discrimination, visible before any P&L.
- **Caution carried into Phase 2:** 55% rejection is heavy — the rate-matched
  control is decisive. If fixed-min-distance at equal add count matches A3,
  this is "fewer adds" in disguise and already known.
- **Jensen penalty measured** for A1/A2: +17.8–21.3% expected cost at equal
  means. Either arm must clear its own penalty before any claim.
- **Frozen k** (from ATR only): M1 3.64 (clamp 70–280), M5 1.84 (126–505),
  M15 1.58 (215–860). Not to be re-fitted.
