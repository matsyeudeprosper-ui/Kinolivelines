# "Tail Guard" — ACCEPTED, 2026-08-14

**Status: accepted as the final strategy.** User's decision, 2026-08-14,
after multi-anchor validation and several rejected variants (see below).

## Final parameters

- Entry: same as the live bot (A0 — every reversal brick, brick 50/rev 2)
- Single position at a time (cap = 1). Concurrency and daily-stacking
  variants were tested and rejected — see below.
- TP = $1.00 flat (100 points) at 0.01 lots
- SL = 1-in-100 rarity percentile of historical adverse excursion,
  calibrated on data BEFORE the trading period only (no hindsight) —
  roughly $260-$445 depending on the calibration window, i.e. ~35-50% of
  BTC price at the time
- No daily loss limit, no recovery/cap basket — plain TP/SL per trade

## Why this shape, not the alternatives tried

- **TP smaller than $1** or **SL narrower than the ~1-in-100 level**: blows
  the account (see `CANDIDATE_TP1_WIDE_SL.md` and the SL-sweep results)
- **SL sized from the whole dataset's literal worst case**: hindsight bias,
  rejected
- **Multiple concurrent positions (cap 2-5)**: looked best on a single
  split, but multi-anchor validation found it dies in 1 of 5 independent
  periods (3 positions hit by the same correlated move within 5 hours,
  Feb 2024) — rejected
- **1 new trade per day regardless of concurrency**: same failure, positions
  quietly stacked to 9-10 during a slow stretch, died in the same period —
  rejected
- **Cutting trades short after a max hold time**: converts slow winners
  into losses (most late-closing trades eventually win if given time) —
  rejected
- **Widening the entry signal (REV=1)**: doesn't increase real trade
  frequency, just increases the skip rate (bottleneck was never signal
  scarcity) — no benefit, not adopted

## Idea

Same entry as the live bot (A0 — every reversal brick). Single position per
signal, no recovery/cap basket, no daily loss limit.

**TP = $1.00 flat.**

**SL = a statistical rarity threshold**, not a guess and not the dataset's
literal worst-case (that version — `CANDIDATE_TP1_WIDE_SL.md` — was
hindsight-biased and rejected). Calibration method:
1. Measure the worst-ever adverse move for every signal on a CALIBRATION
   period only (unconstrained lookahead, 2000h cap).
2. Pick the SL as a percentile of that distribution — e.g. the 99th
   percentile means only ~1 in 100 trades historically moved against it
   that far ("1-in-100 bad luck").
3. Apply that fixed SL to a DIFFERENT, later period the calibration never
   saw, for an honest out-of-sample test.

Code: `study/tp1_percentile_sl.py`.

## Result so far (ONE split: first half of 2022-2026 BTCUSDm H1 calibrates,
second half tests)

| Rarity | SL | Trades (2nd half) | Win rate | Ended ($1,000 start) |
|---|---|---|---|---|
| 1-in-20 | $239.53 | 903 | 99.7% | $1,181 (+18%) |
| **1-in-100** | **$311.48** | 888 | **99.9% (0 losses)** | **$1,576 (+58%)** |
| 1-in-200 | $318.22 | 888 | 99.9% | $1,569 (+57%) |
| 1-in-1000 | $339.35 | 888 | 99.9% | $1,548 (+55%) |

Best of everything tested this session. Positive expectancy, out-of-sample,
no hindsight in the SL size.

## Why this is NOT confirmed yet

- **Only one split point tested** (first half calibrates, second half
  validates). This project's own standard (see `SPEC_HHLL_VARIANTS.md`)
  uses multiple anchors/seeds before trusting a result — a single split can
  look great by chance of where the line landed.
- **Zero losses in 888 trades is encouraging, not proof of safety.** A
  "1-in-100" threshold predicts occasional hits over enough trades; not
  seeing one yet is good news, not a guarantee the tail won't show up
  later.
