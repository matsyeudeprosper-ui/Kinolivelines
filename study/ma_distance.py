"""Distance from a moving average - the last untested OHLC feature.

Every other condition on the list has been measured and come back null. This one
was never tried as a CONTINUOUS variable; earlier work only asked "is price above
or below the EMA", which throws away the magnitude that matters.

Two readings, because distance from a mean has a natural directional story:
  LOCATION   does being far from the MA change the odds at all? Entered long AND
             short, so no direction is supplied.
  REVERSION  trade back TOWARD the MA - the classic "stretched, snaps back" idea.
             Its mirror (trade AWAY from the MA, i.e. continuation) is the control.

Three MA lengths on H1 - 20, 50 and 200 hours - so a result that only appears at
one length is visible as the parameter-fitting it would be.

Discipline as established: non-overlapping windows, live spread, tie rate reported
under three conventions, every symbol against its own control, and a finding must
hold on several symbols with a consistent sign.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYMBOLS = ["BTCUSDm", "JP225m", "XAUUSDm", "US30m", "DE30m", "USTECm"]
STOP_M, TMULT, HOLD = 1.0, 1.5, 8
MAS = (20, 50, 200)
EDGES = [-99, -2.0, -1.0, -0.35, 0.35, 1.0, 2.0, 99]
NAMES = ["< -2", "-2..-1", "-1..-0.35", "near MA", "0.35..1", "1..2", "> 2"]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def build(sym):
    mt5.symbol_select(sym, True)
    tick = mt5.symbol_info_tick(sym)
    if tick is None or tick.ask <= 0:
        return None
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 20000)
    if r is None or len(r) < 5000:
        return None
    spread = tick.ask - tick.bid
    d = pd.DataFrame(r)
    pc = d["close"].shift(1)
    d["atr"] = pd.concat([d.high - d.low, (d.high - pc).abs(),
                          (d.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
    for m in MAS:
        d["ma%d" % m] = d["close"].rolling(m).mean()
    d = d.dropna().reset_index(drop=True)

    hi, lo, cl, atr = (d.high.to_numpy(float), d.low.to_numpy(float),
                       d.close.to_numpy(float), d.atr.to_numpy(float))
    dist = {m: ((cl - d["ma%d" % m].to_numpy(float)) / atr) for m in MAS}
    n = len(cl)
    WIN, LOSS = STOP_M * TMULT, -STOP_M

    recs = []
    for i in range(50, n - HOLD, HOLD):                 # NON-OVERLAPPING
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        sd, td = STOP_M * A, STOP_M * A * TMULT
        w = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[w]); rmin = np.minimum.accumulate(lo[w])
        mid, endp = cl[i], cl[i + HOLD]
        rec = {"d": {m: dist[m][i] for m in MAS}}
        for sgn, tag in ((1, "L"), (-1, "S")):
            e = mid + sgn * spread / 2
            tp, s_ = e + sgn * td, e - sgn * sd
            if sgn > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                hs = np.argmax(rmin <= s_) if rmin[-1] <= s_ else 10 ** 6
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                hs = np.argmax(rmax >= s_) if rmax[-1] >= s_ else 10 ** 6
            if ht == 10 ** 6 and hs == 10 ** 6:
                v = sgn * (endp - e) / A; rec[tag] = (v, v, v)
            elif ht == hs:
                rec[tag] = ((WIN + LOSS) / 2, LOSS, WIN)
            elif hs < ht:
                rec[tag] = (LOSS, LOSS, LOSS)
            else:
                rec[tag] = (WIN, WIN, WIN)
        recs.append(rec)
    return recs


def agg(recs, keep, direction=None):
    v = [[], [], []]
    for r in recs:
        if not keep(r):
            continue
        if direction is None:
            for t in ("L", "S"):
                for k in range(3): v[k].append(r[t][k])
        else:
            dd = direction(r)
            if dd == 0: continue
            t = "L" if dd > 0 else "S"
            for k in range(3): v[k].append(r[t][k])
    if len(v[0]) < 120:
        return None
    a = np.array(v[0])
    return a.mean(), float(np.mean(v[1])), float(np.mean(v[2])), len(a), a.std() / math.sqrt(len(a))


print("DISTANCE FROM MOVING AVERAGE - continuous, in ATR units")
print("non-overlapping 8h windows, stop 1.0x ATR(H1), target 1.5x, live spread\n")

loc_tally = {nm: [] for nm in NAMES}
rev_tally, cont_tally = [], []

for sym in SYMBOLS:
    recs = build(sym)
    if not recs:
        print("%-9s no data" % sym); continue
    rnd = agg(recs, lambda r: True)
    print("%-9s %s windows | random %+.4f" % (sym, f"{len(recs):,}", rnd[0]))
    for m in MAS:
        row = "   MA%-4d" % m
        for k, nm in enumerate(NAMES):
            lo_e, hi_e = EDGES[k], EDGES[k + 1]
            c = agg(recs, lambda r, a=lo_e, b=hi_e, mm=m: a <= r["d"][mm] < b)
            if c is None:
                row += " %-9s" % "-"; continue
            diff = c[0] - rnd[0]
            if m == 50:
                loc_tally[nm].append(diff)
            row += " %+8.4f" % diff
        print(row)
    # reversion: trade back toward the MA when stretched beyond 1 ATR
    rev = agg(recs, lambda r: abs(r["d"][50]) >= 1.0, lambda r: -np.sign(r["d"][50]))
    con = agg(recs, lambda r: abs(r["d"][50]) >= 1.0, lambda r: np.sign(r["d"][50]))
    if rev and con:
        rev_tally.append(rev[0] - rnd[0]); cont_tally.append(con[0] - rnd[0])
        two = 2 * math.sqrt(rev[4] ** 2 + rnd[4] ** 2)
        signs_ok = (rev[1] - rnd[1] > 0) == (rev[2] - rnd[2] > 0) == (rev[0] - rnd[0] > 0)
        tag = "REAL" if abs(rev[0] - rnd[0]) > two and signs_ok else ""
        print("   stretched >1 ATR from MA50: revert %+.4f | continue %+.4f  (2SE %.4f) %s"
              % (rev[0] - rnd[0], con[0] - rnd[0], two, tag))
    print()
mt5.shutdown()

print("=" * 78)
print("BUCKET AVERAGES ACROSS SYMBOLS (MA50) - difference from random\n")
print("%-12s %10s %9s  %s" % ("bucket", "mean", "symbols", "same sign on"))
print("-" * 60)
for nm in NAMES:
    v = loc_tally[nm]
    if not v: continue
    m = float(np.mean(v))
    agree = sum(1 for x in v if (x > 0) == (m > 0))
    print("%-12s %10.4f %9d  %d of %d" % (nm, m, len(v), agree, len(v)))
print("-" * 60)
if rev_tally:
    mr, mc = float(np.mean(rev_tally)), float(np.mean(cont_tally))
    ar = sum(1 for x in rev_tally if (x > 0) == (mr > 0))
    print("\nmean-reversion when stretched: %+.4f  (%d of %d symbols agree)" % (mr, ar, len(rev_tally)))
    print("continuation when stretched:   %+.4f" % mc)
print("""
A real effect shows the same sign on most symbols AND a monotonic pattern across
buckets - being further from the mean should matter more, not randomly. Scattered
signs across buckets is noise no matter how large any single number looks.""")
