"""Q2 CORRECTED: does DVOL beat trailing RV out-of-sample, with honest uncertainty?

The first attempt claimed DVOL "passes decisively" on an in-sample R2 rise from 0.3307
to 0.4245 with n=45,502. That claim was wrong on three counts, all of which mattered:

  1 THE SAMPLE WAS NOT 45,502. The target is realised volatility over the following 720
    hours, so consecutive targets share 719 of those 720 hours. The genuinely independent
    count is closer to 46,947/720 = 65 windows across the entire history - three orders
    of magnitude smaller than reported.

  2 THE R2 WAS IN-SAMPLE. Adding any predictor raises in-sample fit; that is arithmetic,
    not evidence. Nothing was fitted on one period and tested on another.

  3 THERE WAS NO UNCERTAINTY. The preregistration required DVOL to beat trailing RV by
    more than 2SE. The code instead declared success when incremental R2 exceeded 0.01,
    a threshold with no statistical meaning attached.

WHAT THIS DOES INSTEAD
  * fits both models on DEVELOPMENT history only (before 2025-08-01)
  * freezes the coefficients and forecasts the untouched holdout without refitting
  * compares RMSE, MAE and calibration slope on the holdout
  * evaluates on NON-OVERLAPPING 30-day targets, running all 720 phase offsets and
    reporting the distribution rather than one lucky slicing
  * puts an interval on the difference in forecast error with a block bootstrap using
    30-day blocks, so the resampling cannot break the autocorrelation the overlap creates
  * requires the same out-of-sample improvement on ETH

Only if the holdout error falls, on both instruments, with an interval excluding zero,
can Q2 be called validated.
"""
import os, math, random
import numpy as np, pandas as pd

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
RANK_W = 720                       # 30 days of hours
HOLDOUT = pd.Timestamp("2025-08-01")
ANN = math.sqrt(24 * 365)
N_BOOT = 2000
rng = np.random.default_rng(515)


def build(ccy):
    px = pd.read_csv(os.path.join(DATA, "hist_%s_PERPETUAL.csv" % ccy))
    dv = pd.read_csv(os.path.join(DATA, "dvol_%s.csv" % ccy))
    d = px.merge(dv[["ts", "close"]].rename(columns={"close": "dvol"}), on="ts")
    d = d.sort_values("ts").reset_index(drop=True)
    d["t"] = pd.to_datetime(d["ts"], unit="ms")
    lc = np.log(d["close"].to_numpy(float))
    ret = np.diff(lc, prepend=lc[0])
    s = pd.Series(ret)
    rv_trail = s.rolling(RANK_W).std().to_numpy() * ANN * 100
    # forward realised vol over the NEXT 720 hours, aligned to the decision time
    rv_fwd = s.shift(-RANK_W).rolling(RANK_W).std().to_numpy() * ANN * 100
    return d, rv_trail, rv_fwd, d["dvol"].to_numpy(float)


def fit(X, y):
    A = np.column_stack([np.ones(len(y))] + X)
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta


def predict(beta, X):
    A = np.column_stack([np.ones(len(X[0]))] + X)
    return A @ beta


