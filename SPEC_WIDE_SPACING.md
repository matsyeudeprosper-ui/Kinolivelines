# SPEC: Fixed wide add-spacing (promoting Phase 2's control, properly)

*Preregistered 2026-08-07, before any run. The rate-matched CONTROL in
SPEC_ADAPTIVE_SPACING Phase 2 (fixed 2,000-pt minimum add distance) survived
5/6 M15 anchors at $661 while every adaptive arm died. That number was found
by bisection against A3's add count — data-derived — so it gets no free pass.
This spec re-tests the idea with selection and validation separated.*

## 0. Honest framing

- **Even the best Phase-2 result LOST money**: $661 final on $1,000 = −34%
  over 27 months. The realistic ceiling here is "stops dying", not "makes
  money". The long backtest's structure stands: ~93% of cycles win small, the
  few cap losses remove everything (FINDINGS.md).
- The live question this actually answers: can the LIVE bot's ruin probability
  be cut by one parameter without changing anything else it does?

## 1. Hypothesis

**H:** a fixed minimum distance D between a new add and the nearest basket
entry reduces wipeouts on long stretches, and does so BETTER than the simpler
explanation — "just cap the basket lower" — which needs no distance logic at
all. If a lower cap matches it, the finding is "fewer adds", already known,
and D deserves no deployment.

## 2. Arms (declared now, no additions later)

- A0 — live rule (cap 4, no distance gate)
- D-arms — D ∈ {250, 500, 1000, 2000, 4000} fixed pts (grid declared here;
  the Phase-2 bisection value 2,000 sits inside it deliberately)
- C0 — **no adds at all** (first trade only, exit at cycle-zero / TP as now)
- C2 — cap 2 instead of 4, no distance gate

## 3. Selection / validation split (the anti-sweep)

- **Selection:** M15 stretch, FIRST HALF only, 6 anchors. Pick the D with the
  best mean final equity subject to surviving ≥5/6. Tie → smaller D. ONE pick,
  no second chances: if the selected D later fails, the spec CLOSES — no
  "trying the next D", that is the sweep re-entering.
- **Validation (untouched):** M15 SECOND HALF + full M1 + full M5, 6 anchors
  each, selected D vs A0, C0, C2.

## 4. Survival criteria (all must hold on the untouched data)

1. beats A0 on ≥5/6 M15-second-half anchors, mean gain > 2SE;
2. beats BOTH cap controls (C0 and C2) on ≥4/6 there — otherwise the simple
   cap is the real finding;
3. does not lose >2SE vs A0 on full M1 or full M5;
4. wipeout count on M15-h2 strictly below A0's.

## 5. Expectation and deployment

Expectation: moderate that SOME D beats A0 on survival (Phase 2 already showed
it once); low that it beats C0/C2 — wide spacing and low caps may be the same
medicine in different bottles. Deployment is NOT part of this spec; a surviving
D goes to the demo A/B framework first, as a third arm or replacing the trail
arm, under its own decision.

## 6. Mechanics

One engine (`study/hedge_engine.py`), new `max_basket` parameter regression-
tested so default reproduces A0 to the cent. Invariants on. Add-count printed
per arm (Trap 16: identical counts across different D = dead gate = abort).
Distance gate reuses the Phase-2 `add_dist` code path with lo=hi=D.
