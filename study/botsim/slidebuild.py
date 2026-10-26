"""slidebuild.py - an exact, faster stand-in for owl_chart_feed.build() when it is called on a sliding window (botsim speed,
2026-10-26). The feed's start-up replay calls build(R[i-7999:i+1]) for 8000 consecutive i: 64 million candle steps.

build() keeps a candle when its close lands beyond the high/low of the last kept candle; its only state is that last kept
candle. Two scans of windows that differ by one candle at the start keep different candles at first, but as soon as both keep
the SAME candle their states are equal and everything after it is identical. So the new window's answer = a short fresh scan
from its first candle until it meets a candle the previous answer kept, then the previous answer from there, then the new
last candle. Same output as build(), checked on real windows by check() below.
"""
import numpy as np


def _scan(H, L, C, a, b, ref=None, stop=None):
    """keep-indices of build() over rows a..b-1 starting from state ref=(h, l) or None; stops early at the first kept row in
    `stop` (a set) and returns (indices, met_row)"""
    out = []
    rh = rl = None
    if ref is not None:
        rh, rl = ref
    for k in range(a, b):
        c = C[k]
        if rh is None or c > rh or c < rl:
            out.append(k)
            rh, rl = H[k], L[k]
            if stop is not None and k in stop:
                return out, k
    return out, None


class Slider:
    """build() on consecutive windows of the same array, exact"""

    def __init__(self, base):
        self.base = base
        self.H = base["high"].astype(float)
        self.L = base["low"].astype(float)
        self.C = base["close"].astype(float)
        self.a = self.b = None
        self.idx = None                   # kept row indices of the last window
        self.rows = {}

    def keep(self, a, b):
        H, L, C = self.H, self.L, self.C
        if self.idx is not None and a == self.a + 1 and b == self.b + 1 and self.idx:
            old = self.idx
            pos = {k: n for n, k in enumerate(old)}
            fresh, met = _scan(H, L, C, a, self.b, None, set(old))
            if met is not None:
                idx = fresh + old[pos[met] + 1:]
            else:
                idx = fresh
            # the new last row, from the state of the last kept row
            last = idx[-1] if idx else None
            tail, _ = _scan(H, L, C, self.b, b, (H[last], L[last]) if last is not None else None)
            idx = idx + tail
        else:
            idx, _ = _scan(H, L, C, a, b)
        self.a, self.b, self.idx = a, b, idx
        return idx

    def kept(self, a, b):
        R, rc = self.base, self.rows
        out = []
        for k in self.keep(a, b):
            v = rc.get(k)
            if v is None:                 # each row is made once, exactly as build() makes it
                r = R[k]
                o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
                v = rc[k] = (int(r["time"]), round(o, 2), round(h, 2), round(l, 2), round(c, 2), 1 if c >= o else -1)
            out.append(list(v))
        return out


def check(R, build, W=8000, n=400):
    """compare with the real build() on n consecutive windows of R (ends at len(R))"""
    S = Slider(R)
    bad = 0
    for i in range(len(R) - n, len(R)):
        a = max(0, i - W + 1)
        if S.kept(a, i + 1) != build(R[a:i + 1]):
            bad += 1
    return bad
