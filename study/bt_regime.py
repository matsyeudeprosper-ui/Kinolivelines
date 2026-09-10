"""User 2026-09-10: 'no indicator that identifies the ranging
market so we pause and resume?'  Fair trial for the classic
regime meters, as entry gates on the touch-config base stream:
  ER60/ER240 - Kaufman efficiency ratio (net move / path length)
  ADX14      - Wilder ADX on M15 bars
Gate: trade only when metric >= a percentile threshold.
Thresholds picked on days 1-35 ONLY, blind test days 36-69,
random-direction controls for the picked gate."""
from collections import deque

import numpy as np

from bt_bos import Struct, O, H, L, C, T, S

LOT = 0.02
RR = 0.8
WIN = 7200
mid = int(np.searchsorted(T, T[0] + (T[-1] - T[0]) // 2))
n = len(T)

# --- efficiency ratios on M1 closes ---
absd = np.abs(np.diff(C, prepend=C[0]))
cpath = np.cumsum(absd)


def eff(win):
    e = np.zeros(n)
    idx = np.arange(n)
    lo = np.maximum(0, idx - win)
    path = cpath - cpath[lo]
    netm = np.abs(C - C[lo])
    with np.errstate(divide="ignore", invalid="ignore"):
        e = np.where(path > 0, netm / path, 0.0)
    return e


ER60 = eff(60)
ER240 = eff(240)

# --- ADX14 on M15 aggregation ---
m15 = n // 15
h15 = H[:m15 * 15].reshape(-1, 15).max(1)
l15 = L[:m15 * 15].reshape(-1, 15).min(1)
c15 = C[:m15 * 15].reshape(-1, 15)[:, -1]
up = h15[1:] - h15[:-1]
dn = l15[:-1] - l15[1:]
pdm = np.where((up > dn) & (up > 0), up, 0.0)
ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
tr15 = np.maximum(h15[1:] - l15[1:],
                  np.maximum(np.abs(h15[1:] - c15[:-1]),
                             np.abs(l15[1:] - c15[:-1])))
P = 14
atr_s = np.zeros(len(tr15))
pdm_s = np.zeros(len(tr15))
ndm_s = np.zeros(len(tr15))
atr_s[0], pdm_s[0], ndm_s[0] = tr15[0], pdm[0], ndm[0]
for i in range(1, len(tr15)):
    atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / P + tr15[i]
    pdm_s[i] = pdm_s[i - 1] - pdm_s[i - 1] / P + pdm[i]
    ndm_s[i] = ndm_s[i - 1] - ndm_s[i - 1] / P + ndm[i]
with np.errstate(divide="ignore", invalid="ignore"):
    pdi = 100 * pdm_s / atr_s
    ndi = 100 * ndm_s / atr_s
    dx = 100 * np.abs(pdi - ndi) / np.maximum(pdi + ndi, 1e-9)
adx15 = np.zeros(len(dx))
adx15[0] = dx[0]
for i in range(1, len(dx)):
    adx15[i] = (adx15[i - 1] * (P - 1) + dx[i]) / P
# map back to M1 index (bar i sees the LAST CLOSED M15 value)
ADX = np.zeros(n)
for j in range(n):
    k = min(j // 15 - 1, len(adx15) - 1)
    ADX[j] = adx15[k] if k >= 0 else 0.0


def run(a, b, metric=None, thr=0.0, mode="signal", seed=1):
    st = Struct()
    pos = None
    ev = deque()
    out = []
    used_hi = used_lo = None
    rs = [seed]

    def rnd():
        rs[0] = (rs[0] * 1103515245 + 12345) % (2 ** 31)
        return rs[0] / (2 ** 31)

    def gate(j):
        return metric is None or metric[j] >= thr

    def mkpos(d, e, slp):
        if mode == "random":
            dist = abs(e - slp)
            d = 1 if rnd() < 0.5 else -1
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
                        if gate(j):
                            pos = mkpos(1, e, slp)
            elif (st.trend == -1 and st.lo_v is not None
                    and l < st.lo_v and used_lo != st.lo_v):
                span = st.kept[st.lo_i + 1:]
                if span and any(x[5] == 1 for x in span):
                    slp = max(span, key=lambda x: x[2])[2]
                    e = st.lo_v
                    if slp - e > S:
                        used_lo = st.lo_v
                        if gate(j):
                            pos = mkpos(-1, e, slp)
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
        if pos is None and gate(j):
            pos = mkpos(d, e2, slp)
    W = sum(1 for x in out if x > 0)
    cum = pk = mdd = 0.0
    for x in out:
        cum += x
        pk = max(pk, cum)
        mdd = max(mdd, pk - cum)
    return sum(out), len(out), W, mdd


def show(lbl, r):
    nn, c2, w, dd = r
    print(f"  {lbl:26s}: n {c2:3d} wr {w/max(1,c2):.0%} "
          f"net {nn:+8.2f} maxDD {dd:6.2f}")


METS = {"ER60": ER60, "ER240": ER240, "ADX14/M15": ADX}
print("== grid on FIRST half only ==")
show("h1 baseline", run(0, mid))
best = None
for name, m in METS.items():
    for pct in (30, 40, 50, 60):
        thr = float(np.percentile(m[:mid], pct))
        r = run(0, mid, m, thr)
        show(f"h1 {name} >=p{pct} ({thr:.2f})", r)
        if best is None or r[0] > best[0]:
            best = (r[0], name, m, thr, pct)
print(f"picked: {best[1]} >= p{best[4]} ({best[3]:.2f})")
print("== BLIND second half ==")
show("h2 baseline", run(mid, n))
show(f"h2 {best[1]} gate", run(mid, n, best[2], best[3]))
print("== random-direction controls, gate ON, full 69d ==")
show("signal + gate", run(0, n, best[2], best[3]))
for s in (11, 22, 33):
    show(f"random + gate s{s}",
         run(0, n, best[2], best[3], "random", s))
