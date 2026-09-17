# The structure engine's rules, as actually coded (2026-09-16)

Source of truth: `engine()` in `owl_chart_feed.py`. One rule set, applied
to two candle series. The same function drives the main and the internal
structure; only the candles differ.

## The candles
- **Main**: the silence filter. A candle is kept only if its CLOSE lands
  beyond the last kept candle's high or low. Wicks do not count, the close
  has to commit. Roughly **41%** of raw M1 survives.
- **Internal**: **raw M1**, no filter, restarted at the last main event.
  This is divergence #1 in `INTERNAL_VS_MAIN.md`.

## The two running references
- `hi_v` — the high a close must beat for the next bullish break.
- `lo_v` — the low a close must break for the next bearish break.
Both are published as "prochain BOS" for their trend's side.

## The glowing dot (a confirmed swing)
Never placed on the candle you are watching. It is placed backwards, on
the extreme of the span, the moment a close confirms it.

- A close **above `hi_v`** confirms a **LOW dot**: the lowest low strictly
  between the candle that set `hi_v` and this one, valid only if at least
  one **red** candle sits in that span.
- A close **below `lo_v`** confirms a **HIGH dot**: the highest high in the
  span, valid only with at least one **green** candle there.

The newest dot on the trend's side is the **protected dot**. It is what the
dashed line and the diamond mark, and it is the only dot that decides
anything.

## BOS
The same close event as above. A `marks` entry is written only for the
break that **confirms a flip** - the first break in the new direction after
a CHoCH. A continuation break in an established trend writes no mark: it
just moves the protected dot along. So the BOS tags you see are flips, and
the "prochain BOS" level is what the next break has to take out.

## CHoCH
A **close** fully beyond the protected dot - below it in an uptrend, above
it in a downtrend. A wick through is not enough. It:
1. writes the CHoCH mark at the protected dot's price,
2. **clears the protected dot** (this is why the level legitimately
   disappears and the tag reads "sans CHoCH"),
3. arms a pending flip in the opposite direction,
4. resets the reference to the CHoCH candle's own low/high, so the
   confirming BOS must break something formed **after** the CHoCH.

A CHoCH alone does not flip the trend. **CHoCH then BOS** does.

## Starting from nothing
With no trend yet, **two consecutive higher lows** establish an uptrend and
**two consecutive lower highs** a downtrend. This is how the internal
structure usually gets its first direction - not from a BOS.

## Display
The main structure shows only the trend's own side (uptrend = lows,
downtrend = highs), per the owner's 2026-09-08 rule. The internal shows
both sides. That is divergence #2 and it is still open.

## Correction 2026-09-16 — the protected dot of a FRESH trend
Owner spotted it on a bearish internal break: "the protected level dot (the
high) created is at the wrong place. It is supposed to be where the
anticipated BOS was, because that's the highest high created."

Correct, and it happened at **every** flip, not just that one:

| flip | leg top (the anticipated BOS) | protected high chosen |
|---|---|---|
| 17:42 | 75906 | 75484 |
| 14:02 | 75865 | 75606 |
| 13:30 | 75802 | 75764 |
| 12:13 | 76243 | 76089 |

Cause: a CHoCH resets the opposite reference to the CHoCH candle, so the
span the engine searched for the swing ran only from the CHoCH to the
break. Its extreme is a small pullback, not the swing the move came from.
The leg's real extreme was sitting in `hi_v`/`lo_v` untouched all along,
because a bearish CHoCH resets the LOW reference and never the high, and
vice versa.

Fixed in `owl_chart_feed.py`: a flip BOS now protects `hi_v`/`lo_v` at
`hi_i`/`lo_i`. Continuations are unchanged — there the pullback extreme is
the right answer, since the protected level should ratchet with the trend.

**NOT changed: `structure_bos_bot.py` has the same behaviour** at lines
~225 and ~195, and there it also sets the signal's stop (`sig = (-1, m[2])`).
That is frozen production and every experiment E011-E027 was run against
the current rule, so changing it is a strategy change, not a display fix.
Flagged for the owner's decision.

## Correction 2026-09-16 (2) — what gets anticipated during a pending flip
Owner: "the moment a CHoCH is created, and a pullback happens, we should
already show the anticipated BOS; in this case a bearish BOS should have
shown already."

