"""Pinned DEVELOPMENT dataset (review 6): harness.bars() fetches the latest
60000 M1 bars at run time, so the window slides with the clock and no two
studies see the same interval. This freezes one interval to disk and every
study loads it. Metadata (feed, first/last bar, count, sha) sits beside it."""
import hashlib, json, os, sys, time
import numpy as np
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__))
NPZ = os.path.join(HERE, "dev_bars_2026-10-09.npz")
META = NPZ.replace(".npz", ".json")


def load(version=""):
    """version "" = the original pinned file (last bar was FORMING at capture:
    kept for reconciliation); version "b" = closed bars only (review 8)."""
    if version:
        npz = NPZ.replace(".npz", version + ".npz"); meta = json.load(open(npz.replace(".npz", ".json")))
        R = np.load(npz)["R"]
        assert hashlib.sha256(open(npz, "rb").read()).hexdigest()[:16] == meta["sha256"], "dataset drift"
        return meta["symbol"], R, meta
    if not os.path.exists(NPZ):
        import harness as H
        sym, R = H.bars()
        np.savez_compressed(NPZ, R=R)
        meta = {"symbol": sym, "source": "harness.bars(): the std account's terminal (C:/Projects/MT5-KinoliveTrader)",
                "bars": int(len(R)), "first_bar": int(R["time"][0]), "last_bar": int(R["time"][-1]),
                "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sha256": hashlib.sha256(open(NPZ, "rb").read()).hexdigest()[:16]}
        json.dump(meta, open(META, "w"), indent=1)
    meta = json.load(open(META))
    R = np.load(NPZ)["R"]
    assert hashlib.sha256(open(NPZ, "rb").read()).hexdigest()[:16] == meta["sha256"], "dataset drift"
    return meta["symbol"], R, meta


if __name__ == "__main__":
    sym, R, meta = load()
    print(json.dumps(meta, indent=1))
