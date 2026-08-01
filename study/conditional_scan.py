"""The last honest question: does predictability exist CONDITIONALLY?

The variance-ratio scan tested unconditional linear predictability and found
nothing that replicates. This tests whether returns become predictable only in
specific states - after a large move, in a volatility regime, at a time of day.
That is the one thing the previous scan structurally cannot see.

PRE-REGISTERED before any result:

  Statistic   Mean forward return over k bars, conditional on state S, with a
              t-statistic. Directly tradeable, unlike a variance ratio: if the
              mean forward return after state S is +X, you buy on S.

  Cost        |mean forward return| must exceed the round-trip spread as a
              fraction of price. Applied first. An effect below cost is not an
              effect - the UK100 signal in the previous scan was the strongest
              in 192 combinations and was still 7x too small to trade.

  States      Chosen from mechanism, not fishing:
                bigmove_up / bigmove_down  last bar |r| > 2 sigma
                                           (does a shock continue or revert?)
                hivol / lovol              trailing realised vol top/bottom
                                           quartile (regime dependence)
                session_open               first 4 bars after a >1h gap
                                           (opening auction effects)

  Multiple    6 symbols x 2 timeframes x 6 states x 2 horizons = 144 tests.
  comparisons Same guard as before: SPLIT-HALF. Discover on the first half,
              confirm on the second. Must be significant in both, SAME SIGN,
              and clear cost in both. Anything surviving one half only is noise.

  Reporting   The null gets stated plainly. If this is empty too, the honest
              conclusion is that this account cannot support systematic
              directional trading and the choice is venue change or stop.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, os

OUT = os.path.dirname(os.path.abspath(__file__))
TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"

SYMBOLS = ["JP225m", "XAUUSDm", "DE30m", "BTCUSDm", "US30m", "USTECm"]
TFS = {"M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
HORIZONS = [1, 4]


def fetch(sym, tf):
    for n in (100000, 50000, 20000, 10000):
        r = mt5.copy_rates_from_pos(sym, tf, 0, n)
        if r is not None and len(r) >= 3000:
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s")
            return d
    return None


def build_states(d):
    """All states use only information available at the close of bar i."""
    c = d["close"].to_numpy(dtype=float)
    r = np.concatenate([[np.nan], np.diff(np.log(c))])
    d = d.copy()
    d["r"] = r

    # trailing 50-bar realised vol, shifted so it is known at bar i
    vol = pd.Series(r).rolling(50).std()
    sig = pd.Series(r).rolling(200).std()

    gap = d["time"].diff().dt.total_seconds()
    med_gap = gap.median()
    new_session = gap > med_gap * 4          # a real break, not a missing bar
    since_open = (~new_session).groupby(new_session.cumsum()).cumcount()

    q_hi = vol.rolling(500).quantile(0.75)
    q_lo = vol.rolling(500).quantile(0.25)

    return {
        "bigmove_up":   (d["r"] > 2 * sig).to_numpy(),
        "bigmove_down": (d["r"] < -2 * sig).to_numpy(),
        "hivol":        (vol > q_hi).to_numpy(),
        "lovol":        (vol < q_lo).to_numpy(),
        "session_open": (since_open < 4).to_numpy(),
        "all_bars":     np.ones(len(d), dtype=bool),   # control: unconditional
    }, r


def test(mask, r, k, cost_frac):
    """Mean forward k-bar return where mask is True."""
    n = len(r)
    fwd = np.full(n, np.nan)
    logc = np.nancumsum(np.nan_to_num(r))
    fwd[:n - k] = logc[k:] - logc[:n - k]

    ok = mask & np.isfinite(fwd)
    x = fwd[ok]
    if len(x) < 100:
        return None
    m, s = float(np.mean(x)), float(np.std(x, ddof=1))
    if s <= 0:
        return None
    t = m / (s / np.sqrt(len(x)))
    return {"n": len(x), "mean": m, "t": t,
            "edge_over_cost": abs(m) / cost_frac if cost_frac > 0 else np.nan}


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
        cost_frac = spread_px / float(d["close"].mean())

        states, r = build_states(d)
        half = len(d) // 2
        for sname, mask in states.items():
            for k in HORIZONS:
                mA = mask.copy(); mA[half:] = False
                mB = mask.copy(); mB[:half] = False
                a, b = test(mA, r, k, cost_frac), test(mB, r, k, cost_frac)
                if not a or not b:
                    continue
                rows.append({
                    "symbol": sym, "tf": tfname, "state": sname, "k": k,
                    "nA": a["n"], "meanA_bp": a["mean"] * 1e4, "tA": a["t"],
                    "eocA": a["edge_over_cost"],
                    "nB": b["n"], "meanB_bp": b["mean"] * 1e4, "tB": b["t"],
                    "eocB": b["edge_over_cost"],
                    "same_sign": np.sign(a["mean"]) == np.sign(b["mean"]),
                    "cost_bp": cost_frac * 1e4,
                })
    print(f"  scanned {sym}", flush=True)
mt5.shutdown()

df = pd.DataFrame(rows)
df.to_csv(os.path.join(OUT, "conditional_scan.csv"), index=False)
pd.set_option("display.width", 250)
print(f"\n{len(df)} conditional tests\n")

sig = df[(df.tA.abs() > 2.5) & (df.tB.abs() > 2.5) & df.same_sign]
hits = sig[(sig.eocA > 1) & (sig.eocB > 1)]

print("=" * 118)
print("SURVIVORS - significant both halves, same sign, edge > cost in both")
print("=" * 118)
if len(hits):
    print(hits[["symbol", "tf", "state", "k", "nA", "meanA_bp", "tA", "nB",
                "meanB_bp", "tB", "eocA", "eocB", "cost_bp"]]
          .sort_values("eocB", ascending=False)
          .to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
else:
    print("  NONE.")

print("\n" + "=" * 118)
print("Replicable structure that FAILS the cost test (real but unprofitable)")
print("=" * 118)
nc = sig[~((sig.eocA > 1) & (sig.eocB > 1))]
if len(nc):
    print(nc[["symbol", "tf", "state", "k", "meanA_bp", "tA", "meanB_bp", "tB",
              "eocA", "eocB", "cost_bp"]]
          .sort_values("eocB", ascending=False).head(20)
          .to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
else:
    print("  none")

print("\n" + "=" * 118)
print("Diagnostics - did the test fire?")
print("=" * 118)
print(f"  |tA|>2.5: {(df.tA.abs()>2.5).sum()}   |tB|>2.5: {(df.tB.abs()>2.5).sum()}   "
      f"both: {((df.tA.abs()>2.5)&(df.tB.abs()>2.5)).sum()}   both+same_sign: {len(sig)}")
print(f"  |t| range A: {df.tA.abs().min():.2f} - {df.tA.abs().max():.2f}")
print(f"  edge/cost median A: {df.eocA.median():.2f}  max: {df.eocA.max():.2f}")
print(f"\nfull table -> {os.path.join(OUT,'conditional_scan.csv')}")
