"""Whipsaw fingerprint study (user 2026-09-10): do losing patches
share a signature that is measurable AT ENTRY TIME?  Per-trade
features on the touch-config base stream (no chest/adds), bucketed
P&L.  Any candidate filter must later pass walk-forward + random
controls before it goes anywhere near a bot."""
from collections import deque

import numpy as np

from bt_bos import Struct, O, H, L, C, T, S

LOT = 0.02
RR = 0.8
WIN = 7200

# rolling ATR60 (raw M1 true range, 60-bar mean)
tr = np.empty(len(T))
tr[0] = H[0] - L[0]
tr[1:] = np.maximum(H[1:] - L[1:],
                    np.maximum(np.abs(H[1:] - C[:-1]),
                               np.abs(L[1:] - C[:-1])))
cs = np.cumsum(tr)
atr = np.empty(len(T))
atr[:60] = cs[:60] / np.arange(1, 61)
atr[60:] = (cs[60:] - cs[:-60]) / 60

st = Struct()
pos = None
ev = deque()
out = []          # dicts
used_hi = used_lo = None
prev_risk = None

for j in range(len(T)):
    t, o, h, l, c = int(T[j]), O[j], H[j], L[j], C[j]
    if pos is not None:
        d, e, sl, tp, meta = pos
        sl_hit = (l <= sl) if d == 1 else (h >= sl - S)
        tp_hit = (h >= tp) if d == 1 else (l <= tp - S)
        if sl_hit or tp_hit:
            px = sl if sl_hit else tp
            meta["pnl"] = (px - e) * d * LOT
            out.append(meta)
            pos = None

    def feat(kind, e, slp, jj, cc):
        return dict(j=jj, kind=kind, flips=len(ev),
                    risk=abs(e - slp), atr=atr[jj],
                    ratio=(abs(e - slp) / prev_risk)
                    if prev_risk else None,
                    hour=(int(T[jj]) // 3600) % 24, pnl=0.0)

    if pos is None and ev:
        sigt = None
        if (st.trend == 1 and st.hi_v is not None
                and h > st.hi_v and used_hi != st.hi_v):
            span = st.kept[st.hi_i + 1:]
            if span and any(x[5] == -1 for x in span):
                slp = min(span, key=lambda x: x[3])[3]
                e = st.hi_v + S
                if e - slp > S:
                    used_hi = st.hi_v
                    sigt = (1, e, slp)
        elif (st.trend == -1 and st.lo_v is not None
                and l < st.lo_v and used_lo != st.lo_v):
            span = st.kept[st.lo_i + 1:]
            if span and any(x[5] == 1 for x in span):
                slp = max(span, key=lambda x: x[2])[2]
                e = st.lo_v
                if slp - e > S:
                    used_lo = st.lo_v
                    sigt = (-1, e, slp)
        if sigt:
            d, e, slp = sigt
            tp = e + d * RR * abs(e - slp)
            pos = (d, e, slp, tp, feat("cont", e, slp, j, c))
            prev_risk = abs(e - slp)
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
    tp = e2 + d * RR * abs(e2 - slp)
    pos = (d, e2, slp, tp, feat("flip", e2, slp, j, c))
    prev_risk = abs(e2 - slp)

print(f"{len(out)} trades, net {sum(x['pnl'] for x in out):+.2f}")


def bucket(lbl, rows):
    if not rows:
        print(f"  {lbl:24s}: (none)")
        return
    w = sum(1 for x in rows if x["pnl"] > 0)
    n = sum(x["pnl"] for x in rows)
    print(f"  {lbl:24s}: n {len(rows):4d} wr {w/len(rows):.0%} "
          f"net {n:+8.2f} avg {n/len(rows):+.3f}")


print("-- flips in last 2h at entry --")
for k, lo, hi in (("1", 1, 1), ("2", 2, 2), ("3", 3, 3),
                  ("4+", 4, 99)):
    bucket(k, [x for x in out if lo <= x["flips"] <= hi])

print("-- swing size (risk) / ATR60 --")
q = np.quantile([x["risk"] / x["atr"] for x in out],
                [0.25, 0.5, 0.75])
print(f"  quartile edges: {q[0]:.1f} / {q[1]:.1f} / {q[2]:.1f}")
for k, lo, hi in (("Q1 tiny", 0, q[0]), ("Q2", q[0], q[1]),
                  ("Q3", q[1], q[2]), ("Q4 wide", q[2], 9e9)):
    bucket(k, [x for x in out if lo <= x["risk"] / x["atr"] < hi])

print("-- structure shrinking? risk vs previous trade --")
for k, lo, hi in (("shrunk <0.6x", 0, 0.6), ("0.6-1.4x", 0.6, 1.4),
                  ("grew >1.4x", 1.4, 9e9)):
    bucket(k, [x for x in out
               if x["ratio"] is not None and lo <= x["ratio"] < hi])

print("-- hour of day (UTC) --")
for k, lo, hi in (("00-05", 0, 5), ("06-11", 6, 11),
                  ("12-17", 12, 17), ("18-23", 18, 23)):
    bucket(k, [x for x in out if lo <= x["hour"] <= hi])

print("-- combo: many flips (3+) x tiny swings (Q1) --")
bucket("3+ flips & Q1",
       [x for x in out
        if x["flips"] >= 3 and x["risk"] / x["atr"] < q[0]])
bucket("3+ flips & Q2+",
       [x for x in out
        if x["flips"] >= 3 and x["risk"] / x["atr"] >= q[0]])
bucket("1-2 flips & Q1",
       [x for x in out
        if x["flips"] < 3 and x["risk"] / x["atr"] < q[0]])

np.save("whip_rows.npy", np.array(out, dtype=object),
        allow_pickle=True)
