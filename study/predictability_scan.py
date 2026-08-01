"""Where does predictability exist AT ALL — before designing anything to exploit it.

Every prior attempt on this account started from a trading-folklore hypothesis
(levels, sweeps, grids, pairs, breakouts) and tested it. All failed. This inverts
that: measure deviations from a random walk across the tradeable universe, find
where structure exists, and only then design for that specific structure.

PRE-REGISTERED, fixed before any result is seen:

  Statistic      Lo-MacKinlay variance ratio VR(q) with heteroskedasticity-robust
                 z. VR>1 = trending/momentum, VR<1 = mean-reverting, VR=1 = random
                 walk. Reported alongside lag-1 autocorrelation as a cross-check.

  Cost overlay   An effect that cannot pay the spread is not an effect. For each
                 symbol/horizon the per-bar edge implied by the VR deviation is
                 compared against that symbol's own round-trip spread. This is the
                 filter that killed every BTC idea today and it is applied FIRST,
                 not as an afterthought.

  Multiple       Many symbols x many horizons guarantees something looks
  comparisons    significant. So each series is SPLIT IN HALF: discover on the
                 first half, confirm on the second. An effect must survive both,
                 with the same sign, to count. Anything appearing in one half only
                 is reported as noise, not a finding.

  Reporting      The null gets reported as loudly as a hit. "Nothing exceeds cost
                 anywhere" is a real and valuable answer - it stops attempt #14.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, os, json

OUT = os.path.dirname(os.path.abspath(__file__))
TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"

SYMBOLS = ["JP225m", "XAUUSDm", "DE30m", "BTCUSDm", "US30m", "USTECm",
           "US500m", "USOILm", "UK100m", "FR40m", "EURUSDm", "ETHUSDm"]

TFS = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
       "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}

QS = [2, 4, 8, 16]          # variance-ratio aggregation periods


def fetch(sym, tf):
    for n in (100000, 50000, 20000, 10000):
        r = mt5.copy_rates_from_pos(sym, tf, 0, n)
        if r is not None and len(r) >= 2000:
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s")
            return d
    return None


def variance_ratio(logret, q):
    """Lo-MacKinlay VR(q) with heteroskedasticity-consistent z-statistic.

    Using the robust form matters here: financial returns are heavily
    heteroskedastic, and the homoskedastic z would flag volatility clustering
    as if it were predictability."""
    x = np.asarray(logret, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < q * 40:
        return None
    mu = x.mean()
    var1 = np.sum((x - mu) ** 2) / (n - 1)
    if var1 <= 0:
        return None

    # overlapping q-period sums
    cs = np.cumsum(np.insert(x, 0, 0.0))
    xq = cs[q:] - cs[:-q]
    m = q * (n - q + 1) * (1 - q / n)
    varq = np.sum((xq - q * mu) ** 2) / m
    vr = varq / var1

    # heteroskedasticity-robust variance of VR
    theta = 0.0
    for j in range(1, q):
        d = (x[j:] - mu) ** 2
        e = (x[:-j] - mu) ** 2
        dj = np.sum(d * e) / (np.sum((x - mu) ** 2) ** 2 / n)
        theta += ((2 * (q - j) / q) ** 2) * dj
    if theta <= 0:
        return None
    return {"vr": vr, "z": (vr - 1) / np.sqrt(theta / n)}


def analyse(d, spread_px):
    """Return per-q stats for the first and second half of the series."""
    px = d["close"].to_numpy(dtype=float)
    lr = np.diff(np.log(px))
    half = len(lr) // 2
    halves = {"A": lr[:half], "B": lr[half:]}

    mean_px = float(np.mean(px))
    cost_frac = spread_px / mean_px          # round-trip cost as a return

    out = {}
    for q in QS:
        rec = {}
        for tag, seg in halves.items():
            r = variance_ratio(seg, q)
            if r is None:
                rec = None
                break
            sd = float(np.std(seg, ddof=1))
            # crude per-trade edge implied by the VR deviation over q bars:
            # |VR-1| scales the q-bar return sd
            implied = abs(r["vr"] - 1.0) * sd * np.sqrt(q)
            rec[tag] = {"vr": r["vr"], "z": r["z"],
                        "implied_edge": implied,
                        "edge_over_cost": implied / cost_frac if cost_frac > 0 else np.nan}
        out[q] = rec
    return out, cost_frac


mt5.initialize(path=TERMINAL)
rows = []
for sym in SYMBOLS:
    if not mt5.symbol_select(sym, True):
        continue
    si = mt5.symbol_info(sym)
    for tfname, tf in TFS.items():
        d = fetch(sym, tf)
        if d is None:
            continue
        spread_px = float(np.median(d["spread"].to_numpy())) * si.point
        if spread_px <= 0:
            spread_px = si.spread * si.point
        res, cost_frac = analyse(d, spread_px)
        days = (d["time"].iloc[-1] - d["time"].iloc[0]).days
        for q, rec in res.items():
            if not rec:
                continue
            a, b = rec["A"], rec["B"]
            same_sign = np.sign(a["vr"] - 1) == np.sign(b["vr"] - 1)
            rows.append({
                "symbol": sym, "tf": tfname, "q": q, "bars": len(d), "days": days,
                "vr_A": a["vr"], "z_A": a["z"], "vr_B": b["vr"], "z_B": b["z"],
                "same_sign": same_sign,
                "both_sig": (abs(a["z"]) > 2.5) and (abs(b["z"]) > 2.5),
                "edge_over_cost_A": a["edge_over_cost"],
                "edge_over_cost_B": b["edge_over_cost"],
                "cost_frac_bp": cost_frac * 1e4,
            })
    print(f"  scanned {sym}", flush=True)
mt5.shutdown()

df = pd.DataFrame(rows)
df.to_csv(os.path.join(OUT, "predictability_scan.csv"), index=False)
pd.set_option("display.width", 250)

print(f"\n{len(df)} symbol/timeframe/q combinations tested\n")

# The bar, stated before looking: significant in BOTH halves, same direction,
# and the implied edge must exceed the round-trip cost in both halves.
hits = df[df["both_sig"] & df["same_sign"] &
          (df["edge_over_cost_A"] > 1) & (df["edge_over_cost_B"] > 1)].copy()

print("=" * 110)
print("SURVIVORS — significant in BOTH halves, same sign, edge > cost in both")
print("=" * 110)
if len(hits):
    hits["dir"] = np.where(hits["vr_A"] > 1, "TREND", "REVERT")
    print(hits[["symbol", "tf", "q", "dir", "vr_A", "z_A", "vr_B", "z_B",
                "edge_over_cost_A", "edge_over_cost_B", "days"]]
          .sort_values("edge_over_cost_B", ascending=False)
          .to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
else:
    print("  NONE. No symbol/horizon shows replicable structure that clears its own cost.")

print("\n" + "=" * 110)
print("Significant in both halves but FAILS the cost test (real but unprofitable structure)")
print("=" * 110)
nc = df[df["both_sig"] & df["same_sign"] &
        ~((df["edge_over_cost_A"] > 1) & (df["edge_over_cost_B"] > 1))]
if len(nc):
    print(nc[["symbol", "tf", "q", "vr_A", "vr_B", "edge_over_cost_A", "edge_over_cost_B"]]
          .sort_values("edge_over_cost_B", ascending=False).head(15)
          .to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
else:
    print("  none")

print(f"\nfull table -> {os.path.join(OUT, 'predictability_scan.csv')}")
