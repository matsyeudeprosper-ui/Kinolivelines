"""live_cfg_months.py (2026-10-25, owner: "run it one month at a time; after each month give the result so we can pause
and continue whenever").

Today's LIVE configuration of the owner's account (package of uid 'kino' in live/owl_packages.json, the deployed rules in
lab/harness.simulate - pullback-direction gate, continuations, bullets/jar, storm line, kill line) replayed month by month
on the Exness public tick archive (BTCUSD = the Pro symbol), M1 bars built from BID ticks, the month's median real spread.

  python study/live_cfg_months.py 2025-01 2025-12        # runs the months not done yet, in order
  touch study/live_cfg_months/PAUSE                      # stops cleanly after the month in progress
  delete PAUSE and run again                             # resumes at the next month not done

Each month: <out>/<YYYY-MM>.json + one line appended to <out>/SUMMARY.txt. Engine state starts fresh each month after a
3-day warm-up taken from the end of the previous month (structure needs history); the warm-up's own trades and money are
subtracted exactly (the engine is causal: the warm-up alone is replayed and removed). Lot: the package base lot at the
reference balance (0.02 at $200 - twice today's live 0.01, which is scaled down by the $181 balance). Drag: the measured
live execution drag per trade (harness drag='auto').
"""
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIVE = os.path.join(ROOT, "live")
OUT = os.path.join(HERE, "live_cfg_months")
CACHE = os.path.join(OUT, "m1")
URL = "https://ticks.ex2archive.com/ticks/BTCUSD/{y}/{m:02d}/Exness_BTCUSD_{y}_{m:02d}.zip"
WARM_DAYS = 3
TODAY_SPREAD = 7.0                       # today's live spread on the Pro account
DRAG = 0.57                              # measured engine-to-real drag per trade at 0.02 (mt5_engine_drag_gap, 2026-10)
RATES = np.dtype([("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
                  ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")])


def log(s):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), s)
    print(line, flush=True)
    io.open(os.path.join(OUT, "run.log"), "a", encoding="utf-8").write(line + "\n")


def month_m1(y, m):
    """-> (rates array, median spread $, tick count); cached as <CACHE>/<YYYY-MM>.npz"""
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, "%d-%02d.npz" % (y, m))
    if os.path.exists(cp):
        z = np.load(cp)
        return z["R"], float(z["spr"]), int(z["n"])
    import pandas as pd
    zp = os.path.join(CACHE, "_dl.zip")
    log("download %d-%02d" % (y, m))
    # 2026-10-25: the archive server drops big months mid-way (162 MB, "got only 38 MB"): resume with a Range request
    # from where the file stopped instead of starting over, up to 12 tries
    url, size = URL.format(y=y, m=m), None
    if os.path.exists(zp):
        os.remove(zp)
    for k in range(12):
        try:
            have = os.path.getsize(zp) if os.path.exists(zp) else 0
            req = urllib.request.Request(url, headers={"Range": "bytes=%d-" % have} if have else {})
            with urllib.request.urlopen(req, timeout=120) as r, open(zp, "ab" if have else "wb") as f:
                if size is None:
                    cr = r.headers.get("Content-Range")
                    size = int(cr.split("/")[-1]) if cr else int(r.headers.get("Content-Length") or 0)
                if have and r.status != 206:
                    f.seek(0)
                    f.truncate()
                while True:
                    ch = r.read(1 << 20)
                    if not ch:
                        break
                    f.write(ch)
            if size and os.path.getsize(zp) >= size:
                break
            log("  download %d: %d of %s bytes, resuming" % (k + 1, os.path.getsize(zp), size))
        except Exception as e:
            log("  download try %d stopped at %d bytes: %s" % (k + 1, os.path.getsize(zp) if os.path.exists(zp) else 0, e))
            time.sleep(10 * (k + 1))
    else:
        raise RuntimeError("download failed %d-%02d" % (y, m))
    z = zipfile.ZipFile(zp)
    name = [i.filename for i in z.infolist() if i.filename.endswith(".csv")][0]
    with z.open(name) as f:
        df = pd.read_csv(f, usecols=["Timestamp", "Bid", "Ask"], dtype={"Bid": "float64", "Ask": "float64"})
    z.close()
    os.remove(zp)
    df = df.drop_duplicates()
    df = df[(df["Bid"] > 0) & (df["Ask"] >= df["Bid"])]
    # pandas may parse to ns or ms depending on version: go through datetime64[s] explicitly (a //1e9 on ms collapsed a month to 45 bars)
    t = pd.to_datetime(df["Timestamp"], utc=True).dt.tz_convert(None).to_numpy().astype("datetime64[s]").astype("int64")
    t = pd.Series(t)
    b = df["Bid"].to_numpy()
    spr = (df["Ask"] - df["Bid"]).to_numpy()
    o = np.argsort(t.to_numpy(), kind="stable")
    t, b, spr = t.to_numpy()[o], b[o], spr[o]
    mi = t // 60
    keys, start = np.unique(mi, return_index=True)
    end = np.append(start[1:], len(mi))
    R = np.zeros(len(keys), dtype=RATES)
    R["time"] = keys * 60
    R["open"] = b[start]
    R["close"] = b[end - 1]
    R["high"] = np.maximum.reduceat(b, start)
    R["low"] = np.minimum.reduceat(b, start)
    R["tick_volume"] = end - start
    R["spread"] = np.round(np.add.reduceat(spr, start) / (end - start) * 100).astype("i4")
    med = float(np.median(spr))
    np.savez_compressed(cp, R=R, spr=med, n=len(b))
    log("  %d-%02d: %d ticks, %d M1 bars, median spread %.2f $" % (y, m, len(b), len(R), med))
    return R, med, len(b)


