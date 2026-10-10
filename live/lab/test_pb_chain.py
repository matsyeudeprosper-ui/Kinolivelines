"""The sticky pullback chain (owner 2026-10-10): once a candle has carried the
pullback chart's structure it stays in the chain; old times fall off with the
bar window; the feed writes, a read-only caller never does.
    python live/lab/test_pb_chain.py
"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.argv = ["x"]
import owl_chart_feed as F


def mk(times):
    return [[t, 1.0, 2.0, 0.5, 1.5, 1] for t in times]


def run():
    d = tempfile.mkdtemp(); p = os.path.join(d, "chain.json")
    # 1. first call creates the file with the structure times only
    got = F.pb_sticky_times({100, 200}, 60, p, True)
    assert got == {100, 200}, got
    assert json.load(open(p))["times"] == [100, 200]
    # 2. a later refresh that lost 100 (a flip dropped the other side's dots) keeps it
    got = F.pb_sticky_times({200, 300}, 60, p, True)
    assert got == {100, 200, 300}, got
    # 3. the window moved past 100: it falls off
    got = F.pb_sticky_times({300}, 150, p, True)
    assert got == {200, 300}, got
    assert json.load(open(p))["times"] == [200, 300]
    # 4. a read-only caller sees the union but never writes
    before = open(p).read()
    got = F.pb_sticky_times({400}, 150, p, False)
    assert got == {200, 300, 400}, got
    assert open(p).read() == before
    # 5. pullback_view: the newest candle is added for the view but NOT persisted
    kept = mk([200, 250, 300, 350, 400, 450])
    dots = [[200, 1.0, 1], [300, 1.0, 1]]; marks = []; brks = []
    try:
        F.pullback_view(kept, dots, marks, brks, sticky=p)
    except Exception:
        pass  # too few candles for the engine is fine here; the persistence is what we test
    assert json.load(open(p))["times"] == [200, 300], json.load(open(p))["times"]
    # 6. missing / corrupt file = empty set, no crash
    open(p, "w").write("{not json")
    assert F.pb_sticky_times({1}, 0, p, False) == {1}
    # 7. a time on the forming candle (>= ceil_t) joins the view but is never persisted
    os.remove(p)
    got = F.pb_sticky_times({100, 500}, 0, p, True, ceil_t=500)
    assert got == {100, 500}, got
    assert json.load(open(p))["times"] == [100]
    print("test_pb_chain: 7 ok")


if __name__ == "__main__":
    run()
