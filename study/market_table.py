"""The owner's market table (2026-10-16): per market and robot, the bar-pack result (synthetic fills, 2026-10-15
rerun) next to the tick-pack result (every broker tick) with its luck check. Reads live/robots/market_tests.json,
live/robots/results/<rid>@<SYM>.json and study/random_control_<rid>_<SYM>.json. Prints markdown.
    python study/market_table.py
"""
import json, os, glob
HERE = os.path.dirname(os.path.abspath(__file__)); LIVE = os.path.join(os.path.dirname(HERE), "live")
Q = json.load(open(os.path.join(LIVE, "robots", "market_tests.json"), encoding="utf-8"))
NAMES = {"owl": "Owl", "pekos-owl": "Pekos owl"}
rows = {}
for x in Q:
    if x.get("state") != "done" or x.get("net") is None:
        continue
    key = (x["rid"], x["sym"].upper())
    rows.setdefault(key, {"bars": None, "ticks": None})
    kind = "ticks" if "tick" in (x.get("note") or "") else "bars"
    rows[key][kind] = x          # the latest done job of each kind wins (the queue is chronological)
out = ["| Market | Robot | Bars (synthetic fills) | Ticks (every broker tick) | Trades | Luck check | Verdict |", "|---|---|---|---|---|---|---|"]
for (rid, sym), r in sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0])):
    res = None
    try:
        res = json.load(open(os.path.join(LIVE, "robots", "results", "%s@%s.json" % (rid, sym)), encoding="utf-8"))
    except Exception:
        pass
    tick_res = res if res and res.get("fills") == "ticks" else None
    t_net = tick_res["robot"]["net"] if tick_res else (r["ticks"]["net"] if r["ticks"] else None)
    trades = tick_res["robot"]["trades"] if tick_res else "?"
    pc = None
    try:
        c = json.load(open(os.path.join(HERE, "random_control_%s_%s.json" % (rid, sym)), encoding="utf-8"))
        if c.get("real", {}).get("net") is not None and t_net is not None and abs(float(c["real"]["net"]) - float(t_net)) < 0.02:
            pc = float(c["percentile"])
    except Exception:
        pass
    b_net = r["bars"]["net"] if r["bars"] else None
    fmt = lambda v: ("%+.2f $" % v) if v is not None else "-"
    luck = ("%.0fe percentile" % pc) if pc is not None else ("pending" if (t_net or 0) > 0 else "not needed")
    if t_net is None:
        verdict = "no tick test yet"
    elif t_net <= 0:
        verdict = "no"
    elif pc is None:
        verdict = "waiting for the luck check"
    else:
        verdict = "PASSES the real-money rule" if pc >= 95 else "within luck: test only"
    out.append("| %s | %s | %s | %s | %s | %s | %s |" % (sym, NAMES.get(rid, rid), fmt(b_net), fmt(t_net), trades, luck, verdict))
print("\n".join(out))
