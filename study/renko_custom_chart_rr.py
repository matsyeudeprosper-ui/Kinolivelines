"""Same filtered-chart reversal, different reward-to-risk ratios.

Stop stays where it was: the low (or high) of the last candle before the turn.
Only the target moves.

Each ratio has its own break-even win rate: 1:1 needs >50%, 1:1.5 needs >40%,
1:2 needs >33.3%, before costs. The spread adds a little on top. Both the
required and the actual rate are printed so the gap is visible.

All three tie conventions again - though the wider the target, the less often a
single bar spans both barriers, so the conventions should converge.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD, PT, START = 10.0, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000)
mt5.shutdown()
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c)
days = (tm[-1] - tm[0]) / 86400

shown, sdir = [0], [0]
ref = 0
for i in range(1, N):
    if c[i] > h[ref]:
        shown.append(i); sdir.append(1); ref = i
    elif c[i] < l[ref]:
        shown.append(i); sdir.append(-1); ref = i

setups = []
for k in range(2, len(shown)):
    if sdir[k] == 0 or sdir[k-1] == 0 or sdir[k] == sdir[k-1]:
        continue
    bar, prev = shown[k], shown[k-1]
    if bar + 1 < N:
        setups.append({"bar": bar, "dir": sdir[k],
                       "stop": l[prev] if sdir[k] == 1 else h[prev]})
byBar = {}
for s in setups:
    byBar.setdefault(s["bar"], []).append(s)
print(f"M5 {days:.0f} days, {len(setups)} reversals ({len(setups)/(days/30.4):.0f}/month)\n")


def sim(sets, tie, rr):
    bal = START; peak = START; mdd = 0.0
    w = ls = 0; risks = []; pending = None; pos = None
    for j in range(N):
        if pending is not None:
            L, stop = pending
            e = o[j] + SPREAD if L else o[j]
            risk = (e - stop) if L else (stop - e)
            if risk > SPREAD:
                risks.append(risk)
                pos = (L, e, (e - risk) if L else (e + risk),
                       (e + risk*rr) if L else (e - risk*rr), risk)
            pending = None
        if pos is not None:
            L, e, sp, tgt, risk = pos
            hitS = (l[j] <= sp) if L else (h[j] >= sp + SPREAD)
            hitT = (h[j] >= tgt) if L else (l[j] <= tgt - SPREAD)
            done = False
            if hitS and hitT:
                if tie == "loss":   bal -= risk * PT; ls += 1; done = True
                elif tie == "win":  bal += risk*rr * PT; w += 1; done = True
                else:               done = True
            elif hitS:
                bal -= risk * PT; ls += 1; done = True
            elif hitT:
                bal += risk*rr * PT; w += 1; done = True
            if done:
                pos = None
        for s in sets.get(j, []):
            if pos is None and pending is None:
                pending = ((s["dir"] == 1), s["stop"])
        peak = max(peak, bal); mdd = max(mdd, peak - bal)
        if bal <= 0:
            return dict(eq=0.0, w=w, l=ls, mdd=mdd, dead=j, risk=np.mean(risks) if risks else 0)
    return dict(eq=bal, w=w, l=ls, mdd=mdd, dead=None, risk=np.mean(risks) if risks else 0)


print(f"{'RR':<7}{'tie':<8}{'final':>12}{'trades':>8}{'win rate':>11}"
      f"{'need':>9}{'gap':>9}{'drawdown':>11}")
best = {}
for rr in (1.0, 1.5, 2.0, 2.5, 3.0):
    for tie in ("loss", "split", "win"):
        z = sim(byBar, tie, rr)
        n = z["w"] + z["l"]
        wr = 100 * z["w"] / max(1, n)
        need = 100 * (1/(1+rr)) + 100 * SPREAD / ((1+rr) * max(1, z["risk"]))
        end = (f"DIED {datetime.utcfromtimestamp(tm[z['dead']]):%Y-%m}"
               if z["dead"] is not None else f"${z['eq']:,.2f}")
        print(f"{('1:'+str(rr)):<7}{tie:<8}{end:>12}{n:>8}{wr:>10.1f}%"
              f"{need:>8.1f}%{wr-need:>+8.1f}{'$%.0f'%z['mdd']:>11}")
        if tie == "split":
            best[rr] = z
    print()

# random control on the best ratio by final equity
top = max(best, key=lambda k: best[k]["eq"])
print(f"random control on the best ratio, 1:{top} (tie->split)")
rate = len(setups) / N
dists = np.abs(np.array([c[s["bar"]] - s["stop"] for s in setups]))
rng = np.random.default_rng(20260805)
outs = []
for t in range(30):
    idx = np.flatnonzero(rng.random(N) < rate)
    fake = {}
    for i in idx:
        if i + 1 >= N: continue
        L = rng.random() < 0.5
        dd = float(rng.choice(dists))
        fake.setdefault(int(i), []).append({"dir": 1 if L else -1,
                                            "stop": c[i]-dd if L else c[i]+dd})
    z = sim(fake, "split", top)
    outs.append(0.0 if z["dead"] is not None else z["eq"])
outs = np.array(outs)
b = best[top]
print(f"  real ${b['eq']:,.2f}   random median ${np.median(outs):,.2f}   "
      f"best ${outs.max():,.2f}   died {int((outs==0).sum())}/30")
print(f"  random beat it {int((outs >= b['eq']).sum())}/30  ->  "
      f"{100*(outs < b['eq']).mean():.0f}th percentile")
