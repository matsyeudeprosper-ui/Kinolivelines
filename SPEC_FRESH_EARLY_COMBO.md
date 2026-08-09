# SPEC: Fresh-reversal window x early-day cap combo (user's idea, 2026-08-09)

*Preregistered before any run.*

## Hypothesis

Combine the two surviving mechanisms:
- entries only while the $150-brick series is in a fresh reversal window
  (flip pair printed, nothing further - SPEC_BIG_BRICK_GATE addendum 4), AND
- at most 2 new cycles per UTC day (SPEC_DAY_CAP's early-cycle quality
  gradient: the day's first cycles earn ~3x per cycle).

Both parts fixed as previously specified - no re-tuning of either. Recovery
adds unchanged.

## Arms (M1 / M5 / M15 / H1, 6 anchors, arm="same")

- **A0** - plain rule.
- **FREV** - fresh-reversal gate alone (attribution reference).
- **C2** - day cap 2 alone (attribution reference).
- **COMBO** - both gates.
- **R** - rate-matched random skip, p = COMBO cycles / A0 cycles per
  timeframe, seeds 0/1/2 averaged.

## Survival criteria (all required - the bar is the user's own goal:
survive AND actually earn)

1. Zero wipeouts for COMBO on all four timeframes (keep the shield);
2. COMBO beats R (mean > 2SE, >=5/6 anchors) on >=2 of 4 timeframes and
   never loses >2SE to R anywhere (the mechanism must survive);
3. **Absolute profit: COMBO mean final equity > start on >=2 of 4
   timeframes** - "loses less" does not qualify.

Kill: anything less. One shot.

## RESULT (2026-08-09): SURVIVED all three criteria — first survivor of the
search. Zero wipeouts 4/4 TFs; beats R on M15 (+466/2SE 373, 5/6) and H1
(+923/2SE 116, 6/6); absolute profit on M1 (+1.4%) and M5 (+2.5%).
Synergy is real: combo > both ingredients on M15, and on H1 cap-2 alone
DIES while the combo ends at −4% over 91 months.

## ADDENDUM — ETH confirmation, declared BEFORE running

H1 is not fully untouched (the combo was formed partly because FREV looked
good there). The one untouched sample on this account is ETHUSDm (only
other symbol whose spread passes the stop test). Same battery, same fixed
rule (brick $5 ≈ same brick/ATR proportion? NO — bricks scale by price:
ETH trades ~40x cheaper than BTC, so the $50/$150 bricks are replaced by
the SAME PROPORTION of price: brick = 50/65000 of ETH price at data start,
rounded to a clean number, big brick 3x that; spread from live quotes).
Survival on ETH: zero wipeouts everywhere AND beats R (mean>2SE, >=5/6) on
>=1 of 4 TFs AND no >2SE loss to R anywhere. Kill: anything less.
