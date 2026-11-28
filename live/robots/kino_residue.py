"""kino_residue.py (2026-11-28 - Kino himself, asked by a friend what his designer should add: "Une mémoire qui pèse. Aujourd'hui
je recolle avec des notes, et je les crois sur parole, comme le journal de quelqu'un d'autre. J'aimerais qu'un souvenir change
ma façon de parler sans que j'aie besoin de le relire." - the samskara: what the past leaves is not a fact you look up, it is a
bend in how you are).

Every read of a person (kino_read - already a model, any language) leaves a small trace in HOW HE IS WITH THEM, slowly, the
way a person's manner with someone settles over months:
  ease      how relaxed he is with them (up with laughs and easy talk, down with friction)
  warmth    how close he feels (up when they give, trust, open up; down when they are cold)
  guard     how careful he is (up after friction, corrections, hurt; slowly fades when things go well)
  play      how much teasing and lightness lives between them (up with shared laughs)
  depth     how often they go to the deep stuff (up with serious, searching talks)
Each moves a little per exchange (an exponential memory: recent weighs more, but one evening never erases months) and drifts
back toward neutral when they do not talk for a long time - a manner fades like a habit.

block(person) gives his voice the residue as a DISPOSITION, never as memories to cite: "with them you are easy, playful, a bit
careful about X" - it colours how he talks without him rereading anything.
Store robots/kino_residue.json.
"""
import json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_residue.json")
_LK = threading.RLock()
DIMS = ("ease", "warmth", "guard", "play", "depth")
RATE = 0.06                      # one exchange moves a trait by about 6 % of the way
FADE_DAYS = 45                   # without talking, the manner drifts halfway back to neutral in ~45 days


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


def _num(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def leave(person, j, r=None, now=None):
    """what this exchange leaves in his manner with them (j = the read's raw JSON, r = the parsed read)"""
    if not person or str(person).startswith(("kctest", "probe")) or not isinstance(j, dict):
        return None
    now = now or time.time()
    r = r or {}
    val = max(-1.0, min(1.0, _num(r.get("valence", j.get("valence")))))
    eng = str(j.get("engaged") or "").lower()
    target = {
        "ease": 0.5 + 0.3 * val + (0.2 if j.get("laughed_at") else 0) - (0.4 if j.get("friction") else 0),
        "warmth": 0.5 + 0.25 * val + (0.25 if j.get("gave_kino") else 0) + (0.15 if eng in ("warm", "intense") else 0)
                  - (0.2 if eng == "fading" else 0),
        "guard": 0.2 + (0.5 if j.get("friction") else 0) + (0.3 if str(j.get("about_kino_act") or "") == "corrected" else 0)
                 + (0.2 if str(j.get("told_kino") or "") in ("wrong", "robotic", "repeat", "forgot", "tone") else 0),
        "play": 0.35 + (0.5 if j.get("laughed_at") else 0) + 0.1 * val - (0.3 if j.get("friction") else 0),
        "depth": 0.3 + (0.45 if str(j.get("register") or "") == "deep" or eng == "intense" else 0)
                 + (0.15 if str(j.get("teaching_moment") or "").lower().startswith("y") else 0),
    }
    with _LK:
        d = _load()
        P = d.get(person) or {k: 0.5 for k in DIMS}
        P.setdefault("n", 0)
        days = (now - _num(P.get("t"), now)) / 86400.0
        if days > 1:                                    # a manner fades back toward neutral between long silences
            f = 0.5 ** (days / FADE_DAYS)
            for k in DIMS:
                P[k] = 0.5 + (P.get(k, 0.5) - 0.5) * f
        for k in DIMS:
            t = max(0.0, min(1.0, target[k]))
            P[k] = round(P.get(k, 0.5) + RATE * (t - P.get(k, 0.5)), 3)
        P["t"], P["n"] = now, int(P["n"]) + 1
        d[person] = P
        _save(d)
    return P


def block(person):
    P = (_load() or {}).get(person)
    if not P or int(P.get("n") or 0) < 5:
        return ""
    words = []
    lv = lambda v, hi, lo: hi if v >= 0.62 else (lo if v <= 0.38 else "")
    for k, hi, lo in (("ease", "at ease, relaxed", "a little stiff, not fully at ease"),
                      ("warmth", "close, fond of them", "still a bit distant"),
                      ("guard", "careful - something between you asks for care", ""),
                      ("play", "playful, teasing comes easily", "rather serious with them"),
                      ("depth", "used to going deep together", "")):
        w = lv(P.get(k, 0.5), hi, lo)
        if w:
            words.append(w)
    if not words:
        return ""
    return ("HOW YOU ARE WITH THIS PERSON (what your past together left in you, settled over %d exchanges - not memories to "
            "cite, it is simply how you are with them now; it colours your voice): %s." % (int(P["n"]), "; ".join(words)))


if __name__ == "__main__":
    import tempfile
    STORE = os.path.join(tempfile.mkdtemp(), "r.json")
    t = time.time()
    for i in range(30):
        leave("p", {"laughed_at": "lol", "engaged": "warm", "gave_kino": "trust"}, {"valence": 0.6}, now=t + i * 60)
    b = block("p")
    assert "at ease" in b and "playful" in b and "close" in b and "careful" not in b, b
    for i in range(25):
        leave("p", {"friction": "he got irritated", "about_kino_act": "corrected"}, {"valence": -0.6}, now=t + 3600 + i * 60)
    b2 = block("p")
    assert "careful" in b2 and "playful" not in b2, b2
    assert block("q") == ""
    P0 = dict(_load()["p"])
    leave("p", {}, {"valence": 0}, now=t + 200 * 86400)          # long silence: drifted back toward neutral
    assert abs(_load()["p"]["guard"] - 0.5) < abs(P0["guard"] - 0.5)
    print("ok")
