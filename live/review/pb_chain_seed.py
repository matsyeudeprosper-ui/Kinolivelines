"""Seed the sticky pullback chain (owner 2026-10-10: "calculate the hline level
properly so we start on good ground").

Replays the last 8000 closed M1 bars CAUSALLY: at every bar the feed's own
build -> engine runs over the 8000 bars ending there (exactly what the live
feed did at that minute) and the structure times it found are added to the
set. The result is the chain the feed would hold today if it had been sticky
all along. It is written to live/owl_pb_chain.json (atomic), then the
pullback view is printed both ways (rebuilt-from-now vs sticky) and the number
of pullback trend changes along the walk for each, as evidence.

    python live/review/pb_chain_seed.py [--dry]        (--dry: no file written)
"""
import os, sys, json, time
LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIVE)
DRY = "--dry" in sys.argv; sys.argv = ["x"]
import MetaTrader5 as mt5
import owl_chart_feed as F

WIN = F.RAW_BARS            # 8000, the live window
STEP = 1


def want_of(kept):
    bk = []
    dots, marks, trend, *_ = F.engine(kept, brk_out=bk)
    if trend:
        dots = [d for d in dots if d[2] == trend]
    # closed candles only (same rule as the feed): the newest bar may still be forming
    return ({t for t in ({d[0] for d in dots} | {m[0] for m in marks} | {b[0] for b in bk}) if t < kept[-1][0]}), dots, marks, bk


def pb_of(kept, dots, marks, bk, sticky_set):
    want = {d[0] for d in dots} | {m[0] for m in marks} | {b[0] for b in bk}
    if sticky_set is not None:
        want |= {t for t in sticky_set if t >= kept[0][0]}
    want.add(kept[-1][0])
    cands = [c for c in kept if c[0] in want]
    chain = F.pb_join(F.pb_quiet(F.pb_join(cands)))
    if len(chain) < 3:
        return None
    bk2 = []
    d2, m2, tr2, ch2, nxt, inv, nxt_t, inv_t, dr2, flp, flp_t, fdir = F.engine(chain, brk_out=bk2)
    return {"trend": tr2, "choch": ch2, "next_bos": nxt, "invalid": inv, "flip_bos": flp,
            "last_break": (bk2[-1] if bk2 else None), "n_chain": len(chain)}


def main():
    assert F.connect(), "no terminal serves BTCUSD"
    R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 2 * WIN)
    assert R is not None and len(R) >= WIN + 100, "not enough bars"
    n = len(R); t0 = time.time()
    S = set(); flips_rebuilt = flips_sticky = 0; last_r = last_s = None
    for i in range(WIN - 1, n, STEP):
        kept = F.build(R[i - WIN + 1:i + 1])
        if len(kept) < 3:
            continue
        w, dots, marks, bk = want_of(kept)
        S |= w
        S = {t for t in S if t >= kept[0][0]}
        if (i - WIN + 1) % 500 == 0 or i == n - 1:
            pr = pb_of(kept, dots, marks, bk, None); ps = pb_of(kept, dots, marks, bk, S)
            print("%5d/%d  %s  rebuilt trend %2s  sticky trend %2s  |S|=%d  %.0fs" % (
                i - WIN + 1, n - WIN, time.strftime("%m-%d %H:%M", time.gmtime(int(R[i]["time"]))),
                pr and pr["trend"], ps and ps["trend"], len(S), time.time() - t0), flush=True)
        # trend-change counts along the walk (cheap enough: two small engines per bar)
        pr = pb_of(kept, dots, marks, bk, None); ps = pb_of(kept, dots, marks, bk, S)
        tr_r = pr["trend"] if pr else 0; tr_s = ps["trend"] if ps else 0
        if last_r is not None and tr_r != last_r: flips_rebuilt += 1
        if last_s is not None and tr_s != last_s: flips_sticky += 1
        last_r, last_s = tr_r, tr_s
    kept = F.build(R[n - WIN:n]); w, dots, marks, bk = want_of(kept)
    S |= w; S = {t for t in S if t >= kept[0][0]}
    now_r = pb_of(kept, dots, marks, bk, None); now_s = pb_of(kept, dots, marks, bk, S)
    print("\nwalk: %d bars, pullback trend changes: rebuilt-from-now %d, sticky %d" % (n - WIN + 1, flips_rebuilt, flips_sticky))
    print("NOW rebuilt :", now_r)
    print("NOW sticky  :", now_s)
    print("sticky set  : %d times, first %s" % (len(S), time.strftime("%m-%d %H:%M", time.gmtime(min(S))) if S else "-"))
    if not DRY:
        tmp = F.PB_CHAIN + ".tmp"
        json.dump({"times": sorted(int(t) for t in S), "updated": int(time.time()), "seeded": "causal walk %d bars" % (n - WIN + 1)}, open(tmp, "w"))
        os.replace(tmp, F.PB_CHAIN)
        print("written", F.PB_CHAIN)
    mt5.shutdown()


if __name__ == "__main__":
    main()
