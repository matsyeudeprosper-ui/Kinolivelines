"""Manifest-driven package runner (ChatGPT reviews 9 + 10).

Loads ONLY review/compte_frozen_manifest.json, maps EVERY package field
explicitly into harness settings (a package field outside the known set is a
REJECT, a harness key the simulator does not know is an error), validates the
fixed values against the LOADED simulator constants, prints the effective
config beside each regime, runs the parity contrasts with decision traces,
and records the matched control k per regime and cost basis from
development data only.

Review 10: per-entry money limits in the live order on the CURRENT simulated
balance (harness limits_live=1): min_balance refusal -> policy multiplier ->
risk_fit shrink -> hard cap on the FINAL lot. The legacy generic convention
(limits_live=0) is untouched and still reproduces the v2c tables.

    python manifest_runner.py
"""
import sys, json, bisect, statistics, math, time, hashlib
sys.path.insert(0, r"C:\Projects\KinoliveLines\study\frozen_entry_study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\study\frozen_entry_study")
sys.path.insert(0, r"C:\Projects\KinoliveLines\study\frozen_entry_study"); sys.argv = ["x"]
import harness as H
from compte_controller import CompteController
import dev_dataset
MAN = r"C:\Projects\KinoliveLines\study\frozen_entry_study\compte_frozen_manifest.json"
man = json.load(open(MAN, encoding="utf-8"))
sym, R, META = dev_dataset.load("b")

MAPPED = {"base_lot", "max_extra", "adds_on", "jar", "kill_net", "day_cap", "risk_fit_pct", "rr", "k_streak",
          "nervosity", "movement", "internal_entries", "debt_gate", "scale_with_balance", "scale_ref_balance",
          "max_risk_pct", "min_balance"}
# fixed in the simulator: the package value must EQUAL the loaded constant, else REJECT
FIXED = {"chest_cap": ("CHEST_CAP", H.CHEST_CAP), "jar_skim": ("JAR_SKIM", H.JAR_SKIM), "jar_stake": ("JAR_STAKE", H.JAR_STAKE),
         "jar_debt_mult": ("JAR_DEBT_MULT", H.JAR_DEBT_MULT), "jar_floor_cap": ("JAR_FLOOR_CAP", H.JAR_FLOOR_CAP)}
FIXED_BEHAVIOUR = {"day_cap_waived": True, "debt_mode": "hwm", "touch_entries": False, "eq_half": False,
                   "recov_bullets_only": False, "max_trades_day": None}
INFORMATIONAL = {"label", "week_target"}


