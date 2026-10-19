"""Live 1-minute candles for ghost mode (owner 2026-10-19 item 4: "the robot trades with pretend money on live prices,
Kino follows each pretend trade"). One small loop: every 60 s, the last 3000 closed M1 candles of every market that has
a ghost running (demo_cache/ghost_syms.json, written by the app) from the chart feed's DEMO terminal (read-only, no
order), saved on the tests' scale (prices x k, same k as the demo / test candles) to demo_cache/live_<SYM>.npz.
Stops by itself after 30 min with no ghost. One instance (lock).
    pythonw live/robots/ghost_feed.py"""
import json, os, sys, time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "demo_cache")
SYMS = os.path.join(CACHE, "ghost_syms.json")
LOCK = os.path.join(CACHE, "ghost_feed.lock")
STUDY = os.path.join(os.path.dirname(os.path.dirname(HERE)), "study")
TERMINAL = r"C:\NestTerminals\u476954287\terminal64.exe"


def k_of(sym):
    """the same scale as the test / demo candles of that market"""
    if sym.startswith("BTC"):
        return 1.0
    for f in (os.path.join(STUDY, "markets_tick", sym, "meta.json"), os.path.join(STUDY, "markets", sym, "meta.json"),
              os.path.join(CACHE, "bars_%s.json" % sym)):
        try:
            return float(json.load(open(f, encoding="utf-8"))["k"])
        except Exception:
            pass
    return None


def main():
    os.makedirs(CACHE, exist_ok=True)
    if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 180:
        return
    import MetaTrader5 as mt5
    if not mt5.initialize(path=TERMINAL, timeout=120000):
        return
    idle = time.time()
    try:
        while True:
            open(LOCK, "w").write(str(os.getpid()))
            try:
                want = [str(x).upper() for x in json.load(open(SYMS, encoding="utf-8"))]
            except Exception:
                want = []
            if want:
                idle = time.time()
            elif time.time() - idle > 1800:
                break
            for sym in want[:10]:
                k = k_of(sym)
                name = "BTCUSD" if sym.startswith("BTC") else sym
                if k is None or not mt5.symbol_select(name, True):
                    continue
                R = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_M1, 1, 3000)        # closed candles only
                if R is None or len(R) < 500:
                    continue
                R = np.array(R).copy()
                for f in ("open", "high", "low", "close"):
                    R[f] = R[f] * k
                fn = os.path.join(CACHE, "live_%s.npz" % sym)
                np.savez_compressed(fn + ".tmp.npz", R=R)
                os.replace(fn + ".tmp.npz", fn)
                json.dump({"sym": sym, "k": k, "last": int(R["time"][-1]), "at": int(time.time())},
                          open(fn.replace(".npz", ".json"), "w"))
            time.sleep(60)
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
        try:
            os.remove(LOCK)
        except Exception:
            pass


if __name__ == "__main__":
    main()
