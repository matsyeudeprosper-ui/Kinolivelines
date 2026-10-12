# Portfolio study - research specification (DRAFT, not frozen, not run) - 2026-10-11

Mike's intended destination: **one shared account, a multi-market Owl.** When BTC has no eligible setup, another
approved market can supply one; after a trade closes, Owl may take the next FRESH eligible setup. The per-market
scanner (SCANNER-F2) cannot answer that: it keeps one virtual position per market, with no shared balance, risk,
recovery or limits. This study is separate from SCANNER-F2, the Compte pipeline, the shared demo and the frozen entry
study, and reads none of their records. Nothing live; no automatic promotion of a historical winner.

## 1. Question
Does letting one account take the next fresh eligible setup from a small approved set of markets improve the
account's **net** result and risk versus BTC-only and versus simple fixed selection rules - after contract-aware
sizing, sessions, spreads, swaps and a commission/slippage stress - or does it only add trades?

## 2. Instruments
BTCUSD (today's market) + the scanner's candidates USTEC, XAUUSD (primary), US30, US500 (secondary, highly
correlated with USTEC: 0.77-0.90 hourly). The approved list is fixed per run and stated before the run. Every run
reports which instrument supplied each trade.

## 3. Signals (no new strategy)
Per instrument, the robot's own `Struct` from a frozen engine bundle (same build method as `engine_f2`), seeded with
3000 closed M1 bars, stepped per closed bar; `pb_gate("trend")` on the pullback state of the last 8000 closed bars;
the min-stop rule (S_MIN_DIST on BTC, 10/7 x spread elsewhere); stop = the new protected dot; target 0.8 x risk.
Exactly the scanner's signal layer, so the two studies share signals but not account logic.

## 4. Account behaviour under test
* **One open position across the whole portfolio** (v1). A second-position variant is a later, separate study.
* **Fresh setups only, no queue:** a setup is eligible only on the candle that produced it (bar model: that bar's
  close; tick model: <= 90 s after the candle close, fresh quote <= 30 s); signals arriving while a position is open
  are DISCARDED and logged, never stored for later.
* **Revalidation at entry:** at the entry quote the trend gate is re-run, the stop must still be on the correct side
  and beyond the min distance, the instrument must be in session and quoting.
* **Selection when several qualify in the same decision minute - fixed, causal rules decided now:**
  * S0 **BTC-only** (benchmark - today's robot behaviour on this layer);
  * S1 **BTC first, then a fixed list** BTC > XAUUSD > USTEC > US30 > US500;
  * S2 **first come**: earliest candle close, ties broken by the S1 list;
  * S3 **cheapest**: lowest expected cost in R at the decision (spread / stop distance, both known then);
  * S4 **BTC + gold only** (smallest diversified set; gold is the least correlated candidate, 0.42-0.47);
  * S5 **random among the qualifying** (control for the selection itself).
  No rule may use past performance of an instrument (that would promote a historical winner); a
  performance-weighted rule would be its own, separately frozen study.

## 5. Money management - one ledger for all instruments
The live robot's account rules applied to the portfolio as one account (deposit currency USD):
* sizing: base lot logic and balance scaling translated to **dollar risk per trade**, converted per instrument
  with the broker's own arithmetic (`order_calc_profit` for the value of the stop distance per lot; volume min /
  step / max from `symbol_info`); the 10 % max-risk cap per trade;
* recovery: one debt / jar / bullets state shared across instruments (a loss on gold is recovered by any later
  trade); FLIP + 1 continuation in debt; adds at the midpoint sized in dollars; recovery restrictions as live;
* daily profit cap (adaptive, as live), the -$60 kill line on net from start, day boundaries in UTC;
* reported both with and without recovery, so the selection effect is not hidden by the recovery effect.

## 6. Sessions, costs, data
* Entries only while the instrument trades (sessions from observed bars / quotes, broker calendar); positions held
  across a close keep their gap risk (stop filled at the first quote beyond it).
* Costs: the instrument's spread (bar spread in the bar model, bid/ask in the tick model), **overnight swaps** from
  `symbol_info` swap rates converted with `order_calc_profit`, and a stress of +0.5 / +1.0 x spread per trade as
  commission/slippage. Results are called net only under the +1.0 stress.
* Data: demo-server M1 bars and ticks; history depth measured per instrument before the spec is frozen; gaps reported.

## 7. Execution tiers
1. **Bar tier (exploratory):** entry at the signal bar's close (+spread for a buy), M1-bar exits, same-bar tie = loss,
   explicit end-of-window close (last window bar, bid/ask) for every rule and control alike.
2. **Tick tier (confirmatory):** the v3 rules - fresh quote at detection with 5 s polling latency, tick exits after
   the entry tick, stop slippage, missing quotes = missed.
Only tick-tier results can be quoted as the portfolio's performance.

## 8. Comparisons and controls
* Every rule vs **S0 BTC-only** and vs **S5 random selection**.
* **Matched random-entry portfolio**: random entry times under the SAME constraints (one position, sessions,
  fresh-only, same sizing / recovery / limits, same direction and stop-distance distributions per instrument).
* Windows: last 30 calendar days, previous 30, equal halves of each, and the longest history the data allows.
* Metrics: net $ and %, expectancy per trade ($ and R), max drawdown $ / %, worst debt, kill / cap days, trades and
  net per instrument, signals discarded because busy (per instrument), time in market, costs and swaps, concurrency
  of qualifying signals across instruments, and per-instrument correlation of trade outcomes.

## 9. Decision rule (to be frozen with GPT before the tick tier)
A rule beats BTC-only only if, in the tick tier, its net result under the +1.0 stress is better in every window AND
its max drawdown / worst debt is not worse by more than an agreed margin AND it beats the matched random portfolio's
95th percentile. Even then the next step is a separately frozen VIRTUAL forward test of the portfolio account, never a
deployment.

## 10. Separation and safety
Own folder `study/portfolio/`, own frozen engine bundle, own outputs; no read of Compte, SCANNER-F2 records, the
frozen entry study or member data; read-only MT5 access on the demo terminal; heavy jobs run sequentially (disk /
pagefile incident) with a free-space check before tick downloads.

## 11. Runtime estimate (for GPT's go / no-go)
| step | estimate |
|---|---|
| History depth + swap/contract tables, 5 instruments | 5 min |
| Signal pre-computation, bar tier (shared by all rules), 3 windows | ~5 min (scanner backtest speed, 17 s per 30 d per instrument) |
| Portfolio replays, bar tier: 6 rules x 3 windows x (full + 2 halves), with and without recovery | 15-30 min |
| Matched random portfolios, bar tier, 500 reps x 6 rules x 3 windows | 45-90 min |
| Tick download (60 days, USTEC ~0.47 M ticks/day; total ~50 M ticks, ~2-3 GB) | 20-40 min, sequential |
| Tick tier replays, 6 rules x 3 windows | 2-4 h |
| **Total** | **bar tier ~1-2 h; tick tier +3-5 h (overnight, sequential)** |

## 12. Questions for GPT before freezing
1. Approved list: all five, or BTC + gold first (S4) as the primary hypothesis?
2. Recovery semantics across instruments: shared debt as above, or per-instrument debt?
3. The drawdown / debt margin for "not worse" in section 9.
4. Whether the bar tier may run now as exploratory, with the tick tier frozen afterwards.