`nxt` was keyed to `trend`, so after a bearish CHoCH the chart still
anticipated the BULLISH break of the trend that was already broken. The
anticipated level now follows `choch` while a flip is armed and falls back
to `trend` when none is. The arrow on the tag follows the same direction,
so it points the new way instead of the dying one; the redundant
"· bascule" suffix is gone from the tag (the panel line still names both).

Verified by replay (`verify_pending.py`): at 22:14, trend +1 with a bearish
CHoCH armed, the anticipated break reads bearish at 75302.68. Before the
change it read the bullish level above.

The pullback gate keeps its meaning. During a straight drop `lo_v` ratchets
down every candle, so the level is only the current extreme and stays
hidden; the first candle that does not extend it counts as the pullback and
the level appears.

## Correction 2026-09-16 (3) — BOTH anticipated levels, not one
The two owner requests point at different keys and cannot both be served by
a single level:

| owner's state | wanted | that is |
|---|---|---|
| trend +1, CHoCH -1 armed | the level BELOW | the flip's confirming break |
| trend -1, CHoCH +1 armed | the level BELOW | the trend's continuation break |

Both levels are now published and drawn:
- **continuation** — keyed to `trend`, the break that extends it. Labelled
  `int BOS`. This is what continuation trades need.
- **confirmation** — keyed to `choch`, only while a flip is armed and only
  when it differs from the trend. Labelled `int flip`, drawn dimmer and
  finer so the hierarchy is obvious.

Each carries its own pullback gate, so a level stays hidden while it is
merely the current extreme. The main structure publishes the same pair
(`next_bos` / `flip_bos`).

## Taking the FIRST trade of a flip (2026-09-16)
Owner: "at the anticipated level I'd like to take a buy, the first buy of a
flip, but the panel is still VENTE, which is logical since bullish is not
yet confirmed."

The tool takes its direction from the trend, so during an armed flip it
offers the dying trend's side. Inverting used to MIRROR the lines around
price, which produced a setup with no structure behind it.

Inverting now REBUILDS from the structure for the other side:
- **entry** = the anticipated break on that side, as a programmed order, so
  the trade only exists once the break actually happens;
- **stop** = that side's structural level (internal first, then the main
  diamond, then a plain offset);
- **target** = the automation's own R:R.

The rules already in place do the rest. A first-trade-of-a-flip runs against
the main trend, so it is already half a lot and already waits for a candle
to CLOSE beyond the line. That is "wait for the BOS to confirm the flip",
expressed in rules written weeks earlier. Nothing new was needed to make the
trade correct - only to stop mirroring and start reading the structure.

The Inverser button turns purple and names the level whenever the other side
has a confirmed anticipated break, so the opportunity is visible without
opening anything.

## Correction 2026-09-16 (3) — a dot means a confirmed break, and only that
Owner: "a dot should only be seen after a confirmed BOS (at the low of it if
bullish, at the high of it if bearish)."

Audited every dot in the internal window (`dot_origin.py`, which tags each
append site in the real engine source rather than a copy):

| origin | before | after |
|---|---|---|
| continuation break | 78 | 78 |
| flip break | 26 | 27 |
| **trend-0 bootstrap, no break at all** | **3** | **0** |

So the rule was already honoured for 104 of 107 dots. The three strays came
from the bootstrap, which counts higher lows / lower highs to establish a
first direction and was marking each step. It now marks only the moment the
trend is actually set.

**The visual problem was the bigger one.** A CHoCH event mark was drawn as a
small circle, identical to a dot, so every event read as another dot. Three
shapes now, three meanings:

- **disc** = a dot, a confirmed break's protected extreme
- **diamond** = a CHoCH happened here
- **triangle** = a BOS happened here

And the count is genuinely high because raw M1 breaks often: 78 continuation
breaks in this window. The chart draws only the last 6 dots.

## Correction 2026-09-16 (4) — what a pullback actually is
Owner: "pullback is opposite candle close below previous candle in my
filtered custom chart. Until pullback is confirmed no anticipated BOS visual
is possible." The sequence is flip (CHoCH) → pullback → BOS → pullback → BOS.

My first implementation was wrong twice over. It asked for an opposite
**coloured** candle, and it asked it of **raw M1**. The owner's rule is a
**close that commits beyond the previous candle**, judged on the
**silence-filtered** series the chart actually draws:

