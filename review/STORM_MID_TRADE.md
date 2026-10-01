# E028 — a storm arrives while you're in the trade. Cut, or let it run?

**The owner, 2026-10-01:** *"When I'm in a trade, entered during calm météo,
then while still in the trade the très agité météo arrives when the bot is
not supposed to be trading — do we cut off the trade at the next positive
pnl whatever it is, or let the trade just complete normally to its SL or
TP?"*

**Answer: let it run. Don't cut.** Measured, and it is not close.

`python review/storm_mid_trade.py` → `review/storm_mid_trade.json`

---

## First, what the bot does today

**Nothing.** Nervosity gates *entries* only — `weather_gate()` is called
from `enter()` and nowhere else — so an open trade runs to its target or
its stop whatever the weather does. Every storm study on the shelf
(`post_storm`, `skip_post_storm`, `storm_gate`, `storm_during_recovery`,
`storm_hedge`) asks whether to **open**. None asked this. So "let it run"
was the untested default, not a considered choice. It is now tested.

"Très agité" = nervosity ≥ **1.85**, the top band on the weather card.

## Three arms, and why the third one matters

| | |
|---|---|
| **RUN** | today's behaviour — the trade goes to SL or TP |
| **GREEN** | the owner's suggestion — once the storm hits, leave at the first close that isn't negative |
| **OUT** | leave at the first close after the storm, whatever the P&L — **the control** |

OUT is what makes this answerable rather than flattering. If GREEN won and
OUT won too, the gain would be "getting out of storms", nothing to do with
waiting for green.

## The result

| | net | h1 | h2 | win rate | drawdown |
|---|---|---|---|---|---|
| **base** RUN | **+188.38** | +58.29 | +106.35 | 61.0% | 50.23 |
| base GREEN | +152.40 (**−19%**) | +49.10 | +79.56 | 61.6% | 55.77 |
| base OUT | +140.78 (**−25%**) | +56.41 | +56.07 | 59.7% | 55.14 |
| **valere** RUN | **+151.84** | +53.51 | +73.27 | 62.3% | 34.48 |
| valere GREEN | +97.99 (**−35%**) | +44.14 | +28.78 | 61.9% | 51.56 |
| valere OUT | +82.11 (**−46%**) | +41.02 | +19.93 | 59.2% | 50.94 |

Every one of the eight cells is worse than leaving it alone, and the
**drawdown gets worse too** — so it is not even buying comfort.

**The strongest thing in this table is the order: RUN > GREEN > OUT, on
both references.** More patience, more money, monotonically. A single
comparison can land either way on a small sample; a dose-response across
three arms on two references is much harder to get by accident.

## Why — and this is the part worth remembering

A storm arrives on **2–4% of trades** (7–16 events), so the big percentages
rest on few events and deserved an audit. Taking exactly the trades GREEN
cut and asking what RUN paid on those same entries:

| | cut paid | left alone would have paid | direct cost |
|---|---|---|---|
| base, 10 trades | **+$9.69** | **+$42.95** | −$33.26 |
| valere, 7 trades | +$5.54 | +$24.06 | −$18.52 |

On `base` that −$33.26 is 92% of the whole −$35.98 difference, so the
attribution is clean. Trade by trade:

```
dist  425  cut +1.87   would have been  +6.66   gave up a winner
dist  132  cut +0.04   would have been  +1.97   gave up a winner
dist  572  cut +1.52   would have been  +9.01   gave up a winner
dist  726  cut +0.57   would have been +11.48   gave up a winner
dist  478  cut +0.42   would have been  +7.51   gave up a winner
dist  142  cut +0.02   would have been  -2.97   dodged a loser
```

**Nine of ten were winners surrendered for pocket change.** The mechanism
is almost obvious once you see it:

> A storm *is* big candles. Big candles are exactly what carries a trade to
> its target. So "wait until it's green, then get out" systematically cuts
> the fast winners at a few cents — while the losers never turn green at
> all, so they get stopped out regardless. You keep every loser and sell
> every winner for nothing.

And the damage is worst on the widest stops, which have the furthest to
travel and need the big candles most: the 726-point trade banked **$0.57
instead of $11.48**.

## Verdict

**LEAVE IT.** The bar was written before the run — beat RUN on both
references *and* both halves *and* beat its own control — and neither arm
clears any part of it. The trade should complete normally to its SL or TP.

## Discipline notes

* Pre-registered: arms, references, halves, the control, and the verdict
  rule were written into `review/storm_mid_trade.py` before any number was
  read. The 1.85 floor is the deployed one and the only one tested — no
  "what if 1.6" afterwards.
* The storm check is deliberately evaluated **only when the stop and target
  both survived the bar**, so a storm exit can never pre-empt a real hit.
  Pessimistic ordering, as everywhere else in this harness.
* The exit is priced at the close the decision was taken on, with the
  spread charged — the bot polls after a bar closes and sends a market
  order within the second.
* There is **no `continue`** in the storm-exit branch. An early version
  would have skipped the rest of the bar, which would have starved the
  structure engine of that candle and corrupted every level afterwards.
* A storm exit is scored a win when it banks money, because that is what
  the live bot does — it reads the closed deal's profit, it does not ask
  whether a target was touched.
* With the dial off the harness is **bit-identical** to the committed
  version (asserted against `git show HEAD:live/lab/harness.py`), so this
  did not move the baseline every other study is compared against.
