"""Take profit in DOLLARS. $4.00 = 400 points at 0.01 lots (now: $2.50 = 250).

Recovery trigger stays 150 points, cap stays 4. Only the target moves.

A bigger target means each win is worth more but arrives less often, and
positions sit open longer - which makes baskets last longer and should push more
cycles into the cap. Both effects are reported.

Paired across brick anchors, M1, the timeframe the live bot runs on.
"""
import numpy as np
import MetaTrader5 as mt5

SPREAD = 10.0
BRICK, REV = 50.0, 2
SL, CAP, PT, START = 150.0, 4, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
mt5.shutdown()
days = (R["time"][-1] - R["time"][0]) / 86400
mon = days / 30.4
print(f"M1, {days:.0f} days ({mon:.1f} months)\n")


def run(a, tp):
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None; incyc = False
    peak = START; mdd = 0.0; lo = START; eq = START
    by = {"tp": [], "rec": [], "cap": []}
    for j in range(N):
        if pending is not None:
            L = pending
            if len(ent) == 0: incyc = True
            ent = np.append(ent, o[j] + SPREAD if L else o[j])
            lng = np.append(lng, L); pending = None
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
                if ((len(ent) == 0) or (rec and len(ent) <= CAP)) and j + 1 < N:
                    pending = (d == 1)
            pd_ = d
        if len(ent):
            hit = np.where(lng, h[j] >= ent + tp, l[j] <= ent - tp - SPREAD)
            if hit.any():
                bal += float(hit.sum()) * tp * PT
                ent, lng = ent[~hit], lng[~hit]
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - SL, h[j] >= ent + SL + SPREAD).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j]-ent, ent-c[j]-SPREAD)) * PT) if len(ent) else 0.0
        eq = bal + flo
        closed = None
        if rec and len(ent) and eq >= cyc:
            closed = "rec"
        elif len(ent) > CAP:
            closed = "cap"
        if closed:
            by[closed].append(eq - cyc); incyc = False; bal = eq
            ent = np.empty(0); lng = np.empty(0, dtype=bool); eq = bal
        if len(ent) == 0:
            if incyc and closed is None:
                by["tp"].append(bal - cyc); incyc = False
            rec = False; cyc = bal
        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        if eq <= 0:
            return dict(eq=0.0, mdd=mdd, lo=0.0, by=by, dead=True)
    return dict(eq=eq, mdd=mdd, lo=lo, by=by, dead=False)


ANCH = [0, 1, 3, 7, 15, 31, 60, 120]
ref = np.array([run(a, 250.0)["eq"] for a in ANCH])
print(f"{'target':<10}{'pts':>6}{'mean final':>12}{'vs $2.50':>10}{'2SE':>8}"
      f"{'better':>8}{'wins/mo':>9}{'caps/mo':>9}{'avg cap':>9}{'drawdn':>9}")
for dollars in (1.5, 2.5, 3.0, 4.0, 5.0, 6.0):
    tp = dollars * 100.0
    out = [run(a, tp) for a in ANCH]
    got = np.array([x["eq"] for x in out])
    dd = got - ref
    se = 2 * dd.std(ddof=1) / np.sqrt(len(dd)) if dollars != 2.5 else 0.0
    nw = np.mean([len(x["by"]["tp"]) for x in out])
    nc = np.mean([len(x["by"]["cap"]) for x in out])
    ac_ = np.mean([np.mean(x["by"]["cap"]) if x["by"]["cap"] else 0 for x in out])
    md = np.mean([x["mdd"] for x in out])
    tag = f"${dollars:.2f}" + ("  <-now" if dollars == 2.5 else "")
    print(f"{tag:<10}{tp:>6.0f}{got.mean():>12.2f}{dd.mean():>+10.2f}{se:>8.2f}"
          f"{f'{int((dd>0).sum())}/8':>8}{nw/mon:>9.0f}{nc/mon:>9.0f}{ac_:>9.2f}{md:>9.2f}")
