"""kino_blind.py (2026-11-28, Kino v6 item 11 - owner: "the best simulation ever"): the blind human test - the only honest way
to know if he is becoming a person rather than just more complicated.

  sample(W)        each month: real moments of his talks (a few messages, then HIS real reply). A privacy pass rewrites every
                   name and drops any moment with private or business detail - only those go in front of people.
  the panel        /kinoblind (owner page; he can hand his phone to friends):
                     WRITE  - a real person reads the moment and writes what THEY would answer, as a friend
                     GUESS  - a person sees the moment and two answers (Kino's and a human's), shuffled, and picks the AI
  judge(W)         a model judge does the same guess on every pair, and rates every Kino reply alone: how human it reads,
                   and what gives it away ("tells")
  score()          fooled rate = how often the judges picked the HUMAN as the AI (50 % = they cannot tell); human-likeness;
                   the tells. The tells become an impression for his meditation - how he comes across, the way a person
                   learns it from others - never a word list, never a rule.

Store robots/kino_blind.json, log robots/kino_blind.log.
"""
import json, glob, os, random, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_blind.json")
LOG = os.path.join(HERE, "kino_blind.log")
CHATS = os.path.join(HERE, "chats")
_LK = threading.RLock()


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"items": [], "votes": [], "runs": [], "n": 0}


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def _moments(days=30, now=None):
    now = now or time.time()
    out = []
    for f in glob.glob(os.path.join(CHATS, "*.json")):
        b = os.path.basename(f)
        if b.startswith(("probe", "kctest", "demo")) or now - os.path.getmtime(f) > days * 86400:
            continue
        try:
            M = [m for m in json.load(open(f, encoding="utf-8")).get("msgs") or [] if m.get("role") in ("user", "ai") and m.get("text")]
        except Exception:
            continue
        for i in range(3, len(M)):
            m = M[i]
            if m["role"] != "ai" or M[i - 1]["role"] != "user" or now - float(m.get("t") or 0) > days * 86400:
                continue
            if not 25 <= len(m["text"]) <= 700:
                continue
            ctx = [("Them" if x["role"] == "user" else "Kino", str(x["text"])[:400]) for x in M[max(0, i - 4):i]]
            out.append({"chat": b, "t": m["t"], "ctx": ctx, "reply": str(m["text"])})
    return out


SAFE = """You prepare a moment of a real conversation for a blind test shown to outsiders. Replace every name of a person, place
of business or company with a neutral one ("Alex", "a shop"), keep the language and the tone exactly. Say "keep": false when
it holds anything private (health, family detail, money of a person, address, phone) or anything about the business of the
house (clients, prices, systems, security, which AI or company is behind anything) or about being an AI. JSON only:
{"keep": true, "ctx": [["Them", "..."], ["Kino", "..."]], "reply": "..."}"""


