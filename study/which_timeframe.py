"""Which higher timeframe actually predicts a move of THIS size?

Calibrated to the winning trade: +195 points, 0.302%, 7.5 minutes, 1.72x ATR(M15).

The question is not "which timeframe looks like the trend" - it is which
timeframe's state, known BEFORE the move, separates up-moves from down-moves.
Measured as hit rate conditional on each timeframe's direction, on the large
moves that are actually worth trading.

Cost is deliberately IGNORED here. This is a pure direction question.

No lookahead: every trend state uses only bars that had closed at the decision
moment, and is merged onto M1 with a backward as-of join.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, os

OUT = os.path.dirname(os.path.abspath(__file__))
SYM = "BTCUSDm"
HOLD_MIN = 8          # the trade took 7.5 minutes
mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def get(tf, n=50000):
    for k in (n, 20000, 10000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s")
            return d
    return None


m1 = get(mt5.TIMEFRAME_M1)
tfs = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
       "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
mt5.shutdown()

m1 = m1.sort_values("time").reset_index(drop=True)
c = m1["close"].to_numpy(float)
n = len(c)

# forward move over the holding period
fwd = np.full(n, np.nan)
fwd[:n - HOLD_MIN] = c[HOLD_MIN:] - c[:n - HOLD_MIN]

# ATR(M15) in points, to define what counts as a "big" move
tr = pd.concat([m1.high - m1.low,
                (m1.high - m1.close.shift(1)).abs(),
                (m1.low - m1.close.shift(1)).abs()], axis=1).max(axis=1)
atr_m1 = tr.rolling(14).mean()
atr_m15_equiv = atr_m1 * np.sqrt(15)            # scale M1 ATR to M15 terms

print(f"M1 bars: {n:,}   {m1.time.iloc[0]} -> {m1.time.iloc[-1]}")
print(f"holding period: {HOLD_MIN} min (the trade took 7.5)\n")

# --- build trend signals per higher timeframe, shifted to avoid lookahead ---
sigs = {}
mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
for name, tf in tfs.items():
    d = get(tf)
    if d is None:
        continue
    d = d.sort_values("time").reset_index(drop=True)
    px = d["close"]
    ema_f, ema_s = px.ewm(span=8).mean(), px.ewm(span=21).mean()
    don_hi = d["high"].rolling(20).max()
    don_lo = d["low"].rolling(20).min()

    feat = pd.DataFrame({"time": d["time"]})
    feat["ema_cross"] = np.sign(ema_f - ema_s)                       # fast vs slow
    feat["slope"]     = np.sign(px.diff(5))                          # 5-bar momentum
    feat["above_ema"] = np.sign(px - ema_s)                          # price vs trend
    feat["donchian"]  = np.where(px >= don_hi.shift(1), 1,
                        np.where(px <= don_lo.shift(1), -1, 0))      # breakout
    hh = d["high"] > d["high"].shift(1)
    ll = d["low"]  < d["low"].shift(1)
    feat["structure"] = np.where(hh & ~ll, 1, np.where(ll & ~hh, -1, 0))

    # CRITICAL: shift by one bar so the state was fully known at decision time,
    # then stamp it at the bar's CLOSE (bar time + duration).
    dur = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}[name]
    # cast to float first: np.where produces int64, and shifting introduces NaN
    cols = [x for x in feat.columns if x != "time"]
    feat[cols] = feat[cols].astype(float).shift(1)
    # normalise resolution: adding a Timedelta promotes s -> us and merge_asof
    # refuses to join keys of different datetime resolutions
    feat["time"] = (feat["time"] + pd.Timedelta(minutes=dur)).astype("datetime64[ns]")
    sigs[name] = feat.dropna()
mt5.shutdown()

base = m1[["time"]].copy()
base["time"] = base["time"].astype("datetime64[ns]")
base["fwd"] = fwd
base["atr15"] = atr_m15_equiv.to_numpy()
for name, feat in sigs.items():
    merged = pd.merge_asof(base[["time"]], feat, on="time", direction="backward")
    for col in feat.columns[1:]:
        base[f"{name}_{col}"] = merged[col].to_numpy()

base = base.dropna(subset=["fwd", "atr15"])

# "worth trading" = forward move at least 1.5x ATR(M15), like the real trade (1.72x)
big = base[base["fwd"].abs() >= 1.5 * base["atr15"]].copy()
print(f"bars with a >=1.5x ATR(M15) move in the next {HOLD_MIN} min: "
      f"{len(big):,} of {len(base):,}  ({len(big)/len(base)*100:.1f}%)\n")

rows = []
for name in sigs:
    for col in ["ema_cross", "slope", "above_ema", "donchian", "structure"]:
        k = f"{name}_{col}"
        if k not in big:
            continue
        for sub, lab in ((big, "big moves"), (base, "all bars")):
            s = sub[k]
            up = sub["fwd"] > 0
            long_n = (s > 0).sum()
            short_n = (s < 0).sum()
            if long_n < 200 or short_n < 200:
                continue
            hit_long = up[s > 0].mean()          # signal says up -> move was up?
            hit_short = (~up)[s < 0].mean()      # signal says down -> move was down?
            edge = (hit_long + hit_short) / 2    # balanced accuracy, 0.5 = useless
            rows.append({"tf": name, "signal": col, "sample": lab,
                         "n_long": long_n, "n_short": short_n,
                         "hit_up": hit_long, "hit_dn": hit_short,
                         "balanced_acc": edge})

r = pd.DataFrame(rows)
r.to_csv(os.path.join(OUT, "which_timeframe.csv"), index=False)
pd.set_option("display.width", 200)

for lab in ("big moves", "all bars"):
    sub = r[r["sample"] == lab].sort_values("balanced_acc", ascending=False)
    print("=" * 92)
    print(f"DIRECTION ACCURACY — {lab}   (0.500 = coin flip)")
    print("=" * 92)
    print(sub[["tf", "signal", "n_long", "n_short", "hit_up", "hit_dn", "balanced_acc"]]
          .head(12).to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    print()

print("=" * 92)
print("BEST TIMEFRAME overall (averaged across its 5 signals, big moves)")
print("=" * 92)
bm = r[r["sample"] == "big moves"].groupby("tf")["balanced_acc"].agg(["mean", "max", "count"])
print(bm.sort_values("mean", ascending=False).to_string(float_format=lambda x: f"{x:,.3f}"))
print(f"\nfull table -> {os.path.join(OUT,'which_timeframe.csv')}")
