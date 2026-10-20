"""Chart demonstrations for the robot workshop (owner 2026-10-19: "the user should be able to demonstrate a piece of
the idea from a custom chart, same for the AI: chart demonstration markings and even a play of auto trade to the
user to confirm a point or an understanding").

  candles(market, tf, end, n)       the market's candles for the member's drawing chart (real prices)
  facts(market, t)                  what the candle at t looked like, in numbers the AI can read
  examples(market, rules, n, ov)    the robot's own trades on past candles: window, entry, stop, target, exit, overlays
                                    -> the page draws them and REPLAYS them candle by candle

Candles = the test's own data: Bitcoin's frozen dataset (study/dev_dataset "b") and each market's pack
(study/markets/<SYM>/bars.npz, prices x k there - the same scale as the tests and the live market bots, so formulas
are computed on it and prices are divided by k only for display). The eyes' breaks come from the live bot's own
structure engine (class Struct lifted from structure_bos_bot.py, as live/robots/test_bot_formula_path.py does),
cached per dataset. A demonstration is a simplified replay (candle highs/lows, no spread, no brakes): it shows HOW the
robot trades; the money figures come from the real test.
"""
import ast, hashlib, json, os, pickle, sys, threading, time

import numpy as np

import robot_expr as X

HERE = os.path.dirname(os.path.abspath(__file__)); LIVE = os.path.dirname(HERE); STUDY = os.path.join(os.path.dirname(LIVE), "study")
CACHE = os.path.join(HERE, "demo_cache")
TFS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}
_MEM, _LOCK = {}, threading.Lock()


# ---------------------------------------------------------------- data
def _struct_class():
    src = open(os.path.join(LIVE, "structure_bos_bot.py"), encoding="utf-8-sig").read()
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "Struct")
    g = {"say": lambda *a, **k: None}
    exec(compile(ast.Module([node], []), "Struct", "exec"), g)
    return g["Struct"]


def _eyes(R, key):
    """per candle: break direction (+1/-1/0), flip, protected point - the live bot's engine over these candles"""
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, "eyes_%s.pkl" % key)
    try:
        return pickle.load(open(fn, "rb"))
    except Exception:
        pass
    S = _struct_class()()
    S.quiet = True
    n = len(R); d = np.zeros(n, np.int8); fl = np.zeros(n, bool); slp = np.full(n, np.nan)
    for i in range(n):
        pt = S.trend
        sg = S.step(int(R["time"][i]), float(R["open"][i]), float(R["high"][i]), float(R["low"][i]), float(R["close"][i]))
        if sg:
            d[i] = sg[0]; slp[i] = float(sg[1]); fl[i] = S.trend != pt
    out = {"d": d, "flip": fl, "slp": slp}
    pickle.dump(out, open(fn + ".tmp", "wb")); os.replace(fn + ".tmp", fn)
    return out


def data(market):
    """(R on the test's scale, k, eyes, key) for a market, or None when its candles are not prepared yet"""
    m = (market or "BTCUSD").upper()
    with _LOCK:
        if m in _MEM:
            return _MEM[m]
    if m.rstrip("M").startswith("BTCUSD") or m == "BTCUSD":
        sys.path.insert(0, STUDY)
        import dev_dataset
        _, R, meta = dev_dataset.load("b")
        k, key = 1.0, "BTCUSD_" + meta["sha256"][:12]
    else:
        d = os.path.join(STUDY, "markets", m)
        base = m[:-1] if m.endswith("M") and not os.path.isdir(d) else m
        d = os.path.join(STUDY, "markets", base)
        try:
            meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
            R = np.load(os.path.join(d, "bars.npz"))["R"]
            k, key = float(meta["k"]), base + "_" + str(meta.get("sha256", ""))[:12]
        except Exception:
            # 2026-10-19: no test pack - the light demo candles (demo_bars.py), fetched on demand, refreshed after 12 h
            fn = os.path.join(CACHE, "bars_%s.npz" % base)
            try:
                lm = json.load(open(fn.replace(".npz", ".json"), encoding="utf-8"))
                R = np.load(fn)["R"]
                k, key = float(lm["k"]), "%s_light_%d" % (base, int(lm["at"]))
                if time.time() - float(lm["at"]) > 12 * 3600:
                    fetch(base)
            except Exception:
                fetch(base)
                return None
    eyes = _eyes(R, key)
    out = (R, k, eyes, key)
    with _LOCK:
        _MEM[m] = out
    return out


