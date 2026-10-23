"""owl_market.py - "La place des robots" (owner 2026-10-17: "go straight for the marketplace, build it correctly").

A creator (a Strategie member, or the owner) PUBLISHES a robot they built: a plain name, a sentence in simple
words, a monthly price (free, or $5 to $49), and whether others may start from its recipe. A FOLLOWER (an
Automatique member) SUBSCRIBES: the robot then runs on their own account, through the same switch as
"Le robot de ce compte". Each confirmed month pays the creator CREATOR_PCT into their cagnotte (owl_wallet).

The gate never moves: a robot can be published only when its 42-day Bitcoin test on real ticks is positive
(live/robots/results/<rid>.json), and the sign-up verdict card already says which published robots pay at a
member's broker. A listing whose latest test turns negative is PAUSED for new followers (existing followers keep
their robot until their month ends; they are told).

Files: live/owl_market.json
  {"listings": {rid: {"alias", "blurb", "price_usd", "open_recipe", "by_uid", "published_at", "hidden", "paused"}},
   "subs": {uid: {"rid", "price_usd", "started", "until", "paid_via", "auto"}},
   "log": [...]}
"""
import json, os, time, threading

DIR = os.path.dirname(os.path.abspath(__file__))
MARKET = os.path.join(DIR, "owl_market.json")
ROBOTS = os.path.join(DIR, "robots", "robots.json")
RESULTS = os.path.join(DIR, "robots", "results")
PRICE_MIN, PRICE_MAX = 5.0, 49.0
SUB_DAYS = 30
_LOCK = threading.Lock()


