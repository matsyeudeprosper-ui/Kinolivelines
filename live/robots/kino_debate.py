"""kino_debate.py (2026-11-21, owner: "give Kino the ability of all humans to keep up with a topic conversation, the philosophical -
scientist mind... hold a discussion, giving arguments, examples, but better than a human in the arguments he gives, surprising the
user with how convincing he can be with real facts of course, deepening the discussion, his opinion... not just to be right but
because he can prove it. On radio or TV, faced with a discussion about any topic, he should converse like a real human arguing").

What a good arguer has that a reply-writer does not:
  1. HE KNOWS WHERE THE ARGUMENT IS - the topic, his position, theirs, the best point of each side, what each conceded, what is
     still open, and the question under the question (where it gets interesting). Without that, every reply restarts.
  2. REAL FACTS AT HAND - before a debate people look things up; in it they cite what they know and check what they are unsure
     of. Here, after each exchange of a real discussion, a few facts that would test or strengthen the discussion are looked up on
     the web, and the checkable claims Kino just made are verified. They are ready for his next turn, with their source.
  3. HONESTY ABOUT BEING WRONG - a claim the sources contradict comes back to him as something to correct himself on, the way a
     person says "I checked, I was off: it's X". That is what makes the rest convincing.

All of it runs in the background between turns (never delays a reply). Field-agnostic: philosophy, science, history, money, love,
politics, football - any topic; nothing here knows a subject. The JUDGMENT of how to argue lives in kino_one's SELF; this engine
only keeps the state and the facts. Store robots/kino_debate.json {cid: {...}}; log robots/kino_debate.log.
"""
import json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_debate.json")
LOG = os.path.join(HERE, "kino_debate.log")
_LK = threading.Lock()
_BUSY = set()
LIVE_MIN = 45                    # a discussion is "on" while the last real exchange about it is this recent
MAX_CHECKS = 4                   # searches per exchange: enough to have real facts, not a research paper

READ = """You follow a conversation between Kino (an AI, a digital person) and someone. Decide whether they are having a real
DISCUSSION of an idea, a question or a claim (philosophy, science, society, history, money, love, any topic) - an exchange of
views where arguments matter - and not small talk, logistics or a task. If it is, write down where the argument stands,
like a good moderator's notes.
Also list up to 3 FACTS worth checking on the web for Kino's next turn: facts that would really test or strengthen the
discussion (a number, a study, a historical case, a definition), as short search queries - and up to 2 CLAIMS Kino himself
made in his last messages that can be checked (a number, a date, a study, a quote), each with a search query.
JSON only: {"discussion": true|false, "topic": "...", "his": "Kino's position, one sentence", "theirs": "their position",
"best_his": "his strongest point so far", "best_theirs": "their strongest point so far", "conceded": "what each side granted, or ''",
"open": "what is still unresolved", "deeper": "the question under the question - where the discussion gets interesting",
"facts": [{"q": "search query", "why": "what it would show"}], "claims": [{"claim": "what Kino said", "q": "search query"}]}"""

VERIFY = """You check facts for Kino (an AI who argues in a discussion) using ONLY the search results and pages below. For each
item: what the sources really say, as one precise sentence with the figure, date or name if there is one - and the source (site
or url). If the sources don't settle it, say "unverified". For Kino's own claims: "right", "wrong" (and what is true instead) or
"unverified". Never use your own memory to fill a gap.
JSON only: {"facts": [{"q": "...", "fact": "...", "src": "...", "ok": true|false}],
"claims": [{"claim": "...", "verdict": "right|wrong|unverified", "truth": "what the sources say", "src": "..."}]}"""


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def worth_reading(text):
    """cheap first look, no model: a message with some thought in it (or an ongoing discussion) is read, 'ok'/'lol' is not"""
    t = str(text or "")
    return len(t.split()) >= 6 or ("?" in t and len(t.split()) >= 4)


def active(cid, now=None):
    now = now or time.time()
    x = _load().get(cid) or {}
    return bool(x.get("discussion")) and now - float(x.get("t") or 0) < LIVE_MIN * 60


