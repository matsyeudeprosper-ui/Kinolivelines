"""User 2026-09-10: take the OPPOSITE of every trade (buy->sell,
sell->buy), SL/TP mirrored around the entry with the same
distances and RR 0.8.  Spread-correct on the flipped side.
Full 69d + halves."""
from collections import deque

import numpy as np

from bt_bos import Struct, O, H, L, C, T, S

LOT = 0.02
RR = 0.8
WIN = 7200
mid = int(np.searchsorted(T, T[0] + (T[-1] - T[0]) // 2))


def run(a, b, invert):
    st = Struct()
    pos = None
    ev = deque()
    out = []
    used_hi = used_lo = None

    def mkpos(d, mid_e, dist):
        # mid_e = decision price (bid); build entry on correct side
        if invert:
            d = -d
        e = mid_e + (S if d == 1 else 0.0)
        slp = e - d * dist
        tp = e + d * RR * dist
        return (d, e, slp, tp)

    for j in range(a, b):
        t, o, h, l, c = int(T[j]), O[j], H[j], L[j], C[j]
        if pos is not None:
            d, e, sl, tp = pos
            sl_hit = (l <= sl) if d == 1 else (h >= sl - S)
            tp_hit = (h >= tp) if d == 1 else (l <= tp - S)
            if sl_hit or tp_hit:
                px = sl if sl_hit else tp
                out.append((px - e) * d * LOT)
                pos = None
        if pos is None and ev:
            if (st.trend == 1 and st.hi_v is not None
                    and h > st.hi_v and used_hi != st.hi_v):
                span = st.kept[st.hi_i + 1:]
                if span and any(x[5] == -1 for x in span):
                    slp = min(span, key=lambda x: x[3])[3]
                    if st.hi_v + S - slp > S:
                        used_hi = st.hi_v
                        pos = mkpos(1, st.hi_v, st.hi_v + S - slp)
            elif (st.trend == -1 and st.lo_v is not None
                    and l < st.lo_v and used_lo != st.lo_v):
                span = st.kept[st.lo_i + 1:]
                if span and any(x[5] == 1 for x in span):
                    slp = max(span, key=lambda x: x[2])[2]
                    if slp - st.lo_v > S:
                        used_lo = st.lo_v
                        pos = mkpos(-1, st.lo_v, slp - st.lo_v)
        pt = st.trend
        sig = st.step(t, o, h, l, c)
        if st.trend != pt and st.trend != 0 and pt != 0:
            ev.append(t)
        while ev and ev[0] < t - WIN:
            ev.popleft()
        if sig is None or pos is not None or not ev:
            continue
        if st.trend == pt:
            continue
        d, slp = sig
        e2 = c + S if d == 1 else c
        if abs(e2 - slp) <= S:
            continue
        pos = mkpos(d, c, abs(e2 - slp))
    W = sum(1 for x in out if x > 0)
    cum = pk = mdd = 0.0
    for x in out:
        cum += x
        pk = max(pk, cum)
        mdd = max(mdd, pk - cum)
    return sum(out), len(out), W, mdd


for lbl, inv in (("normal ", False), ("INVERTED", True)):
    n, c2, w, dd = run(0, len(T), inv)
    n1, _, _, _ = run(0, mid, inv)
    n2, _, _, _ = run(mid, len(T), inv)
    print(f"{lbl}: n {c2:4d} wr {w/max(1,c2):.0%} net {n:+8.2f} "
          f"maxDD {dd:6.2f} | h1 {n1:+7.2f} h2 {n2:+7.2f}")
