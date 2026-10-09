"""Development replay of the three Compte allocation policies (ChatGPT brief
2026-10-09, review 5 "minimum first economic deliverable").

INPUT CURVE: an INDEPENDENT fixed-size reference - the frozen strategy
simulated with n_cont unlimited, no bullets, no jar, lot 0.02 - whose trades
carry their close time. At every entry of the LIVE-settings bot (jar on,
package dynamics) the three compte-ctl-2 controllers (global / buy / sell)
are fed with the reference outcomes closed STRICTLY before that entry.
No aggregate-P&L / multiplier reconstruction is used.

POLICIES
  baseline      current frozen package, no allocation
  global        0.5x while the GLOBAL reference curve is in a downtrend with
                no CHoCH up pending; 1x otherwise; never above 1x
  directional   0.5x only if the trade's OWN side (buy / sell curve) is in
                that state
Each policy in two forms: main+adds (the add budget halves too - the primary,
economically complete policy) and main-only (attribution diagnostic).

CONTROLS
  constant exposure  a fixed multiplier on every trade, chosen so the summed
                     PLANNED stop risk (dist x lot, main + max add budget)
                     matches the candidate's on the development data
  block-shifted      the candidate's own multiplier schedule (by entry index)
                     circularly shifted by whole blocks of 20 entries, run
                     through the full sequential simulator (serial dependence
                     kept); 10 shifts, median reported

OUTPUTS per run: net, planned exposure, worst drop, tail (sum of the 5 worst
trades, p95 loss), trades, and the continuous later third of the period.
Cold-start halves (run_cfg) are reported apart as a diagnostic. Costs:
spread 7 and an execution drag of 0 and 0.35 $/0.02 lot (the measured
history's typical magnitude). Ambiguity: the harness is bar-based; a bar
hitting both barriers is scored by its own tie rule (pessimistic for the
opened side) - a known limitation, stated.
All data here were inspected before: DEVELOPMENT, never a holdout."""
import sys, json, bisect, statistics
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.argv = ["x"]
import harness as H
from compte_controller import CompteController
sym, R = H.bars()
OUT = {}

# ---------------- independent fixed-size reference
REF_CFG = {"n_cont": 999, "bullets": 0, "jar": False}
H.TRACE = []; fr = H.simulate(R, 7.0, REF_CFG)
ref = sorted([x for x in H.TRACE if x.get("pnl") is not None and x.get("tc")], key=lambda x: x["tc"]); H.TRACE = None
TC = [x["tc"] for x in ref]
print("reference: %d trades, net %.2f (fixed 0.02, no recovery)" % (len(ref), fr["net"]), flush=True)
_cache = {}
def states_at(t):
    n = bisect.bisect_left(TC, t)                 # closed strictly before t
    if n in _cache: return _cache[n]
    out = {}
    for name, flt in (("global", lambda d: True), ("buy", lambda d: d == 1), ("sell", lambda d: d == -1)):
        c = CompteController()
        for x in ref[:n]:
            if flt(x["d"]): c.feed(x["pnl"])
        out[name] = (c.state["trend"], c.state["choch"])
    _cache[n] = out
    return out
def reduce(trend, choch):
    return trend == -1 and choch != 1

# ---------------- policies as EQHOOK closures (record their schedule)
def policy(kind):
    sched = []
    def hook(_all):
        t = CUR["t"]; d = CUR["d"]; st = states_at(t)
        if kind == "global": m = 0.5 if reduce(*st["global"]) else 1.0
        elif kind == "directional": m = 0.5 if reduce(*st["buy" if d == 1 else "sell"]) else 1.0
        else: m = 1.0
        sched.append(m); return m, False
    hook.sched = sched
    return hook
CUR = {"t": None, "d": None}
# the harness calls EQHOOK before TRACE gets the entry; capture t,d via DIRGATE (called just before)
def capture(t, d):
    CUR["t"], CUR["d"] = t, d; return True
H.DIRGATE = capture

