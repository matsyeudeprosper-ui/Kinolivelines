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

## 4. Crowding as a RISK measure — SURVIVES

See the table in [`README.md`](README.md). Adverse excursion rises ~5–6% at positioning
extremes, on BTC and ETH via funding and on 20 unseen futures markets via COT.

Direction remains completely unpredictable. Favourable excursion does **not** replicate,
so the widening is asymmetric — a crowded market travels further against a position than
for it.

**Effect lives at ~4 hours.** At 8h it points the same way with the same magnitude but
fails the rotation null; at 1 day it is gone.

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

## Methods worth reusing

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
