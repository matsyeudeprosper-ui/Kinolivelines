# Moving the stop to the next glowing protected level

**Asked by the owner, 2026-10-01.** *"The SL on Valère currently for example
is just too much, it's more than the daily profit of many days. So I want
this, let's move the SL to the Next glowing protected level that Will come
(if it comes)."*

**Verdict: REJECT, both variants.** The complaint is right. This particular
cure is not the one — and it is not a close call.

Run it yourself: `python review/trail_stop.py` → `review/trail_stop.json`.

---

## The complaint is real

Valère's 17 closed trades, from his own journal:

| | |
|---|---|
| losses | 9, averaging **−$5.02** |
| wins | 8, averaging **+$3.45** |
| worst single loss | **−$11.95** — about three wins |
| stop width | median 214 pts, max 594 |

A loss worth three wins is exactly the thing that makes an account feel
unmanageable, and the owner is reading his account correctly.

## What was tested

The glowing dot is already the stop convention: `enter()` takes the
protected level as the stop, no buffer. So the trail simply puts the stop
where a fresh entry would put it, every time a new level forms.

* **trail 1** — every new level, including ones past the entry, so the stop
  can carry the trade into profit. This is the owner's words, literally.
* **trail 2** — only once the level is past the entry. Never protects early,
  never closes for less than the trade risked.

Both measured on `base` and `valere` plus the two live account shapes, over
the full window and both halves, and on the bot's real entries as well.
99,000 M1 bars.

## What happened

| | net | win rate | trades |
|---|---|---|---|
| stop never moves (`base`, full) | **+186** | 61% | 402 |
| trail 1 | **+18** | 52% | 464 |
| trail 2 | **+115** | 57% | 435 |
| stop never moves (`valere`, full) | **+150** | 62% | 275 |
| trail 1 | **+55** | 52% | 387 |
| trail 2 | **+144** | 59% | 281 |

**The second half is the one to look at.** With trail 1, both references
land on *exactly* the same number: net −61.54, 42 trades, drawdown 61.54.
That identity is not a bug — it is the −$60 kill switch firing. The trailing
stop drove the account past its own kill line and the run stopped there. An
account that took 225 trades and made +$102 took 42 and died instead.

On the bot's **real entries**, where the entry list is held fixed so the
trade count cannot drift, both variants are far worse: −$11.50 becomes
−$42.54 (trail 1) and −$38.89 (trail 2). Thirteen trades is a small sample,
but it points the same way as the synthetic one.

## Why it fails, in one line

**It converts winners into scratches.** The win rate falls from 61–62% to
52%. The protected level moves on *every* break, including continuations —
21 breaks against 5 trend-turning ones in a recent window — so the stop
ratchets up tight behind price and the ordinary pullback inside a good move
takes the trade out before the target.

A trap worth naming, because the harness reports it and reading it alone
would mislead: the moved stop genuinely *saved* +13,725 points across the
78 trades it closed. That number is real and it is irrelevant. It counts
what the old stop would have paid on those trades, and says nothing about
the targets that never got hit. A saving on the exits you take is not a
profit if it buys them by giving up the exits you wanted.

## The other half of the honest answer

The trail **does not touch the loss the owner is complaining about.** Look
at the worst-single-loss column in the run: `+0.0%` nearly everywhere. The
worst losses happen on trades where price goes straight against the entry
and no new level ever forms — so there is nothing to trail to. The trail
only ever shrinks the *average* loss (by 5–27%), and it charges a third of
the net for it.

What governs the dollar size of a loss is already built and already
measured: `risk_fit_pct`, which shrinks the lot so one trade cannot risk
more than a set share of the balance (see `RISK_CAP.md` — shrinking costs
about half what refusing the trade costs).

**Valère runs with no such cap.** His package sets only the 10% hard
ceiling; `risk_fit_pct` is unset, so on a ~$270 balance a single trade may
risk up to ~$27. Dépenses already runs `valere_cap3` at 3%, which on
Valère's balance would put the ceiling near **$8** — and would have cut the
−$11.95 down to roughly −$8, *including* on the straight-against trades the
trail cannot help.

That is a live-money change on a real account, so it is the owner's call,
not mine. It is the lever that matches the complaint.

## Discipline notes

* The verdict rule, the measures and both variants were written into
  `review/trail_stop.py` **before** any number was read. Nothing was tuned
  afterwards and no third variant was searched for.
* The harness priced every losing exit as exactly `−(dist + spread)`, which
  a moving stop makes false. The rewrite prices the exit at the stop as it
  stands. With the dial **off** the original expression is used verbatim:
  the two are equal in algebra but not always in the last bit of a float,
  and `run` is a running total — on the first attempt that bit moved one
  trade's money by a cent 146 trades later. Every past measurement on this
  harness is a comparison against that baseline, so it is now asserted
  bit-identical, not merely equal to the cent.
* The harness reports how many trades the level actually came for, and the
  study refuses to print a verdict if that count is zero. A dial that is
  never wired in produces identical numbers, which reads as "no effect"
  when it means "not running". That has happened here before.
* The trade count moves between variants (402 → 464) because trades close
  earlier and free the single position slot for the next entry. That is
  real behaviour, not a modelling artifact — the live bot also holds one
  trade at a time — but it is why the fixed-entry view matters.
* `bars_long()` pulls fresh bars each run, so nets shift by a few cents
  between invocations. Read one run's `trail_stop.json`, not two runs side
  by side.