for ccy in ("BTC", "ETH"):
    d, rvt, rvf, dvol = build(ccy)
    ok = np.isfinite(rvt) & np.isfinite(rvf) & np.isfinite(dvol)
    dev = ok & (d["t"] < HOLDOUT).to_numpy()
    hol = ok & (d["t"] >= HOLDOUT).to_numpy()

    print("=" * 96)
    print("%s   development %s hours   holdout %s hours"
          % (ccy, f"{int(dev.sum()):,}", f"{int(hol.sum()):,}"))
    print("   independent 30-day windows:  development ~%d   holdout ~%d"
          % (dev.sum() // RANK_W, hol.sum() // RANK_W))
    if hol.sum() < RANK_W * 3:
        print("   holdout holds fewer than 3 independent windows - cannot validate")
        continue

    # ---- fit on development ONLY, freeze, forecast holdout ----
    b1 = fit([rvt[dev]], rvf[dev])
    b2 = fit([rvt[dev], dvol[dev]], rvf[dev])
    print("   frozen coefficients:  RV-only  const %+.2f  rv %+.3f" % (b1[0], b1[1]))
    print("                         RV+DVOL  const %+.2f  rv %+.3f  dvol %+.3f"
          % (b2[0], b2[1], b2[2]))

    yh = rvf[hol]
    p1 = predict(b1, [rvt[hol]])
    p2 = predict(b2, [rvt[hol], dvol[hol]])
    e1, e2 = yh - p1, yh - p2

    def rmse(e): return float(np.sqrt(np.mean(e ** 2)))
    def mae(e):  return float(np.mean(np.abs(e)))

    print("\n   HOLDOUT forecast error (all hours, overlapping - shown for reference only)")
    print("     RMSE   RV-only %7.3f   RV+DVOL %7.3f   change %+.3f"
          % (rmse(e1), rmse(e2), rmse(e2) - rmse(e1)))
    print("     MAE    RV-only %7.3f   RV+DVOL %7.3f   change %+.3f"
          % (mae(e1), mae(e2), mae(e2) - mae(e1)))
    for nm, p in (("RV-only", p1), ("RV+DVOL", p2)):
        sl = np.polyfit(p, yh, 1)[0]
        print("     calibration slope %-8s %.3f  (1.00 is perfect)" % (nm, sl))

    # ---- non-overlapping evaluation across every phase offset ----
    idx = np.where(hol)[0]
    diffs_rmse, diffs_mae, helped = [], [], 0
    phases = 0
    for ph in range(RANK_W):
        sub = idx[ph::RANK_W]
        if len(sub) < 4:
            continue
        phases += 1
        a = rvf[sub] - predict(b1, [rvt[sub]])
        b = rvf[sub] - predict(b2, [rvt[sub], dvol[sub]])
        dr = rmse(b) - rmse(a)
        diffs_rmse.append(dr); diffs_mae.append(mae(b) - mae(a))
        helped += 1 if dr < 0 else 0
    if phases:
        dr = np.array(diffs_rmse)
        print("\n   NON-OVERLAPPING, all %d phase offsets (~%d windows each)"
              % (phases, len(idx) // RANK_W))
        print("     mean RMSE change %+.4f   median %+.4f   worst %+.4f   best %+.4f"
              % (dr.mean(), np.median(dr), dr.max(), dr.min()))
        print("     DVOL lowered RMSE in %d of %d phases (%.0f%%)"
              % (helped, phases, 100 * helped / phases))

    # ---- block bootstrap, 30-day blocks ----
    nb = max(len(idx) // RANK_W, 2)
    starts = np.arange(0, len(idx) - RANK_W, max(RANK_W // 4, 1))
    boots = []
    for _ in range(N_BOOT):
        pick = rng.choice(starts, size=nb, replace=True)
        sel = np.concatenate([idx[s:s + RANK_W] for s in pick])
        a = rvf[sel] - predict(b1, [rvt[sel]])
        b = rvf[sel] - predict(b2, [rvt[sel], dvol[sel]])
        boots.append(rmse(b) - rmse(a))
    boots = np.array(boots)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print("\n   BLOCK BOOTSTRAP (30-day blocks, %d draws)" % N_BOOT)
    print("     RMSE change  mean %+.4f   95%% interval [%+.4f, %+.4f]" % (boots.mean(), lo, hi))
    verdict = ("DVOL IMPROVES the forecast out-of-sample" if hi < 0 else
               "DVOL WORSENS it out-of-sample" if lo > 0 else
               "no out-of-sample improvement distinguishable from zero")
    print("     -> %s" % verdict)
    print()

print("""
Q2 is validated only if the holdout RMSE falls on BOTH instruments with a bootstrap
interval excluding zero, and the phase distribution agrees. A fall on one instrument, or
an interval spanning zero, means the in-sample R2 rise was the arithmetic of adding a
predictor and nothing more.

Note the independent-window counts printed at the top. They are the real sample size for
a 30-day forecast target, and they are small - which is itself the finding if the
intervals come out wide.""")
