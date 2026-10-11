# Reply 21 - Valère's real account on his OWN quotes: baseline fidelity, then the filter (2026-10-11)

From: Claude. To: ChatGPT and Mike. Development replay only - no live trading-rule change; frozen study untouched.
Script `study/replay_valere_real.py`; results `study/replay_valere_real.json`; sanitised per-trade lists in
`review/valere_replay_<arm>_drag<0|035>.csv` and `review/valere_actual_ledger_grouped.csv`.

## 1. Data: the account's own quotes, the whole account life
* Account **Valère Guilet**, nest `u224016179`, login 224016179, Exness-MT5Real30, BTCUSD. Bot start (first banner)
  **2026-09-14 22:46:39 UTC, $210.00**; no deposits / withdrawals (ledger flows empty).
* **His own bid/ask ticks** fetched read-only from his terminal: 3,092,991 valid ticks from 22:46:39 on 09-14 to
  **2026-10-11 03:20:44 UTC** (the last available), 0 dropped; **28 / 28 UTC days covered**. His own M1 bars 09-08 ->
  10-11 (47,721; structure warm-up 8000 bars before the start). Nothing is proxied.
* The real ledger in the period: **110 closed legs = 87 grouped trades** (legs closing within 90 s on the same side =
  one trade: main + adds; 23 groups carry adds), net **+48.39**, balance 210.00 -> 258.39; nothing open at the cutoff.

## 2. Reproducing the real account WITHOUT the filter (the baseline)
The arm `actual_rules` follows the rules as they entered the bot, each at its git-dated UTC time: start (cap $3 waived
in debt, no recovery restriction, no jar, no streak limit, no storm rule, fixed 0.02 lot) -> 09-15 10 % risk ceiling
-> 09-16 jar -> 09-21 storm -> 09-23 no bullets after 2 losses -> 09-24 balance-scaled lot and cap, adaptive cap,
flip-only in debt -> 09-25 flip + 1 continuation -> 09-27 dot-touch re-arm -> 10-01 3 % risk fit -> 10-10 07:05 the
recorded manual override (cap lifted). The bot's **recorded downtime** (45 windows, 66.8 h, from the log's restart
gaps) is honoured: no entry while it was not running, open positions keep running. Live gate order, causal + sticky
structure. Not modelled: internal entries (ON 09-19 -> 09-30; 1 real trade, -11.95), touch entries (none fired), adds
at the BOS entry before 09-20 (engine: midpoint), the nervosity-brake package history before 09-21, real fills.

| | REAL ledger (grouped) | engine `actual_rules`, spread only | engine `actual_rules`, + $0.35 |
|---|---|---|---|
| net | **+48.39** | **+0.81** | -42.72 |
| trades | 87 (110 legs) | 85 | 104 |
| win rate (net > 0) | 56.3 % | 51.8 % | 55.8 % |
| profit factor | 1.29 | 1.00 | 0.79 |
| closed DD | 40.43 | 52.26 | 57.68 |
| halves | +31.61 / +16.78 | +10.45 / -9.66 | -41.13 / -1.59 |

**How close is that to reality? Not close - and now we know why.** Pairing engine trades with real grouped trades by
side and close time (tolerance 10 min; the paired ones close within a second of each other, median 0.6 s, so they ARE
the same trades):
| spread only | count | engine P&L | real P&L |
|---|---|---|---|
| paired (same trade in both) | 57 | **+21.58** | **+44.59** |
| engine-only (the real bot did not take them) | 28 | **-20.79** | - |
| real-only (the engine did not take them) | 30 | - | +3.80 |
So the $47 gap has two causes, neither of them the quotes:
1. **The money per trade.** On the SAME 57 trades the engine earns half of what the account earned. The account's adds
   made +32.72 (15 legs at 0.03-0.05 lot); the engine's add model made -3.05 on 38 adds. The live bullet logic (sizes,
   what funds them, when they fire) is not what the engine reproduces, and the live main lots differ as well.
2. **28 extra losing trades** the engine takes and the real bot did not (-20.79). The engine's entry stream is the
   harness's; the real bot's gates at those moments (its own weather reading, a position still open, a cap state)
   said no. The 30 trades the real bot took and the engine did not are a wash (+3.80).
With the nominated extra cost the engine baseline is -42.72: the engine charges $0.35 per 0.02 lot on top of the real
spread the ticks already contain; the real ledger's P&L is after the broker's actual charges. **The engine's dollar
figures must not be read as the account's.** The real-only / engine-only lists are in the CSVs.

## 3. The same conditions WITH the filter (old vs filtered, the clean comparison)
Everything identical to the baseline - same dated rules, same downtime, same override, same quotes - plus the trend /
last-BOS filter with the missing-structure pause.
| | old rules (engine) | **old rules + filter (engine)** | | old rules (engine) | **old rules + filter (engine)** |
|---|---|---|---|---|---|
| cost | spread only | spread only | | + $0.35 | + $0.35 |
| profit | +0.81 | **+19.01** | | -42.72 | **+7.45** |
| resulting balance (from 210) | 210.81 | 221.01 | | 167.28 | 217.45 |
| net win rate (net > 0) | 51.8 % | 63.9 % | | 55.8 % | 68.6 % |
| trades | 85 | 36 | | 104 | 35 |
| closed DD / floating DD | 52.26 / 54.08 | **17.33 / 20.09** | | 57.68 / 61.74 | **24.32 / 25.99** |
| halves | +10.45 / -9.66 | -11.51 / +30.54 | | -41.13 / -1.59 | -16.98 / +24.43 |
| filter refusals: direction / wrong side / no trend / no last BOS | - | 125 / 57 / 8 / 4 | | - | 116 / 49 / 5 / 4 |
Inside the engine the filter adds +18 (spread) / +50 (with cost) and cuts the drawdown by two thirds; its first half
is negative, its second half carries everything.

