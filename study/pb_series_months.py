"""pb_series_months.py - the PULLBACK CHART minute by minute for other months (2026-11-07, owner: "test the stop >= 200 version
on months it has never seen - if it does not slow the VPS").

The same causal rebuild as pb_minute_series.py (the live feed's own code: build(), the minute structure, the sticky chain,
pb_join(pb_quiet(pb_join(...)))), on the broker's public 1-minute archive, one month at a time, warmed up on the month before.
Output study/pb_series/<YYYY-MM>.npz (time, open, high, low, close, spread + pb_dir pb_open pb_high pb_low pb_close
pb_live_dir pb_trend). The robot's own study/pb_minute_series.npz is never touched. Run at low priority, one month at a time:
    python study/pb_series_months.py 2026-01 2026-02 ...
"""
import importlib.util, json, os, sys, tempfile, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(os.path.dirname(HERE), "live")
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "botsim")); sys.path.insert(0, LIVE)
import slidebuild as SB
import fastidx

OUTD = os.path.join(HERE, "pb_series")
src = open(os.path.join(LIVE, "owl_chart_feed.py"), encoding="utf-8-sig").read()
tmp = tempfile.mkdtemp()
open(os.path.join(tmp, "feed_fast.py"), "w", encoding="utf-8").write(fastidx.patch_source(src))
json.dump({"mt5_password": "sim"}, open(os.path.join(tmp, "owl_secrets.json"), "w"))
sp = importlib.util.spec_from_file_location("feed_fast", os.path.join(tmp, "feed_fast.py"))
F = importlib.util.module_from_spec(sp); sp.loader.exec_module(F)
WIN = F.RAW_BARS


def arc(m):
    return np.load(os.path.join(HERE, "ticks_archive_BTCUSD", "bars_%s.npz" % m))["R"]


def prev_month(m):
    y, mo = int(m[:4]), int(m[5:])
    return "%d-%02d" % ((y, mo - 1) if mo > 1 else (y - 1, 12))


def one(m):
    out = os.path.join(OUTD, "%s.npz" % m)
    if os.path.exists(out):
        print(m, "exists", flush=True)
        return
    R = arc(m)
    W = arc(prev_month(m))[-(WIN + 500):]
    RW = np.concatenate([W, R]); off = len(W); n = len(R)
    cols = {k: np.full(n, np.nan) for k in ("pb_dir", "pb_open", "pb_high", "pb_low", "pb_close", "pb_live_dir", "pb_trend")}
    Sl = SB.Slider(RW)
    S = set()
    t0 = time.time()
    for i in range(max(WIN - 1, off - 1), len(RW)):
        kept = Sl.kept(i - WIN + 1, i + 1)
        if len(kept) < 3:
            continue
        bk = []
        dots, marks, trend, _ch, nxt, inv, _nt, _it, _dr, flp, *_ = F.engine(kept, brk_out=bk)
        if trend:
            dots = [d for d in dots if d[2] == trend]
        S |= {t for t in ({d[0] for d in dots} | {mk[0] for mk in marks} | {b[0] for b in bk}) if t < kept[-1][0]}
        S = {t for t in S if t >= kept[0][0]}
        j = i - off
        if j < 0:
            continue
        want = {d[0] for d in dots} | {mk[0] for mk in marks} | {b[0] for b in bk} | S
        want.add(kept[-1][0])
        chain = F.pb_join(F.pb_quiet(F.pb_join([c for c in kept if c[0] in want])))
        if len(chain) >= 2:
            c = chain[-2]
            cols["pb_dir"][j] = c[5]; cols["pb_open"][j] = c[1]; cols["pb_high"][j] = c[2]; cols["pb_low"][j] = c[3]; cols["pb_close"][j] = c[4]
            cols["pb_live_dir"][j] = chain[-1][5]
        if len(chain) >= 3:
            cols["pb_trend"][j] = int(F.engine(chain, brk_out=[])[2] or 0)
        if j % 5000 == 0:
            el = time.time() - t0
            print("%s %d / %d (%.0f s, ~%.0f min left)" % (m, j, n, el, el / max(1, j + 1) * (n - j) / 60), flush=True)
    os.makedirs(OUTD, exist_ok=True)
    np.savez_compressed(out, time=R["time"].astype(np.int64), open=R["open"].astype(float), high=R["high"].astype(float),
                        low=R["low"].astype(float), close=R["close"].astype(float), spread=R["spread"].astype(float) * 0.01, **cols)
    print(m, "done (%.0f s)" % (time.time() - t0), flush=True)


if __name__ == "__main__":
    try:                                       # the live bots first
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
    except Exception:
        pass
    for m in sys.argv[1:]:
        one(m)
