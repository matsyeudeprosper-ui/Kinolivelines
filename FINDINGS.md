# Findings

A record of what has been measured, what died, and how this project has previously
fooled itself. Written for whoever picks this up next.

The standing bar for any claim here: **non-overlapping windows, live spreads, several
instruments, a random-entry control, results reported under every tie convention, and a
permutation/rotation null.** A number that survives only some of those is not a finding.

---

## 1. Price history alone — CLOSED

> *"Price history alone does not provide a statistically robust edge after costs, across
> symbols and regimes."*

Fifteen conditions, six instruments (BTCUSDm, JP225m, XAUUSDm, US30m, DE30m, USTECm),
non-overlapping windows, real spreads. Every one null:

| tested | result |
|---|---|
| stop/target geometry (30 shapes, 28k trades each) | all tied at minus the spread |
| hold time 1h → 48h | flat |
| volatility regime, volatility squeeze | null |
| volume (M15 confounded by bar size; M1 clean) | null |
| horizontal levels as a trigger | **worse** than random over 520 days |
| break-following | worse than random → became a hard rule against it |
| momentum continuation / at levels | null |
| cross-asset divergence | 4 indices agreed, 5 of 6 failed split-half |
| session / calendar effects | null |
| Fear & Greed index | null |
| trend-vs-range regime split | signals gave *opposite* conclusions per symbol |
| distance from MA (20/50/200, continuous) | scattered signs, no monotonic pattern |
| all of the above at minutes / hours / days / weeks | null at every horizon |

**Do not propose another price-derived indicator for this instrument set.** That space is
measured.

### The one structural fact worth keeping
The random-entry baseline shrinks from **−0.058** at minute scale to **≈0** at day/week
scale. The spread is paid once regardless of how long a trade lives, so cost drag is a
function of **horizon**, not skill. This is why intraday BTC has been so hard, and it is
the most useful thing the price-only work produced.

---

## 2. Crypto funding as a direction signal — CLOSED

7.3 years of hourly BTC/ETH perpetual funding (Deribit, cached). "Join the crowded side"
initially looked real: +0.086 on BTC *and* +0.086 on ETH at a 3-day horizon, the only
sign-consistent result in the whole search at that point.

The **phase test** killed it — BTC 48/72 phases positive, **ETH 37/72** (chance). It was
one lucky slicing of the history.

---

## 3. COT positioning as a reversal signal — CLOSED

Discovery on 10 markets looked strong: persistence gap −0.0327, 8 of 9 markets, rotation
null at 4.6%, and it **survived** conditioning on prior-move size (−0.0351 → −0.0358), so
it was not merely "big moves revert".

**The holdout killed it anyway.** Twenty markets that took no part in discovery: gap
−0.0103, 11 of 20 markets (chance), rotation null 12.2%.

This is the single most important episode in the project. A result can pass a rotation
null, survive its most obvious confound, and still be an artefact of the particular
histories it was found in. **Holdout markets are not optional.**

---

## 4. Crowding as a RISK measure — real in the population, CLOSED for this bot

Adverse excursion rises ~5–6% at positioning extremes, on BTC and ETH via funding and on
20 unseen futures markets via COT. Direction remains completely unpredictable. Favourable
excursion does **not** replicate, so the widening is asymmetric — a crowded market travels
further against a position than for it. The effect lives at **~4 hours**; at 8h it points
the same way but fails the rotation null, and at 1 day it is gone.

| | BTC | ETH |
|---|---|---|
| adverse excursion, 4h, stratified by entry volatility | +0.061 ±0.026 | +0.051 ±0.024 |
| volatility quintiles with the same sign | 5 of 5 | 5 of 5 |
| two-sided rotation null | 1.0% | 0.0% |
| stop-out rate at 1.0× ATR | +2.90 pp | +2.00 pp |

### …and why it still closed

Tested on **the setups this bot genuinely takes** rather than on every hour, the effect
disappears and the point estimate reverses:

| convention | crowded stop-out | normal | difference (2SE 3.4pp) |
|---|---|---|---|
| fade | 65.2% (n=920) | 67.5% (n=4,972) | **−2.3 pp** |
| follow | 66.8% | 67.4% | −0.5 pp |

Mean R is also *better* when crowded (−0.0075 vs −0.0454, fade). All five policies —
baseline, skip-when-crowded, 75% size, 50% size, wider stop at constant risk — landed
within ±3.6pp of baseline total return, with signs flipping between direction conventions
and between development and holdout. Every apparent improvement is mechanical: baseline
expectancy is negative, so a policy that trades less always looks better.

