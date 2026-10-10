"""Download BTCUSDm bid/ask ticks for the development window (dataset b) from the
std account's terminal, read-only, one UTC day per file: study/ticks/<sym>_<day>.npz
(time_msc int64, bid float64, ask float64, flags uint32). A manifest records per-day
counts, first/last tick and the number of gaps > 5 s inside the trading day.
Files are local (gitignored); the manifest is committed.
    python fetch_ticks.py
"""
import json, os, sys, time, hashlib
FORWARD = "--forward" in sys.argv        # captured BEFORE the imports below (dev_dataset resets sys.argv)
# --uid <nest id> : fetch from THAT account's terminal (read-only) into study/ticks_<uid>/ (Stage 0/2:
# the dedicated demo's own quotes); the symbol is the terminal's (BTCUSD on Exness demo/real, BTCUSDm on std)
UID = sys.argv[sys.argv.index("--uid") + 1] if "--uid" in sys.argv else "std"
import numpy as np
from datetime import datetime, timezone
sys.path.insert(0, r"C:\Projects\KinoliveLines\study")
import dev_dataset
import MetaTrader5 as mt5
LIVE = r"C:\Projects\KinoliveLines\live"; OUT = "C:/Projects/KinoliveLines/study/ticks"; os.makedirs(OUT, exist_ok=True)
sym, R, META = dev_dataset.load("b")
T0, T1 = int(R["time"][0]), int(R["time"][-1]) + 60
# --forward (pre-registered untouched period): from the development cutoff to now, into
# study/ticks_forward/ with its own manifest; re-runnable daily, finished days are skipped,
# the current (partial) day is refreshed. Read-only, no trading call.
if FORWARD:
    T0 = int(META["closed_bar_cutoff"]); T1 = int(time.time()); OUT = "C:/Projects/KinoliveLines/study/ticks_forward"; os.makedirs(OUT, exist_ok=True)
if UID != "std":
    OUT = "C:/Projects/KinoliveLines/study/ticks_%s%s" % (UID, "_forward" if FORWARD else ""); os.makedirs(OUT, exist_ok=True)
u = next(x for x in json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == UID)
if not mt5.initialize(path=u["terminal"]):
    raise SystemExit("MT5: %s" % (mt5.last_error(),))
sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else sym          # the terminal's own symbol name
dt = lambda s: datetime.fromtimestamp(s, tz=timezone.utc)
day0 = T0 - T0 % 86400
man_path = os.path.join(OUT, "manifest.json")
man = json.load(open(man_path)) if os.path.exists(man_path) else {"symbol": sym, "dataset": META["sha256"], "window": [T0, T1], "days": {}, "uid": UID, "terminal": u["terminal"]}
d = day0
while d < T1:
    key = dt(d).strftime("%Y-%m-%d"); fn = os.path.join(OUT, "%s_%s.npz" % (sym, key))
    if key in man["days"] and os.path.exists(fn) and man["days"][key].get("complete", True):
        d += 86400; continue
    parts = []
    for h in range(0, 24, 4):                     # 4-hour slices: the API returns at most ~a few hundred thousand per call
        tk = mt5.copy_ticks_range(sym, dt(d + h * 3600), dt(d + (h + 4) * 3600), mt5.COPY_TICKS_ALL)
        if tk is not None and len(tk):
            parts.append(tk)
    if parts:
        tk = np.concatenate(parts)
        tm = tk["time_msc"].astype(np.int64); order = np.argsort(tm, kind="stable"); tm = tm[order]
        bid = tk["bid"].astype(np.float64)[order]; ask = tk["ask"].astype(np.float64)[order]; fl = tk["flags"].astype(np.uint32)[order]
        keep = np.concatenate([[True], np.diff(tm) >= 0])   # keep duplicates of the same ms (ordered), drop nothing else
        np.savez_compressed(fn, time_msc=tm, bid=bid, ask=ask, flags=fl)
        gaps = int(np.sum(np.diff(tm) > 5000))
        man["days"][key] = {"n": int(len(tm)), "first_msc": int(tm[0]), "last_msc": int(tm[-1]), "gaps_gt_5s": gaps,
                            "max_gap_s": round(float(np.max(np.diff(tm)) / 1000.0), 1) if len(tm) > 1 else None,
                            "sha256": hashlib.sha256(open(fn, "rb").read()).hexdigest()[:16],
                            "complete": bool(d + 86400 <= T1 - 3600)}      # a day is complete once an hour past its end has elapsed
        print(key, man["days"][key], flush=True)
    else:
        man["days"][key] = {"n": 0}; print(key, "NO TICKS", flush=True)
    json.dump(man, open(man_path, "w"), indent=1)
    d += 86400
mt5.shutdown()
print("DONE days", len(man["days"]), "ticks", sum(v.get("n", 0) for v in man["days"].values()), flush=True)
