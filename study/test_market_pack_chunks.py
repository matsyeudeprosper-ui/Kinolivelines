"""Exactness check for market_pack's chunked sticky walk (2026-10-14): on BTC bars, a single causal walk and the
same walk split in 3 chunks (each re-walking `win` bars before its range) must give IDENTICAL pullback states at
every bar. Small window (500) so it runs in a couple of minutes; the argument does not depend on the window size.
    python test_market_pack_chunks.py
"""
import sys, os, time, tempfile
sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
import numpy as np
import market_pack as MP


def single(RW, win, want):
    import owl_chart_feed as F
    import tick_engine_pbgate_sticky as K
    S = set(); states = {}; off = win
    for i in range(win - 1, len(RW)):
        kept = F.build(RW[i - win + 1:i + 1])
        if len(kept) < 3:
            continue
        bk = []; dots, marks, trend, *_ = F.engine(kept, brk_out=bk)
        if trend:
            dots = [x for x in dots if x[2] == trend]
        S |= {t for t in ({x[0] for x in dots} | {m[0] for m in marks} | {q[0] for q in bk}) if t < kept[-1][0]}
        S = {t for t in S if t >= kept[0][0]}
        j = i - off
        if j in want:
            try:
                states[j] = K.pb_view_sticky(kept, dots, marks, bk, S)
            except Exception:
                states[j] = (0, 0, None, None)
    return states


if __name__ == "__main__":
    win, n = 500, 3000
    B = np.load(os.path.join(HERE, "dev_bars_2026-10-09b.npz"))["R"]
    RW = B[:win + n]
    want = set(range(0, n))
    t0 = time.time(); s1 = single(RW, win, want); t1 = time.time() - t0
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "rw.npz"); np.savez(p, R=RW)
        lo, hi = win - 1, len(RW); step = (hi - lo + 2) // 3
        jobs = [(p, a, min(hi, a + step), sorted(want), win) for a in range(lo, hi, step)]
        from multiprocessing import get_context
        t0 = time.time()
        with get_context("spawn").Pool(len(jobs)) as pool:
            parts = pool.map(MP._walk_chunk, jobs)
        t2 = time.time() - t0
    s2 = {}
    for q in parts:
        s2.update(q)
    diff = [j for j in want if s1.get(j) != s2.get(j)]
    print("single %d states (%.0fs) | chunked %d states (%.0fs) | differences: %d" % (len(s1), t1, len(s2), t2, len(diff)))
    print("EXACT" if not diff and len(s1) == len(s2) else "NOT EXACT: first %s" % diff[:5])
    sys.exit(0 if not diff else 1)