### Correction — that closure was overstated

Two follow-ups revised this, and both matter more than the original result.

**The hlines are not to blame.** On 7.3 years of hourly BTC, stratified by entry
volatility, the gap is the same whether you trade every hour or only near a level:

| population | stratified gap | 2SE | chains agreeing |
|---|---|---|---|
| all bars | +1.9 pp | 3.3 | 3 of 4 |
| **near level** | **+1.8 pp** | 6.9 | 4 of 4 |
| breakout | +5.2 pp | 9.7 | 4 of 4 |
| random, matched count | +2.8 pp | 6.7 | 4 of 4 |

Level proximity does not remove the effect. The entry condition was never the problem.

**And the bot's setups could not have detected it.** Sequential one-position-at-a-time
leaves **307 crowded trades** and a 2SE near 6pp against an effect of 2–3pp. Stratified,
the three direction conventions give −3.3pp (fade), +1.4pp (follow), +4.7pp
(prior-move) — an 8pp swing from an arbitrary choice, every one consistent with zero and
with the others. The earlier "absent and wrong-signed" verdict was a sample-size artefact
reported as a finding.

The original interaction test was also computed **without volatility stratification**,
repeating trap #5 from this very file. Stratifying barely moved these particular numbers
(−3.8 → −3.3), so the confound was not the driver here — but the statistic was still
wrong to report.

**Honest status: not closed — untestable on this bot's history.** The binding constraint
is data: MT5 BTCUSDm M15 reaches back only ~1.4 years while H1 and H4 reach 7.6, capping
the bot at ~2,000 non-overlapping 4-hour trades. Re-running the same test will not settle
it.

### Two facts worth more than the negative result

**OKX funding does not transfer to Deribit.** Over 277 matched settlements the levels
correlate only **r = 0.30**, and at the top/bottom 5% tail OKX flags 31 hours, Deribit
flags 27, and they **agree on 1** — below chance. Deribit BTC-PERPETUAL is inverse and
USD-margined; OKX BTC-USDT-SWAP is linear. A live rule keyed to `funding_okx` would have
fired on essentially unrelated hours. *Always verify that a researched signal exists in
the feed the live system actually reads.*

**The field matters too.** The research used `interest_8h`; the live recorder captures
`interest_1h`. They correlate 0.85 and the effect survives on `interest_1h` but weaker —
+0.0391 ±0.0254 (4 of 5 quintiles) against +0.0614 ±0.0258 (5 of 5).

---

## 5. Perp-index basis — NULL

Basis = (perpetual close − spot index)/index. Worth testing because `corr(basis,
funding) = 0.046` — genuinely orthogonal to funding, so it was new information rather
than a relabelling of a variable already killed.

63,587 hourly rows, 7.3 years, BTC and ETH, horizons 4h/24h/72h, against a
**volatility-matched** random control, with the final 18 months untouched. Nothing beat
the control anywhere. The best cell was BTC 72h fade at +0.3035 with 5 of 5 volatility
quintiles agreeing — but 2SE was 0.6769 and ETH gave the opposite sign at the same
horizon. Holdout showed nothing on either instrument.

See [`RESEARCH_MAP.md`](RESEARCH_MAP.md) for the remaining hypotheses, each with its
mechanism, minimum detectable effect, validation universe and pass/fail rule.

## 6. Broker feed lag — CLOSED

Exness quote BTCUSDm themselves rather than matching orders, so a lagging feed would be a
pure execution edge needing no directional forecast — and, being broker-specific, owing no
cross-market replication. Tested on paired Exness/OKX samples (~2.2s apart, millisecond
stamps) using price **changes** with the BTC-USD/BTC-USDT basis removed by rolling median,
each day analysed separately, entry only from the next sample.

| criterion | result |
|---|---|
| technically present | **No** — peak lag **0 on both days** (r = +0.53, +0.63 at lag 0; +0.08 and 0.00 at lag +1) |
| economically real | **No** — after OKX moves >$10, Exness then moves **−$0.59 / +$0.53** over six samples against a $14 requirement (spread + slippage both ways). 2SE $3–4, so anything above ~$4 is excluded |
| stable across days | consistently absent on both |
| executable | moot |

