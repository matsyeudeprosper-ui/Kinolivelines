"""Compte allocation policies - development replay v2 (ChatGPT review 6).

Corrections vs v1:
  * exposure split: main stop risk / contingent max add budget at entry /
    actual add risk at fill / planned total / committed total;
  * three drawdowns: daily-sampled realised (harness worst_debt), close-to-
    close realised (every closed result), marked-to-market bounds from the
    bar path (adverse extreme / bar close; main position only);
  * reference cost basis stated: A = spread-only reference state driving a
    cost-stressed policy; B = reference rebuilt under the same cost model;
  * "later slice" = ONE common calendar cutoff (bar at 2/3 of the pinned
    interval) for every policy and control; trade-count thirds kept as a
    separate diagnostic;
  * halves: "full-history reference" (as v1) AND a true cold start where the
    reference is rebuilt from the half only;
  * controls: every phase of each periodic schedule in a prespecified k set,
    and 20 prespecified cyclic block shifts (index-based over the complete
    eligible stream, never 'runs out'); exposure distributions reported;
  * paired power: per-calendar-day policy-minus-baseline differences, block
    bootstrap (nominated block 5 days ~ 20 opportunities; 3 / 10 shown as
    sensitivities) for the mean net difference and the drawdown ratio.
Candidates: directional MAIN+ADDS = primary (as nominated); directional
MAIN-only = exploratory attribution arm; global = parked, reported once.
Data: pinned development interval (study/dev_bars_2026-10-09.npz) - never a
holdout. Results are gross after spread, before the stated execution drag.
Harness ambiguity rule (bar hits both barriers) is pessimistic."""
import sys, json, bisect, random, statistics
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.argv = ["x"]
import harness as H
from compte_controller import CompteController
import dev_dataset
sym, R, META = dev_dataset.load()
print("pinned dataset:", META["symbol"], META["bars"], "bars", META["first_bar"], "->", META["last_bar"], "sha", META["sha256"], flush=True)
T_CUT = int(R["time"][int(len(R) * 2 / 3)])
MID = len(R) // 2
REF_CFG = {"n_cont": 999, "bullets": 0, "jar": False}
OUT = {"dataset": META, "t_cut": T_CUT}


# ---------------- reference streams (fixed 0.02, no recovery), with close times
def reference(Rs, drag):
    H.TRACE = []; H.simulate(Rs, 7.0, dict(REF_CFG, drag=drag))
    ref = sorted([x for x in H.TRACE if x.get("pnl") is not None and x.get("tc")], key=lambda x: x["tc"]); H.TRACE = None
    return ref


class States:
    def __init__(self, ref):
        self.ref = ref; self.tc = [x["tc"] for x in ref]; self.cache = {}
    def at(self, t):
        n = bisect.bisect_left(self.tc, t)
        if n in self.cache: return self.cache[n]
        out = {}
        for name, flt in (("global", lambda d: True), ("buy", lambda d: d == 1), ("sell", lambda d: d == -1)):
            c = CompteController()
            for x in self.ref[:n]:
                if flt(x["d"]): c.feed(x["pnl"])
            out[name] = (c.state["trend"], c.state["choch"])
        self.cache[n] = out; return out


def reduce(trend, choch):
    return trend == -1 and choch != 1


CUR = {"t": None, "d": None}
H.DIRGATE = lambda t, d: (CUR.update(t=t, d=d) or True)


def policy_hook(kind, states):
    sched = []
    def hook(_all):
        st = states.at(CUR["t"])
        if kind == "global": m = 0.5 if reduce(*st["global"]) else 1.0
        elif kind == "directional": m = 0.5 if reduce(*st["buy" if CUR["d"] == 1 else "sell"]) else 1.0
        else: m = 1.0
        sched.append(m); return m, False
    hook.sched = sched; return hook


def sched_hook(sched):
    """cyclic index-based schedule over the complete eligible stream"""
    i = {"n": 0}
    def hook(_all):
        m = sched[i["n"] % len(sched)]; i["n"] += 1; return m, False
    return hook


def run(Rs, cfg, hook=None, adds=False):
    H.EQHOOK = hook; H.EQ_ADDS = adds; H.TRACE = []
    f = H.simulate(Rs, 7.0, cfg); tr = [x for x in H.TRACE if x.get("pnl") is not None]; H.TRACE = None
    H.EQHOOK = None; H.EQ_ADDS = False
    return f, tr


