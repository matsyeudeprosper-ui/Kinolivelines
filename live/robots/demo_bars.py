"""Candles for chart demonstrations on a market that has no test pack yet (owner 2026-10-19: "where is the example?").
    pythonw live/robots/demo_bars.py USDJPY
Downloads ~42 days of closed 1-minute candles from the chart feed's demo terminal (study/market_pack.fetch - the same
read-only download a market test starts with; no test, no order) and saves demo_cache/bars_<SYM>.npz on the tests'
scale: prices x k, k = Bitcoin's median candle range / this market's, so the structure engine reads it like the tests.
"""
import json, os, sys, time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.join(os.path.dirname(os.path.dirname(HERE)), "study")
sys.path.insert(0, STUDY)


def main(sym):
    sym = sym.upper()
    out = os.path.join(HERE, "demo_cache", "bars_%s.npz" % sym)
    lock = out + ".lock"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 600:
        return
    open(lock, "w").write(str(os.getpid()))
    try:
        _argv = sys.argv; sys.argv = ["x"]
        import market_pack as MP
        import dev_dataset
        sys.argv = _argv
        raw, I, server = MP.fetch(sym, MP.DEFAULT_TERMINAL, 0)
        _, B, _ = dev_dataset.load("b")
        ref = float(np.median((B["high"] - B["low"])[B["high"] > B["low"]]))
        rng = float(np.median((raw["high"] - raw["low"])[raw["high"] > raw["low"]]))
        k = ref / rng if rng > 0 else 1.0
        R = np.array(raw).copy()
        for f in ("open", "high", "low", "close"):
            R[f] = R[f] * k
        np.savez_compressed(out + ".tmp.npz", R=R)
        os.replace(out + ".tmp.npz", out)
        json.dump({"symbol": sym, "k": k, "bars": int(len(R)), "server": server, "at": int(time.time()),
                   "description": I.get("description")}, open(out.replace(".npz", ".json"), "w", encoding="utf-8"))
    finally:
        try:
            os.remove(lock)
        except Exception:
            pass


if __name__ == "__main__":
    main(sys.argv[1])
