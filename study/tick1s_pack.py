"""Backtest precision plan, step 4 (owner GO 2026-10-16): REAL broker prices for every tested market, compact.

Source: ONE terminal for every market - the idle Exness Standard demo (C:\\Program Files\\MetaTrader 5, login
436771046; no member, no bot trades on it). Never a live account's terminal: a long history download starves
that terminal's other clients (2026-10-15: Dépenses' app data froze 13 min).

Per market and UTC day:
  ticks    every bid/ask change from the broker, fetched in 2-hour chunks
  storage  EVERY tick, lossless: time as millisecond deltas, prices as integer points (price / point) delta-coded,
           zlib-compressed. 2026-10-16: a first "compact" version (per second: first, last, bid/ask extremes) FAILED
           its proof (study/tick1s_proof.py, Bitcoin: Owl +51.10 -> +73.99) - the 1 s execution delay then lands on
           a kept extreme too often, a fill bias in the trader's favour. compact() is kept only for that record.
  bars     the broker's M1 candles of the same day (the structure is built from them) + a check: every minute's
           bid high/low from the ticks must equal the candle's high/low.
-> study/tick1s/<SYM>/<YYYY-MM-DD>.npz (t_ms, bid, ask) + bars.npz + manifest.json (counts, checks, sha256)

    python study/tick1s_pack.py BTCUSDm XAUUSDm USTECm --days 60
"""
import sys, os, json, time, hashlib, argparse
from datetime import datetime, timedelta, timezone
import numpy as np
import MetaTrader5 as mt5

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
EXPECT_LOGIN = 436771046
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tick1s")
CHUNK_H = 2


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def compact(t, b, a):
    """indices kept: first/last per second + argmax/argmin of bid and of ask per second (real ticks only)"""
    n = len(t)
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    sec = t // 1000
    starts = np.flatnonzero(np.r_[True, sec[1:] != sec[:-1]])
    ends = np.r_[starts[1:], n]
    keep = [starts, ends - 1,
            np.lexsort((-b, sec))[starts], np.lexsort((b, sec))[starts],
            np.lexsort((-a, sec))[starts], np.lexsort((a, sec))[starts]]
    return np.unique(np.concatenate(keep))


def save_lossless(fp, t, b, a, point):
    """every tick, exactly: ms deltas + integer-point price deltas (asserted exact before writing)"""
    bi = np.rint(b / point).astype(np.int64); ai = np.rint(a / point).astype(np.int64)
    assert np.allclose(bi * point, b, atol=point * 1e-3, rtol=0) and np.allclose(ai * point, a, atol=point * 1e-3, rtol=0), "prices not on the point grid"
    np.savez_compressed(fp, t0=t[:1], dt=np.diff(t).astype(np.int64), b0=bi[:1], db=np.diff(bi).astype(np.int64),
                        a0=ai[:1], da=np.diff(ai).astype(np.int64), point=np.array([point]))


def load_day(fp):
    """-> t_ms (int64), bid, ask (float64) exactly as fetched"""
    z = np.load(fp)
    t = np.concatenate([z["t0"], z["t0"] + np.cumsum(z["dt"])])
    p = float(z["point"][0])
    b = np.concatenate([z["b0"], z["b0"] + np.cumsum(z["db"])]) * p
    a = np.concatenate([z["a0"], z["a0"] + np.cumsum(z["da"])]) * p
    return t, b, a


def day_ticks(sym, d0):
    T, B, A = [], [], []
    for h in range(0, 24, CHUNK_H):
        f = d0 + timedelta(hours=h); u = f + timedelta(hours=CHUNK_H)
        x = mt5.copy_ticks_range(sym, f, u, mt5.COPY_TICKS_ALL)
        if x is None or not len(x):
            continue
        t = x["time_msc"].astype(np.int64); b = x["bid"].astype(np.float64); a = x["ask"].astype(np.float64)
        ok = (b > 0) & (a > 0) & (a >= b)
        T.append(t[ok]); B.append(b[ok]); A.append(a[ok])
    if not T:
        return None
    t = np.concatenate(T); b = np.concatenate(B); a = np.concatenate(A)
    o = np.argsort(t, kind="stable")
    return t[o], b[o], a[o]


