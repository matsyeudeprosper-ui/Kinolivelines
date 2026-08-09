# SPEC: Stop-for-the-day after a win (user's idea, 2026-08-09)

*Preregistered before any run.*

## Hypothesis

After the first WINNING cycle of a UTC day, open no new cycles until the next
day. After a losing cycle, continue. Open baskets are always managed to their
normal exit - stopping mid-cycle would leave stopless trades unattended.

**Win is fixed as: cycle P&L > 0.** (This includes recovered-at-slightly-
positive closes, not only full TP wins. No other threshold will be tried -
one definition, one shot.)

## Prior, stated honestly

This is a trade-reduction rule, and the brake family is CLOSED: trails,
adaptive and wide spacing all "rescued" M15 by taxing M5, and none beat
random thinning. What earns this test: it carries a real mechanism claim -
that the market AFTER a day's first win is worse than average - which is
exactly what the count-matched control can isolate.

## Arms

- **A0** - live rule, 6 anchors, arm="same".
- **W** - stop the day after the first winning cycle close.
- **C** - count-matched control: hard cap of N cycles per day, where N is
  W's measured mean cycles/day on that timeframe (rounded, min 1). No
  cleverness, same average trading rate, no win signal.

## Survival criteria (all required)

1. W beats A0: mean > 2SE and >=5/6 anchors on >=2 of 3 timeframes
   (M1/M5/M15), never losing >2SE on the third;
2. W beats C the same way - otherwise the win signal adds nothing over
   simply trading less, and the brake-family verdict stands;
3. W actually reduces cycles vs A0 (dead-gate check), but not below 20% of
   A0's count anywhere (untestably thin closes the spec).

Kill: anything less. One shot, no re-tuning the win definition.
