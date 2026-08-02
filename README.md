# KinoliveLines

> **NEW HERE? READ [HANDOFF.md](HANDOFF.md) FIRST.** ~20 ideas have been tested to
> completion. It lists what is closed, what works, what is still open, and what not to
> re-propose. Reading it will save you from re-running experiments that already have
> answers.


An autonomous BTCUSDm trading loop on a **demo** MetaTrader 5 account, and the research
programme that grew out of it: a systematic search for a tradeable edge, conducted with
enough discipline that most of the answers came back "no".

The negative results are the point. They are recorded here as carefully as the positive
one so that nobody — human or model — spends another week re-deriving them.

> **If you are an AI picking this up cold, read [`FINDINGS.md`](FINDINGS.md) before
> proposing anything.** It lists twenty-odd hypotheses that have already been measured
> and killed, and the five specific ways this project has previously fooled itself.

---

## The one thing that survived

Fifteen tests of "can we predict price from past price?" came back null across six
instruments and four time scales. So the question changed:

> Not *"can we predict direction?"* but *"can we detect when one side of the market is
> forced or trapped?"*

The answer is that crowded positioning tells you **nothing about direction** and
something real about **risk**:

| | BTC | ETH |
|---|---|---|
| adverse excursion, 4h horizon, stratified by entry volatility | **+6.0%** ±2.6 | **+5.2%** ±2.4 |
| volatility quintiles with the same sign | 5 of 5 | 5 of 5 |
| two-sided rotation null | **1.0%** | **0.0%** |
| stop-out rate at 1.0× ATR | **+2.90 pp** | **+2.00 pp** |

It replicates a completely independent result: weekly CFTC positioning across **twenty
futures markets that took no part in discovery** (grains, softs, livestock, metals, FX)
showed **+5.6%** adverse excursion at positioning extremes. Different data, different
instruments, different measure of crowding — same sign, same magnitude.

**It is a risk fact, not an entry signal**, and it has not yet been implemented. It is
also **not testable on this bot's own history**: sequential trading leaves only 307
crowded trades, a 2SE near 6pp against a 2–3pp effect. The horizontal levels are not the
obstacle — near-level entries show the same +1.8pp gap as trading every hour (+1.9pp).
The obstacle is that MT5 BTCUSDm M15 reaches back only 1.4 years. See
[`FINDINGS.md`](FINDINGS.md) §4.

---

## Layout

```
live/         the trading loop that runs 24/7
  daemon.py       event loop; watches levels, wakes a decider
  brain.py        the rulebook + provider dispatch (GPT-5 / Claude API / Claude session)
  act.py          the ONLY path that touches the account; refuses non-demo, caps lots
  briefing.py     renders live market state for whoever is deciding
  decisions.csv   every decision with its reason and which model made it

recorder/     data collection (some of it irreplaceable — see below)
  recorder.py                 fills, bars, ticks from MT5
  derivs_recorder.py          5-min OKX open interest / long-short / taker / funding
  microstructure_recorder.py  2-sec Exness quote vs OKX order book
  backfill_derivs.py          pulls the 30 days OKX already has
  fetch_funding_history.py    7.3 years of hourly perp funding from Deribit
  fetch_cot.py                CFTC positioning + prices; `python fetch_cot.py holdout`

study/        every experiment, each with its reasoning in the docstring
```

`RESTORE.md` is the operational runbook — how to restart everything, what each process
is, and what "healthy" looks like.

---

## Reproducing the headline result

```bash
python recorder/fetch_funding_history.py    # 7.3y BTC+ETH hourly funding (already cached)
python study/btc_crowding_final.py          # the decisive stratified test
python study/btc_crowding_practical.py      # what it does to stop-out rates

python recorder/fetch_cot.py                # discovery markets
python recorder/fetch_cot.py holdout        # 20 unseen markets
python study/cot_holdout.py                 # the replication that killed the reversal signal
python study/cot_mechanism.py               # and found what survived it
```

Cached datasets live in `recorder/data/` so nothing needs re-downloading:
`hist_BTC_PERPETUAL.csv` / `hist_ETH_PERPETUAL.csv` (63,587 hourly rows each, 2019→2026),
`cot_positioning*.csv` and `cot_prices*.csv` (30 markets, 1986→2026).

---

## Two things that are easy to break

**The recorders cannot be backfilled.** `microstructure_recorder.py` and
`derivs_recorder.py` write history that no API sells. If they stop, that window is gone
permanently. Check their heartbeats before touching anything.

**`act.py` is the only thing allowed to trade.** It verifies the account is the expected
one, refuses outright if `trade_mode != 0` (i.e. not a demo), caps lot size, validates
that a pending order's side makes sense against the current price, and logs every
attempt — including the failures. Do not bypass it.

---

## Status

> **Authorised to trade on demo for forward observation, data collection and execution
> validation. Not authorised for real-money deployment, and not considered to have a
> validated edge.**

Demo account 436771046, ~$979 equity.

### Two questions, kept separate in all reporting

1. **Is the strategy profitable?** — **Unproven, and the historical evidence is
   negative.** The reconstructed baseline over 5,892 setups is deeply negative and no
   entry criterion has ever beaten a random-entry control. Demo trades are **not**
   evidence for this question.
2. **Is the live system executing its stated rules correctly?** — testable now, and
   that is what demo activity is for. Fills, slippage, stop placement, rule adherence
   and failure handling can all be validated without any edge existing.

Conflating the two is the main way a demo record gets misread.

### Standing constraints

- demo only — `act.py` refuses outright if `trade_mode != 0`
- no automatic migration to real money, ever
- no increase in risk to chase recovery
- fixed conservative risk limits — `MAX_LOTS = 0.05` hard ceiling
- one position at a time unless existing rules explicitly require otherwise
- every signal, rejection, entry, fill, slippage, stop, exit and decision context is
  recorded — **rejections included**, via `act.py note`
- the strategy is **not** modified on the basis of a small number of demo outcomes
- performance is evaluated only after a predefined sample size, and then against the
  reconstructed historical expectation and a random-entry control

Demo activity must not divert attention from the liquidation and order-flow research
gates in [`RESEARCH_MAP.md`](RESEARCH_MAP.md); those still govern what gets tested next.