- anticipating a break **up** → a kept candle closing **below** the previous
  kept candle's low;
- anticipating a break **down** → one closing **above** its high.

That is the silence filter's own language, which is why it belongs on the
filtered series: every kept candle is already a commit one way or the other,
so a pullback is simply a commit against the break being anticipated.

**Measured** (`pullback_diff.py`, 682 instants replayed across the internal
window):

| | |
|---|---|
| both rules draw the level | 510 |
| old rule drew it, owner's rule forbids it | **99 (15%)** |
| owner's rule draws it, old did not | 0 |
| both hide it | 73 |

So the old gate showed a level with no confirmed pullback about one minute
in seven, and never hid one it should have shown. `pullback_since()` is now
the single test, used by the main and internal structures and by both the
continuation and flip levels.

## Correction 2026-09-16 (5) — a dot must sit on a candle you can see
Owner: "the purple dots are placed at the wrong places. They are supposed to
be the glowing dot rules of the main structure — placed after a BOS is
confirmed, at the lower low between the previous high and the new high that
just broke it."

The rule was right; the SERIES was not. The internal engine reads raw M1, so
the swing it finds often sits on a minute the silence filter removed. The
price was a genuine raw low, but no drawn candle reaches it, so the dot
floated between candles. Measured before the fix: **5 of 8 internal dots
were on filtered-out minutes**.

`engine()` now takes an optional `snap` series. The internal engine is given
the drawn candles, and each dot is placed on the extreme of the SAME span
among candles that are actually drawn. Where a span falls entirely inside
filtered-out noise, **no dot is drawn at all**.

That last clause was wrong on the first attempt. The fallback snapped to the
nearest drawn candle at or before the break, which put the dot OUTSIDE its
own span at a price that is not the span's extreme. The owner caught it
immediately (`last_dot.py`): the dot shown at 76448.62 came from a raw span
of 04:59-05:00 whose true low was 76432.39, and 04:58 - the candle it landed
on - is not in that span. On this chart that swing does not exist, so the
honest answer is to draw nothing.

After: **every published dot sits on the exact low or high of a visible
candle**, and the count drops (13 to 6 at the time of the fix) because the
swings that only existed in filtered-out noise no longer produce one.
The engine's own bookkeeping (hi_i/lo_i/hi_v/lo_v) still runs on raw, so
break detection is unchanged - only where the dot is drawn moved.

## Correction 2026-09-17 — the opposite candle must be VISIBLE too
Owner: "a dot is always sitting between a previous high and a new high
separated by at least one opposite candle."

The engine already demanded that of the RAW span. It did not demand it of
the drawn candles, so after snapping, a dot could land inside a run that
shows no pullback at all on this chart. `_snap_dot()` now requires at least
one opposite-colour candle among the visible candidates, and draws nothing
otherwise.

Full audit (`dot_audit.py`), 135 confirmed breaks in the internal window:

| | |
|---|---|
| dots drawn | 65 |
| suppressed (no visible swing, or no visible pullback) | 70 |
| drawn dots satisfying the complete rule | **65 / 65** |

The complete rule being checked: the visible span between the two highs
contains at least one opposite candle, and the dot sits on that span's
extreme. Roughly half of all breaks now produce no dot, which is correct -
they happen inside noise the chart does not show.

## 2026-09-17 — the internal structure finally reads the chart itself
Owner, third time: "the dots need to read the chart, that custom chart where
candles considered are the ones which close completely beyond previous
candles... a dot is the valley between two confirmed highs, and the valley's
extreme holds the dot."

Divergence #1 is now CLOSED the other way. The internal engine reads the
**silence-filtered candles**, the same series the chart draws. Raw M1 and
the snap patch on top of it are both gone, and with them the whole class of
bug where a dot referred to a candle the owner could not see.

**The cost that blocked this before was the WINDOW, not the filter.** With
the window running from the main structure's protected dot, a quiet main
structure stretches it to 14 h and 891 chart candles; the engine then tracks
only the largest swings (`why_zero.py`: 14 breaks, 11 of them back-to-back,
**0 dots**). That is what made the earlier attempt look like the filter's
fault.

Capping the window fixes it (`window_sweep.py`):

| look-back, chart candles | structure present | dots now |
|---|---|---|
| 30 | 30% | 0 |
| 60 | 55% | 2 |
| 80 | 70% | 4 |
| 120 | 82% | 4 |
| **200** | **88%** | **13** |
| 400 | 90% | 0 |

