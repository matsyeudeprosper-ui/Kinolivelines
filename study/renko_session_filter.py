"""Harvest with trading blocked during the Asian session.

Broker server time is UTC+0, verified against the live tick, so bar timestamps
are UTC and the session windows below mean what they say.

Two ways to "not trade in Asia", tested separately because they are different
strategies:
  NEW ONLY - do not START a cycle in the window, but if a basket is already open
             keep managing it normally (adds allowed). This is the natural
             reading and the only one that is safe: a basket with no stop loss
             must not be abandoned.
  ALL      - block every entry, including recovery adds. A basket opened before
             the window sits frozen until the window ends.

MULTIPLE COMPARISONS WARNING, printed with the results: 24 hours plus several
window definitions means several dozen ways to slice the same 278 days. Picking
the best slice after the fact is how noise gets promoted. The hour-by-hour table
below is DESCRIPTIVE. Any window that looks good needs its own out-of-sample
test before it means anything.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = 10.0
BRICK, REV = 50.0, 2
TPB, SLB, CAP, PT, START = 5, 3, 4, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000)
mt5.shutdown()
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c)
hour = np.array([datetime.utcfromtimestamp(t).hour for t in tm])
days = (tm[-1] - tm[0]) / 86400
print(f"M5 {days:.0f} days, UTC hours\n")


def run(block=None, mode="new"):
    """block = set of UTC hours to stay out of. mode 'new' or 'all'."""
    blocked = block or set()
    ao = ac = float(o[0]); d = 0; pd_ = 0
    tp, sl = BRICK * TPB, BRICK * SLB
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None; cyc_start = None
    peak = START; mdd = 0.0; lo = START; eq = START
    opened = 0; cycles = []
    dead = None
    for j in range(N):
        if pending is not None:
            L = pending
            px = o[j] + SPREAD if L else o[j]
            if len(ent) == 0: cyc_start = j
            ent = np.append(ent, px); lng = np.append(lng, L)
            opened += 1; pending = None
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
            if pd_ and d != pd_ and pending is None:
                new_cycle = (len(ent) == 0)
                allowed = (len(ent) == 0) or (rec and len(ent) <= CAP)
                inwin = hour[j] in blocked
                if inwin and (mode == "all" or new_cycle):
                    allowed = False
                if allowed and j + 1 < N:
                    pending = (d == 1)
            pd_ = d
        if len(ent):
            hit = np.where(lng, h[j] >= ent + tp, l[j] <= ent - tp - SPREAD)
            if hit.any():
                bal += float(hit.sum()) * tp * PT
                ent, lng = ent[~hit], lng[~hit]
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - sl, h[j] >= ent + sl + SPREAD).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j] - ent, ent - c[j] - SPREAD)) * PT) if len(ent) else 0.0
        eq = bal + flo
        out = None
        if rec and len(ent) and eq >= cyc:
            out = 1
        elif len(ent) > CAP:
            out = 1
        if out:
            cycles.append((cyc_start, eq - cyc)); bal = eq
            ent = np.empty(0); lng = np.empty(0, dtype=bool); eq = bal
        if len(ent) == 0:
            if out is None and cyc_start is not None:
                cycles.append((cyc_start, bal - cyc))
            cyc_start = None; rec = False; cyc = bal
        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        if eq <= 0:
            dead = j; break
    return dict(eq=eq, lo=lo, mdd=mdd, dead=dead, opened=opened, cycles=cycles)


base = run()
print(f"BASELINE, trade all hours:  ${base['eq']:,.2f}   "
      f"{base['opened']} positions   {len(base['cycles'])} cycles\n")

# --- descriptive: P&L of cycles by the hour they STARTED ---------------------
cy = [(hour[s], p) for s, p in base["cycles"] if s is not None]
print("cycle P&L by the UTC hour the cycle opened")
print(f"{'hr':>3}{'cycles':>8}{'total':>10}{'avg':>9}   {'':<20}")
tot_by_h = {}
for hh in range(24):
    sel = [p for (x, p) in cy if x == hh]
    if not sel:
        continue
    tot_by_h[hh] = sum(sel)
    bar = ("+" * min(20, int(sum(sel) / 2))) if sum(sel) > 0 else ("-" * min(20, int(-sum(sel) / 2)))
    print(f"{hh:>3}{len(sel):>8}{sum(sel):>10.2f}{np.mean(sel):>9.3f}   {bar}")

print("\n" + "=" * 74)
print("BLOCKING SESSION WINDOWS")
print("=" * 74)
wins = {
    "Tokyo 00-09 UTC":        set(range(0, 9)),
    "Asia wide 22-08 UTC":    set(list(range(22, 24)) + list(range(0, 8))),
    "Asia 00-08 UTC":         set(range(0, 8)),
    "Asia 01-07 UTC":         set(range(1, 7)),
}
print(f"{'window':<24}{'mode':<7}{'final':>12}{'lowest':>10}{'drawdn':>9}{'positions':>11}")
for nm, w in wins.items():
    for mode in ("new", "all"):
        z = run(w, mode)
        end = (f"DIED {datetime.utcfromtimestamp(tm[z['dead']]):%Y-%m}"
               if z["dead"] is not None else f"${z['eq']:,.2f}")
        print(f"{nm:<24}{mode:<7}{end:>12}{'$%.0f'%z['lo']:>10}"
              f"{'$%.0f'%z['mdd']:>9}{z['opened']:>11}")

print(f"\nbaseline for comparison: ${base['eq']:,.2f}")
print("\n*** 24 hours x 4 windows x 2 modes = many slices of one 278-day sample.")
print("*** Whichever looks best, expect a chunk of that to be luck.")
