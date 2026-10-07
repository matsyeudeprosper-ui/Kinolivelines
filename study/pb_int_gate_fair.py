# Fair readout of pbint_gate.py: the pb chart needs RAW bars of warm-up, so only
# trades after the first pb event can be gated. Compare base vs gates on THAT span,
# split into two halves, and run the random-pick control on the same span.
import os, random, datetime as dt
HERE = r"C:\Users\ADMINI~1\AppData\Local\Temp\2\claude\C--Users-Administrator--local-bin\b61e52db-3e75-4c34-a894-1952c9c0ef5a\scratchpad"
src = open(os.path.join(HERE, "pbint_gate.py")).read().split("res = {}")[0]
exec(src)
TS = min(t for t, *_ in events)
H.DIRGATE = None; H.TRACE = []
H.simulate(R, 7.0, {}); base = [x for x in H.TRACE if x["pnl"] is not None and x["t"] >= TS]; H.TRACE = None
TM = base[len(base) // 2]["t"]
print("span from", dt.datetime.utcfromtimestamp(TS), "| halves split at", dt.datetime.utcfromtimestamp(TM), "| base trades", len(base))
def row(name, tr):
    a = stats([x["pnl"] for x in tr]); h1 = sum(x["pnl"] for x in tr if x["t"] < TM); h2 = sum(x["pnl"] for x in tr if x["t"] >= TM)
    s = stats([x["pnl"] for x in tr if x["t"] >= T27])
    print("%-32s n %3d win %4.1f%% net %7.2f DD %7.2f PF %.2f | 1st half %7.2f 2nd half %7.2f | since 27/9: n %3d net %7.2f PF %.2f"
          % (name, a["n"], a["wr"], a["net"], a["dd"], a["pf"], h1, h2, s["n"], s["net"], s["pf"]), flush=True)
print("\nA) bot replay with the gate (trades it really takes, chain effects included)")
for name, g in RULES:
    H.DIRGATE = g; H.TRACE = []
    H.simulate(R, 7.0, {}); tr = [x for x in H.TRACE if x["pnl"] is not None and x["t"] >= TS]; H.TRACE = None; H.DIRGATE = None
    row(name, tr)
print("\nB) base trades kept by each gate vs 2000 random picks of the same size (same span)")
random.seed(7); P = [x["pnl"] for x in base]
for name, g in RULES[1:]:
    for half, lo, hi in (("all", 0, 2e9), ("h1", 0, TM), ("h2", TM, 2e9)):
        bb = [x for x in base if lo <= x["t"] < hi]; PP = [x["pnl"] for x in bb]
        keep = [x["pnl"] for x in bb if g(x["t"], x["d"])]
        if not keep: print("  %-32s %s none kept" % (name, half)); continue
        k = len(keep); s = sum(keep)
        pct = 100 * sum(1 for _ in range(2000) if sum(random.sample(PP, k)) < s) / 2000
        print("  %-32s %-3s kept %3d of %3d  per trade %+.2f (all %+.2f)  random pct %3.0f" % (name, half, k, len(PP), s / k, sum(PP) / len(PP), pct))
