"""quick.py (2026-10-30, owner: "start a owl version 2 ... quick test it, do all possible variations").

The lab harness (live/lab/harness.py, same structure engine as the bot) run on the saved M1 archive, month by month,
fresh each month like the full simulator. Prints net per month and per week. Bar-level, so it is a SCREEN: a variation
must also pass the full tick simulator (study/botsim) before anyone believes it.

    python study/owl_v2/quick.py '{"rr": 1.0}' [--pkg valere] [--months 2026-01,2026-02]
"""
import json, os, sys, time
from datetime import datetime, timezone
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
ROOT = os.path.dirname(STUDY)
sys.path.insert(0, os.path.join(ROOT, "live", "lab"))
_argv = sys.argv[1:]
import harness as H                                           # noqa: E402  (harness resets sys.argv)

MONTHS = ["2026-%02d" % m for m in range(1, 11)]


def month_bars(ym, warm_days=3):
    """that month's M1 bars plus a few days before it (the structure needs history), and the index where the month starts"""
    y, m = map(int, ym.split("-"))
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    parts = []
    for k in ("%d-%02d" % (py, pm), ym):
        p = os.path.join(STUDY, "ticks_archive_BTCUSD", "bars_%s.npz" % k)
        if os.path.exists(p):
            parts.append(np.load(p)["R"])
    if ym == "2026-10" and not os.path.exists(os.path.join(STUDY, "ticks_archive_BTCUSD", "bars_2026-10.npz")):
        R = np.load(os.path.join(STUDY, "bars_u224016179.npz"))["R"]
        parts.append(R)
    R = np.concatenate(parts) if len(parts) > 1 else parts[0]
    R = R[np.unique(R["time"], return_index=True)[1]]
    t0 = datetime(y, m, 1, tzinfo=timezone.utc).timestamp()
    t1 = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc).timestamp()
    R = R[(R["time"] >= t0 - warm_days * 86400) & (R["time"] < t1)]
    return R, int(np.searchsorted(R["time"], t0))


def run_month(ym, cfg):
    R, i0 = month_bars(ym)
    spread = float(np.median(R["spread"][i0:])) * 0.01
    c = dict(cfg)
    c["trade_from"] = int(R["time"][i0])               # warm-up days build the structure, no entries before the month
    out = H.simulate(R, spread, c)
    return out, spread


def weeks(curve):
    """net per ISO week from the dated daily curve"""
    W, prev = {}, 0.0
    for d, v in curve:
        wk = datetime.strptime(d, "%Y-%m-%d").strftime("%G-W%V")
        W[wk] = W.get(wk, 0.0) + (v - prev)
        prev = v
    return W


def main():
    over = json.loads(_argv[0]) if _argv and _argv[0].startswith("{") else {}
    pkg = _argv[_argv.index("--pkg") + 1] if "--pkg" in _argv else "valere"
    months = _argv[_argv.index("--months") + 1].split(",") if "--months" in _argv else MONTHS
    cfg = H.package_cfg(pkg, over)
    cfg["balance"] = 200.0
    res = []
    for ym in months:
        t = time.time()
        o, sp = run_month(ym, cfg)
        W = weeks(o["curve"])
        res.append({"month": ym, "net": o["net"], "trades": o["trades"], "wr": o["wr"], "worst": o["worst_debt"],
                    "spread": sp, "weeks": {k: round(v, 2) for k, v in W.items()}})
        print("%s net %+8.2f  trades %4d  win %5.1f%%  worst %7.2f  spread %.1f  weeks+ %d/%d  (%.0fs)" % (
            ym, o["net"], o["trades"], o["wr"], o["worst_debt"], sp, sum(v > 0 for v in W.values()), len(W), time.time() - t), flush=True)
    tot = sum(r["net"] for r in res)
    print("TOTAL %+.2f  months+ %d/%d" % (tot, sum(r["net"] > 0 for r in res), len(res)))
    tag = _argv[_argv.index("--tag") + 1] if "--tag" in _argv else None
    if tag:
        json.dump({"over": over, "pkg": pkg, "res": res}, open(os.path.join(HERE, "q_%s.json" % tag), "w"), indent=1)


if __name__ == "__main__":
    main()
