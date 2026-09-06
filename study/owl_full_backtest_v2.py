"""Full-system backtest v2 - the rulebook as of 2026-09-06 evening.

Serial by design (ONE-SAGA): page -> its fighters -> chain ends -> next
page. Entries: fresh structure only, NO-CHASE (confirmation > max(20,
35% of wall) beyond the level = retest-arm instead; retest within 15pts
enters, new pattern replaces). Fighters: door candle-closes; FLIPS wait
for a pullback structure in the break direction (SL = extreme since the
stopped entry, at entry time); re-entries immediate. Guards: lock40 ->
breakeven-plus, partial85 (>=0.02), deep >=0.04 bank70 + heal(debt+3
when nearer than 1:1), min wall 60, $35/link, $100 chain stop, 6h
expiries. Storms: 3 real losses(>|0.5|) -> chain freezes, VIRTUAL twin
of this exact machine runs; a virtual WIN (tp/bank) lifts; frozen chain
resumes on next structure (its lot), flip-waits stay direction-locked.
Costs: $10 spread per entry. Ambiguous bars: half/half.
Compare: v1 rulebook scored -176.62 on the same 69 days.
"""
from datetime import datetime, timezone
import MetaTrader5 as mt5

SPREAD, MIN_WALL, LINK_CAP, CHAIN_CAP = 10.0, 60.0, 35.27, 100.0
PAGE_LOT, PAGE_TGT, PAGE_MAXR, BUFFER = 0.01, 1.50, 2.50, 0.10
mt5.initialize(path=r"C:\Projects\MT5-KinoliveTrader\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 1, 99000)
mt5.shutdown()
O = R["open"].astype(float)
H = R["high"].astype(float)
L = R["low"].astype(float)
C = R["close"].astype(float)
T = R["time"].astype(int)
N = len(R)
print(f"bars {N}  {datetime.fromtimestamp(int(T[0]), tz=timezone.utc):%Y-%m-%d}"
      f" -> {datetime.fromtimestamp(int(T[-1]), tz=timezone.utc):%Y-%m-%d}")


class Det:
    """Structure detector with NO-CHASE + retest."""

    def __init__(self):
        self.up, self.dn = {}, {}

    def step(self, i):
        po, pc, ph, pl = O[i - 1], C[i - 1], H[i - 1], L[i - 1]
        co, cc, ch, cl = O[i], C[i], H[i], L[i]
        up, dn = self.up, self.dn
        sig = None
        if pc > po and cc > co and cc > ph:
            up.clear()
            up.update(leg=True, peak=ch, glow=cl)
        elif up.get("leg"):
            up["peak"] = max(up["peak"], ch)
            if cc > co:
                up["glow"] = cl
            elif cc < up["glow"]:
                up.update(pending=up["peak"], plow=cl, leg=False,
                          pt=T[i], retest=None)
        if up.get("pending"):
            up["plow"] = min(up.get("plow", cl), cl)
            if T[i] - up["pt"] > 21600:
                up["pending"] = None
            elif cc > up["pending"]:
                wd = abs(up["pending"] - up["plow"])
                if cc - up["pending"] > max(20.0, 0.35 * wd):
                    up.update(retest=up["pending"],
                              rt_plow=up["plow"], rt_t=T[i],
                              pending=None)
                else:
                    sig = (1, up["plow"])
                    up["pending"] = None
        elif up.get("retest"):
            if T[i] - up.get("rt_t", T[i]) > 21600:
                up["retest"] = None
            elif (cl <= up["retest"] + 15.0
                  and cc >= up["retest"] - 15.0):
                sig = (1, up.get("rt_plow", cl))
                up["retest"] = None
        if pc < po and cc < co and cc < pl:
            dn.clear()
            dn.update(leg=True, dip=cl, rhigh=ch)
        elif dn.get("leg"):
            dn["dip"] = min(dn["dip"], cl)
            if cc < co:
                dn["rhigh"] = ch
            elif cc > dn["rhigh"]:
                dn.update(pending=dn["dip"], phigh=ch, leg=False,
                          pt=T[i], retest=None)
        if dn.get("pending") and sig is None:
            dn["phigh"] = max(dn.get("phigh", ch), ch)
            if T[i] - dn["pt"] > 21600:
                dn["pending"] = None
            elif cc < dn["pending"]:
                wd = abs(dn["phigh"] - dn["pending"])
                if dn["pending"] - cc > max(20.0, 0.35 * wd):
                    dn.update(retest=dn["pending"],
                              rt_phigh=dn["phigh"], rt_t=T[i],
                              pending=None)
                else:
                    sig = (-1, dn["phigh"])
                    dn["pending"] = None
        elif dn.get("retest") and sig is None:
            if T[i] - dn.get("rt_t", T[i]) > 21600:
                dn["retest"] = None
            elif (ch >= dn["retest"] - 15.0
                  and cc <= dn["retest"] + 15.0):
                sig = (-1, dn.get("rt_phigh", ch))
                dn["retest"] = None
        return sig


class Machine:
    """One serial saga machine. virtual=True: same rules, no money."""

    def __init__(self, virtual):
        self.virtual = virtual
        self.det = Det()
        self.pos = None          # open position dict
        self.watch = None        # door watch
        self.flip = None         # flip-wait {dir, lot, t0, loss}
        self.chain_loss = 0.0
        self.results = []        # real closes: (i, lot, pnl, kind)
        self.won = False         # virtual: a win happened (lift)

    def busy(self):
        return (self.pos is not None or self.watch is not None
                or self.flip is not None)

    def open_pos(self, i, d, lot, e, wall, chainpos):
        dist = abs(e - wall)
        disc = min(1.0, 0.25 * dist * lot)
        tpd = dist - disc / lot
        if chainpos and lot >= 0.04 and self.chain_loss > 0:
            hd = (self.chain_loss + 3.0) / lot
            if MIN_WALL < hd < tpd:
                tpd = hd
        if not chainpos:
            tpd = min(tpd, PAGE_TGT / lot)
        self.pos = dict(d=d, lot=lot, e=e, sl=wall, tp=e + d * tpd,
                        locked=False, parted=False, t0=i,
                        chain=chainpos)

    def close(self, i, px, kind):
        p = self.pos
        pnl = (px - p["e"]) * p["d"] * p["lot"]
        self.pos = None
        if kind in ("sl", "scratch"):
            self.chain_loss += max(0.0, -pnl)
            self.watch = dict(dir=p["d"], sl=p["sl"], trig=p["e"],
                              lot=p["lot"], t=T[i], t0=p["t0"])
        else:
            self.chain_loss = 0.0     # profitable close ends the chain
            if pnl > 0:
                self.won = True
        return pnl, kind

    def bar(self, i):
        """Advance one bar. Returns list of (pnl, kind) real closes."""
        out = []
        p = self.pos
        if p is not None:
            hi, lo, d = H[i], L[i], p["d"]
            prize = abs(p["tp"] - p["e"])
            fav = ((hi if d == 1 else 2 * p["e"] - lo) - p["e"]) * 1.0
            fav = (hi - p["e"]) if d == 1 else (p["e"] - lo)
            if (not p["parted"] and p["lot"] >= 0.02
                    and fav >= 0.85 * prize):
                out.append((0.85 * prize * (p["lot"] / 2), "partial"))
                p["parted"] = True
                p["lot"] = round(p["lot"] / 2, 2)
            if p["chain"] and p["lot"] >= 0.04 and fav >= 0.70 * prize:
                out.append(self.close(i, p["e"] + p["d"] * 0.70
                                      * prize, "bank70"))
                return out
            if not p["locked"] and fav >= 0.40 * prize:
                p["locked"] = True
                p["cur"] = p["e"] + p["d"] * min(
                    SPREAD + BUFFER / p["lot"], 0.5 * fav)
            slv = p.get("cur", p["sl"]) if p["locked"] else p["sl"]
            tp_hit = (hi >= p["tp"]) if d == 1 else (lo <= p["tp"])
            sl_hit = (lo <= slv) if d == 1 else (hi >= slv)
            if tp_hit and sl_hit:
                out.append(self.close(i, (p["tp"] + slv) / 2, "tie"))
            elif sl_hit:
                out.append(self.close(
                    i, slv, "scratch" if p["locked"] else "sl"))
            elif tp_hit:
                out.append(self.close(i, p["tp"], "tp"))
            return out
        w = self.watch
        if w is not None:
            if T[i] - w["t"] > 21600:
                self.watch = None
                self.chain_loss = 0.0
                return out
            cc = C[i]
            broke = (cc < w["sl"]) if w["dir"] == 1 else (cc > w["sl"])
            reent = (not broke and ((cc > w["trig"]) if w["dir"] == 1
                                    else (cc < w["trig"])))
            nl = round(w["lot"] + 0.01, 2)
            if broke:
                self.flip = dict(dir=-w["dir"], lot=nl, t0=w["t0"],
                                 t=T[i])
                self.watch = None
            elif reent:
                j0 = w["t0"]
                wall = (min(L[j0:i + 1]) if w["dir"] == 1
                        else max(H[j0:i + 1]))
                e = C[i] + (SPREAD if w["dir"] == 1 else 0.0)
                dist = abs(e - wall)
                if dist * nl >= CHAIN_CAP:
                    self.watch = None
                    self.chain_loss = 0.0
                elif dist >= MIN_WALL and dist * nl <= LINK_CAP:
                    self.watch = None
                    self.open_pos(i, w["dir"], nl, e, wall, True)
            return out
        f = self.flip
        sig = self.det.step(i)
        if f is not None:
            if T[i] - f["t"] > 21600:
                self.flip = None
                self.chain_loss = 0.0
            elif sig is not None and sig[0] == f["dir"]:
                j0 = f["t0"]
                wall = (min(L[j0:i + 1]) if f["dir"] == 1
                        else max(H[j0:i + 1]))
                e = C[i] + (SPREAD if f["dir"] == 1 else 0.0)
                dist = abs(e - wall)
                if dist * f["lot"] >= CHAIN_CAP:
                    self.flip = None
                    self.chain_loss = 0.0
                elif dist >= MIN_WALL and dist * f["lot"] <= LINK_CAP:
                    self.flip = None
                    self.open_pos(i, f["dir"], f["lot"], e, wall, True)
            return out
        if sig is not None:
            d, wall = sig
            e = C[i] + (SPREAD if d == 1 else 0.0)
            dist = abs(e - wall)
            if MIN_WALL <= dist and dist * PAGE_LOT <= PAGE_MAXR:
                self.chain_loss = 0.0
                self.open_pos(i, d, PAGE_LOT, e, wall, False)
        return out


real = Machine(False)
virt = None
frozen = None            # (lot, loss) of the frozen chain
storm = False
ls = 0
balance = 150.0
closed = []
storms = 0
resume_det = Det()

for i in range(40, N):
    if not storm:
        for pnl, kind in real.bar(i):
            balance += pnl
            closed.append((i, pnl, kind))
            if pnl < -0.5:
                ls += 1
                if ls >= 3:
                    storm = True
                    storms += 1
                    # freeze whatever the chain was building
                    if real.watch is not None:
                        frozen = (round(real.watch["lot"] + 0.01, 2),
                                  real.chain_loss)
                        real.watch = None
                    elif real.flip is not None:
                        frozen = (real.flip["lot"], real.chain_loss)
                        real.flip = None
                    virt = Machine(True)
                    virt.det = Det()
            elif pnl > 0.5:
                ls = 0
    else:
        # open real position (if any) still finishes on its own
        if real.pos is not None:
            for pnl, kind in real.bar(i):
                balance += pnl
                closed.append((i, pnl, kind))
        virt.bar(i)
        if virt.won:
            storm = False
            ls = 0
            virt = None
            real.det = Det()          # fresh eyes after the storm
    if not storm and frozen is not None and not real.busy():
        sig = resume_det.step(i)
        if sig is not None:
            d, wall = sig
            lot, loss = frozen
            e = C[i] + (SPREAD if d == 1 else 0.0)
            dist = abs(e - wall)
            if MIN_WALL <= dist and dist * lot <= LINK_CAP:
                real.chain_loss = loss
                real.open_pos(i, d, lot, e, wall, True)
                frozen = None
    elif not storm and frozen is None:
        resume_det.step(i)

wins = [c for c in closed if c[1] > 0.05]
losses = [c for c in closed if c[1] < -0.05]
print(f"\ndays {(T[-1]-T[0])/86400:.0f}  trades {len(closed)}  "
      f"storms {storms}")
print(f"wins {len(wins)} avg +{sum(c[1] for c in wins)/max(1,len(wins)):.2f}"
      f"  losses {len(losses)} avg "
      f"{sum(c[1] for c in losses)/max(1,len(losses)):.2f}")
print(f"net {balance-150:+.2f}  (v1 rulebook was -176.62)")
days = {}
for i2, pnl, kind in closed:
    k = datetime.fromtimestamp(int(T[i2]), tz=timezone.utc).strftime("%m-%d")
    days[k] = days.get(k, 0.0) + pnl
neg = sum(1 for v in days.values() if v < 0)
print(f"trading days {len(days)}  green {len(days)-neg}  red {neg}  "
      f"best {max(days.values(), default=0):+.2f}  "
      f"worst {min(days.values(), default=0):+.2f}")
cum = peak = mdd = 0.0
for i2, pnl, kind in closed:
    cum += pnl
    peak = max(peak, cum)
    mdd = max(mdd, peak - cum)
print(f"max drawdown {mdd:.2f}")