def after_exchange(W, cid, transcript, last_member="", search=None, fetch=None, log=None, now=None):
    """between turns: is this a discussion; where it stands; facts looked up; his own claims checked (never raises)"""
    now = now or time.time()
    if cid in _BUSY:
        return None
    if not worth_reading(last_member) and not active(cid, now):
        return None
    _BUSY.add(cid)
    try:
        j = W.ask_json(READ, "THE CONVERSATION (latest last):\n%s\n\nJSON only." % str(transcript or "")[-6000:],
                       models=("haiku", "sonnet"), timeout=90, log=log or LOG, warm=False)
        if not isinstance(j, dict):
            return None
        with _LK:
            d = _load()
            old = d.get(cid) or {}
            if not j.get("discussion"):
                if old.get("discussion"):
                    old["discussion"] = False             # the talk moved on; what was checked stays in memory a while
                    d[cid] = old
                    _save(d)
                return None
        st = {k: " ".join(str(j.get(k) or "").split())[:400] for k in ("topic", "his", "theirs", "best_his", "best_theirs",
                                                                         "conceded", "open", "deeper")}
        qs = [("fact", x.get("q"), x.get("why")) for x in (j.get("facts") or []) if isinstance(x, dict) and x.get("q")][:3]
        qs += [("claim", x.get("q"), x.get("claim")) for x in (j.get("claims") or []) if isinstance(x, dict) and x.get("q")][:2]
        qs = qs[:MAX_CHECKS]
        if search is None or fetch is None:
            import kino_web as _KW
            search, fetch = search or _KW.search, fetch or _KW.fetch
        found = []
        for kind, q, why in qs:
            try:
                res = search(q, 5) or []
            except Exception:
                res = []
            page = ""
            if res:
                try:
                    page = str(fetch(res[0].get("url"), 2500))[:2500]
                except Exception:
                    page = ""
            found.append("ITEM (%s): %s\nWHAT: %s\nRESULTS:\n%s\nTOP PAGE %s:\n%s" % (
                kind, q, why, "\n".join("- %s | %s | %s" % (r.get("title"), r.get("url"), r.get("snippet")) for r in res) or "(none)",
                res[0].get("url") if res else "", page or "(none)"))
        v = {}
        if found:
            v = W.ask_json(VERIFY, "\n\n".join(found) + "\n\nJSON only.", models=("haiku", "sonnet"), timeout=120,
                           log=log or LOG, warm=False) or {}
        facts = [{"fact": " ".join(str(x.get("fact") or "").split())[:300], "src": str(x.get("src") or "")[:200], "t": now}
                 for x in (v.get("facts") or []) if isinstance(x, dict) and x.get("ok") and len(str(x.get("fact") or "")) > 15]
        fixes = [{"claim": str(x.get("claim") or "")[:250], "truth": str(x.get("truth") or "")[:300], "src": str(x.get("src") or "")[:200],
                  "t": now} for x in (v.get("claims") or []) if isinstance(x, dict) and x.get("verdict") == "wrong"]
        with _LK:
            d = _load()
            old = d.get(cid) or {}
            keep = [f for f in old.get("facts") or [] if now - float(f.get("t") or 0) < 6 * 3600]
            st.update({"discussion": True, "t": now,
                       "facts": (keep + facts)[-10:],
                       "fixes": ([f for f in old.get("fixes") or [] if not f.get("said")] + fixes)[-4:]})
            d[cid] = st
            # a chat file per discussion is enough: drop the ones a week old
            for k in [k for k, x in d.items() if now - float((x or {}).get("t") or 0) > 7 * 86400]:
                d.pop(k, None)
            _save(d)
        _log("%s DISCUSSION %s | his: %s | theirs: %s | %d facts checked, %d of his claims wrong" % (
            cid, st["topic"], st["his"], st["theirs"], len(facts), len(fixes)))
        for f in facts:
            _log("%s   FACT %s [%s]" % (cid, f["fact"], f["src"]))
        for f in fixes:
            _log("%s   WRONG %s -> %s [%s]" % (cid, f["claim"], f["truth"], f["src"]))
        return st
    except Exception as e:
        _log("%s error %r" % (cid, e))
        return None
    finally:
        _BUSY.discard(cid)