def main(a, b):
    os.makedirs(OUT, exist_ok=True)
    sys.path.insert(0, os.path.join(LIVE, "lab"))
    sys.path.insert(0, LIVE)
    os.chdir(LIVE)
    import harness as H
    P = json.load(open(os.path.join(LIVE, "owl_packages.json"), encoding="utf-8"))
    pkg = ((P.get("accounts") or P.get("by_account") or {}).get("kino")) or "valere"
    # 2026-10-25 (owner: "with all its rules, brakes, recovery - just like it runs live?"): package_cfg() does NOT carry
    # pb_dir_gate / risk cap / rr / k_streak from the package (the first queued run would have replayed WITHOUT the
    # pullback-direction gate). The settings are taken from the bot's own resolver (owl_package.for_account, exactly what
    # structure_bos_bot.py reads at start) and mapped onto the harness dials one by one, as review/bot_harness_parity.py maps them.
    import owl_package as PKM
    L = PKM.for_account("kino")
    pkg = L.get("package") or pkg
    cfg = H.cfg_of({
        "lot": float(L["base_lot"]), "bullets": float(L["max_extra"]), "jar": bool(L["jar"]),
        "kill_net": float(L["kill_net"] or 0.0), "day_cap": float(L.get("day_cap") or 0.0),
        "nerv_gate": bool(L.get("nervosity", True)), "storm": 1.85 if L.get("storm_ceiling") is None else float(L["storm_ceiling"]),
        "rr": float(L.get("rr") or 0.8), "k_streak": int(L.get("k_streak") or 2),
        "pb_dir_gate": bool(L.get("pb_dir_gate", False)), "pb_gate_mode": str(L.get("pb_gate_mode") or "trend"),
        "risk_pct": 100.0 * float(L.get("max_risk_pct") or 0.0),          # bot: fraction of balance; harness: percent
        "risk_fit": float(L.get("risk_fit_pct") or 0.0), "internal": 1 if L.get("internal_entries") else 0,
        "debt_gate": 1 if L.get("debt_gate", True) else 0,
        "scale_ref": float(L.get("scale_ref_balance") or 200.0),
        "balance": float(L.get("scale_ref_balance") or 200.0) if L.get("scale_with_balance") else 0.0,
    })
    for k in ("adds_on", "chest_cap", "jar_skim", "jar_stake", "jar_debt_mult", "jar_floor_cap", "min_balance", "debt_mode",
              "max_trades_day", "movement", "recov_bullets_only", "eq_half", "day_cap_waived", "week_target"):
        log("  live %-18s = %s  (harness: built-in, checked by bot_harness_parity / package_parity)" % (k, json.dumps(L.get(k))))
    cfg["drag"] = 0.0                   # drag is charged after, so both views share one replay (engine-to-real drag 0.57 $/trade @0.02, mt5_engine_drag_gap)
    log("start %s..%s package %s lot %s drag %.2f $/trade cfg %s" % (a, b, pkg, cfg["lot"], DRAG, json.dumps(cfg)[:400]))
    y, m = map(int, a.split("-"))
    ye, me = map(int, b.split("-"))
    prev = None
    while (y, m) <= (ye, me):
        key = "%d-%02d" % (y, m)
        if os.path.exists(os.path.join(OUT, "PAUSE")):
            log("PAUSE file present - stopped before %s" % key)
            return
        R, spr, nt = month_m1(y, m)
        if prev is None:
            py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
            try:
                prev = month_m1(py, pm)[0]
            except Exception:
                prev = np.zeros(0, dtype=RATES)
        if not os.path.exists(os.path.join(OUT, key + ".json")):
            t0 = time.time()
            W = prev[prev["time"] >= int(R["time"][0]) - WARM_DAYS * 86400] if len(prev) else prev
            full = np.concatenate([W, R]) if len(W) else R
            res = {"month": key, "package": pkg, "lot": cfg["lot"], "spread_median": round(spr, 2), "ticks": nt, "bars": int(len(R)),
                   "engine": "lab/harness.simulate (deployed rules), M1 from bid ticks, constant spread; drag %.2f $/trade charged after" % DRAG}
            for tag, sp in (("real", spr), ("today", TODAY_SPREAD)):
                sf = H.simulate(full, sp, cfg)
                sw = H.simulate(W, sp, cfg) if len(W) else {"net": 0.0, "pnls": []}
                pn = (sf.get("pnls") or [])[len(sw.get("pnls") or []):]
                net = sf["net"] - sw["net"]
                wins = sum(1 for p in pn if p > 0)
                run, peak, dd = 0.0, 0.0, 0.0
                for p in pn:
                    run += p - DRAG * cfg["lot"] / 0.02
                    peak = max(peak, run)
                    dd = max(dd, peak - run)
                res[tag] = {"spread": round(sp, 2), "trades": len(pn), "won": wins, "win_pct": round(100.0 * wins / len(pn), 1) if pn else 0.0,
                            "net_engine": round(net, 2), "net": round(net - DRAG * len(pn) * cfg["lot"] / 0.02, 2), "dip": round(dd, 2)}
            res["secs"] = round(time.time() - t0, 1)
            json.dump(res, open(os.path.join(OUT, key + ".json"), "w", encoding="utf-8"), indent=1)
            done = sorted(f for f in os.listdir(OUT) if f.endswith(".json") and f[:4].isdigit())
            J = [json.load(open(os.path.join(OUT, f), encoding="utf-8")) for f in done]
            cr, ct = sum(x["real"]["net"] for x in J), sum(x["today"]["net"] for x in J)
            r_, t_ = res["real"], res["today"]
            line = ("%s | at that month's spread %.2f $: %4d trades, %5.1f%% won, net %+8.2f $, dip %6.2f $ | at today's 7 $: %4d trades, "
                    "%5.1f%% won, net %+8.2f $, dip %6.2f $ | total so far %+8.2f $ / %+8.2f $ over %d months") % (
                key, spr, r_["trades"], r_["win_pct"], r_["net"], r_["dip"], t_["trades"], t_["win_pct"], t_["net"], t_["dip"], cr, ct, len(done))
            io.open(os.path.join(OUT, "SUMMARY.txt"), "a", encoding="utf-8").write(line + chr(10))
            log("DONE " + line + "  (%.0f s)" % res["secs"])
        prev = R
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    log("all months done")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-01", sys.argv[2] if len(sys.argv) > 2 else "2025-12")
