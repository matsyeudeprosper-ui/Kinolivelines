# Offers audit — promises vs. delivery (2026-10-17)

Owner: "review that all offers during subscription are provided; anything delivered we are not listing?
should creating and selling a robot be a separate package?"

Method: each bullet of the three cards on /offres against the gate that delivers it in owl_app_server.py
(`has(uid, pkg)`, `chart_view`, the builder payload, the notifier).

## Signal — $29 / 30 days (app-only)

| Promise on the card | Delivered by | Verdict |
|---|---|---|
| Every robot decision live: what it sees, why it enters, why it waits | En direct + the brain log, `signals` route (manual only) | kept |
| "The same screen as automatic accounts" (old info text) | `chart_view` = obs for app-only Signal: no structure, no next-break level (owner 2026-10-05, pre-alert verdict) | **overstated** → info text reworded: the dashboard, the entry levels come with the alert |
| An alert on the phone at each entry | `owl_push_notifier.signal_members()` → every app-only member with manual_until > now | kept |
| No broker account to give; name your broker for levels at its prices | app-only record; `member_feed` per broker feed when we have one (FOREX.com) | kept ("when we have them") |
| For the robot to do it for you: Automatique | invitation flow | kept |
| *(unlisted)* Robots page and the place, to read; referral 7 days + 20 % in days; patterns / market-hours / compare pages | robots_data reader payload, /place, owl_wallet | **added** as one bullet |

## Stratégie — $49 / 30 days (app-only, includes Signal)

| Promise | Delivered by | Verdict |
|---|---|---|
| The workshop: a robot from simple pieces, no code | builder `can_create`, AI build, chart studio | kept |
| The test on real prices: 42 days of Bitcoin tick by tick, then gold and Nasdaq, luck control | robot_test, robot_test_markets, random control | kept |
| The place: publish it, every member running your robot earns you money (30 %, USDT from $50) | owl_market.publish, owl_wallet.accrue_share, payouts | kept (text fixed today, was still "70 % in days") |
| Full chart and the method in plain words; Signal included | chart_view full; `has(strategy)` implies manual | kept |
| *(unlisted)* Les coulisses: all strategies, verdicts, the AI team | strategies_data / team_data (strategy gate) | **added** to bullet 4 |
| *(not said)* Stratégie alone cannot run a robot on an account | account_robot_set needs a trading account | **added**: "to run it on your own account: Automatique, by invitation" |

Separate package for building + selling? **No.** It is the reason to pay $49 over $29; a fourth package would
split the smallest paying group and add a choice nobody asked for. It stays inside Stratégie, now worded as money,
not days, and with the Automatique dependency stated.

## Automatique — Famille, by invitation

| Promise | Delivered by | Verdict |
|---|---|---|
| The robot places orders on your MT5 account, day and night, from our server | structure_bos_bot per account | kept |
| Its rules, brakes, recovery after a loss | owl_packages money management, brakes | kept |
| Fixed price each month, settled with the Owl; code via Telegram | ent_grant, codes, invitation link | kept |
| *(unlisted)* Any robot of your choice, the Owl or a place robot, included; switch any time | acct_robot_block / account_robot_set, pay-once | **added** |
| *(unlisted)* Patrimoine, poches, results day by day, alerts | wealth, performance, notifier | **added** |

## Common to all, now said once on the Signal card and in Compte
Referral (7 free days for the friend, 20 % of their payments in days for you), the Robots page and the place
readable by every account.

Nothing promised is missing in the app; two card texts overstated or lagged (Signal "same screen", Stratégie
"70 % in days") and are fixed; five delivered features were unlisted and are now on the cards. English
dictionary updated for the new lines.
