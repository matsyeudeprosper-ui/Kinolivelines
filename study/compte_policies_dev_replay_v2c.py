"""Replay v2c (review 8) on dataset version b (closed bars only).

Corrections vs v2b:
  * bootstrap horizon exact: N_DAYS sampled days, last block trimmed; degenerate
    resamples (baseline drawdown 0) counted and reported, never scored as 1;
    intervals labelled CONDITIONAL DEVELOPMENT DIAGNOSTICS (resampled path
    returns; the adaptive policy is not rerun; no selection correction);
  * controls recomputed on MAIN + RULE-PERMITTED add risk, main and adds
    reported apart; schedules keyed by a common opportunity id = the entry
    bar time of the BASELINE stream; an arm's opportunity absent from that
    stream (paths diverge) gets multiplier 1.0 and is counted;
  * documented before any prospective outcome: K_SET = (2,3,4,6,8), all
    phases; SHIFTS = 20 cyclic shifts of 10 opportunities; bootstrap seed 7,
    3000 resamples; blocks 5 nominated, 3 / 10 sensitivities.
Arms: baseline; directional MAIN+ADDS (primary); directional MAIN-only (arm).
Drag 0 with reference basis A; drag 0.35 with basis B. Gross after spread,
before the stated drag. Development data, never a holdout."""
import sys, json, bisect, random, statistics
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.argv = ["x"]
import harness as H
from compte_controller import CompteController
import dev_dataset
sym, R, META = dev_dataset.load("b")
T0, T1 = int(R["time"][0]), int(R["time"][-1]) + 60
N_DAYS = (T1 - T0 + 86399) // 86400
REF_CFG = {"n_cont": 999, "bullets": 0, "jar": False}
K_SET = (2, 3, 4, 6, 8); SHIFTS = [10 * s for s in range(1, 21)]; SEED = 7; REPS = 3000
CUR = {"t": None, "d": None}
H.DIRGATE = lambda t, d: (CUR.update(t=t, d=d) or True)
print("dataset b:", META["symbol"], META["bars"], "bars", META["first_bar"], "->", META["last_bar"], "sha", META["sha256"], "| days", N_DAYS, flush=True)


def reference(drag):
    H.TRACE = []; H.simulate(R, 7.0, dict(REF_CFG, drag=drag))
    ref = sorted([x for x in H.TRACE if x.get("pnl") is not None and x.get("tc")], key=lambda x: x["tc"]); H.TRACE = None; return ref


class States:
    def __init__(self, ref): self.ref, self.tc, self.cache = ref, [x["tc"] for x in ref], {}
    def at(self, t):
        n = bisect.bisect_left(self.tc, t)
        if n in self.cache: return self.cache[n]
        out = {}
        for name, flt in (("buy", lambda d: d == 1), ("sell", lambda d: d == -1)):
            c = CompteController()
            for x in self.ref[:n]:
                if flt(x["d"]): c.feed(x["pnl"])
            out[name] = (c.state["trend"], c.state["choch"])
        self.cache[n] = out; return out


def hook_directional(S):
    sched = {}
    def hook(_a):
        tr, ch = S.at(CUR["t"])["buy" if CUR["d"] == 1 else "sell"]
        m = 0.5 if (tr == -1 and ch != 1) else 1.0; sched[CUR["t"]] = m; return m, False
    hook.sched = sched; return hook


def hook_keyed(mult_of_t, miss):
    """schedule keyed by the baseline opportunity id (entry bar time)"""
    def hook(_a):
        m = mult_of_t.get(CUR["t"])
        if m is None: miss[0] += 1; return 1.0, False
        return m, False
    return hook


def run(cfg, hook=None, adds=False):
    H.EQHOOK = hook; H.EQ_ADDS = adds; H.TRACE = []
    f = H.simulate(R, 7.0, cfg); tr = [x for x in H.TRACE if x.get("pnl") is not None and x.get("tc")]; H.TRACE = None
    H.EQHOOK = None; H.EQ_ADDS = False
    return f, sorted(tr, key=lambda x: x["tc"])


def dd_of(seq):
    c = pk = dd = 0.0
    for p in seq:
        c += p; pk = max(pk, c); dd = max(dd, pk - c)
    return dd


