"""merge_random_control.py <SYM> <robot> - join the _part<start>.json files of random_control_market.py into one
verdict (same fixed rule: top 5 % of the random runs = the entries beat chance on this market)."""
import sys, os, json, glob
HERE = os.path.dirname(os.path.abspath(__file__))
sym, rid = sys.argv[1].upper(), sys.argv[2]
parts = sorted(glob.glob(os.path.join(HERE, "random_control_%s_%s_part*.json" % (rid, sym))))
P = [json.load(open(f)) for f in parts]
real = P[0]["real"]; nets = sorted(sum((p["nets"] for p in P), []))
n = len(nets); q = lambda x: nets[min(n - 1, int(x * n))]
pct = 100.0 * sum(1 for x in nets if x < real["net"]) / n
out = {"symbol": sym, "robot": rid, "seeds": n, "real": real,
       "control": {"median": q(.5), "p05": q(.05), "p25": q(.25), "p75": q(.75), "p95": q(.95), "mean": sum(nets) / n,
                   "share_positive": sum(1 for x in nets if x > 0) / n, "best": nets[-1], "worst": nets[0]},
       "percentile": pct, "verdict": "beats chance" if pct >= 95 else "within luck", "nets": nets}
json.dump(out, open(os.path.join(HERE, "random_control_%s_%s.json" % (rid, sym)), "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "nets"}, indent=1))
