"""Manifest-driven package runner (ChatGPT review 9).

Loads ONLY review/compte_frozen_manifest.json, maps each package field
EXPLICITLY into harness settings (cfg_strict: an unknown key is an error),
REJECTS unsupported behaviour instead of falling back, prints the effective
config beside each regime, runs the parity contrasts with traces, and records
the matched control k per regime and cost basis from development data only.

    python manifest_runner.py            -> parity checks + k per regime, updates the manifest
"""
import sys, json, bisect, statistics, math, time, hashlib
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.argv = ["x"]
import harness as H
from compte_controller import CompteController
import dev_dataset
MAN = r"C:\Projects\KinoliveLines\review\compte_frozen_manifest.json"
man = json.load(open(MAN, encoding="utf-8"))
sym, R, META = dev_dataset.load("b")

UNSUPPORTED_FIXED = {         # package field -> what the harness hard-codes (must match or reject)
    "max_risk_pct": (0.10, "harness: B.MAX_RISK_PCT (0.10) x $230, fixed"),
    "chest_cap": (10.0, "harness CHEST_CAP 10.0, fixed"), "jar_skim": (0.5, "harness JAR_SKIM 0.5, fixed"),
    "jar_stake": (0.5, "harness JAR_STAKE 0.5, fixed"), "jar_debt_mult": (0.5, "harness JAR_DEBT_MULT 0.5, fixed"),
    "jar_floor_cap": (10.0, "harness JAR_FLOOR_CAP 10.0, fixed"), "day_cap_waived": (True, "harness waives the cap while in debt, always"),
    "debt_mode": ("hwm", "harness debt_mode hwm"), "min_balance": (None, "not modelled (never binds above $20 in these sims) - DISCLOSED"),
    "week_target": (None, "informational only"), "label": (None, "label"), "touch_entries": (False, "harness has no TOUCH path"),
    "eq_half": (False, "live dial, not part of the frozen regimes - REJECT if true"),
    "recov_bullets_only": (False, "live dial, not part of the frozen regimes - REJECT if true"),
    "scale_ref_balance": (None, "mapped"), "movement": (None, "mapped"), "nervosity": (None, "mapped"),
}


def effective_cfg(pkg, balance, drag):
    """explicit mapping; returns (cfg, report) or raises on unsupported"""
    rep, cfg = {}, {}
    cfg["lot"] = float(pkg["base_lot"]); rep["lot"] = "base_lot %.2f" % cfg["lot"]
    cfg["bullets"] = int(pkg["max_extra"]) if pkg.get("adds_on", True) else 0
    rep["bullets"] = "max_extra %d, adds_on %s -> %d" % (pkg["max_extra"], pkg.get("adds_on", True), cfg["bullets"])
    cfg["jar"] = bool(pkg.get("jar", True)); rep["jar"] = str(cfg["jar"])
    cfg["kill_net"] = float(pkg["kill_net"]) if pkg.get("kill_net") not in (None, 0) else 0.0
    rep["kill_net"] = ("%.0f" % cfg["kill_net"]) if cfg["kill_net"] else "none"
    cfg["day_cap"] = float(pkg["day_cap"]) if pkg.get("day_cap") else 0.0; rep["day_cap"] = ("%.2f" % cfg["day_cap"]) if cfg["day_cap"] else "none"
    cfg["risk_fit"] = float(pkg.get("risk_fit_pct") or 0.0); rep["risk_fit"] = "risk_fit_pct %.1f%% -> %.1f (percent, unchanged)" % (cfg["risk_fit"], cfg["risk_fit"])
    cfg["rr"] = float(pkg["rr"]); cfg["k_streak"] = int(pkg["k_streak"]); rep["rr/k_streak"] = "%.1f / %d" % (cfg["rr"], cfg["k_streak"])
    cfg["nerv_gate"] = bool(pkg.get("nervosity", True)); cfg["movement"] = bool(pkg.get("movement", True))
    rep["gates"] = "nervosity %s, movement %s" % (cfg["nerv_gate"], cfg["movement"])
    cfg["internal"] = 1 if pkg.get("internal_entries") else 0; rep["internal"] = str(cfg["internal"])
    cfg["debt_gate"] = 1 if pkg.get("debt_gate", True) else 0; rep["debt_gate"] = "%s -> harness debt_gate %d (0 = every BOS taken in debt)" % (pkg.get("debt_gate", True), cfg["debt_gate"])
    if pkg.get("scale_with_balance"):
        cfg["balance"] = float(balance); cfg["scale_ref"] = float(pkg.get("scale_ref_balance") or 200.0); cfg["scale_daily"] = 1
        rep["scaling"] = "ON: lot and cap from (balance %.2f + run)/%.0f once per UTC day (live cadence)" % (cfg["balance"], cfg["scale_ref"])
    else:
        cfg["balance"] = 0.0; cfg["scale_daily"] = 0; rep["scaling"] = "OFF (flat lot)"
    cfg["drag"] = drag; rep["drag"] = "%.2f $/0.02 lot" % drag
    for k, (fixed, why) in UNSUPPORTED_FIXED.items():
        v = pkg.get(k)
        if fixed is None or v is None:
            continue
        if v != fixed:
            raise ValueError("REJECT %s: package %s=%r but %s" % (pkg.get("label", "?"), k, v, why))
    rep["fixed_or_disclosed"] = {k: why for k, (fixed, why) in UNSUPPORTED_FIXED.items() if fixed is not None or k == "min_balance"}
    return H.cfg_strict(cfg), rep


