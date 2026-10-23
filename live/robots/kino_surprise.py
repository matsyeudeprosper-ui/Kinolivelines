"""kino_surprise.py (2026-10-23, Kino architecture review, engine 5): the surprise engine - prediction error beyond the markets.

His market bets and test bets already compare what he expected with what came. Nothing did it for the people, his word,
the lab or his own plan. Here every ten minutes, no model: what did not go as he expected becomes a feeling (kino_inner)
and a thought he can bring up - that is how a person NOTICES things instead of being told.

  people    a reading of a member that was wrong (kino_person: he expected a short answer, got a long one; expected
            silence, they wrote) - curiosity, small; a member who usually writes at this hour and has not for 2+ days -
            worry, a thought "X n'a pas écrit depuis..."
  word      a commitment broken (kino_commit) - worry about them, a strong thought (he must say it)
  lab       a test result far from the robot's previous one (sign flip, or a change bigger than 1.5x) - excitement or
            annoyance, a thought with the numbers
  plan      a plan item missed at night (kino_exec review) - annoyance at himself, a lesson-shaped thought

Each surprise is written once (kino_surprise.json keeps what was seen) and shown 24 h in the prompt (SURPRISES).
"""
import io, json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_surprise.json")
CHATS = os.path.join(HERE, "chats")
_LOCK = threading.Lock()


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"seen": {}, "log": []}


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    for i in range(40):
        try:
            os.replace(tmp, STORE)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, STORE)


def _emit(d, key, uid, text, feel, thought_strength, KI, src):
    """one surprise, once"""
    if key in d["seen"]:
        return False
    d["seen"][key] = time.time()
    d["log"].append({"t": time.time(), "uid": uid, "text": text[:240], "src": src})
    d["log"] = d["log"][-200:]
    try:
        if feel:
            KI.feel(feel[0], feel[1], uid, text[:120])
        if thought_strength:
            KI.add_thought(text[:240], "surprise", thought_strength, uid, src="surprise:" + src, half_h=12)
    except Exception:
        pass
    return True


def _people(d, KI, KP, humans):
    now = time.time()
    P = KP._load()
    for uid, u in P.items():
        if humans is not None and uid not in humans:
            continue
        for p in (u.get("preds") or [])[-10:]:
            if p.get("checked") and p.get("right") is False and now - float(p.get("t") or 0) < 86400:
                key = "pred:%s:%d" % (uid, int(p["t"]))
                _emit(d, key, uid, "Je pensais que %s répondrait %s, et c'est venu %s. Ma lecture était à côté." % (
                    uid, {"short": "court", "long": "long", "silent": "par un silence"}.get(p.get("next"), p.get("next")),
                    {"short": "court", "long": "long", "silent": "un silence"}.get(p.get("actual"), p.get("actual"))), ("curiosity", 0.08), 0.25, KI, "people")
        M = u.get("msgs") or []
        if M and u.get("hours") and sum(u["hours"]) >= 12:
            last = float(M[-1].get("t") or 0)
            days = (now - last) / 86400
            h = time.gmtime(now).tm_hour
            usual = u["hours"][h] >= max(1, 0.04 * sum(u["hours"]))
            if days >= 2 and usual:
                key = "absent:%s:%s" % (uid, time.strftime("%Y-%m-%d", time.gmtime(now)))
                _emit(d, key, uid, "%s n'a pas écrit depuis %d jours, d'habitude c'est une de ses heures (%s). Je me demande ce qu'il devient." % (
                    uid, int(days), KP.usual_hours(uid)), ("worry", 0.15), 0.4, KI, "people")


def _word(d, KI, KC):
    now = time.time()
    for x in KC._load().get("items") or []:
        if x.get("status") == "broken" and now - float(x.get("done_t") or 0) < 86400:
            _emit(d, "broken:" + x["id"], x.get("uid"), "J'ai cassé ma parole avec %s : « %s ». Ça ne devait pas arriver - je le dis, sans excuse." % (
                x.get("uid"), x.get("what")), ("worry", 0.3), 0.7, KI, "word")


def _lab(d, KI):
    now = time.time()
    if not os.path.isdir(CHATS):
        return
    for f in os.listdir(CHATS):
        if not f.endswith(".json"):
            continue
        try:
            c = json.load(open(os.path.join(CHATS, f), encoding="utf-8"))
        except Exception:
            continue
        R = [m for m in c.get("msgs") or [] if m.get("role") == "result" and isinstance(m.get("result"), dict) and m["result"].get("net") is not None]
        if len(R) < 2 or now - float(R[-1].get("t") or 0) > 86400:
            continue
        a, b = float(R[-2]["result"]["net"]), float(R[-1]["result"]["net"])
        flip = (a > 0) != (b > 0) and abs(a - b) > 10
        big = abs(b - a) > max(20.0, 1.5 * abs(a))
        if flip or big:
            nm = (c.get("robot") or {}).get("name") or c.get("thread") or "le robot"
            _emit(d, "result:%s:%d" % (c["id"], int(R[-1]["t"])), c.get("uid"), "Le test de '%s' est passé de %+.2f $ à %+.2f $ - je ne m'y attendais pas, il faut comprendre ce qui a changé avant d'en dire plus." % (nm, a, b),
                  ("excitement" if b > a else "annoyance", 0.25), 0.5, KI, "lab")


def _plan(d, KI, KX):
    now = time.time()
    for r in (KX._load().get("reviews") or [])[-2:]:
        if now - float(r.get("t") or 0) < 86400 and r.get("missed"):
            _emit(d, "missed:" + r["day"], None, "Hier j'avais prévu %d choses que je n'ai pas faites (%s). %s" % (
                len(r["missed"]), ", ".join(r["missed"][:4]), r.get("lesson") or ""), ("annoyance", 0.2), 0.35, KI, "plan")


def tick(humans=None):
    """every ~10 min from the server; humans = the ids of real members (bot accounts are never people to worry about)"""
    import kino_inner as KI
    with _LOCK:
        d = _load()
        try:
            import kino_person as KP
            _people(d, KI, KP, humans)
        except Exception:
            pass
        try:
            import kino_commit as KC
            _word(d, KI, KC)
        except Exception:
            pass
        try:
            _lab(d, KI)
        except Exception:
            pass
        try:
            import kino_exec as KX
            _plan(d, KI, KX)
        except Exception:
            pass
        now = time.time()
        d["seen"] = {k: t for k, t in d["seen"].items() if now - float(t) < 7 * 86400}
        _save(d)


def block(uid=None, lang="fr"):
    now = time.time()
    L = [x for x in _load().get("log") or [] if now - float(x["t"]) < 86400 and (x.get("uid") in (None, uid))]
    if not L:
        return ""
    return "SURPRISES OF THE LAST 24 H (what did not go as you expected - yours to bring up if it fits, once):\n" + "\n".join(
        "  - %s (%s)" % (x["text"], time.strftime("%H:%M", time.gmtime(x["t"]))) for x in L[-5:])