`INT_MAX = 200` is a tuned constant, not a derived one, and 400 shows the
result is not monotonic - the reference ratchet makes a longer window able
to see LESS. Re-run the sweep before changing it.

Live after the change: 8 dots, 9 events, and **8 of 8 dots sit on the exact
low of a chart candle**.

## 2026-09-17 — the leg-extreme workaround is withdrawn
On 2026-09-16 the owner said a flip's protected dot belonged at the leg's
extreme, not at the pullback between the CHoCH and the break. Today he said
the opposite: the diamond should sit at the recent swing high, where his
stop was.

Both are right, and the reason is the series. On **raw M1** the post-CHoCH
span was 1-3 noise minutes and its extreme was meaningless - which is what
he was objecting to in September 16. Taking the leg extreme was a workaround
for that. Now the engine reads the **chart**, and that same span is a real
pullback: at the 08:15 bearish flip it covered 07:59-08:13, eight chart
candles, topping at 76459.32.

| rule | 04:07 flip | 08:15 flip |
|---|---|---|
| leg extreme (the workaround) | 76458.14 @ 03:33 | 76601.46 @ 07:06 |
| pullback extreme (restored) | 76334.21 @ 04:06 | **76459.32 @ 08:04** |

The workaround is withdrawn; the engine protects the pullback extreme again,
as it always did before the raw detour. Live check: the diamond moved from
76601.46 to **76459.32**, the exact high of the 08:04 chart candle, seven
points from where the owner had placed his stop by eye.

Lesson: a fix aimed at a symptom outlives the bug it was written for. When
the root cause moved (raw to filtered), the workaround became the defect.


## 2026-09-17 — the single look-back was unstable; the window is adaptive now
The owner: "I have lost my internal structure indicator on the chart."

Not a regression, a fragile constant. `INT_MAX = 200` was picked from a
sweep taken at one moment. Measured again two days later on the same live
window:

| look-back | result |
|---|---|
| 100 chart candles | no direction |
| **200 (the setting)** | **no direction** |
| 300 | trend +1, 8 dots |
| 500 | trend +1, 29 dots |
| 1221 (all of it) | no direction |

Not monotonic, and 200 had landed in a dead spot. The cause is the engine's
cold start: it needs two consecutive higher lows to establish a direction,
and whether it gets them depends on where the window happens to begin.

`INT_WINDOWS = (200, 300, 400, 550)` — try each and take the first that
yields a direction. Stated plainly in the code as a DISPLAY choice: it
decides what is drawn, never what a trade does. Live immediately after: the
300-candle window recovered the structure.

**And when there genuinely is none**, the chart now prints a small
"pas de structure interne" tag near price instead of drawing nothing, which
read exactly like a broken feature - the owner reported it as one.


## 2026-09-17 — the real cause of the vanishing internal structure
The owner: "the structures on the chart are gone again, or disappearing from
time to time." The adaptive look-back was NOT the cause; that was a separate,
real, but smaller problem.

Diagnosis from the published feed, not from reading code: it showed
`int_trend 0` together with `int_win 300`. Those two cannot both come out of
the same pass - a 300-candle window is only ever chosen when a direction was
found. So the block had not run at all and `_inner` was a stale value from an
earlier cycle.

`invalid_t` and `int_since` were both null. The window start is

    _t0 = inv_t or (marks[-1][0] if marks else None)

The feed held `RAW_BARS = 3000` M1 candles, about 50 hours. The main
structure's last event was 09-15 17:35, about 48 hours old. As the window
slid forward that mark fell out of range, `marks` emptied, `inv_t` was
already null because a CHoCH had consumed the protected dot — so `_t0` was
None and the **entire internal block was skipped**. Minutes later a new mark
appeared and it came back. Hence "from time to time".

Two fixes: `RAW_BARS = 8000` so the main structure always has events in
range, and `_t0` falls back to the oldest held candle rather than being
undefined. The look-back trims the window to size regardless, so the
fallback costs nothing.

Verified: 60 consecutive reads over 2 minutes, zero state changes, zero
cycles without a structure.

**Lesson:** the published artefact showed an impossible pair of values, and
that is what located the bug. Reading the code first would not have found it,
because the code is correct - it simply was not running.
