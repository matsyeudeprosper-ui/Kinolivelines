"""Volume as an entry filter, measured on M1 bars where ties are rare.

The M15 version of this test was unusable. Volume correlates with bar size, bar
size determines how often ONE bar spans both the stop and the target, and those
ambiguous bars dominated the result - VOL SPIKE tied 18.9% of the time against
7.8% for random, and its expectancy swung from -0.091 to +0.099 depending purely
on how those bars were scored. That measures bar size, not volume.

On M1 the stop is ~60 points and a typical bar spans 20-40, so a single bar
rarely contains both barriers. 68 days instead of 520, but a clean 68 beats a
contaminated 520.

The tie rate is printed for every filter. If it is close to the random rate the
confound is gone and the comparison is meaningful; if a filter still ties far
more often, its number stays untrustworthy no matter how good it looks.

A result counts only if it differs from random in the SAME DIRECTION under all
three tie conventions. The earlier version checked significance but not sign, and
labelled a filter "REAL" that was significantly better under one convention and
significantly worse under another.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYM, SPREAD, HOLD = "BTCUSDm", 10.0, 120        # 120 M1 bars = 2h
STOP_ATR, TMULT = 0.40, 1.50

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, want):
    for k in (want, 90000, 45000, 20000, 10000, 5000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m1 = bars(mt5.TIMEFRAME_M1, 99000)
m15 = bars(mt5.TIMEFRAME_M15, 50000)
h1 = bars(mt5.TIMEFRAME_H1, 45000)
h4 = bars(mt5.TIMEFRAME_H4, 20000)
mt5.shutdown()

pc = m15["close"].shift(1)
m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                        (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
a = m15[["time", "atr"]].dropna().copy()
a["time"] = (a["time"] + pd.Timedelta(minutes=15)).astype("datetime64[ns]")
d = pd.merge_asof(m1, a, on="time", direction="backward").dropna(subset=["atr"]).reset_index(drop=True)

hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                   d["close"].to_numpy(float), d["atr"].to_numpy(float))
vol = d["tick_volume"].to_numpy(float)
n = len(cl)
print("M1 bars %s covering %d days" % (f"{n:,}", (d["time"].max() - d["time"].min()).days))
print("median M1 range %.0f pts vs typical stop %.0f pts -> ties should be rare\n"
      % (np.median(hi - lo), 0.40 * np.nanmedian(atr)))

vs = pd.Series(vol)
q80 = vs.rolling(720).quantile(0.80).shift(1).to_numpy()     # 720 M1 = 12h context
q20 = vs.rolling(720).quantile(0.20).shift(1).to_numpy()
med = vs.rolling(720).median().shift(1).to_numpy()

high_vol = vol >= q80
low_vol = vol <= q20
spike = vol >= 3.0 * med
big_spike = vol >= 5.0 * med
rising = np.r_[[False] * 3, (np.diff(vol)[:-2] > 0) & (np.diff(vol)[1:-1] > 0) & (np.diff(vol)[2:] > 0)]

lvl = np.zeros(n, bool)
for src, mins in ((h1, 60), (h4, 240)):
    j = np.searchsorted((src["time"] + pd.Timedelta(minutes=mins)).values,
                        d["time"].values, side="right") - 1
    H, L = src["high"].to_numpy(), src["low"].to_numpy()
    ok = np.where(j >= 0)[0]
    jj = j[ok]
    lvl[ok] |= ((lo[ok] <= H[jj]) & (hi[ok] >= H[jj])) | ((lo[ok] <= L[jj]) & (hi[ok] >= L[jj]))

WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR


def run(entries):
    w = l = ti = to = 0
    s1 = s2 = sL = sW = 0.0
    for i in entries:
        A = atr[i]
        if not np.isfinite(A) or A <= 0 or i + HOLD >= n:
            continue
        sd, td = STOP_ATR * A, STOP_ATR * A * TMULT
        win = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[win]); rmin = np.minimum.accumulate(lo[win])
        mid, endp = cl[i], cl[i + HOLD]
        for sign in (1, -1):
            e = mid + sign * SPREAD / 2
            tp, sl = e + sign * td, e - sign * sd
            if sign > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                hs = np.argmax(rmin <= sl) if rmin[-1] <= sl else 10 ** 6
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                hs = np.argmax(rmax >= sl) if rmax[-1] >= sl else 10 ** 6
            if ht == 10 ** 6 and hs == 10 ** 6:
                to += 1; r = rL = rW = sign * (endp - e) / A
            elif ht == hs:
                ti += 1; r = (WIN_R + LOSS_R) / 2; rL = LOSS_R; rW = WIN_R
            elif hs < ht:
                l += 1; r = rL = rW = LOSS_R
            else:
                w += 1; r = rL = rW = WIN_R
            s1 += r; s2 += r * r; sL += rL; sW += rW
    tot = max(w + l + ti + to, 1)
    m = s1 / tot
    return (w / tot * 100, m, math.sqrt(max(s2 / tot - m * m, 0) / tot), tot,
            ti / tot * 100, sL / tot, sW / tot)


base = np.arange(800, n - HOLD - 2)
valid = base[np.isfinite(q80[base]) & np.isfinite(med[base])]
rw, rm, rse, rtot, rtie, rL, rW = run(valid)

print("%-16s %9s %6s %7s %11s %11s %11s  %s"
      % ("filter", "trades", "tie%", "win%", "TIE->SPLIT", "TIE->LOSS", "TIE->WIN", "verdict"))
print("-" * 92)
print("%-16s %9s %5.1f%% %6.2f%% %+11.4f %+11.4f %+11.4f" % ("RANDOM", f"{rtot:,}", rtie, rw, rm, rL, rW))

for name, mask in (("HIGH VOL", high_vol), ("LOW VOL", low_vol),
                   ("VOL SPIKE 3x", spike), ("VOL SPIKE 5x", big_spike),
                   ("VOL RISING", rising), ("HIGH VOL+LEVEL", high_vol & lvl),
                   ("LOW VOL+LEVEL", low_vol & lvl)):
    e = valid[mask[valid]]
    if len(e) < 300:
        print("%-16s only %s entries - too few" % (name, f"{len(e):,}")); continue
    w_, m_, se_, tot_, tie_, mL, mW = run(e)
    two = 2 * math.sqrt(se_ ** 2 + rse ** 2)
    diffs = [m_ - rm, mL - rL, mW - rW]
    sig = [abs(x) > two for x in diffs]
    same_sign = all(x > 0 for x in diffs) or all(x < 0 for x in diffs)
    if all(sig) and same_sign:
        verdict = "REAL (%s)" % ("better" if diffs[0] > 0 else "worse")
    elif same_sign and any(sig):
        verdict = "leaning %s" % ("better" if diffs[0] > 0 else "worse")
    elif not same_sign:
        verdict = "SIGN FLIPS - untrustworthy"
    else:
        verdict = "no"
    print("%-16s %9s %5.1f%% %6.2f%% %+11.4f %+11.4f %+11.4f  %s"
          % (name, f"{tot_:,}", tie_, w_, m_, mL, mW, verdict))
print("-" * 92)
print("""
Check the tie%% column first. If a filter's tie rate is close to random's, the
confound that ruined the M15 run is gone and its number can be read. A verdict of
"SIGN FLIPS" means the filter is better than random under one scoring convention
and worse under another - that is a broken measurement, not a result.""")
