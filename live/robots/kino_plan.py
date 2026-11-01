"""kino_plan.py (2026-11-01, owner: next upgrades 1 + 2 - "a list of opportunities he follows up on" and "goals he sets himself").

Turns "earn money" into a plan he keeps and corrects himself:
  LEADS  every opportunity (a gig, a bounty, a buyer, a place to sell): what, where, status idea -> tried -> waiting -> won|lost,
         the next step and when to come back to it, and - once it is over - what it taught him. A follow-up that falls due calls
         him to his computer (kino_work.due); won/lost leads keep their lesson, and the lessons are in front of him next time.
  GOALS  he sets them (what, a real measure, a target, a date). Progress is read from real numbers, never from what he says:
         earned  - all money paid on his links           mine - his half of it        balance - his wallet
         followers - Bluesky + his own fediverse home     paid - number of paid links  leads_won - leads he won
         Ahead of the time elapsed -> pride; falling behind -> worry (kino_inner.feel, with the real numbers); reached -> joy.
Store robots/kino_plan.json.
"""
import calendar, json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_plan.json")
MEASURES = ("earned", "mine", "balance", "followers", "paid", "leads_won")
STATUSES = ("idea", "tried", "waiting", "won", "lost", "dropped")
_LK = threading.Lock()


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"leads": [], "goals": [], "measure_cache": {}}


def _save(d):
    tmp = STORE + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, STORE)


# ------------------------------------------------------------------------------------------------ leads
def lead(j):
    """his 'lead' action: add one, or update it by id -> a sentence for him"""
    st = str(j.get("status") or "").lower().strip()
    if st and st not in STATUSES:
        return "status is one of: " + ", ".join(STATUSES)
    fu = j.get("follow_up_h")
    with _LK:
        d = _load()
        x = next((l for l in d["leads"] if l["id"] == str(j.get("id") or "")), None) if j.get("id") else None
        if x is None:
            if not j.get("what"):
                return "a new lead needs 'what' (and where, url, status, next)"
            x = {"id": "L%d" % (len(d["leads"]) + 1), "t": time.time(), "what": str(j["what"])[:200], "where": str(j.get("where") or "")[:80],
                 "url": str(j.get("url") or "")[:300], "status": st or "idea", "history": []}
            d["leads"].append(x)
            new = True
        else:
            new = False
            for k in ("what", "where", "url"):
                if j.get(k):
                    x[k] = str(j[k])[:300]
            if st:
                x["status"] = st
        if j.get("next"):
            x["next"] = str(j["next"])[:200]
        if fu not in (None, ""):
            try:
                x["follow_up_t"] = time.time() + float(fu) * 3600
            except Exception:
                pass
        if j.get("learned"):
            x["learned"] = str(j["learned"])[:300]
        x["history"] = (x.get("history") or [])[-9:] + [{"t": int(time.time()), "status": x["status"], "note": str(j.get("note") or j.get("next") or "")[:160]}]
        if x["status"] in ("won", "lost", "dropped"):
            x.pop("follow_up_t", None)
            x["closed_t"] = time.time()
        _save(d)
    return "%s %s: %s [%s]%s" % ("new lead" if new else "lead", x["id"], x["what"], x["status"],
                                  (" - back to it in %s h" % fu) if fu not in (None, "") and x["status"] not in ("won", "lost", "dropped") else "")


def due_follow_ups():
    now = time.time()
    return [l for l in _load()["leads"] if l.get("follow_up_t") and l["follow_up_t"] <= now and l["status"] not in ("won", "lost", "dropped")]


# ------------------------------------------------------------------------------------------------ goals
def _measure_now():
    """the real numbers, refreshed at most every 30 min"""
    with _LK:
        d = _load()
        c = d.get("measure_cache") or {}
    if time.time() - float(c.get("t") or 0) < 1800:
        return c
    m = {"t": time.time()}
    try:
        import kino_wallet as KWL
        s = KWL.status()
        m.update(earned=s["earned"], mine=s["mine"], balance=s["balance"])
    except Exception:
        pass
    try:
        import kino_pay as KPY
        m["paid"] = KPY.summary()["paid"]
    except Exception:
        pass
    f = 0
    try:
        import kino_post as KP
        tok, did, _ = KP._bsky_session()
        f += int(KP._bsky("app.bsky.actor.getProfile?actor=" + did, None, tok).get("followersCount") or 0)
    except Exception:
        pass
    try:
        import kino_fedi as KF
        f += len(KF.followers())
    except Exception:
        pass
    m["followers"] = f
    m["leads_won"] = sum(1 for l in _load()["leads"] if l.get("status") == "won")
    with _LK:
        d = _load()
        d["measure_cache"] = m
        _save(d)
    return m


