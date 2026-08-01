"""Do the direction signals work AT THE MOMENT WE ACTUALLY ENTER?

The earlier which_timeframe.py scan measured "from a random bar, does H1-EMA
predict the next 8 minutes" and reported 0.645. Three problems with using that
to justify feeding signals to the decider:

  1. It was never split-half validated (my omission).
  2. It measured random bars. We do not enter on random bars - we rest limit
     orders at KinoliveLines levels and get filled when price comes TO us.
     A filled limit is a conditioned event, not a random sample.
  3. The 0.645 sample was selected using the outcome.

This rebuilds it honestly:

  POPULATION   Only bars where price touches a KinoliveLines level - the actual
               entry population. Levels reconstructed per-bar exactly as the EA
               builds them (prev closed H4/H1/M15 high+low, ATR merge, spacing).
  SPLIT-HALF   Every number reported for first half AND second half. A signal
               must hold in both, same direction, to count.
  NO OUTCOME   Measured on ALL level touches, not just ones followed by a big
     SELECTION move. This is what live trading actually gives you.
  HORIZON      8 minutes, matching the observed trade duration.

If the signals do not clear 0.50 in both halves on THIS population, they do not
belong in the prompt - they would be a statistic borrowed from trades we do not
take.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, os

OUT = os.path.dirname(os.path.abspath(__file__))
SYM, HOLD = "BTCUSDm", 8
mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def g(tf, n=50000):
    for k in (n, 20000, 10000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)
    return None


m1, m5, m15, h1, h4 = (g(mt5.TIMEFRAME_M1), g(mt5.TIMEFRAME_M5), g(mt5.TIMEFRAME_M15),
                       g(mt5.TIMEFRAME_H1), g(mt5.TIMEFRAME_H4))
si = mt5.symbol_info(SYM)
mt5.shutdown()

c = m1["close"].to_numpy(float)
n = len(c)
fwd = np.full(n, np.nan)
fwd[:n - HOLD] = c[HOLD:] - c[:n - HOLD]

# ---------- reconstruct the level set per M1 bar, as the EA builds it ----------
DUR = {"H4": 240, "H1": 60, "M15": 15}
SRC = {"H4": (h4, 3), "H1": (h1, 2), "M15": (m15, 1)}
idx = {k: np.searchsorted((SRC[k][0]["time"] + pd.Timedelta(minutes=DUR[k])).values,
                          m1["time"].values, side="right") - 1 for k in SRC}
arr = {k: (SRC[k][0]["high"].to_numpy(), SRC[k][0]["low"].to_numpy(), SRC[k][1]) for k in SRC}

pc = h1["close"].shift(1)
h1_atr = pd.concat([h1.high - h1.low, (h1.high - pc).abs(),
                    (h1.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean().to_numpy()
spread_px = float(np.median(m1["spread"].to_numpy())) * si.point

touch = np.zeros(n, bool)
for i in range(300, n - HOLD):
    j1 = idx["H1"][i]
    a = h1_atr[j1] if j1 >= 0 else np.nan
    if not np.isfinite(a) or a <= 0:
        continue
    raw = []
    for k in ("H4", "H1", "M15"):
        j = idx[k][i]
        if j < 0:
            continue
        hi, lo, p = arr[k]
        raw += [[hi[j], True, p], [lo[j], False, p]]
    if not raw:
        continue
    tol = max(spread_px * 3.0, a * 0.12)
    raw.sort(key=lambda x: x[0])
    keep = [True] * len(raw)
    for x in range(len(raw)):
        if not keep[x]:
            continue
        for y in range(x + 1, len(raw)):
            if keep[y] and abs(raw[x][0] - raw[y][0]) <= tol:
                if raw[y][2] > raw[x][2]:
                    raw[x] = raw[y]
                keep[y] = False
    merged = [r for x, r in enumerate(raw) if keep[x]]
    md = merged[0][0] * 0.001
    lv = []
    for r in merged:
        if not lv or r[1] != lv[-1][1] or abs(r[0] - lv[-1][0]) >= md:
            lv.append(r)
        if len(lv) >= 6:
            break
    lo_i, hi_i = m1["low"].iat[i], m1["high"].iat[i]
    if any(lo_i <= p <= hi_i for p, _, _ in lv):
        touch[i] = True

print(f"M1 bars {n:,}  |  bars touching a level: {touch.sum():,} ({touch.sum()/n*100:.1f}%)")

# ---------- direction signals, lagged, stamped at bar close ----------
sig = {}
for name, d in (("M5", m5), ("M15", m15), ("H1", h1), ("H4", h4)):
    px = d["close"]
    f = pd.DataFrame({"time": d["time"]})
    f["vs_ema21"] = np.sign(px - px.ewm(span=21).mean())
    f["ema_cross"] = np.sign(px.ewm(span=8).mean() - px.ewm(span=21).mean())
    hh = d["high"] > d["high"].shift(1)
    ll = d["low"] < d["low"].shift(1)
    f["structure"] = np.where(hh & ~ll, 1.0, np.where(ll & ~hh, -1.0, 0.0))
    cols = [x for x in f.columns if x != "time"]
    f[cols] = f[cols].astype(float).shift(1)
    f["time"] = (f["time"] + pd.Timedelta(minutes=DUR.get(name, 5))).astype("datetime64[ns]")
    sig[name] = f.dropna()

base = m1[["time"]].copy()
for name, f in sig.items():
    m = pd.merge_asof(base[["time"]], f, on="time", direction="backward")
    for col in f.columns[1:]:
        base[f"{name}_{col}"] = m[col].to_numpy()

base["fwd"] = fwd
base["touch"] = touch
d = base.dropna().reset_index(drop=True)
tt = d[d["touch"]].reset_index(drop=True)
half_all, half_t = len(d) // 2, len(tt) // 2
print(f"usable rows {len(d):,}  |  level-touch rows {len(tt):,}\n")


def acc(df, col, lo, hi):
    s = df[col].to_numpy()[lo:hi]
    up = (df["fwd"].to_numpy()[lo:hi] > 0)
    nl, ns = (s > 0).sum(), (s < 0).sum()
    if nl < 100 or ns < 100:
        return None, 0
    return (up[s > 0].mean() + (~up[s < 0]).mean()) / 2, nl + ns


rows = []
for name in sig:
    for col in ("vs_ema21", "ema_cross", "structure"):
        k = f"{name}_{col}"
        aT, nA = acc(tt, k, 0, half_t)
        bT, nB = acc(tt, k, half_t, len(tt))
        aA, _ = acc(d, k, 0, half_all)
        bA, _ = acc(d, k, half_all, len(d))
        if None in (aT, bT):
            continue
        rows.append({"tf": name, "signal": col,
                     "touch_A": aT, "touch_B": bT, "touch_min": min(aT, bT),
                     "all_A": aA, "all_B": bA, "nA": nA, "nB": nB})

r = pd.DataFrame(rows).sort_values("touch_min", ascending=False)
r.to_csv(os.path.join(OUT, "direction_at_levels.csv"), index=False)
pd.set_option("display.width", 200)

print("=" * 94)
print("DIRECTION ACCURACY AT LEVEL TOUCHES — split-half   (0.500 = coin flip)")
print("=" * 94)
print(r[["tf", "signal", "nA", "touch_A", "nB", "touch_B", "touch_min", "all_A", "all_B"]]
      .to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

good = r[(r.touch_A > 0.52) & (r.touch_B > 0.52)]
print("\n" + "=" * 94)
print("SURVIVES BOTH HALVES at >0.52 on the entry population")
print("=" * 94)
print(good[["tf", "signal", "touch_A", "touch_B"]].to_string(index=False, float_format=lambda x: f"{x:,.3f}")
      if len(good) else "  NONE — these signals do not belong in the prompt.")
print(f"\nfull table -> {os.path.join(OUT,'direction_at_levels.csv')}")
