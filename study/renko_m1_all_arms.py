"""Every recovery variant, M1 only, ONE run, paired across anchors.

Earlier numbers came from separate scripts that loaded the data minutes apart and
some used a single anchor. With a one-bar shift worth up to $240 that makes them
uncomparable. This runs every arm on the same bars, at the same anchors, so the
column can be read straight down.

ARMS
  any               current bot: add on every reversal in recovery
  same              live now: only adds in the first trade's direction
  hedge SL 1.0x     ONE opposite trade, target 1.5x the drawdown, stop 1.0x;
                    if it stops, close everything and reset
  hedge SL 1.5x     same but a wider stop
  hedge no SL       one opposite trade, target only, nothing forces the exit
  many hedges       opposite-direction adds with no per-hedge stop, cap 4
"""
import numpy as np
import MetaTrader5 as mt5

SPREAD = 10.0
BRICK, REV = 50.0, 2
TP, SLTRIG, CAP, PT, START = 250.0, 150.0, 4, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
mt5.shutdown()
MON = (R["time"][-1] - R["time"][0]) / 86400 / 30.4
print(f"BTCUSDm M1, {len(R)} bars, {MON:.1f} months, spread {SPREAD:g}, brick {BRICK:g}\n")


def run(a, arm):
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    tpp = np.empty(0); slv = np.empty(0)
    rec = False; pending = None; cyc_dir = None
    f_ent = None; f_long = None; hedged_this = 0
    peak = START; mdd = 0.0; lo = START; eq = START
    caps = 0; stops = 0; adds = 0
    one_hedge = arm.startswith("hedge")
    for j in range(N):
        if pending is not None:
            L, ptp, psl = pending
            px = o[j] + SPREAD if L else o[j]
            if len(ent) == 0:
                cyc_dir = L; f_ent = px; f_long = L; hedged_this = 0
            else:
                adds += 1
                if one_hedge:
                    hedged_this += 1
            ent = np.append(ent, px); lng = np.append(lng, L)
            tpp = np.append(tpp, ptp); slv = np.append(slv, psl)
            pending = None
        ci = c[j]
        while True:
            u = (ao if d == -1 else ac) + BRICK * (REV if d == -1 else 1)
            n_ = (ao if d == 1 else ac) - BRICK * (REV if d == 1 else 1)
            if ci >= u:
                base = ao if d == -1 else ac; ao, ac, d = base, base + BRICK, 1
            elif ci <= n_:
                base = ao if d == 1 else ac; ao, ac, d = base, base - BRICK, -1
            else:
                break
            if pd_ and d != pd_ and pending is None and j + 1 < N:
                want = (d == 1)
                if len(ent) == 0:
                    pending = (want, TP, 0.0)
                elif rec:
                    if arm == "any" and len(ent) <= CAP:
                        pending = (want, TP, 0.0)
                    elif arm == "same" and len(ent) <= CAP and want == cyc_dir:
                        pending = (want, TP, 0.0)
                    elif arm == "many" and len(ent) <= CAP and want != cyc_dir:
                        pending = (want, TP, 0.0)
                    elif one_hedge and hedged_this == 0 and want != cyc_dir:
                        dn = max(((f_ent - c[j]) if f_long else (c[j] - f_ent)), BRICK)
                        m = {"hedge10": 1.0, "hedge15": 1.5, "hedge00": 0.0}[arm]
                        pending = (want, 1.5 * dn, m * dn)
            pd_ = d
        if len(ent):
            hitT = np.where(lng, h[j] >= ent + tpp, l[j] <= ent - tpp - SPREAD)
            if hitT.any():
                bal += float(np.sum(tpp[hitT])) * PT
                ent, lng, tpp, slv = ent[~hitT], lng[~hitT], tpp[~hitT], slv[~hitT]
        if len(ent):
            has = slv > 0
            hitS = has & np.where(lng, l[j] <= ent - slv, h[j] >= ent + slv + SPREAD)
            if hitS.any():
                # the hedge stopped -> book it AND close everything, reset
                bal -= float(np.sum(slv[hitS])) * PT
                keep = ~hitS
                rest = np.where(lng[keep], c[j] - ent[keep], ent[keep] - c[j] - SPREAD)
                bal += float(np.sum(rest)) * PT
                stops += 1
                ent = np.empty(0); lng = np.empty(0, dtype=bool)
                tpp = np.empty(0); slv = np.empty(0)
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - SLTRIG, h[j] >= ent + SLTRIG + SPREAD).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j]-ent, ent-c[j]-SPREAD)) * PT) if len(ent) else 0.0
        eq = bal + flo
        closed = None
        if rec and len(ent) and eq >= cyc:
            closed = 1
        elif len(ent) > CAP:
            closed = 1; caps += 1
        if closed:
            bal = eq
            ent = np.empty(0); lng = np.empty(0, dtype=bool)
            tpp = np.empty(0); slv = np.empty(0); eq = bal
        if len(ent) == 0:
            rec = False; cyc = bal; cyc_dir = None; f_ent = None; hedged_this = 0
        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        if eq <= 0:
            return dict(eq=0.0, dead=True, mdd=mdd, lo=0.0, caps=caps, stops=stops, adds=adds)
    return dict(eq=eq, dead=False, mdd=mdd, lo=lo, caps=caps, stops=stops, adds=adds)


ANCH = [0, 1, 3, 7, 15, 31, 60, 120]
ref = np.array([run(a, "any")["eq"] for a in ANCH])
print(f"{'arm':<28}{'mean final':>12}{'vs current':>12}{'2SE':>8}{'better':>8}"
      f"{'worst dd':>10}{'adds/mo':>9}{'caps/mo':>9}")
for arm, nm in (("any", "any direction (current)"),
                ("same", "same direction (live now)"),
                ("hedge10", "1 hedge, stop 1.0x"),
                ("hedge15", "1 hedge, stop 1.5x"),
                ("hedge00", "1 hedge, no stop"),
                ("many", "many hedges, no stop")):
    out = [run(a, arm) for a in ANCH]
    eqs = np.array([x["eq"] for x in out]); dd = eqs - ref
    se = 2 * dd.std(ddof=1) / np.sqrt(len(dd)) if arm != "any" else 0.0
    print(f"{nm:<28}{eqs.mean():>12.2f}{dd.mean():>+12.2f}{se:>8.2f}"
          f"{(f'{int((dd>0).sum())}/8' if arm != 'any' else '-'):>8}"
          f"{np.mean([x['mdd'] for x in out]):>10.2f}"
          f"{np.mean([x['adds'] for x in out])/MON:>9.0f}"
          f"{np.mean([x['caps'] for x in out])/MON:>9.1f}")
print(f"\n  anchor noise floor on this data is about $237 - anything smaller is nothing.")
