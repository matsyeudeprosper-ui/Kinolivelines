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
| A follower pays a robot subscription ($5-$49/month, crypto through our payment system) | the robot's creator, in REAL MONEY (earnings, apart from the cagnotte) | 70 %, paid out by the owner in USDT once >= $50 |

Spending: "Utiliser ma cagnotte" adds floor(usd / daily price of the member's CURRENT package) days (Signal
$0.97/day, Strategie $1.63/day, Automatique `family_usd`/30). The cagnotte buys days and nothing else (owner
2026-10-17: referral = time, robots = money). Brake: at most 10 credited friends per referrer per calendar month.

Creators: 70 % of each robot month is EARNINGS in dollars (`owl_wallet.earnings`), never spendable as time; the
creator saves a USDT address in the app; from $50 the owner pays by hand once a month (the owner's place page
lists who is due, "J'ai paye" records the transfer and tells the creator). Why through our payment system and
not creator-to-follower: the robot gate (positive real-tick test, pause when negative) and the 30 % only exist
if the month is paid where the robot is switched; a direct payment would bypass both and leave disputes to us.

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
  paid -> a NOWPayments invoice (order "uid|robot:rid|ts"); after the
  payment, the switch asks the member's password like any robot change.
- Month end: the notifier switches the account back to the Owl and tells the member; a renewal re-subscribes.
- Pause: a listing whose latest test is no longer positive is paused for new followers; existing followers finish
  their month and are told.
- Creator side: "Mes robots sur la place": followers, earnings, pause state; the cagnotte in Parrainage.

## 2026-10-17 — Who may do what on the Robots page and the place (owner: "accessible by all, paid actions by the right account")

Reading is free for every account, the demo included. Every paid action is checked on the server at the POST, and the
page shows the door that opens it instead of hiding the feature.

| Action | Démo (public) | Signal $29 | Automatique | Stratégie $49 | Stratégie + Automatique | Owner |
|---|---|---|---|---|---|---|
| See the Owl, public robots, their pieces in plain words, 42-day results, test zone results, the place catalogue | yes | yes | yes | yes | yes | yes |
| Change the robot of MY account (free robots) | – (door: Automatique) | – (door: Automatique) | yes (password) | – (door: Automatique) | yes | yes |
| Follow a PAID robot from the place (crypto month, 70 % to the creator) | – | – | yes | – | yes | yes |
| Create / edit / delete a robot, make pieces, explain to the AI, chart studio | – (door: Stratégie) | – (door: Stratégie) | – (door: Stratégie) | yes | yes | yes |
| Launch market tests (zone de test) | – | – | – | yes | yes | yes |
| Publish on the place, set a price, earn 70 % | – | – | – | yes | yes | yes |
| Plug a robot on ANOTHER account, pay creators | – | – | – | – | – | yes |

How it is enforced: `robots_data` returns the full page to everyone but strips piece rules, edit rights and the plug
list for readers (`builder.can_create=false`, `tier`); POSTs `robot_*`, `piece_*`, `ai_*`, `studio_*`, `robot_test*`
answer `{"err":"strategy"}` without Stratégie; `account_robot_set` needs a trading account (Automatique);
`place_follow` needs Automatique and, for a paid robot, a confirmed crypto invoice; `place_publish` needs Stratégie.

## 2026-10-17 — PAY ONCE (owner "Go")

The owner asked whether a member should pay the plan AND a robot month. Decision: no. Every robot on the place is
INCLUDED in the plan. The creator of the robot a member runs gets CREATOR_SHARE = 30 % of that member's confirmed
plan payment (crypto IPN or a code settled with the owner, valued at family_usd), in real money, paid in USDT from
$50 as before. Running the Owl or one of the owner's robots: the nest keeps 100 %. Referral stays time-only.

Mechanics: owl_wallet.on_plan_share (kind "share"), called by owl_app_server._creator_share from the two payment
confirmation points (_ref_family_credit for codes, the NOWPayments IPN for plans). Subscriptions are OPEN-ENDED
(owl_market start_sub -> "open": true, no month end, no reminder); a member stops or switches whenever they want.
No invoice is ever created for a robot; the price picker is gone; listings carry price 0; the "robot:" IPN branch
stays only for history. Later, with several followed member robots, the add-on plan ("Automatique Plus") can fund
the creator share instead of the base plan — a configuration change, not a rebuild.

### Share BY TIME (owner, same day: "what if they run it five minutes?")
The 30 % is NOT credited at payment time. It accrues every tick (~10 min, _market_tick -> _creator_accrue) while the
member's plan is active and the creator's robot is attached: share = family_usd / 30 / 86400 * seconds * 0.30.
Fractions of a cent wait in cash_frac; whole cents go to cash and to one history line per robot, follower and day.
Five minutes earn ~$0.002 (nothing visible); a full day on a $60 plan earns $0.60; a full month the full $18.
Switching back and forth simply splits the time between creators. The Owl and the owner's robots accrue nothing.

