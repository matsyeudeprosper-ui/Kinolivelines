"""random_control_market.py (2026-10-14, owner: "run that control") - does a robot's ENTRY beat chance on a market?

Preregistered before any run: the robot is replayed on the market pack exactly as in its market test (same arm,
same filters, same recovery and money, same synthetic quotes, no extra drag). Each control run replaces the robot's
opportunity stream with the SAME NUMBER of opportunities at RANDOM closed bars and in a RANDOM direction:
  * each random opportunity copies a randomly drawn REAL opportunity's stop distance (|close - stop|), its flip flag
    and its market-state fields (awake, nv, mv2), so risk per trade and the gates' pass rates match the robot's;
  * the pullback (trend) state given to a random bar is the one at the last REAL opportunity before it;
  * level = the bar's close (never reused), hour / weekday from the bar's own time.
Reported: the robot's net, the control's distribution (100 seeds), and the robot's percentile. Verdict rule (fixed):
top 5 % -> the entries beat chance here; otherwise the market result is within luck.
    python random_control_market.py USTEC [robot id] [seeds]
"""
import sys, os, json, time, pickle, random, bisect
ARGS = list(sys.argv); sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import robot_runner as RR
import market_pack as MP
import tick_engine_matrix as TMX
from datetime import datetime, timezone
E, K, H = RR.E, RR.K, RR.H

sym = (ARGS[1] if len(ARGS) > 1 else "USTEC").upper()
rid = ARGS[2] if len(ARGS) > 2 else "owl"
seeds = int(ARGS[3]) if len(ARGS) > 3 else 100
d = MP.pack_dir(sym); meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
D = MP.use(meta, d, E, K, TMX, H)
TM, BID, ASK, nb, END = MP.synthetic_ticks(D, meta)
K.install_nopause_gate()
cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": RR.BAL}), drag=0.0, limits_live=1))
opps, bars = E.streams(cfg0, D)
cache = pickle.load(open(K.CACHE, "rb")); assert cache.get("bars_sha") == meta["sha256"]
S_idx = cache["states"]
S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
reg = json.load(open(RR.REG, encoding="utf-8")); robots = {r["id"]: r for r in reg.get("robots") or []}
PCS = {p["id"]: p for p in reg.get("pieces") or []}
parts = RR.resolve(rid, robots)
RR.DRAG = 0.0


def run(op, St):
    arm = RR.arm_for("robot", parts, bars, St, PCS)
    return RR.run_pair([arm], TM, BID, ASK, END, op, bars)["robot"]


t0 = time.time()
real = run(opps, S)
print("%s on %s: real net %.2f, %d trades (%.0fs)" % (rid, sym, real["net"], real["trades"], time.time() - t0), flush=True)

times = [int(x) for x in D["time"]]
real_t = [o["t"] for o in opps]; real_sorted = sorted(range(len(opps)), key=lambda k: opps[k]["t"])
rt_sorted = [opps[k]["t"] for k in real_sorted]
lo = 1440                                   # same warm-up as the harness (nervosity needs a day of bars)
nets, pfs, trs = [], [], []
for sd in range(seeds):
    rnd = random.Random(1000 + sd)
    idx = sorted(rnd.sample(range(lo, len(D) - 2), len(opps)))
    op, St = [], {}
    for i in idx:
        src = opps[rnd.randrange(len(opps))]
        t = times[i]; cl = float(D["close"][i]); dist = abs(src["cl"] - src["slp"]) or 1e-6
        dr = rnd.choice((1, -1))
        g = datetime.fromtimestamp(t, tz=timezone.utc)
        op.append({"t": t, "i": i, "d": dr, "slp": cl - dr * dist, "cl": cl, "flip": src["flip"], "awake": src["awake"],
                   "nv": src["nv"], "mv2": src["mv2"], "i_fire": False, "lvl": cl, "weekday": g.weekday(), "hour": g.hour, "minute": g.minute})
        j = bisect.bisect_right(rt_sorted, t) - 1
        St[t] = S.get(rt_sorted[j], (0, 0, None, None)) if j >= 0 else (0, 0, None, None)
    r = run(op, St)
    nets.append(r["net"]); pfs.append(r["profit_factor"] or 0); trs.append(r["trades"])
    if (sd + 1) % 10 == 0:
        print("  %d/%d seeds (%.0fs)" % (sd + 1, seeds, time.time() - t0), flush=True)

nets_s = sorted(nets)
pct = 100.0 * sum(1 for x in nets if x < real["net"]) / len(nets)
q = lambda p: nets_s[min(len(nets_s) - 1, int(p * len(nets_s)))]
out = {"symbol": sym, "robot": rid, "seeds": seeds, "real": {k: real[k] for k in ("net", "trades", "win_rate", "profit_factor", "cc_dd", "first_half", "later_half")},
       "control": {"median": q(0.5), "p05": q(0.05), "p25": q(0.25), "p75": q(0.75), "p95": q(0.95), "mean": sum(nets) / len(nets),
                   "share_positive": sum(1 for x in nets if x > 0) / len(nets), "median_trades": sorted(trs)[len(trs) // 2],
                   "median_pf": sorted(pfs)[len(pfs) // 2]},
       "percentile": pct, "verdict": "beats chance" if pct >= 95 else "within luck", "nets": nets,
       "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
json.dump(out, open(os.path.join(HERE, "random_control_%s_%s.json" % (rid, sym)), "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "nets"}, indent=1))
