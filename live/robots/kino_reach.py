"""
Kino's reach - where in the world he can get things done (owner plan 2026-11-14, memory mt5_kino_world_helpers_plan).

Two kinds of helpers:
  remote  - calls, emails, forms, posting ads, research: matched by LANGUAGE (and time zone), any country
  local   - presence: matched by PLACE (same city first, then same country)
A mission needing presence somewhere with nobody there -> "not yet in your area": the remote part is done anyway,
the person joins the waitlist of their place, is offered the gig opt-in, and that place gets recruiting priority.

The owner is the default remote helper for France and the last resort - a profile here, not a hard-coded rule.
Store: kino_reach.json  {"waitlist": [...], "demand": {"country|city": {"n":, "last":, "what": [...]}}}
Helper profiles stay in kino_helpers.json "workers" (new fields: kind, langs, country, tz, payout).
"""
import json
import os
import re
import threading
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_reach.json")
LOG = os.path.join(HERE, "kino_reach.log")
_LK = threading.Lock()

OWNER_UID = "std"                    # the owner's gig account (his accounts: kino/std/expenses) - default remote helper for France
OWNER_PROFILE = {"name": "Matsy", "kind": "remote", "langs": ["fr", "en"], "country": "france", "city": "",
                 "note": "the owner - default remote helper for France, last resort; never present him as staff to a client"}


def _log(line):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _j():
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"waitlist": [], "demand": {}}


def _mut(fn):
    with _LK:
        d = _j()
        r = fn(d)
        tmp = STORE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
        return r


def norm(s):
    """'Viry-Châtillon ' -> 'viry chatillon' (places compared without accents/case/dashes)"""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


_LANGS = {"fr": r"fran[cç]|french|fr\b", "en": r"angl|english|en\b", "es": r"espa|spanish|es\b", "pt": r"portug|pt\b",
          "ar": r"arab|ar\b", "ln": r"lingala|ln\b", "sw": r"swahili|sw\b", "hi": r"hindi|hi\b", "de": r"allem|german|deutsch|de\b",
          "it": r"ital|it\b", "zh": r"chin|mandarin|zh\b", "wo": r"wolof|wo\b"}


def langs_of(text):
    t = str(text or "").lower()
    return [k for k, rx in _LANGS.items() if re.search(rx, t)]


def helpers():
    """every opted-in helper, as profiles (the owner always included as the France remote fallback)"""
    try:
        import kino_helpers as KH
        W = KH.workers()
    except Exception:
        W = {}
    out = {}
    for uid, w in W.items():
        p = dict(w)
        p["uid"] = uid
        p.setdefault("kind", "local" if w.get("city") else "remote")
        p["langs"] = p.get("langs") or ["fr"]
        out[uid] = p
    o = dict(out.get(OWNER_UID) or {})
    o.update(OWNER_PROFILE, uid=OWNER_UID, owner=True)
    o["kind"] = "both"                                  # remote for all France, on the ground around his home
    o["city"] = (out.get(OWNER_UID) or {}).get("city") or "Viry-Chatillon"
    out[OWNER_UID] = o
    return out


def match(lang="fr", country="", city="", presence=False, limit=5):
    """-> {"ok": bool, "who": [profiles best first], "why": str}
    presence: local helpers of that city, then that country. Otherwise remote (or local willing) speaking the language;
    the owner last, and only for France."""
    H = helpers()
    c, ci = norm(country), norm(city)
    lang = (lang or "fr")[:2].lower()

    def score(p):
        s = float(p.get("done") or 0) * 0.5 - float(p.get("declined") or 0) * 0.3
        return s
    if presence:
        same_city = [p for p in H.values() if not p.get("owner") and p.get("kind") in ("local", "both")
                     and ci and norm(p.get("city")) == ci]
        same_country = [p for p in H.values() if not p.get("owner") and p.get("kind") in ("local", "both")
                        and c and norm(p.get("country")) == c and p not in same_city]
        who = sorted(same_city, key=score, reverse=True) + sorted(same_country, key=score, reverse=True)
        if not who and ci and ci in norm(H[OWNER_UID].get("city")):
            who = [H[OWNER_UID]]                        # the owner around his own home, last
        if who:
            return {"ok": True, "who": who[:limit], "why": "%d local helper(s) in %s" % (len(who), city or country)}
        return {"ok": False, "who": [], "why": "nobody on the ground in %s yet" % (city or country or "that place")}
    who = [p for p in H.values() if not p.get("owner") and lang in (p.get("langs") or [])]
    who = sorted(who, key=lambda p: (p.get("kind") in ("remote", "both"), score(p)), reverse=True)
    if c in ("", "france") and lang == "fr":
        who.append(H[OWNER_UID])                        # the owner: France fallback, last
    if who:
        return {"ok": True, "who": who[:limit], "why": "%d remote helper(s) speaking %s" % (len(who), lang)}
    return {"ok": False, "who": [], "why": "no remote helper speaking %s yet" % lang}


