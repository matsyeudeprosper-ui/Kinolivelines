# Taking aligned trades only from the discount half (2026-09-17)

Owner: "split the main range in half and only take the trades in the same
direction of the main structure from the discount area - if the main is
bearish take sells in the top part of the range, mirror for bullish."

Range = the main protected level (the diamond) to the level the next main
break must take out. Recorded at EVERY candle, because both move on every
trigger, not only when a dot is created - the first attempt anchored them at
dot events and the range came out far too narrow (`discount2.py`).

## Reading 1 — as a filter on where the break fires: it removes everything

| | n |
|---|---|
| aligned internal trades | 135 |
| of those, firing in the favourable half | **1** |

Not a bug. An aligned break IS price making a new extreme, so it confirms at
the far end of the range by construction. A bearish break happens near the
bottom, never the top. The two conditions cannot both hold at the same
instant.

## Reading 2 — as a pullback ENTRY: measurably worse
So the idea only means something as "wait for the retrace, then enter".
Tested on the same aligned breaks (`discount3.py`), stop at the internal
protected level, target 0.8R, a retrace that never arrives = no trade:

| arm | n | win | expectancy | total |
|---|---|---|---|---|
| A enter at the break (today) | 135 | 53% | −0.040 R | −5.4 R |
| C enter on a retrace of a quarter | 108 | 47% | −0.150 R | −16.2 R |
| B enter on a retrace to the midpoint | 81 | 42% | −0.244 R | −19.8 R |

Monotone: the deeper the retrace waited for, the worse the result and the
fewer the trades. The mechanism is adverse selection - waiting to be filled
means you only get the breaks that turn against you first, while the ones
that run away immediately never fill at all. The 54 trades lost between A
and B are the good ones.

## Verdict: no. Entering at the break is better than waiting for a discount.
Both readings of the idea fail, and the pullback version fails in the
direction that a cheaper entry price would suggest it should win. Price
improvement is not free: it is paid for by only being filled on the losers.
