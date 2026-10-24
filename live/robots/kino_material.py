"""Kino's material (owner 2026-10-23 evening, after a 50-minute chat: "he has no story, nothing of his own to tell, no
opinion"): several TRUE, concrete things he could tell a member today, written by Opus (nobody waits) from REAL data only -
their robot's day, the lab, the market, his own bets and slips - refreshed every 3 h in the member's hours, each told once.

  write(uid, ctx, lang)   one Opus call: 4-6 anecdotes {id, kind, text} from the context digest the server builds
  block(uid)              "THINGS YOU COULD TELL" for the message: the untold ones of the last 24 h (max 4)
  told(uid, ids)          the reply field "told": ["m..."] - said once, never again
  due(uid)                refresh when the last batch is older than 3 h (or none today)
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(HERE, "kino_material.json")
_LOCK = threading.Lock()
REFRESH_S = 3 * 3600
KINDS = ("robot", "lab", "market", "me", "them")


def _load():
    try:
        return json.load(open(F, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LOCK:
        d = _load()
        fn(d)
        tmp = F + ".tmp"
        io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
        os.replace(tmp, F)


def due(uid):
    u = (_load().get("u") or {}).get(uid) or {}
    return time.time() - float(u.get("t") or 0) > REFRESH_S


def items(uid, untold_only=True, hours=24):
    u = (_load().get("u") or {}).get(uid) or {}
    now = time.time()
    return [x for x in u.get("items") or [] if now - x["t"] < hours * 3600 and (not untold_only or not x.get("told"))]


def write(uid, ctx, lang="fr"):
    """ctx: the digest the server built (true facts only). One Opus call; the result replaces the untold items older than 3 h."""
    import robot_warm as W
    _mut(lambda d: d.setdefault("u", {}).setdefault(uid, {}).__setitem__("t", time.time()))      # taken (no double call)
    sysp = ("You are Kino, the AI who lives in the OwlNest trading app and talks with members like a friend. From the FACTS below "
            "(all true, measured today), write the things you would genuinely want to tell THIS member tonight, like someone "
            "coming home with stories: what their robot did today (a moment, not a report), what happened in the lab (a robot that "
            "died, a test that surprised you), something in the markets you noticed and what YOU think of it, a bet of yours that "
            "went right or wrong, a slip you made and what it taught you. Rules: every fact comes from the FACTS - never invent a "
            "trade, a number, a headline or an event; at most ONE number per item, rounded the way people talk; first person, spoken, "
            "2-3 short sentences each, with YOUR opinion or feeling in it; no advice, no bulletin tone, no 'as an AI'; in %s. "
            "Answer ONE JSON object only: {\"items\": [{\"kind\": \"robot|lab|market|me|them\", \"text\": \"...\"}]} with 4 to 6 items, "
            "the best first. If the facts give you nothing worth telling for a kind, skip that kind." % ("French" if lang != "en" else "English"))
    raw = None
    try:
        raw = W.ask_json(sysp, "FACTS (today, true):\n" + str(ctx)[:9000] + "\n\nJSON only.", models=("opus", "sonnet"), timeout=150,
                         log=os.path.join(HERE, "kino_material.log"), warm=False)
    except Exception:
        raw = None
    L = []
    for i, x in enumerate((raw or {}).get("items") or [] if isinstance(raw, dict) else []):
        t = str((x or {}).get("text") or "").strip()
        k = str((x or {}).get("kind") or "me").strip().lower()
        if 20 <= len(t) <= 420 and k in KINDS:
            L.append({"id": "m%d%d" % (int(time.time()) % 100000, i), "kind": k, "text": t, "t": time.time(), "told": False})
    try:
        from kino_inner import BAD as _BAD
        L = [x for x in L if not _BAD.search(x["text"])]
    except Exception:
        pass
    L = _verified(ctx, L)
    if not L:
        return []

    def _ws(t):
        return set(w for w in re.findall(r"[a-z\u00e0-\u00ff']{5,}", str(t or "").lower()))

    def put(d):
        u = d.setdefault("u", {}).setdefault(uid, {})
        old = [x for x in u.get("items") or [] if x.get("told") or time.time() - x["t"] < 24 * 3600]  # 24 h of items stay (dedupe)
        # 2026-10-24: the oil story was written again at every refresh and told five times - a new item that overlaps an item
        # of the last 24 h (word sets) is the same story and is skipped
        new = []
        for x in L:
            wx = _ws(x["text"])
            if any(wx and len(wx & _ws(o["text"])) >= 0.4 * min(len(wx), len(_ws(o["text"]))) for o in old):
                continue
            new.append(x)
        u["items"] = (old + new)[-30:]
        u["t"] = time.time()
    _mut(put)
    try:
        io.open(os.path.join(HERE, "kino_material.log"), "a", encoding="utf-8").write("%s %s wrote %d: %s\n" % (
            time.strftime("%m-%d %H:%M:%S"), uid, len(L), " | ".join(x["kind"] + ": " + x["text"][:70] for x in L)))
    except Exception:
        pass
    return L


def _verified(ctx, L):
    """2026-10-23: the first real batch said a robot FAILED its luck test when the facts said it PASSED (two lab lines
    conflated). Every item is checked against the facts by a second, cheaper call; an item with one unsupported claim is
    dropped, and the drop is logged. Without a verdict (call failed) nothing is kept - an invented fact is worse than silence."""
    if not L:
        return L
    import robot_warm as W
    q = "\n".join("[%d] %s" % (i, x["text"]) for i, x in enumerate(L))
    raw = None
    try:
        raw = W.ask_json("You are a strict fact checker. You get FACTS (true) and ITEMS written from them. For each item decide whether "
                         "EVERY factual claim in it (names, numbers, events, outcomes, which robot did what, headlines) is supported by "
                         "the FACTS. Opinions and feelings are fine; a wrong name, number, outcome or an event not in the facts is not. "
                         "Answer ONE JSON object only: {\"keep\": [item indexes fully supported], \"dropped\": {\"index\": \"the unsupported claim\"}}",
                         "FACTS:\n" + str(ctx)[:9000] + "\n\nITEMS:\n" + q + "\n\nJSON only.", models=("sonnet", "opus"), timeout=90,
                         log=os.path.join(HERE, "kino_material.log"), warm=False)
    except Exception:
        raw = None
    if not isinstance(raw, dict) or not isinstance(raw.get("keep"), list):
        return []
    keep = set(int(i) for i in raw["keep"] if str(i).lstrip("-").isdigit())
    try:
        for i, why in (raw.get("dropped") or {}).items():
            io.open(os.path.join(HERE, "kino_material.log"), "a", encoding="utf-8").write("%s DROPPED [%s] %s | %s\n" % (
                time.strftime("%m-%d %H:%M:%S"), i, str(why)[:160], (L[int(i)]["text"][:120] if str(i).isdigit() and int(i) < len(L) else "")))
    except Exception:
        pass
    return [x for i, x in enumerate(L) if i in keep]


def auto_told(uid, say):
    """2026-10-24: a sent message that overlaps an untold item marks it told even when the model forgot the "told" field"""
    try:
        ws = set(re.findall(r"[a-z\u00e0-\u00ff']{5,}", str(say or "").lower()))
        if len(ws) < 4:
            return
        hit = []
        for x in items(uid):
            wx = set(re.findall(r"[a-z\u00e0-\u00ff']{5,}", x["text"].lower()))
            if wx and len(ws & wx) >= 0.4 * len(wx):
                hit.append(x["id"])
        if hit:
            told(uid, hit)
    except Exception:
        pass


def block(uid, lang="fr"):
    L = items(uid)[-8:]
    if not L:
        return ""
    L = sorted(L, key=lambda x: -x["t"])[:4]
    return ("THINGS YOU COULD TELL THEM (true, from today, yours - tell ONE when it fits the moment or when a short close hands you the "
            "floor; in your own words, with your opinion; then \"told\": [\"its id\"]; never two in a row, never as a list):\n" +
            "\n".join("- [%s, %s] %s" % (x["id"], x["kind"], x["text"]) for x in L))


def told(uid, ids):
    ids = set(str(i) for i in (ids or []))
    if not ids:
        return

    def f(d):
        for x in ((d.get("u") or {}).get(uid) or {}).get("items") or []:
            if x["id"] in ids:
                x["told"] = True
                x["told_t"] = time.time()
    _mut(f)


def stats(uid):
    u = (_load().get("u") or {}).get(uid) or {}
    I = u.get("items") or []
    return {"items": len(I), "told": sum(1 for x in I if x.get("told")), "last": u.get("t")}