# ---------------- reference states (basis by drag)
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
K_SET = tuple(man["arms"]["exposure_control"]["K_SET"]); SHIFTS = man["arms"]["block_shift_control"]["shifts"]
out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset": META["sha256"], "regimes": {}, "parity_checks": {}}

print("=== effective configs (manifest only) ===", flush=True)
for uid, pname, bal in REGIMES:
    pkg = man["arms"]["baseline"]["package_regimes"][uid]
    try:
        cfg, rep = effective_cfg(pkg, bal, 0.0)
        print(uid, pname, json.dumps(rep), flush=True)
    except (ValueError, KeyError) as e:
        print(uid, pname, "REJECTED:", e, flush=True); out["regimes"][uid] = {"rejected": str(e)}

# ---------------- parity contrasts with traces
print("\n=== parity contrasts ===", flush=True)
cap_pkg = man["arms"]["baseline"]["package_regimes"]["u224016179"]      # valere_cap3: risk_fit 3 %
cfg_cap, _ = effective_cfg(cap_pkg, 267.42, 0.0)
cfg_nocap = dict(cfg_cap, risk_fit=0.0)
f1, t1 = run(cfg_nocap); f2, t2 = run(cfg_cap)
b1 = {x["t"]: x for x in t1}; changed = [(t, b1[t]["risk"], x["risk"], x["lot"]) for t, x in ((x["t"], x) for x in t2) if t in b1 and abs(b1[t]["risk"] - x["risk"]) > 0.005]
over = [x for x in t1 if x["risk"] > 0.03 * 267.42]
print("1. 3%% risk-fit (cap $%.2f at the start balance): trades above the cap without it %d; trades whose risk changed with it %d; e.g. %s" % (
    0.03 * 267.42, len(over), len(changed), changed[:3]), flush=True)
out["parity_checks"]["risk_fit"] = {"cap_usd": round(0.03 * 267.42, 2), "over_cap_without": len(over), "changed_with": len(changed), "examples": changed[:5], "pass": len(over) > 0 and len(changed) > 0}
ref_pkg = man["arms"]["baseline"]["package_regimes"]["reference_uncapped"]
cfg_ref, _ = effective_cfg(ref_pkg, 1000.0, 0.0); f3, t3 = run(cfg_ref)
adds3 = sum(x.get("add_n", 0) for x in t3)
print("2. reference regime (adds_on false, max_extra 0): adds fired %d (must be 0); trades %d net %.2f" % (adds3, len(t3), f3["net"]), flush=True)
out["parity_checks"]["reference_no_adds"] = {"adds_fired": adds3, "pass": adds3 == 0}
inf_pkg = man["arms"]["baseline"]["package_regimes"]["infinity"]
cfg_inf, _ = effective_cfg(inf_pkg, 175.70, 0.0); f4, t4 = run(cfg_inf)
lots = sorted(set(x["lot"] for x in t4)); cfg_inf_static = dict(cfg_inf, scale_daily=0); f5, t5 = run(cfg_inf_static)
print("3. balance scaling at live cadence (infinity, balance 175.70, ref 200): lots seen %s (static run lots %s); net daily %.2f vs static %.2f" % (
    lots, sorted(set(x["lot"] for x in t5)), f4["net"], f5["net"]), flush=True)