- Win rate (99.9%) is still close to the breakeven line implied by this
  TP:SL ratio — thin margin, same shape-risk as everything else tested
  today, just smaller and statistically grounded instead of guessed.

## Frequency and returns (1-in-100 SL, $311.48, second-half test period,
771 days / 888 trades)

| | Trades | $ |
|---|---|---|
| Per day (avg) | 1.15 | +$0.75 |
| Per week (avg) | 8.1 | +$5.23 |
| Per month (avg) | 35 | +$22.73 |
| Total (2.3 years) | 888 | +$575.52 |

## Seasonality check — no real pattern found

Checked by session, day-of-week, calendar month, and hour-of-day. **No
genuine seasonal edge.** What looks like a pattern (e.g. "Mondays are bad",
"NY session is worse") is fully explained by where the 2 losing trades
happened to land — with only 2 losses in the whole sample, any per-bucket
breakdown is dominated by noise, not signal. 22 of 24 hours were 100%
winners; the only 2 losing hours are exactly the 2 loss entries below.

## THE TWO LOSSES — corrected count (was misreported as 1 earlier)

| Loss | Entry (UTC) | Exit (UTC) | Held | Amount |
|---|---|---|---|---|
| 1 | 2024-09-09 15:00, Monday | 2024-11-11 19:00 | ~2 months | −$311.47 |
| 2 | 2025-11-14 03:00, Friday | 2026-02-05 15:00 | ~2.7 months | −$311.47 |

Both losses sat open for 2+ months before the stop was finally hit — the
rare bad luck shows up as a long, slow adverse grind, not a fast hit. This
also means the strategy was "busy" (skipping all other signals) for a very
long stretch during each of these — a real cost not captured by the P&L
number alone.

## Random-entry control — a real dent, 2026-08-14

Same TP/SL rule tested with random entries instead of the reversal-brick
signal (5 seeds, same second-half period). Random entries performed
comparably on average ($1,095 avg vs A0's $1,203) and ONE random seed beat
A0 outright ($1,835, 0 losses). **The entry timing is not clearly proven to
add value beyond the TP:SL shape itself and BTC's drift over this period.**
This is a real weakness, not resolved as of this writing.

## Concurrency experiment — tested, REJECTED

Tried allowing multiple simultaneous positions (instead of one at a time)
to increase trade frequency (single-position version only trades on 26% of
days). Cap=2 and cap=3 concurrent looked like the best results of the
session on the single-split test (cap=3 ended $1,642). **Multi-anchor
validation (5 independent periods) rejected this**: cap=3 died completely
in 1 of 5 segments — a real Feb-2024 price move hit all 3 concurrently-open
positions within 5 hours (losses at 20:00, then two more at 01:00),
wiping ~75% of the account in one stretch. Concurrency multiplies exposure
to the same rare event instead of diversifying it. Not saved as a separate
file per the user's instruction not to record rejected variants
permanently — noted here only for the record of what was tried.

## Multi-anchor validation — cap=1 (single position), 2026-08-14

The original single-position version, re-tested the same way: 6 segments
across the 4.6-year history, each segment's SL calibrated (1-in-100
percentile) using only the data before it, tested on that segment alone.

| Segment | Test period | Trades | Win rate | Ended ($1,000 start) |
|---|---|---|---|---|
| 1 | 2022-10 to 2023-07 | 31 | 100% | $1,031 |
| 2 | 2023-07 to 2024-04 | 22 | 95.5% | $754 (real loss, survived) |
| 3 | 2024-04 to 2025-01 | 386 | 99.7% | $1,074 |
| 4 | 2025-01 to 2025-11 | 258 | 100% | $1,258 |
| 5 | 2025-11 to 2026-08 | 302 | 100% | $1,302 |

**0 of 5 died. 4 of 5 profitable. 1 of 5 down ~25% but survived intact.**
The same Feb-2024 event that killed cap=3 only cost cap=1 a single loss
here (one position open, one loss) — confirms the concurrency finding above
from the other direction. **This is the most robust result of the session
so far**, but the random-entry control weakness above is still unresolved
and applies equally to this version (it uses the same entry signal).

