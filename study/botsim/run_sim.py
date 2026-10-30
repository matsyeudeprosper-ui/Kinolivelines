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
                    "bars": "bars_u224016179.npz", "ticks": ["ticks_u224016179", "ticks_u224016179_forward"]},
         # 2026-10-30 (owner: "do the last week test"): the bot's own demo kept trading through the real-money pause; same broker
         # feed (Valere's recording) - its own tick recording stops 10-09
         "reference": {"uid": "u477508138", "login": 477508138, "log": "bos_bot_u477508138.log", "state": "bos_state_u477508138.json",
                       "bars": "bars_u224016179.npz", "ticks": ["ticks_u477508138", "ticks_u224016179_forward"]}}


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
    if not os.environ.get("BOTSIM_NOFASTIDX"):    # 2026-10-26 (speed): exact patch of the sandbox copy only, see fastidx.py
        import fastidx
        _fp = os.path.join(sb, "owl_chart_feed.py")
        _fs = open(_fp, encoding="utf-8-sig").read()
        open(_fp, "w", encoding="utf-8").write(fastidx.patch_source(_fs))
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
    ap.add_argument("--order-lag", type=float, default=0.0, help="s between the sim's entry and the fill (real median ~2 s more)")
    ap.add_argument("--order-lag-real", action="store_true", help="replay each real entry's own delay from the real log")
    ap.add_argument("--order-lag-deals", default="", help="real deals json [(time, pos, entry, ...)]: each entry fills at its real "
                                                             "deal time (the log line is written seconds after the fill)")
    ap.add_argument("--fresh", action="store_true", help="start with no debt, no history and --balance (month studies)")
    ap.add_argument("--balance", type=float, default=200.0)
    ap.add_argument("--bars", default="", help="M1 candles npz (key R) instead of the account's recorded ones; several with +")
    ap.add_argument("--ticks", default="", help="tick folder(s) under study/ instead of the account's, comma separated")
    a = ap.parse_args()
    A = ACCTS[a.acct]
    t0, t1 = ts(a.start), ts(a.end)
    sb = os.path.join(HERE, "runs", (a.tag or a.acct) + "_" + a.start[:10])
    logf = os.path.join(LIVE, A["log"])
    st0, bal_log = state_from_log(logf, t0)
    bal = balance_at(logf, t0) or bal_log or 200.0
    if a.fresh:
        st0 = {"debt": 0.0, "chest": 0.0, "banked": 0.0, "trades": 0, "killed": False, "last_bar": 0, "open_lot": 0.0,
               "loss_streak": 0, "add": None}
        bal = a.balance
    build_sandbox(sb, a.acct, st0)
    if a.rev:                                   # the bot as it was at that revision (what really traded then)
        import subprocess
        src = subprocess.run(["git", "-C", ROOT, "show", "%s:live/structure_bos_bot.py" % a.rev], capture_output=True).stdout
        assert src, "no such revision"
        open(os.path.join(sb, "structure_bos_bot.py"), "wb").write(src)
        print("bot from revision", a.rev, flush=True)
    print("sandbox", sb, "| start state", st0, "| balance", bal, flush=True)

    if a.bars:                                  # 2026-10-26: other data (the Exness public archive for months before our recording)
        bars = np.concatenate([np.load(os.path.join(STUDY, f))["R"] for f in a.bars.split("+")])
        bars = bars[np.argsort(bars["time"], kind="stable")]
    else:
        bars = np.load(os.path.join(STUDY, A["bars"]))["R"]
    ticks = load_ticks(a.ticks.split(",") if a.ticks else A["ticks"], t0 - 3 * 86400, t1)
    print("bars", len(bars), "ticks", len(ticks[0]), flush=True)

    clock = SC.Clock(t0, t1, real_compute=False)        # switched on when the BOT starts (set-up is not the bot's time)
    broker = FM.Broker(clock, bars, ticks, login=A["login"], balance=bal)
    broker.net_lag = a.net_lag
    broker.order_lag = a.order_lag
    if a.order_lag_deals:                      # 2026-10-26: the broker's own deal times are the truth (log lines come after the fill)
        _od = {}
        for r in json.load(open(a.order_lag_deals)):
            if int(r[2]) == 0 and t0 <= float(r[0]) <= t1:          # entry IN
                k = int(r[0]) // 60 * 60
                _od.setdefault(k, max(0.0, float(r[0]) - k - 1.0))   # the sim sends at :01
        broker.order_lag_at = _od
        print("real deal delays:", {_real_time.strftime("%m-%d %H:%M", _real_time.gmtime(k)): v for k, v in sorted(_od.items())}, flush=True)
    if a.order_lag_real:                        # each real entry's second after the minute, minus the sim's own (1 s)
        _oa = {}
        for ln in open(logf, encoding="utf-8", errors="replace"):
            m = re.match(r"(\S+) (?:FLIP-)?BOS ENTRY", ln) or re.match(r"(\S+) \S+ ENTRY:", ln)
            if m:
                try:
                    tt = ts(m.group(1))
                except Exception:
                    continue
                if t0 <= tt <= t1:
                    _oa[int(tt) // 60 * 60] = max(0.0, (tt - int(tt) // 60 * 60) - 1.0)
        broker.order_lag_at = _oa
        print("real entry delays:", {_real_time.strftime("%m-%d %H:%M", _real_time.gmtime(k)): v for k, v in sorted(_oa.items())}, flush=True)
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

    # 2026-10-26 (speed, profile: json.dump ~25% of the steady time): json.dump() always takes the pure-Python encoder, json.dumps()
    # the C one - same text, byte for byte. The sim writes the same files, faster. Live code is untouched.
    import json as _js
    _jdump0 = _js.dump

    def _jdump_fast(obj, fp, **kw):
        if kw.get("indent") is None and not kw.get("cls"):
            fp.write(_js.dumps(obj, **kw))
        else:
            _jdump0(obj, fp, **kw)
    if not os.environ.get("BOTSIM_NOFASTJSON"):
        _js.dump = _jdump_fast
    import owl_chart_feed as FEED
    # 2026-10-26 (speed, profile: build() = ~70% of the time, called ~75 times a simulated minute on the same candles):
    # build() is a pure function of its candles, so the same candles give the same answer - a memo keyed on the exact bytes
    # of the candles changes nothing in what the bot sees. Only the simulator holds the memo; live code is untouched.
    import hashlib as _hl
    _build0, _memo = FEED.build, {}

    import slidebuild as _SB
    _sl = {"base": None, "S": None, "prev": None}

    def _build_memo(rates):
        # a window of the SAME array one candle further than the previous call (the feed's start-up replay): the exact
        # sliding build. Anything else (a fresh array each feed tick) goes to the memo below.
        try:
            bs = rates.base
            if bs is not None and getattr(bs, "dtype", None) == rates.dtype and len(rates) > 100:
                off = int((rates.__array_interface__["data"][0] - bs.__array_interface__["data"][0]) // rates.itemsize)
                end = off + len(rates)
                pv, _sl["prev"] = _sl["prev"], (bs, off, end)
                if pv is not None and pv[0] is bs and off >= 0 and end <= len(bs) and (off, end) in ((pv[1] + 1, pv[2] + 1), (pv[1], pv[2] + 1)):
                    if _sl["base"] is not bs:
                        _sl["base"], _sl["S"] = bs, _SB.Slider(bs)
                        _sl["S"].keep(pv[1], pv[2])            # the previous window, to start from
                    if (off, end) == (pv[1], pv[2] + 1):       # the window still grows from the start (before it reaches full size)
                        _sl["S"].idx = None
                    return _sl["S"].kept(off, end)
        except Exception:
            pass
        try:
            k = _hl.blake2b(rates.tobytes(), digest_size=16).digest()
        except Exception:
            return _build0(rates)
        v = _memo.get(k)
        if v is None:
            v = _build0(rates)
            if len(_memo) > 4000:
                _memo.clear()
            _memo[k] = v
        return [list(x) for x in v]                # a fresh copy: callers may change the lists they get
    if not os.environ.get("BOTSIM_NOMEMO"):
        FEED.build = _build_memo
    # the sticky pullback chain: built causally over the 8000 bars before the start (the live one exists since 10-10)
    json.dump({"times": [], "updated": int(t0) - 8000 * 60}, open(FEED.PB_CHAIN, "w"))
    _tcu = _real_time.perf_counter()
    try:
        FEED.pb_catch_up()
    except Exception as e:
        print("catch-up failed", e, flush=True)
    real_stdout.write("catch-up %.1f s\n" % (_real_time.perf_counter() - _tcu)); real_stdout.flush()

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
