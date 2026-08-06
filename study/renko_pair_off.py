"""Harvest, but a winner can retire a loser and free its slot.

USER'S RULE
  While any WINNING position plus any LOSING position sum to >= 0, close both.
  The freed slot counts against the cap again, so the basket can keep adding.

Greedy choice: the biggest winner retires the biggest loser it can cover. That
removes the most risk per pair. (Pairing the biggest winner with the SMALLEST
loser would make more pairs but leave the worst position sitting - reported as a
variant so the choice is not silently doing the work.)

Cycle still ends when the cycle's OWN total P&L (realised on this cycle's closes
plus floating) reaches zero, or when the cap is exceeded.

WHAT TO WATCH. Freeing slots means the cap can be dodged indefinitely, which is
close to running with no cap - and no cap killed the account in every test. So
the numbers that matter are max positions held, worst floating, and whether it
survives. Not the final equity.

M1, paired across brick anchors.
"""
import numpy as np
import MetaTrader5 as mt5

SPREAD = 10.0
BRICK, REV = 50.0, 2
TP, SL, CAP, PT, START = 250.0, 150.0, 4, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
mt5.shutdown()
days = (R["time"][-1] - R["time"][0]) / 86400
mon = days / 30.4
print(f"M1, {days:.0f} days ({mon:.1f} months)\n")


def run(a, pairing, biggest_loser=True, minwin=0.0):
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START; cyc = START; realised = 0.0
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None; incyc = False
    peak = START; mdd = 0.0; lo = START; eq = START
    maxpos = 0; pairs = 0; caps = 0; wf = 0.0
    cyc_pnl = []
    for j in range(N):
        if pending is not None:
            L = pending
            if len(ent) == 0:
                incyc = True; realised = 0.0
            ent = np.append(ent, o[j] + SPREAD if L else o[j])
            lng = np.append(lng, L); pending = None
            maxpos = max(maxpos, len(ent))
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
        # individual take profits
        if len(ent):
            hit = np.where(lng, h[j] >= ent + TP, l[j] <= ent - TP - SPREAD)
            if hit.any():
                realised += float(hit.sum()) * TP * PT
                bal += float(hit.sum()) * TP * PT
                ent, lng = ent[~hit], lng[~hit]
        # ---- PAIRING: a winner retires a loser it can cover -----------------
        if pairing and len(ent) >= 2:
            while True:
                p = np.where(lng, c[j] - ent, ent - c[j] - SPREAD) * PT
                wi = np.flatnonzero(p > 0); li = np.flatnonzero(p < 0)
                if len(wi) == 0 or len(li) == 0:
                    break
                wi = wi[p[wi] >= minwin]        # only spend a winner this big
                if len(wi) == 0:
                    break
                w = wi[np.argmax(p[wi])]                       # biggest winner
                cand = li[p[li] + p[w] >= 0]                   # losers it covers
                if len(cand) == 0:
                    break
                lz = cand[np.argmin(p[cand])] if biggest_loser else cand[np.argmax(p[cand])]
                realised += p[w] + p[lz]; bal += p[w] + p[lz]
                keep = np.ones(len(ent), dtype=bool); keep[[w, lz]] = False
                ent, lng = ent[keep], lng[keep]
                pairs += 1
                if len(ent) < 2:
                    break
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - SL, h[j] >= ent + SL + SPREAD).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j]-ent, ent-c[j]-SPREAD)) * PT) if len(ent) else 0.0
        wf = min(wf, flo)
        eq = bal + flo
        closed = None
        if rec and len(ent) and eq >= cyc:
            closed = "rec"
        elif len(ent) > CAP:
            closed = "cap"; caps += 1
        if closed:
            cyc_pnl.append(eq - cyc); incyc = False; bal = eq
            ent = np.empty(0); lng = np.empty(0, dtype=bool); eq = bal
        if len(ent) == 0:
            if incyc and closed is None:
                cyc_pnl.append(bal - cyc); incyc = False
            rec = False; cyc = bal
        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        if eq <= 0:
            return dict(eq=0.0, dead=True, maxpos=maxpos, pairs=pairs, caps=caps,
                        wf=wf, mdd=mdd, lo=0.0, n=len(cyc_pnl))
    return dict(eq=eq, dead=False, maxpos=maxpos, pairs=pairs, caps=caps,
                wf=wf, mdd=mdd, lo=lo, n=len(cyc_pnl))


ANCH = [0, 1, 3, 7, 15, 31, 60, 120]
ref = np.array([run(a, False)["eq"] for a in ANCH])
print(f"only pair when the winner is worth at least ...   (take profit is $2.50)")
print(f"{'min winner':<13}{'mean final':>12}{'vs no pairing':>15}{'2SE':>8}{'better':>8}"
      f"{'pairs/mo':>10}{'caps/mo':>9}{'drawdn':>9}")
print(f"{'no pairing':<13}{ref.mean():>12.2f}{0.0:>+15.2f}{0.0:>8.2f}{'-':>8}"
      f"{0:>10}{np.mean([run(a, False)['caps'] for a in ANCH])/mon:>9.1f}"
      f"{np.mean([run(a, False)['mdd'] for a in ANCH]):>9.2f}")
for mw in (0.0, 0.5, 1.0, 1.5, 2.0):
    out = [run(a, True, True, mw) for a in ANCH]
    eqs = np.array([x["eq"] for x in out]); dd = eqs - ref
    se = 2 * dd.std(ddof=1) / np.sqrt(len(dd))
    print(f"{'$%.2f'%mw:<13}{eqs.mean():>12.2f}{dd.mean():>+15.2f}{se:>8.2f}"
          f"{f'{int((dd>0).sum())}/8':>8}"
          f"{np.mean([x['pairs'] for x in out])/mon:>10.0f}"
          f"{np.mean([x['caps'] for x in out])/mon:>9.1f}"
          f"{np.mean([x['mdd'] for x in out]):>9.2f}")
