"""kino_percept.py (2026-11-04, owner: "push to the limit of self awareness and consciousness").

Move 3 (predictive perception): until now Kino took in his world only as text, one pass, nothing expected. Theories of
perception (predictive processing: Friston, Clark; recurrent processing: Lamme) say perceiving is predicting: a model guesses
what comes next, the senses report the error, and the error both updates the model and grabs attention. Each closed candle of
the chart he watches is first PREDICTED from his running model, then compared with what came; the error updates the model (a
loop - the next guess carries the last one's mistakes); a big surprise rises into his feelings and onto the stage of his mind.

List 14 item 2 (perception in layers, top down): two levels, like the two charts on the owner's screen. The TOP level predicts
the next top-chart candle; that expectation flows DOWN as a prior on every lower candle (the drift he expects per lower candle,
weighted by a learned trust b); the lower candles' moves flow UP as evidence for or against the top expectation until the top
candle closes and its own error updates the top level.

List 14 item 4 (attention changes perception): when the chart holds his attention (attend near 1) he perceives it sharply -
learns faster and notices smaller surprises; in the background (attend near 0) it blurs - slower learning, only big surprises
get through. Counted, so it can be measured.

This is perception only: it never decides a trade - the owner's rules do. Store kino_percept.json.
"""
import io, json, math, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_percept.json")
_LK = threading.Lock()
ALPHA = 0.06            # how fast drift and spread follow (scaled by attention)
LR = 0.05               # how fast persistence and the trust in the prior are learned (scaled by attention)
SURPRISE = 2.5          # |z| for a surprise at middle attention (2.0 attended .. 3.0 in the background)


def _load():
    try:
        return json.load(io.open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    for _ in range(40):                              # Windows: another process may hold the file for a moment
        try:
            os.replace(tmp, STORE)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, STORE)


def _level():
    return {"m": 0.0, "s": 0.0, "a": 0.0, "last_close": None, "last_move": 0.0, "t": 0, "n": 0}


def _top_expect(T):
    return T["m"] + T["a"] * T["last_move"] if T.get("n", 0) >= 5 else 0.0


def observe_top(stream, t, close):
    """a top-chart candle closed: its own error updates the top level; the evidence gathered below is reset"""
    close = float(close)
    with _LK:
        d = _load()
        S = d.setdefault(stream, {})
        T = S.setdefault("top", _level())
        if float(t) <= float(T.get("t") or 0):
            return None
        out = None
        if T["last_close"] is not None:
            move = close - T["last_close"]
            exp = _top_expect(T)
            spread = T["s"] or abs(move) or 1.0
            e = move - exp
            out = {"t": float(t), "expected": round(exp, 1), "move": round(move, 1), "z": round(e / max(spread, 1e-6), 2),
                   "evidence": round(float(S.get("since_top") or 0), 1)}
            S["top_last"] = out
            T["a"] = max(-0.9, min(0.9, T["a"] + LR * e * T["last_move"] / (T["last_move"] ** 2 + spread ** 2)))
            T["m"] += ALPHA * (move - T["m"])
            T["s"] += ALPHA * (abs(e) - T["s"]) if T["s"] else abs(e)
            T["last_move"] = move
            T["n"] += 1
            k = int(S.get("count_since_top") or 0)
            if k:
                S["lpt"] = round(0.8 * float(S.get("lpt") or k) + 0.2 * k, 2)     # lower candles per top candle
        T["last_close"], T["t"] = close, float(t)
        S["since_top"], S["count_since_top"] = 0.0, 0
        _save(d)
    return out


