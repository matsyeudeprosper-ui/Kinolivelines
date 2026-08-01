"""Q4, as preregistered: does VRP identify regimes where trend or mean-reversion differ?

This was frozen in PREREGISTRATION_dvol.md and then omitted from the first run - an
error, not a result. It is completed here on its own, with the frozen definitions
unchanged and no reference to the stop-calibration question, which is separate work.

FROZEN RULE, quoted from the preregistration:
    "Passes only if the momentum-versus-fade difference flips sign or differs by >2SE
     between high and low VRP, on both instruments, in development and holdout. A
     difference visible on one instrument is that instrument's history."

DEFINITIONS, all carried over unchanged:
    VRP        DVOL(t) - RV_trailing(t), ex-ante, known at entry
    rank       trailing 720-hour percentile of VRP
    high/low   rank >= 95% / rank <= 5%  - the frozen extreme thresholds
    horizons   4h, 24h, 72h
    costs      BTCUSDm $10 spread + $2/side; ETH $1.00 + $0.20/side
    holdout    2025-08-01 onward
    entry      the hourly close after the signal hour closes

MOMENTUM is a trade in the direction of the prior h-hour move; FADE is its mirror. Their
difference is measured inside each VRP regime, and the question is whether that difference
itself changes between regimes. Windows do not overlap and every phase is used.

A median split is also printed as a supplementary view because the 5% tails are thin, but
it is NOT the preregistered test and cannot be used to claim a pass.
"""
import os, math
import numpy as np, pandas as pd

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
RANK_W, TOPQ = 720, 0.05
HORIZONS = [("4h", 4), ("24h", 24), ("72h", 72)]
HOLDOUT = pd.Timestamp("2025-08-01")
COSTS = {"BTC": (10.0, 2.0), "ETH": (1.0, 0.2)}
ANN = math.sqrt(24 * 365)


def trank(v, w=RANK_W):
    out = np.full(len(v), np.nan)
    g = np.where(np.isfinite(v), v, np.nanmedian(v))
    win = np.lib.stride_tricks.sliding_window_view(g, w)[:-1]
    out[w:] = (win < g[w:, None]).mean(axis=1)
    return out


def build(ccy):
    px = pd.read_csv(os.path.join(DATA, "hist_%s_PERPETUAL.csv" % ccy))
    dv = pd.read_csv(os.path.join(DATA, "dvol_%s.csv" % ccy))
    d = px.merge(dv[["ts", "close"]].rename(columns={"close": "dvol"}), on="ts")
    d = d.sort_values("ts").reset_index(drop=True)
    d["t"] = pd.to_datetime(d["ts"], unit="ms")
    cl = d["close"].to_numpy(float)
    lc = np.log(cl)
    ret = np.diff(lc, prepend=lc[0])
    rv = pd.Series(ret).rolling(RANK_W).std().to_numpy() * ANN * 100
    hi, lo = d["high"].to_numpy(float), d["low"].to_numpy(float)
    pc = np.roll(cl, 1); pc[0] = cl[0]
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - pc), np.abs(lo - pc)))
    c = np.cumsum(tr)
    atr = np.full(len(cl), np.nan)
    atr[14:] = (c[14:] - np.concatenate(([0], c[:-15]))) / 14
    vrp = d["dvol"].to_numpy(float) - rv
    return d, cl, lc, atr, vrp


def mom_minus_fade(cl, lc, atr, idx, h, spread, slip):
    """Mean net return of momentum minus that of fade, over non-overlapping entries."""
    vals = []
    seq, busy = [], -1
    for i in idx:
        if i > busy:
            seq.append(int(i)); busy = i + h
    for i in seq:
        if i + h >= len(cl) or i - h < 0 or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        s = np.sign(lc[i] - lc[i - h])
        if s == 0:
            continue
        mom = (s * (cl[i + h] - cl[i]) - spread - 2 * slip) / atr[i]
        fad = (-s * (cl[i + h] - cl[i]) - spread - 2 * slip) / atr[i]
        vals.append(mom - fad)
    if len(vals) < 40:
        return None
    a = np.array(vals)
    return a.mean(), 2 * a.std() / math.sqrt(len(a)), len(a)


print("Q4 - DOES VRP IDENTIFY DIFFERENT TREND / MEAN-REVERSION REGIMES?")
print("preregistered thresholds: high VRP = rank >= 95%, low VRP = rank <= 5%\n")

for split_name, hi_fn, lo_fn, tag in (
        ("PREREGISTERED (5% tails)", lambda r: r >= 1 - TOPQ, lambda r: r <= TOPQ, True),
        ("supplementary (median)", lambda r: r >= 0.5, lambda r: r < 0.5, False)):
    print("=" * 96)
    print("%s" % split_name + ("" if tag else "   [NOT the frozen test - context only]"))
    for ccy in ("BTC", "ETH"):
        d, cl, lc, atr, vrp = build(ccy)
        spread, slip = COSTS[ccy]
        pr = trank(vrp)
        hol = (d["t"] >= HOLDOUT).to_numpy()
        print("\n  %s" % ccy)
        print("    %-12s %-6s %9s %11s %9s %11s   %s"
              % ("period", "horiz", "n high", "high VRP", "n low", "low VRP", "difference"))
        for period, pm in (("development", ~hol), ("holdout", hol)):
            base = np.where(np.isfinite(atr) & (atr > 0) & np.isfinite(pr) & pm)[0]
            base = base[(base > RANK_W) & (base < len(cl) - 80)]
            if len(base) < 500:
                continue
            for hname, h in HORIZONS:
                hg = base[hi_fn(pr[base])]
                lg = base[lo_fn(pr[base])]
                a = mom_minus_fade(cl, lc, atr, hg, h, spread, slip)
                b = mom_minus_fade(cl, lc, atr, lg, h, spread, slip)
                if not a or not b:
                    continue
                diff = a[0] - b[0]
                two = math.sqrt(a[1] ** 2 + b[1] ** 2)
                flips = (a[0] > 0) != (b[0] > 0)
                mark = "  <== differs" if abs(diff) > two else ("  (flips sign)" if flips else "")
                print("    %-12s %-6s %9d %+11.4f %9d %+11.4f   %+.4f (2SE %.4f)%s"
                      % (period, hname, a[2], a[0], b[2], b[0], diff, two, mark))
    print()

print("""
The frozen rule needs the SAME horizon to differ on BOTH instruments in BOTH periods.
A cell that differs in development on one instrument is what testing twelve cells
produces by chance, and the earlier Q1 result is the cautionary example: two cells crossed
2SE at different horizons on different instruments and neither survived holdout.""")
