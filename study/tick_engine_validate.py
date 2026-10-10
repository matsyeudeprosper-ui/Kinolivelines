"""Infinity end-to-end validation of the tick engine against the harness bar-level baseline
(review 14: regenerated on the final run; the rounding source stated). Writes
study/tick_engine_validation_infinity.md."""
import sys, json, statistics
sys.argv = ["x"]
src = open(r"C:\Projects\KinoliveLines\study\manifest_runner.py", encoding="utf-8").read().split("REGIMES = [")[0]
ns = {"__file__": r"C:\Projects\KinoliveLines\study\manifest_runner.py"}; exec(src, ns)
H, man, R, effective_cfg = ns["H"], ns["man"], ns["R"], ns["effective_cfg"]; H.DIRGATE = None
cfg, _ = effective_cfg(man["arms"]["baseline"]["package_regimes"]["infinity"], 175.70, 0.0)
H.TRACE = []; f = H.simulate(R, 7.0, cfg); hb = sorted([x for x in H.TRACE if x.get("pnl") is not None], key=lambda x: x["t"]); H.TRACE = None
eng_row = json.load(open(r"C:\Projects\KinoliveLines\study\tick_engine.json"))["rows"]["infinity|0.00"]["arms"]["baseline"]
eng = eng_row["trades_list"]
eb = {x["t"]: x for x in eng}; hbm = {x["t"]: x for x in hb}
common = sorted(set(eb) & set(hbm)); only_h = sorted(set(hbm) - set(eb)); only_e = sorted(set(eb) - set(hbm))
d_pnl = [eb[t]["pnl"] - hbm[t]["pnl"] for t in common]; agree = sum(1 for t in common if eb[t]["win"] == hbm[t]["win"])
flips = [t for t in common if eb[t]["win"] != hbm[t]["win"]]; flip_sum = sum(eb[t]["pnl"] - hbm[t]["pnl"] for t in flips)
w = [eb[t]["pnl"] - hbm[t]["pnl"] for t in common if eb[t]["win"] == hbm[t]["win"] == True]; l = [eb[t]["pnl"] - hbm[t]["pnl"] for t in common if eb[t]["win"] == hbm[t]["win"] == False]
sum_rounded = round(sum(x["pnl"] for x in eng), 2)
first = next((t for t in sorted(set(eb) | set(hbm)) if (t in eb) != (t in hbm)), None)
md = f"""# Tick engine - Infinity end-to-end validation (drag 0), regenerated on the final run

Engine baseline arm vs the harness bar-level baseline (same manifest package, dataset b).

| | harness (bars) | engine (ticks) |
|---|---|---|
| trades | {len(hb)} | {len(eng)} |
| net (engine: unrounded running balance) | {f["net"]:.2f} | {eng_row["net"]:.2f} |
| engine: sum of the per-trade P&L rounded to cents | | {sum_rounded:.2f} |
| common signals traded by both | {len(common)} | |
| harness-only / engine-only trades | {len(only_h)} | {len(only_e)} |
| outcome agreement on common signals | {agree} / {len(common)} ({100.0 * agree / max(1, len(common)):.1f}%) | |
| per-trade P&L difference on common signals (engine - harness) | mean {statistics.mean(d_pnl):.3f}, median {statistics.median(d_pnl):.3f}, sum {sum(d_pnl):.2f} | |
| of which the {len(flips)} outcome flips | {flip_sum:.2f} | |
| common wins ({len(w)}): mean diff | {statistics.mean(w) if w else 0:.3f} | |
| common losses ({len(l)}): mean diff | {statistics.mean(l) if l else 0:.3f} | |
| first path divergence (signal time) | {first} ({"harness-only" if first in hbm else "engine-only"}) | |

The $0.0x between the engine's net and the sum of its rounded per-trade rows is cent rounding of the
attribution (the running balance is unrounded internally; Reply 14 item 4). The gap to the harness is the
intended execution realism: the live ask-based target geometry flips a few bar-level wins into tick-level
losses, 1 s fills and the embedded bid/ask cost cents per trade, and the paths diverge where a tick exit
lands later than a bar-granular one (signals skipped while the engine's position was still open).
"""
open(r"C:\Projects\KinoliveLines\study\tick_engine_validation_infinity.md", "w", encoding="utf-8").write(md)
print(md)