def metrics(f, tr):
    pn = [x["pnl"] for x in tr if x["pnl"] is not None]
    losses = sorted(p for p in pn if p < 0)
    exp = sum(x.get("risk", 0) for x in tr)
    t_last = tr[int(len(tr) * 2 / 3)]["t"] if tr else 0
    late = sum(x["pnl"] for x in tr if x["t"] >= t_last and x["pnl"] is not None)
    return {"net": round(f["net"], 2), "trades": f["trades"], "exposure": round(exp, 2), "worst_drop": round(-f["worst_debt"], 2),
            "tail5": round(sum(losses[:5]), 2), "p95_loss": round(losses[int(len(losses) * 0.05)] if losses else 0, 2),
            "later_third": round(late, 2)}

def run(cfg, hook=None, adds=False, label=""):
    H.EQHOOK = hook; H.EQ_ADDS = adds; H.TRACE = []
    f = H.simulate(R, 7.0, cfg); tr = list(H.TRACE); H.TRACE = None
    sched = list(hook.sched) if (hook is not None and hasattr(hook, "sched")) else None   # the continuous run's schedule only
    v = H.run_cfg(R, 7.0, cfg)
    H.EQHOOK = None; H.EQ_ADDS = False
    m = metrics(f, tr); m["h1"], m["h2"] = round(v["h1"]["net"], 2), round(v["h2"]["net"], 2)
    m["label"] = label; return m, tr, sched

def row(m):
    print("%-40s net %8.2f | later third %8.2f | drop %7.2f | tail5 %7.2f p95 %6.2f | exposure %8.2f | trades %3d | cold halves %7.2f / %7.2f" % (
        m["label"], m["net"], m["later_third"], m["worst_drop"], m["tail5"], m["p95_loss"], m["exposure"], m["trades"], m["h1"], m["h2"]), flush=True)

for drag in (0.0, 0.35):
    LIVE = {"jar": True, "drag": drag}
    print("\n=== spread 7, execution drag $%.2f per 0.02 lot ===" % drag, flush=True)
    base, _, _ = run(LIVE, None, label="baseline"); row(base)
    res = {"baseline": base}
    for kind in ("global", "directional"):
        for adds in (True, False):
            lab = "%s half (%s)" % (kind, "main+adds PRIMARY" if adds else "main-only diag")
            m, tr, sched = run(LIVE, policy(kind), adds, lab); row(m); res[lab] = m
            if adds:
                # constant-exposure control: multiplier matching the candidate's planned exposure
                k = m["exposure"] / base["exposure"] if base["exposure"] else 1.0
                def const_hook(_a, k=k): return k, False
                mc, _, _ = run(LIVE, const_hook, True, "   control: constant %.2fx exposure" % k); row(mc); res[lab + " const"] = mc
                # block-shifted schedules through the sequential simulator
                nets, drops = [], []
                for sh in range(1, 11):
                    s2 = sched[:]; off = (sh * 20) % max(1, len(s2))
                    s2 = s2[off:] + s2[:off]
                    it = iter(s2)
                    def sh_hook(_a, it=it):
                        try: return next(it), False
                        except StopIteration: return 1.0, False
                    ms, _, _ = run(LIVE, sh_hook, True, "")
                    nets.append(ms["net"]); drops.append(ms["worst_drop"])
                nets.sort(); drops.sort()
                print("   control: block-shifted schedule x10 -> median net %.2f, median drop %.2f | candidate beats: net %d/10, drop %d/10" % (
                    nets[5], drops[5], sum(1 for x in nets if x < m["net"]), sum(1 for x in drops if x < m["worst_drop"])), flush=True)
                res[lab + " shift"] = {"median_net": nets[5], "median_drop": drops[5], "beats_net": sum(1 for x in nets if x < m["net"]), "beats_drop": sum(1 for x in drops if x < m["worst_drop"])}
    OUT["drag_%.2f" % drag] = res
H.DIRGATE = None
json.dump(OUT, open(r"C:\Projects\KinoliveLines\study\compte_policies_dev_replay.json", "w"), indent=1)
print("\nreference stream: %d outcomes; input = fixed 0.02 gross, spread 7, same drag as the bot; states causal (closed before entry); DEVELOPMENT DATA" % len(ref))
