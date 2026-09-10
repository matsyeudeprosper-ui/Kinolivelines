"""User idea 2026-09-10: BUY only when the new glowing dot (the
low-dot = SL level) is HIGHER than the previous glowing dot;
mirror for SELL (new high-dot lower than previous).  I.e. only
trade strengthening structure (higher lows / lower highs).
Dot tracking updates on EVERY signal (taken or not) so the
feature is stable under filtering."""
from collections import deque

import numpy as np

from bt_bos import Struct, O, H, L, C, T, S

LOT = 0.02
RR = 0.8
WIN = 7200
mid = int(np.searchsorted(T, T[0] + (T[-1] - T[0]) // 2))


def run(a, b, filt=True, mode="signal", seed=1):
    st = Struct()
    pos = None
    ev = deque()
    out = []
    used_hi = used_lo = None
    last_dot_up = last_dot_dn = None   # previous glowing dot / side
    rs = [seed]

    def rnd():
        rs[0] = (rs[0] * 1103515245 + 12345) % (2 ** 31)
        return rs[0] / (2 ** 31)

    def allowed(d, slp):
        if not filt:
            return True
        prev = last_dot_up if d == 1 else last_dot_dn
        if prev is None:
            return True
        return slp > prev if d == 1 else slp < prev

    def note(d, slp):
        nonlocal last_dot_up, last_dot_dn
        if d == 1:
            last_dot_up = slp
        else:
            last_dot_dn = slp

    def mkpos(d, e, slp):
        if mode == "random":
            dist = abs(e - slp)
            d2 = 1 if rnd() < 0.5 else -1
            base = e if d == 1 else e  # entry px kept
            e = base + (S if (d2 == 1 and d != 1) else 0) \
                - (S if (d2 == -1 and d == 1) else 0)
            d = d2
            slp = e - d * dist
        tp = e + d * RR * abs(e - slp)
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
                    e = st.hi_v + S
                    if e - slp > S:
                        used_hi = st.hi_v
                        if allowed(1, slp):
                            pos = mkpos(1, e, slp)
                        note(1, slp)
            elif (st.trend == -1 and st.lo_v is not None
                    and l < st.lo_v and used_lo != st.lo_v):
                span = st.kept[st.lo_i + 1:]
                if span and any(x[5] == 1 for x in span):
                    slp = max(span, key=lambda x: x[2])[2]
                    e = st.lo_v
                    if slp - e > S:
                        used_lo = st.lo_v
                        if allowed(-1, slp):
                            pos = mkpos(-1, e, slp)
                        note(-1, slp)
        pt = st.trend
        sig = st.step(t, o, h, l, c)
        if st.trend != pt and st.trend != 0 and pt != 0:
            ev.append(t)
        while ev and ev[0] < t - WIN:
            ev.popleft()
        if sig is None or not ev:
            continue
        if st.trend == pt:
            continue
        d, slp = sig
        e2 = c + S if d == 1 else c
        if abs(e2 - slp) <= S:
            continue
        if pos is None and allowed(d, slp):
            pos = mkpos(d, e2, slp)
        note(d, slp)
    W = sum(1 for x in out if x > 0)
    cum = pk = mdd = 0.0
    for x in out:
        cum += x
        pk = max(pk, cum)
        mdd = max(mdd, pk - cum)
    return sum(out), len(out), W, mdd


def show(lbl, r):
    n, c2, w, dd = r
    print(f"  {lbl:22s}: n {c2:3d} wr {w/max(1,c2):.0%} "
          f"net {n:+8.2f} maxDD {dd:6.2f}")


print("== full 69 days ==")
show("baseline (no filter)", run(0, len(T), False))
show("rising-dots filter", run(0, len(T), True))
print("== halves ==")
show("h1 baseline", run(0, mid, False))
show("h1 filter", run(0, mid, True))
show("h2 baseline", run(mid, len(T), False))
show("h2 filter", run(mid, len(T), True))
print("== random-direction controls, filter ON ==")
for s in (11, 22, 33, 44, 55):
    show(f"random s{s}", run(0, len(T), True, "random", s))