### The nest never pays what it did not receive (owner: "I'm not spending money in this model, right?")
Checked against the live entitlements on 2026-10-17: every Automatique member is on the grandfathered first period
(no payment recorded). Rule: ent_grant now records paid_usd / paid_days on each Automatique grant; the share accrues
ONLY on that money: crypto = the amount paid; code = the package price (the owner sells codes; a code given away is
the owner's conscious gift); wallet days, welcome days, owner grants, the grandfathered period = 0 -> no share.
Worst case per member and month = 30 % of what that member paid, and only for the time they ran a member's robot.
The Owl and the owner's robots accrue nothing, so today the exposure is exactly $0.

## 2026-10-17 — Referral audit (owner: "best model, not losing money in whatever case, solid")

Money paths checked, each with a test in review/test_market_wallet.py (49 checks, all pass):
* A referred member's confirmed payment credits the referrer 20 % as DAYS (never cash). Crypto = the amount paid;
  code = the package price; an OFFERED code = 0 (fixed today: before, a free Automatique code still credited $12
  of days). Wallet days, welcome days and owner grants credit nothing.
* Self-referral is refused; a public account has no code; at most 10 friends credited per referrer per month.
* The cagnotte converts at the member's own package price, cannot go negative, never pays cash, never touches
  the creator ledger.
* The 7 welcome days cost service time only, once per referred member.
* Worst case per referred payment: 20 % in days + 30 % creator share (only while running a member robot) =
  the nest keeps >= 50 % cash-equivalent, >= 70 % in cash. There is no path that credits anything on money the
  nest did not receive. A member who refers their own second account gets a 20 % discount in days - the cap
  (10 friends/month) and the fact that the nest still receives 80 % make it harmless.
* Signal / Strategie codes now credit the referrer like a crypto payment would (they did not before; no loss,
  just inconsistency). IPN replays are rejected by payment_id; signatures are verified or cross-checked with
  NOWPayments.
Why it is the right model here: paid in time, so it is never a cash liability; proportional to real revenue; capped;
and it rewards the referrer every month the friend stays, which is what the owner asked for.

## 2026-10-17 evening — Referral becomes REAL MONEY: 50 % of the friend's FIRST paid month (owner changed his mind)
"To really motivate people, even those who don't take signals": the referrer gets 50 % of the referred member's first
confirmed payment (any package; a code month at package price; an offered code = 0), in the cash ledger (kind
"referral"), paid out in USDT by the owner from $100 (creator money keeps its $50 door; one balance, owl_wallet._due).
Later months of the same friend credit nothing. 10 new friends a month max. The friend keeps the 7 welcome days.
The nest keeps 50 % of that first month and 100 % of every later month: no path pays more than received.
A campaign page /<tok>/parrainage (owl_referral_page.html, referral_data) shows code, share, friends, earned, the
$100 progress and payouts; any account can refer, paid or not (an unpaid sign-up has a code; the public demo is
told to open an account). A quiet nudge on the home appears when the account is above its start balance, at most
once every 14 days, dismissible. The old days-cagnotte stays readable for anyone who had one (none today).

## 2026-10-17 night — Creators / YouTubers programme (owner)
A member applies on the Parrainage page with their channel and the video that mentions OwlNest (a tick: no gains
promised, the demo shown, Signal/Stratégie only - Automatique is on invitation and must not be advertised). The owner
sees the queue on his own Parrainage page and approves or refuses with a button (push both ways). Approved: the
SAME code now pays INF_PCT = 30 % of EVERY payment of the creator's users, as long as they pay (kind "influencer"),
instead of 50 % once. One code, one rule, never both: the worst month pays out 30 % creator-programme + 30 % robot
share = 60 %, the nest keeps at least 40 %; fake users cost the fraudster 70 % of each payment. Refused: back to the
one-time rule. Payout from $100 with the referral money. Dashboard for an approved creator: active subscribers
(paid in the last 35 days), this month, in all, 6-month bars, links to the video and channel. Files:
live/owl_influencers.py (+ owl_influencers.json, git-ignored). Tests: review/test_market_wallet.py 66 checks.
Option kept in one constant for later: limit the 30 % to the first N months of each user.
Update (same night): the 30 % is limited to the first 12 PAID MONTHS of each user (owl_wallet.INF_MONTHS); the creator
has their own page /<tok>/createur (owl_creator_page.html): status badge, link, KPIs (active subscribers, expected next
month if all renew, this month, in all), 6-month chart, payout ring, subscribers with months paid / months left bars,
the approved video and channel, the rules; the Parrainage page only shows a status-aware door to it. 68 checks pass.
Proof on any platform (owner, same night): the application names the platform (YouTube, TikTok, Instagram,
Facebook, Telegram, blog/site, podcast, other) and ONE link to the publication that mentions OwlNest and shows the
creator's link or code; the page/profile link is optional. Closed Telegram / Facebook groups: the invite link plus
a screenshot of the pinned message sent to the Owl on Telegram. The data is the final proof: sign-ups through the
link appear on the dashboard whether approved or not.

## 2026-10-17 late — Link traffic + automatic check (owner: "do we track traffic? approve without asking?")
Traffic: every visit to /offres?p=<code> is counted per code and per day (hits + daily uniques through a salted
hash, owl_ref_clicks.json, 90 days, no IP stored; rate-limited 30/10 min per address). The Parrainage page shows
"visiteurs 30 j"; the creator dashboard shows visitors 30 d / 7 d and the sign-ups-per-visitor rate.
Automatic check: on application the server fetches the publication (public hosts only - SSRF guard refuses private,
loopback, link-local, bare IPs and our own domain, which always shows the code) and looks for the member's code or
link. Found -> approved on the spot (review_note "auto : ..."), creator and owner told. Not found or unreadable ->
stays in the owner's queue with the reason, the link's visitors, sign-ups and paid counts, and a "re-vérifier"
button. Tests: 80 checks (review/test_market_wallet.py).
Publications (owner, same night): an approved creator adds new publications from the dashboard ("Vos publications",
platform + link); each is checked automatically on its own (✓ code trouvé / ✗ reason) without touching the status;
duplicates refused; the channel/page link stays optional and informational - the publication link is the proof.
