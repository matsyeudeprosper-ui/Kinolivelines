# E029 — the trend flips against your open trade. Hold, close, or reverse?

**The owner, 2026-10-01:** *"What if the trend changes mid trade? For
example I'm in a buy trade taking long to hit tp and then before it hits tp
it's flipped trend and now makes the first BOS on the opposite direction?"*

**Answer: hold it.** But this one is closer than the storm question, and
the owner's instinct is partly right — closing *does* dodge real losers.
It just costs far more than it saves.

`python review/flip_mid_trade.py` → `review/flip_mid_trade.json`

---

## Yes, this really happens — and here's why it can

Worth seeing, because at first glance it looks impossible: shouldn't the
stop be hit before the trend can flip against you?

No. **The protected level ratchets up on every continuation break.** So by
the time price closes below the *latest* protected low — confirming a
bearish CHoCH — the stop your long was *born* with can still be sitting
untouched further down. The trade is alive, and the structure now points
the other way. It happened on **4–6% of trades** (12–27 events).

## What the bot does today — twice, by omission

One line: `if sig is None or pos: continue`. Any signal arriving while a
position is open is **dropped**. So the bot (a) keeps the now-wrong-way
trade to its target or stop, and (b) misses the new flip entry entirely.
Neither was a decision. Both are the same missing branch.

## The result

| | net | h1 | h2 | win rate | drawdown |
|---|---|---|---|---|---|
| **base** HOLD | **+199.00** | +59.79 | +117.78 | 61.5% | 50.23 |
| base CLOSE | +116.77 (**−41%**) | +31.48 | +71.11 | 58.7% | **41.87** |
| base REVERSE | +57.08 (**−71%**) | +5.16 | +36.10 | 57.5% | 51.62 |
| **valere** HOLD | **+162.99** | +55.55 | +98.06 | 63.0% | 34.48 |
| valere CLOSE | +119.59 (**−27%**) | +56.09 | +63.14 | 60.2% | 35.58 |
| valere REVERSE | +102.36 (**−37%**) | +39.05 | +60.52 | 58.9% | 40.65 |

**HOLD > CLOSE > REVERSE on both references.** The more you react to the
flip, the worse you do — the same dose-response the storm question gave,
and the same reason to trust the direction on a modest sample.

**REVERSE deserves its own note.** It had to beat CLOSE to be worth
anything, and it is markedly *worse*. So the flip signal taken right after
being wrong-footed is a below-average trade — those are entries the bot
currently skips, and skipping them is not costing anything.

## The honest part: closing does dodge real losers

Pairing the 22 trades `base` CLOSE cut short against what HOLD paid on
those same entries:

| | |
|---|---|
| gave up a winner | **13 trades** |
| dodged a loser | **9 trades** |
| cutting them paid | **−$44.58** |
| holding them paid | **+$28.20** |
| direct cost | **−$72.78** (−$3.31 per trade) |

The dodges are not imaginary — it sidestepped a **−$22.32** and a −$9.93.
That is exactly why the drawdown improved on `base` (50.23 → 41.87). But
the winners surrendered were bigger and more numerous: +16.53, +15.63,
+9.94, +9.27, +9.01, +8.66 and more.

**And note what cutting actually realises: 21 of the 22 cuts closed in the
red.** Of course they did — a flip against you means price has already
moved against you, so "close at the flip" is a rule that books a small loss
almost every time, then hopes it avoided a bigger one.

## Why holding wins — the asymmetry

> **The target is closer than the stop.** RR is 0.8, so TP sits at 0.8× the
> stop distance. A trade that is slightly underwater at the flip needs only
> a small bounce to reach its target, while a loss needs the full stop
> distance to run. Holding gets paid on the cheap recovery and only
> occasionally pays the expensive one.

Roughly 60% of the flipped-against trades recovered to target. At a 0.8 RR,
60% recovery is comfortably profitable — which is precisely what the
numbers show.

## Verdict

**LEAVE IT.** Neither arm clears the bar written before the run. Let the
trade finish at its SL or TP, and keep ignoring the opposing flip signal
while a position is open.

**The one thing worth revisiting**, and only with more data: on `base`,
CLOSE cut the drawdown by 8.4 while costing 41% of net. That is a terrible
exchange rate, but it is the *only* arm in two days of studies that
improved drawdown at all. If the owner ever prioritises a smaller worst
stretch over profit, this is where to look — not at stop placement
(`TRAIL_STOP.md`) and not at the weather (`STORM_MID_TRADE.md`). It did not
reproduce on `valere` (34.48 → 35.58), so today it is one reference's
coincidence, not a finding.

## Discipline notes

* Pre-registered: arms, references, halves, the REVERSE-must-beat-CLOSE
  requirement and the verdict rule were all written into
  `review/flip_mid_trade.py` before any number was read. No "only when the
  trade is losing" arm was added afterwards.
* The flip branch runs **after** `eng.step` for the bar, so the structure
  engine always sees the candle; and the `continue` for the CLOSE arm sits
  after that, where it can only skip entry logic.
* A flip exit is scored a win when it banks money — what the live bot does.
* Its accounting is a separate block from the storm branch on purpose:
  E028's numbers are published and refactoring that branch would put them
  at risk. A comment in the code says that if either changes, both must.
* With the dial off the harness is **bit-identical** to the committed
  version (asserted against `git show HEAD:live/lab/harness.py`).
