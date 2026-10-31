"""months.py - each month of 2026 through the REAL bot (botsim), three at a time (2026-10-26).

Owner's pending order: "once the backtest money matches reality AND most 2026 months are negative -> pause". The earlier month
figures came from the harness (a model of the bot). This replays the live bot itself on each month: Exness public archive ticks
for Jan-Sep (validated: 14-21 Sep archive = recorded, 7/7 trades, same balance to the cent), our own recording for October.
Each month starts fresh (no debt, 200 $, Valère's package), like study/live_cfg_months.py.

python study/botsim/months.py [2026-01 2026-02 ...]      -> study/botsim/months_summary.json + one line per month
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
ROOT = os.path.dirname(STUDY)
PAR = int(os.environ.get("BOTSIM_PAR", "3"))
# 2026-10-31: a variant run (BOTSIM_TAG + BOTSIM_PKG package dials, see run_sim.py) gets its own runs/ and summary
TAG = os.environ.get("BOTSIM_TAG", "month")
OUT = os.path.join(HERE, "months_summary.json" if TAG == "month" else "months_summary_%s.json" % TAG)


def month_args(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    ny, nm = (y, m + 1) if m < 12 else (y + 1, 1)
    start, end = "%d-%02d-01T00:00:00" % (y, m), "%d-%02d-01T00:00:00" % (ny, nm)
    if ym >= "2026-10":                          # our own recording (exact); it ends today
        end = os.environ.get("BOTSIM_OCT_END") or time.strftime("%Y-%m-%dT00:00:00", time.gmtime())   # 2026-10-31: same end as a run to compare with
        return start, end, []
    bars = "ticks_archive_BTCUSD/bars_%d-%02d.npz+ticks_archive_BTCUSD/bars_%d-%02d.npz" % (py, pm, y, m)
    return start, end, ["--bars", bars, "--ticks", "ticks_archive_BTCUSD"]


def summarize(ym, tag):
    sb = os.path.join(HERE, "runs", "%s_%s" % (tag, ym + "-01"))
    try:
        br = json.load(open(os.path.join(sb, "sim_broker.json")))
    except Exception:
        return {"month": ym, "error": "no result"}
    W = L = 0
    killed = False
    for ln in open(os.path.join(sb, "bos_bot_valere.log"), encoding="utf-8", errors="replace"):
        if re.search(r" WIN [+-]", ln):
            W += 1
        elif re.search(r" LOSS [+-]", ln):
            L += 1
        if "KILL" in ln or "kill line" in ln.lower():
            killed = True
    return {"month": ym, "net": round(float(br["balance"]) - 200.0, 2), "end_balance": round(float(br["balance"]), 2),
            "wins": W, "losses": L, "killed": killed}


def main():
    months = sys.argv[1:] or ["2026-%02d" % m for m in range(1, 11)]
    done = {}
    if os.path.exists(OUT):
        done = {r["month"]: r for r in json.load(open(OUT)) if "net" in r}
    todo = [m for m in months if m not in done]
    running = {}
    while todo or running:
        while todo and len(running) < PAR:
            # a month whose archive files are not downloaded yet waits; the next ready month goes first
            ready = [m for m in todo if all(os.path.exists(os.path.join(STUDY, f)) for f in
                                            (month_args(m)[2][1].split("+") if month_args(m)[2] else []))]
            if not ready:
                break
            ym = ready[0]
            todo.remove(ym)
            start, end, extra = month_args(ym)
            tag = TAG
            cmd = [sys.executable, os.path.join(HERE, "run_sim.py"), "--acct", "valere", "--start", start, "--end", end, "--tag", tag, "--fresh", "--balance", "200"] + extra
            lf = open(os.path.join(HERE, "runs", "%s_%s.out" % (tag, ym)), "w")
            running[ym] = (subprocess.Popen(cmd, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT), tag, time.time())
            print(time.strftime("%H:%M:%S"), "start", ym, start, "->", end, flush=True)
        for ym, (p, tag, t0) in list(running.items()):
            if p.poll() is not None:
                del running[ym]
                r = summarize(ym, tag)
                r["wall_h"] = round((time.time() - t0) / 3600, 2)
                done[ym] = r
                json.dump([done[k] for k in sorted(done)], open(OUT, "w"), indent=1)
                print(time.strftime("%H:%M:%S"), "done", r, flush=True)
        time.sleep(30)
    neg = sum(1 for r in done.values() if r.get("net", 0) < 0)
    print("months negative: %d of %d" % (neg, len(done)), flush=True)


if __name__ == "__main__":
    main()
