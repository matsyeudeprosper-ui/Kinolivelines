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
