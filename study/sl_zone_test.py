"""sl_zone_test.py (2026-10-14, owner idea): only take a trade whose STOP-LOSS is inside the pullback chart's
allowed zone - for a buy, stop ABOVE the pullback chart's last BOS; for a sell, stop BELOW it. Today's rule only
asks the ENTRY to be beyond that level.

Preregistered: the Owl on the BTC tick bench (same as its robot test: 42 days, $200, live gate order, sticky
pullback states), with and without the rule, cost 0.35 and 0.00. The rule refuses at the weather position (after the
pullback filter, the allowance already consumed - as the live bot would). Grades = lab/harness.py verdict():
A better money in BOTH halves and worst debt not worse; B partly; C otherwise. Also: the baseline's trades split
into 'stop inside' / 'stop outside' the zone, with their results (what the rule would remove).
    python sl_zone_test.py [robot id]
"""
import sys, os, json, time, pickle
ARGS = list(sys.argv); sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import robot_runner as RR
E, K, H = RR.E, RR.K, RR.H

rid = ARGS[1] if len(ARGS) > 1 else "owl"
reg = json.load(open(RR.REG, encoding="utf-8")); robots = {r["id"]: r for r in reg.get("robots") or []}
PCS = {p["id"]: p for p in reg.get("pieces") or []}
parts = RR.resolve(rid, robots)
K.install_nopause_gate()
TM, BID, ASK, nb, END = E.load_ticks()
cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": RR.BAL}), drag=0.0, limits_live=1))
opps, bars = E.streams(cfg0, E.R)
cache = pickle.load(open(K.CACHE, "rb")); S_idx = cache["states"]
S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}


def outside(o):
    """True = the stop is NOT inside the allowed zone (or the zone is unknown)"""
    st = S.get(o["t"]); lb = st[3] if st else None
    if lb is None:
        return True
    return float(o["slp"]) <= lb if o["d"] == 1 else float(o["slp"]) >= lb


def arm(rule):
    a = RR.arm_for("robot", parts, bars, S, PCS)
    if rule:
        base = a.late_gates
        def lg(o, debt_now, _b=base, _a=a):
            if outside(_a._with_stop(o) if hasattr(_a, "_with_stop") else o):
                _a.n["sl_zone"] = _a.n.get("sl_zone", 0) + 1
                return True
            return _b(o, debt_now)
        a.late_gates = lg
    return a


def summ(o):
    return {k: o[k] for k in ("net", "trades", "win_rate", "profit_factor", "cc_dd", "first_half", "later_half", "worst")}


out = {"robot": rid, "days": round((int(TM[-1]) - int(TM[0])) / 86400000, 1)}
for drag in (0.35, 0.0):
    RR.DRAG = drag
    t0 = time.time()
    b = arm(False); r = RR.run_pair([b], TM, BID, ASK, END, opps, bars)["robot"]
    v = arm(True); rv = RR.run_pair([v], TM, BID, ASK, END, opps, bars)["robot"]
    out["drag%s" % drag] = {"today": summ(r), "sl_inside_rule": summ(rv), "refused_by_rule": v.n.get("sl_zone", 0)}
    print("drag", drag, json.dumps(out["drag%s" % drag]), "(%.0fs)" % (time.time() - t0), flush=True)

# what the rule removes: the baseline's own trades split by where their stop sat
RR.DRAG = 0.35
b = arm(False)
from tick_engine_matrix import summarise
RR.run_pair([b], TM, BID, ASK, END, opps, bars)
tl = summarise(b, TM, BID, ASK, END, (int(TM[0]) + int(TM[-1])) // 2)["trades_list"]
keys = sorted(tl[0].keys()) if tl else []
by_t = {o["t"]: o for o in opps}
ins, outs = [], []
for t in tl:
    o = by_t.get(t.get("t") or t.get("sig_t") or t.get("t_sig"))
    if o is None:
        continue
    (outs if outside(b._with_stop(o) if hasattr(b, "_with_stop") else o) else ins).append(t["pnl"])
f = lambda L: {"n": len(L), "net": round(sum(L), 2), "win_rate": round(sum(1 for x in L if x > 0) / len(L), 3) if L else None,
               "avg": round(sum(L) / len(L), 2) if L else None}
out["split_today"] = {"stop_inside": f(ins), "stop_outside": f(outs), "matched": len(ins) + len(outs), "trades": len(tl), "trade_keys": keys}
print("split", json.dumps(out["split_today"]), flush=True)
json.dump(out, open(os.path.join(HERE, "sl_zone_test_%s.json" % rid), "w"), indent=1)
