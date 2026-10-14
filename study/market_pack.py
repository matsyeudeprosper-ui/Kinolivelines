"""market_pack.py - a market's data pack for the robot bench (owner 2026-10-14: "users want to test their
robots on a chosen symbol; the symbols are those of the account's broker").

The bench (robot_runner.py) was written for one BTC dataset. Its money arithmetic is points x lot (true only for
BTCUSD, $1 per 1.0 move per lot) and a few rules are in BTC points (S_MIN_DIST 10). A pack makes another market
look like that to the SAME code, with no engine edit:

  * bars: N_DATA closed M1 bars + the RAW_BARS (8000) before them as warm-up, from the member's own terminal
    (their broker, their symbol names - BTCUSDm on a standard account);
  * prices are multiplied by k = V x m:
      V = trade_tick_value / trade_tick_size  -> "points x lot" becomes real dollars (gold: 0.1 / 0.001 = 100);
      m = BTC's median M1 range / this market's (in dollars per lot) -> the SAME RISK per trade as the BTC test,
          so the $200 balance, sizing limits, kill line and dollar results mean what they mean on BTC.
      m changes nothing but the size of every number: win rate, profit factor and the trade list are unchanged,
      and real dollars at the robot's own lot = result / m (kept in meta);
  * S_MIN_DIST = 10/7 x this market's median spread (the BTC rule, 10 for a 7 spread - as the trial scanner);
  * synthetic ticks: open, then low/high in the adverse-first order of the candle's colour, then close; bid = the
    bar price, ask = bid + the bar's spread. Bar fills are less precise than BTC's real ticks - said in the app;
  * the sticky pullback-state cache, built by the bench's own causal walk (~52 ms per bar: about 35-50 min),
    fingerprinted on these bars so a pack can never be read against other data.

    python market_pack.py XAUUSD [terminal64.exe path]      build (or reuse) one pack
    python market_pack.py --list                           packs on disk
Packs: study/markets/<SYMBOL>/ (bars.npz, warm.npz + .json, meta.json, pb_cache.pkl)
"""
import sys, os, json, time, hashlib
ARGS = list(sys.argv); sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import numpy as np

PACKS = os.path.join(HERE, "markets")
N_DATA = 60000
DEFAULT_TERMINAL = r"C:\NestTerminals\u476954287\terminal64.exe"   # the Pro demo that feeds the charts
PACK_VERSION = 1


def pack_dir(sym):
    return os.path.join(PACKS, sym.upper())


def pack_ready(sym):
    d = pack_dir(sym)
    try:
        meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
        return meta.get("cache_ok") and os.path.exists(os.path.join(d, "pb_cache.pkl")) and meta.get("version") == PACK_VERSION
    except Exception:
        return False


def _sha(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


def fetch(sym, terminal, n_warm):
    import MetaTrader5 as mt5
    if not mt5.initialize(path=terminal, timeout=120000):
        raise SystemExit("MT5: %s" % (mt5.last_error(),))
    try:
        if not mt5.symbol_select(sym, True):
            raise SystemExit("symbol %s not available on this account" % sym)
        info = mt5.symbol_info(sym)
        time.sleep(1.0)
        rates = None
        for _ in range(5):                       # history may still be downloading
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, N_DATA + n_warm)   # from 1: closed bars only
            if rates is not None and len(rates) >= n_warm + 5000:
                break
            time.sleep(3.0)
        if rates is None or len(rates) < n_warm + 5000:
            raise SystemExit("not enough M1 history for %s (%s bars)" % (sym, 0 if rates is None else len(rates)))
        I = {k: getattr(info, k) for k in ("digits", "point", "trade_tick_size", "trade_tick_value", "trade_contract_size",
                                           "spread", "currency_profit", "description", "path")}
        server = getattr(mt5.account_info(), "server", "")
    finally:
        mt5.shutdown()                            # detaches; the terminal keeps running
    return np.array(rates), I, server