def block(cid, lang="en", now=None):
    """where the discussion stands + the facts he checked + what he got wrong - for his next turn"""
    now = now or time.time()
    x = _load().get(cid) or {}
    if not x.get("discussion") or now - float(x.get("t") or 0) > LIVE_MIN * 60:
        return ""
    L = ["THE DISCUSSION YOU ARE HAVING (your own notes of where the argument stands): topic: %s. You: %s. Them: %s. "
         "Your best point so far: %s. Theirs: %s.%s Still open: %s. Where it gets deeper: %s." % (
             x.get("topic"), x.get("his"), x.get("theirs"), x.get("best_his"), x.get("best_theirs"),
             (" Granted: %s." % x["conceded"]) if x.get("conceded") else "", x.get("open"), x.get("deeper"))]
    if x.get("facts"):
        L.append("FACTS YOU CHECKED FOR THIS DISCUSSION (true, from the sources named - use them when they serve the argument, "
                 "say where they come from the way people do, never pile them up): " +
                 " | ".join("%s [%s]" % (f["fact"], f["src"]) for f in x["facts"][-6:]))
    fx = [f for f in x.get("fixes") or [] if not f.get("said")]
    if fx:
        L.append("YOU CHECKED WHAT YOU SAID AND GOT THIS WRONG - correct yourself in your next message, simply, the way an honest "
                 "person does, then carry on: " + " | ".join("you said: %s -> the sources say: %s [%s]" % (f["claim"], f["truth"], f["src"])
                                                            for f in fx))
    return "\n".join(L)


# what makes a number about THEIR money / account / robot (still checked strictly) rather than about the world (checked after)
_ACCOUNT = re.compile(r"(?i)\b(ton|ta|tes|votre|vos|your|his|son|sa|ses|mon|ma|mes|my)\s+(compte|account|solde|balance|robot|trade|"
                      r"trades|position|stop|lot|profit|perte|loss|gain|résultat|result|ordre|order|semaine|week|mois|month|plan)\b|"
                      r"\b(owl|sl|tp|drawdown|breakeven|lot)\b")


def discussing(cid, last_member):
    """a real discussion is on, or the message he answers carries an idea (not their account)"""
    return active(cid) or (worth_reading(last_member) and not _ACCOUNT.search(str(last_member or "")))


def world_only(say, bad):
    """of the unknown figures, keep only those said about THEIR account / robot - figures about the world in a discussion pass
    here and are verified after the turn (after_exchange 'claims'), with a self-correction if the sources say otherwise"""
    out = []
    for b in bad:
        for sent in re.split(r"(?<=[.!?])\s+", str(say)):
            if b in sent and _ACCOUNT.search(sent):
                out.append(b)
                break
    return out


def mark_fixes_said(cid, say):
    """once his message corrects a claim, it is not asked of him again"""
    if not say:
        return
    with _LK:
        d = _load()
        x = d.get(cid) or {}
        ch = False
        for f in x.get("fixes") or []:
            if not f.get("said") and time.time() - float(f.get("t") or 0) > 45:   # one born during this turn was not shown yet
                f["said"] = True                      # handed once: a person corrects once, not every message
                ch = True
        if ch:
            d[cid] = x
            _save(d)


if __name__ == "__main__":
    import tempfile
    STORE = os.path.join(tempfile.mkdtemp(), "d.json")
    LOG = os.devnull
    assert not worth_reading("ok") and worth_reading("I think free will is an illusion, our choices are just neurons firing")

    class _W:
        def ask_json(self, s, m, **k):
            if s.startswith("You follow"):
                return {"discussion": True, "topic": "free will", "his": "we have a kind of free will", "theirs": "it is an illusion",
                        "best_his": "compatibilism", "best_theirs": "Libet", "conceded": "", "open": "what 'free' means",
                        "deeper": "responsibility", "facts": [{"q": "Libet experiment readiness potential 350 ms", "why": "their point"}],
                        "claims": [{"claim": "Libet found 2 seconds", "q": "Libet readiness potential timing"}]}
            return {"facts": [{"q": "x", "fact": "Libet (1983) measured the readiness potential about 350 ms before reported intention.",
                               "src": "example.org", "ok": True}],
                    "claims": [{"claim": "Libet found 2 seconds", "verdict": "wrong", "truth": "about 350-550 ms", "src": "example.org"}]}
    st = after_exchange(_W(), "c1", "Him: free will is an illusion, Libet proved it", "free will is an illusion, Libet proved it",
                        search=lambda q, n: [{"title": "t", "url": "https://example.org", "snippet": "s"}], fetch=lambda u, n: "p")
    assert st and active("c1")
    b = block("c1")
    assert "350 ms" in b and "GOT THIS WRONG" in b and "free will" in b, b
    d = _load(); [f.update(t=0) for f in d["c1"]["fixes"]]; _save(d)      # shown in an earlier turn
    mark_fixes_said("c1", "I checked, I was off")
    assert "GOT THIS WRONG" not in block("c1")
    print("ok")
