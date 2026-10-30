"""sweep2.py (2026-10-30, Owl v2) - every variation, judged honestly.

~1200 versions over 3 families (break of structure, opening-range break, mean reversion) x stop/target/filters/breakeven.
Protocol fixed BEFORE looking: pick on one half of the year, judge on the other half, both ways round
(Jan-May -> Jun-Oct, Jun-Oct -> Jan-May). The judge half is compared with 60 random-direction replays of the same trades.
    python study/owl_v2/sweep2.py   -> sweep2.json, sweep2_verdict.json
"""
import itertools, json, os, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fastbt as F, signals as S

M5 = ["2026-%02d" % m for m in range(1, 6)]
M10 = ["2026-%02d" % m for m in range(6, 11)]


def scale(sig, rr):
    return [(i, d, sd, sd * rr) for (i, d, sd, _) in sig]


def variants():
    for tf, k, stop, mode in itertools.product([5, 15, 60, 240], [2, 3, 5], ["struct", "atr"], ["follow", "fade"]):
        base = S.bos(tf=tf, k=k, rr=1.0, stop=stop, m_atr=1.5, mode=mode)
        for flt in [None, "with", "against"]:
            sg = base if flt is None else S.filt_trend(base, htf=240, n=50, side=flt)
            for rr, be in itertools.product([0.8, 1.5, 2.5], [0.0, 0.5]):
                yield "bos tf%d k%d %s %s trend=%s rr%.1f be%.1f" % (tf, k, stop, mode, flt, rr, be), scale(sg, rr), be
    for h, mins, mode in itertools.product([0, 7, 8, 13, 14], [15, 30, 60, 120], ["follow", "fade"]):
        base = S.orb(start_h=h, mins=mins, rr=1.0, mode=mode)
        for rr, be in itertools.product([0.8, 1.5, 2.5], [0.0, 0.5]):
            yield "orb h%d m%d %s rr%.1f be%.1f" % (h, mins, mode, rr, be), scale(base, rr), be
    for tf, n, z, sz, rr in itertools.product([5, 15, 60], [20, 50], [2.0, 2.5, 3.0], [1.0, 2.0], [None, 1.0]):
        yield "mr tf%d n%d z%.1f sz%.1f rr%s" % (tf, n, z, sz, rr), S.meanrev(tf=tf, n=n, z=z, stop_z=sz, rr=rr), 0.0


def half(r, ms):
    return sum(r["months"][m] for m in ms), sum(r["months"][m] > 0 for m in ms)


def main():
    rows, keep = [], {}
    t0 = time.time()
    for lab, sg, be in variants():
        r = F.report(F.simulate(sg, be_frac=be), lab, quiet=True)
        r["be"] = be
        rows.append(r)
        keep[lab] = (sg, be)
        if len(rows) % 50 == 0:
            print(len(rows), "%.0fs" % (time.time() - t0), flush=True)
    json.dump(rows, open(os.path.join(HERE, "sweep2.json"), "w"), indent=0, default=float)
    V = {}
    for pick, judge, name in ((M5, M10, "pick Jan-May, judge Jun-Oct"), (M10, M5, "pick Jun-Oct, judge Jan-May")):
        cand = [r for r in rows if r["n"] >= 100]
        cand.sort(key=lambda r: -half(r, pick)[0])
        out = []
        for r in cand[:10]:
            sg, be = keep[r["label"]]
            jn, ju = half(r, judge)
            nulls = []
            for s in range(60):
                rr_ = F.report(F.simulate(S.random_like(sg, seed=s), be_frac=be), "", quiet=True)
                nulls.append(half(rr_, judge)[0])
            nulls = np.array(nulls)
            out.append({"label": r["label"], "pick_net": round(half(r, pick)[0], 1), "judge_net": round(jn, 1), "judge_months_up": int(ju),
                        "null_mean": round(float(nulls.mean()), 1), "null_sd": round(float(nulls.std()), 1),
                        "p": round(float((nulls >= jn).mean()), 3), "all_months": r["months"], "days": r["days_traded"]})
            print(name, "|", out[-1]["label"], "pick %+.0f judge %+.0f (%d/5 up) null %+.0f sd %.0f p %.2f" % (
                out[-1]["pick_net"], jn, ju, nulls.mean(), nulls.std(), out[-1]["p"]), flush=True)
        V[name] = out
    json.dump(V, open(os.path.join(HERE, "sweep2_verdict.json"), "w"), indent=1, default=float)
    print("done %.0fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
