# E030 — current sizing vs a constant 1.5% of balance per trade

**Asked by the owner, 2026-10-15:** *"test what would be better: current risk
management, or a fixed risk per trade of 1.5% of the account balance, no
matter the distance between entry and SL."*

`python review/e030_const_risk.py` → `review/e030_const_risk.json` / `.out`
Harness: new option `risk_const` (off by default, nothing else changes).

## Verdict: no clear winner — do not switch globally

| estimator | result |
|---|---|
| A. real money, 484 trades, 8 accounts | mixed per account; total **−75 → −101** but driven by the $990 reference demo, where 1.5% is ~5× its current risk. Without it **−42 → −37** |
| A2. same average risk, only the shape changes | **−75 → −63**, max dip 187 → 185; 4 accounts better, 3 trade-off, 1 worse (Valère) |
| B. random-lot control | 1.5% sizing at the **58th percentile** of random lot assignments — inside luck |
| C. re-simulation, 69 days, each account's own dials | Mike/Infinity/Dad **+134 → +71**, dip 29 → 19 (trade-off); Valère **+97 → +71**, dip 18 → 19 (worse); Dépenses **+121 → +125**, dip 19 → 19 (better, but 4 of its rules are not modelled) |

## Mechanism

Constant risk makes **tight-stop trades bigger and wide-stop trades smaller**.

* Real trades: the wide stops lost (−$0.59 each over 80 trades), the tight
  ones lost less (−$0.16 each over 207) → shrinking wide stops helps a
  little.
* Simulation: the wide stops are the winners (E009) → shrinking them halves
  the profit, while the drawdown drops.

The same tension as E009/E027. The real-money gain is not distinguishable
from chance (B, 58th pct).

## Two practical facts

1. **On a $100–200 account 1.5% cannot be honoured on wide stops**: 0.01
   lot is the broker minimum and already risks 1.5% at a 300-point stop on
   $200. 15 of 110 simulated trades risked more than 1.5%.
2. **The worst single loss** falls (real: Mike −11.95 → −5.97, Dad −17.93 →
   −6.01) — but the 3% cap already delivers most of that.

## Caveats

* One 69-day window; simulator dollars are not account dollars.
* Not modelled in C: eq_half, recov_bullets_only, debt_gate (Dépenses),
  max_risk_pct 10% ceiling (all accounts).
* First C run was invalid: `package_cfg` carried only 5 dials, so four
  packages produced the identical result with no trend gate and no 3% cap.
  Caught by the identical-results rule, rebuilt from the parity RULE_MAP.
