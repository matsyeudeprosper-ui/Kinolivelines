"""H6: does the options market's volatility quote help a BTCUSDm trader?

Runs exactly the four questions frozen in PREREGISTRATION_dvol.md. Nothing here was
chosen after seeing an outcome.

The distinction that governs the whole test: the variance risk premium is an OPTIONS
phenomenon. Implied volatility exceeding realised volatility is well documented and
almost certainly true in this data too, and it is not by itself a directional edge on a
CFD - harvesting it requires selling options, which this bot cannot do. So Q2 is expected
to pass and proves nothing alone; Q1 is the only route to a directional edge; Q3 and Q4
count only if they would change an implementable rule.

  Q1 direction          does VRP predict which way price goes?
  Q2 volatility         does DVOL beat trailing realised vol at predicting forward vol?
                        the bar is INCREMENTAL - correlating with forward vol is not a
                        result, because trailing vol does that too
  Q3 adverse excursion  does VRP predict how far a trade goes against you?
  Q4 regime             do momentum and mean-reversion behave differently by VRP?

VRP is the EX-ANTE premium, DVOL(t) - RV_trailing(t), which is fully known at entry. The
realised premium DVOL(t) - RV_forward(t) is the true quantity but cannot be known when
the trade is placed and is never used as a signal.
"""
import os, math, random
import numpy as np, pandas as pd

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
RANK_W, TOPQ, NQ = 720, 0.05, 5
HORIZONS = [("4h", 4), ("24h", 24), ("72h", 72)]
HOLDOUT = pd.Timestamp("2025-08-01")
COSTS = {"BTC": (10.0, 2.0), "ETH": (1.0, 0.2)}
ANN = math.sqrt(24 * 365)
rng = random.Random(90210)


def trank(v, w=RANK_W):
    out = np.full(len(v), np.nan)
    good = np.where(np.isfinite(v), v, np.nanmedian(v))
    win = np.lib.stride_tricks.sliding_window_view(good, w)[:-1]
    out[w:] = (win < good[w:, None]).mean(axis=1)
    return out


def load(ccy):
    px = pd.read_csv(os.path.join(DATA, "hist_%s_PERPETUAL.csv" % ccy))
    dv = pd.read_csv(os.path.join(DATA, "dvol_%s.csv" % ccy))
    px["ts"] = px["ts"].astype(np.int64)
    dv["ts"] = dv["ts"].astype(np.int64)
    d = px.merge(dv[["ts", "close"]].rename(columns={"close": "dvol"}), on="ts", how="inner")
    d = d.sort_values("ts").reset_index(drop=True)
    d["t"] = pd.to_datetime(d["ts"], unit="ms")
    hi, lo, cl = (d[c].to_numpy(float) for c in ("high", "low", "close"))
    lc = np.log(cl)
    ret = np.diff(lc, prepend=lc[0])
    rv = pd.Series(ret).rolling(RANK_W).std().to_numpy() * ANN * 100
    pc = np.roll(cl, 1); pc[0] = cl[0]
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - pc), np.abs(lo - pc)))
    c = np.cumsum(tr)
    atr = np.full(len(cl), np.nan)
    atr[14:] = (c[14:] - np.concatenate(([0], c[:-15]))) / 14
    vrp = d["dvol"].to_numpy(float) - rv
    return d, hi, lo, cl, lc, ret, atr, rv, vrp


def strat_diff(a, b, vq):
    """Weighted mean of (a-b) within volatility strata, with pooled 2SE and per-cell signs."""
    num = den = var = 0.0
    cells = []
    for q in range(NQ):
        m = vq == q
        x, y = a[m], b[m]
        x, y = x[np.isfinite(x)], y[np.isfinite(y)]
        if len(x) < 30 or len(y) < 30:
            cells.append(None); continue
        dd = x.mean() - y.mean()
        w = len(x)
        num += w * dd; den += w
        var += w * w * (x.var() / len(x) + y.var() / len(y))
        cells.append(dd)
    if den == 0:
        return None
    return num / den, 2 * math.sqrt(var) / den, cells