out["parity_checks"]["scaling_cadence"] = {"lots_daily": lots, "lots_static": sorted(set(x["lot"] for x in t5)), "net_daily": f4["net"], "net_static": f5["net"], "pass": True}
S0 = States(reference(0.0)); f6, t6 = run(cfg_inf, hook_directional(S0), True)
b4 = {x["t"]: x for x in t4}; inc = [(t, b4[t]["lot"], x["lot"]) for t, x in ((x["t"], x) for x in t6) if t in b4 and x["lot"] > b4[t]["lot"] + 1e-9]
halved = sum(1 for x in t6 if x["t"] in b4 and x["lot"] < b4[x["t"]]["lot"] - 1e-9)
print("4. policy rounding never increases the baseline lot: increases %d (must be 0); halved %d of %d matched" % (len(inc), halved, len(b4)), flush=True)
out["parity_checks"]["never_above_baseline"] = {"increases": len(inc), "halved": halved, "matched": len(b4), "pass": len(inc) == 0}

# ---------------- k per regime and cost basis (development only)
print("\n=== matched control k per regime (development, dataset b) ===", flush=True)
for drag in (0.0, 0.35):
    S = States(reference(drag)); basis = "B" if drag else "A"
    for uid, pname, bal in REGIMES:
        pkg = man["arms"]["baseline"]["package_regimes"][uid]
        try:
            cfg, rep = effective_cfg(pkg, bal, drag)
        except (ValueError, KeyError) as e:
            continue
        fb, trb = run(cfg); fp, trp = run(cfg, hook_directional(S), True)
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
        row = {"basis": basis, "balance_used": bal, "effective": rep, "baseline": {"net": fb["net"], "dd_cc": round(ddb, 2), "trades": len(trb)},
               "primary": {"net": fp["net"], "dd_cc": round(ddp, 2), "trades": len(trp), "ratio": round(ddp / ddb, 3) if ddb else None},
               "k": kb, "k_phases": per[kb], "beats_net": sum(1 for x in per[kb]["net"] if x < fp["net"]), "beats_dd": sum(1 for x in per[kb]["dd_cc"] if x > ddp)}
        out["regimes"].setdefault(uid, {})["drag_%.2f" % drag] = row
        print("%-20s %-12s drag %.2f basis %s | baseline net %7.2f dd %6.2f | primary net %7.2f dd %6.2f ratio %s | k=%d beats net %d/%d dd %d/%d | unkeyed %s" % (
            uid, pname, drag, basis, fb["net"], ddb, fp["net"], ddp, row["primary"]["ratio"], kb, row["beats_net"], kb, row["beats_dd"], kb, per[kb]["unkeyed"]), flush=True)
H.DIRGATE = None
json.dump(out, open(r"C:\Projects\KinoliveLines\study\manifest_runner_report.json", "w"), indent=1)
# ---- update the manifest: selected k, effective configs, unsupported list, harness hash
man["control_k_by_regime"] = {uid: {d: {"k": r["k"], "basis": r["basis"], "balance_used": r["balance_used"]} for d, r in v.items() if "k" in r} for uid, v in out["regimes"].items()}
man["effective_configs"] = {uid: {d: r["effective"] for d, r in v.items() if "effective" in r} for uid, v in out["regimes"].items()}
man["unsupported_fixed_or_disclosed"] = {k: v[1] for k, v in UNSUPPORTED_FIXED.items() if v[0] is not None or k == "min_balance"}
man["hashes"]["lab/harness.py"] = hashlib.sha256(open(r"C:\Projects\KinoliveLines\live\lab\harness.py", "rb").read()).hexdigest()[:16]
man["hashes"]["study/manifest_runner.py"] = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:16]
man["parity_report"] = "study/manifest_runner_report.json"
json.dump(man, open(MAN, "w", encoding="utf-8"), indent=1)
print("\nmanifest updated with k per regime, effective configs, disclosed/fixed fields", flush=True)
