# E027 — what the 3% risk cap costs. Measured, with an interval.

**Asked by the owner, 2026-10-01:** *"Now do the test to be sure if the
number is measured."* He was right to push. `RISK_CAP.md` deployed the cap
while admitting the cost was *"somewhere between zero and about 9%, and no
tighter statement is honest"*. That is a confession, not a measurement.

**It is now measured — and the answer is not one number.** The cap's sign
depends on whether the widest-stop trades pay in the period, and that is
the finding, not a caveat on it.

`python review/risk_cap_cost.py` → `review/risk_cap_cost.json`

---

## Why the old study was blind

It compared two **nets** — capped against uncapped, ~400 trades each. But
the cap only changes the handful of trades where it binds; the other ~370
are identical. So a small signal was laid on top of a large, noisy,
path-dependent total, and the difference was read off. The halves
disagreed, which is exactly what that looks like.

More price history would help a bit, and is not available: the terminal's
*Max bars in chart* is 100,000 and it caps `copy_rates_range` as well as
`copy_rates_from_pos` — checked, 30 days of M1 returns 43,186 bars and 90
days returns `Invalid params`. Raising it means restarting a terminal that
the live app and a harvest bot are using. Not worth it, because the data
was never the real problem.

## The idea that does work, with no new data

The cap is **deterministic** and it does not move the price path:

```
risk = dist × lot ;  cap = pct% × balance
  fits             → nothing happens
  does not fit     → lot shrinks to floor((cap/dist)/0.01)×0.01
  even 0.01 fails  → the trade is refused
```

P&L scales linearly with the lot on an unchanged path, so the cost on one
trade is **exactly** `pnl × (new_lot/old_lot − 1)`, and `−pnl` for a
refusal. The trades where nothing binds contribute exactly zero instead of
contributing noise. Which collapses the question to one sentence:

> **The cap's cost is the expectancy of the trades whose stops are too wide
> for it.** The only sample that matters is the binding trades.

## A. Real money — 92 trades, 6 accounts, net −$30.52

| 3% cap | |
|---|---|
| binds on | **10 of 92** (11%), 3 of them refusals |
| worth | **+$31.88**, 90% interval **[+12.78 … +48.58]** |
| per binding trade | **+$3.19** |
| worst single loss | **−$11.95 → −$5.97** |
| the trades it touches made | **−$5.50 each** |
| the ones it leaves alone | **+$0.30 each** |

On the trades the bot has actually taken, the cap would have **saved**
money, and the interval excludes zero. Not because capping is profitable —
because the wide-stop trades have lost money so far.

## B. The 69-day simulated window — same arithmetic

| | binds | direct cost | interval | wide stops |
|---|---|---|---|---|
| `base`, net +192.97 | 37 of 403 | **−$28.79** | [−88.78 … +35.26] | **+$1.40** each vs +$0.19 |
| `valere`, net +158.19 | 18 of 275 | −$1.60 | [−30.56 … +26.82] | +$0.18 each vs +$0.40 |

**Opposite sign, same mechanism.** In the backtest the wide-stop trades
*win* — which is E009's finding — so capping them costs. Both intervals
span zero on their own; it is the real sample that has the signal, and it
points the other way.

## C. The path effects the direct arithmetic cannot see

A smaller loss leaves less debt, which changes later recovery lots and can
move the kill line. Comparing the paired estimate against a full
re-simulation shows how big that is:

| | paired | re-simulated | path effect |
|---|---|---|---|
| `base` 3% | −28.79 | **−59.30** | −30.51 |
| `base` 5% | −1.75 | −11.58 | −9.83 |
| `valere` 3% | −1.60 | **−11.08** | −9.48 |
| `valere` 5% | −5.74 | −2.82 | +2.92 |

**In a profitable stretch the full cost is roughly double the direct
arithmetic**, and always in the same direction for the 3% cap: capping
banks less, so the account sits in debt longer and the recovery machinery
earns less. The direct estimate is a floor on the cost, not the cost.

## What this means, plainly

* **The worst-loss cut is real and confirmed on real money**: −$11.95 →
  −$5.97. It is mechanical and it is not period-dependent. That is what
  the cap was bought for.
* **The cost is a variance charge, not a fixed fee.** It charges you in
  stretches where the wide stops pay and refunds you in stretches where
  they don't. On Valère's own shape the simulated cost is about **7% of
  net** (−11.08 on +158.19), which is consistent with the old doc's −8.6%;
  on his real trades so far it would have been a **gain**.
* **The `base` reference is much worse (−31%)** than the old "up to 9%"
  claim. `base` is not the package any real account runs, but the number
  belongs on the record: a bigger lot relative to balance makes the cap
  bind harder and the path effect bite deeper.

### A tension worth naming, not resolving

E009 concluded the widest stops are the **best** trades. The simulated
window agrees (+$1.40 vs +$0.19 per trade). **The 92 real trades say the
opposite** (−$5.50 vs +$0.30). Ten binding trades in one stretch cannot
overturn E009, and this is not claimed to. But it is the second time real
trading has disagreed with that finding, and it is the reason the cap looks
free on live data and expensive in the lab. Revisit when the binding count
passes ~40.

## Correction to `RISK_CAP.md`

Section 4 of that document says the cost "is not precisely knowable from
this data … somewhere between zero and about 9%". That was true of the
method it used and is now superseded. The cost *is* measurable, the right
sample is the binding trades, and 9% was an underestimate for anything but
Valère's own shape once the path effects are included.

## Discipline notes

* The verdict rule and the three estimators were written into
  `review/risk_cap_cost.py` before any number was read. The bootstrap seed
  is fixed so the interval reproduces.
* **This study's own good news was audited before it was published**, and
  that found three defects in the instrument: a bootstrap over a single
  observation printing a zero-width "interval" and claiming an established
  sign; a verdict that read only the flattering real-money sample and
  hid the opposite-signed simulated one; and "as a share of net" printing
  `+104.5%` against a *negative* net, which reads like a gain. All three
  are fixed — `MIN_BIND = 8` before any sign is claimed, both samples in
  the verdict, percentages only where net is positive.
* `lot` and `risk` were added to the harness trade trace so the study reads
  the lot the simulation actually used instead of reconstructing it from
  balance and nervosity. A reconstruction that drifted would mismeasure the
  cap silently.
