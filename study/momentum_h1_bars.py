"""Settle the JP225 momentum question using 7.6 years instead of 173 days.

The result was "consistent +0.031 to +0.042 across every sampling density, but
0.5 standard errors from zero". That looked like a data problem needing months of
waiting. It was not - it was a resolution mistake.

The barriers are hourly-sized and the hold is 8 hours, so 5-minute bars buy almost
nothing. But M5 only reaches back 173 days while H1 reaches 7.6 YEARS:

    M5   50,000 bars = 173 days  ->    211 independent 8h windows
    H1   45,103 bars = 7.6 years -> ~5,600 independent 8h windows

Twenty-six times the independent evidence, from data already on disk.

THE COST, and it is trap #1: with a 1.0x ATR(H1) stop and a 1.5x target, a single
H1 bar can span the stop, and occasionally both barriers. So the tie rate is
measured and every result is reported under all three tie conventions. A finding
only counts if its SIGN is the same in all three - that discipline is what caught
the fake break-reversal effect earlier.

Windows are NON-OVERLAPPING (step = hold). Trap #5: overlapping windows shrink the
error bar without adding information, and turned a negative gold result positive.

Momentum is defined on the same idea as before - price moved at least 0.35x
ATR(H1) over the previous 6 hours - with the FADE arm as the built-in control.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYMBOLS = ["JP225m", "BTCUSDm", "XAUUSDm", "US30m", "DE30m", "USTECm"]
STOP_M, TMULT, HOLD, LOOK = 1.0, 1.5, 8, 6      # hold 8 H1 bars = 8h; look back 6h

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def series(sym):
    mt5.symbol_select(sym, True)
    tick = mt5.symbol_info_tick(sym)
    if tick is None or tick.ask <= 0:
        return None
    for k in (45000, 20000, 10000):
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, k)
        if r is not None and len(r) > 5000:
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s")
            pc = d["close"].shift(1)
            d["atr"] = pd.concat([d.high - d.low, (d.high - pc).abs(),
                                  (d.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
            return d.dropna(subset=["atr"]).reset_index(drop=True), tick.ask - tick.bid
    return None


def measure(d, spread):
    hi, lo, cl = d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float)
    atr = d.atr.to_numpy(float)
    n = len(cl)
    mv = np.full(n, np.nan)
    mv[LOOK:] = cl[LOOK:] - cl[:-LOOK]

    WIN, LOSS = STOP_M * TMULT, -STOP_M
    rows = []
    for i in range(50, n - HOLD, HOLD):              # NON-OVERLAPPING
        A = atr[i]
        if not np.isfinite(A) or A <= 0 or not np.isfinite(mv[i]):
            continue
        sd, td = STOP_M * A, STOP_M * A * TMULT
        w = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[w]); rmin = np.minimum.accumulate(lo[w])
        mid, endp = cl[i], cl[i + HOLD]
        rec = {"mom": abs(mv[i]) >= 0.35 * A, "dir": np.sign(mv[i])}
        for sgn, tag in ((1, "L"), (-1, "S")):
            e = mid + sgn * spread / 2
            tp, sl = e + sgn * td, e - sgn * sd
            if sgn > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                hs = np.argmax(rmin <= sl) if rmin[-1] <= sl else 10 ** 6
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                hs = np.argmax(rmax >= sl) if rmax[-1] >= sl else 10 ** 6
            if ht == 10 ** 6 and hs == 10 ** 6:
                v = sgn * (endp - e) / A
                rec[tag] = (v, v, v, False)
            elif ht == hs:                                    # ambiguous bar
                rec[tag] = ((WIN + LOSS) / 2, LOSS, WIN, True)
            elif hs < ht:
                rec[tag] = (LOSS, LOSS, LOSS, False)
            else:
                rec[tag] = (WIN, WIN, WIN, False)
        rows.append(rec)
    return rows


def agg(rows, sel, pick_dir=None):
    """Returns (mean_split, mean_loss, mean_win, n, tie%) or None."""
    out = [[], [], []]
    ties = 0
    for r in rows:
        if not sel(r):
            continue
        tag = "L" if (pick_dir(r) > 0 if pick_dir else True) else "S"
        if pick_dir is None:
            for t in ("L", "S"):
                for k in range(3):
                    out[k].append(r[t][k])
                ties += 1 if r[t][3] else 0
        else:
            for k in range(3):
                out[k].append(r[tag][k])
            ties += 1 if r[tag][3] else 0
    if len(out[0]) < 150:
        return None
    a = [np.array(x) for x in out]
    return (a[0].mean(), a[1].mean(), a[2].mean(),
            len(a[0]), ties / len(a[0]) * 100,
            a[0].std() / math.sqrt(len(a[0])))


print("MOMENTUM AT H1 SCALE, measured ON H1 BARS - non-overlapping 8h windows")
print("stop 1.0x ATR(H1), target 1.5x, real spread, 7.6 years of history\n")
print("%-9s %-9s %8s %6s %10s %10s %10s %9s  %s"
      % ("symbol", "arm", "windows", "tie%", "TIE-SPLIT", "TIE-LOSS", "TIE-WIN", "+/-SE", "verdict"))
print("-" * 96)

summary = {}
for s in SYMBOLS:
    got = series(s)
    if got is None:
        print("%-9s no data" % s); continue
    d, spread = got
    rows = measure(d, spread)
    yrs = (d.time.max() - d.time.min()).days / 365
    rnd = agg(rows, lambda r: True)
    if rnd is None:
        print("%-9s too few windows" % s); continue
    print("%-9s %-9s %8s %5.1f%% %10.4f %10.4f %10.4f %9.4f   (%.1f yrs)"
          % (s, "RANDOM", f"{rnd[3]:,}", rnd[4], rnd[0], rnd[1], rnd[2], rnd[5], yrs))
    fol = agg(rows, lambda r: r["mom"], lambda r: r["dir"])
    fad = agg(rows, lambda r: r["mom"], lambda r: -r["dir"])
    if fol is None:
        print("%-9s %-9s too few" % ("", "follow")); continue
    diffs = [fol[k] - rnd[k] for k in range(3)]
    two = 2 * math.sqrt(fol[5] ** 2 + rnd[5] ** 2)
    same = all(x > 0 for x in diffs) or all(x < 0 for x in diffs)
    sig = all(abs(x) > two for x in diffs)
    v = ("REAL " + ("better" if diffs[0] > 0 else "worse")) if (same and sig) else \
        ("leaning " + ("better" if diffs[0] > 0 else "worse")) if same else "SIGN FLIPS"
    summary[s] = (diffs[0], two, same and sig)
    print("%-9s %-9s %8s %5.1f%% %10.4f %10.4f %10.4f %9.4f   %s"
          % ("", "FOLLOW", f"{fol[3]:,}", fol[4], fol[0], fol[1], fol[2], fol[5], v))
    if fad:
        print("%-9s %-9s %8s %5.1f%% %10.4f %10.4f %10.4f %9.4f"
              % ("", "fade", f"{fad[3]:,}", fad[4], fad[0], fad[1], fad[2], fad[5]))
    print()
mt5.shutdown()

print("-" * 96)
print("\nFOLLOW minus RANDOM, with the 2-SE bar for each:")
for s, (d_, two, ok) in summary.items():
    print("  %-9s %+.4f  (2SE %.4f)  %s" % (s, d_, two, "SIGNIFICANT" if ok else ""))
n_pos = sum(1 for v in summary.values() if v[0] > 0)
print("\n%d of %d symbols positive; %d significant under all three tie conventions."
      % (n_pos, len(summary), sum(1 for v in summary.values() if v[2])))
print("""
These windows do not overlap, so the error bars are honest - unlike every earlier
run in this project. If the effect survives here it is real; if it evaporates, the
M5 version was the overlap artifact that trap #5 predicts.""")
