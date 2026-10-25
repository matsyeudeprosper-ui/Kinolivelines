"""run_sim.py - run the REAL live bot (structure_bos_bot.py) and its chart feed on a fake MetaTrader + virtual clock
fed with the broker's own candles and ticks, then compare its log with the real account's log (botsim, 2026-10-25).

Owner 2026-10-25: "the backtest must get the same results as reality ... and auto-adjust when the strategy changes".
There is no second copy of the strategy here: the sandbox is a COPY of live/*.py taken at run time, so whatever the
bot does today is what is replayed.

    python study/botsim/run_sim.py --acct valere --start 2026-10-16T08:59:01 --end 2026-10-25T07:30
"""
import argparse
import datetime as _real_dt
import io
import json
import os
import re
import shutil
import sys
import time as _real_time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
ROOT = os.path.dirname(STUDY)
LIVE = os.path.join(ROOT, "live")
sys.path.insert(0, HERE)
import simclock as SC          # noqa: E402
import fakemt5 as FM           # noqa: E402

ACCTS = {"valere": {"uid": "u224016179", "login": 224016179, "log": "bos_bot_valere.log", "state": "bos_state_valere.json",
                    "bars": "bars_u224016179.npz", "ticks": ["ticks_u224016179", "ticks_u224016179_forward"]}}


def ts(s):
    s = s.replace("Z", "+00:00")
    d = _real_dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=_real_dt.timezone.utc)
    return d.timestamp()


def load_ticks(dirs, t0, t1):
    T, Bd, Ak = [], [], []
    for d in dirs:
        p = os.path.join(STUDY, d)
        if not os.path.isdir(p):
            continue
        for f in sorted(os.listdir(p)):
            m = re.match(r"BTCUSD_(\d{4}-\d{2}-\d{2})\.npz$", f)
            if not m:
                continue
            day = ts(m.group(1) + "T00:00:00")
            if day + 86400 < t0 or day > t1:
                continue
            z = np.load(os.path.join(p, f))
            T.append(z["time_msc"]); Bd.append(z["bid"]); Ak.append(z["ask"])
    t = np.concatenate(T); o = np.argsort(t, kind="stable")
    t, b, a = t[o], np.concatenate(Bd)[o], np.concatenate(Ak)[o]
    keep = np.concatenate([[True], np.diff(t) > 0])
    return t[keep], b[keep], a[keep]


def state_from_log(logf, t0):
    """the bot's state at t0, rebuilt from its own log (no state snapshot exists): debt, chest, banked, trades, streak"""
    debt = chest = banked = 0.0
    trades = streak = 0
    bal = None
    for ln in open(logf, encoding="utf-8", errors="replace"):
        m = re.match(r"(\S+) ", ln)
        if not m:
            continue
        try:
            t = ts(m.group(1))
        except Exception:
            continue
        if t >= t0:
            break
        m2 = re.search(r"debt \$([0-9.]+) \(peak [^)]*\), chest \$([0-9.]+) - bot net ([+-]?[0-9.]+) \((\d+) trades\)", ln)
        if m2:
            debt, chest, banked, trades = float(m2.group(1)), float(m2.group(2)), float(m2.group(3)), int(m2.group(4))
        m3 = re.match(r"\S+ (WIN|LOSS) [+-]", ln)
        if m3:
            streak = streak + 1 if m3.group(1) == "LOSS" else 0
        m4 = re.search(r"BOS-BOT starting on \d+ balance ([0-9.]+)", ln) or re.search(r"lot resized to [0-9.]+ \(balance \$([0-9.]+)", ln)
        if m4:
            bal = float(m4.group(1))
    return {"debt": debt, "chest": chest, "banked": banked, "trades": trades, "killed": False, "last_bar": 0, "open_lot": 0.0,
            "loss_streak": streak, "add": None}, bal


def balance_at(logf, t0):
    """the account balance at t0: the start line at/after t0 within a minute, else the last one before"""
    best = None
    for ln in open(logf, encoding="utf-8", errors="replace"):
        m = re.match(r"(\S+) BOS-BOT starting on \d+ balance ([0-9.]+)", ln)
        if m:
            t = ts(m.group(1))
            if t <= t0 + 60:
                best = float(m.group(2))
            else:
                break
    return best