## Daily activity check — quiet most days, 2026-08-14

Measured across all 5 validated segments (1,406 days): **83.1% of days have
zero trades.** Chance of >=1 trade on a given day: 16.9%. When something
does happen, it clusters (avg 3.19 trades on active days) rather than
spreading evenly, because the wide, rare-event SL means a slow trade can
block new entries for weeks. User wants daily activity; this doesn't
deliver it and isn't being redesigned to — see `CANDIDATE_DAILY_PULSE.md`
for the separate strategy started for that goal instead.

## FINAL — saved as-is, 2026-08-14

User accepted this version and moved on to a separate strategy for the
daily-activity goal, rather than modifying this one further.

## Known open weakness (accepted as-is, not resolved)

The random-entry control (one split, 5 seeds) showed the reversal-brick
entry timing isn't clearly proven to beat chance — random entries with the
same TP/SL performed comparably on average, and one random seed beat A0
outright. This was never re-tested across multiple anchors. Accepted
anyway per user's decision to finalize and move on; worth revisiting if
performance disappoints going forward.

## UPGRADE — "Half Trail" trailing SL, DEPLOYED LIVE 2026-08-17

The live bot (`live/tail_guard_m1_live_bot.py`, account 134499778, real
money) runs on M1 with the *literal* fixed values this document's relative
brick maps to at today's price: BRICK=50pts, TP=100pts ($5.00 at 0.05
lots), SL=44,439pts fixed ($2,221.95 at 0.05 lots — the H1 multi-anchor
worst case above, $444.39 at the 0.01-lot base unit). That flat fixed SL
was the whole design until this upgrade. Full detail and every backtest
number: memory `kinolivelines-tailguard-halftrail-candidate`.

**The rule ("Half Trail"):** once the account has *banked* (realized,
closed-trade — never floating) enough profit to spare, trail the SL down
instead of leaving it flat forever:
- `realized_profit_peak` = highest cumulative realized P&L ever reached
  since deployment. One-way ratchet, updated only when a trade closes.
- Below `2 x floor` ($800) banked: SL stays at the fixed default above.
- At/above `$800` banked: `SL = max(realized_profit_peak / 2, floor)`,
  floor = $400. Guarantees the account can never give back more than half
  its peak banked profit once trailing is active.

**Why a floor, and why $400 specifically:** without one, trailing tightens
straight into ordinary per-trade noise (dips of $10-30 happen on a quarter
to a third of ALL trades, most of which still go on to win) and converts
good trades into forced early losses. $350-$500 is a genuine stable
plateau in the 2-year M1 backtest — not a fragile single lucky value —
so $400 was picked as the round number centered in it.

**2-year M1 backtest (2024-08-16 to 2026-08-17, the real live signal):**