def metrics(f, tr):
    pn = [x["pnl"] for x in tr]; losses = sorted(p for p in pn if p < 0)
    main = sum(x.get("risk", 0) for x in tr); addmax = sum(x.get("add_max_risk", 0) for x in tr); addact = sum(x.get("add_risk", 0) for x in tr)
    k = int(len(tr) * 2 / 3)
    return {"net": round(f["net"], 2), "trades": f["trades"],
            "later_calendar": round(sum(x["pnl"] for x in tr if x["t"] >= T_CUT), 2),
            "later_tradecount": round(sum(x["pnl"] for x in tr[k:]), 2),
            "dd_daily": round(f["worst_debt"], 2), "dd_cc": round(f["cc_dd"], 2),
            "dd_mtm_close": round(f["mtm_dd_close"], 2), "dd_mtm_adverse": round(f["mtm_dd_adverse"], 2),
            "tail5": round(sum(losses[:5]), 2),
            "exp_main": round(main, 2), "exp_add_max": round(addmax, 2), "exp_add_actual": round(addact, 2),
            "exp_planned": round(main + addmax, 2), "exp_committed": round(main + addact, 2),
            "adds_fired": sum(x.get("add_n", 0) for x in tr)}


def daily(tr):
    d = {}
    for x in tr:
        k = x["t"] // 86400; d[k] = d.get(k, 0.0) + x["pnl"]
    return d


def dd_of(seq):
    c = pk = dd = 0.0
    for p in seq:
        c += p; pk = max(pk, c); dd = max(dd, pk - c)
    return dd


