"""GPT review of reply 18, item 2: WARM-UP bars for the causal/sticky structure walk - the 8000 M1 bars that
precede the development dataset's first bar, fetched from the same terminal (the std account's, as
harness.bars() does), so every opportunity of the dataset is judged with a full 8000-bar window.
Read-only on the terminal; saved as study/dev_bars_2026-10-09b_warmup.npz (+ .json with sha / span).
    python fetch_warmup_bars.py
"""
import os, sys, json, time, hashlib
import numpy as np
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
import MetaTrader5 as mt5
HERE = os.path.dirname(os.path.abspath(__file__))
META = json.load(open(os.path.join(HERE, "dev_bars_2026-10-09b.json")))
OUT = os.path.join(HERE, "dev_bars_2026-10-09b_warmup.npz")
WIN = 8000


def main():
    first = int(META["first_bar"]); sym = META["symbol"]
    u = next(x for x in json.load(open(r"C:\Projects\KinoliveLines\live\owl_nest_users.json", encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit("MT5: %s" % (mt5.last_error(),))
    from datetime import datetime, timezone
    t0 = datetime.fromtimestamp(first - (WIN + 3000) * 60, tz=timezone.utc); t1 = datetime.fromtimestamp(first - 1, tz=timezone.utc)
    R = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, t0, t1)
    mt5.shutdown()
    if R is None or len(R) < WIN:
        raise SystemExit("not enough warm-up bars: %s" % (None if R is None else len(R)))
    R = R[R["time"] < first][-WIN:]
    np.savez_compressed(OUT, R=R)
    meta = {"symbol": sym, "source": "std account terminal, copy_rates_range (read-only)", "for_dataset": META["sha256"], "bars": int(len(R)),
            "first_bar": int(R["time"][0]), "last_bar": int(R["time"][-1]), "dataset_first_bar": first,
            "gap_to_dataset_s": int(first - int(R["time"][-1])), "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sha256": hashlib.sha256(open(OUT, "rb").read()).hexdigest()[:16]}
    json.dump(meta, open(OUT.replace(".npz", ".json"), "w"), indent=1)
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