def effective_cfg(pkg, balance, drag):
    """explicit mapping; (cfg, report); raises ValueError('REJECT ...') on anything unsupported"""
    unknown = sorted(set(pkg) - MAPPED - set(FIXED) - set(FIXED_BEHAVIOUR) - INFORMATIONAL)
    if unknown:
        raise ValueError("REJECT %s: unhandled package fields %s" % (pkg.get("label", "?"), unknown))
    for k, (name, const) in FIXED.items():
        if k in pkg and abs(float(pkg[k]) - float(const)) > 1e-12:
            raise ValueError("REJECT %s: %s=%r but the loaded simulator constant %s is %r" % (pkg.get("label", "?"), k, pkg[k], name, const))
    for k, want in FIXED_BEHAVIOUR.items():
        if k in pkg and pkg[k] != want:
            raise ValueError("REJECT %s: %s=%r is not modelled (simulator behaviour fixed at %r)" % (pkg.get("label", "?"), k, pkg[k], want))
    rep, cfg = {}, {}
    cfg["lot"] = float(pkg["base_lot"]); rep["lot"] = "base_lot %.2f" % cfg["lot"]
    cfg["bullets"] = int(pkg["max_extra"]) if pkg.get("adds_on", True) else 0
    rep["bullets"] = "max_extra %d, adds_on %s -> %d" % (pkg["max_extra"], pkg.get("adds_on", True), cfg["bullets"])
    cfg["jar"] = bool(pkg.get("jar", True)); rep["jar"] = str(cfg["jar"])
    cfg["kill_net"] = float(pkg["kill_net"]) if pkg.get("kill_net") not in (None, 0) else 0.0
    rep["kill_net"] = ("%.0f" % cfg["kill_net"]) if cfg["kill_net"] else "none"
    cfg["day_cap"] = float(pkg["day_cap"]) if pkg.get("day_cap") else 0.0; rep["day_cap"] = ("%.2f" % cfg["day_cap"]) if cfg["day_cap"] else "none"
    cfg["risk_fit"] = float(pkg.get("risk_fit_pct") or 0.0); rep["risk_fit"] = "risk_fit_pct %.1f%% -> %.1f%% of the CURRENT balance" % (cfg["risk_fit"], cfg["risk_fit"])
    cfg["rr"] = float(pkg["rr"]); cfg["k_streak"] = int(pkg["k_streak"]); rep["rr/k_streak"] = "%.1f / %d" % (cfg["rr"], cfg["k_streak"])
    cfg["nerv_gate"] = bool(pkg.get("nervosity", True)); cfg["movement"] = bool(pkg.get("movement", True))
    rep["gates"] = "nervosity %s, movement %s" % (cfg["nerv_gate"], cfg["movement"])
    cfg["internal"] = 1 if pkg.get("internal_entries") else 0; rep["internal"] = str(cfg["internal"])
    cfg["debt_gate"] = 1 if pkg.get("debt_gate", True) else 0; rep["debt_gate"] = "%s -> harness debt_gate %d (0 = every BOS taken in debt)" % (pkg.get("debt_gate", True), cfg["debt_gate"])
    cfg["balance"] = float(balance); cfg["limits_live"] = 1
    cfg["hard_cap_pct"] = float(pkg.get("max_risk_pct") or 0.0); cfg["min_balance"] = float(pkg.get("min_balance") or 0.0)
    rep["limits"] = "LIVE order on balance %.2f + run: min_balance %.0f refusal -> policy -> fit -> hard cap %.0f%% of the current balance on the FINAL lot (refuse)" % (
        cfg["balance"], cfg["min_balance"], 100 * cfg["hard_cap_pct"])
    if pkg.get("scale_with_balance"):
        cfg["scale_lot"] = 1; cfg["scale_ref"] = float(pkg.get("scale_ref_balance") or 200.0); cfg["scale_daily"] = 1
        rep["scaling"] = "ON: lot and day cap from (balance + run)/%.0f once per UTC day (live cadence)" % cfg["scale_ref"]
    else:
        cfg["scale_lot"] = 0; cfg["scale_daily"] = 0; rep["scaling"] = "OFF (fixed lot; the balance still exists for the limits)"
    cfg["drag"] = drag; rep["drag"] = "%.2f $/0.02 lot" % drag
    rep["fixed_validated"] = {k: "%s == %r" % (name, const) for k, (name, const) in FIXED.items()}
    rep["fixed_behaviour"] = dict(FIXED_BEHAVIOUR)
    return H.cfg_strict(cfg), rep


# ---------------- canonical reference (the recorder spec, bos_reference_ledger.py header):
# no debt gate, no caps, no kill line, no recovery, no scaling, fixed 0.02 lot, no money ceiling
REF_CANON = {"debt_gate": 0, "bullets": 0, "jar": False, "kill_net": 0.0, "day_cap": 0.0, "lot": 0.02,
             "balance": 0.0, "limits_live": 1, "hard_cap_pct": 0.0, "min_balance": 0.0, "scale_lot": 0}
REF_OLD = {"n_cont": 999, "bullets": 0, "jar": False}        # the v2c approximation, kept for reconciliation only
CUR = {"t": None, "d": None}
H.DIRGATE = lambda t, d: (CUR.update(t=t, d=d) or True)


def reference(drag, spec=REF_CANON):
    H.TRACE = []; H.simulate(R, 7.0, H.cfg_strict(dict(spec, drag=drag)))
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


def hook_keyed(mult, miss):
    def hook(_a):
        m = mult.get(CUR["t"])
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


def matched(tr): return sum(x["risk"] for x in tr) + sum(x.get("add_permitted_risk", 0) for x in tr)


REGIMES = [("infinity", "valere", 175.70), ("u224016179", "valere_cap3", 267.42), ("bos", "special_10", 360.37), ("reference_uncapped", "reference", 1000.0)]
# balances = nest_data at the time of this development run; the FROZEN values are recorded at freeze
K_SET = tuple(man["arms"]["exposure_control"]["K_SET"])
PR = man["arms"]["baseline"]["package_regimes"]
out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset": META["sha256"], "regimes": {}, "parity_checks": {}, "reference": {}}

