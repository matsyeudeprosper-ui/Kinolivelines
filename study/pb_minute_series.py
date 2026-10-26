"""pb_minute_series.py - the PULLBACK CHART, minute by minute, over the robot bench's dataset (owner 2026-10-26: "the higher
timeframe is the pullback chart" - his robot reads it, so the bench must too).

For every 1-minute candle of the dataset (tick_engine.R, with its 8000-bar warm-up before it) the live feed's pullback chart is
rebuilt CAUSALLY as the feed builds it each minute: build() over the last 8000 bars, the minute structure's dots / marks /
breaks, the STICKY set of structure times (owl_pb_chain semantics), pb_join(pb_quiet(pb_join(...))), the engine on that chain.
Per minute it stores:
    pb_dir                  direction of the last FINISHED pullback candle (+1 / -1)   (chain[-2]; chain[-1] is the one in progress)
    pb_open pb_high pb_low pb_close   that candle
    pb_live_dir             direction of the pullback candle in progress (chain[-1])
    pb_trend                the pullback chart's own trend (+1 / -1 / 0)
Speed: botsim's exact sliding build (slidebuild.Slider) and the exact fastidx engine (both proved identical).
Output: study/pb_minute_series.npz (+ .json fingerprint). python study/pb_minute_series.py
"""
import hashlib, importlib.util, json, os, sys, tempfile, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(os.path.dirname(HERE), "live")
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "botsim")); sys.path.insert(0, LIVE)
import tick_engine as E
import slidebuild as SB
import fastidx

OUT = os.path.join(HERE, "pb_minute_series.npz")
WARM_NPZ = os.path.join(HERE, "dev_bars_2026-10-09b_warmup.npz")

src = open(os.path.join(LIVE, "owl_chart_feed.py"), encoding="utf-8-sig").read()
tmp = tempfile.mkdtemp()
open(os.path.join(tmp, "feed_fast.py"), "w", encoding="utf-8").write(fastidx.patch_source(src))
json.dump({"mt5_password": "sim"}, open(os.path.join(tmp, "owl_secrets.json"), "w"))
sp = importlib.util.spec_from_file_location("feed_fast", os.path.join(tmp, "feed_fast.py"))
F = importlib.util.module_from_spec(sp); sp.loader.exec_module(F)
WIN = F.RAW_BARS


def fingerprint():
    h = hashlib.sha256()
    h.update(E.META["sha256"].encode()); h.update(open(WARM_NPZ, "rb").read()[:4096]); h.update(str(WIN).encode())
    h.update(src.encode()); h.update(open(__file__, "rb").read())
    return h.hexdigest()[:16]


def main():
    R = E.R
    W = np.load(WARM_NPZ)["R"]
    assert int(W["time"][-1]) < int(R["time"][0])
    RW = np.concatenate([W, R]); off = len(W); n = len(R)
    cols = {k: np.full(n, np.nan) for k in ("pb_dir", "pb_open", "pb_high", "pb_low", "pb_close", "pb_live_dir", "pb_trend")}
    Sl = SB.Slider(RW)
    S = set()
    t0 = time.time()
    first = max(WIN - 1, off - 1)
    for i in range(first, len(RW)):
        kept = Sl.kept(i - WIN + 1, i + 1)
        if len(kept) < 3:
            continue
        bk = []
        dots, marks, trend, *_ = F.engine(kept, brk_out=bk)
        if trend:
            dots = [d for d in dots if d[2] == trend]
        S |= {t for t in ({d[0] for d in dots} | {m[0] for m in marks} | {b[0] for b in bk}) if t < kept[-1][0]}
        S = {t for t in S if t >= kept[0][0]}
        j = i - off
        if j < 0:
            continue
        want = {d[0] for d in dots} | {m[0] for m in marks} | {b[0] for b in bk} | S
        want.add(kept[-1][0])
        cands = [c for c in kept if c[0] in want]
        chain = F.pb_join(F.pb_quiet(F.pb_join(cands)))
        if len(chain) >= 2:
            c = chain[-2]
            cols["pb_dir"][j] = c[5]; cols["pb_open"][j] = c[1]; cols["pb_high"][j] = c[2]; cols["pb_low"][j] = c[3]; cols["pb_close"][j] = c[4]
            cols["pb_live_dir"][j] = chain[-1][5]
        if len(chain) >= 3:
            r2 = F.engine(chain, brk_out=[])
            cols["pb_trend"][j] = int(r2[2] or 0)
        if j % 2000 == 0:
            el = time.time() - t0
            print("pb walk %d / %d  (%.0f s, ~%.0f min left)" % (j, n, el, el / max(1, j + 1) * (n - j) / 60), flush=True)
    np.savez_compressed(OUT, time=R["time"].astype(np.int64), **cols)
    json.dump({"fingerprint": fingerprint(), "dataset_sha": E.META["sha256"], "bars": int(n), "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "seconds": round(time.time() - t0)}, open(OUT.replace(".npz", ".json"), "w"))
    print("done %s (%.0f s)" % (OUT, time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
