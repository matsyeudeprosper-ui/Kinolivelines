"""signals.py (2026-10-30, Owl v2) - candidate entry families for fastbt.simulate: (m1_index, dir, stop_dist, tp_dist)."""
import numpy as np
import fastbt as F

_C = {}


def tfb(m):
    if m not in _C:
        b = F.agg(m)
        b["atr"] = F.atr(b)
        _C[m] = b
    return _C[m]


def trend_at(htf, n, ix_m1, how="slope"):
    """+1/-1 trend of the higher frame known at each M1 index (last CLOSED htf bar): EMA slope or close vs EMA"""
    b = tfb(htf)
    key = ("tr", htf, n, how)
    if key not in _C:
        e = F.ema(b["c"], n)
        _C[key] = np.sign(np.r_[0, np.diff(e)]) if how == "slope" else np.sign(b["c"] - e)
    tr = _C[key]
    k = np.searchsorted(b["ix"], ix_m1, side="right") - 1         # htf bars whose close is at/before this entry
    return np.where(k >= 0, tr[np.maximum(k, 0)], 0)


def pivots(b, k):
    """swing highs / lows: index j is a pivot when it is the extreme of j-k..j+k; known at bar j+k"""
    h, l = b["h"], b["l"]
    n = len(h)
    ph = np.zeros(n, bool)
    pl = np.zeros(n, bool)
    from numpy.lib.stride_tricks import sliding_window_view as sw
    if n > 2 * k:
        H = sw(h, 2 * k + 1)
        L = sw(l, 2 * k + 1)
        ph[k:n - k] = H.argmax(1) == k
        pl[k:n - k] = L.argmin(1) == k
    return ph, pl


def bos(tf=5, k=3, rr=1.0, stop="struct", m_atr=1.0, mode="follow", min_atr=0.3, max_atr=4.0, min_sp=4.0):
    b = tfb(tf)
    ph, pl = pivots(b, k)
    h, l, c, A, ix = b["h"], b["l"], b["c"], b["atr"], b["ix"]
    M = F.m1()
    sp = M["sp"]
    out = []
    sh = slo = None
    sh_used = sl_used = True
    for i in range(len(c)):
        j = i - k
        if j >= 0:
            if ph[j]:
                sh, sh_used = h[j], False
            if pl[j]:
                slo, sl_used = l[j], False
        if ix[i] >= len(sp):
            break
        d = 0
        if sh is not None and not sh_used and c[i] > sh:
            d, sh_used = 1, True
        elif slo is not None and not sl_used and c[i] < slo:
            d, sl_used = -1, True
        if not d:
            continue
        if stop == "struct":
            ref = slo if d == 1 else sh
            if ref is None:
                continue
            sd = abs(c[i] - ref)
        else:
            sd = m_atr * A[i]
        if not (min_atr * A[i] <= sd <= max_atr * A[i]) or sd < min_sp * sp[ix[i]]:
            continue
        dd = d if mode == "follow" else -d
        out.append((int(ix[i]), dd, float(sd), float(rr * sd)))
    return out


def orb(start_h=0, mins=60, rr=1.0, mode="follow", tf=1, max_atr_mult=None):
    """daily range of the first `mins` minutes after start_h UTC; first close outside it trades, stop at the other side"""
    M = F.m1()
    t, h, l, c, sp = M["t"], M["h"], M["l"], M["c"], M["sp"]
    day = (t - start_h * 3600) // 86400
    st = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    out = []
    for a, z in zip(st, np.r_[st[1:], len(t)]):
        e = a + mins
        if e >= z:
            continue
        hi, lo = h[a:e].max(), l[a:e].min()
        rng = hi - lo
        if rng < 4 * sp[e]:
            continue
        up = np.flatnonzero(c[e:z] > hi)
        dn = np.flatnonzero(c[e:z] < lo)
        ku, kd = (up[0] if len(up) else 10 ** 9), (dn[0] if len(dn) else 10 ** 9)
        if ku == kd:
            continue
        d, kk = (1, ku) if ku < kd else (-1, kd)
        i = e + kk + 1
        if i >= len(t):
            continue
        sd = rng
        out.append((int(i), d if mode == "follow" else -d, float(sd), float(rr * sd)))
    return out


def meanrev(tf=15, n=20, z=2.0, stop_z=1.0, rr=None):
    """close beyond z std of its n-bar mean -> fade it; target the mean (or rr x stop), stop stop_z std further"""
    b = tfb(tf)
    c, ix = b["c"], b["ix"]
    from numpy.lib.stride_tricks import sliding_window_view as sw
    W = sw(c, n)
    mu, sd = np.full(len(c), np.nan), np.full(len(c), np.nan)
    mu[n - 1:], sd[n - 1:] = W.mean(1), W.std(1)
    M = F.m1()
    sp = M["sp"]
    out = []
    for i in range(n, len(c)):
        if ix[i] >= len(sp) or not sd[i]:
            continue
        zz = (c[i] - mu[i]) / sd[i]
        if abs(zz) < z or abs((c[i - 1] - mu[i - 1]) / sd[i - 1]) >= z:
            continue
        d = -1 if zz > 0 else 1
        st = stop_z * sd[i]
        tp = abs(c[i] - mu[i]) if rr is None else rr * st
        if st < 4 * sp[ix[i]] or tp < 2 * sp[ix[i]]:
            continue
        out.append((int(ix[i]), d, float(st), float(tp)))
    return out


def random_like(sig, seed=1, keep_dir=False):
    """same entry times and geometry, random directions (the timing control: is the DIRECTION worth anything?)"""
    r = np.random.default_rng(seed)
    return [(i, (d if keep_dir else int(r.choice([-1, 1]))), sd, td) for (i, d, sd, td) in sig]


def filt_trend(sig, htf=60, n=50, side="with", how="slope"):
    if not sig:
        return sig
    ix = np.array([s[0] for s in sig])
    tr = trend_at(htf, n, ix, how)
    keep = (tr == np.array([s[1] for s in sig])) if side == "with" else (tr == -np.array([s[1] for s in sig]))
    return [s for s, k in zip(sig, keep) if k]
