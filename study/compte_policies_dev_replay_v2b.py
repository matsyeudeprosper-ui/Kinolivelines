"""Replay v2b - statistics corrected per interim review 7, on the pinned
development dataset. Three arms only (baseline, directional MAIN+ADDS
primary, directional MAIN-only arm), both drags, basis B at drag 0.35.

Corrections:
  * realised accounting by EXIT time (tc); close-to-close drawdown over the
    ordered closes; the bootstrap resamples calendar blocks of the ENTIRE
    fixed interval (zero-trade days included) and keeps the ordered closes
    inside each sampled block, both paths paired on the same blocks;
    daily-aggregate DD kept as a separately named diagnostic;
  * MTM figures labelled main-only proxy (not whole-account bounds);
  * add exposure: nominal capacity vs rule-permitted budget vs actual;
  * power: block-based variance (block means of the paired daily difference,
    nominated 5-day blocks; 3 / 10 shown) - the IID formula shown beside it,
    labelled IID-only.
No parameter changed. Gross after spread, before the stated drag."""
import sys, json, bisect, random, statistics
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.argv = ["x"]
import harness as H
from compte_controller import CompteController
import dev_dataset
sym, R, META = dev_dataset.load()
T0, T1 = int(R["time"][0]), int(R["time"][-1])
REF_CFG = {"n_cont": 999, "bullets": 0, "jar": False}
CUR = {"t": None, "d": None}
H.DIRGATE = lambda t, d: (CUR.update(t=t, d=d) or True)


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
    def hook(_a):
        tr, ch = S.at(CUR["t"])["buy" if CUR["d"] == 1 else "sell"]
        return (0.5 if (tr == -1 and ch != 1) else 1.0), False
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


def day_of(t): return (t - T0) // 86400
N_DAYS = (T1 - T0) // 86400 + 1


def by_day(tr):
    d = {}
    for x in tr: d.setdefault(day_of(x["tc"]), []).append(x["pnl"])     # EXIT time, ordered closes kept
    return d


