# The Harvest Strategy — complete specification

A self-contained description of the strategy running as `live/renko_recovery_bot.py`
on MT5 demo account 436771046, written so someone with no access to this project can
review it. Written 2026-08-05.

**Summary in one line:** trade Renko reversals with no stop loss; when a trade goes
against you, add more positions on each new reversal up to a hard limit of 4, close the
whole basket when the group is back to break-even, and if a 5th would be needed, close
everything at a loss.

**Status: it loses in backtest.** Numbers and caveats in section 7. It runs on demo as
forward measurement only. No live money follows it.

---

## 0. Where the code is

Public repository: **https://github.com/matsyeudeprosper-ui/Kinolivelines**

| file | what it is |
|---|---|
| `live/renko_recovery_bot.py` | **the harvest bot itself** — the whole strategy, ~250 lines |
| `live/renko_bot.py` | the control bot: same entries, conventional stop loss, magic 770404 |
| `live/renko_journal.py` | records 86 columns per completed trade, including MAE/MFE and a 24 h post-mortem on stopped trades |
| `live/brick_watch.py` | warns when the fixed 50-point brick drifts >30% from its calibration price |
| `live/mt5_watchdog.py` | restarts the MT5 terminal if it dies |
| `charting/live_feed.py` | builds the Renko series as an MT5 custom symbol |
| `charting/KLRenkoLive.mq5` | chart overlay: live price, forming brick, and the bots' open trades |
| `study/renko_clean.py` | **the backtest behind section 7** — the run whose invariants pass |
| `study/renko_alignment_control.py` | changes one variable to prove the alignment bug was the cause |
| `study/renko_rerun_corrected.py` | the earlier corrected run, kept for the record |
| `FINDINGS.md` | section 7 is this strategy; the "traps" section lists every mistake made measuring it |

Reading order for a reviewer: `renko_recovery_bot.py` first (it is self-contained and the
docstring states the loses-money result up front), then `study/renko_clean.py` for how the
numbers were produced, then `FINDINGS.md` traps 14, 15 and 16 for the three bugs.

Local path on the machine it runs on: `C:\Projects\KinoliveLines\`

---

## 1. Instrument and account

| | |
|---|---|
| Symbol | `BTCUSDm` (Exness) |
| Account | 436771046, **demo** — the bot refuses to start on any other account or on a non-demo account |
| Position size | **0.01 lots, fixed.** Never scaled, never compounded |
| Value | 1 point of BTC price movement = **$0.01** at 0.01 lots |
| Spread | ~**10 points** flat (measured live; $10 on a ~$64,000 price) |
| Magic number | **770405** — the bot only ever sees or touches positions carrying this |

A second bot (`renko_bot.py`, magic **770404**) runs on the same account taking the same
entries with a conventional stop loss. It exists as a control, not as a strategy. The two
never touch each other's positions.

---

## 2. Renko bricks — how the chart is built

Renko ignores time. A brick appears only when price moves far enough.

**Parameters:** brick size **50 points**, reversal threshold **2 bricks**.

Built from **closed 1-minute bars**, using each bar's **close** price only — highs and
lows are ignored. The bot rebuilds the whole brick series from a fixed anchor date
(2026-07-17) on every poll, so brick boundaries never shift.

**The algorithm**, where `ao`/`ac` are the current brick's open and close and `d` is the
current direction (+1 up, −1 down):

```
for each closed M1 bar, take its close price C:
    repeat:
        up_gate   = (ao if d == -1 else ac) + 50 * (2 if d == -1 else 1)
        down_gate = (ao if d ==  1 else ac) - 50 * (2 if d ==  1 else 1)

        if C >= up_gate:            # new UP brick
            base = ao if d == -1 else ac
            ao, ac, d = base, base + 50, +1
        elif C <= down_gate:        # new DOWN brick
            base = ao if d == 1 else ac
            ao, ac, d = base, base - 50, -1
        else:
            stop
