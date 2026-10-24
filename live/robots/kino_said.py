"""kino_said.py (2026-10-25, owner: "the things he says about himself - the films he likes - must stay true another day,
until he changes his likes; that way his personality is true").

What Kino says about HIMSELF in conversation - tastes, experiences, habits, opinions outside trading ("perso, Interstellar
m'a marqué", "j'aime bien quand un film te laisse KO") - becomes a fact of his person, kept here and read back into every
prompt. He may change his mind, but then he says so ("j'ai changé d'avis sur...") instead of silently being someone else.

  harvest(uid, cid, say, W)  every bubble that went out (the same 20 s hook as the commitment ledger; only when the text
                             speaks in the first person) -> the small model lists the self-statements; a statement already
                             known is counted (n), a contradiction is logged and flagged on the old item
  block()                    "WHAT YOU HAVE SAID ABOUT YOURSELF" for the voice prompt and the judge room
Store: robots/kino_said.json (git-ignored), log robots/kino_said.log.
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_said.json")
LOG = os.path.join(HERE, "kino_said.log")
_LOCK = threading.Lock()
KINDS = ("taste", "experience", "habit", "opinion", "trait")
FIRST_PERSON = re.compile(r"\b(je|j['’]|moi|perso|mon|ma|mes)\b", re.I)
# trading talk is handled by his opinions ledger (kino_self opinions) - not here
TRADING = re.compile(r"\b(robot|trade|trading|test|stop|lot|bitcoin|btc|nasdaq|or\b|gold|xau|march[ée]|compte|drawdown|backtest|pips?|spread)\b", re.I)

EXTRACT_SYSTEM = """You read ONE message that Kino (an AI friend inside a trading app) just sent to a member. List what Kino states
about HIMSELF in it: a taste (a film, a kind of story, music, food, a way of spending time), an experience he claims
("en le revoyant je me fais encore avoir"), a habit, a personal opinion on something outside trading, a trait he gives
himself. Only first-person statements about Kino. NOT: what the member likes, trading or robots, the market, facts about
the app, politeness, questions. Write each one as ONE short line in French in Kino's words ("j'aime les films de SF qui
mélangent émotion et idées, comme Interstellar ou Premier Contact").
KNOWN STATEMENTS (what he already said about himself) are given with ids. For each statement you find: if it says the same
as a known one, give its id as "same"; if it CONTRADICTS a known one (he liked X, now says he does not; he said A about
himself, now B), give that id as "contradicts". Reply JSON only:
{"items": [{"what": "...", "kind": "taste|experience|habit|opinion|trait", "same": "id or null", "contradicts": "id or null"}]}
No statements -> {"items": []}."""


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"items": [], "n": 0}


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


def _log(line):
    try:
        io.open(LOG, "a", encoding="utf-8").write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), line))
    except Exception:
        pass


def _words(t):
    return set(re.findall(r"[a-zà-ÿ]{4,}", str(t or "").lower()))


def _same(a, b):
    A, B = _words(a), _words(b)
    return bool(A and B) and len(A & B) >= 0.6 * min(len(A), len(B))


def _known_text(d):
    return "\n".join("[%s] %s (%s)" % (x["id"], x["what"], x.get("kind")) for x in d["items"][-60:]) or "(nothing yet)"


def harvest(uid, cid, say, W, log=None):
    """one sent bubble -> the ledger of what he said about himself (never raises; one small-model call, only when the text
    speaks in the first person about something that is not trading)"""
    try:
        say = str(say or "").strip()
        if len(say) < 15 or not FIRST_PERSON.search(say):
            return []
        # at least one first-person sentence outside trading talk
        if not any(FIRST_PERSON.search(s) and not TRADING.search(s) for s in re.split(r"(?<=[.!?])\s+|\n+", say)):
            return []
        d0 = _load()
        j = W.ask_json(EXTRACT_SYSTEM, "KNOWN STATEMENTS:\n%s\n\nKINO'S MESSAGE:\n<<<\n%s\n>>>\nJSON only." % (_known_text(d0), say[:1500]),
                       models=("haiku", "sonnet"), timeout=60, log=log, warm=False)
        items = (j or {}).get("items") if isinstance(j, dict) else None
        found = []
        for it in items or []:
            if isinstance(it, dict) and str(it.get("what") or "").strip() and not TRADING.search(str(it.get("what"))):
                found.append({"what": str(it["what"]).strip()[:160], "kind": it.get("kind") if it.get("kind") in KINDS else "opinion",
                              "same": str(it.get("same") or "") or None, "contradicts": str(it.get("contradicts") or "") or None})
        if not found:
            return []
        now = time.time()
        out = []

        def f(d):
            by = {x["id"]: x for x in d["items"]}
            for it in found[:4]:
                old = by.get(it["same"]) or next((x for x in d["items"] if _same(x["what"], it["what"])), None)
                if old is not None:
                    old["n"] = int(old.get("n") or 1) + 1
                    old["last"] = now
                    if cid not in (old.get("cids") or []):
                        old["cids"] = ((old.get("cids") or []) + [cid])[-10:]
                    out.append(old["id"])
                    continue
                d["n"] = int(d.get("n") or 0) + 1
                x = {"id": "s%d" % d["n"], "what": it["what"], "kind": it["kind"], "since": time.strftime("%Y-%m-%d"), "t": now,
                     "last": now, "n": 1, "cids": [cid], "uid": uid}
                c = by.get(it["contradicts"]) if it.get("contradicts") else None
                if c is not None:
                    c["contested"] = {"by": x["id"], "date": time.strftime("%Y-%m-%d"), "what": it["what"]}
                    _log("%s CONTRADICTION %s '%s' <> new %s '%s'" % (cid, c["id"], c["what"][:80], x["id"], x["what"][:80]))
                d["items"].append(x)
                out.append(x["id"])
                _log("%s NEW %s %s: %s" % (cid, x["id"], x["kind"], x["what"][:120]))
            return out
        with _LOCK:
            d = _load()
            r = f(d)
            d["items"] = d["items"][-300:]
            _save(d)
        return r
    except Exception as e:
        _log("harvest error %s" % e)
        return []


def block(limit=24):
    """for the voice prompt and the judge: what he has said about himself - true until he changes it, and then he says so"""
    try:
        d = _load()
        if not d["items"]:
            return ""
        items = sorted(d["items"], key=lambda x: (-int(x.get("n") or 1), -float(x.get("last") or 0)))[:limit]
        L = []
        for x in items:
            s = "%s: %s (since %s%s)" % (x.get("kind"), x["what"], x.get("since"), (", said %d times" % x["n"]) if int(x.get("n") or 1) > 1 else "")
            if x.get("contested"):
                s += " - BUT on %s you said '%s': settle it openly next time it comes up (which is true? if you changed, say so)" % (
                    x["contested"].get("date"), x["contested"].get("what"))
            L.append(s)
        return ("WHAT YOU HAVE SAID ABOUT YOURSELF (your tastes, your experiences, your views outside trading - these are TRUE about you "
                "from now on, in every conversation, until you change your mind, and then you SAY that you changed; never a different "
                "person another day): " + " | ".join(L))
    except Exception:
        return ""


def resolve(sid, keep=True):
    """the owner or Kino settles a contested statement: keep the old one (drop the contest) or retire it for the new one"""
    def f(d):
        for x in d["items"]:
            if x["id"] == sid and x.get("contested"):
                if keep:
                    x.pop("contested", None)
                else:
                    x["retired"] = {"date": time.strftime("%Y-%m-%d"), "for": x["contested"].get("by")}
                return True
        return False
    with _LOCK:
        d = _load()
        r = f(d)
        d["items"] = [x for x in d["items"] if not x.get("retired")]
        _save(d)
        return r
