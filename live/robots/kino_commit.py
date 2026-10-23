"""kino_commit.py (2026-10-23, Kino architecture review, engine 1): the commitment ledger.

Owner's own log that day: "j'ai dit deux fois que je lançais alors que rien ne partait." Kino says "je lance / je regarde /
je reviens dans 10 min" and it only happens when a regex catches it or the model sets the right JSON field. Nothing owned
the promise. Here one thing does:

  harvest   every message Kino sends is read for commitments - first the structured fields (act, build, show, work),
            then the text itself (a small model lists what Kino committed to do, the member's language, with a deadline)
  ledger    robots/kino_commitments.json: what, kind, due, status open -> kept | broken, how it was verified
  keep      test -> the test is started if it is not; build -> the builder runs; check/tell/other -> the chat's "work"
            tray (the promise watcher brings the event "YOUR PROMISE" at the due time)
  verify    at the due time the ledger looks for evidence (a test queued, a build made, the promise event answered);
            none = BROKEN, and Kino gets the event to say so in one honest line
  prompt    "YOUR OPEN COMMITMENTS" + kept/broken counts of the week, read every turn (robot_chat.prompt)

The number that matters for trust is broken / (kept + broken); it is in the prompt and in stats().
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "kino_commitments.json")
_LOCK = threading.Lock()
KINDS = ("test", "build", "show", "check", "tell", "other")
DEFAULT_MIN = {"test": 3, "build": 10, "show": 2, "check": 10, "tell": 1440, "other": 30}
# a message worth reading for commitments (the extraction call costs ~$0.002 - not on every "ok")
GATE = re.compile(r"\b(je (lance|relance|démarre|regarde|vérifie|reviens|m'y mets|creuse|mesure|calcule|compare|cherche|teste|prépare|note|m'en occupe|"
                  r"te (dis|donne|montre|sors|prépare|envoie|écris|préviens|redis|fais|tiens au courant))|dès que|tout de suite|dans (\d+|quelques|dix|cinq|deux|trois) "
                  r"(min|minutes|secondes|heures)|i'?ll|let me|right away|i (check|look|run|start|launch|get back|prepare|measure))\b", re.I)
NOT_NOW = re.compile(r"\b(demain|plus tard|tomorrow|later|ce soir|tonight|cette nuit|la semaine prochaine|next week)\b", re.I)

EXTRACT_SYSTEM = """You read ONE message that Kino (an AI friend who builds trading robots for a member) just sent.
List what Kino COMMITS TO DO himself after this message - firm, first person: "je lance le test", "je regarde et je te dis",
"je te prépare un robot", "je reviens dans 10 min", "je te dis quand le test tombe".
NOT: conditionals ("si tu veux je..."), questions, offers, things already done in this message, the member's actions, generic
"on verra". Nothing firm = empty list.
kind: test = start a robot test | build = build or change a robot | show = put something on a chart | check = look into
something and come back | tell = tell them when something happens later | other.
minutes = when it must be kept: as Kino said; else test 3, build 10, show 2, check 10, tell 1440, other 30.
what: in the member's language, at most 12 words, the thing itself ("lancer le test du robot Nasdaq").
Reply with JSON only: {"items": [{"what": "...", "kind": "...", "minutes": n}]}"""


def _load():
    try:
        return json.load(open(LEDGER, encoding="utf-8"))
    except Exception:
        return {"items": [], "n": 0}


def _save(d):
    tmp = LEDGER + ".%d.tmp" % threading.get_ident()
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    for i in range(40):
        try:
            os.replace(tmp, LEDGER)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, LEDGER)


def _mut(fn):
    with _LOCK:
        d = _load()
        out = fn(d)
        d["items"] = d["items"][-400:]
        _save(d)
        return out


def _words(t):
    return set(re.findall(r"\w{4,}", str(t or "").lower()))


def _same(a, b):
    A, B = _words(a), _words(b)
    return bool(A and B) and len(A & B) >= 0.5 * min(len(A), len(B))


def add(uid, cid, items, src="text", said=""):
    """items: [{what, kind, minutes}] -> the ids added (an open commitment saying the same thing in this chat is not doubled)"""
    now = time.time()

    def f(d):
        ids = []
        for it in items or []:
            kind = it.get("kind") if it.get("kind") in KINDS else "other"
            what = str(it.get("what") or "").strip()[:120]
            if not what:
                continue
            if any(x["cid"] == cid and x["status"] == "open" and (x["what"] == what or _same(x["what"], what)) for x in d["items"]):
                continue
            try:
                mins = max(1, min(2880, int(it.get("minutes") or DEFAULT_MIN[kind])))
            except Exception:
                mins = DEFAULT_MIN[kind]
            d["n"] = int(d.get("n") or 0) + 1
            x = {"id": "c%d" % d["n"], "uid": uid, "cid": cid, "t": now, "what": what, "kind": kind, "due": now + 60 * mins, "status": "open",
                 "src": src, "said": str(said or "")[:160], "tries": 0}
            d["items"].append(x)
            ids.append(x["id"])
        return ids
    return _mut(f)


def resolve(cid, what_or_id, status, how=""):
    """close the open commitment of this chat named by id or by its words -> the item or None"""
    def f(d):
        for x in reversed(d["items"]):
            if x["cid"] == cid and x["status"] == "open" and (x["id"] == what_or_id or x["what"] == what_or_id or _same(x["what"], what_or_id)):
                x.update(status=status, done_t=time.time(), how=str(how or "")[:160])
                return x
        return None
    return _mut(f)


def resolve_ids(cid, ids, how="said kept"):
    for i in ids or []:
        resolve(cid, str(i), "kept", how)


def open_for(uid=None, cid=None):
    return [x for x in _load()["items"] if x["status"] == "open" and (uid is None or x["uid"] == uid) and (cid is None or x["cid"] == cid)]


def stats(uid=None, days=7):
    t0 = time.time() - days * 86400
    X = [x for x in _load()["items"] if (uid is None or x["uid"] == uid) and x["t"] >= t0]
    k = sum(1 for x in X if x["status"] == "kept")
    b = sum(1 for x in X if x["status"] == "broken")
    return {"kept": k, "broken": b, "open": sum(1 for x in X if x["status"] == "open"), "rate": (b / (k + b)) if (k + b) else None}


def _ago(sec, lang):
    m = int(sec / 60)
    if m < 1:
        return "à l'instant" if lang == "fr" else "just now"
    if m < 60:
        return ("il y a %d min" if lang == "fr" else "%d min ago") % m
    return ("il y a %d h" if lang == "fr" else "%d h ago") % (m // 60)


def block(uid, cid, lang="fr"):
    """the prompt block: what he still owes this member, and his week"""
    now = time.time()
    O = [x for x in open_for(uid) if now - x["t"] < 3 * 86400]
    s = stats(uid, 7)
    L = []
    if O:
        L.append("YOUR OPEN COMMITMENTS (you said it - it happens, or you say honestly that it did not; the system starts tests and "
                 "builds for you and brings the others back at their time; set \"kept\": [ids] when THIS message keeps one):")
        for x in O[-6:]:
            L.append("  [%s] %s - said %s%s - %s" % (x["id"], x["what"], _ago(now - x["t"], lang), "" if x["cid"] == cid else " (another conversation)",
                                                    ("due in %d min" % max(0, (x["due"] - now) / 60)) if x["due"] > now else "OVERDUE"))
    if s["kept"] or s["broken"]:
        L.append("YOUR WORD THIS WEEK: %d commitments kept, %d broken%s. A broken one is the worst thing for trust: when it happens, say it "
                 "in one plain line, no excuse, and do the thing or say what you do instead." % (
                     s["kept"], s["broken"], (" (%.0f%% broken)" % (100 * s["rate"])) if s["rate"] is not None else ""))
    return "\n".join(L)


def from_fields(q, pa):
    """the structured fields of a reply as commitments (free, no model)"""
    q, pa = q or {}, pa or {}
    out = []
    if q.get("act") == "test":
        out.append({"what": "lancer le test du robot", "kind": "test", "minutes": 3})
    if q.get("build"):
        out.append({"what": "construire / modifier le robot", "kind": "build", "minutes": 10})
    w = pa.get("work") or q.get("work")
    if isinstance(w, dict) and w.get("what"):
        try:
            mins = max(2, min(1440, int(w.get("in") or 600) // 60))
        except Exception:
            mins = 10
        out.append({"what": str(w["what"])[:120], "kind": "check", "minutes": mins, "_work": True})
    return out


def extract_text(say, W, log=None):
    """the small model lists the commitments of the text -> [{what, kind, minutes}] (never raises)"""
    try:
        say = str(say or "").strip()
        if len(say) < 12 or not GATE.search(say):
            return []
        j = W.ask_json(EXTRACT_SYSTEM, "KINO'S MESSAGE:\n<<<\n%s\n>>>\nJSON only." % say[:1500], models=("haiku", "sonnet"), timeout=60, log=log, warm=False)
        items = (j or {}).get("items") if isinstance(j, dict) else None
        out = []
        for it in items or []:
            if isinstance(it, dict) and str(it.get("what") or "").strip():
                if NOT_NOW.search(str(it.get("what"))) and it.get("kind") in ("test", "build", "show"):
                    continue                              # "demain je lance" is not for the next 3 minutes
                out.append({"what": str(it["what"]).strip()[:120], "kind": it.get("kind") if it.get("kind") in KINDS else "other",
                            "minutes": it.get("minutes")})
        return out[:4]
    except Exception:
        return []


def harvest(uid, cid, say, q, pa, W, H, log=None):
    """one sent message -> ledger (+ keeps what can be kept right away). H = server hooks: chat(cid), act_test(cid, uid),
    build(cid, uid), work_add(cid, what, minutes), show_done(cid)"""
    try:
        if pa and pa.get("kept"):
            resolve_ids(cid, pa["kept"] if isinstance(pa["kept"], list) else [pa["kept"]])
        F = from_fields(q, pa)
        ids = add(uid, cid, [x for x in F if not x.get("_work")], "field", say)
        for x in F:                                       # a "work" field already feeds the promise watcher: only the ledger entry
            if x.get("_work"):
                add(uid, cid, [x], "field", say)
        T = extract_text(say, W, log)
        T = [t for t in T if not any(_same(t["what"], f["what"]) or (t["kind"] == f["kind"] and t["kind"] in ("test", "build")) for f in F)]
        new = add(uid, cid, T, "text", say)
        c = H["chat"](cid) or {}
        for x in [x for x in open_for(uid, cid) if x["id"] in new]:
            try:
                if x["kind"] == "test":
                    if not _test_evidence(c, x["t"]):
                        H["act_test"](cid, uid)
                        _bump(x["id"])
                elif x["kind"] == "build":
                    H["build"](cid, uid)
                    _bump(x["id"])
                elif x["kind"] == "show":
                    H["show"](cid, uid)
                else:                                     # check / tell / other: the promise watcher brings it back at its time
                    H["work_add"](cid, x["what"], max(2, int((x["due"] - x["t"]) / 60)))
            except Exception:
                pass
        return ids + new
    except Exception:
        return []


def _bump(cid_id):
    def f(d):
        for x in d["items"]:
            if x["id"] == cid_id:
                x["tries"] = int(x.get("tries") or 0) + 1
    _mut(f)


def _test_evidence(c, since):
    t = (c or {}).get("test") or {}
    if t.get("state") not in ("queued", "running", "done"):
        return False
    at = t.get("at")                                      # "2026-10-23T14:48:07Z" (chat_test) - an old test is no evidence
    try:
        if isinstance(at, (int, float)):
            return float(at) >= since - 30
        import calendar
        return calendar.timegm(time.strptime(str(at)[:19], "%Y-%m-%dT%H:%M:%S")) >= since - 30
    except Exception:
        return False


def _build_evidence(c, since):
    for m in reversed((c or {}).get("msgs") or []):
        if float(m.get("t") or 0) < since - 5:
            break
        if m.get("role") == "ai" and (m.get("made") or m.get("rev")):
            return True
    return False


def tick(H):
    """every minute from the server: test and build commitments past due are verified - evidence = kept, a second try when
    there was none, then BROKEN and Kino is told to say so. H adds: event(cid, uid, text), building(cid)"""
    now = time.time()
    for x in open_for():
        if x["kind"] not in ("test", "build") or now < x["due"]:
            continue
        try:
            c = H["chat"](x["cid"]) or {}
            ok = _test_evidence(c, x["t"]) if x["kind"] == "test" else _build_evidence(c, x["t"])
            if ok:
                resolve(x["cid"], x["id"], "kept", "test queued" if x["kind"] == "test" else "robot built")
                continue
            if x["kind"] == "build" and H["building"](x["cid"]):
                continue                                  # still at it
            if int(x.get("tries") or 0) < 2:
                (H["act_test"] if x["kind"] == "test" else H["build"])(x["cid"], x["uid"])
                _bump(x["id"])
                def _later(d, x=x):
                    for y in d["items"]:
                        if y["id"] == x["id"]:
                            y["due"] = time.time() + 180
                _mut(_later)
                continue
            resolve(x["cid"], x["id"], "broken", "no evidence after 2 tries")
            H["event"](x["cid"], x["uid"], "YOUR COMMITMENT WAS NOT KEPT: %s you said you would \"%s\" (%s) and it did not happen (the system tried "
                       "twice: no test queued / no robot built - probably a robot or a moments check still missing). Tell them in ONE plain line, no "
                       "excuse, and say what you do now (ask for the missing piece, or do it now with act / build if it is possible this time)." % (
                           _ago(now - x["t"], "en"), x["what"], x["kind"]))
        except Exception:
            pass


def resolve_work(cid, what, kept, how=""):
    """the promise watcher answered (or dropped) a "work" promise"""
    try:
        resolve(cid, what, "kept" if kept else "broken", how or ("promise event answered" if kept else "promise dropped / not answered"))
    except Exception:
        pass