def check_vs_bars(t, b, bars):
    """every minute with ticks: tick bid high/low == candle high/low (within one price step)"""
    if not len(t) or bars is None or not len(bars):
        return {"minutes": 0}
    m = t // 60000 * 60
    hi = {}; lo = {}
    starts = np.flatnonzero(np.r_[True, m[1:] != m[:-1]]); ends = np.r_[starts[1:], len(m)]
    for s, e in zip(starts, ends):
        hi[int(m[s])] = float(b[s:e].max()); lo[int(m[s])] = float(b[s:e].min())
    step = 10 ** -int(bars.attrs_digits) if hasattr(bars, "attrs_digits") else None
    ok = bad = nobar = 0; worst = 0.0
    bt = {int(r["time"]): (float(r["high"]), float(r["low"])) for r in bars}
    for k in hi:
        if k not in bt:
            nobar += 1; continue
        dh, dl = abs(hi[k] - bt[k][0]), abs(lo[k] - bt[k][1])
        worst = max(worst, dh, dl)
        if dh <= TOL and dl <= TOL:
            ok += 1
        else:
            bad += 1
    gaps = sum(1 for k in bt if k not in hi)
    return {"minutes": len(hi), "match": ok, "mismatch": bad, "tick_min_no_bar": nobar, "bar_min_no_tick": gaps, "worst_diff": round(worst, 5)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("syms", nargs="+"); ap.add_argument("--days", type=int, default=60)
    A = ap.parse_args()
    if not mt5.initialize(path=TERMINAL, timeout=60000):
        raise SystemExit("cannot attach the idle terminal: %s" % (mt5.last_error(),))
    acc = mt5.account_info()
    if acc is None or acc.login != EXPECT_LOGIN:
        mt5.shutdown(); raise SystemExit("wrong terminal/account (%s) - refusing" % (acc and acc.login))
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    days = [today - timedelta(days=i) for i in range(A.days, 0, -1)]          # complete UTC days only
    global TOL
    for sym in A.syms:
        if not mt5.symbol_select(sym, True):
            log(sym, "not on this terminal - skipped"); continue
        si = mt5.symbol_info(sym); TOL = (si.point or 0.01) * 1.01
        d = os.path.join(OUT, sym); os.makedirs(d, exist_ok=True)
        man_p = os.path.join(d, "manifest.json")
        man = json.load(open(man_p)) if os.path.exists(man_p) else {"symbol": sym, "server": acc.server, "login": acc.login, "point": si.point, "digits": si.digits, "days": {}}
        log("%s: %d days, point %s" % (sym, len(days), si.point))
        allbars = []
        for d0 in days:
            key = d0.strftime("%Y-%m-%d"); fp = os.path.join(d, key + ".npz")
            bars = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, d0, d0 + timedelta(days=1) - timedelta(seconds=1))
            if bars is not None and len(bars):
                allbars.append(bars)
            if key in man["days"] and os.path.exists(fp):
                continue
            t0 = time.time()
            x = day_ticks(sym, d0)
            if x is None:
                man["days"][key] = {"raw": 0, "kept": 0, "note": "no ticks (market closed)"}
                json.dump(man, open(man_p, "w"), indent=1); log(sym, key, "no ticks"); continue
            t, b, a = x
            chk = check_vs_bars(t, b, bars)
            save_lossless(fp, t, b, a, si.point)
            tt, bb, aa = load_day(fp)                 # round trip: what is read back must be what was fetched
            assert np.array_equal(tt, t) and np.allclose(bb, b, atol=si.point * 1e-3, rtol=0) and np.allclose(aa, a, atol=si.point * 1e-3, rtol=0), "round trip failed " + key
            k = np.arange(len(t))
            man["days"][key] = {"raw": int(len(t)), "kept": int(len(k)), "first": int(t[0]), "last": int(t[-1]),
                                "sha256": hashlib.sha256(open(fp, "rb").read()).hexdigest()[:16], "check": chk,
                                "spread_med": round(float(np.median(a - b)), 5), "secs": round(time.time() - t0, 1)}
            json.dump(man, open(man_p, "w"), indent=1)
            log("%s %s raw %d -> kept %d (%.0f%%) | minutes %s match %s mismatch %s no-tick %s | %.0fs" % (
                sym, key, len(t), len(k), 100.0 * len(k) / len(t), chk.get("minutes"), chk.get("match"), chk.get("mismatch"), chk.get("bar_min_no_tick"), time.time() - t0))
            del t, b, a, x
        if allbars:
            B = np.concatenate(allbars); B = B[np.unique(B["time"], return_index=True)[1]]
            np.savez_compressed(os.path.join(d, "bars.npz"), R=B)
            man["bars"] = {"n": int(len(B)), "first": int(B["time"][0]), "last": int(B["time"][-1])}
            json.dump(man, open(man_p, "w"), indent=1)
        log(sym, "done")
    mt5.shutdown()


TOL = 0.01
if __name__ == "__main__":
    main()
