"""E025 - Trading AGAINST the higher timeframes: does it cost more when it
loses?

WHY THIS IS NOT E012 AGAIN. E012 (2026-09-12) closed higher-timeframe
alignment as an ENTRY filter: it does not predict whether a trade reaches
its target or its stop (regression AUC 0.569 train, 0.499 test, 0.504 V2).
That is a question about the DIRECTION of the outcome, and it is closed. It
never asked about the SIZE of the loss. That is the shape the crowding
result took on this desk: not an entry rule, a risk rule.

PRE-REGISTERED QUESTION, one only:
    Among LOSING trades, is the loss bigger when the trade direction
    opposes the majority of M15/H1/H4?

Decided before looking:
  - measure   : median and p95 of the loss, in points of adverse move, and
                in money, split by ALIGNED vs AGAINST.
  - control   : 200 shuffles of the aligned/against label over the same
                trades. A real gap must beat the 95th percentile of the
                shuffles, or it is noise.
  - halves    : the gap must hold in BOTH halves of the period, same sign.
  - verdict   : A only if control AND both halves agree. Otherwise C.
  - no tuning : if it fails, it is closed. No second cut, no other split.

HOW THE HIGHER TIMEFRAMES ARE BUILT. From the same M1 bars the simulation
runs on, resampled to M15/H1/H4, each fed to structure_bos_bot.Struct - the
engine the bot itself uses. A candle only enters its timeframe once it has
CLOSED, so the trend known at a trade's entry minute is the trend a live bot
could have known. No lookahead.

Run:  python review/htf_risk.py
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(os.path.dirname(HERE), "live")
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(LIVE, "lab"))

import harness as H            # noqa: E402
import structure_bos_bot as B  # noqa: E402

TFS = (("M15", 900), ("H1", 3600), ("H4", 14400))
SEED = 20260930
DRAWS = 200


def htf_trend_series(R, secs):
    """trend of one higher timeframe at every M1 bar, completed candles
    only. Returns a list the same length as R."""
    eng = B.Struct()
    out = [0] * len(R)
    cur = None          # the candle being built: [t0, o, h, l, c]
    trend = 0
    for i, r in enumerate(R):
        t = int(r["time"])
        slot = t - (t % secs)
        if cur is None:
            cur = [slot, float(r["open"]), float(r["high"]),
                   float(r["low"]), float(r["close"])]
        elif slot != cur[0]:
            # the previous candle has CLOSED - only now may the engine see it
            eng.step(cur[0], cur[1], cur[2], cur[3], cur[4])
            trend = int(getattr(eng, "trend", 0) or 0)
            cur = [slot, float(r["open"]), float(r["high"]),
                   float(r["low"]), float(r["close"])]
        else:
            cur[2] = max(cur[2], float(r["high"]))
            cur[3] = min(cur[3], float(r["low"]))
            cur[4] = float(r["close"])
        out[i] = trend
    return out


def pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    k = min(len(s) - 1, max(0, int(round((len(s) - 1) * q))))
    return s[k]


def med(xs):
    return pct(xs, 0.5)


def split_gap(rows, key):
    """median loss of AGAINST minus median loss of ALIGNED (positive = the
    against side loses more)."""
    ag = [r[key] for r in rows if r["against"]]
    al = [r[key] for r in rows if not r["against"]]
    if len(ag) < 8 or len(al) < 8:
        return None, len(ag), len(al)
    return med(ag) - med(al), len(ag), len(al)


def main():
    print("E025 higher-timeframe risk - loading bars...")
    sym, R = H.bars_long()
    if R is None or not len(R):
        print("no bars from MT5 - is a terminal running?")
        return 2
    print(f"{sym}: {len(R)} M1 bars "
          f"{H.datetime.utcfromtimestamp(int(R[0]['time'])):%Y-%m-%d} -> "
          f"{H.datetime.utcfromtimestamp(int(R[-1]['time'])):%Y-%m-%d}")

    print("building the higher timeframes with the bot's own engine...")
    series = {}
    for name, secs in TFS:
        series[name] = htf_trend_series(R, secs)
        n_up = sum(1 for v in series[name] if v == 1)
        n_dn = sum(1 for v in series[name] if v == -1)
        print(f"  {name}: up {n_up/len(R)*100:.0f}%  down {n_dn/len(R)*100:.0f}%"
              f"  flat {100-(n_up+n_dn)/len(R)*100:.0f}%")

    # the trades: one real account's own deployed rules, not a generic one
    cfg = H.package_cfg("valere")
    H.TRACE = []
    H.simulate(R, 7.0, cfg)
    tr = H.TRACE
    H.TRACE = None
    print(f"trades simulated: {len(tr)}")

    at = {int(r["time"]): i for i, r in enumerate(R)}
    rows = []
    for x in tr:
        i = at.get(int(x["t"]))
        if i is None or x.get("pnl") is None:
            continue
        v = [series[n][i] for n, _ in TFS]
        up, dn = v.count(1), v.count(-1)
        maj = 1 if up > dn else (-1 if dn > up else 0)
        if maj == 0:
            continue                      # no majority: not this question
        rows.append({"t": x["t"], "d": x["d"], "pnl": x["pnl"],
                     "dist": x["dist"], "win": x["win"],
                     "against": (x["d"] != maj),
                     "loss": max(0.0, -x["pnl"])})

    losses = [r for r in rows if not r["win"]]
    print(f"with a higher-timeframe majority: {len(rows)} trades, "
          f"{len(losses)} losing")
    if len(losses) < 40:
        print("VERDICT C - not enough losing trades to answer this. "
              "Closed, no second cut.")
        return 0

    gap, n_ag, n_al = split_gap(losses, "loss")
    if gap is None:
        print(f"VERDICT C - one side too small (against {n_ag}, aligned {n_al}).")
        return 0
    m_ag = med([r["loss"] for r in losses if r["against"]])
    m_al = med([r["loss"] for r in losses if not r["against"]])
    p_ag = pct([r["loss"] for r in losses if r["against"]], 0.95)
    p_al = pct([r["loss"] for r in losses if not r["against"]], 0.95)
    print("")
    print("LOSING TRADES ONLY")
    print(f"  against the big picture : n {n_ag:4d}  median ${m_ag:5.2f}  p95 ${p_ag:5.2f}")
    print(f"  aligned with it         : n {n_al:4d}  median ${m_al:5.2f}  p95 ${p_al:5.2f}")
    print(f"  gap (against - aligned) : ${gap:+.2f}")

    # ---- control: the same trades, the label shuffled ------------------
    rnd = random.Random(SEED)
    labels = [r["against"] for r in losses]
    vals = [r["loss"] for r in losses]
    draws = []
    for _ in range(DRAWS):
        rnd.shuffle(labels)
        a = [v for v, L in zip(vals, labels) if L]
        b = [v for v, L in zip(vals, labels) if not L]
        if len(a) < 8 or len(b) < 8:
            continue
        draws.append(med(a) - med(b))
    draws.sort()
    beat = sum(1 for d in draws if d < gap)
    p95 = pct(draws, 0.95)
    print(f"  control {len(draws)} shuffles: p95 ${p95:+.2f}, "
          f"the real gap sits at the {beat/len(draws)*100:.0f}th percentile")

    # ---- both halves ---------------------------------------------------
    losses.sort(key=lambda r: r["t"])
    half = len(losses) // 2
    g1, _, _ = split_gap(losses[:half], "loss")
    g2, _, _ = split_gap(losses[half:], "loss")
    print(f"  first half ${g1 if g1 is None else round(g1,2)}   "
          f"second half ${g2 if g2 is None else round(g2,2)}")

    ok_ctrl = gap > p95
    ok_half = (g1 is not None and g2 is not None and g1 > 0 and g2 > 0)
    vd = "A" if (ok_ctrl and ok_half) else "C"
    print("")
    print(f"VERDICT {vd}  (control {'pass' if ok_ctrl else 'FAIL'}, "
          f"halves {'pass' if ok_half else 'FAIL'})")
    if vd == "C":
        print("Closed. Alignment does not size the loss either. "
              "Do not re-propose it on this engine without new data.")
    else:
        print("A risk rule is worth building: smaller stake when the minute "
              "fights the big picture. NOT an entry filter - E012 closed that.")

    out = {"engine": H.ENGINE, "symbol": sym, "bars": len(R),
           "trades": len(rows), "losses": len(losses),
           "median_against": m_ag, "median_aligned": m_al,
           "p95_against": p_ag, "p95_aligned": p_al,
           "gap": gap, "control_p95": p95,
           "control_pctile": beat / max(1, len(draws)) * 100,
           "half1": g1, "half2": g2, "verdict": vd}
    with open(os.path.join(HERE, "htf_risk.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("written: review/htf_risk.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