def wait(uid, country, city, what, lang=""):
    """a person whose presence-mission nobody can do yet: on the waitlist of their place; the place gains priority"""
    key = "%s|%s" % (norm(country), norm(city))

    def f(d):
        d.setdefault("waitlist", []).append({"uid": uid, "country": country, "city": city, "what": str(what)[:200],
                                             "lang": lang, "t": time.time()})
        d["waitlist"] = d["waitlist"][-500:]
        dm = d.setdefault("demand", {}).setdefault(key, {"n": 0, "what": []})
        dm["n"] += 1
        dm["last"] = time.time()
        dm["what"] = (dm["what"] + [str(what)[:80]])[-5:]
        return dm["n"]
    n = _mut(f)
    _log("WAIT %s %s/%s n=%d %s" % (uid, country, city, n, str(what)[:80]))
    return "on the waitlist for %s (%d request(s) waiting there) - recruiting there now has priority" % (city or country, n)


def served(country, city):
    """helpers arrived in a place: who was waiting there (to tell them it's open now)"""
    c, ci = norm(country), norm(city)
    return [w for w in _j().get("waitlist") or [] if norm(w.get("country")) == c and (not ci or norm(w.get("city")) == ci)]


def priorities(limit=6):
    """places where people wait and nobody is on the ground - where local recruiting goes first"""
    D = _j().get("demand") or {}
    out = []
    for key, dm in D.items():
        country, city = (key.split("|") + [""])[:2]
        if match(country=country, city=city, presence=True)["ok"]:
            continue
        out.append((dm.get("n", 0), dm.get("last", 0), country, city, dm.get("what") or []))
    out.sort(reverse=True)
    return out[:limit]


def coverage():
    """country -> {"local": n, "remote": n, "cities": {city: n}, "waiting": n}"""
    cov = {}
    for p in helpers().values():
        if p.get("owner"):
            continue
        c = norm(p.get("country")) or "unknown"
        e = cov.setdefault(c, {"local": 0, "remote": 0, "cities": {}, "waiting": 0})
        e["remote" if p.get("kind") == "remote" else "local"] += 1
        if p.get("city"):
            e["cities"][p["city"]] = e["cities"].get(p["city"], 0) + 1
    for key, dm in (_j().get("demand") or {}).items():
        c = key.split("|")[0] or "unknown"
        cov.setdefault(c, {"local": 0, "remote": 0, "cities": {}, "waiting": 0})["waiting"] += dm.get("n", 0)
    return cov


def block():
    """for the desk: what the reach is today and where recruiting goes first"""
    cov = coverage()
    lines = ["REACH (worldwide - never assume France): helpers by country: " + ("; ".join(
        "%s: %d on the ground (%s), %d remote%s" % (c, e["local"], ", ".join("%s %d" % kv for kv in list(e["cities"].items())[:4]) or "-",
                                                     e["remote"], (", %d waiting" % e["waiting"]) if e["waiting"] else "")
        for c, e in list(cov.items())[:10]) or "none yet beyond the owner (remote, France, French/English)")]
    pr = priorities()
    if pr:
        lines.append("RECRUIT FIRST where people wait and nobody is there: " + "; ".join(
            "%s%s (%d waiting: %s)" % (city + ", " if city else "", country, n, " / ".join(w[:40] for w in what[-2:]))
            for n, _, country, city, what in pr))
    return "\n".join(lines)


if __name__ == "__main__":
    print(block())
    print(match(lang="fr", country="france"))
    print(match(country="congo", city="Brazzaville", presence=True))