print("=== effective configs (manifest only) ===", flush=True)
for uid, pname, bal in REGIMES:
    try:
        cfg, rep = effective_cfg(PR[uid], bal, 0.0); print(uid, pname, json.dumps(rep), flush=True)
    except (ValueError, KeyError) as e:
        print(uid, pname, "REJECTED:", e, flush=True); out["regimes"][uid] = {"rejected": str(e)}
# strictness demonstrations
for bad in ({"unexpected_entry_rule": True}, {"eq_half": True}, {"jar_skim": 0.4}):
    try:
        effective_cfg(dict(PR["infinity"], **bad), 175.70, 0.0); print("STRICTNESS FAILED: accepted", bad, flush=True); out["parity_checks"]["strict_" + list(bad)[0]] = {"pass": False}
    except ValueError as e:
        print("strictness:", e, flush=True); out["parity_checks"]["strict_" + list(bad)[0]] = {"pass": True, "msg": str(e)}

# ---------------- reference reconciliation (review 10)
print("\n=== reference reconciliation ===", flush=True)
for drag in (0.0, 0.35):
    rc, ro = reference(drag, REF_CANON), reference(drag, REF_OLD)
    ids_c, ids_o = {x["t"] for x in rc}, {x["t"] for x in ro}
    print("drag %.2f: canonical (recorder spec) %d outcomes net %.2f | old n_cont=999 %d outcomes net %.2f | only canonical %d, only old %d" % (
        drag, len(rc), sum(x["pnl"] for x in rc), len(ro), sum(x["pnl"] for x in ro), len(ids_c - ids_o), len(ids_o - ids_c)), flush=True)
    out["reference"]["drag_%.2f" % drag] = {"canonical_n": len(rc), "canonical_net": round(sum(x["pnl"] for x in rc), 2), "old_n": len(ro), "old_net": round(sum(x["pnl"] for x in ro), 2),
                                           "only_canonical": sorted(ids_c - ids_o), "only_old": sorted(ids_o - ids_c)}

# ---------------- parity contrasts with traces
print("\n=== parity contrasts (live-order limits on the current balance) ===", flush=True)
cfg_cap, _ = effective_cfg(PR["u224016179"], 267.42, 0.0); cfg_nocap = dict(cfg_cap, risk_fit=0.0)
f1, t1 = run(cfg_nocap); f2, t2 = run(cfg_cap)
b1 = {x["t"]: x for x in t1}
changed = [(t, x["bal_now"], x["fit_cap"], b1[t]["risk"], x["risk"], x["lot"]) for t, x in ((x["t"], x) for x in t2) if t in b1 and abs(b1[t]["risk"] - x["risk"]) > 0.005]
fits = [x["fit_cap"] for x in t2]
print("1. 3%% risk-fit on the CURRENT balance (Depenses): fit cap ranged $%.2f..$%.2f over the run (start $%.2f); risks changed %d; e.g. (t, balance, fit, risk before, after, lot) %s" % (
    min(fits), max(fits), 0.03 * 267.42, len(changed), changed[:3]), flush=True)
out["parity_checks"]["risk_fit_current_balance"] = {"fit_min": min(fits), "fit_max": max(fits), "changed": len(changed), "examples": changed[:5], "pass": len(changed) > 0 and min(fits) < max(fits)}
cfg_inf, _ = effective_cfg(PR["infinity"], 175.70, 0.0)
f3a, t3a = run(dict(cfg_inf, hard_cap_pct=0.0)); f3b, t3b = run(cfg_inf)
would = [(x["t"], x["bal_now"], x["risk"], round(0.10 * x["bal_now"], 2)) for x in t3a if x["risk"] > 0.10 * x["bal_now"] + 1e-9]
legacy_pass = [w for w in would if w[2] <= 0.10 * 230.0]
print("2. hard 10%% cap on the FINAL lot vs the current balance (Infinity, $175.70): trades that break it without the cap %d (%d of them would PASS the legacy fixed $23 ceiling); trades with cap %d vs without %d; e.g. %s" % (
    len(would), len(legacy_pass), len(t3b), len(t3a), would[:3]), flush=True)
