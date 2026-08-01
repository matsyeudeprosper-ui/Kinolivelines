"""H3: does the Exness BTCUSDm quote LAG the real exchange by enough to trade?

Exness quote BTCUSDm themselves - the price is derived from real markets rather than
being a venue anyone trades on. If their feed trails, the next move is briefly knowable
and that is an execution edge requiring no directional forecast at all. It would also be
entirely Exness-specific, so no cross-market replication is owed.

WHAT THIS DATA CAN AND CANNOT ANSWER. Paired samples arrive every ~2.4 seconds, so
sub-second lag is invisible here. That is not the limitation it appears to be: an order
from this VPS through MT5 to Exness cannot round-trip in less than roughly a hundred
milliseconds, and a lag shorter than that is untradeable no matter how real. The
economically relevant range is seconds, which is exactly what these samples resolve.

METHOD, following the constraints set for this test:
  * millisecond timestamps on both legs, not sample index
  * PRICE CHANGES, never the raw gap. The Exness-OKX difference is dominated by the
    BTC-USD versus BTC-USDT basis plus Exness's own markup - a spread of about $72 here
    - which is a level, drifts slowly, and would swamp any lag signal
  * the basis is removed explicitly with a rolling median before anything is measured
  * each recorded day is analysed SEPARATELY and must agree in direction before pooling
  * the headline number is not a correlation: it is the actual future Exness move in
    DOLLARS conditional on an OKX move having already happened
  * execution is modelled honestly - the move is only capturable from the NEXT sample
    onward, because you cannot act on information at the instant you receive it
  * the final quarter of each day is held out untouched

PASS/FAIL, fixed before running. The lead must be positive, agree across every day, and
the capturable move must comfortably exceed the $10 spread plus slippage. A statistically
detectable lag that yields $2 is not an edge; it is a curiosity.
"""
import os, glob, math
import numpy as np, pandas as pd

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
SPREAD = 10.0
SLIP = 2.0                 # assumed adverse fill vs quoted mid, per side
BASIS_WIN = 125            # ~5 minutes of samples
MAX_LAG = 6                # samples, ~14 seconds
HOLDOUT_FRAC = 0.25

files = sorted(glob.glob(os.path.join(DATA, "micro_BTCUSDm_*.csv")))
print("BROKER FEED LAG - Exness BTCUSDm vs OKX BTC-USDT")
print("spread $%.0f, assumed slippage $%.0f/side, entry only from the NEXT sample\n"
      % (SPREAD, SLIP))

days = []
for fp in files:
    d = pd.read_csv(fp)
    if len(d) < 400:
        print("%s  only %d rows - skipped" % (os.path.basename(fp), len(d)))
        continue
    d = d.dropna(subset=["mt5_bid", "mt5_ask", "okx_bid", "okx_ask", "mt5_ms", "okx_ms"])
    ex = (d["mt5_bid"] + d["mt5_ask"]) / 2.0
    ok = (d["okx_bid"] + d["okx_ask"]) / 2.0
    # remove the BTC-USD vs BTC-USDT basis and the broker markup: a slow level, not a signal
    basis = (ex - ok).rolling(BASIS_WIN, min_periods=30).median()
    ex_adj = (ex - basis).to_numpy(float)
    ok_a = ok.to_numpy(float)
    m = np.isfinite(ex_adj) & np.isfinite(ok_a)
    ex_adj, ok_a = ex_adj[m], ok_a[m]
    mt5_ms = d["mt5_ms"].to_numpy(float)[m]
    okx_ms = d["okx_ms"].to_numpy(float)[m]
    if len(ex_adj) < 400:
        continue
    days.append({"name": os.path.basename(fp)[-12:-4], "ex": ex_adj, "ok": ok_a,
                 "mt5_ms": mt5_ms, "okx_ms": okx_ms, "n": len(ex_adj)})

if not days:
    raise SystemExit("no usable paired data")

print("%-10s %7s %9s  %s" % ("day", "samples", "median dt", "timestamp offset OKX-MT5"))
for D in days:
    dt = np.median(np.diff(D["mt5_ms"])) / 1000.0
    off = np.median(D["okx_ms"] - D["mt5_ms"]) / 1000.0
    print("%-10s %7d %8.2fs  %+.2fs" % (D["name"], D["n"], dt, off))

