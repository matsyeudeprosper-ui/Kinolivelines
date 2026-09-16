# Internal structure vs main structure — where the rules differ (2026-09-16)

Owner asked whether the nested ("internal") structure follows the same
rules as the main one. It does not. Three divergences, all introduced by
me when the internal structure was added on 2026-09-16. Scripts here are
read-only (`int_filter.py`, `int_anchor.py`).

## 1. The silence filter is applied to the main structure only
`owl_chart_feed.py` runs the main engine on `kept` (the v2 close-commits
filter, 41% of raw candles survive) and the internal engine on **raw M1**.
The header badge says FILTRE SILENCE, which is true of only half the chart.

This is not a free fix. Applying the filter to the internal window across
the last 31 windows:

| | raw M1 | silence-filtered |
|---|---|---|
| internal dots found, 31 windows | 272 | 53 |
| windows with **no structure at all** | 2/31 (6%) | **17/31 (55%)** |

The current window (since 09-15 17:28, 1144 candles) finds 77 dots raw and
**0** filtered. Turning the filter on would delete the internal structure
most of the time. The mechanism is the engine's ratchet: `hi_v`/`lo_v` only
move on a break, and inside a range a filtered series produces no breaks.

## 2. The one-sided dot rule is applied to the main structure only
The owner's 2026-09-08 rule — an uptrend displays lows only, a downtrend
highs only — filters `dots` at the publish site but never `int_dots`. The
internal set therefore carries both sides (38 lows and 38 highs when
measured). This is what made "put the stop at the internal dot" ambiguous.

## 3. Internal BOS/CHoCH events are computed and thrown away
`i_marks` is never published. The chart shows internal *levels* but never
the internal breaks that created them, while the main structure publishes
its `marks`.

## Not a problem: the window anchor
Shifting the internal window start by 1..40 candles leaves trend, BOS and
CHoCH identical; only the dot count wobbles (77-82). The internal verdict
is not an artifact of where the window begins.

## Scale problem worth noting
The window runs from the last main event to now, uncapped. The main
structure has not printed an event since 09-15 17:28, so the "internal"
structure currently spans 1144 of 2000 candles — 57% of the chart. It is
not nested inside anything at that size.

## 4. The label showed the trend that was about to die (fixed 2026-09-16)
Owner: "it will never turn bearish?" It turns bearish constantly. Replaying
the internal engine over its window (`int_trace.py`) shows **55 events in
19 hours**, a flip roughly every 20 minutes, including bearish BOS at
10:24, 12:13 and 13:10 the same day.

What the label hid: the engine had fired a bearish CHoCH at 13:20, two
minutes after the bullish BOS at 13:18, and was waiting for the bearish BOS
to confirm the flip. The tag showed the stale bullish arrow plus
"sans CHoCH", which states a technical fact (the protected dot is consumed)
instead of the useful one (a reversal is already under way).

`int_choch` is now published and the tag reads `· bascule ▼` while a CHoCH
against the internal trend is pending. `int_since` was also reading off the
display-filtered marks, so it went null whenever the last main event
scrolled out of view; it now reports the real value.

The churn rate is itself evidence for divergence #1: 55 events in 19 hours
is what raw M1 buys. The silence filter exists precisely to slow this down.

## 5. Rules unified on owner's instruction (2026-09-16) — with the cost
Owner, after seeing the measurements above: "Make them same rules.
Especially the silence filter... however in the main structure make sure
the anticipated BOS level uses the internal rule meaning the pullback
confirmation first."

Done, all three:
1. the internal structure now reads the same silence-filtered candles,
2. the one-sided dot rule now applies to the internal too,
3. the MAIN anticipated break now waits for a confirmed pullback.

**Measured cost** (`int_after.py`, 49 windows / 118 hours): the internal
structure now exists **24% of the time (40 h of 118)** and is absent the
other **76%**. Before unification it was present essentially always. Total
internal dots over the sample: 70, against 272 on raw M1.

Immediate consequence on the desk: with no internal level, the trade tool's
stop falls back to the main diamond. Measured at the time of the change
that was 1551 points away, $31.02 at 0.02 lot — **refused by the 10% risk
rule**, and $15.51 at 0.01.

**Reverted the same day.** The owner: "bring back the internal... I want
internal structure." The silence filter is OFF for the internal structure
again; that single difference stands, deliberately and with the cost
measured on both sides. Divergence #1 is therefore CLOSED as a decision,
not as a defect.

Still shared after the revert: the one-sided dot rule (divergence #2,
fixed), the published internal events (divergence #3, fixed), and the
pullback condition on the anticipated break, which was promoted from the
internal structure to the main one.

The open question is no longer the filter but the WINDOW: when the main
structure is quiet the internal window reaches 19 h and 57% of the chart,
which is what makes raw M1 so busy there. Capping it is the next lever if
the internal structure ever feels too noisy.


## 6. Why the internal engine reads raw candles — the actual mechanism
Owner: "we don't change the filter because that is what makes the chart
smooth... I don't understand why candles must go unfiltered."

**The chart is still filtered.** Only the internal ENGINE reads raw M1.
The candles drawn are `kept`, the silence-filtered series, exactly as
before. Nothing about the chart's smoothness changed.

**Why the engine cannot use the filtered series** (`int_why.py`): the
filter and the swing rule do the same job twice. The filter keeps a candle
only if its close commits beyond the previous kept candle's extreme. The
engine confirms a swing from the candles sitting BETWEEN the reference and
the break. Filtering removes precisely those in-between candles, so the
span is empty and no dot can form.

Measured over the same period and the same window:

| series | candles | triggers | empty span | dots |
|---|---|---|---|---|
| raw M1 | 1425 | 13 | 69% | 4 |
| silence-filtered | 562 | 13 | **92%** | 1 |

Same number of trigger events either way. The filter does not hide breaks,
it destroys the evidence needed to place the swing that the break confirms.

## 7. Two real bugs this uncovered (fixed 2026-09-16)
- **22 of 30 internal dots were never drawn.** The engine emits them on raw
  minutes; the chart indexes x by drawn candle time, so a dot on a filtered
  minute silently returned early. A nearest-drawn-candle lookup (`xnear`)
  now snaps them. All 30 draw.
- **The internal window was anchored to `marks[-1]`, which records only
  flips.** The owner's definition is the space between a confirmed BOS and
  the glowing dot it created, and that dot moves on every break including
  continuations. The window now opens at `inv_t`, the current protected
  dot, so a continuation genuinely restarts the nested space instead of
  leaving it running for hours.