**The test was biased toward finding a lag and still found none.** The recorder reads MT5
first and fetches OKX afterwards, so the OKX stamp sits ~0.6s *later* (measured +0.58s,
+0.61s). OKX therefore carries the fresher information, and a genuinely lagging Exness
would have peaked at lag +1. It peaked at 0.

Honest caveat: moves >$25 had only 4–6 samples, so a lag appearing exclusively during
violent moves is not excluded. Nothing in the tradeable >$10 range.

---

## 7. Renko capped recovery — RUNNING ON DEMO, not validated

The first design in this project that both survives a long backtest and ends it in
profit. It is running forward on demo 436771046 to find out whether that is real. It has
**not** met the bar at the top of this file and must not be described as an edge.

**The rule.** A Renko reversal brick (50 points, 2-brick reversal) opens one 0.01 lot with
a 5-brick take profit. If price goes 3 bricks against it the position is *not* closed —
each subsequent reversal adds another 0.01 lot, to a maximum of 4. When the cycle's own
P&L returns to zero the whole basket closes. If the basket would exceed the cap, it closes
at a loss instead.

**Step 6 — the cap — is the entire design.** Uncapped, the identical rule ran 5.2 years
and then died. Recovery succeeded **743 times out of 744**; the single failure took the
account. Capped at 4: 3,626 recoveries, 266 forced small losses, survived. Those 266
losses are what buys the survival.

7.6 years of H1: $1,000 → $3,631, 74% of months positive, median month +$33, worst month
−$173, worst drawdown **$384 (11.7%)**, equity never below the starting deposit. Caps 2
through 12 all survived (+131% to +263%) — a broad plateau, not a tuned cell, which is the
opposite of what the TP/SL grid showed.

**What was killed reaching it, and must not be re-proposed:**

| tested | result |
|---|---|
| plain 5:3 with a broker stop, one at a time | bled to zero in 3.3 years; best of 25 cells matched by shuffled data |
| no stop, unlimited positions | +287% in 55 days, dead in 5 years; underwater 98% of the time |
| close the basket at +2% profit | never fires — the basket is in profit 0.1% of the time, peak +0.25% |
| monthly $1,000 deposit chasing "house money" | 62 months, **zero** ever exceeded the deposit |
| breakeven stop after 1 brick | worse at every level (−7 to −11 vs +1.71); wins fell 322 → 290 |

**Capital buys survival, not returns.** At fixed 0.01 lots the dollar profit is identical
at any balance — $250 and $10,000 accounts both made exactly $2,630 over 7.6 years, and
the worst drawdown is $384 either way. Sizing capital ≈ 2–3× worst drawdown ≈ $1,000.
Anything above that is idle. Compounding was tested and **parked**: it doubles the return
for ~3× the drawdown, and critically the safety cap counts *positions, not dollars*, so it
does not scale with size. Rewrite the cap as a percentage of equity before ever enabling it.

**The brick is fixed at 50 points and that is a live liability.** It was calibrated at BTC
$64,000 (0.078% of price). A fixed brick silently changes meaning as price moves, and a
mismatched brick roughly **tripled** the worst drawdown in backtest ($987 vs $384) purely
because 50 points meant something different at BTC $3,500. `live/brick_watch.py` warns
beyond 30% drift and changes nothing — the decision is deliberately human.

---

## Traps this project has actually fallen into

Each of these produced a wrong answer that was believed for a while.

**1. Overlapping windows.** Standard errors came out **5.3× too small** across an entire
session's work. A gold result read +0.0172 with overlapping windows and was negative on
every non-overlapping step. *Always step by the full holding period.*

**2. Tie conventions.** With a 1.0× ATR stop and a 1.5× target, one bar can span both
barriers. Report every result under tie→loss, tie→win and tie→split; if the **sign**
changes between them, there is no finding. This caught a fake break-reversal effect.

**3. Significance without sign consistency.** A "VOL SPIKE" result was significant under
one tie convention and significantly *worse* under another. Verdict logic must require
the same sign, not just a small p-value.

**4. Testing against nothing.** Every timing signal must be compared against **random
entry** on the same instrument. Drift reads as edge otherwise.

**5. The ATR denominator — inverts signs.** Excursions divided by ATR-at-entry are
confounded: funding extremes follow violent moves, ATR is already inflated, and
volatility mean-reverts, so the ratio shrinks for reasons unrelated to positioning. Raw
ETH says crowded markets are *safer* (34.9% vs 35.6% stop-outs); stratified by entry
volatility it says **riskier (+2.00pp)**. Simpson's paradox. *Never compare
ATR-normalised excursions without stratifying on entry volatility.*