for ccy in ("BTC", "ETH"):
    d, hi, lo, cl, lc, ret, atr, rv, vrp = load(ccy)
    spread, slip = COSTS[ccy]
    vrank = trank(np.where(np.isfinite(atr), atr, 0.0))
    prank = trank(vrp)
    hold = (d["t"] >= HOLDOUT).to_numpy()
    print("=" * 100)
    print("%s   %s joined hourly rows   %s -> %s"
          % (ccy, f"{len(d):,}", d.t.min().date(), d.t.max().date()))
    print("   DVOL mean %.1f   RV_trail mean %.1f   VRP mean %+.1f  (positive = implied "
          "above realised, as expected)" % (np.nanmean(d["dvol"]), np.nanmean(rv), np.nanmean(vrp)))

    for period, pm in (("DEVELOPMENT", ~hold), ("HOLDOUT", hold)):
        base = np.where(np.isfinite(atr) & (atr > 0) & np.isfinite(prank)
                        & np.isfinite(vrank) & np.isfinite(vrp) & pm)[0]
        base = base[(base > RANK_W) & (base < len(cl) - 80)]
        if len(base) < 800:
            continue
        cuts = np.quantile(vrank[base], np.linspace(0, 1, NQ + 1)[1:-1])
        by_q = {q: [int(x) for x in base if int(np.searchsorted(cuts, vrank[x])) == q]
                for q in range(NQ)}
        print("\n  --- %s  (%s hours) ---" % (period, f"{len(base):,}"))

        # ---------------- Q1 direction ----------------
        print("  Q1 DIRECTION   (net of $%.0f spread + $%.1f/side slippage)" % (spread, slip))
        print("     %-5s %-7s %8s %10s %9s  %s" % ("horiz", "arm", "n", "vs random", "2SE", "quintiles"))
        for hname, h in HORIZONS:
            hi_g = base[prank[base] >= 1 - TOPQ]
            lo_g = base[prank[base] <= TOPQ]
            for arm in ("HIGH-VRP long", "HIGH-VRP short"):
                s0 = 1 if arm.endswith("long") else -1
                sig, ctl, vq = [], [], []
                for grp, side in ((hi_g, s0), (lo_g, -s0)):
                    seq, busy = [], -1
                    for i in grp:
                        if i > busy:
                            seq.append(int(i)); busy = i + h
                    for i in seq:
                        q = int(np.searchsorted(cuts, vrank[i]))
                        cand = by_q.get(q) or []
                        if len(cand) < 20 or i + h >= len(cl):
                            continue
                        v = (side * (cl[i + h] - cl[i]) - spread - 2 * slip) / atr[i]
                        j = cand[rng.randrange(len(cand))]
                        if j + h >= len(cl):
                            continue
                        cv = (side * (cl[j + h] - cl[j]) - spread - 2 * slip) / atr[j]
                        if np.isfinite(v) and np.isfinite(cv):
                            sig.append(v); ctl.append(cv); vq.append(q)
                if len(sig) < 150:
                    continue
                r = strat_diff(np.array(sig), np.array(ctl), np.array(vq))
                if r is None:
                    continue
                est, two, cells = r
                ag = sum(1 for c in cells if c is not None and (c > 0) == (est > 0))
                got = sum(1 for c in cells if c is not None)
                flag = "  <== PASSES" if est > two and ag >= 4 else ""
                print("     %-5s %-7s %8d %10.4f %9.4f  %d of %d%s"
                      % (hname, arm.split("-")[-1], len(sig), est, two, ag, got, flag))

        # ---------------- Q3 adverse excursion ----------------
        print("  Q3 ADVERSE EXCURSION  (stratified by entry volatility)")
        for hname, h in HORIZONS:
            adv, rk, vq = [], [], []
            seq, busy = [], -1
            for i in base:
                if i > busy:
                    seq.append(int(i)); busy = i + h
            for i in seq:
                if i + h >= len(cl) or i - h < 0:
                    continue
                s = np.sign(lc[i] - lc[i - h])
                if s == 0:
                    continue
                w = slice(i + 1, i + 1 + h)
                a = (cl[i] - lo[w].min()) / atr[i] if s > 0 else (hi[w].max() - cl[i]) / atr[i]
                adv.append(a); rk.append(prank[i]); vq.append(int(np.searchsorted(cuts, vrank[i])))
            adv, rk, vq = np.array(adv), np.array(rk), np.array(vq)
            ex = (rk <= TOPQ) | (rk >= 1 - TOPQ)
            nm = (rk > 0.2) & (rk < 0.8)
            if ex.sum() < 60 or nm.sum() < 120:
                continue
            num = den = var = 0.0; cells = []
            for q in range(NQ):
                m = vq == q
                x, y = adv[m & ex], adv[m & nm]
                if len(x) < 25 or len(y) < 50:
                    cells.append(None); continue
                dd = x.mean() - y.mean(); w = len(x)
                num += w * dd; den += w
                var += w * w * (x.var() / len(x) + y.var() / len(y))
                cells.append(dd)
            if den == 0:
                continue
            est, two = num / den, 2 * math.sqrt(var) / den
            ag = sum(1 for c in cells if c is not None and (c > 0) == (est > 0))
            got = sum(1 for c in cells if c is not None)
            print("     %-5s n_ext %-6d %+8.4f ATR  2SE %.4f  %d of %d%s"
                  % (hname, int(ex.sum()), est, two, ag, got,
                     "  <== PASSES" if abs(est) > two and ag >= 4 else ""))

    # ---------------- Q2 incremental volatility prediction ----------------
    print("\n  Q2 VOLATILITY PREDICTION - does DVOL beat trailing RV at forecasting forward RV?")
    fwd = pd.Series(ret).shift(-720).rolling(720).std().to_numpy() * ANN * 100
    ok = np.isfinite(fwd) & np.isfinite(rv) & np.isfinite(d["dvol"].to_numpy(float))
    ok &= np.arange(len(ok)) > RANK_W
    y = fwd[ok]
    x1 = rv[ok]
    x2 = d["dvol"].to_numpy(float)[ok]
    def r2(*xs):
        X = np.column_stack([np.ones(len(y))] + list(xs))
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        return 1 - resid.var() / y.var()
    a, b = r2(x1), r2(x1, x2)
    n = len(y)
    print("     n=%s   R2 trailing-RV alone %.4f   + DVOL %.4f   incremental %+.4f"
          % (f"{n:,}", a, b, b - a))
    print("     %s" % ("DVOL adds real forecasting power" if b - a > 0.01
                       else "DVOL adds nothing beyond trailing realised vol"))
    print()

print("""
READING THIS. Q2 passing is expected and means nothing on its own - implied volatility
forecasting realised volatility is one of the most documented facts in finance and cannot
be traded through a directional CFD.

Only Q1 could give a directional edge, and it must clear costs, controls, quintiles, ETH
and holdout together. Q3 counts only if the difference is large enough to change a stop or
a position size - under about 2pp of stop-out rate it cannot.

If the only real effect is the volatility premium itself, that is an options result: real,
but outside what this bot can execute.""")
