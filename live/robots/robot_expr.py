"""The formula language of the robot builder (owner 2026-10-19: "even if the piece doesn't exist the AI creates it").

A piece the fixed piece language (robot_dsl) cannot say is written as a FORMULA over the candles, e.g.
    close > ema(close, 50) @ H1 and rsi(close, 14) < 30
The formula is parsed with Python's own parser and then checked node by node against a short whitelist; it is
never executed as code - this module walks the tree and computes it with numpy. So a formula from the AI (or a
member) can only read prices and do arithmetic: no names, calls or syntax outside the lists below get through.

    names       open high low close volume  body range upper_wick lower_wick mid  (the candle, 1 minute by default)
                hour minute weekday (UTC; 0 = Monday)  asia london newyork  (sessions: 0-8, 7-16, 12-21 UTC)
                pdh pdl pdc (previous day high / low / close)  day_open day_high day_low (today so far)
                trend (+1 / -1 / 0 = the nest's background trend)  bos_up bos_down choch_up choch_down
                (the eyes' breaks, true on the candle that closes them)
    functions   ema sma rsi stdev highest lowest (series, n)   atr(n)   prev(series, k=1)   change(series, k=1)
                cross_up cross_down (a, b)   rising falling (series, n)   bb_up bb_low (series, n, k)
                macd macd_signal (series, fast, slow[, signal])   vwap()   abs min max
    operators   + - * /  < <= > >= == !=  and or not   ( )
    timeframe   <part> @ M5 | M15 | M30 | H1 | H4 | D1 : that part is computed on that chart's candles, and each
                1-minute candle sees the value of the LAST CLOSED candle of that chart (no look-ahead)
Every value at a candle uses only that candle's close and before. Warm-up values are "unknown" and make a
condition false.
"""
import ast
import math

import numpy as np

TFS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
SERIES = ("open", "high", "low", "close", "volume", "body", "range", "upper_wick", "lower_wick", "mid")
CLOCK = ("hour", "minute", "weekday", "asia", "london", "newyork")
DAY = ("pdh", "pdl", "pdc", "day_open", "day_high", "day_low")
EYES = ("trend", "bos_up", "bos_down", "choch_up", "choch_down")
NAMES = SERIES + CLOCK + DAY + EYES
# function -> (min args, max args, which args are constant whole numbers (index), max for those)
FUNCS = {"ema": (2, 2), "sma": (2, 2), "rsi": (2, 2), "stdev": (2, 2), "highest": (2, 2), "lowest": (2, 2),
         "atr": (1, 1), "prev": (1, 2), "change": (1, 2), "cross_up": (2, 2), "cross_down": (2, 2),
         "rising": (2, 2), "falling": (2, 2), "bb_up": (3, 3), "bb_low": (3, 3), "macd": (3, 3), "macd_signal": (3, 4),
         "vwap": (0, 0), "abs": (1, 1), "min": (2, 2), "max": (2, 2)}
INT_ARGS = {"ema": [1], "sma": [1], "rsi": [1], "stdev": [1], "highest": [1], "lowest": [1], "atr": [0], "prev": [1],
            "change": [1], "rising": [1], "falling": [1], "bb_up": [1], "bb_low": [1], "macd": [1, 2], "macd_signal": [1, 2, 3]}
MAX_LEN, MAX_NODES, MAX_WIN = 400, 80, 500


class FormulaError(ValueError):
    pass