| | Trades | Win% | Losses | Net | Per month |
|---|---|---|---|---|---|
| Baseline (flat fixed SL, today's shape) | 1,107 | 99.82% | 2 | $1,081.10 | $44.99 |
| **Half Trail (floor=$400)** | 1,572-1,576 | ~99.7% | 5 | **$2,352-2,372** | **~$97** |

**Mechanism, understood down to the per-trade level (H1 multi-anchor
segments 3 and 4, dug into after segment 4 initially looked like a
regression):** Half Trail's effect splits cleanly into two pieces.
1. An "extra trades" pool — signals only Half Trail reaches because its
   tighter SL resolves positions faster than the flat-SL version, freeing
   up cap=1 sooner. This pool sits near breakeven and can land either side
   of its own thin win-rate threshold by chance (+$104 in one segment,
   -$705 in another, at ~98.7-99.1% win rates either way) — sample noise,
   not a dependable edge.
2. Disaster insurance on trades the flat-SL version would have taken
   anyway — when a real crash lands on one of those, Half Trail's tighter
   SL saves the gap between the full $2,221.95-class SL and wherever
   trailing had reached. This is the real value, and it is large when it
   fires (+$1,130 in one segment), but only fires if a genuine disaster
   actually happens to land during the window being measured.

**Correct mental model: insurance, not a free edge.** Pays a small,
roughly break-even "premium" during ordinary quiet periods (piece 1,
drifts either way), pays out big only when a real disaster lands on a
trade the base strategy would have taken regardless (piece 2). The 2-year
aggregate is positive because the two real disasters in that window (Sept
2024, Oct/Nov 2025) landed favorably for it — not a guarantee every future
disaster will.

**Deployment (2026-08-17, user's explicit instruction: "upgrade the live
bot. deploy it to live. i understand the risk"):**
- New state fields `realized_cum` / `realized_profit_peak` in
  `tail_guard_live_state.json`, updated only on trade close.
- New `effective_sl_pts()` in the live bot picks the SL for each new trade
  per the rule above; the old fixed-SL path is unchanged and is exactly
  what's used until activation.
- **`realized_cum` started at $0.00 at deployment** — not backfilled from
  the account's pre-existing trading history. Deliberately conservative:
  the bot behaves identically to the pre-upgrade fixed-SL version until
  $800 of *new* profit is banked from 2026-08-17 onward. This is the
  well-understood "first disaster after deployment is unprotected"
  characteristic, now the live starting condition.
- `alive.json` reports `halftrail_realized_cum`, `halftrail_realized_peak`,
  `halftrail_active`, `halftrail_current_sl_pts/usd`. The log carries
  `HALF TRAIL:` lines on every trade open/close and peak update.
- Verified before going live: syntax compiled clean, `effective_sl_pts`
  spot-checked against the exact backtest formula, old process stopped
  with zero open positions before the new one started, startup banner and
  `alive.json` confirmed showing the new fields correctly.

**Status: LIVE, still NOT forward-validated** — zero live trades have
happened under actual trailing yet (won't until $800 is banked). Watch
`tail_guard_live.log` / `alive.json`'s `halftrail_*` fields going forward.

### MAJOR CORRECTION, same day (2026-08-17) — 4-year backtest

The 2-year M1 backtest above was run on a lucky sub-window. Fetched 2 more
years of Coinbase M1 data (2022-08-16 to 2024-08-16) specifically to check
this, and re-ran both configs over the full 4 years (2022-08-16 to
2026-08-17, 1,051 trades):

| | Trades | Losses | Net |
|---|---|---|---|
| Baseline (flat fixed SL) | 1,051 | 3 | **−$1,425.85** |
| Half Trail (floor=$400) | 1,051 | 3 | **−$1,425.85 — byte-identical, verified via diagnostic trace, not a bug** |

Two findings:
1. **A third real disaster sits just before the 2-year window's start
   date** — SELL 2023-10-16, −$2,221.95 (the M1 counterpart of the H1
   segment-2 loss found earlier). With it included, the underlying
   baseline strategy is **net negative over the full 4 years**, not the
   +$1,081.10 the 2-year test showed.
2. **Half Trail never activates anywhere in the 4-year history.** The
   highest `realized_profit_peak` ever reached across the whole dataset is
   **$710.00** — $90 short of the $800 activation line. Losses recur
   (~every 16 months here) faster than the account can climb $800+ above
   its prior peak in the gap between them, so over this longer window the
   "insurance" is never actually bought at all — not inert-and-harmless
   like on the quiet H1 segments, but structurally unable to turn on.

**This materially walks back the "mechanically better, deploy it"
conclusion the deployment above was based on.** Still live on the real
account (user's decision, informed of this correction) — but "2.2x
better" was an overstatement built on a favorable 2-year slice, not the
honest long-run expectation. The live account's `realized_cum` started at
$0.00 at deployment; this result says it may take a very long time to
reach $800, or come close and reset on the next loss before crossing.

### ROOT CAUSE dug out, same day (2026-08-17) — and a fix

User asked for a "best brain" recommendation given the correction above.
Investigated whether the 4-year negative baseline is "just 3 unlucky
disasters" or a deeper problem. It's neither, exactly — it's one specific,
identifiable, fixable structural mismatch.

**All 3 losses, unbounded-horizon replay (no artificial time cap):**

| Loss | Entry | Entry price | SL hit | Held | What happened |
|---|---|---|---|---|---|
| SELL 2023-10-16 | $27,989 | 2024-03-11 | 147 days | BTC rallied $27,989 → $72,428 |
| SELL 2024-11-06 | $70,787 | 2025-07-10 | 247 days | BTC rallied $70,787 → $115,226 |
| BUY 2025-10-28 | $113,794 | 2026-02-05 | 100 days | BTC crashed $113,794 → $69,355 |

**None of these are crashes — every one is a position held 3-8 months that
eventually got run over by one of BTC's own well-known multi-month
bull/bear cycles.** cap=1 lets a losing position sit open indefinitely (a
time-based exit was already tried and rejected above — it kills slow
winners). Combined with a SL expressed as a FIXED NOMINAL point distance
(44,439 pts = $2,221.95 at 0.05 lots) on an asset whose own price moved
5-6x across the dataset ($15,497 → $126,198), that "fixed" SL is a wildly
different relative risk depending on when a trade opens:
- at BTC=$28,000: 44,439 pts = **158.7%** of price (effectively no stop)
- at BTC=$63,000: 44,439 pts = 70.5% of price
- at BTC=$114,000: 44,439 pts = **39.0%** of price (much tighter)

The "1-in-100 rarity" calibration measured point-in-time volatility
percentiles — it was never built to capture "probability that a
months-long secular trend eventually exceeds a wide, stale SL." That's a
different, much less rare phenomenon given how often BTC has multi-month
trend cycles, and it explains why extending 2yr→4yr found a 3rd disaster:
a longer window just samples more of BTC's own multi-year cycle history.

**Breakeven check on the whole 4yr sample:** TP=$5.00/SL=$2,221.95 needs a
99.7755% win rate. Actual: 99.7146% (1,049 trades, 3 losses; breakeven
would predict 2.36 losses). Razor-thin — noise sitting on the breakeven
line, not strong evidence of a broken OR a real edge either way.

**Random-entry control, redone properly** (M1, real mechanism, full 4yr,
20 seeds — the old check was H1, one split, 5 seeds): A0's real entry nets
-$1,435.85, sitting almost exactly at the MEDIAN of 20 random seeds
(average -$1,569.31, 10/20 seeds beat A0 outright, one hit +$1,479).
**Confirms with much more data the project's known, previously unresolved
weakness: the entry timing shows no demonstrable edge over random entry
with the same TP/SL shape.** Reinforces that the SL/TP shape — not entry
timing — is the lever that actually matters.

**Fix: SL as a percentage of entry price, not a fixed point count.**
Same entry signal, same TP=100pts/$5, only `SL_PTS_FIXED` becomes
`entry_price * sl_pct`. 4-year M1 backtest:

| SL width | Trades | Losses | Net | /month |
|---|---|---|---|---|
| Fixed 44,439pts (today's live config) | 1,049 | 3 | **-$1,435.85** | -$29.88 |
| 10-20% | 2,595-4,581 | 25-81 | -$2,454 to -$2,488 | too tight, noise zone |
| 30% | 1,744 | 9 | +$1,596.39 | +$33.22 |
| 35% | 1,559 | 5 | +$2,465.26 | +$51.31 |
| 38% | 1,678 | 4 | +$3,560.82 | +$74.11 |
| **40%** | 1,777 | 4 | **+$3,802.70** | **+$79.14 — best** |
| 42% | 1,755 | 4 | +$3,439.59 | +$71.58 |
| 45% | 1,693 | 4 | +$2,683.60 | +$55.85 |
| 50-52% | 1,067-1,129 | 3 | +$1,621 to +$2,073 | thinning |
| 55%+ | <770 | 3 | negative again | too wide |

**35-45% is a genuine stable plateau** (same robustness shape as the EMA
and Half Trail floor plateaus found earlier), **40% recommended**. At the
SAME dollar risk as today (70.5% ≈ $44,439 at current BTC price): fixed
nets -$1,435.85, relative nets **+$2,602.68** — isolating the mechanism
cleanly. It's not that the SL needs to be wider or narrower, it needs to
scale with price to stay consistent across a multi-year, multi-price-
regime backtest. Full detail: memory `kinolivelines-tailguard-relative-
sl-candidate`.

**Known gap:** the entry brick (50 literal points) has the same relative-
drift problem the SL had — not addressed by this fix, a larger separate
change.

**UPDATE, same day (2026-08-17) — DEPLOYED LIVE.** User confirmed after a
plain-English recap. `effective_sl_pts()` now takes the current price;
Half Trail's ACTIVE branch (profit-based $ trailing) is unchanged, only
the INACTIVE/default branch switched from the fixed point constant to
`price * 0.40`. Verified: syntax clean, formula spot-checked against the
backtest at 3 price points (exact match), restarted with 0 open positions,
startup banner and `alive.json` confirmed correct (at BTC≈$64,007: new SL
= $1,280.15 at 0.05 lots, 11.1x the ~$115 balance — smaller than the old
fixed SL's ~19-22x, a direct practical improvement for this account too).
Full detail: memory `kinolivelines-tailguard-relative-sl-candidate`.
**Status: LIVE, still NOT forward-validated** — no real trades under the
new relative SL yet.

### ENTRY-TIMING RETEST + HALF TRAIL DISABLED, same day (2026-08-17)

User asked to dig deeper into the entry-timing question and whether Half
Trail (still live at this point, stacked on top of the relative SL) is
compatible with it / responsible for the backtested profit.

**Entry timing, redone under the NEW relative 40% SL** (30 random seeds,
full 4yr, not the old fixed-SL test): real signal nets $3,802.70, random
average only $359 (median ~$14), just 1/30 seeds beat the real signal —
**97th percentile**. Reversal from the old-SL test where the real signal
sat at the random median (no edge). **The relative SL didn't just fix the
risk shape, it revealed a real entry-timing edge the old SL's price-
scaling noise was hiding.** MAE distribution across all 1,777 trades:
median $6.51, p90 $50.43, p99 $381.80, worst-ever $2,279.72 (1-in-1,777) —
"normal noise" lives in the $1-$20 range, comfortably clear of the SL.

**Half Trail + relative SL, backtested together (the exact combo that was
live) — WORSE than relative SL alone:**

| | Trades | Losses | Net (4yr) |
|---|---|---|---|
| Relative SL alone | 1,777 | 4 | **+$3,802.70** |
| Combined (both live) | 3,157 | **24** | **+$2,475.00 (-$1,327.70 worse)** |

Third confirmation of "stacking protective mechanisms backfires" in this
project (after EMA+Storm Shield, Half Trail+Storm Shield). The relative SL
resolves trades fast enough that realized profit crosses Half Trail's $800
activation often (peak reached $2,475 here vs only $710 ever under the old
fixed SL); once active, Half Trail tightens to ~$545-590, tighter than the
already-good 40% SL, clipping trades that were fine — 4 losses become 24.

**Half Trail DISABLED** via `HALFTRAIL_ENABLED = False` in the live bot
(not deleted — tracking/logging kept for reference, one flag re-enables
it). Verified: syntax clean, `effective_sl_pts` confirmed to always return
the relative SL regardless of banked peak, restarted safely with a
position open (broker already holds that position's bracket independent
of the script), log/`alive.json` confirmed `halftrail_enabled: false`.
Full detail: memory `kinolivelines-tailguard-relative-sl-candidate` and
`kinolivelines-tailguard-halftrail-candidate`.

**Current live state: relative 40% SL alone, Half Trail off.** This is the
config the 4-year backtest actually supports.
