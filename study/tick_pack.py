"""Backtest precision plan, step 4b: a market pack built ONLY from verified broker data (owner GO 2026-10-16).

Same contract as market_pack.py (the bench sees every market as "Bitcoin at the same risk"), different data:
  * bars    the broker's M1 candles from study/tick1s/<SRC>/bars.npz (the 60-day window, candle-checked against
            the ticks) + the 8000 bars before it as warm-up, from the SAME idle terminal;
  * fills   EVERY real tick of the window (study/tick1s, lossless) - no synthetic quotes;
  * scale   k = V x m as market_pack (V = tick value / tick size; m = Bitcoin's median M1 range / this market's,
            Bitcoin measured on ITS pack window). Bitcoin itself: k = 1;
  * min stop  Bitcoin 10 points (the live bot's S_MIN_DIST); elsewhere 10/7 x the market's median REAL spread;
  * the sticky pullback cache from the bench's own causal walk (market_pack.parallel_states).
One window, one source, one method for every market, Bitcoin included.

    python study/tick_pack.py BTCUSD XAUUSD USTEC        (source symbols = name + "m" on the Standard demo)
Packs: study/markets_tick/<SYM>/ (bars.npz, warm.npz + .json, meta.json, pb_cache.pkl)
"""
import sys, os, json, time, glob, pickle, hashlib
ARGS = list(sys.argv); sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import numpy as np
import market_pack as MP
from tick1s_pack import load_day, TERMINAL, EXPECT_LOGIN

TPACKS = os.path.join(HERE, "markets_tick")
TICK1S = os.path.join(HERE, "tick1s")
TPACK_VERSION = 1


def tdir(sym):
    return os.path.join(TPACKS, sym.upper())


def tick_ready(sym):
    try:
        meta = json.load(open(os.path.join(tdir(sym), "meta.json"), encoding="utf-8"))
        return bool(meta.get("cache_ok")) and meta.get("version") == TPACK_VERSION and os.path.exists(os.path.join(tdir(sym), "pb_cache.pkl"))
    except Exception:
        return False


def src_of(sym):
    return sym.upper() + "m"


def med_range(R):
    r = R["high"] - R["low"]
    return float(np.median(r[r > 0]))


def warm_bars(src, first_t, n):
    import MetaTrader5 as mt5
    from datetime import datetime, timezone, timedelta
    if not mt5.initialize(path=TERMINAL, timeout=60000):
        raise SystemExit("cannot attach the idle terminal")
    try:
        if mt5.account_info().login != EXPECT_LOGIN:
            raise SystemExit("wrong terminal - refusing")
        end = datetime.fromtimestamp(first_t - 60, tz=timezone.utc)
        R = mt5.copy_rates_range(src, mt5.TIMEFRAME_M1, end - timedelta(days=int(n / 1000) + 14), end)
        I = mt5.symbol_info(src)._asdict()
        return R[-n:], I
    finally:
        mt5.shutdown()


def build(sym, log=print, workers=MP.WORKERS):
    import tick_engine as E
    import tick_engine_pbgate_sticky as K
    import tick_engine_matrix as TMX
    import owl_chart_feed as F
    import harness as H
    sym = sym.upper(); src = src_of(sym); d = tdir(sym); os.makedirs(d, exist_ok=True)
    WIN = F.RAW_BARS
    D = np.load(os.path.join(TICK1S, src, "bars.npz"))["R"]
    W, I = warm_bars(src, int(D["time"][0]), WIN)
    assert len(W) == WIN and int(W["time"][-1]) < int(D["time"][0]), "warm-up must end before the window"
    V = float(I["trade_tick_value"]) / float(I["trade_tick_size"])
    if sym == "BTCUSD":
        m = 1.0
    else:
        ref = med_range(np.load(os.path.join(TICK1S, "BTCUSDm", "bars.npz"))["R"])     # Bitcoin, same window, $/lot = points
        m = ref / (med_range(D) * V)
    k = V * m
    Wk, Dk = W.copy(), D.copy()
    for f in ("open", "high", "low", "close"):
        Wk[f] = Wk[f] * k; Dk[f] = Dk[f] * k
    man = json.load(open(os.path.join(TICK1S, src, "manifest.json")))
    sp_pts = float(np.median([v["spread_med"] for v in man["days"].values() if v.get("raw")])) / float(I["point"])
    smd = 10.0 if sym == "BTCUSD" else 10.0 / 7.0 * sp_pts * float(I["point"]) * k
    np.savez(os.path.join(d, "warm.npz"), R=Wk)
    json.dump({"symbol": sym, "sha256": MP._sha(Wk), "bars": len(Wk)}, open(os.path.join(d, "warm.json"), "w"))
    np.savez(os.path.join(d, "bars.npz"), R=Dk)
    meta = {"version": TPACK_VERSION, "kind": "ticks", "symbol": sym, "source_symbol": src, "server": man.get("server"), "login": man.get("login"),
            "terminal": TERMINAL, "description": I["description"], "digits": I["digits"], "point": I["point"], "tick_size": I["trade_tick_size"],
            "tick_value": I["trade_tick_value"], "contract": I["trade_contract_size"], "ccy": I["currency_profit"],
            "V": V, "m": m, "k": k, "spread_med_points": sp_pts, "s_min_dist": smd, "bars": len(Dk),
            "first_bar": int(Dk["time"][0]), "last_bar": int(Dk["time"][-1]), "closed_bar_cutoff": int(Dk["time"][-1]) + 60,
            "sha256": MP._sha(Dk), "tick_days": sorted(k2 for k2, v in man["days"].items() if v.get("raw")),
            "ticks_raw": int(sum(v["raw"] for v in man["days"].values())), "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cache_ok": False}
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"), indent=1)
    log("%s: %d bars (%s -> %s) from %s, k=%.6g (V=%.6g x m=%.4g), min stop %.2f, %d ticks; walking the structure..." % (
        sym, len(Dk), time.strftime("%Y-%m-%d", time.gmtime(meta["first_bar"])), time.strftime("%Y-%m-%d", time.gmtime(meta["last_bar"])),
        src, k, V, m, smd, meta["ticks_raw"]))
    MP.use(meta, d, E, K, TMX, H)
    cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": 200.0}), drag=0.0, limits_live=1))
    opps, _b = E.streams(cfg0, Dk)
    t0 = time.time()
    states = MP.parallel_states(d, [o["i"] for o in opps], WIN, workers=workers, log=log)
    wm = json.load(open(os.path.join(d, "warm.json")))
    pickle.dump({"fingerprint": K.fingerprint(wm), "bars_sha": meta["sha256"], "n_bars": len(Dk), "warmup_sha": wm["sha256"], "states": states},
                open(os.path.join(d, "pb_cache.pkl"), "wb"))
    meta["cache_ok"] = True; meta["cache_secs"] = round(time.time() - t0); meta["opportunities"] = len(opps)
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"), indent=1)
    log("%s: tick pack ready (%d opportunities, %ds)" % (sym, len(opps), meta["cache_secs"]))
    return meta


