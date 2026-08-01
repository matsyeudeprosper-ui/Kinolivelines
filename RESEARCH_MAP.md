# Research map — BTC-specific edges still open

Written 2026-08-01, after the OHLC/indicator space was closed and the crowding branch was
found untestable on this bot's history.

**Narrowed objective: one robust, profitable BTC edge after costs.** Cross-symbol
transfer is optional. A BTC-specific mechanism is not required to work on cattle, gold or
currencies — the validation universe must match the mechanism.

## The cost structure that shapes everything

Spread is a fixed $10 on BTCUSDm. What that costs depends entirely on horizon:

| horizon | median ATR | spread as % of ATR | history |
|---|---|---|---|
| M15 | $85 | **11.8%** | 1.4 yr |
| H1 | $383 | 2.61% | 7.59 yr |
| H4 | $798 | 1.25% | 7.59 yr |
| D1 | $1,727 | **0.58%** | 7.59 yr |

The current bot trades where costs are 20× worse and history is 5× shorter. Both argue
for the same move.

**Carry, newly measured and asymmetric:** `swap_long` = −1248.8 points = **−$12.49 per
night per lot (−7.24%/yr)**. `swap_short` = **exactly 0.00**. Shorts finance free; longs
bleed ~2bp a night. Triple charge on Fridays.

---

## Hypotheses, ranked by strength-if-testable-now

### H1 — Perp-index basis (leverage demand). **TESTABLE NOW. Strongest.**

- **Mechanism** — a perpetual has no expiry, so it trades at a premium or discount to its
  spot index purely according to how badly leveraged traders want exposure. A large
  premium means leveraged longs are paying up to get on; a large discount means positions
  are being dumped or unwound.
- **Why an edge should exist** — the gap is an arbitrage relationship. Market makers close
  it by taking the other side and hedging in spot. The question is not whether it reverts
  but whether the reversion is large and slow enough to clear $10.
- **Why it is not funding again** — measured: `corr(basis, funding) = 0.046`. Essentially
  orthogonal. Funding is an 8-hour smoothed average of the same pressure; the basis is
  instantaneous. Funding has been tested and is null for direction; the basis has never
  been tested at all.
- **Instrument / horizon** — BTC, 4h to 3 days.
- **Data** — `hist_BTC_PERPETUAL.csv`, 63,587 hourly rows, 2019-04→2026-07, cached.
  Basis sd 68bp, 1st/99th percentile ±197bp.
- **Minimum detectable effect** — ~15,900 non-overlapping 4h windows, ~1,600 in the
  extreme tails. 2SE ≈ 0.05R on mean R and ≈2.5pp on a stop-out rate. The effects worth
  having (≥0.1R) are comfortably detectable.
- **Validation universe** — BTC across separate periods, ETH-PERPETUAL (cached, same
  mechanism), and OKX BTC-USDT (different margin currency, fetchable). **Not** equities,
  metals or agriculture — the mechanism is specific to perpetual swaps.
- **Pass/fail** — beats a matched random-entry control by >2SE; same sign in ≥4 of 5
  entry-volatility quintiles; replicates on ETH; survives a two-sided rotation null; and
  holds on an untouched final 18 months never used to choose anything.
- **Status** — run this first.

### H2 — Carry asymmetry. **TESTABLE NOW. Low prior, cheap to check.**

- **Mechanism** — not a prediction; a measured cash flow. Shorts pay zero financing, longs
  pay 7.24%/yr.
- **Why an edge might exist** — at multi-day horizons this tilts the arithmetic of any
  hold. A strategy that is a coin flip before financing is positive on the short side and
  negative on the long side.
- **Instrument / horizon** — BTCUSDm specifically (broker-specific), days to weeks.
- **Data** — 7.59 yr of D1/H4.
- **Minimum detectable effect** — carry is 0.02%/night against a D1 ATR of 2.7%, so it is
  ~1/135th of daily noise. ~390 non-overlapping weekly holds. **Underpowered on its own**;
  only meaningful as a tiebreaker applied to a strategy that is already near-neutral.