def fetch(sym):
    """start the light candle download for a market (background, below-normal priority, one at a time per market)"""
    import subprocess
    lock = os.path.join(CACHE, "bars_%s.npz.lock" % sym.upper())
    if os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 600:
        return
    os.makedirs(CACHE, exist_ok=True)
    py = sys.executable.replace("python.exe", "pythonw.exe")
    subprocess.Popen([py if os.path.exists(py) else sys.executable, os.path.join(HERE, "demo_bars.py"), sym.upper()],
                     cwd=HERE, creationflags=0x08000000 | 0x00004000, close_fds=True)


def ready(market):
    """True when charts can be drawn for this market right now"""
    m = (market or "BTCUSD").upper()
    b = m[:-1] if m.endswith("M") else m
    return b.startswith("BTCUSD") or os.path.exists(os.path.join(STUDY, "markets", b, "bars.npz"))         or os.path.exists(os.path.join(CACHE, "bars_%s.npz" % b))


def _bars(R, eyes=None, upto=None):
    E = None
    if eyes is not None:
        n = len(R)
        E = {"bos_up": ((eyes["d"] == 1) & ~eyes["flip"]).astype(float), "bos_down": ((eyes["d"] == -1) & ~eyes["flip"]).astype(float),
             "choch_up": ((eyes["d"] == 1) & eyes["flip"]).astype(float), "choch_down": ((eyes["d"] == -1) & eyes["flip"]).astype(float),
             "trend": np.zeros(n)}
        # the trend after each break, kept until the next (the demo's stand-in for the background trend)
        idx = np.flatnonzero(eyes["d"])
        pos = np.searchsorted(idx, np.arange(n), side="right") - 1
        E["trend"] = np.where(pos >= 0, eyes["d"][idx[np.maximum(pos, 0)]] if len(idx) else 0, 0).astype(float)
    return X.Bars.from_rates(R, E)


def _rows(R, k, i0, i1, tf="M1"):
    s = TFS.get(tf, 60)
    if s == 60:
        return [[int(R["time"][i]), round(R["open"][i] / k, 5), round(R["high"][i] / k, 5), round(R["low"][i] / k, 5),
                 round(R["close"][i] / k, 5)] for i in range(max(0, i0), min(len(R), i1))]
    out, cur = [], None
    for i in range(max(0, i0), min(len(R), i1)):
        t = int(R["time"][i]) // s * s
        if cur is None or cur[0] != t:
            if cur:
                out.append(cur)
            cur = [t, R["open"][i] / k, R["high"][i] / k, R["low"][i] / k, R["close"][i] / k]
        else:
            cur[2] = max(cur[2], R["high"][i] / k); cur[3] = min(cur[3], R["low"][i] / k); cur[4] = R["close"][i] / k
    if cur:
        out.append(cur)
    return [[r[0]] + [round(float(x), 5) for x in r[1:]] for r in out]


