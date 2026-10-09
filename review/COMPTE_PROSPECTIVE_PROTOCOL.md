# Compte directional sizing - prospective shadow protocol

**Status: DRAFT v0.3 (2026-10-09, after review 9). Not frozen.** The executable
configuration is `review/compte_frozen_manifest.json` (hashes, package values,
datasets, arms, controls, seeds, cost basis, horizon). Freezing = a dated FROZEN
line below plus the manifest's `status` set to FROZEN in the same commit.
Nothing here changes a live bot; prospective collection is read-only.

## Candidates (fixed; never reselected)
| arm | definition | role |
|---|---|---|
| baseline | the account's frozen package, no allocation | control path |
| **directional MAIN+ADDS** | at entry, if the trade's OWN side of the reference Compte (buy curve for a buy, sell curve for a sell; compte-ctl-2, resolved closes strictly before entry) is trend -1 with no CHoCH up pending: main lot x0.5 (floored to the 0.01 step, floor 0.01) and the permitted add count x0.5 (int(3 x 0.5) = 1; achieved cut reported); else x1; never above baseline; multiplier frozen per opportunity at entry; invalid state => x1 and tag `state_invalid` | **primary** |
| directional MAIN-only | same trigger, main lot only | exploratory attribution arm; no decision, no inherited evidence |
| exposure control | every k-th eligible opportunity of the BASELINE stream at x0.5, ALL k phases; k from K_SET = (2,3,4,6,8) by closest mean (main + rule-permitted add) risk to the primary on the development interval (value fixed in the manifest after v2c) | matched-exposure control |
| block-shift control | the primary's own schedule, keyed by baseline opportunity id, 20 cyclic shifts of 10 | schedule control |
| global | parked | not evaluated |

## State source
`lab/reference_ledger_infinity.jsonl` (rec-3): the independent fixed-size
reference on Infinity's live feed (read-only). An unresolved close latches the
state invalid until the complete chronology is replayed resolved. Signals
arriving while a reference position is open are recorded (`blocked:
position_open`) so each shadow path applies its own eligibility.
**The prospective reference starts COLD at the FROZEN line.** On the
development halves a cold-start reference made the policy worse than baseline
in the weak half (-43 vs -35 at drag 0; -85 vs -71 at drag 0.35). No seed,
warm-up or trigger change is allowed to rescue this; it is measured as is.

## Paths
Every arm is a COMPLETE package path on the same opportunity stream with its
OWN debt, jar, loss streak, eligibility, caps, balance and position lifecycle
(`study/manifest_runner.py`: the manifest's package values mapped EXPLICITLY
into harness settings by `effective_cfg()`, unknown keys an error, unsupported
behaviour rejected, fixed-or-disclosed fields listed in the manifest; balance
scaling at the live cadence - lot and day cap recomputed once per UTC day from
balance + realised run), run on the closed bars of the control feed from the
FROZEN line. Initial state: flat, debt 0, jar 0, streak 0, balance =
the account's balance at FROZEN (recorded in the manifest at freeze). Real fills
of the live accounts are observations for matched trades only (fill-realism
check), never the counterfactual. Capped regimes (valere, valere_cap3,
special_10) and the uncapped reference regime are evaluated apart; the shared
opportunity stream counts once.

## Feed provenance (limitation)
Development data = BTCUSDm on the std account's terminal; the prospective
reference and shadow paths = Infinity's feed (BTCUSD, Real27). Feed, contract
and fill parity between them is NOT measured; development results transport
to the prospective feed only as a hypothesis.

## Horizon
Fixed: **120 calendar days** from the FROZEN line, ONE evaluation at the end,
no interim checks. Adequacy target: 600 reference opportunities by then (not a
stopping rule); fewer => inconclusive. Sensitivity blocks (3 / 10 days) are
reported, never used to pick a result.

## Costs - gross and net separated
Results are gross after spread, before execution drag. Commission on the
reference is unknown: the shadow collects GROSS evidence from the FROZEN line;
no net label can PASS until a verified cost model is registered in the
manifest (a dated entry with its source). Observations collected before that
registration remain gross-only; the net evaluation period starts at the
registration date and runs its own 120 days. **Initialisation at that date
(frozen now):** the REFERENCE state is a declared causal replay of the gross
period under the registered cost model (the curve keeps its history, recomputed
with costs); the SHADOW ACCOUNT PATHS restart flat (declared cold restart:
debt 0, jar 0, streak 0, balance = each account's balance at that date). Earlier
gross observations stay outside the net evaluation. No result-driven seed. Drag sensitivity $0 / $0.35 per
0.02 lot is reported throughout. Curve basis B (reference rebuilt under the
registered cost model) is the evaluation basis; A is a sensitivity.

## Metrics (full path, every arm)
net; main stop risk, rule-permitted add budget, actual add risk (reported
apart); close-to-close realised drawdown (primary); daily-sampled realised
drawdown; MTM main-only proxy (whole-account MTM UNAVAILABLE - stated); tail
(sum of 5 worst, p95 loss); trade count; later calendar half.

## Decision labels - RISK only; every label is subject to all other gates
* **LABEL A (registered gate, unchanged):** candidate / baseline close-to-close
  maximum drawdown <= 0.80 with the block-bootstrap 90% interval (5-day
  blocks, exact horizon, seed 7, 3000 resamples; degenerate resamples
  reported) entirely <= 0.80.
* **LABEL B (secondary, reported apart, never a PASS alone):** interval
  entirely < 1.0 and point ratio <= 0.80.
* **Net non-degradation:** paired net degradation <= 0.05 baseline-risk units
  per eligible opportunity with its 90% interval respecting the bound -
  requires the net label, so UNAVAILABLE until a cost model is registered.
* **Controls:** the primary beats >= 75% of the exposure-control phases (k
  per regime and cost basis as recorded in the manifest from development data;
  where none is recorded for a regime, that limitation is reported and no k is
  chosen from prospective performance) and >= 75% of the 20 block shifts on
  the drawdown ratio; unkeyed opportunities counted independently.
LABEL A with the controls = "**gross risk criterion met; complete decision
unavailable**" while the net label is unavailable. The COMPLETE decision gate
= LABEL A + controls + net non-degradation under the registered cost model.
Neither state permits a live sizing change. Otherwise inconclusive
(interval straddles) or FAIL (point the wrong way). Bootstrap intervals are
conditional development-style diagnostics (resampled path returns; the
adaptive policy is not rerun); the 8 historical five-day blocks make the
power figures approximate planning diagnostics, not a promise.

## Prohibited
Parameter sweeps on multiplier, window, CHoCH definition, k or block length;
reselecting the arm after seeing prospective results; any live rollout; any
change to the manifest after FROZEN except the dated cost-model registration.

FROZEN: (not yet)
