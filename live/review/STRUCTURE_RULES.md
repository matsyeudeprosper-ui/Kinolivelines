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
