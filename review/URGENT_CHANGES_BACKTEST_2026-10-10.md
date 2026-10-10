# Backtest of the 2026-10-10 urgent live changes (for Mike) - development data, tick engine (v3: cap-claim corrected)

Three changes went live today on your instruction. Here is what the same replay that GPT audited says about
them (dataset b: 42 days of BTCUSDm M1 bars + 4.87 million bid/ask ticks, each account's own package, both
cost cases: spread only, and spread + $0.35 per 0.02 lot). Development data = the same history we have been
looking at for a week, so these are point estimates, not proof.

## 1. The pullback-direction gate (`pb_dir_gate`, with the CHoCH exception) - `study/tick_engine_pbgate.py` (v2)
v2 (replaces the first run, kept as `tick_engine_pbgate_v1.json`): the gate now runs in the SAME order as the live
bot - after the awake / weather / dedupe gates and after the recovery allowance is consumed, right before the
order (GPT's review-16 correction). The pullback chart is rebuilt causally at every signal bar (814 of 857
opportunities had a trend, 368 a pending CHoCH). "Live rule" = refuse against the pullback trend unless a CHoCH
in the trade's direction is pending and price is beyond it; "strict" = refuse always.

| account | cost | as before: net / drawdown | LIVE rule: net / drawdown | strict: net / drawdown |
|---|---|---|---|---|
| Infinity | spread only | 38.5 / 56.8 | 32.4 / 36.0 | 23.4 / 24.3 |
| Infinity | + $0.35 | -24.7 / 55.0 | -7.9 / 47.2 | +2.6 / 33.6 |
| Depenses (cap3) | spread only | 62.2 / 61.1 | 43.0 / 52.3 | 40.1 / 39.5 |
| Depenses (cap3) | + $0.35 | -44.8 / 64.7 | -21.5 / 66.0 | +3.7 / 44.9 |
| Special | spread only | 68.6 / 117.4 | 71.2 / 94.2 | 84.6 / 56.4 |
| Special | + $0.35 | -72.1 (kill) / 117.0 | -68.3 (kill) / 99.5 | +10.4 / 84.7 |
| reference demo (no brakes) | spread only | 60.6 / 84.7 | 9.0 / 101.9 | 29.6 / 61.6 |
| reference demo | + $0.35 | -43.0 / 113.5 | -59.9 / 130.4 | -21.5 / 81.9 |

What it means, plainly (unchanged by the ordering fix, numbers a little kinder):
* With spread only, the live rule makes less money on Infinity and Depenses (-16% / -31%), about the same on
  Special (+4%), and much less on the reference (-85%), for a smaller drawdown on the capped accounts (-37% /
  -14% / -20%). The pullback direction itself does not pick better trades - same conclusion as the 10-07 test.
* With the extra $0.35 cost, the live rule loses less than before on the three live accounts (fewer trades =
  less cost paid), but it is still negative on all three.
* The CHoCH exception is the weak part: the trades it lets back in turn a strict gate's +2.6 / +3.7 / +10.4
  (under cost) back into -7.9 / -21.5 / -68.3. The strict version (no exception) is the only variant positive
  on every live account under cost and it cuts drawdown the most - but it trades about 40% less and gives up
  profit when costs are low (except on Special).
* The reference demo must stay OFF (it is): it loses the most with the gate.
* Not measured: the gate TOGETHER with the cap exception (the two live changes were tested one at a time), and
  the cap exception as a discretionary "press" (it is modelled as "no daily stop for the whole period").

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
without changing the drawdown much - with the accounts entering as they do today. One caution (corrected
2026-10-10 evening, GPT review 17): in the same matrix, removing the cap HURT the SELECTED always-delay /
all-BOS combination (cap on 92.27 / 142.39 / 236.38 vs cap off 45.10 / 123.18 / 161.04 net on Infinity /
Depenses / Special at spread only) - that is the variant the statement applies to in these results, not
every delayed variant; so if that combination ever goes live the cap should come back with it.

## 3. The Nid "all robots" switch
A control, not a strategy - nothing to backtest. It writes the master pause file every robot reads live.

## Bottom line
* Cap exception: supported by the replay (more profit, same risk) for the accounts as they trade today.
* Pullback-direction gate as deployed (with the CHoCH exception): not supported - it costs profit at low cost
  and only softens losses when costs are high; the exception gives back most of what the strict gate saves.
  Your call: keep it (your rule), switch to the strict version, or turn it off (one dial, `pb_dir_gate`, bots
  restart in a minute).
