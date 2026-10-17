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
- 7 BUILT (2026-10-16 evening, commit below): `live/owl_chart_broker.py <key>` = the BTC feed's own code on another broker's price-only account (owner's demo from owl_secrets, else a member there), outputs `live/chart_broker/<key>[_htf|_nerv|_pbchain].json` + meta.json, candle/tick times shifted back to UTC (FOREX.com +3 h). `broker_book.key_of / feed_file / feed_fresh`; the readiness check's "feed" passes when that broker's feed is alive. Readers: app chart/htf/home card/Signal price via `member_feed(user)` + label "Prix FOREX.com" (chart header, `feed_label`); the generic member bot reads CHART_F/HTF_F/PBC_F from its broker's feed and pulls its own candles through `rates_utc`. The Exness feed no longer falls back to a non-Exness member terminal. Pilot feed running: forexcomglobal (symbol Bitcoin). NOT yet: signals/notifier per broker for Signal members (they get Exness signals + the "Prix Exness" line), auto-start of broker feeds by the provisioner/restart.ps1.

## 2026-10-17 — Markets at the member's broker (owner: "are we assuming the user will trade only BTC?")
Real money is Bitcoin-only today (no other market has passed the luck check), so the verdict card's Bitcoin check
is the right gate. Groundwork for the day that changes:
* broker_profile.NEST_MARKETS (Or, Nasdaq 100, Dow Jones, Pétrole US) + find_market(): name prefixes, then
  FOREX.com-style names ("Gold", "US Tech 100"), then the description; gold in euro and untradeable symbols are
  ignored. profile() now carries "markets" (name, spread, contract) - the sign-up probe and the 6-hourly member
  profile (nest_data/<uid>.broker.json) both get it. On the idle Exness demo all four are found (XAUUSDm, USTECm,
  US30m, USOILm).
* broker_book.verdict carries "markets" [{key,label,found,name}]; the card shows "Autres marchés · Or ✓, ... ·
  Pétrole US ✗" with the sentence that only Bitcoin trades for real.
* account_robot_set refuses a robot whose "market" (robots.json, default BTCUSD) is absent from the member's
  broker profile ({"err":"no_market"}); every robot is BTCUSD today so nothing changes for anyone.
Tests: live/test_broker_profile.py (markets block) - all pass.

## 2026-10-17 — Broker chooser BEFORE any login (owner: "we already know; suggest brokers that will work")
The Automatique sheet opens with "Chez quel courtier est votre compte ?": one chip per brand of the broker book
(GET /brokers: brand, zone against the current cost curve, spread, servers; Exness first and "recommandé") plus
"Un autre courtier". A red brand hides the fields and shows the three doors right there (Signal / an Exness
account / write to the Owl) with "Vérifier quand même mon compte" for the stubborn; a green or orange brand shows
the fields with the brand's server as placeholder; "another broker" says the account will be read in a minute.
So nobody at a known-bad broker types a login. The verdict card's robot list is now a two-column comparison
("à Exness" / "chez X", gagne / perd) placed BEFORE the doors on a red card. Hints and reasons say "écart", not
"coût par trade". Verified headless: chips 3, doors 3, fields hidden on FOREX.com; fields shown on Exness.

## 2026-10-17 — Automatique is invitation-only on the public page (owner "Go", legal caution)
Running trades on members' accounts from our server is the exposed part (automatic execution = portfolio
management under EU rules); the public one-click sign-up was the exposure, not the member count. Decision: the
Automatique card stays on /offres (so the nest is understood) but its button is "Sur invitation · écrire au Owl"
(Telegram, prefilled text). The Automatique sheet opens only from an invitation link /offres?inv=<code> carrying a
valid, unused Automatique activation code; the owner's code sheet now writes that link into the message for
Automatique codes. Signal and Stratégie keep the public sign-up. Everything behind the sheet (probe, broker
chooser, verdict card) is unchanged. Longer-term safe model written in the chat of 2026-10-17: the robot as an
.ex5 the member runs on their own terminal/VPS, the nest reading results with the investor (read-only) password.