```

In words:

- **Continuing** the current direction needs **50 points** past the last brick's close.
- **Turning around** needs **100 points** (2 bricks) measured from the last brick's
  *open*, not its close.
- Several bricks can form from a single 1-minute bar if price moved far in that minute.

**A reversal brick** is any brick whose direction differs from the brick immediately
before it. That is the only signal this strategy uses.

---

## 3. Entry

When the most recent reversal brick is newer than the last one traded:

- Reversal **UP** brick → **BUY**
- Reversal **DOWN** brick → **SELL**

Order type: **market**, 0.01 lots, with a **take profit attached** and **no stop loss**.

**Take profit = 5 bricks = 250 points** from the fill price.

**Freshness guard.** A reversal older than **6 minutes** is skipped and marked as seen.
This stops a restart from firing on a stale signal. The bot polls every **20 seconds**.

**Known execution cost, unmodelled.** The reversal is only confirmed on a closed
1-minute bar, and price keeps moving in the meantime. Observed live fills have been
**46 to 125 points past the brick's close price**, on a trade aiming for 250. No backtest
in this project charges for that. Real results should be worse than any figure below.

---

## 4. Recovery — the distinguishing mechanism

There is **no broker stop loss**. Instead, 3 bricks against is a *trigger*, not an exit.

**Trigger:** any open position is **150 points (3 bricks)** underwater, measured on the
current bid/ask.

**On trigger, the cycle enters recovery mode.** The losing position is *not* closed.
From then on, **every new reversal brick opens another 0.01 lot** in whatever direction
that reversal points — which may be the same side or the opposite side of the existing
position. Positions are not hedged deliberately; the bot simply takes each new signal.

**Hard limit: 4 positions.** The check permits opening while the basket holds 4 or fewer,
so the basket can momentarily reach **5**, at which point the cap fires.

Each position in a basket keeps its own independent 250-point take profit, so individual
legs can and do close on their own while the basket is open.

---

## 5. Exit — a cycle ends in exactly one of three ways

A **cycle** runs from the first position opened while flat, until the bot is flat again.

**(a) Take profit.** The position, or every remaining position, hits its 250-point
target. Cycle over, profit banked.

**(b) Recovered.** In recovery, the **cycle's own profit and loss returns to zero or
better** → close every position in the basket at market, immediately.

**(c) Cap hit.** A 5th position would be needed → **close everything at a loss**. This is
the only way the strategy books a large loss, and it is the mechanism that stops it from
dying outright.

### How "back to zero" is computed — this matters

Cycle P&L = **money already banked on this cycle's tickets** + **floating P&L on the
tickets still open**.

Only positions this bot opened during *this* cycle count. Each is tracked by **position
ticket**, recorded in a state file, matched by ticket and never by time.

**This was a real bug, fixed 2026-08-05.** The original code tested
`account_info().equity` — the *whole account*, including the other bot's positions and
realised wins. On 2026-08-04 the harvest basket sat at −$1.13, the other bot banked
+$2.46, account equity touched the target, and the basket closed **at a loss under a rule
that says close at zero or better**. The dangerous direction is the reverse: when the
other bot is losing, the target becomes unreachable and the basket is held *longer* than
the rule allows, adding positions toward the cap.

Deal timestamps are in broker server time while the host runs UTC−5; matching by time
silently drops or double-counts deals. Ticket matching avoids this entirely.

---

## 6. Parameters, all of them

| Name | Value | Meaning |
|---|---|---|
| `BRICK` | 50.0 | brick size, points |
| `REVERSAL` | 2 | bricks needed to turn |
| `TP_BRICKS` | 5 | take profit = 250 points |
| `SL_BRICKS` | 3 | recovery trigger = 150 points against. **Not a broker stop** |
| `MAX_BASKET` | 4 | cap; a 5th opening forces the basket shut |
| `LOTS` | 0.01 | fixed, never scaled |
| `POLL` | 20 s | decision loop interval |
| `FRESH_MIN` | 6 min | ignore reversals older than this |
| `ANCHOR` | 2026-07-17 | fixed brick-series start so boundaries never move |
| `MAGIC` | 770405 | position ownership |

Source timeframe for bricks: **M1**, closed bars only.

---

## 7. What the backtest says

**Read the caveats before the numbers. Three separate bugs were found and fixed in this
study on 2026-08-05, and each one changed the answer.**

### Bugs found and corrected

1. **Barrier alignment.** Entries were priced at the *next* bar's open while take
   profit/stop were tested against the *signal* bar — a bar that closed before the trade
   existed. Correcting this alone changed the result from **+$3,558 to $415**.
2. **Stale recovery flag.** When a basket emptied entirely on take profits, the recovery
   flag was never reset, so the next cycle inherited the previous cycle's target. (The
   live bot never had this bug.)
3. **The data was not hourly.** Exness serves BTCUSDm H1 with **365 bars for all of
   2019** and 366 for 2020 — one bar per *day* under an H1 label. A 250-point target
   tested against a daily bar's high/low fires almost every time.

### Result on data that actually exists

**H1, 2022-01-01 onward, 4.6 years, ~100% coverage, price-scaled 50-point-equivalent
brick.** Invariants pass (9,221 opened + 1,389 skipped + 1 unfillable = 10,611 signals;
sum of all cycle P&L = change in equity, both −$426.12).

| | |
|---|---|
| $1,000 → | **$573.88 (−43%)** |
| lowest equity | $352.31 |
| worst drawdown | $706 (66.7% from peak) |
| expectancy | **−$0.11 per cycle** |
| months | 56 · **57% profitable** · median **+$7.07** · average **−$7.61** |
| signals unusable because a basket was open | **1,389 (13.1%)** |

**Why it loses, arithmetically.** 93% of cycles win about **+$2.04**; 7% hit the cap and
lose about **−$27.68**. `0.93 × 2.04 = 1.90` against `0.07 × 27.68 = 1.94`. The losses win
by four cents a cycle, 3,790 times.

**The shape is the trap.** Median month **positive**, average month **negative**. More
than half of all months make money and a few take it all back.

### Per-period distribution (same run)

| period | profitable | average win | average loss | average drawdown inside the period |
|---|---|---|---|---|
| day | 62% | +$8.73 | −$15.01 | $13.55 |
| week | 56% | +$27.57 | −$39.15 | $47.52 |
| month | 57% | +$48.19 | −$82.10 | $109.50 |

### Cap sensitivity — the survivor is a lucky cell

| cap | outcome |
|---|---|
| no cap | **zero**, June 2022 |
| 2 | **zero**, March 2025 |
| 3 | **zero**, December 2024 |
| **4 (running)** | survives at $573.88 |
| 5 | **zero**, November 2024 |
| 6 | **zero**, November 2024 |
| 8 | **zero**, October 2023 |
| 12 | **zero**, March 2023 |

Seven of eight settings reach zero. Cap 4 is the only survivor, and it is what runs live.

### On M30 with a FIXED 50-point brick and the real 10-point spread

Harsher and closer to the live bot: **every** take-profit setting from 1 to 5 bricks
reaches zero within 2–3 years. Under this engine the current TP=5 configuration also dies
(July 2024).

---

## 8. Variations already tested and dead

| tested | result |
|---|---|
| take profit 1, 2, 3, 4 bricks | all reach zero; TP=1 gives a **92% win rate** and still dies, because winners bank only +$0.56 while cap hits cost −$56.96 |
| brick size 10/15/20/25/30/40/50/75/100 × reversal 1/2/3 (27 combinations) | **26 reach zero.** The one survivor (brick 100, reversal 3) returned +3.6% over 4.6 years and sits at the **70th percentile of random entries** — 9 of 30 random-entry trials beat it |
| limit entry at the brick price instead of market, expiries 1h to forever | every expiry reaches zero, **faster** than market entry. Waiting for a pullback means you miss the trades that run and get filled on the ones that keep going against you |
| breakeven stop after 1 brick | worse at every level |
| close the basket at +2% account profit | never fires — the basket is in profit ~0.1% of the time |
| compounding position size | ~2× return for ~3× drawdown, and the cap counts *positions* not *dollars*, so the safety limit does not scale with size |
| plain version with a real 150-point stop | its result **changes sign** depending on how a bar that spans both barriers is scored (died at 3.2y / died at 6.9y / +$4,597), so by this project's own rules it is not a measurement at all. A driftless random walk with TP 5 / SL 3 wins 3/(5+3) = **37.5%** by geometry; the observed rate is indistinguishable from that |

---

## 9. Honest open questions for a reviewer

1. **Is the entry signal informative at all?** Every test is consistent with "no". The
   random-entry control on the best surviving configuration says no.
2. **Can any money-management rule rescue a zero-edge entry?** The arithmetic says no —
   recovery redistributes P&L, it does not create it — but this is the core claim worth
   challenging.
3. **Execution cost is unmodelled.** Live fills land 46–125 points past the brick.
   Including that would make every figure above worse. How much worse is unmeasured.
4. **The backtest is not the live bot.** Backtests run on H1 or M30 bars; the bot runs on
   M1 with a 20-second poll. Intrabar ordering (which of the high/low came first) is
   unknowable at these resolutions and has already flipped one result in this project.
5. **Cost versus movement.** The flat 10-point spread is 4% of a 250-point target. The
   untested question is whether some other instrument has a materially better
   cost-to-volatility ratio, which would change every conclusion above without changing
   the strategy.

---

## 10. Live behaviour observed so far

Running since 2026-08-04 17:14 on demo. As of 2026-08-05 ~14:00 local: **15 closed
positions, 10 winners (67%), +$12.12**, account equity $963.71 from a $941.84 start.

One full basket has occurred: four positions between 09:57 and 10:57 on 2026-08-05,
reaching the cap boundary, closed at **+$0.31** when price came back. The cap itself has
never fired live.

**This sample proves nothing.** At ~15 trades, a run like this is roughly as likely as
its opposite. The backtest expectation is that good stretches occur and are given back.
