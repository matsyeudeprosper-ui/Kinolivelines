"""Whipsaw filter, part 2: re-simulate with the skip rule active
(skipping frees the one-trade slot, so the stream changes).
ratio = this signal's swing / PREVIOUS SIGNAL's swing (updated on
every signal, taken or not, so the feature is stable under
filtering).  Skip entry if ratio < X, and/or flips_2h >= F.
Walk-forward: pick X,F on days 1-35, blind test days 36-69.
Random-direction controls under the same filter."""
from collections import deque

import numpy as np

from bt_bos import Struct, O, H, L, C, T, S

LOT = 0.02
RR = 0.8
WIN = 7200
mid = int(np.searchsorted(T, T[0] + (T[-1] - T[0]) // 2))


def run(a, b, xmin=None, fmax=None, mode="signal", seed=1):
    st = Struct()
    pos = None
    ev = deque()
    out = []
    used_hi = used_lo = None
    prev_risk = None
    rs = [seed]

    def rnd():
        rs[0] = (rs[0] * 1103515245 + 12345) % (2 ** 31)
        return rs[0] / (2 ** 31)

    def allowed(risk):
        if fmax is not None and len(ev) > fmax:
            return False
        if xmin is not None and prev_risk and risk / prev_risk < xmin:
            return False
        return True

    def mkpos(d, e, slp):
        if mode == "random":
            dist = abs(e - slp)
            d = 1 if rnd() < 0.5 else -1
            mide = e if d == 1 else e - S  # keep ask-side entry
            e = mide + (S if d == 1 else 0)
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
                        if allowed(e - slp):
                            pos = mkpos(1, e, slp)
                        prev_risk = e - slp
            elif (st.trend == -1 and st.lo_v is not None
                    and l < st.lo_v and used_lo != st.lo_v):
                span = st.kept[st.lo_i + 1:]
                if span and any(x[5] == 1 for x in span):
                    slp = max(span, key=lambda x: x[2])[2]
                    e = st.lo_v
                    if slp - e > S:
                        used_lo = st.lo_v
                        if allowed(slp - e):
                            pos = mkpos(-1, e, slp)
                        prev_risk = slp - e
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
        risk = abs(e2 - slp)
        if pos is None and allowed(risk):
            pos = mkpos(d, e2, slp)
        prev_risk = risk
    W = sum(1 for x in out if x > 0)
    cum = pk = mdd = 0.0
    for x in out:
        cum += x
        pk = max(pk, cum)
        mdd = max(mdd, pk - cum)
    return sum(out), len(out), W, mdd


print("== grid on FIRST half (days 1-35) ==")
best = None
for xm in (None, 0.5, 0.6, 0.7, 0.8):
    for fm in (None, 2, 3):
        n, c2, w, dd = run(0, mid, xm, fm)
        tag = f"x>={xm} f<={fm}"
        print(f"  {tag:18s}: n {c2:3d} wr {w/max(1,c2):.0%} "
              f"net {n:+8.2f} maxDD {dd:6.2f}")
        if xm is not None or fm is not None:
            if best is None or n > best[0]:
                best = (n, xm, fm)
print(f"picked on h1: x>={best[1]} f<={best[2]} (net {best[0]:+.2f})")

print("== BLIND second half (days 36-69) ==")
n, c2, w, dd = run(mid, len(T), None, None)
print(f"  baseline          : n {c2:3d} wr {w/max(1,c2):.0%} "
      f"net {n:+8.2f} maxDD {dd:6.2f}")
n, c2, w, dd = run(mid, len(T), best[1], best[2])
print(f"  picked filter     : n {c2:3d} wr {w/max(1,c2):.0%} "
      f"net {n:+8.2f} maxDD {dd:6.2f}")

print("== random-direction controls, full 69d, same filter ==")
n, c2, w, dd = run(0, len(T), best[1], best[2])
print(f"  signal+filter     : n {c2:3d} wr {w/max(1,c2):.0%} "
      f"net {n:+8.2f} maxDD {dd:6.2f}")
for s in (11, 22, 33, 44, 55):
    n, c2, w, dd = run(0, len(T), best[1], best[2], "random", s)
    print(f"  random+filter s{s:2d}: n {c2:3d} wr {w/max(1,c2):.0%} "
          f"net {n:+8.2f} maxDD {dd:6.2f}")
