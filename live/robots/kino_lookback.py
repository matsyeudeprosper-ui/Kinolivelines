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
