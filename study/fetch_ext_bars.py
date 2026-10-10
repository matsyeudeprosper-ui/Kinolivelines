"""Bars AFTER the development dataset (from its last closed bar to now), fetched read-only from the same
terminal as harness.bars() (the std account's), so a replay can run to the latest available quotes.
Saved as study/dev_bars_ext.npz (+ .json with sha / span). Re-run any time; it overwrites.
    python fetch_ext_bars.py
"""
import os, sys, json, time, hashlib
import numpy as np
sys.argv = ["x"]
import MetaTrader5 as mt5
HERE = os.path.dirname(os.path.abspath(__file__))
META = json.load(open(os.path.join(HERE, "dev_bars_2026-10-09b.json")))
OUT = os.path.join(HERE, "dev_bars_ext.npz")


def main():
    last = int(META["last_bar"]); sym = META["symbol"]
    u = next(x for x in json.load(open(r"C:\Projects\KinoliveLines\live\owl_nest_users.json", encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit("MT5: %s" % (mt5.last_error(),))
    from datetime import datetime, timezone
    R = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, datetime.fromtimestamp(last + 60, tz=timezone.utc), datetime.now(timezone.utc))
    mt5.shutdown()
    if R is None or not len(R):
        raise SystemExit("no bars after the dataset")
    R = R[R["time"] > last][:-1]          # closed bars only (the newest one may still be forming)
    np.savez_compressed(OUT, R=R)
    meta = {"symbol": sym, "source": "std account terminal, copy_rates_range (read-only)", "after_dataset": META["sha256"], "bars": int(len(R)),
            "first_bar": int(R["time"][0]), "last_bar": int(R["time"][-1]), "dataset_last_bar": last,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sha256": hashlib.sha256(open(OUT, "rb").read()).hexdigest()[:16]}
    json.dump(meta, open(OUT.replace(".npz", ".json"), "w"), indent=1)
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
