"""M1 bars of ONE account's own terminal (read-only), for a replay on that account's quotes.
    python fetch_bars_uid.py --uid u224016179 --from 2026-09-09T00:00:00 [--to 2026-10-11T00:00:00]
Writes study/bars_<uid>.npz (+ .json meta with sha / span / symbol). Closed bars only.
"""
import os, sys, json, time, hashlib
import numpy as np
A = list(sys.argv); sys.argv = ["x"]
import MetaTrader5 as mt5
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
uid = A[A.index("--uid") + 1]
t0 = datetime.strptime(A[A.index("--from") + 1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
t1 = datetime.strptime(A[A.index("--to") + 1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) if "--to" in A else datetime.now(timezone.utc)
u = next(x for x in json.load(open(r"C:\Projects\KinoliveLines\live\owl_nest_users.json", encoding="utf-8")) if x["id"] == uid)
if not mt5.initialize(path=u["terminal"]):
    raise SystemExit("MT5: %s" % (mt5.last_error(),))
sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
R = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, t0, t1)
mt5.shutdown()
if R is None or not len(R):
    raise SystemExit("no bars")
R = R[:-1] if int(R["time"][-1]) > int(time.time()) - 60 else R
out = os.path.join(HERE, "bars_%s.npz" % uid); np.savez_compressed(out, R=R)
meta = {"uid": uid, "symbol": sym, "server": u.get("mt5_server"), "bars": int(len(R)), "first_bar": int(R["time"][0]), "last_bar": int(R["time"][-1]),
        "first_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(R["time"][0]))), "last_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(R["time"][-1]))),
        "gaps_over_5min": int((np.diff(R["time"]) > 300).sum()), "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sha256": hashlib.sha256(open(out, "rb").read()).hexdigest()[:16]}
json.dump(meta, open(out.replace(".npz", ".json"), "w"), indent=1)
print(json.dumps(meta, indent=1))
