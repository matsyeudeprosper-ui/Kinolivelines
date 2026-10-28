"""kino_beliefs.py (2026-10-28, KINO_V3_HUMAN.md engine 4) - what he thinks, how sure, and when he changed his mind.

People hold opinions with a degree of certainty. Saying the same thing again (and seeing it hold) makes it firmer; being
pushed back on, or seeing it fail, makes it shakier; saying the opposite is felt as a change of mind - you either resist
it or you own it ("I said X on Monday, I was wrong"). Kino had none of this: each message was decided fresh, so he called
the owner's lot ladder "revenge trading", apologised, then flagged it again.

Here, after each message he sends, a small pass reads the STANCES in it (judgements on trading, methods, markets, the
member's choices, himself) against what he already believes: same -> firmer, opposite -> a recorded change of mind (old
stance kept in his history), new -> a fresh belief, unsure. The one mind sees what he believes near the current topic,
how sure he is, and his recent changes of mind. Beliefs about one member's ways are kept under that member (never shown
to another one). Store robots/kino_beliefs.json (git-ignored).
"""
import json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_beliefs.json")
_LK = threading.Lock()

SYSTEM = """You read one message Kino (an AI friend who trades with the member) just sent, and list the STANCES in it:
his judgements and opinions - on trading, a method, a rule, a market, the member's choices, robots, himself. Not facts,
not numbers, not plans: what he THINKS (e.g. "raising the lot after a loss is risky", "the flip after a stop is sound").
Compare each with HIS KNOWN BELIEFS (ids). JSON only:
{"stances": [{"claim": "short, first person, general", "topic": "2-4 words", "same": "id or null", "opposite": "id or null",
 "firmness": 0.0-1.0 (how firmly it was said)}]}
Empty list if the message holds no opinion. At most 3."""


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"n": 0, "items": [], "shifts": []}


def _save(d):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, STORE)


def _visible(x, uid):
    return x.get("uid") in (None, "", uid)


def harvest(W, uid, cid, say, about_member=None, log=None):
    """one sent message -> beliefs firmed / changed / added (never raises)"""
    try:
        say = " ".join(str(say or "").split())
        if len(say) < 60:
            return
        d = _load()
        known = [x for x in d["items"] if _visible(x, uid) and x.get("alive", True)][-40:]
        kt = "\n".join("[%s] %s (topic: %s, certainty %.1f)" % (x["id"], x["claim"], x.get("topic"), x["c"]) for x in known) or "(none yet)"
        j = W.ask_json(SYSTEM, "HIS KNOWN BELIEFS:\n%s\n\nHIS MESSAGE:\n<<<\n%s\n>>>\n%s\nJSON only." % (
            kt, say[:1500], ("THE MEMBER'S LAST MESSAGE (context): " + str(about_member)[:400]) if about_member else ""),
            models=("haiku", "sonnet"), timeout=60, log=log, warm=False)
        S = (j or {}).get("stances") if isinstance(j, dict) else None
        if not S:
            return
        now = time.time()
        with _LK:
            d = _load()
            by = {x["id"]: x for x in d["items"]}
            for s in S[:3]:
                if not isinstance(s, dict) or not str(s.get("claim") or "").strip():
                    continue
                fm = max(0.1, min(1.0, float(s.get("firmness") or 0.5)))
                same, opp = by.get(str(s.get("same") or "")), by.get(str(s.get("opposite") or ""))
                if same is not None and _visible(same, uid):
                    same["c"] = round(same["c"] + (1 - same["c"]) * 0.25 * fm, 3)      # said again: firmer, never certain
                    same["n"] = int(same.get("n") or 1) + 1
                    same["last"] = now
                    continue
                d["n"] = int(d.get("n") or 0) + 1
                x = {"id": "b%d" % d["n"], "claim": str(s["claim"]).strip()[:200], "topic": str(s.get("topic") or "")[:40],
                     "c": round(0.35 + 0.3 * fm, 3), "n": 1, "since": time.strftime("%Y-%m-%d"), "t": now, "last": now,
                     "uid": uid if re.search(r"\b(your|his|ton|ta|tes|son|sa|ses)\b", str(s["claim"]).lower()) else None,
                     "alive": True}
                if opp is not None and _visible(opp, uid) and opp.get("alive", True):
                    opp["alive"] = False                                                 # a change of mind: the old stance goes to history
                    d.setdefault("shifts", []).append({"t": now, "from": opp["claim"], "to": x["claim"], "topic": x["topic"],
                                                       "old_c": opp["c"], "uid": x["uid"] or opp.get("uid"), "cid": cid})
                    x["uid"] = x["uid"] or opp.get("uid")
                d["items"].append(x)
                by[x["id"]] = x
            d["items"] = [x for x in d["items"] if x.get("alive", True)][-200:] + [x for x in d["items"] if not x.get("alive", True)][-100:]
            d["shifts"] = (d.get("shifts") or [])[-60:]
            _save(d)
    except Exception:
        pass


def _words(t):
    return set(re.findall(r"[a-zà-ÿ]{4,}", str(t or "").lower()))


def block(uid, context, limit=6):
    """what he believes near the current topic (word overlap with the live talk) + his recent changes of mind"""
    d = _load()
    cw = _words(context)
    A = [x for x in d.get("items") or [] if x.get("alive", True) and _visible(x, uid)]
    if not A:
        return ""
    sc = lambda x: len(cw & _words(x["claim"] + " " + (x.get("topic") or ""))) + 0.3 * x["c"] + 0.1 * min(5, int(x.get("n") or 1))
    A = sorted(A, key=lambda x: -sc(x))[:limit]
    word = lambda c: "sûr" if c >= 0.8 else "assez sûr" if c >= 0.6 else "pas très sûr"
    L = ["Ce que tu penses (d'après ce que tu as dit toi-même ; ta certitude entre parenthèses) : " + " | ".join(
        "%s (%s, dit %d fois)" % (x["claim"], word(x["c"]), int(x.get("n") or 1)) for x in A)]
    sh = [s for s in d.get("shifts") or [] if s.get("uid") in (None, "", uid) and time.time() - float(s["t"]) < 14 * 86400][-3:]
    if sh:
        L.append("Tes changements d'avis récents : " + " | ".join(
            "le %s, sur %s : avant « %s », maintenant « %s »" % (time.strftime("%d/%m", time.gmtime(float(s["t"]))), s.get("topic") or "-",
                                                               s["from"][:100], s["to"][:100]) for s in sh))
    return "\n".join(L)
