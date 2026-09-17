# The whole rule set, measured end to end (2026-09-17)

Owner: "the profits and number of trades of the backtests, still good now
with nervosity in view?" `stack.py`, 42 days, both window anchors.

Filters applied in the order they were measured: direction alignment, then
at least one internal movement in an hour, then nervosity at or below 1.0x.

## Anchor = protected dot (what the live feed uses)

| step | trades | per day | win | expectancy | total |
|---|---|---|---|---|---|
| all internal breaks | 304 | 7.3 | 53% | −0.047 | −14.2 R |
| + main-trend direction | 221 | 5.3 | 53% | −0.039 | −8.6 R |
| + movement in the last hour | 54 | 1.3 | 63% | +0.133 | +7.2 R |
| **+ nervosity ≤ 1.0× (final)** | **35** | **0.8** | **69%** | **+0.234** | **+8.2 R** |

## Anchor = break (the control)

| step | trades | per day | win | expectancy | total |
|---|---|---|---|---|---|
| all internal breaks | 336 | 8.1 | 52% | −0.068 | −22.8 R |
| + main-trend direction | 172 | 4.1 | 48% | −0.142 | −24.4 R |
| + movement in the last hour | 77 | 1.8 | 51% | −0.088 | −6.8 R |
| **+ nervosity ≤ 1.0× (final)** | **53** | **1.3** | **53%** | **−0.049** | **−2.6 R** |

## Reading it
- **Volume falls ~90%**: 7-8 trades a day become about 1.
- **Both anchors improve at every step after alignment.** −14.2 → +8.2 one
  way, −22.8 → −2.6 the other. The filters reliably cut the damage.
- **Profitability is not established.** The final set is +0.234 R one way and
  −0.049 R the other. Only the loss-reduction is common to both.
- **Alignment is the weak link**: it helps under the live anchor and hurts
  under the control (−22.8 → −24.4). Its earlier permutation result (3.5%)
  did not anticipate that.
- **The money is small either way.** At a 142-point median stop and 0.02 lot,
  +8.2 R is about **+$23 over 42 days**; the control case is about −$7.

## Verdict
The rule set is a good brake and not yet a motor. It turns a clearly losing
set into roughly break-even on about one trade a day. Nothing here justifies
raising size, and 35 trades is far too few to call an edge.