def by_day(tr):
    d = {}
    for x in tr: d.setdefault((x["tc"] - T0) // 86400, []).append(x["pnl"])
    return d


def cc_bootstrap(trA, trB, block_days):
    """exact horizon: exactly N_DAYS sampled days (last block trimmed); ordered
    closes kept within each block; paths paired on the same blocks; zero-close
    days retained; degenerate (baseline DD == 0) resamples counted apart."""
    A, B = by_day(trA), by_day(trB); r = random.Random(SEED)
    ratios, diffs, degenerate = [], [], 0
    for _ in range(REPS):
        sa, sb, got = [], [], 0
        while got < N_DAYS:
            s = r.randrange(0, N_DAYS - block_days + 1)
            take = min(block_days, N_DAYS - got)
            for dday in range(s, s + take):
                sa.extend(A.get(dday, [])); sb.extend(B.get(dday, []))
            got += take
        da, db = dd_of(sa), dd_of(sb)
        if db <= 0:
            degenerate += 1; continue
        ratios.append(da / db); diffs.append(sum(sa) - sum(sb))
    ratios.sort(); diffs.sort(); q = lambda xs, p: xs[int(p * (len(xs) - 1))] if xs else None
    return {"cc_ratio_ci90": [round(q(ratios, 0.05), 3), round(q(ratios, 0.95), 3)], "net_diff_ci90": [round(q(diffs, 0.05), 2), round(q(diffs, 0.95), 2)],
            "resamples": len(ratios), "degenerate": degenerate, "label": "conditional development diagnostic (resampled path returns; policy not rerun; no selection correction)"}


def block_power(trA, trB, block_days):
    A, B = by_day(trA), by_day(trB)
    daily = [sum(A.get(d, [])) - sum(B.get(d, [])) for d in range(N_DAYS)]
    blocks = [statistics.mean(daily[i:i + block_days]) for i in range(0, N_DAYS - block_days + 1, block_days)]
    sd_b = statistics.pstdev(blocks) if len(blocks) > 1 else 0.0
    return {"days": N_DAYS, "blocks": len(blocks), "mean_daily_diff": round(statistics.mean(daily), 3), "sd_block_means": round(sd_b, 3),
            "sd_daily_iid_only": round(statistics.pstdev(daily), 3), "detectable_daily_diff_at_blocks": {str(K): round(2.49 * sd_b / (K ** 0.5), 3) for K in (6, 12, 24)},
            "label": "approximate planning diagnostic from %d historical blocks" % len(blocks)}


def arm_metrics(f, tr):
    pn = [x["pnl"] for x in tr]
    return {"net": round(f["net"], 2), "trades": len(tr), "dd_cc": round(dd_of(pn), 2), "dd_daily_sampled": round(f["worst_debt"], 2),
            "mtm_main_only_proxy": round(f["mtm_dd_adverse"], 2),
            "exp_main": round(sum(x["risk"] for x in tr), 2), "exp_add_permitted": round(sum(x.get("add_permitted_risk", 0) for x in tr), 2),
            "exp_add_actual": round(sum(x.get("add_risk", 0) for x in tr), 2), "adds_fired": sum(x.get("add_n", 0) for x in tr),
            "later_half_calendar": round(sum(x["pnl"] for x in tr if x["tc"] >= (T0 + T1) / 2), 2)}


def matched(m): return m["exp_main"] + m["exp_add_permitted"]


OUT = {"dataset": META, "K_SET": K_SET, "SHIFTS": SHIFTS, "SEED": SEED, "REPS": REPS}
for drag in (0.0, 0.35):
    LIVE = {"jar": True, "drag": drag}; basis = "B" if drag else "A"
    S = States(reference(drag))
    fb, trb = run(LIVE); mb = arm_metrics(fb, trb); base_ids = [x["t"] for x in trb]
    res = {"baseline": mb}
    print("\n=== drag $%.2f, basis %s | baseline %s" % (drag, basis, json.dumps(mb)), flush=True)
    for lab, adds in (("primary main+adds", True), ("arm main-only", False)):
        hk = hook_directional(S); f, tr = run(LIVE, hk, adds); m = arm_metrics(f, tr)
        m["cc_ratio"] = round(m["dd_cc"] / mb["dd_cc"], 3)
        m["bootstrap"] = {str(bd): cc_bootstrap(tr, trb, bd) for bd in (5, 3, 10)}
        m["power"] = {str(bd): block_power(tr, trb, bd) for bd in (5, 3, 10)}
        print("%s: %s" % (lab, json.dumps({k: v for k, v in m.items() if k not in ("bootstrap", "power")})), flush=True)
        b5 = m["bootstrap"]["5"]; p5 = m["power"]["5"]
        print("   CC ratio %.3f CI90 b5 %s b3 %s b10 %s (degenerate %d/%d) | net diff CI90 b5 %s | power b5: mean %+.3f sd_blocks %.3f detect@24 %.3f" % (
            m["cc_ratio"], b5["cc_ratio_ci90"], m["bootstrap"]["3"]["cc_ratio_ci90"], m["bootstrap"]["10"]["cc_ratio_ci90"], b5["degenerate"], REPS,
            b5["net_diff_ci90"], p5["mean_daily_diff"], p5["sd_block_means"], p5["detectable_daily_diff_at_blocks"]["24"]), flush=True)
        if lab.startswith("primary"):
            target = matched(m); sched = dict(hk.sched)
            per = {}
            for k in K_SET:
                rows = []
                for ph in range(k):
                    mult = {t: (0.5 if (i % k) == ph else 1.0) for i, t in enumerate(base_ids)}
                    miss = [0]; fc, tc_ = run(LIVE, hook_keyed(mult, miss), adds); mc = arm_metrics(fc, tc_); mc["unkeyed_opportunities"] = miss[0]; rows.append(mc)
                per[k] = rows
            kb = min(K_SET, key=lambda k: abs(statistics.mean(matched(x) for x in per[k]) - target))
            pb = per[kb]
            print("   periodic (matched on main+permitted adds, target %.0f; k=%d, %d phases): matched exp %s | main %s | permitted adds %s | net %s | dd_cc %s | beats net %d/%d dd %d/%d | unkeyed %s" % (
                target, kb, len(pb), [round(matched(x)) for x in pb], [round(x["exp_main"]) for x in pb], [round(x["exp_add_permitted"]) for x in pb],
                [x["net"] for x in pb], [x["dd_cc"] for x in pb], sum(1 for x in pb if x["net"] < m["net"]), len(pb), sum(1 for x in pb if x["dd_cc"] > m["dd_cc"]), len(pb), [x["unkeyed_opportunities"] for x in pb]), flush=True)
            sh = []
            for s_ in SHIFTS:
                seq = [sched.get(t, 1.0) for t in base_ids]; off = s_ % len(seq); seq = seq[off:] + seq[:off]
                mult = dict(zip(base_ids, seq)); miss = [0]; fc, tc_ = run(LIVE, hook_keyed(mult, miss), adds); mc = arm_metrics(fc, tc_); mc["unkeyed"] = miss[0]; sh.append(mc)
            nets = sorted(x["net"] for x in sh); dds = sorted(x["dd_cc"] for x in sh); ex = sorted(matched(x) for x in sh)
            print("   block shifts (20, keyed by baseline opportunity id): net median %.2f IQR [%.2f, %.2f] | dd_cc median %.2f | matched exp [%.0f..%.0f] | beats net %d/20 dd %d/20 | unkeyed max %d" % (
                nets[10], nets[5], nets[15], dds[10], ex[0], ex[-1], sum(1 for x in nets if x < m["net"]), sum(1 for x in dds if x > m["dd_cc"]), max(x["unkeyed"] for x in sh)), flush=True)
            m["controls"] = {"periodic_k": kb, "periodic": {str(k): [{kk: vv for kk, vv in x.items()} for x in v] for k, v in per.items()}, "shifts": sh}
        res[lab] = m
    OUT["drag_%.2f" % drag] = res
H.DIRGATE = None
json.dump(OUT, open(r"C:\Projects\KinoliveLines\study\compte_policies_dev_replay_v2c.json", "w"), indent=1)
print("\nDONE v2c", flush=True)
