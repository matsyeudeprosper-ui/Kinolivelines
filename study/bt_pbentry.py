"""User 2026-09-10: after a BOS confirms, do NOT enter at the
break.  Wait for a pullback to 30% (or 50%) of the risk distance,
enter there, TP at the BOS level (the old entry), SL at the dot.
Pending entry is cancelled when the trend flips or a new BOS
replaces it; if price never pulls back, no trade (missed move).
Spread-correct fills.  vs the live config (+255)."""
from collections import deque

import numpy as np

from bt_bos import Struct, O, H, L, C, T, S

LOT = 0.02
WIN = 7200
mid = int(np.searchsorted(T, T[0] + (T[-1] - T[0]) // 2))


def run(a, b, frac):
    st = Struct()
    pos = None          # (d, e, sl, tp)
    pend = None         # (d, level, sl, tp)
    ev = deque()
    out = []
    used_hi = used_lo = None
    missed = 0

    def arm(d, bos_bid, dot):
        # buy: limit at bos - frac*R (ask fills when bid <= P-S)
        # sell: limit at bos + frac*R (fills when bid >= P)
        R = abs(bos_bid - dot) + (S if d == 1 else 0)
        if R <= S:
            return None
        if d == 1:
            lvl = bos_bid - frac * R
            return (1, lvl, dot, bos_bid)
        lvl = bos_bid + frac * R
        return (-1, lvl, dot, bos_bid)

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
            if pend is not None:      # flip cancels the waiting order
                pend = None
                missed += 1
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
        if pend is not None:          # new flip BOS replaces pending
            pend = None
            missed += 1
        pend = arm(d, c, slp)
    W = sum(1 for x in out if x > 0)
    cum = pk = mdd = 0.0
    for x in out:
        cum += x
        pk = max(pk, cum)
        mdd = max(mdd, pk - cum)
    return sum(out), len(out), W, mdd, missed


for frac in (0.3, 0.5):
    n, c2, w, dd, ms = run(0, len(T), frac)
    n1, _, _, _, _ = run(0, mid, frac)
    n2, _, _, _, _ = run(mid, len(T), frac)
    print(f"pullback {frac:.0%}: n {c2:4d} wr {w/max(1,c2):.0%} "
          f"net {n:+8.2f} maxDD {dd:6.2f} missed {ms:3d} | "
          f"h1 {n1:+7.2f} h2 {n2:+7.2f}")
print("baseline (live config): n 622 wr 58% net +255.12 maxDD 66"
      " | h1 +85.87 h2 +166.62")
