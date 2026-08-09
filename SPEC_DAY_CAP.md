# SPEC: "2 and done" - hard cap of 2 cycles per day (2026-08-09)

*Preregistered before any run.*

## Origin, stated honestly - HIGH multiplicity risk

This candidate was the count-matched CONTROL in SPEC_WIN_STOP, noticed
looking good afterwards (M1 mean 1084 vs A0 1024 over 1.8 months). Promoting
a control after peeking is the classic forking-paths move, so the bar here
is the full bar, no shortcuts. N=2 is FIXED because that is what the win-stop
run happened to use - no grid, no tuning.

Priors against: the brake family is closed (thinning rescues M15, taxes M5 -
cap-2 already lost -75 vs A0 on M5 in the win-stop run), and sessions are
dead (rate-matched random hour-sets matched or beat every session filter),
which argues early-vs-late has no information.

## Hypothesis

At most 2 new cycles per UTC day; after that, no new cycles until the next
day. Open baskets always managed to their normal exit. If this works it
requires the day's FIRST TWO cycles to be better than later ones.

## Arms

- **A0** - live rule, 6 anchors, arm="same", M1/M5/M15.
- **C2** - day_stop=("cap", 2).
- **R** - rate-matched random skip: accept each new-cycle signal with
  probability p = (C2 cycles / A0 cycles) on that timeframe, seeds 0/1/2
  averaged per anchor. Same trading rate, skips spread over the whole day.

## Survival criteria (all required)

1. C2 beats A0: mean > 2SE and >=5/6 anchors on >=2 of 3 timeframes, never
   losing >2SE on the third (the M5 tax is the expected killer);
2. C2 beats R the same way - otherwise early-vs-late carries nothing and
   the brake-family verdict stands;
3. C2 keeps at least 20% of A0's cycles everywhere.

Kill: anything less. One shot.
