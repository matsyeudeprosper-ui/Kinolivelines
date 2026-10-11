"""scanner_research.py - GPT review of b8aea4d (2026-10-11), items 1-2.

For each candidate (primary USTEC, XAUUSD; secondary US30, US500; BTCUSD as reference):
  * the scanner's bar-close backtest (model v2-robot-struct, live/owl_scanner.backtest) on
    the last 30 CALENDAR days and on the 30 days before that;
  * equal calendar halves of each window (trades split by entry time);
  * a MATCHED random-entry control: for every real trade, a random bar of the same
    window (market open), same direction, same stop distance in price, same 0.8 RR,
    same entry convention (bar close, + bar spread for a buy) and the same M1 exit rule
    (stop and target on one bar = loss). N_REPS replications -> where the real
    expectancy sits in the random distribution;
  * expectancy (avg R), sum R, max drawdown in R (closed-trade curve), cost (bar spread
    / risk, in R), signals and why they were not taken, data gaps.
  * hourly-return correlation between the candidates (diversification among them).

Read only. Writes study/results/scanner_research_2026-10-11.json.
    python study/scanner_research.py
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(os.path.dirname(HERE), "live")
sys.path.insert(0, LIVE)
sys.argv = ["scanner_research"]
import owl_scanner as S          # noqa: E402
import MetaTrader5 as mt5        # noqa: E402

CANDS = [("USTEC", "primary"), ("XAUUSD", "primary"), ("US30", "secondary"), ("US500", "secondary"),
         ("BTCUSD", "reference")]
N_REPS = 1000
HORIZON = 5 * 1440              # a random trade still open after 5 days of bars is closed at market
RNG = np.random.default_rng(7)
OUT = os.path.join(HERE, "results", "scanner_research_2026-10-11.json")


def metrics(trs):
    if not trs:
        return {"n": 0}
    r = np.array([t["r"] for t in trs], dtype=float)
    cum = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    dd = float(np.max(peak - cum)) if len(cum) else 0.0
    cost = np.array([(t.get("spread") or 0.0) / t["risk"] for t in trs if t.get("risk")], dtype=float)
    w = r[r > 0]
    gl = -r[r <= 0].sum()
    return {"n": int(len(r)), "wr": round(float((r > 0).mean() * 100), 1), "avg_r": round(float(r.mean()), 3),
            "sum_r": round(float(r.sum()), 2), "max_dd_r": round(dd, 2),
            "pf": round(float(w.sum() / gl), 2) if gl > 0 else None,
            "cost_r": round(float(cost.mean()), 3) if len(cost) else None,
            "both_on_bar": int(sum(1 for t in trs if t.get("both")))}


def random_control(trs, R, k0, k1, point):
    """matched random entries; returns the distribution of avg R and the real's percentile"""
    if not trs:
        return None
    hi = R["high"].astype(float); lo = R["low"].astype(float); cl = R["close"].astype(float)
    sp = R["spread"].astype(float) * point
    n = len(R)
    picks = np.arange(k0, k1 - 2)
    means = np.empty(N_REPS)
    for rep in range(N_REPS):
        res = []
        starts = RNG.choice(picks, size=len(trs))
        for t, i in zip(trs, starts):
            d, risk = t["d"], t["risk"]
            e = cl[i] + (sp[i] if d == 1 else 0.0)
            sl = e - d * risk
            tp = e + d * 0.8 * risk
            j1 = min(n, i + 1 + HORIZON)
            h = hi[i + 1:j1]; l = lo[i + 1:j1]; s = sp[i + 1:j1]
            if d == 1:
                hs = l <= sl; ht = h >= tp
            else:
                hs = h + s >= sl; ht = l + s <= tp
            any_ = hs | ht
            if not any_.any():
                x = cl[j1 - 1] if d == 1 else cl[j1 - 1] + sp[j1 - 1]
                res.append(d * (x - e) / risk)
                continue
            f = int(np.argmax(any_))
            res.append(-1.0 if hs[f] else 0.8)
        means[rep] = np.mean(res)
    real = float(np.mean([t["r"] for t in trs]))
    return {"reps": N_REPS, "real_avg_r": round(real, 3), "random_mean": round(float(means.mean()), 3),
            "random_p05": round(float(np.percentile(means, 5)), 3), "random_p95": round(float(np.percentile(means, 95)), 3),
            "real_percentile": round(float((means < real).mean() * 100), 1)}


def gaps(R, k0, k1):
    t = R["time"][k0:k1].astype(np.int64)
    dt = np.diff(t)
    return {"bars": int(k1 - k0), "gaps_over_5min": int((dt > 300).sum()), "largest_gap_h": round(float(dt.max() / 3600), 1) if len(dt) else None}


def run():
    t_start = time.time()
    S.bot()
    if not mt5.initialize(path=S.TERMINAL):
        raise SystemExit(mt5.last_error())
    out = {"built": int(time.time()), "model": "v2-robot-struct bar-close backtest", "n_reps": N_REPS, "symbols": {}}
    for sym, role in CANDS:
        row = {"role": role}
        for label, end_ago in (("last_30d", 0.0), ("prev_30d", 30.0)):
            b = S.backtest(sym, 30.0, end_ago=end_ago, save=False)
            if b.get("err"):
                row[label] = {"err": b["err"]}
                continue
            R, k0, k1, point = b.pop("_R")
            trs = b["trades"]
            mid = b["from"] + (b["to"] - b["from"]) / 2
            row[label] = {"from": b["from"], "to": b["to"], "signals": b["signals"], "not_taken": b["refused"],
                          "all": metrics(trs), "half_1": metrics([t for t in trs if t["t"] < mid]),
                          "half_2": metrics([t for t in trs if t["t"] >= mid]),
                          "random": random_control(trs, R, k0, k1, point), "data": gaps(R, k0, k1)}
            print(sym, label, row[label]["all"], "random pct", (row[label]["random"] or {}).get("real_percentile"),
                  "%.0fs" % (time.time() - t_start))
            sys.stdout.flush()
        out["symbols"][sym] = row
    # correlation among the candidates (not only with BTC)
    H = {}
    for sym, _ in CANDS:
        Rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 24 * 60)
        H[sym] = {int(r["time"]): float(r["close"]) for r in Rh}
    corr = {}
    names = [s for s, _ in CANDS]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ts = sorted(set(H[a]) & set(H[b]))
            x = np.diff(np.log([H[a][t] for t in ts])); y = np.diff(np.log([H[b][t] for t in ts]))
            g = np.diff(ts) == 3600
            corr[a + "/" + b] = round(float(np.corrcoef(x[g], y[g])[0, 1]), 2)
    out["corr_hourly_60d"] = corr
    out["secs"] = round(time.time() - t_start, 1)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
    print("corr", corr)
    print("done in %.0fs" % out["secs"])
    mt5.shutdown()


if __name__ == "__main__":
    run()
