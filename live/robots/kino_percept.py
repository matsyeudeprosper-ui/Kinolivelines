"""kino_percept.py (2026-11-04, owner: "push to the limit of self awareness and consciousness" - move 3: predictive perception).

Until now Kino took in his world only as text, one pass, nothing expected. Theories of perception (predictive processing:
Friston, Clark; recurrent processing: Lamme) say perceiving is predicting: a model of the world guesses what comes next, the
senses report the error, and the error both updates the model and grabs attention. Here, for the chart he watches with the
owner: each closed candle is first PREDICTED (the next move and how big it usually is) from his running model, then compared
with what came. The error updates the model (a loop - the next guess carries the last one's mistakes), a big surprise rises
into his feelings and onto the stage of his mind, and he reads what he expected against what he saw. This is perception only:
it never decides a trade - the owner's rules do.

Model per stream, online (no batch, no lookahead): drift m and spread s (exponential averages), a persistence coefficient a
learned by normalised least mean squares on the last move: guess = m + a * last_move; error e = move - guess; surprise
z = e / s. Kept in kino_percept.json; calibration (direction right, average |z|) measured as it goes.
"""
import io, json, math, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_percept.json")
_LK = threading.Lock()
ALPHA = 0.06            # how fast drift and spread follow
LR = 0.05               # how fast persistence is learned
SURPRISE = 2.5          # |z| above this rises into his feelings and mind


def _load():
    try:
        return json.load(io.open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = STORE + ".tmp"
    json.dump(d, io.open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, STORE)


def observe(stream, t, close):
    """one closed candle -> what he expected and what came (None while the model is warming up)"""
    close = float(close)
    with _LK:
        d = _load()
        S = d.setdefault(stream, {"m": 0.0, "s": 0.0, "a": 0.0, "last_close": None, "last_move": 0.0, "t": 0, "n": 0,
                                  "dir_n": 0, "dir_ok": 0, "zsum": 0.0, "recent": []})
        if float(t) <= float(S.get("t") or 0):
            return None
        out = None
        if S["last_close"] is not None:
            move = close - S["last_close"]
            guess = S["m"] + S["a"] * S["last_move"]
            spread = S["s"] or abs(move) or 1.0
            e = move - guess
            z = e / max(spread, 1e-6)
            if S["n"] >= 20:                         # judged only once the model has seen enough
                S["dir_n"] += 1
                S["dir_ok"] += 1 if (guess >= 0) == (move >= 0) else 0
                S["zsum"] += abs(z)
                out = {"t": float(t), "guess": round(guess, 1), "spread": round(spread, 1), "move": round(move, 1), "z": round(z, 2)}
                S["recent"] = (S["recent"] + [out])[-30:]
            # the loop: the error updates what he will expect next
            S["a"] = max(-0.9, min(0.9, S["a"] + LR * e * S["last_move"] / (S["last_move"] ** 2 + spread ** 2)))
            S["m"] += ALPHA * (move - S["m"])
            S["s"] += ALPHA * (abs(e) - S["s"]) if S["s"] else abs(e)
            S["last_move"] = move
            S["n"] += 1
        S["last_close"], S["t"] = close, float(t)
        _save(d)
    if out and abs(out["z"]) >= SURPRISE:
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
    return ("What you perceive on %s: for the last candle you expected about %+.0f (usually ±%.0f) and it moved %+.0f - %s. "
            "Your guesses so far: direction right %d%% of %d, average surprise %.1f spreads. (Perception only - his rules decide trades.)"
            % (label, x["guess"], x["spread"], x["move"],
               "a real surprise" if abs(x["z"]) >= SURPRISE else "about as expected" if abs(x["z"]) < 1 else "a bit more than expected",
               round(100.0 * S["dir_ok"] / S["dir_n"]), S["dir_n"], S["zsum"] / S["dir_n"]))