def cc_bootstrap(trA, trB, block_days, reps=3000, seed=7):
    """Paired block bootstrap over the ENTIRE fixed interval (zero-trade days
    included): sample day-blocks, concatenate the ordered closes of each
    sampled block for BOTH paths, then close-to-close DD and net on those."""
    A, B = by_day(trA), by_day(trB); r = random.Random(seed)
    nb = max(1, N_DAYS // block_days); ratios, diffs = [], []
    for _ in range(reps):
        sa, sb = [], []
        for _b in range(nb):
            s = r.randrange(0, max(1, N_DAYS - block_days + 1))
            for dday in range(s, min(N_DAYS, s + block_days)):
                sa.extend(A.get(dday, [])); sb.extend(B.get(dday, []))
        da, db = dd_of(sa), dd_of(sb)
        ratios.append(da / db if db > 0 else 1.0); diffs.append(sum(sa) - sum(sb))
    ratios.sort(); diffs.sort(); q = lambda xs, p: xs[int(p * (len(xs) - 1))]
    return {"cc_ratio_ci90": [round(q(ratios, 0.05), 3), round(q(ratios, 0.95), 3)], "net_diff_ci90": [round(q(diffs, 0.05), 2), round(q(diffs, 0.95), 2)]}


def block_power(trA, trB, block_days):
    """block-based variance of the paired daily difference"""
    A, B = by_day(trA), by_day(trB)
    daily = [sum(A.get(d, [])) - sum(B.get(d, [])) for d in range(N_DAYS)]
    blocks = [statistics.mean(daily[i:i + block_days]) for i in range(0, N_DAYS - block_days + 1, block_days)]
    sd_b = statistics.pstdev(blocks) if len(blocks) > 1 else 0.0
    sd_iid = statistics.pstdev(daily)
    # detectable mean DAILY difference (80% power, one-sided 5%) with K blocks
    det = {str(K): round(2.49 * sd_b / (K ** 0.5), 3) for K in (6, 12, 24)}
    return {"days": N_DAYS, "blocks": len(blocks), "mean_daily_diff": round(statistics.mean(daily), 3),
            "sd_block_means": round(sd_b, 3), "sd_daily_iid_only": round(sd_iid, 3),
            "detectable_daily_diff_at_blocks": det, "note": "blocks of %d days; IID sd shown for reference only" % block_days}


def arm_metrics(f, tr):
    pn = [x["pnl"] for x in tr]
    return {"net": round(f["net"], 2), "trades": len(tr), "dd_cc_observed": round(dd_of(pn), 2),
            "dd_daily_sampled": round(f["worst_debt"], 2), "dd_daily_aggregate_diag": round(dd_of([sum(v) for k, v in sorted(by_day(tr).items())]), 2),
            "mtm_main_only_proxy": {"adverse": round(f["mtm_dd_adverse"], 2), "close": round(f["mtm_dd_close"], 2), "label": "main position only, vs realised peak, whole-bar extremes: a proxy, not a whole-account bound"},
            "exp_main": round(sum(x["risk"] for x in tr), 2), "add_nominal_capacity": round(sum(x.get("add_max_risk", 0) for x in tr), 2),
            "add_rule_permitted": round(sum(x.get("add_permitted_risk", 0) for x in tr), 2), "add_actual": round(sum(x.get("add_risk", 0) for x in tr), 2),
            "adds_fired": sum(x.get("add_n", 0) for x in tr),
            "later_half_calendar": round(sum(x["pnl"] for x in tr if x["tc"] >= (T0 + T1) / 2), 2)}


OUT = {"dataset": META}
for drag in (0.0, 0.35):
    LIVE = {"jar": True, "drag": drag}
    basis = "B" if drag else "A"
    S = States(reference(drag))
    fb, trb = run(LIVE); res = {"baseline": arm_metrics(fb, trb)}
    print("\n=== drag $%.2f, reference basis %s ===" % (drag, basis), flush=True)
    print("baseline:", json.dumps(res["baseline"]), flush=True)
    for lab, adds in (("directional main+adds PRIMARY", True), ("directional main-only arm", False)):
        f, tr = run(LIVE, hook_directional(S), adds); m = arm_metrics(f, tr)
        m["cc_ratio_observed"] = round(m["dd_cc_observed"] / res["baseline"]["dd_cc_observed"], 3)
        m["bootstrap"] = {str(bd): cc_bootstrap(tr, trb, bd) for bd in (5, 3, 10)}
        m["power"] = {str(bd): block_power(tr, trb, bd) for bd in (5, 3, 10)}
        res[lab] = m
        print(lab + ":", json.dumps({k: v for k, v in m.items() if k not in ("bootstrap", "power")}), flush=True)
        print("   CC ratio observed %.3f | CI90 block5 %s block3 %s block10 %s | net diff CI90 block5 %s" % (
            m["cc_ratio_observed"], m["bootstrap"]["5"]["cc_ratio_ci90"], m["bootstrap"]["3"]["cc_ratio_ci90"], m["bootstrap"]["10"]["cc_ratio_ci90"], m["bootstrap"]["5"]["net_diff_ci90"]), flush=True)
        p5 = m["power"]["5"]
        print("   power (block 5): mean daily diff %+.3f | sd of block means %.3f (IID daily sd %.3f) | detectable daily diff at 6/12/24 blocks %s" % (
            p5["mean_daily_diff"], p5["sd_block_means"], p5["sd_daily_iid_only"], p5["detectable_daily_diff_at_blocks"]), flush=True)
    OUT["drag_%.2f" % drag] = res
H.DIRGATE = None
json.dump(OUT, open(r"C:\Projects\KinoliveLines\study\compte_policies_dev_replay_v2b.json", "w"), indent=1)
print("\nDONE v2b", flush=True)