out["parity_checks"]["hard_cap_current_balance"] = {"breaking_without": len(would), "legacy_would_pass": len(legacy_pass), "trades_with": len(t3b), "trades_without": len(t3a), "examples": would[:5], "pass": len(would) > 0}
# order: fit then cap on the final lot - a trade shrunk by the fit must be judged by the cap on the SHRUNK lot
f4, t4 = run(cfg_cap)
after_fit = [x for x in t4 if x["lot"] < x["lot_pol"] - 1e-9]
viol = [x for x in after_fit if x["risk"] > x["hard_cap"] + 1e-9]
print("3. order fit -> cap: %d traced trades were shrunk by the fit; %d of them exceed the hard cap on the FINAL lot (must be 0)" % (len(after_fit), len(viol)), flush=True)
out["parity_checks"]["fit_then_cap_order"] = {"shrunk_by_fit": len(after_fit), "cap_violations_after_fit": len(viol), "pass": len(viol) == 0}
f5, t5 = run(dict(cfg_inf, scale_daily=0))
lots = sorted(set(x["lot_prop"] for x in t3b))
print("4. balance scaling at live cadence (Infinity): proposed lots seen %s (static %s); net daily %.2f vs static %.2f" % (lots, sorted(set(x["lot_prop"] for x in t5)), f3b["net"], f5["net"]), flush=True)
out["parity_checks"]["scaling_cadence"] = {"lots_daily": lots, "lots_static": sorted(set(x["lot_prop"] for x in t5)), "net_daily": f3b["net"], "net_static": f5["net"], "pass": True}
S0 = States(reference(0.0)); f6, t6 = run(cfg_inf, hook_directional(S0), True)
inc = [x for x in t6 if x["lot_pol"] > x["lot_prop"] + 1e-9]
fired = [x for x in t6 if x["lot_pol"] < x["lot_prop"] - 1e-9]
inert = sum(1 for x in t6 if x["lot_prop"] <= 0.01 + 1e-9)
print("5. rounding from the decision's OWN ladder (Infinity primary): policy lot > proposed lot %d (must be 0); halved %d of %d; at the 0.01 floor %d decisions could not halve the MAIN" % (
    len(inc), len(fired), len(t6), inert), flush=True)
out["parity_checks"]["never_above_proposed"] = {"increases": len(inc), "halved": len(fired), "n": len(t6), "at_floor": inert, "pass": len(inc) == 0}
# min_balance: force a tiny balance to show the refusal binds (demonstration only)
f7, t7 = run(dict(cfg_inf, balance=25.0, min_balance=20.0, scale_lot=0))
print("6. min_balance modelled: with balance $25 and the $20 floor, %d refusals (minbal) over the run" % f7.get("minbal", -1), flush=True)
out["parity_checks"]["min_balance"] = {"refusals_at_25": f7.get("minbal", -1), "pass": f7.get("minbal", -1) >= 0}
# review 11: the REQUESTED multiplier drives the add count rule, the achieved main ratio is reporting only
trig_floor = [x for x in t6 if x["req_mult"] < 1.0 and x["lot_prop"] <= 0.01 + 1e-9]
trig_02 = [x for x in t6 if x["req_mult"] < 1.0 and x["lot_prop"] >= 0.02 - 1e-9]
untrig = [x for x in t6 if x["req_mult"] == 1.0]
ok_floor = all(x["lot_pol"] == 0.01 and x["add_cnt_after"] == 1 and x["ach_mult"] == 1.0 for x in trig_floor)
ok_02 = all(x["add_cnt_after"] == 1 and x["ach_mult"] == 0.5 for x in trig_02)
ok_un = all(x["add_cnt_after"] == x["add_cnt_before"] == 3 for x in untrig)
over = [x for x in t6 if x.get("add_n", 0) > x["add_cnt_after"]]
ex = (trig_floor[:1] or [{}])[0]
print("7. add rule on the REQUESTED multiplier (Infinity primary): triggered at the 0.01 floor %d decisions -> main stays 0.01 (achieved 1.0), permitted adds 3 -> 1: %s; triggered at 0.02: %d -> main 0.01, adds 1: %s; untriggered %d keep 3: %s; fired adds above budget %d (must be 0); e.g. %s" % (
    len(trig_floor), ok_floor, len(trig_02), ok_02, len(untrig), ok_un, len(over),
    {k: ex.get(k) for k in ("t", "lot_prop", "lot_pol", "req_mult", "ach_mult", "add_cnt_before", "add_cnt_after", "add_permitted_before", "add_permitted_risk", "add_n")}), flush=True)
