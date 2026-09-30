# The wide stop on internal entries: my hypothesis was wrong

Run 2026-09-30, engine `2026-09-29b`, 99 000 M1 bars, two real balances.
`review/internal_widestop.py`, `review/internal_widestop.json`.

## What I claimed, and why it looked right

The internal trade that cost real money on 2026-09-25 carried a **594 pt**
stop. The median stop on main-structure trades over the same period was
**214 pt**. I said: an internal structure is the *small* structure inside
the big one, so a stop nearly three times the normal width is a
contradiction, and a guard refusing an internal entry wider than the main
structure's own stop should follow from the definition.

## What the measurement says

That guard filters **almost nothing**: 408 internal entries become 407 on
Valère, 407 become 404 on Dépenses. One trade, and three.

The reason is structural and I should have seen it. The internal
invalidation sits **between price and the main invalidation** — that is
where an inner structure lives. So the internal stop is nearly always
*tighter* than the main one, by construction. There was never a
contradiction to catch.

The 594 pt stop was not an internal-structure defect. It was a **wide
market moment**: the main structure's stop was wider still. Comparing that
trade against the *median* main stop, rather than against the main stop *at
that moment*, is what made it look like an internal-specific fault. That
comparison was mine and it was the wrong one.

## What does work, and how far

An absolute cap — refuse an internal entry whose stop exceeds N times the
median 60-minute candle range — does cut the damage a long way.

| account | mode | net | h1 | h2 | internal fires | vs main |
|---|---|---|---|---|---|---|
| Valère | main only | **+146.43** | +55.83 | +72.41 | 0 | — |
| Valère | internal, no guard | +83.52 | +55.59 | +16.03 | 408 | −43.0 % |
| Valère | tighter than main | +90.53 | +55.59 | +23.04 | 407 | −38.2 % |
| Valère | stop < 3× median | +103.52 | +58.05 | +31.99 | 172 | −29.3 % |
| Valère | stop < 2× median | +126.56 | +38.54 | +69.84 | 65 | −13.6 % |
| Dépenses | main only | **+101.18** | +13.90 | +67.62 | 0 | — |
| Dépenses | internal, no guard | +44.24 | +13.39 | +14.57 | 407 | −56.3 % |
| Dépenses | tighter than main | +47.41 | +13.39 | +17.75 | 404 | −53.1 % |
| Dépenses | stop < 3× median | +62.54 | +16.54 | +27.01 | 167 | −38.2 % |
| Dépenses | stop < 2× median | +98.14 | +13.52 | +64.96 | 65 | −3.0 % |

The tightest guard throws away 84 % of internal entries and recovers most of
the loss. But it recovers it **towards** main-only, never past it: −13.6 %
and −3.0 % are still negative, in both halves on both accounts.

So the guard is not finding a good subset of internal trades. It is finding
fewer internal trades. The limit of that process is taking none.

## Conclusion

The internal rule is dead, not merely its wide-stop half. No stop guard
rescues it. Keeping it switched off — done today on every account — is the
right call, and it should stay off even with a stop filter attached.

## What I got wrong, recorded on purpose

I proposed a guard from first principles ("an inner structure cannot be
looser than the one containing it") and it was near-vacuous because the
premise is automatically true. The lesson is not that the reasoning was
sloppy; it is that a guard derived from a definition should be **measured
for how often it binds** before it is proposed as a fix. A filter that fires
on 1 trade in 408 is not a fix, whatever its logic.

## Not opened

Whether a 2× median stop cap would help MAIN-structure trades. E008 closed
stop width as noise for continuations, and one suggestive column here is not
new data.
