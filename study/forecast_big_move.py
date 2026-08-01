"""Can a big move be forecast BEFORE it happens?

This is the bottleneck the timeframe scan exposed. That scan found higher-
timeframe trend calls the direction of large moves ~64% of the time - but the
sample was selected using the outcome ("bars where a big move happened"), which
cannot be known in advance. On all bars, direction is a coin flip.

So the strategy only exists if the ex-ante question has an answer:

    Given only information available NOW, is a large move likely in the next
    8 minutes?

If some observable lifts the probability meaningfully above the 1.9% base rate,
then combining it with the H1-EMA direction signal is a real strategy. If
nothing does, the 64% number is permanently out of reach and this line closes.

PRE-REGISTERED:
  Target      |forward 8-min move| >= 1.5 x ATR(M15). Base rate ~1.9%.
  Predictors  Only ex-ante observables:
                compression   short vol / long vol (coiling before expansion)
                range_ratio   recent range / ATR
                since_big     bars since the last big move
                vol_of_vol    is volatility itself unstable
                tick_vol      volume vs its own average
                hour          time of day
  Bar         A predictor must raise P(big move) in BOTH halves of the data,
              in the same direction, by a margin worth acting on. Lift is
              reported against the base rate, not against zero.
  Trap        Selecting on the outcome is exactly what invalidated the previous
              result. Every predictor here is computed from data strictly
              BEFORE the bar whose forward move is being predicted.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, os

OUT = os.path.dirname(os.path.abspath(__file__))
SYM, HOLD = "BTCUSDm", 8

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
d = None
for k in (50000, 20000):
    r = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M1, 0, k)
    if r is not None and len(r):
        d = pd.DataFrame(r); break
mt5.shutdown()
d["time"] = pd.to_datetime(d["time"], unit="s")
d = d.sort_values("time").reset_index(drop=True)

c = d["close"].to_numpy(float)
n = len(c)
lr = pd.Series(np.concatenate([[np.nan], np.diff(np.log(c))]))

tr = pd.concat([d.high - d.low, (d.high - d.close.shift(1)).abs(),
                (d.low - d.close.shift(1)).abs()], axis=1).max(axis=1)
atr14 = tr.rolling(14).mean()
atr15_equiv = atr14 * np.sqrt(15)

fwd = np.full(n, np.nan)
fwd[:n - HOLD] = c[HOLD:] - c[:n - HOLD]
big = (np.abs(fwd) >= 1.5 * atr15_equiv.to_numpy())

# ---- predictors, all strictly backward-looking ----
vol_s = lr.rolling(15).std()
vol_l = lr.rolling(120).std()
X = pd.DataFrame({
    "compression": (vol_s / vol_l),                                  # <1 = coiling
    "range_ratio": (d.high.rolling(15).max() - d.low.rolling(15).min()) / atr14,
    "vol_of_vol":  vol_s.rolling(60).std() / vol_s,
    "tick_vol":    d.tick_volume / d.tick_volume.rolling(120).mean(),
    "hour":        d.time.dt.hour.astype(float),
})
# bars since the last big move — uses only past outcomes, which IS knowable live
sb = np.zeros(n); cnt = 0
for i in range(n):
    sb[i] = cnt
    cnt = 0 if (i >= HOLD and big[i - HOLD] == True) else cnt + 1
X["since_big"] = sb

X = X.shift(1)                       # everything known at the PREVIOUS close
ok = np.isfinite(fwd) & X.notna().all(axis=1).to_numpy() & np.isfinite(atr15_equiv.to_numpy())
X, y = X[ok].reset_index(drop=True), big[ok]
half = len(X) // 2
base = y.mean()

print(f"M1 bars {n:,} | usable {len(X):,} | base rate of a big move: {base*100:.2f}%")
print(f"(a 'big move' = >= 1.5x ATR(M15) within {HOLD} minutes)\n")

rows = []
for col in X.columns:
    v = X[col].to_numpy()
    if col == "hour":
        buckets = [(h, v == h) for h in range(24)]
    else:
        qs = np.nanquantile(v, [0.2, 0.4, 0.6, 0.8])
        buckets = [("Q1 low", v <= qs[0]), ("Q2", (v > qs[0]) & (v <= qs[1])),
                   ("Q3", (v > qs[1]) & (v <= qs[2])), ("Q4", (v > qs[2]) & (v <= qs[3])),
                   ("Q5 high", v > qs[3])]
    for lab, m in buckets:
        a = m.copy(); a[half:] = False
        b = m.copy(); b[:half] = False
        if a.sum() < 300 or b.sum() < 300:
            continue
        pa, pb = y[a].mean(), y[b].mean()
        rows.append({"predictor": col, "bucket": lab,
                     "nA": int(a.sum()), "pA": pa, "liftA": pa / base,
                     "nB": int(b.sum()), "pB": pb, "liftB": pb / base,
                     "min_lift": min(pa / base, pb / base)})

r = pd.DataFrame(rows)
r.to_csv(os.path.join(OUT, "forecast_big_move.csv"), index=False)
pd.set_option("display.width", 200)

print("=" * 96)
print("PREDICTORS THAT RAISE P(big move) IN BOTH HALVES — ranked by weakest half")
print("=" * 96)
hits = r[(r.liftA > 1.3) & (r.liftB > 1.3)].sort_values("min_lift", ascending=False)
if len(hits):
    print(hits[["predictor", "bucket", "nA", "pA", "liftA", "nB", "pB", "liftB"]]
          .head(15).to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
else:
    print("  NONE reach 1.3x lift in both halves.")

print("\n" + "=" * 96)
print("BEST AND WORST BUCKET PER PREDICTOR (both halves shown)")
print("=" * 96)
for col in X.columns:
    s = r[r.predictor == col]
    if not len(s):
        continue
    bst = s.loc[s.min_lift.idxmax()]
    wst = s.loc[s.min_lift.idxmin()]
    print(f"  {col:<12} best {str(bst.bucket):<8} liftA {bst.liftA:.2f} liftB {bst.liftB:.2f}   |   "
          f"worst {str(wst.bucket):<8} liftA {wst.liftA:.2f} liftB {wst.liftB:.2f}")

print(f"\nA lift of 1.0 = no information. 2.0 = twice as likely as the base {base*100:.2f}%.")
print(f"full table -> {os.path.join(OUT,'forecast_big_move.csv')}")
