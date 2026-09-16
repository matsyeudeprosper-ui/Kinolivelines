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
