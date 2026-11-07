"""Builds the lab's two data sets (2026-11-07):
  research  2025-12 .. 2026-06  -> C:\\KinoWorld\\lab\\data\\btc_m1_research.npz  (his to use freely)
  locked    2026-07 .. now      -> study/kino_lab/locked_btc_m1.npz          (only the app opens it, for a final exam)
1-minute BTCUSD candles: the broker's public archive, then our own recording from 2026-10-01 (the real spread). Spread is
stored in price units (MT5 points x 0.01).
    python build_data.py
"""
import os, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
OUT_R = r"C:\KinoWorld\lab\data\btc_m1_research.npz"
OUT_L = os.path.join(HERE, "locked_btc_m1.npz")
KEYS = ("time", "open", "high", "low", "close", "spread")


def arc(m):
    return np.load(os.path.join(STUDY, "ticks_archive_BTCUSD", "bars_%s.npz" % m))["R"]


def pack(rows):
    R = np.concatenate(rows)
    R = R[np.argsort(R["time"], kind="stable")]
    _, u = np.unique(R["time"], return_index=True)
    R = R[u]
    return {"time": R["time"].astype(np.int64), "open": R["open"].astype(float), "high": R["high"].astype(float),
            "low": R["low"].astype(float), "close": R["close"].astype(float), "spread": R["spread"].astype(float) * 0.01}


def main():
    research = pack([arc(m) for m in ("2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06")])
    own = np.load(os.path.join(STUDY, "bars_u224016179.npz"))["R"]
    oct1 = time.mktime((2026, 10, 1, 0, 0, 0, 0, 0, 0)) - time.timezone
    locked = pack([arc(m) for m in ("2026-07", "2026-08", "2026-09")] + [own[own["time"] >= oct1]])
    os.makedirs(os.path.dirname(OUT_R), exist_ok=True)
    np.savez_compressed(OUT_R, **research)
    np.savez_compressed(OUT_L, **locked)
    for nm, d in (("research", research), ("locked", locked)):
        print(nm, len(d["time"]), time.strftime("%Y-%m-%d", time.gmtime(d["time"][0])), "->",
              time.strftime("%Y-%m-%d", time.gmtime(d["time"][-1])), "spread median %.2f" % np.median(d["spread"]))


if __name__ == "__main__":
    main()
