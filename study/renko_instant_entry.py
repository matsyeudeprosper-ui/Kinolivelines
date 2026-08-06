"""INSTANT entry with no hindsight.

The previous version placed a stop order only at levels where a reversal was
already known to have confirmed later. That is hindsight: in real time a stop
resting at the gate is hit by ANY wick through it, including the many that never
confirm a reversal at all. Those are exactly the bad fills, and they were all
being skipped.

Here the gate is known from the current brick state alone, and the order fills on
the first touch, confirmed or not. Nothing about the future is consulted.

  A  WAIT     brick confirms on a closed M1 bar -> market fill at next bar open
  C  INSTANT  stop rests at the reversal gate -> fills on ANY touch, honestly

Intrabar fills cannot use their own bar's range (unknown ordering), so C's
barriers start on the following bar. A fills at a bar's open, so its own bar is
fair.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = 10.0
BRICK, REV = 50.0, 2
TPB, SLB, CAP, PT, START = 5, 3, 4, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
mt5.shutdown()
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c)
days = (tm[-1] - tm[0]) / 86400
print(f"M1 {N} bars, {days:.0f} days\n")


def run(mode):
    ao = ac = float(o[0]); d = 0; pd_ = 0        # brick state, from CLOSES
    tp, sl = BRICK * TPB, BRICK * SLB
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool); fresh = np.empty(0, dtype=bool)
    rec = False; pending = None; in_cycle = False
    peak = START; mdd = 0.0; lo = START; eq = START
    opened = trig = wick_only = 0
    by = {"tp": [], "rec": [], "forced": []}
    dead = None
    for j in range(N):
        # --- WAIT: fill last bar's confirmed signal at this open --------------
        if mode == "wait" and pending is not None:
            L, g = pending
            px = o[j] + SPREAD if L else o[j]
            if len(ent) == 0: in_cycle = True
            ent = np.append(ent, px); lng = np.append(lng, L)
            fresh = np.append(fresh, False); opened += 1; pending = None

        # --- the gates implied by the CURRENT brick state, known in advance ---
        up_gate = (ao if d == -1 else ac) + BRICK * (REV if d == -1 else 1)
        dn_gate = (ao if d == 1 else ac) - BRICK * (REV if d == 1 else 1)

        # --- INSTANT: a resting stop is hit by ANY touch, confirmed or not ----
        if mode == "instant":
            hitUp = (d == -1) and h[j] >= up_gate      # reversal gate, up
            hitDn = (d ==  1) and l[j] <= dn_gate      # reversal gate, down
            if hitUp or hitDn:
                trig += 1
                if not (c[j] >= up_gate if hitUp else c[j] <= dn_gate):
                    wick_only += 1                     # never confirmed on close
                can = (len(ent) == 0) or (rec and len(ent) <= CAP)
                if can and j + 1 < N:
                    L = hitUp
                    px = (up_gate + SPREAD) if L else dn_gate
                    if len(ent) == 0: in_cycle = True
                    ent = np.append(ent, px); lng = np.append(lng, L)
                    fresh = np.append(fresh, True); opened += 1

        # --- advance the brick state on this bar's CLOSE ----------------------
        ci = c[j]
        while True:
            u = (ao if d == -1 else ac) + BRICK * (REV if d == -1 else 1)
            n = (ao if d == 1 else ac) - BRICK * (REV if d == 1 else 1)
            if ci >= u:
                base = ao if d == -1 else ac; ao, ac, d = base, base + BRICK, 1
            elif ci <= n:
                base = ao if d == 1 else ac; ao, ac, d = base, base - BRICK, -1
            else:
                break
            if pd_ and d != pd_ and mode == "wait" and pending is None:
                can = (len(ent) == 0) or (rec and len(ent) <= CAP)
                if can and j + 1 < N:
                    pending = ((d == 1), u if d == 1 else n)
            pd_ = d

        # --- manage ------------------------------------------------------------
        if len(ent):
            hit = np.where(lng, h[j] >= ent + tp, l[j] <= ent - tp - SPREAD) & ~fresh
            if hit.any():
                bal += float(hit.sum()) * tp * PT
                ent, lng, fresh = ent[~hit], lng[~hit], fresh[~hit]
        if len(ent) and not rec:
            if (np.where(lng, l[j] <= ent - sl, h[j] >= ent + sl + SPREAD) & ~fresh).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j] - ent, ent - c[j] - SPREAD)) * PT) if len(ent) else 0.0
        eq = bal + flo
        closed = None
        if rec and len(ent) and eq >= cyc:
            closed = "rec"
        elif len(ent) > CAP:
            closed = "forced"
        if closed:
            by[closed].append(eq - cyc); in_cycle = False; bal = eq
            ent = np.empty(0); lng = np.empty(0, dtype=bool)
            fresh = np.empty(0, dtype=bool); eq = bal
        if len(ent) == 0:
            if in_cycle and closed is None:
                by["tp"].append(bal - cyc); in_cycle = False
            rec = False; cyc = bal
        fresh = np.zeros(len(ent), dtype=bool)
        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        if eq <= 0:
            dead = j; break
    allc = np.array(by["tp"] + by["rec"] + by["forced"]) if any(by.values()) else np.array([0.0])
    return dict(eq=eq, lo=lo, mdd=mdd, dead=dead, opened=opened, trig=trig,
                wick=wick_only, by=by, n=len(allc), exp=float(allc.mean()))


for mode, name in (("wait", "A  WAIT for the close (current bot)"),
                   ("instant", "C  INSTANT stop at the gate, HONEST")):
    z = run(mode)
    end = (f"DIED {datetime.utcfromtimestamp(tm[z['dead']]):%Y-%m-%d}"
           if z["dead"] is not None else f"${z['eq']:,.2f}")
    print(f"{name}")
    print(f"   final {end}   lowest ${z['lo']:,.2f}   worst drawdown ${z['mdd']:,.2f}")
    print(f"   positions opened {z['opened']}")
    if mode == "instant":
        print(f"   gate touches {z['trig']}, of which {z['wick']} "
              f"({100*z['wick']/max(1,z['trig']):.0f}%) NEVER confirmed on the close")
    b = z["by"]; n = max(1, z["n"]); f = lambda v: (np.mean(v) if v else 0.0)
    print(f"   cycles {z['n']}: target {len(b['tp'])} (${f(b['tp']):+.2f})  "
          f"recovered {len(b['rec'])} (${f(b['rec']):+.2f})  "
          f"cap {len(b['forced'])} (${f(b['forced']):+.2f})")
    print(f"   expectancy ${z['exp']:+.3f} per cycle\n")