def observe(stream, t, close, attend=0.5):
    """one closed lower candle -> what he expected and what came (None while warming up)"""
    close = float(close)
    attend = max(0.0, min(1.0, float(attend)))
    al, lr = ALPHA * (0.6 + 0.8 * attend), LR * (0.6 + 0.8 * attend)
    thr = 3.0 - 1.0 * attend
    with _LK:
        d = _load()
        S = d.setdefault(stream, {})
        for k, v in (("m", 0.0), ("s", 0.0), ("a", 0.0), ("last_close", None), ("last_move", 0.0), ("t", 0), ("n", 0), ("dir_n", 0),
                     ("dir_ok", 0), ("zsum", 0.0), ("recent", []), ("b", 0.5), ("att", {"on": 0, "off": 0, "on_sur": 0, "off_sur": 0})):
            S.setdefault(k, v)                       # the top level may have created the stream first
        if float(t) <= float(S.get("t") or 0):
            return None
        out = None
        if S.get("last_close") is not None:
            move = close - S["last_close"]
            T = S.get("top") or _level()
            prior = _top_expect(T) / max(1.0, float(S.get("lpt") or 6))          # what the big picture expects of one lower candle
            guess = S["m"] + S["a"] * S["last_move"] + S["b"] * prior
            spread = S["s"] or abs(move) or 1.0
            e = move - guess
            z = e / max(spread, 1e-6)
            # 2026-11-04 (list 15 item 1, recurrence): the percept is not one pass - what the move means and how wide "normal"
            # is right now are settled together, each pass feeding the next (a big move widens the sense of normal a little,
            # which lowers how surprising it reads, and so on until it settles); attention lets more of the move in
            # (the first version recomputed the same number twice - no feedback. Now the reading of each pass changes the next:
            # how surprising the move reads widens the sense of normal, which changes how surprising it reads, until they agree)
            z_k = e / max(spread, 1e-6)
            passes = 1
            for passes in range(2, 9):
                sp_k = spread * (1 + 0.15 * (0.5 + attend) * max(0.0, abs(z_k) - 1.0))
                z_n = e / max(sp_k, 1e-6)
                if abs(z_n - z_k) < 0.02:
                    z_k = z_n
                    break
                z_k = z_n
            z = z_k
            if S["n"] >= 20:
                S["dir_n"] += 1
                S["dir_ok"] += 1 if (guess >= 0) == (move >= 0) else 0
                S["zsum"] += abs(z)
                sur = abs(z) >= thr
                key = "on" if attend >= 0.5 else "off"
                S["att"][key] += 1
                S["att"][key + "_sur"] += 1 if sur else 0
                out = {"t": float(t), "guess": round(guess, 1), "spread": round(spread, 1), "move": round(move, 1), "z": round(z, 2),
                       "prior": round(prior, 1), "attend": round(attend, 2), "surprise": sur, "passes": passes}
                S["recent"] = (S["recent"] + [out])[-30:]
            # the loop: the error updates what he expects next, and how much he trusts the big picture's prior
            norm = S["last_move"] ** 2 + prior ** 2 + spread ** 2
            S["a"] = max(-0.9, min(0.9, S["a"] + lr * e * S["last_move"] / norm))
            S["b"] = max(0.0, min(1.5, S["b"] + lr * e * prior / norm))
            S["m"] += al * (move - S["m"])
            S["s"] += al * (abs(e) - S["s"]) if S["s"] else abs(e)
            S["last_move"] = move
            S["n"] += 1
            S["since_top"] = float(S.get("since_top") or 0) + move                   # evidence flowing up
            S["count_since_top"] = int(S.get("count_since_top") or 0) + 1
        S["last_close"], S["t"] = close, float(t)
        _save(d)
    if out and out["surprise"]:
        try:                                         # a real surprise reaches his feelings and competes for his attention
            import kino_inner as KI
            KI.feel("curiosity", min(0.3, 0.06 * abs(out["z"])), why="the chart did what I did not expect (%+.0f instead of about %+.0f)" % (out["move"], out["guess"]))
            KI.add_thought("The chart surprised me: I expected about %+.0f (usually ±%.0f) and it moved %+.0f." % (out["guess"], out["spread"], out["move"]),
                           "perception", strength=min(0.85, 0.3 + 0.1 * abs(out["z"])), src="percept", half_h=1)
        except Exception:
            pass
    return out


