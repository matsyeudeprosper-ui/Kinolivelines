"""User 2026-09-11: count the CHoCH as an entry as well.

Live config (awake gate 2h, flip-BOS on close, continuation touch
entries, SL at dot, TP 0.8R, one trade at a time) PLUS: on the bar
whose close breaks the protected dot (= CHoCH), enter in the CHoCH
direction.  SL = the swing extreme the market just turned from
(running high of the up-leg for a bearish CHoCH, running low for a
bullish one); TP = 0.8 x risk.  Spread-correct, ties = SL.

Variants: choch gated by the awake window like every other entry
(gate) / choch exempt from the gate (nogate) / choch entries only
(only) / random-direction control on the choch trades (rnd).
"""
from collections import deque

import numpy as np

from bt_bos import Struct, O, H, L, C, T, S

LOT = 0.02
RR = 0.8
WIN = 7200
mid = int(np.searchsorted(T, T[0] + (T[-1] - T[0]) // 2))


def run(a, b, choch="off", seed=1):
    st = Struct()
    pos = None
    ev = deque()
    out = []
    tag = []
    used_hi = used_lo = None
    rs = [seed]

    def rnd():
        rs[0] = (rs[0] * 1103515245 + 12345) % (2 ** 31)
        return rs[0] / (2 ** 31)

    def mkpos(d, mid_e, dist):
        e = mid_e + (S if d == 1 else 0.0)
        return (d, e, e - d * dist, e + d * RR * dist)

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
        if pos is None and ev and choch != "only":
            if (st.trend == 1 and st.hi_v is not None
                    and h > st.hi_v and used_hi != st.hi_v):
                span = st.kept[st.hi_i + 1:]
                if span and any(x[5] == -1 for x in span):
                    slp = min(span, key=lambda x: x[3])[3]
                    if st.hi_v + S - slp > S:
                        used_hi = st.hi_v
                        pos = mkpos(1, st.hi_v, st.hi_v + S - slp)
                        tag.append("bos")
            elif (st.trend == -1 and st.lo_v is not None
                    and l < st.lo_v and used_lo != st.lo_v):
                span = st.kept[st.lo_i + 1:]
                if span and any(x[5] == 1 for x in span):
                    slp = max(span, key=lambda x: x[2])[2]
                    if slp - st.lo_v > S:
                        used_lo = st.lo_v
                        pos = mkpos(-1, st.lo_v, slp - st.lo_v)
                        tag.append("bos")
        pt, pch = st.trend, st.choch
        p_hi, p_lo = st.hi_v, st.lo_v
        sig = st.step(t, o, h, l, c)
        if st.trend != pt and st.trend != 0 and pt != 0:
            ev.append(t)
        while ev and ev[0] < t - WIN:
            ev.popleft()
        # --- CHoCH entry ---
        if (choch != "off" and st.choch != 0 and st.choch != pch
                and pos is None and (ev or choch == "nogate")):
            d = st.choch
            slp = p_lo if d == 1 else p_hi
            if choch == "rnd":
                dist = abs(c - slp)
                d = 1 if rnd() < 0.5 else -1
                slp = c - d * dist
            e2 = c + S if d == 1 else c
            if slp is not None and abs(e2 - slp) > S:
                pos = mkpos(d, c, abs(e2 - slp))
                tag.append("choch")
                continue
        if choch == "only":
            continue
        if sig is None or pos is not None or not ev:
            continue
        if st.trend == pt:
            continue
        d, slp = sig
        e2 = c + S if d == 1 else c
        if abs(e2 - slp) <= S:
            continue
        pos = mkpos(d, c, abs(e2 - slp))
        tag.append("bos")
    W = sum(1 for x in out if x > 0)
    cum = pk = mdd = 0.0
    for x in out:
        cum += x
        pk = max(pk, cum)
        mdd = max(mdd, pk - cum)
    ch = [x for x, g in zip(out, tag) if g == "choch"]
    chw = sum(1 for x in ch if x > 0)
    return sum(out), len(out), W, mdd, sum(ch), len(ch), chw


print(f"{len(T)} bars, {(T[-1]-T[0])/86400:.0f} days, spread ${S}, "
      f"lot {LOT}, RR {RR}")
for lbl, mode, sd in (("baseline (live)  ", "off", 1),
                      ("+choch gated     ", "gate", 1),
                      ("+choch no gate   ", "nogate", 1),
                      ("choch ONLY (gate)", "only", 1),
                      ("+choch RANDOM dir", "rnd", 11),
                      ("+choch RANDOM dir", "rnd", 22),
                      ("+choch RANDOM dir", "rnd", 33)):
    n, c2, w, dd, cn, cc, cw = run(0, len(T), mode, sd)
    n1 = run(0, mid, mode, sd)[0]
    n2 = run(mid, len(T), mode, sd)[0]
    extra = (f" | choch part: n {cc:3d} wr {cw/max(1,cc):.0%} "
             f"net {cn:+7.2f}") if cc else ""
    print(f"{lbl}: n {c2:4d} wr {w/max(1,c2):.0%} net {n:+8.2f} "
          f"maxDD {dd:6.2f} | h1 {n1:+7.2f} h2 {n2:+7.2f}{extra}")
