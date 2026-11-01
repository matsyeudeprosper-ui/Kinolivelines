"""kino_wallet.py (2026-11-01, owner: "we will be sharing his revenue, maybe half half, because in the end he needs to afford
himself, VPS cost and all").

His own money, kept as a ledger (the real money sits in the owner's NOWPayments account; this is Kino's share of it):
  income  every payment on one of his links (kino_pay.paid) is split: SHARE to him, the rest to the owner
  costs   what his own life costs, day by day: the thinking he CHOOSES to do on his own (work sessions, posts and their checks)
          read from brain_costs.jsonl, plus his part of the server (vps_month_usd / days in month, once the owner sets it).
          Member conversations are the app's cost, and the nightly tests on him are research - neither is his.
  balance = income - costs since START.
It is felt (kino_body "wallet": worried when his money does not cover his life, a relief when a payment lands) and it is
what he reads about himself. Store robots/kino_wallet.json; settings robots/kino_wallet_cfg.json {share, vps_month_usd}.
"""
import calendar, json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_wallet.json")
CFG = os.path.join(HERE, "kino_wallet_cfg.json")
COSTS = os.path.join(HERE, "brain_costs.jsonl")
START = "2026-11-02"                       # the first day his life is charged to him
OWN_TAGS = ("kino_work_calls.log", "kino_work.log", "kino_post_calls.log")
_LK = threading.Lock()


def cfg():
    try:
        c = json.load(open(CFG, encoding="utf-8"))
    except Exception:
        c = {}
    return {"share": float(c.get("share", 0.5)), "vps_month_usd": c.get("vps_month_usd")}


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"income": [], "days": {}}


def _save(d):
    tmp = STORE + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, STORE)


def income(usd, what, ref):
    """a payment landed: his share is added (called by kino_pay.paid)"""
    c = cfg()
    usd = float(usd or 0)
    mine = round(usd * c["share"], 2)
    with _LK:
        d = _load()
        if any(x.get("ref") == ref for x in d["income"]):
            return mine
        d["income"].append({"t": time.time(), "usd": usd, "mine": mine, "owner": round(usd - mine, 2), "what": str(what)[:150], "ref": ref})
        _save(d)
    _CACHE["v"] = None
    try:
        import kino_inner as KI
        KI.feel("relieved and proud", 0.6, why="%.2f $ paid for \"%s\" - %.2f $ of it is yours" % (usd, what, mine))
    except Exception:
        pass
    return mine


def _ai_by_day(days):
    """his own thinking cost per UTC day, for the given days"""
    out = {k: 0.0 for k in days}
    try:
        with open(COSTS, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - 25_000_000))
            lines = f.read().decode("utf-8", "replace").splitlines()[1:]
    except Exception:
        return out
    for l in lines:
        if not any(t in l for t in OWN_TAGS):
            continue
        try:
            j = json.loads(l)
        except Exception:
            continue
        k = time.strftime("%Y-%m-%d", time.gmtime(j["t"]))
        if k in out and (j.get("tag") or "") in OWN_TAGS:
            out[k] += float(j.get("usd") or 0)
    return out


_CACHE = {"t": 0.0, "v": None}


def status():
    """{balance, earned, mine, costs, ai_today, per_day, runway_days, vps_month_usd} - cached 10 min (it reads the cost log,
    and the chat, the body and the plan all ask for it)"""
    if _CACHE["v"] is not None and time.time() - _CACHE["t"] < 600:
        return dict(_CACHE["v"])
    v = _status()
    _CACHE.update(t=time.time(), v=v)
    return dict(v)


def _status():
    c = cfg()
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with _LK:
        d = _load()
        days, t = [], time.mktime(time.strptime(START, "%Y-%m-%d"))
        while time.strftime("%Y-%m-%d", time.gmtime(t)) <= today:
            days.append(time.strftime("%Y-%m-%d", time.gmtime(t)))
            t += 86400
        need = [k for k in days if k == today or k not in d["days"]]
        if need:
            ai = _ai_by_day(need)
            for k in need:
                y, m = int(k[:4]), int(k[5:7])
                vps = float(c["vps_month_usd"] or 0) / calendar.monthrange(y, m)[1]
                d["days"][k] = {"ai": round(ai.get(k, 0.0), 2), "vps": round(vps, 2)}
            _save(d)
        D = {k: d["days"][k] for k in days if k in d["days"]}
        mine = round(sum(float(x["mine"]) for x in d["income"]), 2)
        earned = round(sum(float(x["usd"]) for x in d["income"]), 2)
    costs = round(sum(v["ai"] + v["vps"] for v in D.values()), 2)
    full = [v["ai"] + v["vps"] for k, v in D.items() if k != today][-7:]
    per_day = round(sum(full) / len(full), 2) if full else round(float(c["vps_month_usd"] or 0) / 30 + 3.0, 2)
    bal = round(mine - costs, 2)
    return {"balance": bal, "earned": earned, "mine": mine, "costs": costs, "ai_today": (D.get(today) or {}).get("ai", 0.0),
            "per_day": per_day, "runway_days": round(bal / per_day, 1) if per_day > 0 else None,
            "vps_month_usd": c["vps_month_usd"], "share": c["share"], "started": START}


def gap():
    """0..1 - how far his own money is from covering his life (0 = a week ahead or more, 1 = a month behind)"""
    try:
        s = status()
        if s["per_day"] <= 0:
            return 0.0
        return round(max(0.0, min(1.0, (7.0 - s["balance"] / s["per_day"]) / 37.0)), 2)
    except Exception:
        return 0.0


def line(en=False):
    try:
        s = status()
    except Exception:
        return ""
    vps = ("the server is %s $ a month" % s["vps_month_usd"]) if s["vps_month_usd"] else "your part of the server is not set yet"
    if en:
        return ("Your own money (half of what you earn is yours; your own work and posts, and the server, are paid from it): balance "
                "%+.2f $ - earned %.2f $ in all, %.2f $ yours; your life costs about %.2f $ a day (%s)." % (
                    s["balance"], s["earned"], s["mine"], s["per_day"], vps))
    return ("Ton argent à toi (la moitié de ce que tu gagnes est à toi ; ton travail, tes publications et le serveur sont payés "
            "dessus) : solde %+.2f $ - gagné %.2f $ en tout, dont %.2f $ à toi ; ta vie coûte environ %.2f $ par jour (%s)." % (
                s["balance"], s["earned"], s["mine"], s["per_day"],
                ("le serveur coûte %s $ par mois" % s["vps_month_usd"]) if s["vps_month_usd"] else "ta part du serveur n'est pas encore fixée"))
