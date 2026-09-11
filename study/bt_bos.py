"""Backtest of the user's structure-bot rules (2026-09-08):
enter every BOS of a confirmed trend, SL at the glowing dot,
TP = 0.8 x risk, one position at a time, base 0.02.

Engine = the chart's exact rules (silence filter: close beyond last
shown high/low; dots confirmed by closes; 2-dot bootstrap;
CHoCH -> first fresh BOS flips the trend). Execution on RAW M1 bars
(silenced candles still move price), bid OHLC + $7 ask spread,
ties = SL (pessimistic).

Modes: signal (the rule) | random (coin direction at the same
signal times and distances - the control).
"""
import sys
import numpy as np

import os
D = np.load(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "pro_m1.npz"))
O, H, L, C = (D[k].astype(float) for k in "ohlc")
T = D["t"].astype(int)
S = 7.0
LOT = 0.02
RR = 0.8


class Struct:
    """Incremental port of the chart feed's build()+engine()."""

    def __init__(self):
        self.kept = []
        self.ref_h = self.ref_l = None
        self.hi_i = self.lo_i = 0
        self.hi_v = self.lo_v = None
        self.trend = 0
        self.choch = 0
        self.last_lo = self.last_hi = None
        self.up_st = self.dn_st = 0
        self.prot_lo = self.prot_hi = None

    def step(self, t, o, h, l, c):
        """Feed one CLOSED raw candle. Returns a signal
        (dir, sl_price) when a trend-side dot confirms (=BOS entry),
        else None."""
        if self.ref_h is not None and not (c > self.ref_h
                                           or c < self.ref_l):
            return None                      # silenced candle
        k = self.kept
        k.append([t, o, h, l, c, 1 if c >= o else -1])
        self.ref_h, self.ref_l = h, l
        i = len(k) - 1
        if i == 0:
            self.hi_v, self.lo_v = h, l
            return None
        sig = None
        # CHoCH
        if (self.trend == 1 and self.prot_lo is not None
                and c < self.prot_lo[1]):
            self.choch = -1
            self.prot_lo = None
            self.lo_i, self.lo_v = i, l
        elif (self.trend == -1 and self.prot_hi is not None
                and c > self.prot_hi[1]):
            self.choch = 1
            self.prot_hi = None
            self.hi_i, self.hi_v = i, h
        if c > self.hi_v:
            span = k[self.hi_i + 1:i]
            if span and any(x[5] == -1 for x in span):
                m = min(span, key=lambda x: x[3])
                nd = [m[0], m[3], 1]
                if self.choch == 1 and self.trend != 1:
                    self.trend = 1
                    self.choch = 0
                    self.prot_lo = nd
                    self.up_st = self.dn_st = 0
                    sig = (1, m[3])
                elif self.trend == 1:
                    self.prot_lo = nd
                    self.choch = 0
                    sig = (1, m[3])
                elif self.trend == 0:
                    if self.last_lo is not None and m[3] > self.last_lo:
                        self.up_st += 1
                        if self.up_st >= 2:
                            self.trend = 1
                            self.prot_lo = nd
                            self.dn_st = 0
                            sig = (1, m[3])
                    else:
                        self.up_st = 0
                self.last_lo = m[3]
                self.lo_i = k.index(m)
                self.lo_v = m[3]
            self.hi_i, self.hi_v = i, h
        elif c < self.lo_v:
            span = k[self.lo_i + 1:i]
            if span and any(x[5] == 1 for x in span):
                m = max(span, key=lambda x: x[2])
                nd = [m[0], m[2], -1]
                if self.choch == -1 and self.trend != -1:
                    self.trend = -1
                    self.choch = 0
                    self.prot_hi = nd
                    self.up_st = self.dn_st = 0
                    sig = (-1, m[2])
                elif self.trend == -1:
                    self.prot_hi = nd
                    self.choch = 0
                    sig = (-1, m[2])
                elif self.trend == 0:
                    if self.last_hi is not None and m[2] < self.last_hi:
                        self.dn_st += 1
                        if self.dn_st >= 2:
                            self.trend = -1
                            self.prot_hi = nd
                            self.up_st = 0
                            sig = (-1, m[2])
                    else:
                        self.dn_st = 0
                self.last_hi = m[2]
                self.hi_i = k.index(m)
                self.hi_v = m[2]
            self.lo_i, self.lo_v = i, l
        return sig


def run(mode="signal", seed=1):
    st = Struct()
    pos = None
    res = []
    skipped_busy = 0
    rs = [seed]

    def rnd():
        rs[0] = (rs[0] * 1103515245 + 12345) % (2 ** 31)
        return rs[0] / (2 ** 31)

    for j in range(len(T)):
        t, o, h, l, c = T[j], O[j], H[j], L[j], C[j]
        if pos is not None:
            d, e, sl, tp = pos
            if d == 1:
                sl_hit = l <= sl
                tp_hit = h >= tp
            else:
                sl_hit = h >= sl - S
                tp_hit = l <= tp - S
            if sl_hit:                        # ties = SL
                res.append((j, (sl - e) * d * LOT, "sl"))
                pos = None
            elif tp_hit:
                res.append((j, (tp - e) * d * LOT, "tp"))
                pos = None
        sig = st.step(t, o, h, l, c)
        if sig is None:
            continue
        if pos is not None:
            skipped_busy += 1
            continue
        d, slp = sig
        if mode == "random":
            dist = abs(c - slp)
            d = 1 if rnd() < 0.5 else -1
            slp = c - d * dist
        if d == 1:
            e = c + S
            if e - slp <= S:
                continue                     # dot inside the spread
            tp = e + RR * (e - slp)
        else:
            e = c
            if slp - e <= S:
                continue
            tp = e - RR * (slp - e)
        pos = (d, e, slp, tp)
    W = [r for r in res if r[1] > 0]
    Lo = [r for r in res if r[1] < 0]
    net = sum(r[1] for r in res)
    cum = peak = mdd = 0.0
    for r in res:
        cum += r[1]
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    days = (T[-1] - T[0]) / 86400
    print(f"{mode:7s}: n {len(res):4d} ({len(res)/days*1.0:.1f}/day) "
          f"wr {len(W)/max(1,len(W)+len(Lo)):.0%} net {net:+8.2f} "
          f"avgW {sum(r[1] for r in W)/max(1,len(W)):+.3f} "
          f"avgL {sum(r[1] for r in Lo)/max(1,len(Lo)):+.3f} "
          f"maxDD {mdd:6.2f} busy-skips {skipped_busy}")
    return net


print(f"{len(T)} bars, {(T[-1]-T[0])/86400:.0f} days, spread ${S}, "
      f"lot {LOT}, RR {RR}")
run("signal")
for s in (11, 22, 33):
    run("random", seed=s)