def build_sandbox(sb, acct, st0):
    if os.path.exists(sb):
        shutil.rmtree(sb)
    os.makedirs(os.path.join(sb, "robots"))
    for f in os.listdir(LIVE):
        if f.endswith(".py"):
            shutil.copy2(os.path.join(LIVE, f), sb)
    for f in os.listdir(os.path.join(LIVE, "robots")):
        if f.endswith(".py"):
            shutil.copy2(os.path.join(LIVE, "robots", f), os.path.join(sb, "robots"))
    for f in ("owl_packages.json",):
        shutil.copy2(os.path.join(LIVE, f), sb)
    A = ACCTS[acct]
    json.dump([{"id": A["uid"], "name": "sim", "terminal": "SIM", "mt5_login": A["login"], "login": A["login"],
                "mt5_server": "Exness-MT5Real30", "mt5_password": "sim", "trade": True}],
              open(os.path.join(sb, "owl_nest_users.json"), "w"))
    json.dump({"mt5_password": "sim"}, open(os.path.join(sb, "owl_secrets.json"), "w"))
    json.dump(st0, open(os.path.join(sb, A["state"]), "w"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--acct", default="valere")
    ap.add_argument("--start", default="2026-10-16T08:59:01")
    ap.add_argument("--end", default="2026-10-25T07:30:00")
    ap.add_argument("--real-compute", action="store_true", help="the bot's own compute time counts as time")
    ap.add_argument("--feed-every", type=float, default=10.0)
    ap.add_argument("--tag", default="")
    ap.add_argument("--rev", default="", help="git revision of live/structure_bos_bot.py to run (default: the current file)")
    ap.add_argument("--stall", action="append", default=[], help="ISO_TIME,SECONDS: the bot is busy then (replay a live stall)")
    ap.add_argument("--net-lag", type=float, default=0.0, help="s a tick takes to reach the terminal")
    a = ap.parse_args()
    A = ACCTS[a.acct]
    t0, t1 = ts(a.start), ts(a.end)
    sb = os.path.join(HERE, "runs", (a.tag or a.acct) + "_" + a.start[:10])
    logf = os.path.join(LIVE, A["log"])
    st0, bal_log = state_from_log(logf, t0)
    bal = balance_at(logf, t0) or bal_log or 200.0
    build_sandbox(sb, a.acct, st0)
    if a.rev:                                   # the bot as it was at that revision (what really traded then)
        import subprocess
        src = subprocess.run(["git", "-C", ROOT, "show", "%s:live/structure_bos_bot.py" % a.rev], capture_output=True).stdout
        assert src, "no such revision"
        open(os.path.join(sb, "structure_bos_bot.py"), "wb").write(src)
        print("bot from revision", a.rev, flush=True)
    print("sandbox", sb, "| start state", st0, "| balance", bal, flush=True)

    bars = np.load(os.path.join(STUDY, A["bars"]))["R"]
    ticks = load_ticks(A["ticks"], t0 - 3 * 86400, t1)
    print("bars", len(bars), "ticks", len(ticks[0]), flush=True)

    clock = SC.Clock(t0, t1, real_compute=False)        # switched on when the BOT starts (set-up is not the bot's time)
    broker = FM.Broker(clock, bars, ticks, login=A["login"], balance=bal)
    broker.net_lag = a.net_lag
    fake = FM.FakeMT5(broker)

    # the sandbox modules see the fake MetaTrader, the virtual clock and the virtual datetime
    ftime = SC.time_module(clock)
    fdt = type(sys)("datetime")
    for k in dir(_real_dt):
        if not k.startswith("__"):
            setattr(fdt, k, getattr(_real_dt, k))
    fdt.datetime = SC.datetime_class(clock)
    sys.modules["MetaTrader5"] = fake
    sys.modules["time"] = ftime
    sys.modules["datetime"] = fdt
    sys.path.insert(0, sb)
    sys.path.insert(0, os.path.join(sb, "robots"))
    os.chdir(sb)

    out = io.open(os.path.join(sb, "sim_stdout.txt"), "w", encoding="utf-8")
    real_stdout = sys.stdout
    sys.stdout = out

    import owl_chart_feed as FEED
    # the sticky pullback chain: built causally over the 8000 bars before the start (the live one exists since 10-10)
    json.dump({"times": [], "updated": int(t0) - 8000 * 60}, open(FEED.PB_CHAIN, "w"))
    try:
        FEED.pb_catch_up()
    except Exception as e:
        print("catch-up failed", e, flush=True)

    def feed_job(now):
        try:
            FEED.tick_once()
        except Exception as e:
            print("feed error", type(e).__name__, e, flush=True)
    feed_job(clock.now)
    clock.every(a.feed_every, feed_job, (int(t0) // 60 * 60) + 60 + 2)

    sys.argv = ["structure_bos_bot.py", a.acct]
    wall = _real_time.perf_counter()
    clock.now = t0
    clock._sync = _real_time.perf_counter()
    clock.real_compute = a.real_compute
    for x in a.stall:
        _t, _d = x.split(",")
        clock.stalls.append([ts(_t), float(_d)])
    try:
        import structure_bos_bot as BOT
        BOT.main()
    except SC.SimEnd:
        pass
    finally:
        sys.stdout = real_stdout
        out.close()
    print("simulated %.1f h in %.0f s wall, %d sleeps; broker balance %.2f, %d deals" % (
        (clock.now - t0) / 3600, _real_time.perf_counter() - wall, clock.sleeps, broker.balance, len(broker.deals)), flush=True)
    json.dump({"fills": broker.fills, "balance": broker.balance}, open(os.path.join(sb, "sim_broker.json"), "w"), default=str)


if __name__ == "__main__":
    main()