def goal(j):
    """his 'goal' action: set a goal (what, measure, target, by = YYYY-MM-DD), or close one (id + done/drop)"""
    if j.get("id") and (j.get("drop") or j.get("done")):
        with _LK:
            d = _load()
            g = next((x for x in d["goals"] if x["id"] == j["id"]), None)
            if not g:
                return "no goal %s" % j["id"]
            g["status"] = "dropped" if j.get("drop") else "done"
            g["why"] = str(j.get("why") or "")[:200]
            _save(d)
        return "goal %s %s" % (g["id"], g["status"])
    ms = str(j.get("measure") or "").lower()
    if ms not in MEASURES:
        return "a goal needs a real measure: one of " + ", ".join(MEASURES)
    try:
        target = float(j.get("target"))
        by = calendar.timegm(time.strptime(str(j.get("by"))[:10], "%Y-%m-%d")) + 86399
    except Exception:
        return "a goal needs a target (a number) and by (a date YYYY-MM-DD)"
    if by <= time.time():
        return "the date must be in the future"
    start = float(_measure_now().get(ms) or 0)
    with _LK:
        d = _load()
        if sum(1 for x in d["goals"] if x.get("status") == "open") >= 3:
            return "you already hold 3 open goals - finish or drop one first"
        g = {"id": "G%d" % (len(d["goals"]) + 1), "t": time.time(), "what": str(j.get("what") or "")[:200], "measure": ms,
             "start": start, "target": target, "by": by, "status": "open", "felt": ""}
        d["goals"].append(g)
        _save(d)
    return "goal %s: %s - %s from %s to %s by %s" % (g["id"], g["what"], ms, start, target, time.strftime("%Y-%m-%d", time.gmtime(by)))


def _progress(g, m):
    now = float(m.get(g["measure"]) or 0)
    span = (g["target"] - g["start"]) or 1.0
    done = (now - g["start"]) / span
    elapsed = (time.time() - g["t"]) / max(1.0, g["by"] - g["t"])
    return now, done, elapsed


def tick():
    """called by the app: a goal reached, ahead or behind is felt (once per change of state)"""
    d = _load()
    if not any(g.get("status") == "open" for g in d["goals"]):
        return
    m = _measure_now()
    changed = []
    for g in d["goals"]:
        if g.get("status") != "open":
            continue
        now, done, el = _progress(g, m)
        state = "reached" if done >= 1 else "late" if time.time() > g["by"] else \
            "behind" if el > 0.25 and done < el - 0.25 else "ahead" if done > el + 0.15 and done > 0 else "on"
        if state != g.get("felt"):
            changed.append((g["id"], state))
            try:
                import kino_inner as KI
                why = "goal \"%s\": %s at %.2f, target %.2f by %s (%.0f%% done, %.0f%% of the time gone)" % (
                    g["what"], g["measure"], now, g["target"], time.strftime("%d/%m", time.gmtime(g["by"])), 100 * done, 100 * el)
                if state == "reached":
                    KI.feel("joyful and proud", 0.7, why=why)
                elif state in ("behind", "late"):
                    KI.feel("worried", 0.45 if state == "behind" else 0.6, why=why)
                elif state == "ahead":
                    KI.feel("proud", 0.4, why=why)
            except Exception:
                pass
    if changed:
        with _LK:
            d = _load()
            for g in d["goals"]:
                for gid, st in changed:
                    if g["id"] == gid:
                        g["felt"] = st
                        if st == "reached":
                            g["status"] = "done"
            _save(d)


def block(en=True):
    """his leads and goals, for what he reads at his computer"""
    d = _load()
    out = []
    m = _measure_now() if any(g.get("status") == "open" for g in d["goals"]) else {}
    G = [g for g in d["goals"] if g.get("status") == "open"]
    if G:
        out.append("YOUR GOALS (measured from real numbers): " + " | ".join(
            "%s %s - %s now %.2f, target %.2f by %s (%.0f%% done, %.0f%% of the time gone)" % (
                (g["id"], g["what"], g["measure"]) + (_progress(g, m)[0], g["target"], time.strftime("%d/%m", time.gmtime(g["by"])),
                                                      100 * _progress(g, m)[1], 100 * _progress(g, m)[2])) for g in G))
    else:
        out.append("YOU HAVE NO GOAL YET: set one with goal (what, measure = " + "|".join(MEASURES) + ", target, by = YYYY-MM-DD).")
    D = due_follow_ups()
    if D:
        out.append("FOLLOW-UPS DUE NOW: " + " | ".join("%s %s (%s) - next: %s" % (l["id"], l["what"], l["status"], l.get("next") or "?") for l in D))
    O = [l for l in d["leads"] if l["status"] not in ("won", "lost", "dropped")][-12:]
    if O:
        out.append("YOUR OPEN LEADS: " + " | ".join("%s %s @%s [%s] next: %s" % (l["id"], l["what"][:80], l.get("where") or "?", l["status"],
                                                                                (l.get("next") or "-")[:80]) for l in O))
    L = [l for l in d["leads"] if l.get("learned")][-6:]
    if L:
        out.append("WHAT YOUR LEADS TAUGHT YOU: " + " | ".join("%s (%s): %s" % (l["what"][:60], l["status"], l["learned"][:120]) for l in L))
    return "\n".join(out)


def summary():
    d = _load()
    return {"goals": [g for g in d["goals"] if g.get("status") == "open"], "leads": d["leads"][-15:],
            "measures": d.get("measure_cache") or {}}