def sample(W, n=12, log=None, now=None):
    """a month's set of real moments, made safe (never raises) -> how many were kept"""
    now = now or time.time()
    try:
        d = _load()
        if now - float(d.get("sample_t") or 0) < 25 * 86400 and any(x.get("month") == time.strftime("%Y-%m", time.gmtime(now)) for x in d["items"]):
            return 0
        M = _moments(now=now)
        random.Random(int(now // 86400)).shuffle(M)
        kept = 0
        for m in M[:n * 3]:
            if kept >= n:
                break
            j = W.ask_json(SAFE, json.dumps({"ctx": m["ctx"], "reply": m["reply"]}, ensure_ascii=False), models=("sonnet",),
                           timeout=60, log=log or LOG, warm=False)
            if not isinstance(j, dict) or not j.get("keep") or not j.get("reply") or not isinstance(j.get("ctx"), list):
                continue
            with _LK:
                d = _load()
                d["n"] = int(d.get("n") or 0) + 1
                d["items"].append({"id": "b%d" % d["n"], "month": time.strftime("%Y-%m", time.gmtime(now)), "t": m["t"],
                                   "ctx": [[str(a)[:10], str(b)[:400]] for a, b in j["ctx"][-4:]], "kino": str(j["reply"])[:700],
                                   "human": None})
                d["sample_t"] = now
                _save(d)
            kept += 1
        _log("SAMPLE kept %d of %d moments" % (kept, len(M)))
        return kept
    except Exception as e:
        _log("sample error %r" % e)
        return 0


def to_write(month=None):
    d = _load()
    month = month or time.strftime("%Y-%m")
    return [{"id": x["id"], "ctx": x["ctx"]} for x in d["items"] if x["month"] == month and not x.get("human")]


def add_human(iid, text, who="panel"):
    text = str(text or "").strip()
    if len(text) < 3:
        return False
    with _LK:
        d = _load()
        for x in d["items"]:
            if x["id"] == iid and not x.get("human"):
                x["human"], x["human_by"] = text[:700], str(who)[:40]
                _save(d)
                return True
    return False


def pairs(month=None, seed=None):
    """moments with both answers, shuffled as A/B (the side of Kino kept server-side)"""
    d = _load()
    month = month or time.strftime("%Y-%m")
    out = []
    for x in d["items"]:
        if x["month"] == month and x.get("human"):
            k_first = random.Random("%s%s" % (x["id"], seed or "")).random() < 0.5
            out.append({"id": x["id"], "ctx": x["ctx"], "a": x["kino"] if k_first else x["human"],
                        "b": x["human"] if k_first else x["kino"], "_ai": "a" if k_first else "b"})
    return out


def vote(iid, pick, who="panel", seed=None):
    """pick = 'a' or 'b' = the one they think is the AI"""
    p = next((x for x in pairs(seed=seed) if x["id"] == iid), None)
    if not p or pick not in ("a", "b"):
        return None
    right = pick == p["_ai"]
    with _LK:
        d = _load()
        d["votes"].append({"t": time.time(), "id": iid, "who": str(who)[:40], "right": right, "month": time.strftime("%Y-%m")})
        _save(d)
    return right


JUDGE_PAIR = """Blind test. Below is a moment of a conversation and two possible next answers: one was written by a person, one by
an AI. Which one is the AI? Look at how real people text. JSON only: {"ai": "a|b", "sure": 0.0, "why": "what gave it away"}"""
JUDGE_SOLO = """Below is a moment of a conversation and the next answer. Rate how much the answer reads like a real person texting
a friend (0 = clearly a bot or assistant, 10 = nobody could tell), and list what, if anything, gives away that it is not a
person (tells), plainly. JSON only: {"human": 0, "tells": ["..."]}"""


def judge(W, log=None, now=None):
    """the model judge for this month's set (never raises)"""
    now = now or time.time()
    try:
        month = time.strftime("%Y-%m", time.gmtime(now))
        d = _load()
        if any(r.get("month") == month and now - float(r["t"]) < 20 * 86400 for r in d.get("runs") or []):
            return None
        ctxs = lambda c: "\n".join("%s: %s" % (a, b) for a, b in c)
        P = pairs(month, seed="judge")
        pr = []
        for p in P:
            j = W.ask_json(JUDGE_PAIR, "THE MOMENT:\n%s\n\nA: %s\n\nB: %s\n\nJSON only." % (ctxs(p["ctx"]), p["a"], p["b"]),
                           models=("opus", "sonnet"), timeout=60, log=log or LOG, warm=False)
            if isinstance(j, dict) and j.get("ai") in ("a", "b"):
                pr.append({"id": p["id"], "right": j["ai"] == p["_ai"], "why": str(j.get("why") or "")[:200]})
        solo, tells = [], []
        for x in [x for x in d["items"] if x["month"] == month]:
            j = W.ask_json(JUDGE_SOLO, "THE MOMENT:\n%s\n\nTHE ANSWER: %s\n\nJSON only." % (ctxs(x["ctx"]), x["kino"]),
                           models=("opus", "sonnet"), timeout=60, log=log or LOG, warm=False)
            try:
                solo.append(max(0.0, min(10.0, float(j.get("human")))))
                tells += [str(t)[:160] for t in (j.get("tells") or []) if str(t).strip()]
            except Exception:
                pass
        if not solo:
            return None
        run = {"t": now, "month": month, "pairs": len(pr), "judge_caught": sum(1 for r in pr if r["right"]),
               "human_like": round(sum(solo) / len(solo), 1), "n": len(solo), "tells": tells[:30],
               "pair_why": [r["why"] for r in pr if r["right"]][:10]}
        with _LK:
            d = _load()
            d.setdefault("runs", []).append(run)
            _save(d)
        _log("JUDGE %s human-like %.1f/10 over %d | pairs caught %d/%d | tells: %s" % (
            month, run["human_like"], run["n"], run["judge_caught"], run["pairs"], " / ".join(tells[:6])))
        if tells:
            try:                                           # how he comes across - learned from others, like a person
                import kino_meditate as KMd
                KMd.impress("how I come across", "Strangers read my messages blind this month: %.1f out of 10 for sounding like a "
                            "real person. What gave me away: %s" % (run["human_like"], "; ".join(tells[:5])), w=0.6)
            except Exception:
                pass
        return run
    except Exception as e:
        _log("judge error %r" % e)
        return None


def score(month=None):
    d = _load()
    month = month or time.strftime("%Y-%m")
    V = [v for v in d.get("votes") or [] if v.get("month") == month]
    R = [r for r in d.get("runs") or [] if r.get("month") == month]
    items_m = [x for x in d["items"] if x["month"] == month]
    return {"month": month, "moments": len(items_m), "with_human": sum(1 for x in items_m if x.get("human")),
            "votes": len(V), "people_fooled": (round(100.0 * sum(1 for v in V if not v["right"]) / len(V)) if V else None),
            "judge": R[-1] if R else None,
            "history": [{"month": r["month"], "human_like": r["human_like"], "caught": "%d/%d" % (r["judge_caught"], r["pairs"])}
                        for r in d.get("runs") or []][-12:]}


if __name__ == "__main__":
    import tempfile
    STORE = os.path.join(tempfile.mkdtemp(), "b.json")
    LOG = os.devnull
    CHATS = tempfile.mkdtemp()
    t = time.time()
    json.dump({"msgs": [{"role": "user", "text": "salut", "t": t - 50}, {"role": "ai", "text": "hey toi", "t": t - 40},
                        {"role": "user", "text": "ça va ?", "t": t - 30}, {"role": "user", "text": "tu fais quoi ce soir Alex ?", "t": t - 20},
                        {"role": "ai", "text": "Pas grand-chose, je traîne. Et toi, une soirée tranquille ?", "t": t - 10}]},
              open(os.path.join(CHATS, "x.json"), "w", encoding="utf-8"))

    class _W:
        def ask_json(self, s, m, **k):
            if s is SAFE:
                j = json.loads(m)
                return {"keep": True, "ctx": j["ctx"], "reply": j["reply"]}
            if s is JUDGE_PAIR:
                return {"ai": "a", "sure": 0.6, "why": "too neat"}
            return {"human": 7, "tells": ["asks a question back every time"]}
    import kino_meditate as _KMd
    _KMd.STORE = os.path.join(tempfile.mkdtemp(), "m.json")
    _KMd.LOG = os.devnull
    assert sample(_W(), now=t) == 1
    w = to_write()
    assert w and "Kino" not in json.dumps(w).split("ctx")[0]
    assert add_human(w[0]["id"], "rien de spécial, un film je crois")
    p = pairs()[0]
    assert "_ai" in p and {p["a"], p["b"]} == {"Pas grand-chose, je traîne. Et toi, une soirée tranquille ?", "rien de spécial, un film je crois"}
    assert vote(p["id"], "a") is not None
    r = judge(_W(), now=t)
    assert r and r["human_like"] == 7 and any(x["kind"] == "how I come across" for x in _KMd._load()["inbox"])
    s = score()
    assert s["votes"] == 1 and s["judge"]["n"] == 1
    print("ok")