**6. Mirror measures that are algebraically identical.** "Symmetric adverse" defined as
((entry−low)+(high−entry))/2 and "symmetric favourable" as ((high−entry)+(entry−low))/2
are the same number — half the range. Every row printed identical values and the
"asymmetry" verdict was arithmetic. Adverse and favourable only differ once a direction
is fixed.

**7. One-sided nulls on a two-sided question.** A rotation test coded as
`rotated >= real` reported "not distinguishable from noise" for an effect sitting at the
0.7% tail, because the effect was negative.

**8. Ratio tests that pass when the denominator is ~0.** "Survives if |stratified| >
0.5 × |raw|" passes automatically when the raw difference is near zero. Judge a
stratified estimate against **its own** error bar.

**9. Underpowered tests read as negative results.** CME bitcoin COT gives 278 usable
weeks → ~28 extremes → the smallest detectable difference is 26% of baseline while the
effect is 6%. Underpowered ~4×. Every interval spans zero, and that means *nothing*.
Compute detectable effect size **before** running a test.

---

**13. Instrumentation rows counted as trades.** A commission-measurement exercise had
opened and closed positions immediately to read the fee actually charged. Those are real
MT5 positions and sat in `trades_journal.csv` looking like trades. They were **13 of the
33** rows in the current config, all with 0.0 minutes duration, and they dragged the
apparent win rate from 10% to 6% — making the sample look four standard errors worse
than it was, when the true figure is about 2.7. They are now tagged with an
`instrumentation` column rather than deleted, because the fees they measured are why
they exist. *Every performance query must filter on that column.* Any dataset that
mixes measurement artefacts with decisions will mislead whoever reads it next, including
another model.

**11. An unmatched random control.** A control must resemble the signal in everything
except the signal. Basis extremes arrive after violent moves, so signal entries sit at
high ATR while a freely-drawn control sits at average ATR — and ATR is the denominator,
so the control's returns come out larger in magnitude and the signal appears to beat it
on *both* the fade and follow arms at once. Draw each control from the same volatility
band as the trade it stands in for. The guard that caught this — *"fade and follow are
mirror trades; if both look good the control is broken, not the market"* — should be
printed by every study that has a mirror arm.

**12. One instrument's costs applied to another.** BTC's $10 spread was applied to ETH,
which trades near $1,900 with a $1.00 spread, inflating its cost tenfold and making every
ETH figure in that run meaningless.

**14. A strategy measuring the whole account when it shares that account.** The Renko
recovery bot's rule 5 is "close when the money is back to where the cycle started". It
read `mt5.account_info().equity` — which includes the *other* bot's positions and its
realised wins. On 2026-08-04 the recovery basket sat at −$1.13, the plain bot banked
+$2.46 at 19:05, account equity touched the target, and the basket closed **at a loss
under a rule that says close at zero or better**. The reverse is worse: when the other bot
is losing, the target becomes unreachable and the basket is held *longer* than the rule
allows, adding positions toward the cap — defeating the one mechanism that keeps the
design alive. The backtest could never show this because the simulation contained one
strategy. Fixed 2026-08-05 by tracking each cycle's own position tickets and computing
realised + floating on those tickets alone. *A shared account is shared state. Any rule
phrased in terms of "equity" must name whose.*

Two smaller ones from the same build, both caught only by looking:

- **Entering the backtest at the brick price** rather than the next bar's open. The gap
  averaged 78.5 points and manufactured a 94.7% win rate. Corrected: −20.5 pts/trade.
- **Charging the spread twice**, once in the barrier and once in the P&L, which made the
  same results ~10 points per trade too pessimistic.

**10. Declaring a result absent without checking whether the test could see it.** The
crowding effect was pronounced "absent and wrong-signed" on the bot's setups from a
sample of 307 crowded trades with a 2SE of 6pp — against an effect of 2–3pp. That test
could not have detected the effect had it been certain. *Compute the detectable effect
size before interpreting a null,* and state it beside every negative result. This is the
same error as trap #9, made a second time in the same project.

---

## Methods worth reusing

