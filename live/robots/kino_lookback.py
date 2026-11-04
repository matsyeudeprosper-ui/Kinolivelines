"""kino_lookback.py (2026-11-03, owner list 7 item 1: "checking his work after he acts"). A person who just did something
glances back to see it went the way they meant - before the other one has to point it out ("the 09:33 buy never showed up").

compare(meant, opens) holds what he meant (direction, lot, stop, target, around what entry) against what the account shows a
few seconds later, and returns the differences in plain words - or [] when it landed as meant. Nothing is decided here: the
server tells him what he found, he decides what to say. Any act whose result can be read back can use the same shape.
"""


def _near(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def compare(meant, opens, entry=None, tol=1.0):
    """meant: {"d", "lot", "sl", "tp"}; opens: the account's open positions [{"d","lot","e","sl","tp","ticket"}]
    -> (position or None, [differences])"""
    d = int(meant.get("d") or 0)
    cand = [o for o in opens or [] if int(o.get("d") or 0) == d]
    if entry is not None:
        cand.sort(key=lambda o: abs(float(o.get("e") or 0) - float(entry)))
    if not cand:
        return None, ["no %s position is on the account" % ("buy" if d == 1 else "sell")]
    o = cand[0]
    diff = []
    if meant.get("lot") and not _near(o.get("lot"), meant["lot"], 1e-6):
        diff.append("size %s instead of %s" % (o.get("lot"), meant["lot"]))
    for k, nm in (("sl", "stop"), ("tp", "target")):
        want = float(meant.get(k) or 0)
        got = float(o.get(k) or 0)
        if want and not got:
            diff.append("no %s on it (you meant %.0f)" % (nm, want))
        elif want and not _near(got, want, tol):
            diff.append("%s at %.0f instead of %.0f" % (nm, got, want))
    return o, diff



# ---- 2026-11-04 (list 15 item 2): a model of how his own acts change what he then perceives ----------------------------
# A person who acts learns what their action does to the world: "when I send at market I get filled a bit worse than the
# price I was looking at". Each order: the price he saw when he decided, the fill that came back, the direction - slippage in
# points (positive = worse for him). From it, before the next order, he expects a fill and a risk; after, the expectation is
# checked. Store kino_acts.json.
import io as _io, json as _json, os as _os, time as _time
_ACTS = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "kino_acts.json")


def _acts_load():
    try:
        return _json.load(_io.open(_ACTS, encoding="utf-8"))
    except Exception:
        return {"fills": []}


def note_fill(seen_px, fill_px, d, expected_fill=None):
    """one market order: the price he saw, the fill, the side (+1 buy, -1 sell)"""
    try:
        slip = (float(fill_px) - float(seen_px)) * int(d)          # >0: filled worse than he saw
    except Exception:
        return None
    A = _acts_load()
    A["fills"] = (A.get("fills") or [])[-200:] + [{"t": _time.time(), "seen": float(seen_px), "fill": float(fill_px), "d": int(d),
                                                   "slip": round(slip, 2), "exp": expected_fill}]
    tmp = _ACTS + ".tmp"
    _json.dump(A, _io.open(tmp, "w", encoding="utf-8"))
    _os.replace(tmp, _ACTS)
    return slip


def expect_fill(seen_px, d):
    """-> (expected fill, typical slippage, how many orders it is learned from)"""
    F = (_acts_load().get("fills") or [])[-30:]
    if not F:
        return float(seen_px), 0.0, 0
    S = sorted(x["slip"] for x in F)
    med = S[len(S) // 2]
    return round(float(seen_px) + int(d) * med, 2), med, len(F)


def acts_line():
    F = (_acts_load().get("fills") or [])[-30:]
    if len(F) < 2:
        return ""
    S = sorted(x["slip"] for x in F)
    E = [abs(x["fill"] - x["exp"]) for x in F if x.get("exp") is not None]
    return ("What your own orders do to the price you get (from your last %d market orders): typically filled %+.1f points from the price "
            "you saw (worst %+.1f)%s." % (len(F), S[len(S) // 2], S[-1],
                                          ("; your fill predictions were off by %.1f points on average" % (sum(E) / len(E))) if E else ""))