def build(sym, terminal=DEFAULT_TERMINAL, log=print):
    import tick_engine as E
    import tick_engine_pbgate_sticky as K
    import tick_engine_matrix as TMX
    import owl_chart_feed as F
    import harness as H
    sym = sym.upper(); d = pack_dir(sym); os.makedirs(d, exist_ok=True)
    WIN = F.RAW_BARS
    raw, I, server = fetch(sym, terminal, WIN)
    V = float(I["trade_tick_value"]) / float(I["trade_tick_size"])
    rng = np.median((raw["high"] - raw["low"])[raw["high"] > raw["low"]]) * V
    ref = float(np.median((E.R["high"] - E.R["low"])[E.R["high"] > E.R["low"]]))     # BTC, $ per lot = points
    m = ref / rng if rng > 0 else 1.0
    k = V * m
    R = raw.copy()
    for f in ("open", "high", "low", "close"):
        R[f] = R[f] * k
    pt = float(I["point"]) * k
    sp = raw["spread"][raw["spread"] > 0]
    sp_med = float(np.median(sp)) if len(sp) else float(I["spread"] or 1)
    smd = 10.0 / 7.0 * sp_med * pt
    W, D = R[:WIN], R[WIN:]
    np.savez(os.path.join(d, "warm.npz"), R=W)
    json.dump({"symbol": sym, "sha256": _sha(W), "bars": len(W)}, open(os.path.join(d, "warm.json"), "w"))
    np.savez(os.path.join(d, "bars.npz"), R=D)
    meta = {"version": PACK_VERSION, "symbol": sym, "server": server, "terminal": terminal, "description": I["description"],
            "path": I["path"], "digits": I["digits"], "point": I["point"], "tick_size": I["trade_tick_size"],
            "tick_value": I["trade_tick_value"], "contract": I["trade_contract_size"], "ccy": I["currency_profit"],
            "V": V, "m": m, "k": k, "spread_med_points": sp_med, "s_min_dist": smd, "bars": len(D),
            "first_bar": int(D["time"][0]), "last_bar": int(D["time"][-1]), "closed_bar_cutoff": int(D["time"][-1]) + 60,
            "sha256": _sha(D), "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cache_ok": False}
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"), indent=1)
    log("%s: %d bars (%s -> %s), k=%.6g (V=%.6g x m=%.4g), min stop %.2f, building the pullback states..." % (
        sym, len(D), time.strftime("%Y-%m-%d", time.gmtime(meta["first_bar"])), time.strftime("%Y-%m-%d", time.gmtime(meta["last_bar"])),
        k, V, m, smd))
    use(meta, d, E, K, TMX, H)
    cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": 200.0}), drag=0.0, limits_live=1))
    opps, _bars = E.streams(cfg0, D)
    t0 = time.time()
    K.causal_sticky_states([o["i"] for o in opps])
    meta["cache_ok"] = True; meta["cache_secs"] = round(time.time() - t0); meta["opportunities"] = len(opps)
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"), indent=1)
    log("%s: pack ready (%d opportunities, %ds)" % (sym, len(opps), meta["cache_secs"]))
    return meta


def use(meta, d, E, K, TMX, H):
    """point the bench's modules at this pack (bars, cutoff, cache, minimum stop)"""
    D = np.load(os.path.join(d, "bars.npz"))["R"]
    E.R = D; K.R = D
    E.META = {"sha256": meta["sha256"], "closed_bar_cutoff": meta["closed_bar_cutoff"], "symbol": meta["symbol"]}
    K.WARM_NPZ = os.path.join(d, "warm.npz"); K.CACHE = os.path.join(d, "pb_cache.pkl")
    E.S_MIN_DIST = TMX.S_MIN_DIST = H.B.S_MIN_DIST = float(meta["s_min_dist"])
    return D


def synthetic_ticks(D, meta):
    """4 quotes per closed bar: open, adverse extreme first (by candle colour), other extreme, close"""
    pt = float(meta["point"]) * float(meta["k"])
    sp = np.where(D["spread"] > 0, D["spread"], meta["spread_med_points"]).astype(float) * pt
    n = len(D); t = D["time"].astype(np.int64) * 1000
    up = D["close"] >= D["open"]
    a = np.where(up, D["low"], D["high"]); b = np.where(up, D["high"], D["low"])
    TM = np.empty(n * 4, np.int64); BID = np.empty(n * 4)
    TM[0::4] = t; TM[1::4] = t + 15000; TM[2::4] = t + 35000; TM[3::4] = t + 58000
    BID[0::4] = D["open"]; BID[1::4] = a; BID[2::4] = b; BID[3::4] = D["close"]
    ASK = BID + np.repeat(sp, 4)
    return TM, BID, ASK, 0, int(meta["closed_bar_cutoff"]) * 1000


if __name__ == "__main__":
    if "--list" in ARGS:
        for s in sorted(os.listdir(PACKS)) if os.path.isdir(PACKS) else []:
            try:
                mm = json.load(open(os.path.join(PACKS, s, "meta.json")))
                print(s, "ready" if pack_ready(s) else "NOT ready", mm.get("built_at"), "bars", mm.get("bars"))
            except Exception:
                print(s, "broken")
        sys.exit(0)
    build(ARGS[1], ARGS[2] if len(ARGS) > 2 else DEFAULT_TERMINAL)
