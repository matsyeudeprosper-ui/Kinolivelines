"""User detector + 2/hour slots + quarter-TP + optional door FLIPS
(2026-09-07 user request): page SL -> M1 close beyond the wall enters
the OPPOSITE direction at 0.02 (flip exempt from slots; its wall = M1
extreme since the stopped entry; quarter TP; one flip per loss - a
losing flip does not chain). Pages-only otherwise (matches the paper
trackers). Run: python bt_udet_flips.py [sep] [noflips]
"""
import sys
from datetime import datetime, timezone

import MetaTrader5 as mt5

SEP = "sep" in sys.argv
FLIPS = "noflips" not in sys.argv
SPREAD, MIN_WALL, PAGE_MAXR, PAGE_TGT = 10.0, 60.0, 2.50, 1.50
TPF, LOT, FLIP_LOT, BUF = 0.25, 0.01, 0.02, 0.10

mt5.initialize(path=r"C:\Projects\MT5-KinoliveTrader\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 1, 99000)
mt5.shutdown()
if SEP:
    import calendar
    ep = calendar.timegm((2026, 9, 1, 0, 0, 0))
    R = R[R["time"].astype(int) >= ep]
O = R["open"].astype(float)
H = R["high"].astype(float)
L = R["low"].astype(float)
C = R["close"].astype(float)
T = R["time"].astype(int)
N = len(R)


class Det:
    def __init__(self):
        self.up, self.dn = {}, {}

    def step(self, i):
        cc, ch, cl = C[i], H[i], L[i]
        t = T[i]
        up, dn = self.up, self.dn
        sig = None
        if not up.get("pending") and not up.get("retest"):
            if up.get("hh") is None or ch > up["hh"]:
                up["hh"], up["hhlow"] = ch, cl
            elif cc < up["hhlow"]:
                up.update(pending=up["hh"], plow=cl, pt=t,
                          retest=None, hh=None, hhlow=None)
        if up.get("pending"):
            up["plow"] = min(up.get("plow", cl), cl)
            if t - up["pt"] > 21600:
                up["pending"] = None
            elif cc > up["pending"]:
                wd = abs(up["pending"] - up["plow"])
                if cc - up["pending"] > max(20.0, 0.35 * wd):
                    up.update(retest=up["pending"],
                              rt_plow=up["plow"], rt_t=t, pending=None)
                else:
                    sig = (1, up["plow"])
                    up["pending"] = None
        elif up.get("retest"):
            if t - up.get("rt_t", t) > 21600:
                up["retest"] = None
            elif cl <= up["retest"] + 15.0 and cc >= up["retest"] - 15.0:
                sig = (1, up.get("rt_plow", cl))
                up["retest"] = None
        if not dn.get("pending") and not dn.get("retest"):
            if dn.get("ll") is None or cl < dn["ll"]:
                dn["ll"], dn["llhigh"] = cl, ch
            elif cc > dn["llhigh"]:
                dn.update(pending=dn["ll"], phigh=ch, pt=t,
                          retest=None, ll=None, llhigh=None)
        if dn.get("pending") and sig is None:
            dn["phigh"] = max(dn.get("phigh", ch), ch)
            if t - dn["pt"] > 21600:
                dn["pending"] = None
            elif cc < dn["pending"]:
                wd = abs(dn["phigh"] - dn["pending"])
                if dn["pending"] - cc > max(20.0, 0.35 * wd):
                    dn.update(retest=dn["pending"],
                              rt_phigh=dn["phigh"], rt_t=t,
                              pending=None)
                else:
                    sig = (-1, dn["phigh"])
                    dn["pending"] = None
        elif dn.get("retest") and sig is None:
            if t - dn.get("rt_t", t) > 21600:
                dn["retest"] = None
            elif ch >= dn["retest"] - 15.0 and cc <= dn["retest"] + 15.0:
                sig = (-1, dn.get("rt_phigh", ch))
                dn["retest"] = None
        return sig


det = Det()
pos = None
watch = None          # armed flip door after a page SL
slot_used = -1
closed = []
flips_fired = 0

for i in range(2, N):
    if pos is not None:
        d, e = pos["d"], pos["e"]
        prize = abs(pos["tp"] - e)
        fav = (H[i] - e) if d == 1 else (e - L[i])
        if not pos["locked"] and fav >= 0.40 * prize:
            pos["locked"] = True
            bump = min(SPREAD + BUF / pos["lot"], 0.5 * fav)
            pos["sl"] = e + d * bump
        slv = pos["sl"]
        tp_hit = H[i] >= pos["tp"] if d == 1 else L[i] <= pos["tp"]
        sl_hit = L[i] <= slv if d == 1 else H[i] >= slv
        if tp_hit or sl_hit:
            if tp_hit and sl_hit:
                out = (pos["tp"] + slv) / 2
                kind = "tie"
            elif sl_hit:
                out = slv
                kind = "scratch" if pos["locked"] else "sl"
            else:
                out = pos["tp"]
                kind = "tp"
            pnl = (out - e) * d * pos["lot"]
            closed.append((i, pnl, kind, pos["flip"]))
            if (FLIPS and kind == "sl" and not pos["flip"]
                    and pnl < -0.005):
                watch = dict(dir=d, sl=pos["sl0"], t0=pos["t0"],
                             t=T[i])
            pos = None
            det = Det()
        continue
    if watch is not None:
        if T[i] - watch["t"] > 21600:
            watch = None
        else:
            broke = (C[i] < watch["sl"] if watch["dir"] == 1
                     else C[i] > watch["sl"])
            if broke:
                nd = -watch["dir"]
                j0 = watch["t0"]
                wall = (max(H[j0:i + 1]) if nd == -1
                        else min(L[j0:i + 1]))
                e = C[i] + (SPREAD if nd == 1 else 0.0)
                dist = abs(e - wall)
                watch = None
                if dist >= MIN_WALL and dist * FLIP_LOT <= 35.27:
                    tpd = dist - min(1.0, 0.25 * dist * FLIP_LOT) \
                        / FLIP_LOT
                    tpd *= TPF
                    pos = dict(d=nd, lot=FLIP_LOT, e=e,
                               sl=wall, sl0=wall,
                               tp=e + nd * tpd, locked=False,
                               t0=i, flip=True)
                    flips_fired += 1
                continue
    sig = det.step(i)
    if sig is None:
        continue
    if T[i] // 1800 == slot_used:
        continue
    d, wall = sig
    e = C[i] + (SPREAD if d == 1 else 0.0)
    dist = abs(e - wall)
    if dist < MIN_WALL or dist * LOT > PAGE_MAXR:
        continue
    tpd = dist - min(1.0, 0.25 * dist * LOT) / LOT
    tpd = min(tpd, PAGE_TGT / LOT) * TPF
    pos = dict(d=d, lot=LOT, e=e, sl=wall, sl0=wall,
               tp=e + d * tpd, locked=False, t0=i, flip=False)
    slot_used = T[i] // 1800

net = sum(c[1] for c in closed)
wins = [c for c in closed if c[1] > 0.05]
losses = [c for c in closed if c[1] < -0.05]
fl = [c for c in closed if c[3]]
cum = peak = mdd = 0.0
for c in closed:
    cum += c[1]
    peak = max(peak, cum)
    mdd = max(mdd, peak - cum)
print(f"days {(T[-1]-T[0])/86400:.0f}  flips={'ON' if FLIPS else 'OFF'}"
      f"  trades {len(closed)}  net {net:+.2f}  mdd {mdd:.2f}")
print(f"wins {len(wins)} avg "
      f"{sum(c[1] for c in wins)/max(1,len(wins)):+.2f}  "
      f"losses {len(losses)} avg "
      f"{sum(c[1] for c in losses)/max(1,len(losses)):+.2f}")
print(f"flips fired {flips_fired}: net "
      f"{sum(c[1] for c in fl):+.2f} over {len(fl)} closed")