# ---------------------------------------------------------------- 1 lead/lag on CHANGES
print("\n1. CROSS-CORRELATION OF CHANGES (positive lag = OKX leads Exness)")
print("%-10s %s" % ("day", "  ".join("%+d" % L for L in range(-MAX_LAG, MAX_LAG + 1))))
print("-" * 92)
peaks = []
for D in days:
    dex, dok = np.diff(D["ex"]), np.diff(D["ok"])
    cut = int(len(dex) * (1 - HOLDOUT_FRAC))
    dex, dok = dex[:cut], dok[:cut]                 # development portion only
    row, best, bl = [], -9, 0
    for L in range(-MAX_LAG, MAX_LAG + 1):
        if L >= 0:
            a, b = dok[:len(dok) - L], dex[L:]
        else:
            a, b = dok[-L:], dex[:len(dex) + L]
        n = min(len(a), len(b))
        r = np.corrcoef(a[:n], b[:n])[0, 1] if n > 50 else np.nan
        row.append(r)
        if np.isfinite(r) and r > best:
            best, bl = r, L
    peaks.append(bl)
    print("%-10s %s" % (D["name"], "  ".join("%+.2f" % x if np.isfinite(x) else "  -  "
                                             for x in row)))
print("-" * 92)
print("peak lag per day: %s   %s"
      % (peaks, "AGREE" if len(set(peaks)) == 1 else "DISAGREE - no stable lead"))

# ---------------------------------------------------------------- 2 the economic test
print("\n2. CONDITIONAL RESPONSE - given OKX has already moved, what does Exness do next?")
print("   (dollars; entry at the NEXT sample, so the first move is not capturable)")
print("%-10s %-8s %7s %10s %10s %10s  %s"
      % ("day", "OKX move", "n", "Exness +1", "cum +3", "cum +6", "beats $%.0f?" % (SPREAD + 2 * SLIP)))
print("-" * 92)
NEED = SPREAD + 2 * SLIP
verdict_rows = []
for D in days:
    dex, dok = np.diff(D["ex"]), np.diff(D["ok"])
    cut = int(len(dex) * (1 - HOLDOUT_FRAC))
    for label, lo_, hi_ in (("> $10", 10, 1e9), ("> $25", 25, 1e9)):
        sel = np.where((np.abs(dok[:cut]) >= lo_) & (np.abs(dok[:cut]) < hi_))[0]
        sel = sel[sel + 7 < cut]
        if len(sel) < 25:
            print("%-10s %-8s %7d  (too few)" % (D["name"], label, len(sel))); continue
        sgn = np.sign(dok[sel])
        nxt = np.array([sgn[k] * dex[i + 1] for k, i in enumerate(sel)])
        c3 = np.array([sgn[k] * dex[i + 1:i + 4].sum() for k, i in enumerate(sel)])
        c6 = np.array([sgn[k] * dex[i + 1:i + 7].sum() for k, i in enumerate(sel)])
        ok_ = "YES" if c6.mean() > NEED else "no"
        verdict_rows.append((D["name"], label, c6.mean(), ok_))
        print("%-10s %-8s %7d %10.2f %10.2f %10.2f  %s  (2SE %.2f)"
              % (D["name"], label, len(sel), nxt.mean(), c3.mean(), c6.mean(), ok_,
                 2 * c6.std() / math.sqrt(len(c6))))

# ---------------------------------------------------------------- 3 holdout
print("\n3. HOLDOUT (final %.0f%% of each day, untouched until now)" % (HOLDOUT_FRAC * 100))
print("%-10s %-8s %7s %10s  %s" % ("day", "OKX move", "n", "cum +6", "beats $%.0f?" % NEED))
print("-" * 92)
for D in days:
    dex, dok = np.diff(D["ex"]), np.diff(D["ok"])
    cut = int(len(dex) * (1 - HOLDOUT_FRAC))
    sel = np.where(np.abs(dok[cut:]) >= 10)[0] + cut
    sel = sel[sel + 7 < len(dex)]
    if len(sel) < 15:
        print("%-10s %-8s %7d  (too few)" % (D["name"], "> $10", len(sel))); continue
    sgn = np.sign(dok[sel])
    c6 = np.array([sgn[k] * dex[i + 1:i + 7].sum() for k, i in enumerate(sel)])
    print("%-10s %-8s %7d %10.2f  %s" % (D["name"], "> $10", len(sel), c6.mean(),
                                         "YES" if c6.mean() > NEED else "no"))

print("""
VERDICT REQUIRES ALL FOUR:
  1 technically present   a consistent positive peak lag on every day
  2 economically real     the capturable move exceeds $%.0f - spread plus slippage both
                          ways - by a clear margin, not by cents
  3 stable                same sign and rough size on every recorded day and in holdout
  4 executable            the move must persist for longer than the round trip from this
                          VPS through MT5 to an Exness fill, and survive rejected fills
Failing any one closes the hypothesis.""" % NEED)
