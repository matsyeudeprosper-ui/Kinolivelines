"""Does VOLUME carry any information about which barrier gets hit first?

Every test so far has used price alone. tick_volume sits in every bar we have
pulled and has never once been looked at - a whole dimension unexamined.

The idea worth testing is not "volume predicts direction" but the weaker and more
plausible "volume tells you whether a move means anything". A level tested on
heavy participation is a different event from one tested on nothing.

FIVE VARIANTS, each measured against the same random control:
  HIGH VOL      bar volume in the top quintile of the last 96 bars
  LOW VOL       bottom quintile
  VOL SPIKE     volume >= 3x the 96-bar median (a genuine burst, rarer)
  VOL RISING    volume up for 3 consecutive bars
  HIGH + LEVEL  top-quintile volume AND price touching an H1/H4 level

The last one is the interesting combination: level touches alone measured WORSE
than random over 520 days, but that pooled every touch regardless of whether
anyone was actually trading. A defended level should show heavy volume.

All of these are LOCATION filters, entered long AND short, so no direction is
being supplied. If a filter shifts the win rate, it is telling us something about
the quality of the moment, independent of which way it goes.

Corrected method throughout: ambiguous bars where one bar spans both barriers are
scored NEUTRALLY, geometry is the live shape (stop 0.4x ATR M15, target 1.5x
stop, 120-min hold), real $10 spread, timeouts settled at the closing price.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYM, SPREAD, HOLD = "BTCUSDm", 10.0, 8
STOP_ATR, TMULT = 0.40, 1.50

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, want):
    for k in (want, 45000, 20000, 10000, 5000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m15 = bars(mt5.TIMEFRAME_M15, 50000)
h1 = bars(mt5.TIMEFRAME_H1, 45000)
h4 = bars(mt5.TIMEFRAME_H4, 20000)
mt5.shutdown()

pc = m15["close"].shift(1)
m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                        (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
d = m15.dropna(subset=["atr"]).reset_index(drop=True)
hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                   d["close"].to_numpy(float), d["atr"].to_numpy(float))
vol = d["tick_volume"].to_numpy(float)
n = len(cl)
print("M15 bars %s covering %d days" % (f"{n:,}", (d["time"].max() - d["time"].min()).days))
print("tick_volume: median %.0f, p90 %.0f, max %.0f\n"
      % (np.median(vol), np.percentile(vol, 90), vol.max()))

# rolling volume context, strictly backward-looking (shifted so the current bar
# is never part of its own benchmark)
vs = pd.Series(vol)
q80 = vs.rolling(96).quantile(0.80).shift(1).to_numpy()
q20 = vs.rolling(96).quantile(0.20).shift(1).to_numpy()
med = vs.rolling(96).median().shift(1).to_numpy()

high_vol = vol >= q80
low_vol = vol <= q20
spike = vol >= 3.0 * med
rising = np.r_[False, False, False, (np.diff(vol, 1)[:-2] > 0) & (np.diff(vol, 1)[1:-1] > 0) & (np.diff(vol, 1)[2:] > 0)]

# level touches, H1 and H4 previous closed extremes
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
    s1 = s2 = 0.0
    sL = sW = 0.0
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


base = np.arange(300, n - HOLD - 2)
valid = base[np.isfinite(q80[base]) & np.isfinite(med[base])]
rw, rm, rse, rtot, rtie, rL, rW = run(valid)

print("%-16s %9s %6s %7s %11s %11s %11s" % ("filter","trades","tie%","win%","TIE->SPLIT","TIE->LOSS","TIE->WIN"))
print("-" * 84)
print("%-16s %9s %5.1f%% %6.2f%% %+11.4f %+11.4f %+11.4f" % ("RANDOM", f"{rtot:,}", rtie, rw, rm, rL, rW))

for name, mask in (("HIGH VOL", high_vol), ("LOW VOL", low_vol), ("VOL SPIKE", spike),
                   ("VOL RISING", rising), ("HIGH VOL+LEVEL", high_vol & lvl),
                   ("LOW VOL+LEVEL", low_vol & lvl)):
    e = valid[mask[valid]]
    if len(e) < 300:
        print("%-16s only %s entries - too few" % (name, f"{len(e):,}")); continue
    w_, m_, se_, tot_, tie_, mL, mW = run(e)
    two = 2 * math.sqrt(se_ ** 2 + rse ** 2)
    votes = sum(1 for a, b in ((m_, rm), (mL, rL), (mW, rW)) if abs(a - b) > two)
    tag = {3: "REAL (all 3)", 2: "2 of 3", 1: "1 of 3 - suspect", 0: "no"}[votes]
    print("%-16s %9s %5.1f%% %6.2f%% %+11.4f %+11.4f %+11.4f   %s"
          % (name, f"{tot_:,}", tie_, w_, m_, mL, mW, tag))
print("-" * 78)
print("""
Breakeven at this geometry is around 40% wins. Nothing here is expected to clear
that on its own - what matters is whether any filter moves the number at all, in
either direction. A filter that makes things reliably WORSE is as useful as one
that helps, because it can be inverted or avoided.""")
