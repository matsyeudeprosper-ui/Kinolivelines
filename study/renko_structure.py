"""The user's renko-brick HH/HL structure definition (SPEC_HHLL_RENKO,
confirmed by the user 2026-08-08). ONE copy, imported by every spec that
tests it - same philosophy as hedge_engine.

Bricks replicate hedge_engine's walk exactly (brick 50, rev 2, seeded at
the slice's first OPEN, driven by CLOSES). Swing high = last brick close
of an up-run, confirmed when the first down-reversal brick prints; swing
low = mirror.
  buy[j]  = >=2 swing highs and lows confirmed by bar j, AND last swing
            high > previous AND last swing low > previous
  sell[j] = mirror (lower lows AND lower highs). Equal swings = neither.
Only bars <= j are ever used.
"""
import numpy as np

BRICK, REV = 50.0, 2


def renko_masks(R, brick=BRICK, rev=REV):
    o = R["open"].astype(float)
    c = R["close"].astype(float)
    N = len(c)
    buy = np.zeros(N, bool)
    sell = np.zeros(N, bool)
    ao = ac = float(o[0])
    d = 0
    sh, sl_ = [], []
    for j in range(N):
        ci = c[j]
        while True:
            u = (ao if d == -1 else ac) + brick * (rev if d == -1 else 1)
            n_ = (ao if d == 1 else ac) - brick * (rev if d == 1 else 1)
            if ci >= u:
                if d == -1:
                    sl_.append(ac)      # ac = lowest close of the down-run
                base = ao if d == -1 else ac
                ao, ac, d = base, base + brick, 1
            elif ci <= n_:
                if d == 1:
                    sh.append(ac)       # ac = highest close of the up-run
                base = ao if d == 1 else ac
                ao, ac, d = base, base - brick, -1
            else:
                break
        if len(sh) >= 2 and len(sl_) >= 2:
            buy[j] = sh[-1] > sh[-2] and sl_[-1] > sl_[-2]
            sell[j] = sh[-1] < sh[-2] and sl_[-1] < sl_[-2]
    return buy, sell
