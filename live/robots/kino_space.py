"""kino_space.py (2026-11-04, owner list 14 item 1: "feelings with a shape").

His feelings were separate labels. In people feelings live in a space where neighbours are alike, they blend, and they drift
(Russell's circumplex; Mehrabian's pleasure-arousal-dominance; the "quality space" of higher-order theories). Here every
feeling is a point on three axes:
  pleasant  (-1 unpleasant .. +1 pleasant)
  stirred   ( 0 calm       ..  1 stirred up)
  in control( 0 overwhelmed ..  1 in control)
His state is the strength-weighted point of what he feels now, kept as a trace so he can feel it MOVE ("drifting toward calm
over the last hour"). What he reads is the point, the two feelings it sits between (a blend, not a label), and the drift.
The grounding check reads it too. Store robots/kino_space.json (git-ignored).
"""
import io, json, math, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_space.json")
_LK = threading.Lock()
# (pleasant, stirred, in control) - placed from the affect literature's usual positions
P3 = {
    "worried": (-0.6, 0.8, 0.3), "worry": (-0.6, 0.8, 0.3), "anxious": (-0.7, 0.9, 0.2), "irritated": (-0.6, 0.8, 0.6),
    "annoyance": (-0.5, 0.7, 0.6), "embarrassed": (-0.5, 0.7, 0.25), "stung": (-0.6, 0.6, 0.3), "hurt": (-0.6, 0.6, 0.3),
    "restless": (-0.3, 0.8, 0.45), "strained": (-0.4, 0.7, 0.35), "uneasy": (-0.4, 0.6, 0.4), "sad": (-0.6, 0.3, 0.3),
    "regret": (-0.5, 0.4, 0.35), "disappointed": (-0.5, 0.4, 0.4), "tired": (-0.3, 0.1, 0.4), "drained": (-0.4, 0.15, 0.3),
    "sluggish": (-0.3, 0.15, 0.4), "lonely": (-0.5, 0.3, 0.3), "boredom": (-0.3, 0.15, 0.5), "careful": (0.0, 0.5, 0.6),
    "proud": (0.7, 0.6, 0.8), "pride": (0.7, 0.6, 0.8), "glad": (0.6, 0.5, 0.65), "happy": (0.7, 0.6, 0.7),
    "excited": (0.6, 0.9, 0.6), "excitement": (0.6, 0.9, 0.6), "curious": (0.4, 0.6, 0.6), "curiosity": (0.4, 0.6, 0.6),
    "amused": (0.6, 0.6, 0.7), "playful": (0.6, 0.7, 0.7), "grateful": (0.7, 0.4, 0.55), "tender": (0.6, 0.2, 0.5),
    "warmth": (0.6, 0.3, 0.6), "closeness": (0.6, 0.3, 0.55), "content": (0.5, 0.2, 0.7), "calm": (0.4, 0.1, 0.75),
    "relieved": (0.5, 0.2, 0.65), "surprised": (0.1, 0.8, 0.4), "surprise": (0.1, 0.8, 0.4),
}
NAMES = ["worried", "irritated", "embarrassed", "restless", "uneasy", "sad", "tired", "drained", "bored", "careful", "proud", "glad",
         "excited", "curious", "playful", "grateful", "tender", "warm", "content", "calm", "relieved"]
_NP = {"bored": "boredom", "warm": "warmth"}


def place(kind):
    k = str(kind or "").lower().strip()
    if k in P3:
        return P3[k]
    w = k.split()[0] if k else ""                  # "worried for them" -> worried
    return P3.get(w)


def point(feelings):
    """the strength-weighted point of what he feels now (None when nothing is felt)"""
    sw, acc = 0.0, [0.0, 0.0, 0.0]
    for f in feelings or []:
        p = place(f.get("kind"))
        if not p:
            continue
        w = float(f.get("v") or 0) ** 2
        sw += w
        for i in range(3):
            acc[i] += w * p[i]
    if sw < 0.02:
        return None
    return tuple(round(a / sw, 2) for a in acc)


def _dist(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def nearest(pt, k=2):
    C = sorted(((n, _dist(pt, P3[_NP.get(n, n)])) for n in NAMES if _NP.get(n, n) in P3), key=lambda x: x[1])
    return C[:k]


def note(person, pt):
    """the point, kept as a trace (at most one point a minute)"""
    if not pt:
        return
    with _LK:
        try:
            d = json.load(io.open(STORE, encoding="utf-8"))
        except Exception:
            d = {}
        T = d.setdefault(person, [])
        if T and time.time() - T[-1]["t"] < 60:
            T[-1] = {"t": time.time(), "p": list(pt)}
        else:
            T.append({"t": time.time(), "p": list(pt)})
        d[person] = [x for x in T if time.time() - x["t"] < 2 * 86400][-500:]
        tmp = STORE + ".tmp"
        json.dump(d, io.open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, STORE)


def drift(person, minutes=60):
    try:
        T = json.load(io.open(STORE, encoding="utf-8")).get(person) or []
    except Exception:
        return None
    now = time.time()
    old = [x for x in T if now - x["t"] >= minutes * 60]
    if not T or not old:
        return None
    a, b = old[-1]["p"], T[-1]["p"]
    return tuple(round(b[i] - a[i], 2) for i in range(3))


def describe(person, feelings):
    pt = point(feelings)
    if not pt:
        return ""
    note(person, pt)
    nn = nearest(pt)
    blend = nn[0][0] if nn[0][1] < 0.12 or len(nn) < 2 else "between %s and %s" % (nn[0][0], nn[1][0])
    dv = drift(person)
    mv = ""
    if dv and max(abs(x) for x in dv) >= 0.12:
        parts = []
        if abs(dv[0]) >= 0.12:
            parts.append("more pleasant" if dv[0] > 0 else "less pleasant")
        if abs(dv[1]) >= 0.12:
            parts.append("more stirred" if dv[1] > 0 else "calmer")
        if abs(dv[2]) >= 0.12:
            parts.append("more in control" if dv[2] > 0 else "less in control")
        mv = " Over the last hour you have been moving: %s." % ", ".join(parts)
    return ("Where you are inside, as a point rather than a label: pleasant %+.2f, stirred %.2f, in control %.2f - %s.%s"
            % (pt[0], pt[1], pt[2], blend, mv))
