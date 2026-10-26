"""test_fastidx.py - the fastidx patch must give EXACTLY the same swings() and engine() output as the live code, on real
candles (archive months, several window sizes, raw and filtered, with brk_out and snap). python study/botsim/test_fastidx.py"""
import importlib.util, json, os, sys, tempfile, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LIVE = os.path.join(ROOT, "live")
sys.path.insert(0, HERE)
import fastidx

src = open(os.path.join(LIVE, "owl_chart_feed.py"), encoding="utf-8-sig").read()
tmp = tempfile.mkdtemp()
open(os.path.join(tmp, "feed_fast.py"), "w", encoding="utf-8").write(fastidx.patch_source(src))
json.dump({"mt5_password": "sim"}, open(os.path.join(tmp, "owl_secrets.json"), "w"))   # the module reads it at import
sys.path.insert(0, LIVE)


def load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


A = load("feed_live", os.path.join(LIVE, "owl_chart_feed.py"))
B = load("feed_fast", os.path.join(tmp, "feed_fast.py"))
n = 0
ta = tb = 0.0
for ym in ("2026-01", "2026-04", "2026-07", "2026-09"):
    R = np.load(os.path.join(ROOT, "study", "ticks_archive_BTCUSD", "bars_%s.npz" % ym))["R"]
    for size in (600, 2000, 8000):
        for start in range(0, len(R) - size, max(1, (len(R) - size) // 12)):
            w = R[start:start + size]
            kept = A.build(w)
            assert len({k[0] for k in kept}) == len(kept), "duplicate candle times"
            raw = [[int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                    1 if r["close"] >= r["open"] else -1] for r in w]
            for series, snap in ((kept, None), (raw, kept)):
                assert A.swings(series) == B.swings(series)
                ba, bb = [], []
                t0 = time.perf_counter(); ra = A.engine(series, snap=snap, brk_out=ba); ta += time.perf_counter() - t0
                t0 = time.perf_counter(); rb = B.engine(series, snap=snap, brk_out=bb); tb += time.perf_counter() - t0
                assert json.dumps(ra, default=str) == json.dumps(rb, default=str) and ba == bb, (ym, size, start)
                n += 1
print("identical on %d engine runs; engine time live %.1f s -> patched %.1f s" % (n, ta, tb))
