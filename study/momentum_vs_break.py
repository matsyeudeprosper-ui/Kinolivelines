"""Rule 9 says don't follow a level break. Momentum says follow a 1x ATR move.
When both apply at once, which is right?

Rule 9 (validated on 520 days of M15): following a confirmed H1/H4 level break is
worse than random.
Momentum (validated on 68 days of M1, both halves): following a >=1x ATR(M15)
30-minute move is better than random.

Those overlap - a level break usually involves a decent move - so a rule set
holding both is self-contradictory until this is settled. Split the momentum
population by whether the move also broke a level:

  MOMENTUM, NO BREAK    1x ATR move, price NOT at or through an H1/H4 level
  MOMENTUM, AT LEVEL    the move ends with price touching a level
  MOMENTUM, BROKE       the move closed through a level that the prior close
                        was on the other side of

If MOMENTUM-NO-BREAK is the strong arm and MOMENTUM-BROKE is weak, both findings
are true and simply describe different situations - rule 9 stands and momentum
gets a "not at a level" condition. If MOMENTUM-BROKE is just as strong, then rule
9 was measuring something else and needs revisiting.

Measured on M1 where ties are negligible. Real $10 spread, stop 0.4x ATR(M15),
target 1.5x stop, 120-minute cap, timeouts settled at the closing price. CONTINUE
and REVERT arms throughout so each population carries its own control.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYM, SPREAD, HOLD = "BTCUSDm", 10.0, 120
STOP_ATR, TMULT = 0.40, 1.50
LOOK = 30

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, want):
    for k in (want, 90000, 45000, 20000, 10000):
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
n = len(cl)
move = np.full(n, np.nan)
move[LOOK:] = cl[LOOK:] - cl[:-LOOK]

# level context per bar: nearest H1/H4 previous-closed extremes
at_level = np.zeros(n, bool)
broke = np.zeros(n, np.int8)
for src, mins in ((h1, 60), (h4, 240)):
    j = np.searchsorted((src["time"] + pd.Timedelta(minutes=mins)).values,
                        d["time"].values, side="right") - 1
    H, L = src["high"].to_numpy(), src["low"].to_numpy()
    ok = np.where(j >= 1)[0]
    jj = j[ok]
    at_level[ok] |= ((lo[ok] <= H[jj]) & (hi[ok] >= H[jj])) | ((lo[ok] <= L[jj]) & (hi[ok] >= L[jj]))
    up_break = (cl[ok - 1] < H[jj]) & (cl[ok] > H[jj])
    dn_break = (cl[ok - 1] > L[jj]) & (cl[ok] < L[jj])
    broke[ok[up_break]] = 1
    broke[ok[dn_break]] = -1

WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR


def sim(entries, dirs):
    w = l = ti = to = 0
    s1 = s2 = 0.0
    for i, dirn in zip(entries, dirs):
        A = atr[i]
        if not np.isfinite(A) or A <= 0 or i + HOLD >= n:
            continue
        sd, td = STOP_ATR * A, STOP_ATR * A * TMULT
        win = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[win]); rmin = np.minimum.accumulate(lo[win])
        mid, endp = cl[i], cl[i + HOLD]
        for s_ in ((1, -1) if dirn == 0 else (dirn,)):
            e = mid + s_ * SPREAD / 2
            tp, sl = e + s_ * td, e - s_ * sd
            if s_ > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                hs = np.argmax(rmin <= sl) if rmin[-1] <= sl else 10 ** 6
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                hs = np.argmax(rmax >= sl) if rmax[-1] >= sl else 10 ** 6
            if ht == 10 ** 6 and hs == 10 ** 6:
                to += 1; r = s_ * (endp - e) / A
            elif ht == hs:
                ti += 1; r = (WIN_R + LOSS_R) / 2
            elif hs < ht:
                l += 1; r = LOSS_R
            else:
                w += 1; r = WIN_R
            s1 += r; s2 += r * r
    tot = max(w + l + ti + to, 1)
    m = s1 / tot
    return w / tot * 100, m, math.sqrt(max(s2 / tot - m * m, 0) / tot), tot


base = np.arange(800, n - HOLD - 2)
rw, rm, rse, rtot = sim(base, np.zeros(len(base), np.int8))
mom = np.abs(move) >= 1.0 * atr

pops = {
    "MOMENTUM all":        mom,
    "MOM, no level":       mom & ~at_level & (broke == 0),
    "MOM, at level":       mom & at_level & (broke == 0),
    "MOM, BROKE level":    mom & (broke != 0),
}

print("M1 bars %s covering %d days" % (f"{n:,}", (d["time"].max() - d["time"].min()).days))
print("momentum bars %s | of those, broke a level %s, at a level %s\n"
      % (f"{int(mom[base].sum()):,}", f"{int((mom & (broke != 0))[base].sum()):,}",
         f"{int((mom & at_level & (broke == 0))[base].sum()):,}"))

print("%-18s %-9s %8s %7s %11s %11s  %s"
      % ("population", "arm", "trades", "win%", "expectancy", "vs random", "verdict"))
print("-" * 86)
print("%-18s %-9s %8s %6.2f%% %+11.4f" % ("RANDOM", "", f"{rtot:,}", rw, rm))

for name, mask in pops.items():
    e = base[mask[base]]
    if len(e) < 300:
        print("%-18s only %s entries - too few" % (name, f"{len(e):,}")); continue
    dirn = np.sign(move[e]).astype(np.int8)
    for arm, dd in (("CONTINUE", dirn), ("REVERT", -dirn)):
        w_, m_, se_, tot_ = sim(e, dd)
        two = 2 * math.sqrt(se_ ** 2 + rse ** 2)
        d_ = m_ - rm
        v = "REAL %s" % ("better" if d_ > 0 else "worse") if abs(d_) > two else "not sig"
        print("%-18s %-9s %8s %6.2f%% %+11.4f %+11.4f  %s"
              % (name if arm == "CONTINUE" else "", arm, f"{tot_:,}", w_, m_, d_, v))
print("-" * 86)
print("""
If MOM-no-level CONTINUE is strong and MOM-BROKE CONTINUE is weak or negative,
both rules are true about different situations: rule 9 stands, and momentum needs
a "not at a level" condition attached. If MOM-BROKE is just as strong, rule 9 is
in trouble and needs re-examining.""")
