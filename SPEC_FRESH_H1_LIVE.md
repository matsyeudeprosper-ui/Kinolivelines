# SPEC_FRESH_H1_LIVE — preregistered forward test, written BEFORE deployment

2026-09-08, deployed under the user's standing auto-fix authorisation
(2026-09-08: "when the time comes auto fix and deploy you have my
permission... you keep trying until we find a possible edge").

## What is deployed

`live/harvest_fresh_h1_bot.py` on the Pro account 223985697 (BTCUSD,
$7 spread), 0.01 lots, magic 909001. The FRESH+EARLY H1 combo:
harvest rule ($50 bricks from H1 closes, TP 5 bricks, recovery at 3,
same-direction adds, cap 4, cycle-zero exit) gated by (a) fresh $150
brick reversal window (bricks-since-flip ≤ 1, direction match) and
(b) first 2 cycle starts per UTC day.

Replaces the KINO peak/dip-return recipe, retired the same day after
failing its own preregistered test (33 trades, net −2.22, −$2 kill
line) and after corrected spread-aware replay showed the entry to be
noise (S=0 gross +$0.005/trade ≈ random; random controls beat it on
M5/M15).

## Evidence for this rule (before deployment)

- Original 2026-08-09 preregistered pass (BTCUSDm + ETH replication).
- Re-validated 2026-09-08 on the Pro symbol/feed, $7 spread, H1,
  151.8 months: combo +1429 vs rate-matched random, 2SE 162, better
  6/6 anchors; zero wipeouts 6/6 while ungated dies 5/6; absolute
  +$632 at 0.01 lots.
- Per-year (anchor mean): 2018 −19, 2019 −91, 2020 +61, 2021 +24,
  2022 +134, 2023 +152, 2024 −31, 2025 +375, 2026 YTD +28.
- Bot parity: gate mask 75526/75526 bars identical to the study
  code; flip sequence 13136/13136 identical to the engine.
- M1/M15 cells on this terminal are noise-floor (1.8/27 months of
  data, sign flips between runs) — not evidence either way.

## Preregistered criteria (do not move after the fact)

Window: 90 days from first cycle, or 40 cycle starts, whichever
comes FIRST.

- KILL (anytime): bot's own net (banked + floating) ≤ −$60 →
  basket closed, bot stops, verdict FAIL.
- FAIL at window end: net < $0.
- PASS at window end: net ≥ $0 and no kill. (The edge's expected
  pace is ≈ +$0.31/cycle long-run; a 90-day window cannot prove the
  edge, only fail to disprove it — a PASS extends the run, it does
  not "prove" anything.)
- Expected cadence ~4–14 cycle starts/month. If < 4 starts in the
  first 45 days, audit the gate wiring (a silent gate reads as
  "no signals").

## Notes

- The bot honors the app pause switch for NEW cycles; an open basket
  keeps being managed (abandoning a stopless basket is a different,
  worse strategy — engine doc).
- owl_manual_bot stays running as scribe/manager (journals, app
  feed, war-chest books); KINO_ENTRIES=False.
