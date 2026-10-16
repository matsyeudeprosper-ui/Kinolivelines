# Multi-broker go-live checklist (owner 2026-10-16: "prepare go live, new user with a broker other than Exness")

## Must-have (blocking - real money at risk without them)
1. Broker readiness check at sign-up: symbol, contract, lot rules, fill type, broker clock, account currency; no trade until all pass.
2. Bitcoin symbol finder (BTCUSD / BTCUSD. / BTCUSDT ... - today only BTCUSD / BTCUSDm).
3. Contract-aware sizing: lots, min lot, lot step and $ per point from the broker's contract (today: 1 lot = 1 BTC = $1/point assumed).
4. Broker clock -> UTC for candles, day roll, hour filters (Exness = UTC; most brokers UTC+2/+3).
5. Fill type + stop/freeze level for EVERY bot (market bots fixed 2026-10-15; the main BTC bot still hardcodes IOC).
6. Account currency: 3 % cap, 10 % ceiling, kill line, results in the account's currency.
7. Signals from the member's broker prices: today every bot reads ONE Exness feed (owl_chart_feed) - per-broker feed or measured proof the gap is negligible.

## Before public
8. Data-only terminal per broker (downloads/tests never through a live terminal).
9. Tests on the member's own broker, labelled "Testé sur <courtier>" (precision plan step 5).
10. Commission accounts: costs in bot, bench and displayed results.
11. Health monitoring per broker (connection, terminal, feed freshness) with alerts.
12. Pilot: free demo at one other broker, end to end for 1-2 weeks, before any real member.

## After launch
13. Accuracy check per broker at ~40 real trades (synchronised replay, as Valère's) shown on the page.
14. "Le direct comparé au test" card per robot.
15. Automatic re-run of every test when the bench changes; results stamped with data + version.

Order: 1 -> 2-6 (one broker-details layer) -> 7 -> 12 pilot -> rest.

## Status 2026-10-16 (evening)
- 1 DONE: live/broker_profile.py readiness check; workers write nest_data/<uid>.broker.json every 6 h; the main bot refuses new entries while a blocking check fails.
- 2 DONE: `find_btc` knows BTCUSD / BTCUSDm / BTCUSD.x / "Bitcoin" (FOREX.com); the bot and the worker resolve the name at start when the usual one is missing. Log line `COURTIER: <server> | symbole <name> | horloge UTC+N h | execution IOC/FOK`.
- 3 and 6 are GATES, not code: a broker whose Bitcoin is not 1 lot = 1 BTC = $1/point, or whose account is not USD / hedging, gets a red verdict at sign-up and the bot's gate stays shut. Sizing in other contracts or currencies is not built on purpose (no such member yet).
- 4 DONE: `clock_offset_s` measured on the symbol's tick at start; `deals_utc` shifts history windows into broker time and deal times back to UTC (bot + worker). Verified on the fake UTC+3 broker in test_broker_profile.py (12/12) and live on Exness (offset 0, demo bot restart 14:43 UTC).
- 5 DONE: `pick_fill` - IOC where allowed, else FOK, else RETURN; the main bot's four order_send calls use it (FOREX.com = FOK only).
- Sign-up (new, owner "fastest way to say no"): broker book `live/broker_book.json` + shared probe terminal `C:\NestTerminals\probe` + verdict card (green / orange / red / unknown) BEFORE any terminal is built; red builds nothing. Cost curve `live/lab/spread_curve.json` from `study/spread_whatif.py` pending (runs after the market tests).
- 12 PILOT: FOREX.com demo 22319196 (USD, hedging, 1:100): Bitcoin = "Bitcoin", sizing OK, FOK only, clock UTC+3, min stop $0.50, history 3 days M1 / 7 months H1, SPREAD FIXED $40 (Exness Pro $4.48). Verdict waits for the cost curve; expected red.
- 7 (per-broker feed) NEXT: one price-only terminal per broker (a demo you own, else the first automatic member's terminal), every signal/chart/robot decision read on that broker's prices, label "Prix <courtier>" wherever a price is shown; until then Exness signals carry the line "Prix Exness. Vérifiez le niveau sur votre plateforme."
