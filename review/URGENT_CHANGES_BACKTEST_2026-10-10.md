# Backtest of the 2026-10-10 urgent live changes (for Mike) - development data, tick engine

Three changes went live today on your instruction. Here is what the same replay that GPT audited says about
them (dataset b: 42 days of BTCUSDm M1 bars + 4.87 million bid/ask ticks, each account's own package, both
cost cases: spread only, and spread + $0.35 per 0.02 lot). Development data = the same history we have been
looking at for a week, so these are point estimates, not proof.

## 1. The pullback-direction gate (`pb_dir_gate`, with the CHoCH exception) - `study/tick_engine_pbgate.py`
The gate was replayed exactly as the bot computes it (pullback chart rebuilt at every signal bar, causally;
814 of 857 opportunities had a pullback trend, 368 a pending CHoCH). "Live rule" = refuse against the pullback
trend unless a CHoCH in the trade's direction is pending and price is beyond it; "strict" = refuse always.

| account | cost | as before: net / drawdown | LIVE rule: net / drawdown (refused / let in by CHoCH) | strict: net / drawdown |
|---|---|---|---|---|
| Infinity | spread only | 38.5 / 56.8 | 29.3 / 40.2 (249 / 126) | 22.5 / 27.8 |
| Infinity | + $0.35 | -24.7 / 55.0 | -11.6 / 50.6 | +0.3 / 37.3 |
| Depenses (cap3) | spread only | 62.2 / 61.1 | 52.2 / 53.5 (260 / 126) | 41.9 / 43.0 |
| Depenses (cap3) | + $0.35 | -44.8 / 64.7 | -11.4 / 67.1 | +0.9 / 48.0 |
| Special | spread only | 68.6 / 117.4 | 63.7 / 107.9 (249 / 127) | 79.5 / 60.1 |
| Special | + $0.35 | -72.1 (kill) / 117.0 | -61.9 (kill) / 101.2 | +6.0 / 95.8 |
| reference demo (no brakes) | spread only | 60.6 / 84.7 | 9.0 / 101.9 (232 / 108) | 29.6 / 61.6 |
| reference demo | + $0.35 | -43.0 / 113.5 | -59.9 / 130.4 | -21.5 / 81.9 |

What it means, plainly:
* With spread only, the live rule makes LESS money on every account (-24% / -16% / -7%, and -85% on the
  reference) for a smaller drawdown on the three capped accounts (-29% / -12% / -8%). Same conclusion as the
  10-07 test: the pullback direction itself does not pick better trades.
* With the extra $0.35 cost, the live rule loses less than before on the three live accounts (fewer trades =
  less cost paid), but it is still negative everywhere.
* The CHoCH exception is the weak part: the trades it lets back in (108-127 per account) are the ones that
  turn a strict gate's +0.3 / +0.9 / +6.0 (under cost) back into -11.6 / -11.4 / -61.9. The strict version
  (no exception) is the only variant positive on every live account under cost, and it cuts drawdown the
  most - but it also trades 40% less and gives up profit when costs are low.
* The reference demo must stay OFF (it is), it loses the most with the gate.

## 2. The daily-cap exception ("continuer aujourd'hui") - from the 12-cell matrix, cells "cap off" vs "cap on"
Replayed as "no daily profit stop at all" with the accounts' normal entry (the strongest form of the exception).
| account | cost | cap on: net / drawdown | cap off: net / drawdown | extra trading days |
|---|---|---|---|---|
| Infinity | spread only | 38.5 / 56.8 | 67.4 / 56.8 | 37 |
| Infinity | + $0.35 | -24.7 / 55.0 | +0.7 / 55.0 | 17 |
| Depenses | spread only | 62.2 / 61.1 | 64.0 / 62.2 | 30 |
| Depenses | + $0.35 | -44.8 / 64.7 | -33.5 / 64.7 | 11 |
| Special | spread only | 68.6 / 117.4 | 112.5 / 127.3 | 33 |
| Special | + $0.35 | -72.1 / 117.0 | +7.1 / 129.7 | 19 |
Plainly: continuing after the daily target earned MORE on every account (a lot more on Infinity and Special)
without changing the drawdown much - with the accounts entering as they do today. One caution: in the same
matrix, removing the cap HURT every "delayed-entry" variant, so if the delayed entry ever goes live the cap
should come back with it.

## 3. The Nid "all robots" switch
A control, not a strategy - nothing to backtest. It writes the master pause file every robot reads live.

## Bottom line
* Cap exception: supported by the replay (more profit, same risk) for the accounts as they trade today.
* Pullback-direction gate as deployed (with the CHoCH exception): not supported - it costs profit at low cost
  and only softens losses when costs are high; the exception gives back most of what the strict gate saves.
  Your call: keep it (your rule), switch to the strict version, or turn it off (one dial, `pb_dir_gate`, bots
  restart in a minute).