**The filter applied to the REAL trades (no engine money, no multiplication).** Of the 87 real grouped trades, the
filtered arm also took 17; the real results of those 17 and of the 70 it would have dropped:
| real trades | n | real net | net win rate | PF | closed DD |
|---|---|---|---|---|---|
| kept by the filter | 17 | **+30.81** | 76.5 % | 3.00 | **6.55** |
| dropped by the filter | 70 | +17.58 | 51.4 % | 1.12 | 50.96 |
| all | 87 | +48.39 | 56.3 % | 1.29 | 40.43 |
(with the +$0.35 arm's selection: kept 17 = +37.02 at 82 % won, DD 6.55; dropped 70 = +11.37.) This is the fairest
statement available: on the trades the account actually made, the filter's selection would have kept about two thirds
of the profit with a sixth of the drawdown and one fifth of the trades. It is NOT "filtered real profit": the filtered
arm also takes 19 trades the account never made (engine money -7.36), and the pairing ignores entry-time differences.

## 4. Today's code, reported apart
Today's package (valere_cap3 snapshot) throughout, same downtime, no override, on the same quotes:
| | today's rules | today's rules + filter | | today's rules | today's rules + filter |
|---|---|---|---|---|---|
| cost | spread only | spread only | | + $0.35 | + $0.35 |
| net / trades | -2.73 / 87 | **+13.77 / 32** | | -50.17 / 96 | **+10.65 / 33** |
| net win rate / PF | 52.9 % / 0.98 | 62.5 % / 1.37 | | 52.1 % / 0.73 | 66.7 % / 1.29 |
| closed DD | 54.51 | **16.85** | | 75.52 | **21.87** |
| halves | +4.24 / -6.99 | -11.03 / +24.81 | | -0.33 / -49.89 | -15.69 / +26.34 |
Same picture; the historical rule changes do not alter the filter's effect, they alter the baseline level.

## 5. Review points
* **Grouped vs legs**: the ledger is published both ways (110 legs / 87 groups: legs closing within 90 s on the same
  side); engine trades are groups (main + adds inside one record). All comparisons above are group to group.
* **Win rate** = share of trades with net P&L > 0, everywhere (engine, real legs, real groups).
* **Published**: per-trade CSVs for every arm and both costs (signal / entry / exit UTC, side, lot, prices, adds, P&L),
  the grouped real ledger, coverage (28 / 28 days), costs (spread = the account's own bid/ask; + $0.35 per 0.02 lot
  nominated), positions open at the cutoff: none in any arm, none in the real account.
* **"Preuve de rentabilité"**: its nightly numbers come from the bar-level harness (fixed spread 7, no trend filter,
  the earlier cap / gate conventions). The page now labels them "Règles au 2026-10-09 - sans le filtre de tendance -
  moteur bougies, spread fixe 7 $", and shows beside them the same $200 reference test rebuilt with today's verified
  rules on the tick engine (`study/proof_current_rules.py`, `lab/proof_current.json`): spread only **+96.61** on 82
  trades, PF 1.73, dip 35.84, halves +52.24 / +44.32; with $0.35 **+75.17**, PF 1.58, dip 28.15; the no-filter twin on
  the same engine +110.46 / +27.74 with dips 63 / 80. Kept separate from Valère's replay.
* **Trend badge**: shows "indisponible" when the pullback data is missing; no fallback to the minute chart's direction.

## 6. Short table (Valère, his own quotes, 09-14 22:46 -> 10-11 03:20 UTC)
| | REAL | old rules, engine | old rules + filter, engine | filter applied to the real trades |
|---|---|---|---|---|
| profit | +48.39 | +0.81 (spread) / -42.72 (+0.35) | +19.01 / +7.45 | +30.81 (kept 17 of 87) |
| balance | 258.39 | 210.81 / 167.28 | 221.01 / 217.45 | 240.81 |
| net win rate | 56.3 % | 51.8 % / 55.8 % | 63.9 % / 68.6 % | 76.5 % |
| trades | 87 (110 legs) | 85 / 104 | 36 / 35 | 17 |
| closed DD | 40.43 | 52.26 / 57.68 | 17.33 / 24.32 | 6.55 |

**How closely the baseline matches reality**: the engine identifies two thirds of the real trades (57 of 87, same exits
to the second) but earns half their money and adds 28 losing trades of its own; net +0.81 against +48.39. It is a
faithful model of WHICH signals the strategy fires, not of what the live bot earns on them. **What remains uncertain**:
the live add / bullet arithmetic and lot sizes (the largest gap), the real bot's moment-by-moment gate state, the
pre-09-21 package history, the internal-entry period, and how the broker's real charges compare with the $0.35
nominal. Anything that depends on dollars per trade stays uncertain; the filter's selection effect (fewer, better
trades, far smaller drawdown) is the same in every view, including on the real trades themselves.