**The setup reconstructor.** `study/sim_setups.py` rebuilds every setup the daemon would
have been woken for, from OHLC alone: level set = previous closed H4/H1/M15 high and low,
merged within `max(3 × spread, 0.12 × ATR_H1)` with the higher timeframe winning; trigger
= flat, price within `0.06 × ATR_H1`, one-shot arming that re-arms at 2.5× that distance,
1800s per-level cooldown, and M15 levels matching the last two M15 bars skipped as
self-referential (which removes *all* M15 levels — matching live behaviour). ~340 setups
per month. `sim_variants.py` then runs any policy through the real management rules
**sequentially, one position at a time**, so declining a setup genuinely frees the bot for
the next one rather than just deleting a row from a table.

Any future risk or entry idea should be tested through these two scripts before it is
believed. Note the data ceiling: MT5 BTCUSDm M15 reaches back only ~1.4 years, against
7.6 for H1 and H4.

**Phase shifting.** With a hold of *N* bars there are *N* distinct places to start a
chain of non-overlapping windows. Each is a complete clean sample. Running all of them
uses every observation without ever comparing two overlapping windows. It does not shrink
the error bar — it tests **stability**. Bar to clear: **65+ of 72 phases** the same sign.

**Rotation nulls.** Slide one series against the other by a random offset and recompute.
Rotation preserves the autocorrelation of both series exactly and destroys only their
alignment, so it answers "is this what two slow-moving correlated series produce by
accident?" It also absorbs the multiple-testing problem, since the rotated distribution
reflects the same searching. Roll the **finished rank array**, not the raw data — same
logic, orders of magnitude cheaper.

**Stratification before conclusion.** Any measure normalised by a quantity that itself
correlates with the condition being tested must be compared within strata of that
quantity.

---

## Data provenance

| dataset | source | span | notes |
|---|---|---|---|
| `hist_{BTC,ETH}_PERPETUAL.csv` | Deribit | 2019→2026, 63,587 hourly rows | funding + OHLC + index |
| `cot_positioning.csv` / `cot_prices.csv` | CFTC + Yahoo | 1986→2026, 10 markets | discovery set |
| `cot_*_holdout.csv` | CFTC + Yahoo | 20 markets | **never used in discovery** |
| `derivs_BTC_hourly.csv` | OKX | 30 days | OI, long/short, taker buy/sell |
| `micro_*`, `ticks_*` | live recording | ongoing | **cannot be backfilled** |

Two build rules that must not be undone:

- **COT entry is the publication Friday, never the Tuesday report date.** The report is
  released Fri 15:30 ET. Aligning to Tuesday grants three days of hindsight in a weekly
  study — that is most of the "edge" anyone has ever claimed in COT.
- **CFTC renamed contracts to "Consolidated" in Feb 2022.** The fetcher picks the longest
  *single continuous* series rather than splicing. A splice makes position counts jump,
  and a trailing rank reads that jump as an extreme for three years afterwards.

---

## FX CROSS-SECTIONAL MOMENTUM 3M-1M — CLOSED

Preregistered, frozen by the strategy lead, implemented and certified over tasks 003,
003A and 003B. **Permanently failed. The exact V1 must not be revisited.**

Certified task-003B numbers, on the canonical executable panel, 19 fiat FX pairs,
minimum lot, one position, monthly rebalance at the first Monday 20:00 New York:

| | |
|---|---|
| Net | **−$75.94** |
| Return | **−7.76%** |
| Completed trades | **22** |
| Profit factor | **0.529** |
| Validation | **−9.85%** |
| Untouched holdout | **+2.32%** |
| Randomisation p (one-sided, 10,000 perms) | **0.7286** |
| Reverse strategy | **+$27.73** |

**All baseline monthly signal-only periods are negative on both panels** — canonical and
the 8-year broker-D1 panel, in development, validation and holdout alike.

**The failure was directional, not primarily spread cost.** Doubling every historical
spread moved the result by about a dollar on a −$76 outcome. The signal picks worse than
chance: 73% of random pair-and-direction draws beat it.

The simulator itself was certified in 003B — conversions are fitted at the exact H1
timestamp of every fill from midpoint opens, and five deterministic assertions cover exit
pricing, entry-bar stops, graph timestamp equality, monthly signal cadence and position
overlap. The infrastructure is reusable; the strategy is not.

**The reverse and delayed-entry controls are diagnostics, not candidate strategies.**
They exist to show the signal is worse than its own inverse and worse than a stale copy of
itself. Neither has been tested as a strategy, neither is preregistered, and neither may be
promoted on the strength of a control result.