def real_ticks(meta, d):
    """every broker tick of the window, scaled like the bars -> (TM, BID, ASK, n_bad, END) for the bench.
    2026-10-16: served from a disk cache (<pack>/ticks_tm.npy, ticks_bid.npy, ticks_ask.npy) as read-only memory
    maps - Nasdaq's 56 M ticks are 1.3 GB and building them in RAM (day parts + concatenation + scaled copies, ~5x)
    ran the 12 GB server out of memory. The cache is filled one day at a time (peak = one day) and reused; the
    replay walks the maps sequentially, so the OS pages them in as it goes."""
    src = meta["source_symbol"]; k = float(meta["k"])
    lo, hi = int(meta["first_bar"]) * 1000, int(meta["closed_bar_cutoff"]) * 1000
    tag = os.path.join(d, "ticks_cache.json")
    want = {"sha256": meta.get("sha256"), "k": k, "lo": lo, "hi": hi, "days": list(meta["tick_days"])}
    files = [os.path.join(d, "ticks_%s.npy" % x) for x in ("tm", "bid", "ask")]
    try:
        have = json.load(open(tag, encoding="utf-8"))
    except Exception:
        have = None
    if have != want or not all(os.path.exists(f) for f in files):
        n = 0; counts = []
        for day in meta["tick_days"]:                      # pass 1: how many ticks fall in the window
            t, _, _ = load_day(os.path.join(TICK1S, src, day + ".npz"))
            c = int(((t >= lo) & (t < hi)).sum()); counts.append(c); n += c
        tmp = [f + ".tmp" for f in files]
        TMw = np.lib.format.open_memmap(tmp[0], mode="w+", dtype=np.int64, shape=(n,))
        Bw = np.lib.format.open_memmap(tmp[1], mode="w+", dtype=np.float64, shape=(n,))
        Aw = np.lib.format.open_memmap(tmp[2], mode="w+", dtype=np.float64, shape=(n,))
        pos = 0
        for day, c in zip(meta["tick_days"], counts):      # pass 2: fill, one day in memory at a time
            if not c:
                continue
            t, b, a = load_day(os.path.join(TICK1S, src, day + ".npz"))
            m = (t >= lo) & (t < hi)
            TMw[pos:pos + c] = t[m]; Bw[pos:pos + c] = b[m] * k; Aw[pos:pos + c] = a[m] * k
            pos += c
        assert pos == n
        TMw.flush(); Bw.flush(); Aw.flush(); del TMw, Bw, Aw
        for f, tf in zip(files, tmp):
            os.replace(tf, f)
        json.dump(want, open(tag, "w", encoding="utf-8"))
    TM = np.load(files[0], mmap_mode="r"); B = np.load(files[1], mmap_mode="r"); A = np.load(files[2], mmap_mode="r")
    return TM, B, A, 0, hi


if __name__ == "__main__":
    # --workers N (2026-10-16: 4 processes ran the server short of memory; 3 by default from the command line)
    W = int(ARGS[ARGS.index("--workers") + 1]) if "--workers" in ARGS else 3
    for s in [a for i, a in enumerate(ARGS[1:], 1) if a != "--workers" and ARGS[i - 1] != "--workers"]:
        build(s, workers=W)
