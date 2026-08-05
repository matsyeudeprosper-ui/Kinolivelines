"""Re-run BOTH Renko designs on the same bars and settle the monthly numbers.

Written 2026-08-05 because two of my own records disagreed: the bot docstring
says "83% of months profitable, median +$9", my project notes say "74%, median
+$33". Same claimed run. At least one is wrong, so nothing here is copied from
either - every number below comes out of this file.

Also measures something I do not think the original run measured: reversal
signals that arrived while a basket was open and therefore could NOT be taken.
That is the live cost we actually observed - holding losers means missing
winners.

NOTE ON THE BRICK. This uses a PRICE-SCALED brick (50/64000 of price), which is
what the original backtest used so the results are comparable. The LIVE bots use
a FIXED 50 points. That mismatch is exactly what brick_watch.py exists to warn
about; it is not corrected here, because the point of this run is to reproduce
and check the recorded figures, not to change the experiment.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import defaultdict

PCT   = 50.0 / 64000.0        # brick as a share of price
SPCT  = 10.0 / 64000.0        # spread as a share of price
REV   = 2
TPB, SLB = 5, 3
MAXB  = 4                     # cap: a 5th open forces the basket shut
PT    = 0.01                  # $ per point at 0.01 lots
START = 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
# 80000 returns everything there is (45,217 bars); 100000 returns None. An
# oversized request does not truncate, it fails silently - trap 3 in RESTORE.md.
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
if r is None:
    raise SystemExit("no bars")
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]
N = len(c)
span = (tm[-1] - tm[0]) / 86400 / 365
print(f"bars {N}  {datetime.utcfromtimestamp(tm[0]):%Y-%m-%d} -> "
      f"{datetime.utcfromtimestamp(tm[-1]):%Y-%m-%d}  ({span:.1f} years)")
months = np.array([datetime.utcfromtimestamp(t).strftime("%Y-%m") for t in tm])


def signals():
    """Reversal bricks. Identical construction to the live bots."""
    revs = {}
    ao = ac = float(o[0]); d = 0; pd_ = 0
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                base = ao if d == -1 else ac; ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                base = ao if d == 1 else ac; ao, ac, d = base, base - B, -1
            else:
                break
            if pd_ and d != pd_:
                revs.setdefault(i, d)
            pd_ = d
    return revs


REVS = signals()
print(f"reversal signals over the whole history: {len(REVS)}")


def month_stats(eq_by_month, start):
    """Month-end equity -> the distribution people actually care about."""
    keys = sorted(eq_by_month)
    prev = start; deltas = []
    for k in keys:
        deltas.append(eq_by_month[k] - prev)
        prev = eq_by_month[k]
    d = np.array(deltas)
    return dict(n=len(d), pos=float((d > 0).mean() * 100), med=float(np.median(d)),
                best=float(d.max()), worst=float(d.min()), mean=float(d.mean()))


def run_plain():
    """5 brick TP, 3 brick SL, one position at a time. The measuring stick.

    A signal on bar j is filled at the OPEN of bar j+1, and its barriers are
    tested from bar j+1 onward. Testing them on bar j - the signal bar, which
    closed before the trade existed - is what produced a 0.5% win rate on the
    first attempt at this file: the previous bar's range stopped nearly every
    trade out on entry."""
    bal = START; peak = START; mdd = 0.0; mddp = 0.0
    wins = losses = 0
    ent = None; lng = False; tp = sl = 0.0
    pending = None
    eqm = {}
    for j in range(N):
        if pending is not None:                  # fill at THIS bar's open
            lng, tp, sl = pending
            ent = o[j] + (c[j] * SPCT) if lng else o[j]
            pending = None
        if ent is not None:
            # tie convention: a bar spanning both barriers counts as the LOSS
            SP = c[j] * SPCT
            hit_sl = (l[j] <= ent - sl) if lng else (h[j] >= ent + sl + SP)
            hit_tp = (h[j] >= ent + tp) if lng else (l[j] <= ent - tp - SP)
            if hit_sl:
                bal -= sl * PT; losses += 1; ent = None
            elif hit_tp:
                bal += tp * PT; wins += 1; ent = None
        if ent is None and pending is None and j in REVS and j + 1 < N:
            B = c[j] * PCT
            pending = ((REVS[j] == 1), B * TPB, B * SLB)
        peak = max(peak, bal); mdd = max(mdd, peak - bal)
        mddp = max(mddp, (peak - bal) / peak * 100)
        eqm[months[j]] = bal
        if bal <= 0:
            return dict(dead=j, eq=0.0, wins=wins, losses=losses, mdd=mdd,
                        mddp=mddp, eqm=eqm)
    return dict(dead=None, eq=bal, wins=wins, losses=losses, mdd=mdd,
                mddp=mddp, eqm=eqm)


def run_recovery(cap=MAXB):
    """The live design. Exit when THIS cycle's own P&L returns to zero, which in
    a one-strategy simulation is bal-back-to-cycle-start - the same thing. The
    live bot got this wrong by reading account equity; the sim never could."""
    bal = START; cycle_start = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool); tpp = np.empty(0); slv = np.empty(0)
    recovery = False
    peak = START; mdd = 0.0; mddp = 0.0; lo = START; eq = START
    wins = 0; recoveries = 0; recovered = 0; forced = 0
    maxbask = 0; skipped = 0; basket_bars = 0
    pending = None
    eqm = {}
    for j in range(N):
        B = c[j] * PCT; SP = c[j] * SPCT
        # fill last bar's signal at THIS bar's open, before any barrier test
        if pending is not None:
            L, ptp, psl = pending
            ent = np.append(ent, o[j] + SP if L else o[j])
            lng = np.append(lng, L)
            tpp = np.append(tpp, ptp); slv = np.append(slv, psl)
            maxbask = max(maxbask, len(ent))
            pending = None

        if j in REVS and j + 1 < N:
            if len(ent) == 0 or (recovery and len(ent) <= cap):
                pending = ((REVS[j] == 1), B * TPB, B * SLB)
            else:
                skipped += 1          # a signal we could not act on

        if len(ent):
            basket_bars += 1
            hit = np.where(lng, h[j] >= ent + tpp, l[j] <= ent - tpp - SP)
            if hit.any():
                bal += float(np.sum(tpp[hit])) * PT
                wins += int(hit.sum())
                ent, lng, tpp, slv = ent[~hit], lng[~hit], tpp[~hit], slv[~hit]

        if len(ent) and not recovery:
            touched = np.where(lng, l[j] <= ent - slv, h[j] >= ent + slv + SP)
            if touched.any():
                recovery = True; recoveries += 1

        flo = float(np.sum(np.where(lng, c[j] - ent, ent - c[j] - SP)) * PT) if len(ent) else 0.0
        eq = bal + flo

        if recovery and len(ent) and eq >= cycle_start:
            bal = eq; recovered += 1
            ent = np.empty(0); lng = np.empty(0, dtype=bool)
            tpp = np.empty(0); slv = np.empty(0)
            flo = 0.0; eq = bal; recovery = False
        elif len(ent) > cap:
            bal = eq; forced += 1
            ent = np.empty(0); lng = np.empty(0, dtype=bool)
            tpp = np.empty(0); slv = np.empty(0)
            flo = 0.0; eq = bal; recovery = False

        if not recovery and len(ent) == 0:
            cycle_start = bal

        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        mddp = max(mddp, (peak - eq) / peak * 100)
        eqm[months[j]] = eq
        if eq <= 0:
            return dict(dead=j, eq=0.0, wins=wins, recoveries=recoveries,
                        recovered=recovered, forced=forced, mdd=mdd, mddp=mddp,
                        lo=0.0, maxbask=maxbask, skipped=skipped, eqm=eqm,
                        basket_pct=100.0 * basket_bars / (j + 1))
    return dict(dead=None, eq=eq, wins=wins, recoveries=recoveries,
                recovered=recovered, forced=forced, mdd=mdd, mddp=mddp, lo=lo,
                maxbask=maxbask, skipped=skipped, eqm=eqm,
                basket_pct=100.0 * basket_bars / N)


print("\n" + "=" * 66)
print("A. PLAIN 5:3 WITH A STOP, one at a time")
print("=" * 66)
p = run_plain()
if p["dead"] is not None:
    print(f"  DIED {datetime.utcfromtimestamp(tm[p['dead']]):%Y-%m-%d} after "
          f"{(tm[p['dead']]-tm[0])/86400/365:.1f} years")
else:
    print(f"  survived. final ${p['eq']:,.2f}")
print(f"  wins {p['wins']}  losses {p['losses']}  "
      f"win rate {100*p['wins']/max(1,p['wins']+p['losses']):.1f}%")
print(f"  worst drawdown ${p['mdd']:,.2f}  ({p['mddp']:.1f}% of equity at the peak)")
ms = month_stats(p["eqm"], START)
print(f"  months {ms['n']}  positive {ms['pos']:.0f}%  median {ms['med']:+.2f}  "
      f"best {ms['best']:+.2f}  worst {ms['worst']:+.2f}")

print("\n" + "=" * 66)
print(f"B. CAPPED RECOVERY (cap {MAXB})")
print("=" * 66)
q = run_recovery()
if q["dead"] is not None:
    print(f"  DIED {datetime.utcfromtimestamp(tm[q['dead']]):%Y-%m-%d} after "
          f"{(tm[q['dead']]-tm[0])/86400/365:.1f} years")
else:
    print(f"  survived. final ${q['eq']:,.2f}  ({100*(q['eq']/START-1):+.0f}%)")
print(f"  TP wins {q['wins']}  recoveries entered {q['recoveries']}  "
      f"completed {q['recovered']}  force-closed at cap {q['forced']}")
print(f"  biggest basket {q['maxbask']}  worst drawdown ${q['mdd']:,.2f}")
print(f"    = {100*q['mdd']/START:.1f}% of the STARTING $1,000, "
      f"{q['mddp']:.1f}% of equity at the peak it fell from")
print(f"  lowest equity ever ${q['lo']:,.2f}")
print(f"  SIGNALS SKIPPED while holding a basket: {q['skipped']} "
      f"of {len(REVS)} ({100*q['skipped']/len(REVS):.1f}%)")
print(f"  time holding a basket: {q['basket_pct']:.1f}% of all bars")
ms = month_stats(q["eqm"], START)
print(f"  months {ms['n']}  positive {ms['pos']:.0f}%  median {ms['med']:+.2f}  "
      f"best {ms['best']:+.2f}  worst {ms['worst']:+.2f}  mean {ms['mean']:+.2f}")

print("\n" + "=" * 66)
print("C. CAP SENSITIVITY - is 4 a tuned cell or a plateau?")
print("=" * 66)
for cap in (2, 3, 4, 6, 8, 12):
    z = run_recovery(cap)
    tag = f"DIED {(tm[z['dead']]-tm[0])/86400/365:.1f}y" if z["dead"] is not None else f"${z['eq']:>9,.0f}"
    m = month_stats(z["eqm"], START)
    print(f"  cap {cap:>2}  {tag}  dd ${z['mdd']:>7,.0f} ({z['mddp']:>4.1f}%)  "
          f"months+ {m['pos']:>4.0f}%  median {m['med']:>+7.2f}  forced {z['forced']:>4}")