def _load(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def _save(p, obj):
    tmp = p + ".%d.tmp" % os.getpid()
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def data():
    d = _load(MARKET, {}) or {}
    d.setdefault("listings", {}); d.setdefault("subs", {}); d.setdefault("log", [])
    return d


def robots():
    r = _load(ROBOTS, {}) or {}
    return {x["id"]: x for x in (r.get("robots") or [])}


def result_of(rid):
    """the robot's own Bitcoin test (42 days, every recorded tick) or None"""
    r = _load(os.path.join(RESULTS, rid + ".json"), None)
    if rid == "owl" and not r:
        p = _load(os.path.join(DIR, "lab", "proof_current.json"), None)        # the Owl's proof is its test
        if p and isinstance(p.get("net"), (int, float)):
            return {"net": p["net"], "trades": p.get("trades"), "win_rate": p.get("win_rate"), "mtm_dd": p.get("mtm_dd"), "days": p.get("days", 42),
                    "balance": p.get("balance"), "window_utc": p.get("window_utc"), "tested_at": p.get("generated_at")}
        return None
    if not r:
        return None
    R = r.get("robot") or {}
    return {"net": R.get("net"), "trades": R.get("trades"), "wins": R.get("wins"), "win_rate": R.get("win_rate"), "mtm_dd": R.get("mtm_dd"), "cc_dd": R.get("cc_dd"),
            "profit_factor": R.get("profit_factor"), "first_half": R.get("first_half"), "later_half": R.get("later_half"), "best": R.get("best"), "worst": R.get("worst"),
            "max_loss_streak": R.get("max_loss_streak"), "hold_median_min": R.get("hold_median_min"), "balance": r.get("balance"),
            "days": r.get("days"), "tested_at": r.get("generated_at"), "window_utc": r.get("window_utc"), "curve": (R.get("curve") or [])[-120:]}


def markets_of(rid):
    """other markets where this robot's tick test passed the real-money rule"""
    out = []
    try:
        names = {}
        try:
            import owl_chart_multi as _CM
            names = {s: fr for s, fr, en in _CM.SYMS}
        except Exception:
            pass
        hold = _load(os.path.join(DIR, "market_hold.json"), {}) or {}
        for f in sorted(os.listdir(RESULTS)):
            if f.startswith(rid + "@") and f.endswith(".json"):
                sym = f[len(rid) + 1:-5]
                res = _load(os.path.join(RESULTS, f), {}) or {}
                net = float((res.get("robot") or {}).get("net") or 0)
                ctl = _load(os.path.join(os.path.dirname(DIR), "study", "random_control_%s_%s.json" % (rid, sym)), None)
                pct = float(ctl["percentile"]) if ctl and ctl.get("percentile") is not None else None
                held = ("%s@%s" % (rid, sym)) in hold
                out.append({"sym": sym, "name": names.get(sym, sym), "net": round(net, 2), "pct": pct, "held": held,
                            "pays": net > 0 and pct is not None and pct >= 95 and int((ctl or {}).get("seeds") or 0) >= 100 and not held})
    except Exception:
        pass
    return out


def proven(rid, sym="BTCUSD"):
    """2026-10-19 (owner): the place is for robots that passed the luck test on all 100 draws (at most 5 random robots
    as good) - study/random_control_<rid>_<SYM>.json, written by study/random_control_market.py"""
    c = _load(os.path.join(os.path.dirname(DIR), "study", "random_control_%s_%s.json" % (rid, sym)), {})
    if c.get("percentile") is None:
        return False
    rn = float((c.get("real") or {}).get("net") or 0)
    beats = c["beats"] if c.get("beats") is not None else sum(1 for x in c.get("nets") or [] if x >= rn)
    return int(c.get("seeds") or 0) >= 100 and beats <= 5


def best_result(rid):
    """2026-10-22 (owner: "our new robot winner is not public"): the robot's best test on a market where it PASSED the
    100-draw luck test - Bitcoin, or the market it was built for (a gold robot has no Bitcoin test). Proven markets only;
    the most money per 30 days wins. The result dict carries "sym". None when no market is proven."""
    best = None
    btc = result_of(rid)
    if btc and btc.get("net") is not None and proven(rid, "BTCUSD"):
        best = dict(btc, sym="BTCUSD")
    for f in os.listdir(RESULTS) if os.path.isdir(RESULTS) else []:
        if not (f.startswith(rid + "@") and f.endswith(".json")):
            continue
        sym = f[len(rid) + 1:-5]
        if not proven(rid, sym):
            continue
        r = _load(os.path.join(RESULTS, f), None) or {}
        R = r.get("robot") or {}
        if R.get("net") is None:
            continue
        cand = {"net": R.get("net"), "trades": R.get("trades"), "wins": R.get("wins"), "win_rate": R.get("win_rate"), "mtm_dd": R.get("mtm_dd"),
                "cc_dd": R.get("cc_dd"), "profit_factor": R.get("profit_factor"), "first_half": R.get("first_half"), "later_half": R.get("later_half"),
                "best": R.get("best"), "worst": R.get("worst"), "max_loss_streak": R.get("max_loss_streak"), "hold_median_min": R.get("hold_median_min"),
                "balance": r.get("balance"), "days": r.get("days"), "tested_at": r.get("generated_at"), "window_utc": r.get("window_utc"),
                "curve": (R.get("curve") or [])[-120:], "sym": sym}
        p30 = lambda x: float(x.get("net") or 0) * 30.0 / float(x.get("days") or 42)
        if best is None or p30(cand) > p30(best):
            best = cand
    if best:                               # the proof the place shows: the luck test of that market
        c = _load(os.path.join(os.path.dirname(DIR), "study", "random_control_%s_%s.json" % (rid, best["sym"])), {}) or {}
        best.update(luck_pct=c.get("percentile"), luck_seeds=c.get("seeds"), luck_beats=c.get("beats"))
    return best


def any_result(rid):
    """the result to SHOW for a robot (proven or not): its best proven market, else its Bitcoin test, else the test on
    the market it was built for - a gold robot not yet proven still has a result (it said "pas encore testé")"""
    b = best_result(rid) or result_of(rid)
    if b:
        return b
    mk = str((robots().get(rid) or {}).get("market") or "").upper()
    r = _load(os.path.join(RESULTS, "%s@%s.json" % (rid, mk)), None) if mk else None
    R = (r or {}).get("robot") or {}
    if R.get("net") is None:
        return None
    return {"net": R.get("net"), "trades": R.get("trades"), "win_rate": R.get("win_rate"), "cc_dd": R.get("cc_dd"), "days": r.get("days"),
            "window_utc": r.get("window_utc"), "curve": (R.get("curve") or [])[-120:], "sym": mk}


def can_publish(rid, uid, is_admin=False):
    """(ok, why) - the creator (or the owner) may list a tested, positive robot"""
    R = robots().get(rid)
    if not R:
        return False, "robot inconnu"
    if not (is_admin or R.get("by_uid") == uid):
        return False, "pas votre robot"
    res = best_result(rid)                 # 2026-10-22: Bitcoin OR the market it passed its luck test on
    if not res:
        return False, "test de chance à réussir"
    if float(res["net"]) <= 0:
        return False, "test négatif (%.2f $)" % float(res["net"])
    return True, ""


def publish(rid, uid, alias, blurb, price_usd, open_recipe, is_admin=False):
    ok, why = can_publish(rid, uid, is_admin)
    if not ok:
        return {"ok": False, "err": why}
    price = 0.0          # 2026-10-17 (owner "Go"): pay once - every robot on the place is included in the plan; the
                         # creator is paid a share of each follower's plan payment (owl_wallet.CREATOR_SHARE)
    alias = str(alias or "").strip()[:24]
    blurb = str(blurb or "").strip()[:160]
    if len(alias) < 2:
        return {"ok": False, "err": "un nom d'auteur (2 lettres au moins)"}
    with _LOCK:
        d = data()
        cur = d["listings"].get(rid) or {}
        d["listings"][rid] = {"alias": alias, "blurb": blurb, "price_usd": round(price, 2), "open_recipe": bool(open_recipe),
                              "by_uid": cur.get("by_uid") or (robots().get(rid) or {}).get("by_uid") or uid,
                              "published_at": cur.get("published_at") or int(time.time()), "updated": int(time.time()),
                              "hidden": False, "paused": False}
        d["log"].append({"t": int(time.time()), "ev": "publish", "rid": rid, "uid": uid, "price": price})
        _save(MARKET, d)
    return {"ok": True}


def unpublish(rid, uid, is_admin=False):
    with _LOCK:
        d = data()
        L = d["listings"].get(rid)
        if not L:
            return {"ok": False, "err": "pas sur la place"}
        if not (is_admin or L.get("by_uid") == uid):
            return {"ok": False, "err": "pas votre robot"}
        L["hidden"] = True; L["updated"] = int(time.time())
        d["log"].append({"t": int(time.time()), "ev": "unpublish", "rid": rid, "uid": uid})
        _save(MARKET, d)
    return {"ok": True}


def refresh_pauses():
    """a listing whose latest Bitcoin test is no longer positive is paused for new followers (and unpaused when
    it comes back). Called by the notifier once an hour and by the page."""
    with _LOCK:
        d = data(); changed = False
        for rid, L in d["listings"].items():
            res = best_result(rid)
            bad = not res or res.get("net") is None or float(res["net"]) <= 0
            if bool(L.get("paused")) != bad:
                L["paused"] = bad; L["updated"] = int(time.time()); changed = True
                d["log"].append({"t": int(time.time()), "ev": "pause" if bad else "unpause", "rid": rid})
        if changed:
            _save(MARKET, d)


def _active(s):
    return bool(s) and (bool(s.get("open")) or float(s.get("until") or 0) > time.time())


def followers(rid):
    return [uid for uid, s in data()["subs"].items() if s.get("rid") == rid and _active(s)]


def sub_of(uid):
    s = data()["subs"].get(uid)
    return s if _active(s) else None


def listing(rid):
    return data()["listings"].get(rid)


def start_sub(uid, rid, usd, via):
    """the member runs this robot from now on (pay once: included in the plan, OPEN-ENDED until they stop or switch);
    a legacy paid month (usd > 0) still gets its 30 days. Returns the sub."""
    with _LOCK:
        d = data()
        cur = d["subs"].get(uid) or {}
        base = float(cur.get("until") or 0) if cur.get("rid") == rid else 0.0
        until = int(max(time.time(), base) + SUB_DAYS * 86400) if float(usd or 0) > 0 else 0
        d["subs"][uid] = {"rid": rid, "price_usd": round(float(usd), 2), "started": cur.get("started") if cur.get("rid") == rid else int(time.time()),
                          "until": until, "open": float(usd or 0) <= 0, "paid_via": via, "auto": False, "last_pay": int(time.time())}
        d["log"].append({"t": int(time.time()), "ev": "sub", "rid": rid, "uid": uid, "usd": usd, "via": via})
        _save(MARKET, d)
        return d["subs"][uid]


def stop_sub(uid):
    with _LOCK:
        d = data()
        s = d["subs"].pop(uid, None)
        if s:
            d["log"].append({"t": int(time.time()), "ev": "unsub", "rid": s.get("rid"), "uid": uid})
            _save(MARKET, d)
        return s


def expired_subs(grace_s=0):
    """[(uid, sub)] whose month ended (the notifier switches them back to the Owl and tells them)"""
    now = time.time()
    return [(uid, s) for uid, s in data()["subs"].items() if not s.get("open") and float(s.get("until") or 0) + grace_s <= now and not s.get("ended")]


def mark_ended(uid):
    with _LOCK:
        d = data()
        if uid in d["subs"]:
            d["subs"][uid]["ended"] = int(time.time()); _save(MARKET, d)


def catalogue(me_uid=None, my_server="", include_hidden=False):
    """every visible listing with its numbers, best first - what the page shows"""
    refresh_pauses()
    d = data(); R = robots(); out = []
    try:
        import broker_book as BB
        pg = BB.lookup(my_server) if my_server else None
        v = (pg or {}).get("verdict") or {}
        at_my_broker = {r["id"]: r for r in (v.get("robots") or [])}
    except Exception:
        at_my_broker = {}
    for rid, L in d["listings"].items():
        if L.get("hidden") and not include_hidden:
            continue
        rb = R.get(rid) or {}
        res = best_result(rid) or result_of(rid) or {}
        out.append({"id": rid, "name": rb.get("name_fr") or rb.get("name") or rid, "alias": L.get("alias"), "blurb": L.get("blurb"),
                    "price_usd": 0, "free": True, "open_recipe": bool(L.get("open_recipe")),
                    "paused": bool(L.get("paused")), "hidden": bool(L.get("hidden")), "by_uid": L.get("by_uid"), "mine": L.get("by_uid") == me_uid,
                    "published_at": L.get("published_at"), "followers": len(followers(rid)), "by_nest": not rb.get("by_uid"),
                    "test": res, "markets": markets_of(rid), "at_my_broker": at_my_broker.get(rid),
                    "following": bool(me_uid and (sub_of(me_uid) or {}).get("rid") == rid)})
    out.sort(key=lambda x: (-(float((x["test"] or {}).get("net") or 0)), x["name"]))
    return out


def creator_stats(uid):
    """for 'Mes robots sur la place': per listed robot, followers and what they earned"""
    d = data(); out = []
    for rid, L in d["listings"].items():
        if L.get("by_uid") != uid:
            continue
        try:
            import owl_wallet as _OW
            earned = _OW.creator_earned(rid)
        except Exception:
            earned = 0.0
        out.append({"id": rid, "followers": len(followers(rid)), "price_usd": 0, "paused": bool(L.get("paused")),
                    "hidden": bool(L.get("hidden")), "earned_usd": round(earned, 2), "published_at": L.get("published_at")})
    return out
