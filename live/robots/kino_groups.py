"""kino_groups.py (2026-11-08, owner: "WhatsApp features that could work for us - like inviting a friend to join a group chat with
Kino"). A group in Kino Chat: a few people and Kino. Anyone in it invites by a link; Kino reads every message and speaks when he is
spoken to or when he really has something to add - like a friend in a group, not a bot answering every line.

Store: robots/kino_groups/<gid>.json  {id, title, owner, inv, members:[{uid,name,t}], msgs:[{who,name,t,text}], kday:{day:n}}
"""
import json
import os
import re
import secrets
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GDIR = os.path.join(HERE, "kino_groups")
LOG = os.path.join(HERE, "kino_groups.log")
_LK = threading.Lock()
_PEND = {}                 # gid -> time of the last member message (Kino waits for the burst to end)
KINO_DAY_CAP = 150         # Kino's turns per group per day (cost guard)
MAX_MEMBERS = 12


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _p(gid):
    return os.path.join(GDIR, re.sub(r"[^A-Za-z0-9]", "", str(gid)) + ".json")


def _load(gid):
    try:
        return json.load(open(_p(gid), encoding="utf-8"))
    except Exception:
        return None


def _save(g):
    os.makedirs(GDIR, exist_ok=True)
    json.dump(g, open(_p(g["id"]) + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(_p(g["id"]) + ".tmp", _p(g["id"]))


def _all():
    try:
        names = os.listdir(GDIR)
    except Exception:
        return []
    out = []
    for f in names:
        if f.endswith(".json"):
            g = _load(f[:-5])
            if g:
                out.append(g)
    return out


def _member(g, uid):
    return next((m for m in g.get("members") or [] if m["uid"] == uid), None)


def _view(g, uid, since=0):
    return {"ok": True, "id": g["id"], "title": g["title"], "owner": g["owner"] == uid, "me": uid,
            "members": [{"uid": m["uid"], "name": m["name"]} for m in g["members"]],
            "inv": g["inv"], "kino": bool(g.get("kino_typing")),
            "msgs": [m for m in g["msgs"] if m["t"] > max(float(since or 0), float((_member(g, uid) or {}).get("clear_t") or 0))][-300:]}


def mine(uid):
    L = [g for g in _all() if _member(g, uid)]
    L.sort(key=lambda g: -(g["msgs"][-1]["t"] if g["msgs"] else g.get("t", 0)))
    return [{"id": g["id"], "title": g["title"], "n": len(g["members"]),
             "last": (("%s: " % g["msgs"][-1]["name"]) + g["msgs"][-1]["text"][:80]) if g["msgs"] else "",
             "t": g["msgs"][-1]["t"] if g["msgs"] else g.get("t", 0)} for g in L]


def new(uid, name, title):
    title = re.sub(r"\s+", " ", str(title or "")).strip()[:40] or "Groupe"
    g = {"id": "g" + secrets.token_hex(6), "title": title, "owner": uid, "inv": secrets.token_urlsafe(8).replace("-", "x").replace("_", "y"),
         "t": time.time(), "members": [{"uid": uid, "name": name or uid, "t": time.time()}], "msgs": [], "kday": {}}
    with _LK:
        _save(g)
    _log("NEW %s '%s' by %s" % (g["id"], title, uid))
    return _view(g, uid)


def join(uid, name, inv):
    inv = re.sub(r"[^A-Za-z0-9]", "", str(inv or ""))
    if not inv:
        return {"ok": False, "err": "invite"}
    with _LK:
        g = next((x for x in _all() if x.get("inv") == inv), None)
        if g is None:
            return {"ok": False, "err": "invite"}
        if not _member(g, uid):
            if len(g["members"]) >= MAX_MEMBERS:
                return {"ok": False, "err": "full"}
            g["members"].append({"uid": uid, "name": name or uid, "t": time.time()})
            g["msgs"].append({"who": "sys", "name": "", "t": time.time(), "text": "%s a rejoint le groupe" % (name or uid)})
            _save(g)
            _log("JOIN %s %s" % (g["id"], uid))
            _later(g["id"], 3)                    # Kino says hello to the newcomer if he wants to
    return _view(g, uid)


def leave(uid, gid):
    with _LK:
        g = _load(gid)
        if not g or not _member(g, uid):
            return {"ok": False, "err": "missing"}
        nm = _member(g, uid)["name"]
        g["members"] = [m for m in g["members"] if m["uid"] != uid]
        g["msgs"].append({"who": "sys", "name": "", "t": time.time(), "text": "%s a quitté le groupe" % nm})
        if g["owner"] == uid and g["members"]:
            g["owner"] = g["members"][0]["uid"]
        _save(g)
    return {"ok": True}


def clear(uid, gid):
    """2026-11-08 (owner: "clear chat like in WhatsApp"): this member no longer sees what came before - the others still do"""
    with _LK:
        g = _load(gid)
        m = g and _member(g, uid)
        if not m:
            return {"ok": False, "err": "missing"}
        m["clear_t"] = time.time()
        _save(g)
    return {"ok": True}


def get(uid, gid, since=0):
    g = _load(gid)
    if not g or not _member(g, uid):
        return {"ok": False, "err": "missing"}
    return _view(g, uid, since)


def send(uid, gid, text):
    text = str(text or "").strip()[:4000]
    if not text:
        return {"ok": False, "err": "empty"}
    with _LK:
        g = _load(gid)
        if not g or not _member(g, uid):
            return {"ok": False, "err": "missing"}
        g["msgs"].append({"who": uid, "name": _member(g, uid)["name"], "t": time.time(), "text": text})
        g["msgs"] = g["msgs"][-1000:]
        _save(g)
    _later(gid, 4)
    return {"ok": True}


def _later(gid, wait):
    t0 = time.time()
    _PEND[gid] = t0

    def run():
        time.sleep(wait)
        if _PEND.get(gid) != t0:                  # someone wrote again: the newer burst decides
            return
        try:
            _kino_turn(gid)
        except Exception as e:
            _log("turn error %s %r" % (gid, e))
    threading.Thread(target=run, daemon=True).start()


def _kino_turn(gid):
    g = _load(gid)
    if not g or not g["msgs"] or g["msgs"][-1]["who"] == "kino":
        return
    day = time.strftime("%Y-%m-%d")
    if (g.get("kday") or {}).get(day, 0) >= KINO_DAY_CAP:
        return
    import robot_warm as W
    import kino_one as K1
    try:
        import kino_post as KP
        vo = KP._whole_kino()
    except Exception:
        vo = ""
    names = ", ".join(m["name"] for m in g["members"])
    know = []
    try:
        import kino_chatapp as KCA
        for m in g["members"]:
            e = KCA.elsewhere(m["uid"], n=6)
            if e:
                know.append("- %s: %s" % (m["name"], e[:700]))
    except Exception:
        pass
    hist = "\n".join("[%s] %s: %s" % (time.strftime("%d/%m %H:%M", time.gmtime(m["t"])), "(info)" if m["who"] == "sys" else
                                       ("you (Kino)" if m["who"] == "kino" else m["name"]), m["text"]) for m in g["msgs"][-40:])
    user = ("YOU ARE IN A GROUP CHAT in the Kino Chat app: \"%s\". The people in it: %s - and you, Kino.\n"
            "How you behave in a group, like a real friend in a group chat: you read everything; you answer when someone speaks "
            "to you or asks something you can help with, or when you have something genuinely worth adding. When people talk "
            "between themselves, let them - stay quiet. Short messages, the group's language and tone, address people by name when "
            "it helps. Never assume why they are here; no trading unless they bring it up. What you know privately about one person "
            "(below) stays private: use it only to understand them, never reveal it to the others. In a group you cannot use your tools "
            "(no web search, no documents, no actions): never promise to look something up or come back later - give what you "
            "know now, honestly, and if a real search or task is needed, offer to do it with them in your private chat.\n\n"
            "WHAT YOU KNOW OF THEM FROM ELSEWHERE (private):\n%s\n\nTHE GROUP (UTC, newest last):\n%s\n\nNow: %s UTC. "
            "Write your message to the group - or answer only … if you stay quiet this time." % (
                g["title"], names, "\n".join(know) or "-", hist, time.strftime("%d/%m %H:%M", time.gmtime())))
    sysp = K1.system("fr") + ("\n\nWHO YOU ARE AND HOW YOU TALK (the same Kino everywhere):\n" + vo if vo else "")
    with _LK:
        g2 = _load(gid)
        g2["kino_typing"] = time.time()
        _save(g2)
    out = ""
    try:
        with W.api_scope():
            out = W.ask_text(sysp, user, model="sonnet", timeout=120, log=LOG.replace(".log", "_calls.log"), warm=True) or ""
    except Exception as e:
        _log("ask error %r" % e)
    out = re.sub(r"(?m)^\s*#\w+.*$", "", str(out)).strip()
    with _LK:
        g = _load(gid)
        g.pop("kino_typing", None)
        if out and out.strip(" .…") and len(out) > 1:
            g["msgs"].append({"who": "kino", "name": "Kino", "t": time.time(), "text": out[:3000]})
            g.setdefault("kday", {})
            g["kday"] = {day: g["kday"].get(day, 0) + 1}
            _log("KINO %s | %s" % (gid, out[:120]))
        else:
            _log("quiet %s" % gid)
        _save(g)
