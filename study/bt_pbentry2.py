"""User 2026-09-10 follow-up: same pullback entry (enter at 30/50%
retrace after BOS, TP at the BOS level) but the SL is NOT the dot -
it is a fraction of the TP distance (0.5 = half, 1.0 = equal).
Tight stop, favorable RR.  Spread-correct."""
from collections import deque

import numpy as np

from bt_bos import Struct, O, H, L, C, T, S

LOT = 0.02
WIN = 7200
mid = int(np.searchsorted(T, T[0] + (T[-1] - T[0]) // 2))


def run(a, b, frac, slm):
    st = Struct()
    pos = None
    pend = None
    ev = deque()
    out = []
    used_hi = used_lo = None

    def arm(d, bos_bid, dot):
        R = abs(bos_bid - dot) + (S if d == 1 else 0)
        if R <= S:
            return None
        tpd = frac * R
        if tpd <= S:
            return None
        lvl = bos_bid - d * tpd
        sl = lvl - d * slm * tpd
        return (d, lvl, sl, bos_bid)

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
        if pos is None and pend is not None:
            d, lvl, sl, tp = pend
            if d == 1 and l <= lvl - S:
                pos = (1, lvl, sl, tp)
                pend = None
            elif d == -1 and h >= lvl:
                pos = (-1, lvl, sl, tp)
                pend = None
        busy = pos is not None or pend is not None
        if not busy and ev:
            if (st.trend == 1 and st.hi_v is not None
                    and h > st.hi_v and used_hi != st.hi_v):
                span = st.kept[st.hi_i + 1:]
                if span and any(x[5] == -1 for x in span):
                    slp = min(span, key=lambda x: x[3])[3]
                    if st.hi_v + S - slp > S:
                        used_hi = st.hi_v
                        pend = arm(1, st.hi_v, slp)
            elif (st.trend == -1 and st.lo_v is not None
                    and l < st.lo_v and used_lo != st.lo_v):
                span = st.kept[st.lo_i + 1:]
                if span and any(x[5] == 1 for x in span):
                    slp = max(span, key=lambda x: x[2])[2]
                    if slp - st.lo_v > S:
                        used_lo = st.lo_v
                        pend = arm(-1, st.lo_v, slp)
        pt = st.trend
        sig = st.step(t, o, h, l, c)
        if st.trend != pt and st.trend != 0 and pt != 0:
            ev.append(t)
            pend = None
        while ev and ev[0] < t - WIN:
            ev.popleft()
        if sig is None or not ev:
            continue
        if st.trend == pt:
            continue
        if pos is not None:
            continue
        d, slp = sig
        e2 = c + S if d == 1 else c
        if abs(e2 - slp) <= S:
            continue
        pend = arm(d, c, slp)
    W = sum(1 for x in out if x > 0)
    cum = pk = mdd = 0.0
    for x in out:
        cum += x
        pk = max(pk, cum)
        mdd = max(mdd, pk - cum)
    return sum(out), len(out), W, mdd


for frac in (0.3, 0.5):
    for slm in (0.5, 1.0):
        n, c2, w, dd = run(0, len(T), frac, slm)
        n1, _, _, _ = run(0, mid, frac, slm)
        n2, _, _, _ = run(mid, len(T), frac, slm)
        print(f"pb {frac:.0%} sl={slm:.1f}xTP: n {c2:4d} "
              f"wr {w/max(1,c2):.0%} net {n:+8.2f} maxDD {dd:6.2f}"
              f" | h1 {n1:+7.2f} h2 {n2:+7.2f}")
print("baseline: n 622 wr 58% net +255.12 maxDD 66 "
      "| h1 +85.87 h2 +166.62")
