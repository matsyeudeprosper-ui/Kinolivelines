"""User 2026-09-10: what if up to 2 trades at once?  (the ~760
busy-skips in the 69d backtest are signals we currently drop).
Same touch-config base stream, N open slots, each position its own
SL/TP.  Opposite-direction positions CAN coexist after a flip -
that is what the rule change honestly implies.  1 vs 2 vs 3 slots,
full window + halves."""
from collections import deque

import numpy as np

from bt_bos import Struct, O, H, L, C, T, S

LOT = 0.02
RR = 0.8
WIN = 7200
mid = int(np.searchsorted(T, T[0] + (T[-1] - T[0]) // 2))


def run(a, b, slots):
    st = Struct()
    poss = []
    ev = deque()
    out = []
    used_hi = used_lo = None
    peak_open = 0

    def mkpos(d, e, slp):
        tp = e + d * RR * abs(e - slp)
        return [d, e, slp, tp]

    for j in range(a, b):
        t, o, h, l, c = int(T[j]), O[j], H[j], L[j], C[j]
        for p in list(poss):
            d, e, sl, tp = p
            sl_hit = (l <= sl) if d == 1 else (h >= sl - S)
            tp_hit = (h >= tp) if d == 1 else (l <= tp - S)
            if sl_hit or tp_hit:
                px = sl if sl_hit else tp
                out.append((px - e) * d * LOT)
                poss.remove(p)
        if len(poss) < slots and ev:
            if (st.trend == 1 and st.hi_v is not None
                    and h > st.hi_v and used_hi != st.hi_v):
                span = st.kept[st.hi_i + 1:]
                if span and any(x[5] == -1 for x in span):
                    slp = min(span, key=lambda x: x[3])[3]
                    e = st.hi_v + S
                    if e - slp > S:
                        used_hi = st.hi_v
                        poss.append(mkpos(1, e, slp))
            elif (st.trend == -1 and st.lo_v is not None
                    and l < st.lo_v and used_lo != st.lo_v):
                span = st.kept[st.lo_i + 1:]
                if span and any(x[5] == 1 for x in span):
                    slp = max(span, key=lambda x: x[2])[2]
                    e = st.lo_v
                    if slp - e > S:
                        used_lo = st.lo_v
                        poss.append(mkpos(-1, e, slp))
        pt = st.trend
        sig = st.step(t, o, h, l, c)
        if st.trend != pt and st.trend != 0 and pt != 0:
            ev.append(t)
        while ev and ev[0] < t - WIN:
            ev.popleft()
        peak_open = max(peak_open, len(poss))
        if sig is None or len(poss) >= slots or not ev:
            continue
        if st.trend == pt:
            continue
        d, slp = sig
        e2 = c + S if d == 1 else c
        if abs(e2 - slp) <= S:
            continue
        poss.append(mkpos(d, e2, slp))
    W = sum(1 for x in out if x > 0)
    cum = pk = mdd = 0.0
    for x in out:
        cum += x
        pk = max(pk, cum)
        mdd = max(mdd, pk - cum)
    return sum(out), len(out), W, mdd, peak_open


for slots in (1, 2, 3):
    n, c2, w, dd, po = run(0, len(T), slots)
    n1, c1, _, dd1, _ = run(0, mid, slots)
    n2, c22, _, dd2, _ = run(mid, len(T), slots)
    print(f"slots {slots}: n {c2:4d} wr {w/max(1,c2):.0%} "
          f"net {n:+8.2f} maxDD {dd:6.2f} | "
          f"h1 {n1:+7.2f}/DD{dd1:.0f} h2 {n2:+7.2f}/DD{dd2:.0f}")
