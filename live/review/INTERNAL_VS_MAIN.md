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