# ---------------------------------------------------------------- checking
def check(src):
    """the parsed tree of a formula, or FormulaError with a plain reason"""
    if not isinstance(src, str) or not src.strip():
        raise FormulaError("empty")
    if len(src) > MAX_LEN:
        raise FormulaError("too long (max %d characters)" % MAX_LEN)
    s = src.replace("&&", " and ").replace("||", " or ")
    try:
        tree = ast.parse(s.strip(), mode="eval")
    except SyntaxError as e:
        raise FormulaError("cannot read it near character %s" % (e.offset or "?"))
    n = [0]

    def walk(x, in_tf=False):
        n[0] += 1
        if n[0] > MAX_NODES:
            raise FormulaError("too complex")
        if isinstance(x, ast.Expression):
            return walk(x.body)
        if isinstance(x, ast.Constant):
            if isinstance(x.value, bool) or not isinstance(x.value, (int, float)):
                raise FormulaError("only numbers are allowed as values")
            return
        if isinstance(x, ast.Name):
            if x.id not in NAMES:
                raise FormulaError("unknown name '%s'" % x.id)
            return
        if isinstance(x, ast.BinOp):
            if isinstance(x.op, ast.MatMult):
                if not (isinstance(x.right, ast.Name) and x.right.id in TFS):
                    raise FormulaError("after @ comes a chart: " + ", ".join(TFS))
                if in_tf:
                    raise FormulaError("one @ chart at a time")
                return walk(x.left, True)
            if not isinstance(x.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                raise FormulaError("only + - * / are allowed")
            walk(x.left, in_tf); walk(x.right, in_tf); return
        if isinstance(x, ast.UnaryOp):
            if not isinstance(x.op, (ast.USub, ast.UAdd, ast.Not)):
                raise FormulaError("operator not allowed")
            return walk(x.operand, in_tf)
        if isinstance(x, ast.BoolOp):
            for v in x.values:
                walk(v, in_tf)
            return
        if isinstance(x, ast.Compare):
            if not all(isinstance(o, (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)) for o in x.ops):
                raise FormulaError("comparison not allowed")
            walk(x.left, in_tf)
            for c in x.comparators:
                walk(c, in_tf)
            return
        if isinstance(x, ast.Call):
            if not isinstance(x.func, ast.Name):
                raise FormulaError("only the listed functions can be used (ema, rsi, atr...)")
            if x.func.id not in FUNCS or x.keywords:
                raise FormulaError("unknown function '%s'" % x.func.id)
            lo, hi = FUNCS[x.func.id]
            if not lo <= len(x.args) <= hi:
                raise FormulaError("%s takes %s values" % (x.func.id, lo if lo == hi else "%d to %d" % (lo, hi)))
            for i, a in enumerate(x.args):
                if i in INT_ARGS.get(x.func.id, []):
                    if not (isinstance(a, ast.Constant) and isinstance(a.value, int) and not isinstance(a.value, bool) and 1 <= a.value <= MAX_WIN):
                        raise FormulaError("%s needs a whole number from 1 to %d there" % (x.func.id, MAX_WIN))
                elif x.func.id in ("bb_up", "bb_low") and i == 2:
                    if not (isinstance(a, ast.Constant) and isinstance(a.value, (int, float)) and 0 < a.value <= 5):
                        raise FormulaError("the band width is a number from 0 to 5")
                else:
                    walk(a, in_tf)
            return
        raise FormulaError("that kind of writing is not allowed")
    walk(tree)
    return tree


def is_ok(src):
    try:
        check(src); return True, None
    except FormulaError as e:
        return False, str(e)


# ---------------------------------------------------------------- computing
def _ema(x, n):
    out = np.full(len(x), np.nan); a = 2.0 / (n + 1); v = np.nan; seen = 0
    for i, xi in enumerate(x):
        if xi != xi:
            continue
        v = xi if v != v else a * xi + (1 - a) * v
        seen += 1
        if seen >= n:
            out[i] = v
    return out


def _roll(x, n, fn):
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    with np.errstate(all="ignore"):
        out[n - 1:] = fn(w, axis=1)
    return out


def _shift(x, k):
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[:len(x) - k]
    return out


def _rsi(x, n):
    d = np.diff(x, prepend=np.nan)
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    up[0] = dn[0] = np.nan
    au, ad = _wilder(up, n), _wilder(dn, n)
    with np.errstate(all="ignore"):
        rs = au / ad
        r = 100 - 100 / (1 + rs)
    r[(ad == 0) & (au > 0)] = 100.0
    return r


def _wilder(x, n):
    out = np.full(len(x), np.nan); v = np.nan; buf = []
    for i, xi in enumerate(x):
        if xi != xi:
            continue
        if v != v:
            buf.append(xi)
            if len(buf) == n:
                v = sum(buf) / n; out[i] = v
        else:
            v = (v * (n - 1) + xi) / n; out[i] = v
    return out


class Bars:
    """the candles a formula reads: arrays of one chart + the eyes' facts (per 1-minute candle)"""

    def __init__(self, t, o, h, l, c, v, eyes=None, tf="M1"):
        self.t = np.asarray(t, dtype=np.int64); self.o = np.asarray(o, float); self.h = np.asarray(h, float)
        self.l = np.asarray(l, float); self.c = np.asarray(c, float); self.v = np.asarray(v, float)
        self.eyes = eyes or {}; self.tf = tf; self._cache = {}

    @classmethod
    def from_rates(cls, R, eyes=None):
        """from a numpy structured array with time/open/high/low/close/tick_volume (the bench's E.R, a pack's D)"""
        return cls(R["time"], R["open"], R["high"], R["low"], R["close"], R["tick_volume"], eyes)

    def resample(self, tf):
        """this chart's candles grouped into a bigger chart; plus, for each 1-minute candle, the index of the last
        CLOSED big candle (-1 = none yet)"""
        if tf in self._cache:
            return self._cache[tf]
        s = TFS[tf]
        key = self.t // s
        starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        ends = np.r_[starts[1:], len(key)] - 1
        big = Bars(key[starts] * s, self.o[starts], np.maximum.reduceat(self.h, starts), np.minimum.reduceat(self.l, starts),
                   self.c[ends], np.add.reduceat(self.v, starts), {}, tf)
        grp = np.cumsum(np.r_[True, key[1:] != key[:-1]]) - 1          # big candle index of each minute
        closes_now = (self.t + 60) % s == 0                                # this minute closes its big candle
        last = np.where(closes_now, grp, grp - 1)
        # a big candle with a missing last minute (a gap) still closes when the next big candle starts
        self._cache[tf] = (big, last)
        return big, last


def _day_facts(B):
    day = B.t // 86400
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    ends = np.r_[starts[1:], len(day)] - 1
    dh = np.maximum.reduceat(B.h, starts); dl = np.minimum.reduceat(B.l, starts); dc = B.c[ends]; do = B.o[starts]
    g = np.cumsum(np.r_[True, day[1:] != day[:-1]]) - 1
    prev = g - 1
    pdh = np.where(prev >= 0, dh[np.maximum(prev, 0)], np.nan)
    pdl = np.where(prev >= 0, dl[np.maximum(prev, 0)], np.nan)
    pdc = np.where(prev >= 0, dc[np.maximum(prev, 0)], np.nan)
    # today so far (running max/min inside each day)
    run_h = np.empty(len(B.h)); run_l = np.empty(len(B.l))
    for a, b in zip(starts, ends):
        run_h[a:b + 1] = np.maximum.accumulate(B.h[a:b + 1]); run_l[a:b + 1] = np.minimum.accumulate(B.l[a:b + 1])
    return {"pdh": pdh, "pdl": pdl, "pdc": pdc, "day_open": do[g], "day_high": run_h, "day_low": run_l}


def _vwap(B):
    day = B.t // 86400
    tp = (B.h + B.l + B.c) / 3.0; v = np.maximum(B.v, 1.0)
    out = np.empty(len(tp)); pv = vv = 0.0; cur = None
    for i in range(len(tp)):
        if day[i] != cur:
            cur = day[i]; pv = vv = 0.0
        pv += tp[i] * v[i]; vv += v[i]; out[i] = pv / vv
    return out


def evaluate(src, B):
    """the formula's value at every 1-minute candle of B (numpy float array; booleans are 1.0 / 0.0; unknown = nan)"""
    tree = check(src)
    memo = {}

    def name(x, C):
        k = (C.tf, x)
        if k in memo:
            return memo[k]
        if x == "open": v = C.o
        elif x == "high": v = C.h
        elif x == "low": v = C.l
        elif x == "close": v = C.c
        elif x == "volume": v = C.v
        elif x == "body": v = np.abs(C.c - C.o)
        elif x == "range": v = C.h - C.l
        elif x == "upper_wick": v = C.h - np.maximum(C.o, C.c)
        elif x == "lower_wick": v = np.minimum(C.o, C.c) - C.l
        elif x == "mid": v = (C.h + C.l) / 2.0
        elif x in CLOCK:
            close_t = C.t + TFS[C.tf]                  # judged at the candle's close
            hr = (close_t % 86400) // 3600 if C.tf != "D1" else np.zeros(len(C.t))
            if x == "hour": v = hr.astype(float)
            elif x == "minute": v = ((close_t % 3600) // 60).astype(float)
            elif x == "weekday": v = (((C.t // 86400) + 3) % 7).astype(float)      # 1970-01-01 was a Thursday
            elif x == "asia": v = (hr < 8).astype(float)
            elif x == "london": v = ((hr >= 7) & (hr < 16)).astype(float)
            else: v = ((hr >= 12) & (hr < 21)).astype(float)
        elif x in DAY:
            v = _day_facts(C)[x]
        else:                                          # the eyes: only on the 1-minute chart
            if C.tf != "M1":
                raise FormulaError("%s is read on the 1-minute chart only" % x)
            v = np.asarray(C.eyes.get(x, np.zeros(len(C.t))), float)
        memo[k] = v
        return v

    def num(a):
        return float(a.value)

    def ev(x, C):
        if isinstance(x, ast.Expression):
            return ev(x.body, C)
        if isinstance(x, ast.Constant):
            return np.full(len(C.t), float(x.value))
        if isinstance(x, ast.Name):
            return name(x.id, C)
        if isinstance(x, ast.BinOp):
            if isinstance(x.op, ast.MatMult):
                big, last = C.resample(x.right.id)
                vb = ev(x.left, big)
                out = np.full(len(C.t), np.nan)
                ok = last >= 0
                out[ok] = vb[last[ok]]
                return out
            a, b = ev(x.left, C), ev(x.right, C)
            with np.errstate(all="ignore"):
                if isinstance(x.op, ast.Add): return a + b
                if isinstance(x.op, ast.Sub): return a - b
                if isinstance(x.op, ast.Mult): return a * b
                r = a / b; r[~np.isfinite(r)] = np.nan; return r
        if isinstance(x, ast.UnaryOp):
            a = ev(x.operand, C)
            if isinstance(x.op, ast.Not):
                return np.where(np.isnan(a), np.nan, (a == 0).astype(float))
            return -a if isinstance(x.op, ast.USub) else a
        if isinstance(x, ast.BoolOp):
            vals = [ev(v, C) for v in x.values]
            T = [np.nan_to_num(v, nan=0.0) != 0 for v in vals]
            r = np.logical_and.reduce(T) if isinstance(x.op, ast.And) else np.logical_or.reduce(T)
            return r.astype(float)
        if isinstance(x, ast.Compare):
            left = ev(x.left, C); res = np.ones(len(C.t), bool); known = ~np.isnan(left)
            for op, cmpx in zip(x.ops, x.comparators):
                right = ev(cmpx, C); known &= ~np.isnan(right)
                with np.errstate(all="ignore"):
                    if isinstance(op, ast.Lt): r = left < right
                    elif isinstance(op, ast.LtE): r = left <= right
                    elif isinstance(op, ast.Gt): r = left > right
                    elif isinstance(op, ast.GtE): r = left >= right
                    elif isinstance(op, ast.Eq): r = np.isclose(left, right)
                    else: r = ~np.isclose(left, right)
                res &= r; left = right
            return (res & known).astype(float)
        if isinstance(x, ast.Call):
            f = x.func.id; A = x.args
            if f == "vwap": return _vwap(C)
            if f == "atr":
                n = int(A[0].value)
                pc = _shift(C.c, 1)
                tr = np.nanmax(np.vstack([C.h - C.l, np.abs(C.h - pc), np.abs(C.l - pc)]), axis=0)
                return _wilder(tr, n)
            s0 = ev(A[0], C)
            if f == "ema": return _ema(s0, int(A[1].value))
            if f == "sma": return _roll(s0, int(A[1].value), np.mean)
            if f == "stdev": return _roll(s0, int(A[1].value), np.std)
            if f == "highest": return _roll(s0, int(A[1].value), np.max)
            if f == "lowest": return _roll(s0, int(A[1].value), np.min)
            if f == "rsi": return _rsi(s0, int(A[1].value))
            if f == "prev": return _shift(s0, int(A[1].value) if len(A) > 1 else 1)
            if f == "change": k = int(A[1].value) if len(A) > 1 else 1; return s0 - _shift(s0, k)
            if f in ("rising", "falling"):
                n = int(A[1].value); d = np.diff(s0, prepend=np.nan)
                good = (d > 0) if f == "rising" else (d < 0)
                r = _roll(good.astype(float), n, np.min); return np.where(np.isnan(r), 0.0, r)
            if f in ("bb_up", "bb_low"):
                n, k = int(A[1].value), num(A[2])
                m, sd = _roll(s0, n, np.mean), _roll(s0, n, np.std)
                return m + k * sd if f == "bb_up" else m - k * sd
            if f in ("macd", "macd_signal"):
                fa, sl = int(A[1].value), int(A[2].value)
                line = _ema(s0, fa) - _ema(s0, sl)
                return line if f == "macd" else _ema(line, int(A[3].value) if len(A) > 3 else 9)
            if f == "abs": return np.abs(s0)
            s1 = ev(A[1], C)
            if f == "min": return np.fmin(s0, s1)
            if f == "max": return np.fmax(s0, s1)
            p0, p1 = _shift(s0, 1), _shift(s1, 1)
            with np.errstate(all="ignore"):
                if f == "cross_up": r = (s0 > s1) & (p0 <= p1)
                else: r = (s0 < s1) & (p0 >= p1)
            return r.astype(float)
        raise FormulaError("not allowed")
    return ev(tree, B)


def truth(src, B):
    """a condition as a boolean array (unknown = false)"""
    v = evaluate(src, B)
    return np.nan_to_num(v, nan=0.0) != 0


def eyes_from_opps(opps, n, S=None):
    """the eyes' facts per 1-minute candle from the bench's opportunity stream (+ the sticky trend states)"""
    E = {k: np.zeros(n) for k in ("bos_up", "bos_down", "choch_up", "choch_down", "trend")}
    tr = np.zeros(n); last_i, last_v = 0, 0
    for o in sorted(opps, key=lambda o: o["i"]):
        i = int(o["i"])
        if not 0 <= i < n:
            continue
        key = ("choch_" if o.get("flip") else "bos_") + ("up" if o["d"] == 1 else "down")
        E[key][i] = 1.0
        if S is not None and o["t"] in S:
            st = S[o["t"]]
            v = int(st[0]) if isinstance(st, (tuple, list)) and st and st[0] in (1, -1) else last_v
            tr[last_i:i] = last_v; last_i, last_v = i, v
    tr[last_i:] = last_v
    E["trend"] = tr
    return E
