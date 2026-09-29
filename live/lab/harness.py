"""The lab's replay harness (2026-09-28): ONE simulate() for every what-if.

Same engine as the live bot (structure_bos_bot.Struct), same deployed rules
(awake window, storm line, movement gate, one trade per level, flip + N
continuations in debt, tab/jar bullets), driven by a config dict so the
researcher, the chercheur session and a human can all ask the same
question the same way:

    python lab/harness.py --rr 0.6                # one what-if vs deployed
    python lab/harness.py --wait 20 --ext 500 --json

Verdict rules (fixed, never tuned):
  A  better money in BOTH halves, worst debt not worse
  B  a smaller hole in both halves without losing money, or more money
     overall with one half agreeing
  C  everything else
  =  the change touched fewer than 3 trades / less than $1
"""
import argparse
import bisect
import json
import os
import sys
from datetime import datetime, timezone

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
sys.path.insert(0, LIVE)
_ARGV = sys.argv[1:]
sys.argv = ["harness"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

CFG_BASE = {"rr": 0.8, "n_cont": 1, "wait_min": 0, "ext_pts": 0, "skip_wd": [], "skip_hours": [],
            "size_hot": 1.0, "nerv_gate": False, "storm": 1.85, "bullets": 3, "k_streak": 2, "lot": 0.02,
            "debt_nerv_gate": False}   # built 2026-09-29 on the chercheur's request: still in the red AND nervous
CFG_KEYS = list(CFG_BASE.keys())
BLOT = 0.01


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def cfg_of(over=None):
    c = dict(CFG_BASE)
    for k, v in (over or {}).items():
        if k in CFG_BASE:
            c[k] = v
    return c


def simulate(R, spread, cfg):
    c = cfg_of(cfg)
    rr, LOT = float(c["rr"]), float(c["lot"])
    NB, K = float(c["bullets"]), int(c["k_streak"])
    skip_wd, skip_h = set(c["skip_wd"] or []), set(c["skip_hours"] or [])
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    closes = [float(r["close"]) for r in R]
    flips, marks = [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    run = pk = 0.0
    streak = 0
    curve = []
    day_key = None
    last_flip_t = None
    last_close_t = None
    cont_left = 0
    n_trades = wins = 0
    blocked = 0
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, cl = (float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
        g = datetime.fromtimestamp(t, tz=timezone.utc)
        dk = g.strftime("%Y-%m-%d")
        if dk != day_key:
            day_key = dk
            curve.append(run)
        if pos:
            d, e, sl, tp, dist, mid, hit_mid, lot = pos
            if not hit_mid and ((l <= mid) if d == 1 else (h >= mid)):
                hit_mid = True
                pos = (d, e, sl, tp, dist, mid, hit_mid, lot)
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                pts = (rr * dist - spread) if win else -(dist + spread)
                debt = max(0.0, pk - run)
                run += pts * lot
                fire = debt > 0.5 and streak < K
                if fire and hit_mid and NB > 0:
                    bpts = ((1.3 * dist - spread) if win else -(dist / 2.0 + spread))
                    run += bpts * BLOT * NB
                streak = 0 if win else streak + 1
                wins += 1 if win else 0
                pk = max(pk, run)
                pos = None
                last_close_t = t
        touched = False
        if eng.trend == 1 and eng.prot_lo is not None:
            touched = l <= eng.prot_lo[1] <= cl
        elif eng.trend == -1 and eng.prot_hi is not None:
            touched = cl <= eng.prot_hi[1] <= h
        sig = eng.step(t, o, h, l, cl)
        if eng.trend != prev and eng.trend != 0:
            flips.append(t)
            prev = eng.trend
        if sig is not None:
            marks.append(t)
        if touched and last_flip_t is not None and cont_left < c["n_cont"]:
            cont_left = min(int(c["n_cont"]), cont_left + 1)
        if sig is None or pos:
            continue
        if not any(f > t - B.AWAKE_WIN for f in flips):
            continue
        d, slp = sig
        flip = bool(flips) and flips[-1] == t
        if not flip:
            lvl = eng.hi_v if d == 1 else eng.lo_v
            if (d == 1 and used_hi == lvl) or (d == -1 and used_lo == lvl):
                continue
            if d == 1:
                used_hi = lvl
            else:
                used_lo = lvl
        nv = 1.0
        if i >= 1440:
            nv = (sorted(rng[i-60:i])[30] / max(sorted(rng[i-1440:i])[720], 1e-9))
            mv2 = (bisect.bisect_left(marks, t) - bisect.bisect_left(marks, t - 7200))
            if nv >= float(c["storm"]) or mv2 < 1:
                continue
            if c["nerv_gate"] and nv > 1.0:
                blocked += 1
                continue
            if c["debt_nerv_gate"] and nv > 1.0 and max(0.0, pk - run) > 0.5:
                blocked += 1
                continue
        # ---- the what-if brakes ----
        if c["wait_min"] and last_close_t is not None and t - last_close_t < c["wait_min"] * 60:
            blocked += 1
            continue
        if c["ext_pts"] and i >= 61 and abs(closes[i-1] - closes[i-61]) > c["ext_pts"]:
            blocked += 1
            continue
        if skip_wd and g.weekday() in skip_wd:
            blocked += 1
            continue
        if skip_h and g.hour in skip_h:
            blocked += 1
            continue
        debt_now = max(0.0, pk - run)
        if flip:
            last_flip_t = t
            cont_left = int(c["n_cont"])
        elif debt_now > 0.5:
            if cont_left > 0 and last_flip_t is not None:
                cont_left -= 1
            else:
                continue
        dist = abs(cl - slp)
        lot = LOT * (float(c["size_hot"]) if nv >= 1.0 else 1.0)
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        tp = cl + d * rr * dist
        pos = (d, cl, float(slp), tp, dist, cl - d * dist / 2.0, False, lot)
        n_trades += 1
    dd = pk2 = worst = 0.0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
        worst = max(worst, pk2 - v)
    return {"net": round(run, 2), "maxdd": round(dd, 2), "worst_debt": round(worst, 2), "trades": n_trades,
            "wr": round(wins / n_trades * 100, 1) if n_trades else 0.0, "blocked": blocked}


def run_cfg(R, spread, cfg):
    mid = len(R) // 2
    return {"full": simulate(R, spread, cfg), "h1": simulate(R[:mid], spread, cfg), "h2": simulate(R[mid:], spread, cfg)}


def verdict(v, base):
    f, b = v["full"], base["full"]
    dn = f["net"] - b["net"]
    if abs(f["trades"] - b["trades"]) < 3 and abs(dn) < 1.0 and abs(f["worst_debt"] - b["worst_debt"]) < 1.0:
        return "="
    d1 = v["h1"]["net"] - base["h1"]["net"]
    d2 = v["h2"]["net"] - base["h2"]["net"]
    w = f["worst_debt"] - b["worst_debt"]
    w1 = v["h1"]["worst_debt"] - base["h1"]["worst_debt"]
    w2 = v["h2"]["worst_debt"] - base["h2"]["worst_debt"]
    if d1 > 0 and d2 > 0 and w <= 0.5:
        return "A"
    if (dn >= -0.05 * abs(b["net"]) and w1 < 0 and w2 < 0) or (dn > 0 and (d1 > 0 or d2 > 0) and w <= 0.5):
        return "B"
    return "C"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rr", type=float)
    ap.add_argument("--n-cont", type=int)
    ap.add_argument("--wait", type=int, help="minutes after a close")
    ap.add_argument("--ext", type=float, help="no entry after this many points in the last hour")
    ap.add_argument("--skip-wd", type=str, help="weekdays to skip, 0=Mon..6=Sun, comma list")
    ap.add_argument("--skip-hours", type=str, help="UTC hours to skip, e.g. 0-8 or 0,1,2")
    ap.add_argument("--size-hot", type=float, help="lot multiplier when nervosity >= 1.0")
    ap.add_argument("--nerv-gate", action="store_true")
    ap.add_argument("--debt-nerv-gate", action="store_true", help="refuse only when still in the red AND nervous")
    ap.add_argument("--bullets", type=float)
    ap.add_argument("--k-streak", type=int)
    ap.add_argument("--spread", type=float, default=7.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(_ARGV)
    over = {}
    if a.rr is not None: over["rr"] = a.rr
    if a.n_cont is not None: over["n_cont"] = a.n_cont
    if a.wait is not None: over["wait_min"] = a.wait
    if a.ext is not None: over["ext_pts"] = a.ext
    if a.skip_wd: over["skip_wd"] = [int(x) for x in a.skip_wd.split(",") if x.strip()]
    if a.skip_hours:
        hs = set()
        for part in a.skip_hours.split(","):
            if "-" in part:
                lo, hi = part.split("-"); hs.update(range(int(lo), int(hi)))
            elif part.strip():
                hs.add(int(part))
        over["skip_hours"] = sorted(hs)
    if a.size_hot is not None: over["size_hot"] = a.size_hot
    if a.nerv_gate: over["nerv_gate"] = True
    if a.debt_nerv_gate: over["debt_nerv_gate"] = True
    if a.bullets is not None: over["bullets"] = a.bullets
    if a.k_streak is not None: over["k_streak"] = a.k_streak
    sym, R = bars()
    base = run_cfg(R, a.spread, {})
    v = run_cfg(R, a.spread, over)
    out = {"symbol": sym, "days": round(len(R) / 1440, 1), "spread": a.spread, "cfg": cfg_of(over),
           "base": base, "variant": v, "verdict": verdict(v, base)}
    if a.json:
        print(json.dumps(out))
    else:
        print(f"{sym} {out['days']} days, spread {a.spread:.0f}  cfg {json.dumps(over)}")
        for k in ("full", "h1", "h2"):
            b, x = base[k], v[k]
            print(f"  {k:4s} base {b['trades']:4d} tr {b['wr']:5.1f}% net {b['net']:8.2f} worst {b['worst_debt']:6.2f} | "
                  f"variant {x['trades']:4d} tr {x['wr']:5.1f}% net {x['net']:8.2f} worst {x['worst_debt']:6.2f}  ({x['net']-b['net']:+.2f} net, {x['worst_debt']-b['worst_debt']:+.2f} worst)")
        print(f"  verdict {out['verdict']}")


if __name__ == "__main__":
    main()
