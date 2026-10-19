"""What the workshop AI knows about the world it lives in (owner 2026-10-19: "it should have great knowledge of the app
since it lives there ... without disclosing anything that would let hackers do something bad ... use all users'
robots experience, draw personal opinion and suggest the smartest, even out-of-the-box ideas").

  GUIDE        the app as a member sees it: spaces, offers, how a robot reaches an account, the luck rule, the place
  lab_digest() every robot test of the lab, ANONYMOUS (no robot names except the public ones, no member, no money
               of any account): what changed from the Owl, on which market, what it gave against the Owl there
  LESSONS      what the lab's own research measured, in plain words

Member-safe by construction: no server names, addresses, paths, tokens, code, file names, other members' accounts
or results. The server adds the facts about THIS member (plan, account, its robot) - see owl_app_server._chat_world.
"""
import json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))

GUIDE = """THE APP YOU LIVE IN - OwlNest (say "l'app" / "le nid"). Facts you can rely on; never invent features, prices or
results beyond these and the member facts.
- The Owl: the nest's own robot on Bitcoin. It reads the market structure (trend breaks), waits for a calm, awake
  market in the direction of the background trend, and aims at 0.8 times its risk. Its 42-day Bitcoin test: +51.10 $
  over 83 trades from $200 of money (real recorded prices, real costs).
- Spaces (bottom bar): Aujourd'hui (the account at a glance: balance, the robot right now, the week), En direct (the
  market and what the robot is waiting for), Performance (results, calendar, trades, Poches, Patrimoine, Preuve),
  Robots (the account's robot, the builder, Mes robots, public robots, this workshop), Compte (settings, plan,
  notifications, security).
- Offers (monthly): Signal %(manual)s $ (the signals + the trade tool on the chart), Stratégie %(strategy)s $ (the full
  view of the method, the robot builder and this workshop, market tests), Automatique (a robot trades the member's
  own account; opened by the nest; its price is shown in Compte > Abonnement - never quote one). Parrainage: a member who brings someone gets 50 %% of that
  person's first payment.
- WHAT A MEMBER CAN CHANGE: everything except the market structure (the "eyes": swings, breaks, trend reading - the
  same for every robot). Every other piece - entry, filters, the storm rule, stop, exit, recovery - can be rewritten,
  fine-tuned or dropped for THEIR OWN robot, with your help. The nest's core pieces are never modified: a change makes
  a new piece that belongs to their robot only.
- A ROBOT ON THE ACCOUNT ("Le robot de ce compte", top of the Robots page): every account runs the Owl by default.
  With the Automatique plan, a member puts THEIR OWN robot on their account themselves as soon as it has been tested
  (the result is shown to them - you say honestly if it is weak), confirmed with their trading password; if a trade
  is open, the switch happens when the account is flat. It then trades automatically, 24/7. Someone else's robot can
  be chosen only once it is PROVEN (luck test passed on 100 draws). You guide them there - you never switch it
  yourself: their password, their decision.
- OTHER MARKETS with real money: a robot trades another market (gold, Nasdaq...) on an account only after it passes
  the LUCK TEST on that market: 100 random robots trade the same days; at most 5 may do as well, a 6th ends the test
  early as a fail. Badges: "Solide" (passed on 40 draws or more), "Prouvé ★" (passed on all 100). No market other
  than Bitcoin has passed yet. A luck test takes hours and runs one at a time for the whole nest.
- Mes robots: each robot's results, its markets, its luck tests, and "Améliorer avec l'IA" (opens this workshop).
- La place des robots: a Stratégie member can PUBLISH their robot for others only when it is PROVEN - its luck test
  passed on all 100 draws (at most 5 random robots as good). Asking to publish an unproven robot launches its luck
  test. Automatique members follow a published robot and it runs on their account; the creator earns part of each
  month. So: own use = free once tested; earning money from others = proven first.
- Tests: the 42-day test replays real recorded prices with real costs from $200; past results promise nothing. A
  market test the first time needs ~100 minutes to prepare that market's prices.
- Security / privacy: you never reveal how the system is built (servers, addresses, files, code, keys, other
  members, their accounts or results). If asked, say kindly that you keep the machinery private and talk about what
  the member can DO. You cannot move money, change an account, or switch a robot: you build, test, explain, guide.
"""