# 7b. the floor case on real data may have no trigger (cold start = early run = 0.01 days); force it:
# Infinity's package at a FIXED 0.01 lot (scale_lot 0) so every decision sits at the floor
f6b, t6b = run(dict(cfg_inf, lot=0.01, scale_lot=0, scale_daily=0), hook_directional(S0), True)
tf = [x for x in t6b if x["req_mult"] < 1.0]; uf = [x for x in t6b if x["req_mult"] == 1.0]
ok_tf = bool(tf) and all(x["lot_pol"] == 0.01 and x["ach_mult"] == 1.0 and x["add_cnt_after"] == 1 for x in tf)
ok_uf = all(x["add_cnt_after"] == 3 for x in uf); over_f = [x for x in t6b if x.get("add_n", 0) > x["add_cnt_after"]]
exf = (tf[:1] or [{}])[0]
print("7b. forced floor (Infinity package, fixed 0.01 lot): triggered %d -> main 0.01 kept, achieved 1.0, adds 3 -> 1: %s; untriggered %d keep 3: %s; fired over budget %d; e.g. %s" % (
    len(tf), ok_tf, len(uf), ok_uf, len(over_f), {k: exf.get(k) for k in ("t", "lot_prop", "lot_pol", "req_mult", "ach_mult", "add_cnt_before", "add_cnt_after", "add_permitted_before", "add_permitted_risk", "add_n")}), flush=True)
out["parity_checks"]["requested_vs_achieved_forced_floor"] = {"triggered": len(tf), "untriggered": len(uf), "ok_triggered": ok_tf, "ok_untriggered": ok_uf, "fired_over_budget": len(over_f), "example": exf, "pass": ok_tf and ok_uf and not over_f}
out["parity_checks"]["requested_vs_achieved"] = {"triggered_floor": len(trig_floor), "triggered_02": len(trig_02), "untriggered": len(untrig), "ok_floor": ok_floor, "ok_02": ok_02, "ok_untriggered": ok_un,
                                                "fired_over_budget": len(over), "example": ex, "pass": ok_floor and ok_02 and ok_un and not over}

# ---------------- k per regime and cost basis (development only)
print("\n=== matched control k per regime (development, dataset b, canonical reference, live-order limits) ===", flush=True)
# rows are cached as they finish (keyed by dataset + harness hash) so a killed run resumes
ROWS = r"C:\Projects\KinoliveLines\study\frozen_entry_study\manifest_runner_rows.json"
# review 11: the cache key covers everything a row depends on - dataset, harness, this runner's
# mapping, the controller, the bot engine, the canonical reference spec, the cost basis set,
# the control settings and (per row, below) the effective config + starting balance
def _h(path): return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]
HKEY = ":".join([META["sha256"][:16], _h(r"C:\Projects\KinoliveLines\study\frozen_entry_study\harness.py"),
                 hashlib.sha256(open(__file__, "rb").read().split(b"REGIMES = [")[0]).hexdigest()[:16],
                 _h(r"C:\Projects\KinoliveLines\study\frozen_entry_study\compte_controller.py"), _h(r"C:\Projects\KinoliveLines\study\frozen_entry_study\structure_bos_bot.py"),
                 hashlib.sha256(json.dumps(REF_CANON, sort_keys=True).encode()).hexdigest()[:8],
                 hashlib.sha256(json.dumps({"K_SET": K_SET, "drags": [0.0, 0.35], "spread": 7.0}, sort_keys=True).encode()).hexdigest()[:8]])
try:
    cache = json.load(open(ROWS)); cache = cache if cache.get("key") == HKEY else {"key": HKEY, "rows": {}}
except Exception:
    cache = {"key": HKEY, "rows": {}}
