# The debt / recovery system — review and design (2026-09-16)

Owner's goal: every losing trade is recorded; every win puts a slice aside
into a recovery bank; that bank funds a LARGER LOT (never a wider stop) on
later trades to claw the debt back over however many attempts it takes.

## 1. The current system is not doing that. It is dead.
`rebuild_ledger()` grows the war chest only on a **new equity high**
(`if banked > peak: chest += banked - peak`). During a drawdown
`banked < peak`, so the chest never grows — precisely when recovery is
wanted. Measured on the live account, 85 closed trades since 2026-09-08
(`debt_review.py`):

| | |
|---|---|
| trades taken while in debt | 82 of 85 |
| of those, with at least $1 of chest | **5 (6%)** |
| median chest while in debt | **$0.00** |
| wins in the era | 38, worth $158.19 |
| of that, reaching the chest | ~nothing |

The owner's instinct was right: 38 winning trades funded no recovery at all.

## 2. The debt definition itself is correct
`debt = peak − banked` is high-water-mark drawdown, which is exactly "money
lost and not yet won back". It self-corrects: a new equity high means the
losses really were recovered. Keep it.

## 3. The proposed design (specified, simulated, NOT deployed)
- **bank** grows by `SKIM` × every win, not only wins above the peak.
- **stake** per attempt ≤ `STAKE_FRAC` × bank, so a losing streak cannot
  disarm the system in one trade.
- **size to the debt**: `extra_lots ≤ debt / (RR × stop_distance) − base`.
  Never buy more recovery than is owed.
- a losing recovery charges the bank only for the extra lots' share.
- stop distance untouched; only the lot moves. The 10% single-trade cap and
  `LOT_MAX` still bind.

It works mechanically: armed on **82 of 85** trades instead of 0, and it
takes 35–49 recovery attempts instead of none.

## 4. And on this trade record it loses more — monotonically
Only the lot changes, so P&L scales linearly with lot; the simulation is
exact under the owner's own constraint (`debt_sim.py`, `debt_gate.py`).

| arm | net | debt left | attempts |
|---|---|---|---|
| base lot, no recovery | **−$37.83** | $45.73 | 0 |
| bank, skim 25% | −$60.65 | $68.55 | 35 |
| bank, skim 40% | −$79.87 | $86.89 | 44 |
| bank, skim 50% | −$89.29 | $96.31 | 49 |
| bank armed only if last 20 trades > 0 | −$65.22 | $73.12 | 27 |

The better the recovery works, the worse the result. A recovery bank is a
**size multiplier**, and the era's expectancy is negative: 38 wins against
47 losses, −$26.01 realised. Multiplying a negative expectancy makes it
more negative. Gating on recent expectancy cuts the damage roughly in half
but never beats simply not doing it.

(The −$37.83 baseline differs from the account's −$26.01 because the
simulation forces base lot on every trade. All arms share that baseline, so
the comparison between them is fair.)

## 5. Recommendation
1. **Fix the accounting now.** Make the bank fill from every win. The
   numbers on the chart become honest whether or not they drive sizing.
2. **Do not wire the bank to lot size yet.** Keep the base lot fixed.
3. **Arm sizing only on demonstrated positive expectancy** — e.g. trailing
   30 trades positive AND a positive full-era expectancy — and re-run this
   simulation before switching it on.

This is not an argument against the owner's design. The design is sound and
is specified above ready to build. It is an argument about WHEN to arm it:
a recovery multiplier is a lever on the edge, and the edge has to exist
first.