Two structural facts that will recur in any successor on this account:

- **The trade-count bar and the risk rule are in direct tension.** 33 of 55 rebalances were
  skipped, every one on the 1.50%-of-equity stop-risk rule, because a 2-ATR stop at minimum
  lot costs about $14 against a $14.69 budget. Forty trades is not reachable on $979 with
  that stop and a monthly schedule.
- **The canonical executable panel has no development period.** It begins 2021-08-02;
  development ends 2021-07-31. Only the broker-D1 panel has one.

---

## FX POLICY-RATE DIFFERENTIAL V2 — CLOSED

Preregistered and frozen by the strategy lead; implemented in task 005 and certified in
task 005A. **Permanently failed. The exact V2 must not be revisited.**

Principal test is scenario 1, **zero-credit execution**: historical spreads only, no carry
credit of any kind, because this broker does not pay one (below).

| | |
|---|---|
| Baseline net | **−$49.93** (−5.10%), 47 trades |
| Validation | **−$30.39** |
| Untouched holdout | **−$19.55** |
| Profit factor | **0.826** |
| Randomisation p (one-sided, 10,000 paths) | **0.5525** |
| Conditions passed | **6 of 16**, plus one N/A |

### The broker pays nothing on the side the signal selects

Task 004A measured, across all 19 executable pairs, that wherever the policy differential
says a side should earn carry the Exness snapshot pays **exactly 0.00%** on it and charges
the other. V2 always trades that side, so applying the stored 2026 snapshot changed the
result by **$0.00 on every one of the 47 trades**.

**A carry-shaped strategy collects no carry here by construction.** It is left as a pure
directional bet, and the bet loses.

### The two theoretical-credit counterfactuals disagree in sign

| | Trades | Net |
|---|---|---|
| Baseline, zero credit (the executable reality) | 47 | **−$49.93** |
| **A** — fixed 47 baseline trades, credit added | 47 | **+$19.87** |
| **B** — recursively gated account path with credit | 49 | **−$7.32** |
| Actual 2026 Exness snapshot contribution | 47 | **$0.00** |

**A** holds the trade set fixed and adds only the $69.80 theoretical credit. **B** re-runs
the account, so the credit raises equity, which changes which months clear the 1.50% risk
gate, which changes the trade set. Task 005 reported only **B** and concluded that even full
credit leaves V2 negative; on the apples-to-apples comparison that conclusion does not hold.

**Neither may satisfy a pass condition.** Theoretical carry could have turned the fixed
trade set into a small profit — but that carry was not available on this setup, and the
executable strategy still lost.

### Why it failed

Not cost. Doubling every historical spread moved the result by $5.54. It failed on
**direction and on selection**:

- **73% of random pair-and-direction paths beat it** (median −$36.90 against −$49.93).
- Holding the policy-implied *direction* and randomising only the *pair*, the median random
  pick still beat it (−$28.63). **Choosing the largest differential was worse than choosing
  arbitrarily with the same directional logic.**
- The differential tercile diagnostic is **non-monotonic** — the low-differential tercile is
  the only positive one, the middle is the worst.
- The signal does not survive execution: over 58 overlapping months the canonical and D1
  panels agreed on **100% of pairs and 100% of directions**, yet returned **+0.0367**
  unpriced against **−0.0071** executed. The gap is spread and scheduled-open pricing.

### Data correction made during certification

Task 005 used a **forming Sunday D1 bar**. MT5 D1 timestamps are bar-open times on the UTC
day boundary, the FX week opens Sunday ~21:00 UTC, and that partial bar (2,969 ticks against
31,000–58,000 for a full weekday) was still open at retrieval; the Sunday→Monday merge
relabelled it 2026-08-03. Removing it moved the D1 panel end to **2026-07-31** and the D1
holdout from +0.0544 to **+0.0393** — the forming bar had inflated it by 28%. The verdict did
not change.

### Two distinctions that must be preserved

- **A current swap snapshot is not historical swap evidence.** The 2026 figures are a dated
  snapshot and were never applied to a historical date.
- **Zero carry on V2's selected side does not prove that every holding-based strategy on
  every venue is impossible.** It is one venue, one snapshot, one selected side.

### Not candidate strategies

The reverse (−$137.88) and delayed-entry controls exist to characterise the failure. Neither
is preregistered, neither has been tested as a strategy, and neither may be promoted on the
strength of a control result.