- **Validation universe** — BTCUSDm on Exness only. Broker-specific by construction.
- **Pass/fail** — converts an otherwise-neutral rule to positive by >2SE. Never to be
  claimed as an edge in isolation.
- **Honest caveat** — BTC appreciated across the sample, so a naive short bias loses on
  direction far faster than carry can pay.

### H3 — Broker feed lag. **TESTABLE NOW (preliminary). Highest payoff, lowest prior.**

- **Mechanism** — Exness quotes BTCUSDm themselves, derived from real exchanges. If the
  quote trails the market, the next move is briefly knowable.
- **Why an edge should exist** — it would be near-arbitrage, requiring no directional
  forecast at all.
- **Instrument / horizon** — BTCUSDm vs OKX, sub-second to seconds.
- **Data** — 152,307 ticks over 3 days (ms stamps) plus 7,173 rows of 2-second paired
  quotes. **The 2-second study already found the cross-correlation peaks at lag 0**
  (r=0.6127), so the remaining question is strictly sub-2-second.
- **Minimum detectable effect** — to be worth trading the lag must imply a move >$10.
  Tick data resolves milliseconds; 152k ticks is enough for a preliminary read.
- **Validation universe** — Exness BTCUSDm only. Correctly needs no cross-market proof.
- **Pass/fail** — a cross-correlation peak at a strictly positive lag, stable across all
  three days, with implied move > spread. Anything at lag 0 kills it permanently.

### H6 — Variance risk premium (implied vs realised vol). **TESTABLE NOW. New.**

- **Mechanism** — DVOL is Deribit's 30-day implied volatility index, computed from the
  live options book. It is what traders are actually paying for protection, quoted in a
  different market from the one we trade. Realised volatility is computable from data
  already held, so the pair gives the variance risk premium directly.
- **Why an edge should exist** — sellers of volatility earn a premium over realised
  volatility persistently and across every asset class studied. Its size varies, and when
  it is unusually wide fear is priced in; when it inverts, the options market is signalling
  stress the spot market has not yet expressed. Neither reading is derived from past price,
  which is the whole category already exhausted here.
- **Instrument / horizon** — BTC, hours to days.
- **Data** — `dvol_BTC.csv` and `dvol_ETH.csv`, **46,947 hourly points each, 2021-03 →
  2026-08 (5.4 years)**, cached by `recorder/fetch_dvol.py`.
- **Minimum detectable effect** — ~11,700 non-overlapping 4h windows, ~1,170 in the tails.
  MDE ≈ **1.3pp** on a rate. Ample.
- **Validation universe** — BTC across separate periods, replicated on ETH DVOL. Crypto
  options mechanism; no equity, metal or agricultural proof is owed.
- **Pass/fail** — beats a volatility-matched random control by >2SE, same sign in ≥4 of 5
  entry-volatility quintiles, replicates on ETH, survives a two-sided rotation null, and
  holds on an untouched final period. For any directional claim the capturable move must
  exceed $14.
- **Status** — **the strongest testable-now hypothesis. Run next.**

### H4 — Order-flow imbalance / liquidation cascades. **NOT YET.**

- **Mechanism** — forced liquidations are non-informational selling; price should
  overshoot then revert.
- **Data** — `micro_*` has OKX top-5 bid/ask sizes but only 7,173 rows over 2 days.
  Liquidations are **not currently recorded at all** — that is a gap worth closing now so
  the clock starts.
- **Minimum detectable effect** — needs ~30 days for ~4,000 non-overlapping windows.
- **Action** — add liquidation capture to `derivs_recorder.py`; revisit at ~30 days.

### H5 — Open-interest change. **NOT YET.**

- 719 hourly rows (30 days backfilled from OKX, which caps there). ~180 non-overlapping
  4h windows — far too few. Revisit as the recorder fills.

---

## Explicitly closed — do not revisit

Every OHLC/indicator hypothesis (see `FINDINGS.md` §1), funding as a direction signal,
COT positioning as a direction signal, and horizontal levels as an entry trigger. Fifteen
tests, six instruments, four horizons.

## Standing constraint

The M15 bot stays unauthorised to open trades on a signal until an entry edge or a
complete strategy survives validation and then forward-demo confirmation.