def candles(market, tf="M5", end=None, n=240):
    """the member's drawing chart: n candles of tf ending at `end` (default: the last candle of the data)"""
    D = data(market)
    if D is None:
        return None
    R, k, _, _ = D
    s = TFS.get(tf, 300)
    T = R["time"]
    j1 = len(R) if end is None else int(np.searchsorted(T, int(end), side="right"))
    j0 = max(0, j1 - n * s // 60 - s // 60)
    rows = _rows(R, k, j0, j1, tf)[-n:]
    return {"market": market, "tf": tf, "candles": rows, "older": j0 > 0, "first": int(T[0]), "last": int(T[-1])}


# ---------------------------------------------------------------- facts
FACTS = [("rsi14", "rsi(close, 14)"), ("ema20", "ema(close, 20)"), ("ema50", "ema(close, 50)"), ("ema200", "ema(close, 200)"),
         ("ema50_h1", "ema(close, 50) @ H1"), ("atr14", "atr(14)"), ("high30", "highest(high, 30)"), ("low30", "lowest(low, 30)"),
         ("high120", "highest(high, 120)"), ("low120", "lowest(low, 120)"), ("pdh", "pdh"), ("pdl", "pdl"),
         ("day_high", "day_high"), ("day_low", "day_low"), ("bb_up20", "bb_up(close, 20, 2)"), ("bb_low20", "bb_low(close, 20, 2)"),
         ("vwap", "vwap()"), ("trend", "trend")]
PRICE = {"ema20", "ema50", "ema200", "ema50_h1", "atr14", "high30", "low30", "high120", "low120", "pdh", "pdl", "day_high", "day_low",
         "bb_up20", "bb_low20", "vwap"}


def facts(market, t):
    """the candle at time t (and its context) in numbers: what the AI needs to guess the member's rule"""
    D = data(market)
    if D is None:
        return None
    R, k, eyes, _ = D
    i = int(np.searchsorted(R["time"], int(t), side="right")) - 1
    if i < 300:
        return None
    lo = max(0, i - 3000)
    sub = R[lo:i + 1]
    se = {kk: v[lo:i + 1] for kk, v in eyes.items()}
    B = _bars(sub, se)
    out = {"time_utc": __import__("time").strftime("%Y-%m-%d %H:%M", __import__("time").gmtime(int(R["time"][i]))),
           "weekday": int(__import__("time").gmtime(int(R["time"][i])).tm_wday), "close": round(float(R["close"][i]) / k, 5)}
    for name, f in FACTS:
        try:
            v = float(X.evaluate(f, B)[-1])
            out[name] = None if v != v else round(v / k, 5) if name in PRICE else round(v, 3)
        except Exception:
            out[name] = None
    h = int(__import__("time").gmtime(int(R["time"][i])).tm_hour)
    out["session"] = ", ".join(n for n, a, b in (("asia", 0, 8), ("london", 7, 16), ("newyork", 12, 21)) if a <= h < b) or "none"
    last = [j for j in range(max(0, i - 240), i + 1) if eyes["d"][j]]
    out["last_breaks"] = [{"min_ago": i - j, "dir": "up" if eyes["d"][j] == 1 else "down", "kind": "choch" if eyes["flip"][j] else "bos"}
                          for j in last[-3:]]
    c = R["close"][max(0, i - 30):i + 1] / k
    out["last_30_closes"] = [round(float(x), 5) for x in c]
    return out


# ---------------------------------------------------------------- examples
def _signals(rules, R, eyes, B):
    """(i, d, protected point) where the robot's entry fires"""
    en = rules.get("entry") or {"event": "any"}
    out = []
    if en.get("event") == "formula":
        lo, hi = X.evaluate("lowest(low, 20)", B), X.evaluate("highest(high, 20)", B)
        for d, src in ((1, en.get("buy")), (-1, en.get("sell"))):
            if not src:
                continue
            tr = X.truth(src, B)
            for i in np.flatnonzero(tr & ~np.r_[False, tr[:-1]]):
                p = float(lo[i] if d == 1 else hi[i])
                if p == p:
                    out.append((int(i), d, p))
    else:
        ev = en.get("event", "any")
        for i in np.flatnonzero(eyes["d"]):
            fl = bool(eyes["flip"][i])
            if ev == "any" or (ev == "choch") == fl:
                out.append((int(i), int(eyes["d"][i]), float(eyes["slp"][i])))
    out.sort()
    return out


def _ok_filters(rules, i, d, R, B, cache):
    import time as _t
    g = _t.gmtime(int(R["time"][i]))
    for j, f in enumerate(rules.get("filters") or []):
        k = f.get("kind")
        if k == "hours" and not (f["from"] <= g.tm_hour < f["to"]):
            return False
        if k == "weekdays" and g.tm_wday not in f["days"]:
            return False
        if k == "formula":
            src = f.get("buy") if d == 1 else f.get("sell")
            if src:
                if src not in cache:
                    cache[src] = X.truth(src, B)
                if not cache[src][i]:
                    return False
    return True


def _stop(rules, i, d, slp, R, B, cache):
    st = rules.get("stop") or {"kind": "protected"}
    c = float(R["close"][i])
    if st["kind"] == "protected":
        return slp - d * float(st.get("buffer") or 0)
    if st["kind"] == "break_candle":
        return (float(R["low"][i]) if d == 1 else float(R["high"][i])) - d * float(st.get("buffer") or 0)
    if st["kind"] == "fixed":
        return c - d * float(st["points"])
    if st["kind"] == "formula":
        src = st.get("buy") if d == 1 else st.get("sell")
        if not src:
            return float("nan")
        if src not in cache:
            cache[src] = X.evaluate(src, B)
        return float(cache[src][i])
    return slp


def _walk(rules, i, d, e, sl, R, B, cache, rr):
    """the trade candle by candle: (exit index, exit price, why, tp)"""
    ex = rules.get("exit") or {}
    tgt = ex.get("target", rr) if ex else rr
    risk = abs(e - sl)
    tp = e + d * float(tgt) * risk if tgt else None
    xs = ex.get("close_buy") if d == 1 else ex.get("close_sell")
    xa = None
    if xs:
        if xs not in cache:
            cache[xs] = X.truth(xs, B)
        xa = cache[xs]
    be = False
    for j in range(i + 1, min(len(R), i + 1440)):
        h, l, c = float(R["high"][j]), float(R["low"][j]), float(R["close"][j])
        if (d == 1 and l <= sl) or (d == -1 and h >= sl):
            return j, sl, "be" if be else "stop", tp
        if tp is not None and ((d == 1 and h >= tp) or (d == -1 and l <= tp)):
            return j, tp, "target", tp
        if xa is not None and xa[j]:
            return j, c, "formula", tp
        if ex.get("time_min") and j - i >= int(ex["time_min"]):
            return j, c, "time", tp
        if ex.get("breakeven_at") and not be and d * (c - e) >= float(ex["breakeven_at"]) * risk:
            sl, be = e, True
    return None


def examples(market, rules, n=3, overlays=None, rr=0.8, pick="recent"):
    """the robot's trades on the market's candles -> {"market", "trades": [...], "count", "won"} or None (no candles)"""
    D = data(market)
    if D is None:
        return None
    R, k, eyes, _ = D
    B = _bars(R, eyes)
    cache, trades, busy = {}, [], -1
    for i, d, slp in _signals(rules, R, eyes, B):
        if i <= busy or i < 1440 or i >= len(R) - 2:
            continue
        if not _ok_filters(rules, i, d, R, B, cache):
            continue
        e = float(R["close"][i])
        sl = _stop(rules, i, d, slp, R, B, cache)
        if sl != sl or d * (e - sl) <= 0:
            continue
        w = _walk(rules, i, d, e, sl, R, B, cache, rr)
        if w is None:
            continue
        j, xp, why, tp = w
        trades.append({"i": i, "j": j, "d": d, "e": e, "sl": sl, "tp": tp, "x": xp, "why": why, "r": round(d * (xp - e) / abs(e - sl), 2)})
        busy = j
    if pick == "all":           # 2026-10-19: every trade with its times and R (Kino's tools)
        return {"market": market, "all": [{"t_in": int(R["time"][t["i"]]), "t_out": int(R["time"][t["j"]]), "d": t["d"], "r": t["r"],
                                               "e": round(t["e"] / k, 5), "x": round(t["x"] / k, 5)} for t in trades],
                "count": len(trades), "won": sum(1 for t in trades if t["r"] > 0)}
    if not trades:
        return {"market": market, "trades": [], "count": 0, "won": 0}
    if pick == "mix":
        wins = [t for t in trades if t["r"] > 0]; losses = [t for t in trades if t["r"] <= 0]
        sel = (wins[-((n + 1) // 2):] + losses[-(n // 2):])[:n]
        sel.sort(key=lambda t: t["i"])
    else:
        sel = trades[-n:]
    ovs = [o for o in (overlays or [])[:3] if X.is_ok(o)]
    OV = {o: X.evaluate(o, B) for o in ovs}
    out = []
    for t in sel:
        i0, i1 = max(0, t["i"] - 70), min(len(R), t["j"] + 20)
        step = max(1, (i1 - i0) // 160)          # long trades: fewer, bigger candles on the phone
        tf = "M1" if step == 1 else ("M5" if step <= 5 else ("M15" if step <= 15 else "H1"))
        rows = _rows(R, k, i0, i1, tf)
        ovl = []
        for o in ovs:
            v = OV[o]; pts = []
            for r in rows:
                jj = int(np.searchsorted(R["time"], r[0] + TFS[tf] - 60, side="right")) - 1
                x = float(v[jj]) if 0 <= jj < len(v) else float("nan")
                pts.append(None if x != x else round(x / k, 5))
            ovl.append({"f": o, "pts": pts})
        out.append({"tf": tf, "candles": rows, "t_in": int(R["time"][t["i"]]), "t_out": int(R["time"][t["j"]]), "d": t["d"],
                    "entry": round(t["e"] / k, 5), "stop": round(t["sl"] / k, 5), "target": round(t["tp"] / k, 5) if t["tp"] else None,
                    "exit": round(t["x"] / k, 5), "why": t["why"], "r": t["r"], "overlays": ovl})
    return {"market": market, "trades": out, "count": len(trades), "won": sum(1 for t in trades if t["r"] > 0)}


def rules_of(robot, pieces):
    """the chat's robot (slots: {use} or {rule}) -> the piece language dict a demonstration reads; Owl engine pieces
    are mapped to what they do (break entry, protected stop, target); the Owl's brakes are not shown"""
    P = {p["id"]: p for p in pieces}
    out, rr = {}, 0.8

    def rule(s):
        if not s:
            return None, None
        if s.get("rule"):
            return s["rule"], None
        p = P.get(s.get("use")) or {}
        return p.get("rule"), p.get("engine") or {}
    r, eng = rule(robot.get("entry"))
    out["entry"] = r or {"event": "any"}
    r, eng = rule(robot.get("stop"))
    out["stop"] = r or {"kind": "protected"}
    r, eng = rule(robot.get("exit"))
    if r:
        out["exit"] = r
    elif eng and eng.get("rr"):
        rr = float(eng["rr"])
    out["filters"] = [x for x in (rule(f)[0] for f in robot.get("filters") or []) if x]
    return out, rr


def moments(market, formula, side=1, overlays=None, n=3):
    """where ONE idea (a condition, not a whole robot) fires on the market's candles: up to n recent moments, each a
    window of candles with the moment marked (+ lines) - the AI shows "this is what I understood" before building"""
    D = data(market)
    if D is None:
        return None
    if not X.is_ok(formula):
        return {"market": market, "formula": formula, "count": 0, "moments": [], "bad": True}
    R, k, eyes, _ = D
    B = _bars(R, eyes)
    tr = X.truth(formula, B)
    edges = [int(i) for i in np.flatnonzero(tr & ~np.r_[False, tr[:-1]]) if 300 <= i < len(R) - 45]
    days = max(1.0, (int(R["time"][-1]) - int(R["time"][0])) / 86400.0)
    pick, last = [], None
    for i in reversed(edges):                      # the most recent ones, at least 2 hours apart
        if last is None or last - i >= 120:
            pick.append(i); last = i
        if len(pick) >= n:
            break
    pick.sort()
    ovs = [o for o in (overlays or [])[:3] if X.is_ok(o)]
    OV = {o: X.evaluate(o, B) for o in ovs}
    out = []
    for i in pick:
        i0, i1 = max(0, i - 60), min(len(R), i + 40)
        rows = _rows(R, k, i0, i1, "M1")
        ovl = [{"f": o, "pts": [None if OV[o][j] != OV[o][j] else round(float(OV[o][j]) / k, 5) for j in range(i0, i1)]} for o in ovs]
        out.append({"tf": "M1", "candles": rows, "t": int(R["time"][i]), "marks": [{"k": "buy" if side == 1 else "sell", "t": int(R["time"][i]),
                    "p": round(float(R["close"][i]) / k, 5)}], "overlays": ovl,
                    "after": round(float((R["close"][min(len(R) - 1, i + 30)] - R["close"][i]) / k), 5)})
    return {"market": market, "formula": formula, "side": side, "count": len(edges), "per_day": round(len(edges) / days, 1), "moments": out}
