# Poches (pockets) - product note for GPT (2026-10-12)

Owner: like portfolio / crypto-wallet apps, one "pocket" per market so it shows which market performs better; the
main balance reflects all gains. Built in two strictly separate parts. No strategy or live-trading change.

1. **Real pockets** (Patrimoine > "Poches", home card "Vos poches"): from the account's REAL closed trades only.
   `owl_nest_worker.py` now appends the deal's symbol as field 5 of each wealth trade (and to `others`); readers
   of fields 0-4 are unchanged; workers restarted by the manager (9 -> 9). Each pocket: net, trades, win rate,
   best / worst, per trade, curve. Reconciliation shown: start + deposits + sum of pockets + outside-robot = the
   account balance (checked on u224016179: 210.00 + 46.60 = 256.60; on `fresh` BTC -51.52 and ETH +0.94 = 949.42).
   One shared account: a pocket shows what a market EARNED, not a separate balance (allocation per market belongs
   to the portfolio study).
2. **Test pockets** (Scanner > "Poches", labelled "virtuel"): pretend 100 $ per market, 2 % of the pocket risked
   per virtual trade (value = 100 x prod(1 + 0.02 R)); two numbers per market - the 30-calendar-day bar backtest
   and the v3 live test. Never added to any balance, labelled "not a recommendation". It is a presentation of the
   existing scanner records; SCANNER-F2 scoring is unaffected (`owl_scanner.py` and `engine_f2` untouched).

## Update - trial pockets in Patrimoine (same day)
Owner: the markets the scanner trades virtually must also be in the Poches pages; "when virtual testing is done we
will just update to real money". Patrimoine > Poches now has a switch **Argent réel / En essai**. "En essai" =
`<tok>/test_pockets`: the scanner's live virtual strategy trades only (forward_v3, engine v3-quote; not the controls),
pretend 100 $ per market, 2 % per trade; hero (average change per market, markets, virtual trades, open), a two-column
tile grid, each tile opening the same pocket space as a real pocket marked "virtuel" (R per trade shown). Levels only
for Strategie / admin. Never added to the real totals or the balance check. A market that later trades with real
money appears under "Argent réel" by itself (worker symbol field). Display only: SCANNER-F2 records and scoring
untouched.