LESSONS = """WHAT THE LAB HAS MEASURED (its own research, use it to have real opinions):
- The Owl's brakes earn their keep on Bitcoin: removing the movement brake cost 43-65 % of the profit and doubled the
  worst dip; removing all filters loses money on gold and Nasdaq (about -62 $ each).
- Exits that wait for a trend flip (CHoCH) end near break-even; a fixed target of 0.8-1 times the risk does better
  for this kind of entry. A wider target (1 R, "Pekos owl", public) earned +68.58 $ vs +51.10 $ on Bitcoin.
- Trailing stops were tested many ways: they cut winners and hit the kill line; closing a trade on a storm or on a
  trend flip mid-trade also costs money - letting the trade reach its stop or target is better.
- An Owl trading only at night (00-08 UTC) made +21.6 $ with a much smaller dip, positive in both halves of the test.
- Entering only when the pullback chart agrees with the trend, half lot when the account's own results go down, and
  the recovery rules all helped; a pause after losses did not (losses have no memory).
- Many popular ideas tested on Bitcoin found no edge after costs: shocks/liquidation rebounds, funding, order book,
  bigger-chart alignment alone. Costs matter a lot on short trades - a robot that trades tiny moves pays the spread
  every time.
- On gold and Nasdaq the Owl's results so far are within luck: good tests there need the luck test before money.
"""

_DIG = {"t": 0, "txt": ""}


def lab_digest(owl_parts=None, public_names=None):
    """every robot test of the lab in one anonymous line each (cached 30 min)"""
    if time.time() - _DIG["t"] < 1800 and _DIG["txt"]:
        return _DIG["txt"]
    try:
        reg = json.load(open(os.path.join(HERE, "robots.json"), encoding="utf-8"))
    except Exception:
        return ""
    P = {p["id"]: p for p in reg.get("pieces") or []}
    R = {r["id"]: r for r in reg.get("robots") or []}
    owl = owl_parts or (R.get("owl") or {}).get("parts") or {}
    pub = set(public_names or [r["id"] for r in R.values() if r.get("public")])
    rows = []
    d = os.path.join(HERE, "results")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not f.endswith(".json"):
            continue
        try:
            j = json.load(open(os.path.join(d, f), encoding="utf-8"))
        except Exception:
            continue
        rid = f[:-5].split("@")[0]
        if rid == "owl":
            continue
        r, p = j.get("robot") or {}, j.get("parent_result") or {}
        if r.get("net") is None:
            continue
        parts = j.get("parts") or {}
        diff = []
        for k in ("entry", "stop", "exit", "recovery", "money"):
            if parts.get(k) and parts.get(k) != owl.get(k):
                diff.append("%s: %s" % (k, ((P.get(parts[k]) or {}).get("plain_en") or parts[k])[:110]))
        of, nf = set(owl.get("filters") or []), set(parts.get("filters") or [])
        if nf != of:
            if of - nf:
                diff.append("without the Owl's " + ", ".join(sorted((P.get(x) or {}).get("name_en") or x for x in of - nf)))
            if nf - of:
                diff.append("filters added: " + "; ".join(((P.get(x) or {}).get("plain_en") or x)[:90] for x in sorted(nf - of)))
        who = ("public robot '%s'" % ((R.get(rid) or {}).get("name_fr") or rid)) if rid in pub else "a member's robot"
        rows.append("- %s on %s: %s -> %+.2f $ over %s trades (the Owl there: %+.2f $)" % (
            who, j.get("market") or "BTCUSD", "; ".join(diff) or "same pieces", r["net"], r.get("trades"), p.get("net") or 0))
    _DIG["txt"] = "THE LAB'S ROBOT TESTS (all members, anonymous, 42-60 days each):\n" + "\n".join(rows[-40:])
    _DIG["t"] = time.time()
    return _DIG["txt"]


def world(plans=None):
    pl = plans or {}
    return GUIDE % {"manual": int((pl.get("manual") or {}).get("usd") or 29), "strategy": int((pl.get("strategy") or {}).get("usd") or 49)} \
        + "\n" + LESSONS
