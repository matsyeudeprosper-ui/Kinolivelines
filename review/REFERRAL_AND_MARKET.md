# Parrainage and La place des robots (2026-10-17)

Owner: "pay the referrer a portion of the referred person's monthly payment, in subscription time, each month as
long as the friend keeps paying; make sure we don't lose money" and "go straight for the marketplace".

## One wallet, spent as time only
`live/owl_wallet.py` keeps a cagnotte per member in dollars. It is credited only from money the nest has
actually received, and it is spent only as subscription time (or a robot subscription inside the app). Nobody
is paid cash. Two sources:

| Event (confirmed) | Who is credited | How much |
|---|---|---|
| A referred member pays Signal ($29) or Strategie ($49) in crypto | the referrer | 20 % ($5.80 / $9.80) |
| A referred member's Automatique month is settled with the owner (code) | the referrer | 20 % of `family_usd` (nest_config, default $60 -> $12) |
| A follower pays a robot subscription ($5-$49/month) | the robot's creator | 70 % |

Spending: "Utiliser ma cagnotte" adds floor(usd / daily price of the member's CURRENT package) days (Signal
$0.97/day, Strategie $1.63/day, Automatique `family_usd`/30). A cagnotte can also pay a robot subscription in
full. Brake: at most 10 credited friends per referrer per calendar month.

## Why the nest cannot lose money on it
- Every credit is a fraction (20 % or 70 %) of a payment already received; the nest keeps 80 % / 30 % in cash.
- A credit is spent as time on a product whose marginal cost is ~0 (Signal, Strategie: app only) or the share of
  a VPS terminal (Automatique, already capped at 50). The only real cost is the revenue the referrer would have
  paid for those days: a referrer who brings one Signal friend earns 6 days (= $5.80) while the nest gains $29
  that month and every month the friend stays; break-even is 1 friend-month for every 5 referrer-months of
  Signal, i.e. the nest wins unless a referrer's friends churn in under a fifth of a month.
- Robot subscriptions: the follower pays $5-$49, the creator earns 70 % as time, the nest keeps 30 % cash and the
  follower's own Automatique fee. A creator cannot subscribe to their own robot (no self-credit), referral
  credit does not apply to robot payments, and a paused robot takes no new subscriptions.
- Nothing is granted on a pending or unverified payment (the NOWPayments IPN signature check stays the gate).

## The place (`live/owl_market.py`, page `/<token>/place`)
- Publish: creator or owner; robot tested, 42-day Bitcoin test on real ticks positive; alias (author name shown,
  never the member's name), one sentence, price (free or $5-$49), "others may start from my recipe".
- Follow: Automatique members only (a robot needs an account to run on); free -> the switch right away;
  paid -> the cagnotte if it covers the month, else a NOWPayments invoice (order "uid|robot:rid|ts"); after the
  payment, the switch asks the member's password like any robot change.
- Month end: the notifier switches the account back to the Owl and tells the member; a renewal re-subscribes.
- Pause: a listing whose latest test is no longer positive is paused for new followers; existing followers finish
  their month and are told.
- Creator side: "Mes robots sur la place": followers, earnings, pause state; the cagnotte in Parrainage.