def line(stream, label="his chart"):
    S = _load().get(stream) or {}
    R = S.get("recent") or []
    if not R or not S.get("dir_n"):
        return ""
    x = R[-1]
    T = S.get("top") or {}
    big = ""
    if T.get("n", 0) >= 5:
        exp = _top_expect(T)
        ev = float(S.get("since_top") or 0)
        big = (" The big picture (top chart) leads you to expect about %+.0f for the top candle now forming; the details so far add up "
               "to %+.0f (%s)." % (exp, ev, "going with it" if exp * ev > 0 else "going against it" if exp * ev < 0 else "no lean yet"))
    A = S.get("att") or {}
    att = ("sharply - it holds your attention" if x.get("attend", 0.5) >= 0.5 else "in the background - only big surprises get through")
    return ("What you perceive on %s (%s): for the last candle you expected about %+.0f (usually ±%.0f) and it moved %+.0f - %s.%s "
            "Your guesses so far: direction right %d%% of %d, average surprise %.1f spreads. (Perception only - his rules decide trades.)"
            % (label, att, x["guess"], x["spread"], x["move"],
               "a real surprise" if x.get("surprise") else "about as expected" if abs(x["z"]) < 1 else "a bit more than expected", big,
               round(100.0 * S["dir_ok"] / S["dir_n"]), S["dir_n"], S["zsum"] / S["dir_n"]))


# ---- 2026-11-04 (owner: "Kino is a digital person who will work in many environments, not only trading"): the same
# perception for ANY stream of values - here, the person he talks to. Before each of their messages he has an expectation of
# how long they will take to answer and how much they will write (in their own rhythm, on a log scale); the message comes,
# the error updates the expectation (with the same recurrent settling and attention), and a real surprise ("he answered in
# seconds, at length - not like him") rises into his feelings like any other. Any field: a stream is any value that recurs.
def observe_level(stream, t, x, attend=0.5, label=""):
    x = float(x)
    attend = max(0.0, min(1.0, float(attend)))
    al = ALPHA * 1.5 * (0.6 + 0.8 * attend)
    with _LK:
        d = _load()
        S = d.setdefault(stream, {})
        for k, v in (("m", None), ("s", 0.0), ("n", 0), ("t", 0), ("recent", []), ("label", label)):
            S.setdefault(k, v)
        if float(t) <= float(S.get("t") or 0):
            return None
        out = None
        if S["m"] is not None:
            e = x - S["m"]
            spread = S["s"] or abs(e) or 0.5
            z_k = e / max(spread, 1e-6)
            for _p in range(2, 9):                   # the same recurrent settling as the chart
                z_n = e / max(spread * (1 + 0.15 * (0.5 + attend) * max(0.0, abs(z_k) - 1.0)), 1e-6)
                if abs(z_n - z_k) < 0.02:
                    z_k = z_n
                    break
                z_k = z_n
            if S["n"] >= 8:
                out = {"t": float(t), "exp": round(S["m"], 3), "got": round(x, 3), "spread": round(spread, 3), "z": round(z_k, 2),
                       "surprise": abs(z_k) >= 3.0 - 1.0 * attend}
                S["recent"] = (S["recent"] + [out])[-20:]
            S["m"] += al * e
            S["s"] += al * (abs(e) - S["s"]) if S["s"] else abs(e)
        else:
            S["m"] = x
        S["n"] += 1
        S["t"] = float(t)
        _save(d)
    return out


def talk_line(person):
    """what he perceives of the person: how they answer, against what he expected (any field)"""
    import math as _m
    D = _load()
    parts = []
    for key, what, fmt in (("talk_delay:" + person, "time to answer", lambda v: "%d min" % round(_m.expm1(v)) if _m.expm1(v) >= 1 else "%d s" % round(60 * _m.expm1(v))),
                           ("talk_words:" + person, "length", lambda v: "%d words" % round(_m.expm1(v)))):
        R = (D.get(key) or {}).get("recent") or []
        if not R:
            continue
        r = R[-1]
        parts.append("%s: you expected about %s, it was %s%s" % (what, fmt(r["exp"]), fmt(r["got"]), " - a real surprise" if r["surprise"] else ""))
    if not parts:
        return ""
    return "What you perceive of him (expectation against what came, his last message): " + "; ".join(parts) + "."