def paired_bootstrap(trA, trB, block_days, reps=2000, seed=7):
    """A = candidate, B = baseline. Per-calendar-day paired differences and
    the drawdown ratio under block resampling of days (paths kept paired)."""
    da, db = daily(trA), daily(trB); days = sorted(set(da) | set(db))
    a = [da.get(k, 0.0) for k in days]; b = [db.get(k, 0.0) for k in days]
    diff = [x - y for x, y in zip(a, b)]
    r = random.Random(seed); n = len(days); nb = max(1, n // block_days)
    means, ratios = [], []
    for _ in range(reps):
        idx = []
        for _b in range(nb):
            s = r.randrange(0, max(1, n - block_days + 1)); idx.extend(range(s, min(n, s + block_days)))
        means.append(statistics.mean(diff[i] for i in idx))
        ra, rb = dd_of([a[i] for i in idx]), dd_of([b[i] for i in idx])
        ratios.append(ra / rb if rb > 0 else 1.0)
    means.sort(); ratios.sort()
    q = lambda xs, p: xs[int(p * (len(xs) - 1))]
    sd_day = statistics.pstdev(diff) if len(diff) > 1 else 0.0
    return {"days": n, "mean_daily_diff": round(statistics.mean(diff), 3), "sd_daily_diff": round(sd_day, 3),
            "ci90_mean_diff": [round(q(means, 0.05), 3), round(q(means, 0.95), 3)],
            "dd_ratio_point": round(dd_of(a) / dd_of(b), 3) if dd_of(b) > 0 else None,
            "ci90_dd_ratio": [round(q(ratios, 0.05), 3), round(q(ratios, 0.95), 3)],
            # detectable mean daily difference at 80% power, one-sided 5%, for N days
            "detectable_daily_diff_at": {str(N): round(2.49 * sd_day / (N ** 0.5), 3) for N in (30, 60, 120)}}


def row(label, m):
    print("%-44s net %8.2f | later(cal) %8.2f later(cnt) %8.2f | DD daily %6.2f cc %6.2f mtm %6.2f/%6.2f | tail5 %7.2f | exp main %7.1f +addmax %6.1f (planned %7.1f, committed %7.1f, adds %d) | trades %d" % (
        label, m["net"], m["later_calendar"], m["later_tradecount"], m["dd_daily"], m["dd_cc"], m["dd_mtm_close"], m["dd_mtm_adverse"],
        m["tail5"], m["exp_main"], m["exp_add_max"], m["exp_planned"], m["exp_committed"], m["adds_fired"], m["trades"]), flush=True)


K_SET = (2, 3, 4, 6, 8)
SHIFTS = [10 * s for s in range(1, 21)]
for drag in (0.0, 0.35):
    LIVE = {"jar": True, "drag": drag}
    refA = reference(R, 0.0); refB = reference(R, drag) if drag else refA
    print("\n=== spread 7, execution drag $%.2f/0.02 lot | reference A (spread-only): %d outcomes net %.2f | reference B (same drag): %d outcomes net %.2f ===" % (
        drag, len(refA), sum(x["pnl"] for x in refA), len(refB), sum(x["pnl"] for x in refB)), flush=True)
    fb, trb = run(R, LIVE); mb = metrics(fb, trb); row("baseline", mb)
    res = {"baseline": mb}
    for basis, ref in (("A", refA), ("B", refB)):
        if basis == "B" and drag == 0.0: continue
        S = States(ref)
        for kind, adds, lab in (("directional", True, "directional main+adds PRIMARY"), ("directional", False, "directional main-only (attribution arm)"),
                                ("global", True, "global main+adds (parked)")):
            hk = policy_hook(kind, S); f, tr = run(R, LIVE, hk, adds); m = metrics(f, tr); sched = list(hk.sched)
            m["basis"] = basis; row("[%s] %s" % (basis, lab), m); res["%s %s" % (basis, lab)] = m
            if kind != "directional": continue
            # --- controls on the PRIMARY (and reported for the arm too)
            # periodic: every phase of every k in the prespecified set
            per = {}
            for k in K_SET:
                rows_ = []
                for ph in range(k):
                    sc = [0.5 if (i % k) == ph else 1.0 for i in range(k)]
                    fc, tc_ = run(R, LIVE, sched_hook(sc), adds); mc = metrics(fc, tc_); rows_.append(mc)
                per[k] = {"phases": len(rows_), "exp_planned": [x["exp_planned"] for x in rows_], "net": [x["net"] for x in rows_],
                          "dd_cc": [x["dd_cc"] for x in rows_], "later_calendar": [x["later_calendar"] for x in rows_]}
            kbest = min(K_SET, key=lambda k: abs(statistics.mean(per[k]["exp_planned"]) - m["exp_planned"]))
            pb = per[kbest]
            print("   periodic controls (planned exposure matched by k=%d, all %d phases): exposure %s | net %s | dd_cc %s | candidate net %.2f dd_cc %.2f beats net %d/%d dd %d/%d" % (
                kbest, pb["phases"], [round(e) for e in pb["exp_planned"]], pb["net"], pb["dd_cc"], m["net"], m["dd_cc"],
                sum(1 for x in pb["net"] if x < m["net"]), pb["phases"], sum(1 for x in pb["dd_cc"] if x > m["dd_cc"]), pb["phases"]), flush=True)
            # block shifts: cyclic, index-based over the complete stream
            sh = []
            for s_ in SHIFTS:
                off = s_ % len(sched); sc = sched[off:] + sched[:off]
                fc, tc_ = run(R, LIVE, sched_hook(sc), adds); sh.append(metrics(fc, tc_))
            nets = sorted(x["net"] for x in sh); dds = sorted(x["dd_cc"] for x in sh); exps = sorted(x["exp_planned"] for x in sh)
            print("   block-shift controls (20 cyclic shifts): net median %.2f IQR [%.2f, %.2f] | dd_cc median %.2f | planned exposure [%.0f..%.0f] | candidate beats net %d/20 dd %d/20" % (
                nets[10], nets[5], nets[15], dds[10], exps[0], exps[-1], sum(1 for x in nets if x < m["net"]), sum(1 for x in dds if x > m["dd_cc"])), flush=True)
            m["controls"] = {"periodic": per, "periodic_k": kbest, "shifts": {"net": nets, "dd_cc": dds, "exp": exps}}
            # paired bootstrap, three block lengths (5 nominated; 3 / 10 sensitivities)
            m["paired"] = {str(bd): paired_bootstrap(tr, trb, bd) for bd in (5, 3, 10)}
            p5 = m["paired"]["5"]
            print("   paired vs baseline (block 5 days): mean daily diff %+.3f (sd %.2f) CI90 %s | DD ratio (cc) %.3f CI90 %s | detectable daily diff at 30/60/120 days %s" % (
                p5["mean_daily_diff"], p5["sd_daily_diff"], p5["ci90_mean_diff"], p5["dd_ratio_point"], p5["ci90_dd_ratio"], p5["detectable_daily_diff_at"]), flush=True)
            # halves: full-history reference (v1 style) and TRUE cold start
            for half, Rs in (("h1", R[:MID]), ("h2", R[MID:])):
                f_b, _ = run(Rs, LIVE); f_full, _ = run(Rs, LIVE, policy_hook(kind, S), adds)
                S_cold = States(reference(Rs, drag if basis == "B" else 0.0))
                f_cold, _ = run(Rs, LIVE, policy_hook(kind, S_cold), adds)
                m.setdefault("halves", {})[half] = {"baseline": f_b["net"], "full_history_ref": f_full["net"], "cold_start_ref": f_cold["net"]}
            print("   halves: h1 base %.2f / full-ref %.2f / cold-ref %.2f | h2 base %.2f / full-ref %.2f / cold-ref %.2f" % (
                m["halves"]["h1"]["baseline"], m["halves"]["h1"]["full_history_ref"], m["halves"]["h1"]["cold_start_ref"],
                m["halves"]["h2"]["baseline"], m["halves"]["h2"]["full_history_ref"], m["halves"]["h2"]["cold_start_ref"]), flush=True)
    OUT["drag_%.2f" % drag] = res
H.DIRGATE = None
json.dump(OUT, open(r"C:\Projects\KinoliveLines\study\compte_policies_dev_replay_v2.json", "w"), indent=1)
print("\nDONE - development data, pinned interval; gross after spread, before the stated drag", flush=True)