for drag in (0.0, 0.35):
    basis = "B" if drag else "A"; S = None
    for uid, pname, bal in REGIMES:
        try:
            cfg, rep = effective_cfg(PR[uid], bal, drag)
        except (ValueError, KeyError):
            continue
        ck = "%s|%.2f|%s" % (uid, drag, hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:12])
        if ck in cache["rows"]:
            row = cache["rows"][ck]; out["regimes"].setdefault(uid, {})["drag_%.2f" % drag] = row
            print("%-18s %-11s drag %.2f %s | (cached) primary ratio %s k=%d beats net %d/%d dd %d/%d" % (uid, pname, drag, basis, row["primary"]["ratio"], row["k"], row["beats_net"], row["k"], row["beats_dd"], row["k"]), flush=True)
            continue
        if S is None:
            S = States(reference(drag))
        fb, trb = run(cfg); fp, trp = run(cfg, hook_directional(S), True)
        # review 11: the policy's own cut from each decision's trace (not matched across diverged paths)
        main_red = sum((x["lot_prop"] - x["lot_pol"]) * x["dist"] for x in trp)
        add_red = sum(x.get("add_permitted_before", 0) - x.get("add_permitted_risk", 0) for x in trp)
        n_trig = sum(1 for x in trp if x["req_mult"] < 1.0); n_floor_trig = sum(1 for x in trp if x["req_mult"] < 1.0 and x["lot_prop"] <= 0.01 + 1e-9)
        base_ids = [x["t"] for x in trb]; target = matched(trp)
        per = {}
        for k in K_SET:
            exps, nets, dds, miss_ = [], [], [], []
            for ph in range(k):
                mult = {t: (0.5 if (i % k) == ph else 1.0) for i, t in enumerate(base_ids)}
                miss = [0]; fc, tc_ = run(cfg, hook_keyed(mult, miss), True)
                exps.append(matched(tc_)); nets.append(fc["net"]); dds.append(dd_of([x["pnl"] for x in tc_])); miss_.append(miss[0])
            per[k] = {"exp": exps, "net": nets, "dd_cc": dds, "unkeyed": miss_}
        kb = min(K_SET, key=lambda k: abs(statistics.mean(per[k]["exp"]) - target))
        ddp = dd_of([x["pnl"] for x in trp]); ddb = dd_of([x["pnl"] for x in trb])
        row = {"basis": basis, "balance_used": bal, "effective": rep, "baseline": {"net": fb["net"], "dd_cc": round(ddb, 2), "trades": len(trb), "blocked": fb["blocked"], "minbal": fb.get("minbal", 0)},
               "primary": {"net": fp["net"], "dd_cc": round(ddp, 2), "trades": len(trp), "ratio": round(ddp / ddb, 3) if ddb else None,
                           "main_risk_reduction": round(main_red, 2), "permitted_add_reduction": round(add_red, 2),
                           "triggered": n_trig, "triggered_at_floor": n_floor_trig},
               "k": kb, "k_phases": per[kb], "beats_net": sum(1 for x in per[kb]["net"] if x < fp["net"]), "beats_dd": sum(1 for x in per[kb]["dd_cc"] if x > ddp)}
        out["regimes"].setdefault(uid, {})["drag_%.2f" % drag] = row
        cache["rows"][ck] = row; json.dump(cache, open(ROWS, "w"), indent=1)
        print("%-18s %-11s drag %.2f %s | base net %7.2f dd %6.2f | primary net %7.2f dd %6.2f ratio %s | cut main %6.2f adds %6.2f | k=%d beats net %d/%d dd %d/%d | unkeyed %s" % (
            uid, pname, drag, basis, fb["net"], ddb, fp["net"], ddp, row["primary"]["ratio"], main_red, add_red, kb, row["beats_net"], kb, row["beats_dd"], kb, per[kb]["unkeyed"]), flush=True)
H.DIRGATE = None
json.dump(out, open(r"C:\Projects\KinoliveLines\study\frozen_entry_study\manifest_runner_report.json", "w"), indent=1)
man["control_k_by_regime"] = {uid: {d: {"k": r["k"], "basis": r["basis"], "balance_used": r["balance_used"]} for d, r in v.items() if "k" in r} for uid, v in out["regimes"].items()}
man["effective_configs"] = {uid: {d: r["effective"] for d, r in v.items() if "effective" in r} for uid, v in out["regimes"].items()}
man["package_field_coverage"] = {"mapped": sorted(MAPPED), "fixed_validated_against_loaded_constants": {k: v[0] for k, v in FIXED.items()},
                                 "fixed_behaviour": FIXED_BEHAVIOUR, "informational": sorted(INFORMATIONAL), "unknown_field": "REJECT"}
man["reference_state_source"] = {"spec": "bos_reference_ledger.py header: no debt gate, no caps, no kill line, no recovery, no scaling, fixed 0.02 lot, no money ceiling",
                                 "harness_cfg": REF_CANON, "reconciliation_vs_v2c_n_cont_999": out["reference"]}
man["limits_convention"] = "limits_live=1: live enter() order on the current simulated balance; legacy limits_live=0 kept only to reproduce v2c"
man["hashes"]["lab/harness.py"] = hashlib.sha256(open(r"C:\Projects\KinoliveLines\study\frozen_entry_study\harness.py", "rb").read()).hexdigest()[:16]
man["hashes"]["study/manifest_runner.py"] = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:16]
man["parity_report"] = "study/manifest_runner_report.json"
json.dump(man, open(MAN, "w", encoding="utf-8"), indent=1)
print("\nmanifest updated", flush=True)
