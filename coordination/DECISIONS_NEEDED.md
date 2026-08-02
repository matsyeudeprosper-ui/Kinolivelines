FROM: CLAUDE
RE: TASK 002 — open decisions for the strategy lead

Five things task 002 surfaced that I cannot decide, because each one is a strategy or
research-design call, not an implementation detail. Each is stated with the measured facts
and the consequence of either choice. No option is recommended.

Blocking status: **none of these block task 003 from starting.** The dataset as committed is
usable today at 4.99 years. Decisions 1 and 2 change what the universe is, so they are
cheapest to make now rather than after a strategy is fitted.

---

## 1. History depth — 4.99 years, or ~8 years without canonical sessions?

**Fact.** Exness serves dense H1 only from 2021-08. Before that: 155 / 311 / 312 H1 bars for
2018 / 2019 / 2020, where a full year is ~6,200. Verified with explicit `copy_rates_range()`
calls, so it is the broker's limit, not a retryable download.

Broker **D1** does reach back to 2018-07 (~8 years, 2,522 bars).

| Option | Span | Session boundary | Cost |
|---|---|---|---|
| **A** — keep the committed H1-derived panel | 4.99 yrs, 261 weekly bars | true 17:00 NY | ~5 years is thin for a weekly cross-sectional test; 261 weekly observations |
| **B** — rebuild from broker D1 | ~8 yrs, ~420 weekly bars | broker's own daily cut, **not** 17:00 NY | loses canonical sessions; broker cut differs measurably (see decision 3) |
| **C** — both: D1 panel for the long test, H1 panel to check the boundary matters | ~8 yrs + 4.99 yrs | both | roughly one extra build; no new download, D1 is already cached |

**What I need:** which panel task 003 should be fitted on.

---

## 2. Which risk cap governs the universe?

**Fact.** Re-measuring on canonical sessions raised every symbol's 2-ATR risk. Two symbols
crossed the 1% line that task 001 had them inside:

| Symbol | Task 001 risk | Canonical risk |
|---|---|---|
| AUDJPYm | 0.95% | **1.07%** |
| NZDJPYm | 0.90% | **1.03%** |

Universe size by cap, on canonical numbers:

| Cap | Symbols |
|---|---|
| ≤ 1.00% | **10** |
| ≤ 1.50% | **19** |
| ≤ 2.00% | **23** |

**What I need:** the cap. It sets the cross-sectional breadth, and breadth is the thing that
decides whether a cross-sectional test can resolve anything at all. 10 names is a materially
different experiment from 23.

---

## 3. Which ATR governs sizing from here?

**Fact.** Canonical ATR(20) exceeds broker D1 ATR(20) for **23 of 23** symbols — ratio 1.049
to 1.195, median **1.113**. This is a session-boundary effect, not an error: the broker's daily
candle splits range that the 17:00-NY session keeps whole.

Consequence: **every risk number in task 001 is ~11% too small** if canonical sessions are the
intended trading unit.

**What I need:** confirmation that canonical ATR supersedes the task-001 D1 ATR for all future
sizing. If yes, task 001's group A/B boundaries should be treated as provisional, since they
were drawn on the smaller ATR.

---

## 4. NZDCHFm — excluded by 0.02 percentage points

**Fact.** Median spread 6.02% of D1 ATR against a 6.00% cap. Everything else passes: risk
0.63%, exposure 0.60x, 1,705 D1 bars.

I held the threshold rather than rounding in its favour. It is a one-constant change to include
it, taking the universe from 23 to 24.

**What I need:** hold the line, or admit it.

---

## 5. The 17:00 NY rollover hour

**Fact,** from spread alone — no return series was inspected in producing this:

| NY hour | Median spread | p90 |
|---|---|---|
| 00–16 | 20–21 pts | 38–43 |
| **17** | **53 pts** | **158** |
| **18** | **46 pts** | **108** |
| 19–23 | 21 pts | 38–41 |

The rollover hour costs ~2.6x the median hour, and its p90 is ~4x normal. The Sunday
mini-session is similar (median 24, p90 93).

A weekly strategy has to execute somewhere. This is what each hour costs.

**What I need:** the intended execution timestamp for weekly rebalancing. I will not pick it
from returns — choosing an hour by looking at what it earns is exactly the selection that makes
a backtest lie. Name it on cost or on principle and I will build to it.

---

## Not asked, deliberately

I am not proposing a strategy, an entry rule, a ranking formula, a lookback, or a holding
period. Those are the strategy lead's. This file only asks for the parameters that change what
the DATA is, so the dataset does not have to be rebuilt after a strategy is already fitted to it.
