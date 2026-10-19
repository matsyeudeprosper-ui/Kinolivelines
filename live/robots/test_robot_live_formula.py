"""Live bot vs bench for FORMULA pieces (owner 2026-10-19: the live bot reads the Atelier's new pieces).
    python live/robots/test_robot_live_formula.py
The bench computes a formula once over its whole candle array and reads candle i; the live bot adds candles one
by one to its memory (robot_live.Candles) and reads the LAST one. On the real bench candles + made-up breaks of
the eyes, both must give the same answer at every checked candle: entry edges (+ the stand-in protected point),
filters, stop prices, close formulas."""
import os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
_argv = sys.argv; sys.argv = ["x"]
import numpy as np
import robot_expr as X
import robot_live as L
import tick_engine as E
sys.argv = _argv

N = 12000                                   # ~8 days of the bench's own candles
R = E.R[-N:]
rnd = random.Random(7)
opps, S = [], {}
for i in range(50, N):                      # made-up eyes: a break on ~1 candle in 60, its trend
    if rnd.random() < 1 / 60:
        o = {"i": i, "t": int(R["time"][i]), "d": rnd.choice((1, -1)), "flip": rnd.random() < 0.3}
        opps.append(o); S[o["t"]] = (rnd.choice((1, -1, 0)), 0, None, None)
B = X.Bars.from_rates(R, X.eyes_from_opps(opps, N, S))

FORMULAS = ["close > ema(close, 50) @ H1 and rsi(close, 14) < 40", "cross_up(close, pdh) and london",
            "trend == 1 and bos_up", "choch_down or (close < bb_low(close, 20, 2) @ M5)",
            "close < lowest(low, 30) @ M15", "macd(close, 12, 26) > macd_signal(close, 12, 26, 9) and newyork",
            "close > vwap() and rising(close, 3)", "lowest(low, 10) - atr(14)", "highest(high, 10) + atr(14) @ M5",
            "day_high - 0.5 * (day_high - day_low)"]
full = {f: X.evaluate(f, B) for f in FORMULAS + ["lowest(low, 20)", "highest(high, 20)"]}
rules = {"entry": {"event": "formula", "buy": FORMULAS[1], "sell": FORMULAS[3]},
         "filters": [{"kind": "formula", "buy": FORMULAS[0], "sell": None}, {"kind": "formula", "buy": None, "sell": FORMULAS[4]}],
         "stop": {"kind": "formula", "buy": FORMULAS[7], "sell": FORMULAS[8]},
         "exit": {"target": None, "choch": False, "time_min": None, "breakeven_at": None, "close_buy": FORMULAS[5], "close_sell": FORMULAS[6]}}
assert L.uses_formulas(rules) and not L.uses_formulas({"entry": {"event": "bos"}})

def tr(a, i):
    return bool(a[i] == a[i] and a[i] != 0)

fails, checks = 0, 0
def check(name, a, b):
    global fails, checks
    checks += 1
    same = (a == b) or (isinstance(a, float) and isinstance(b, float) and (a != a and b != b or abs(a - b) < 1e-9))
    if not same:
        fails += 1
        if fails <= 15:
            print("  FAIL", name, "bench", a, "live", b)

# the bench's entry edges (robot_runner.robot_opps)
edge = {}
for d, src in ((1, rules["entry"]["buy"]), (-1, rules["entry"]["sell"])):
    t = full[src] == full[src]
    t = t & (np.nan_to_num(full[src]) != 0)
    edge[d] = t & ~np.r_[False, t[:-1]]
edges = set(int(i) for d in edge for i in np.flatnonzero(edge[d]))
probe = sorted(set(rnd.sample(range(1500, N), 400)) | {i for i in edges if i >= 1500})

C = L.Candles()
opp_at = {o["i"]: o for o in opps}
nxt = 0
for i in range(N):
    o = opp_at.get(i)
    C.add(R["time"][i], R["open"][i], R["high"][i], R["low"][i], R["close"][i], R["tick_volume"][i],
          d=o["d"] if o else 0, flip=o["flip"] if o else False, trend=S[o["t"]][0] if o else None)
    if nxt >= len(probe) or i != probe[nxt]:
        continue
    nxt += 1
    for f in FORMULAS:
        check("%s @%d" % (f, i), float(full[f][i]), C.now(f))
    # entry: the bench takes the sell first on a candle where both fire
    want = None
    for d in (-1, 1):
        if edge[d][i]:
            p = float(full["lowest(low, 20)"][i] if d == 1 else full["highest(high, 20)"][i])
            if p == p:
                want = (d, p); break
    check("entry @%d" % i, want, L.formula_entry(rules, C))
    for d in (1, -1):
        fb = rules["filters"][0]["buy"] if d == 1 else None
        fs = rules["filters"][1]["sell"] if d == -1 else None
        bench_ok = (fb is None or tr(full[fb], i)) and (fs is None or tr(full[fs], i))
        check("filters d=%d @%d" % (d, i), bench_ok, L.filters_ok(rules, 12, 2, None, None, d=d, C=C)[0])
        sp = full[FORMULAS[7] if d == 1 else FORMULAS[8]][i]
        check("stop d=%d @%d" % (d, i), float(sp), float(L.stop_for(rules, d, 0.0, 0, 0, 0, C=C)))
        xs = FORMULAS[5] if d == 1 else FORMULAS[6]
        check("exit d=%d @%d" % (d, i), tr(full[xs], i), L.formula_exit(rules, d, C) is not None)

# the gates around them
check("eyes' break refused for a formula robot", False, L.entry_ok(rules, "BOS")[0])
check("formula signal allowed", True, L.entry_ok(rules, "FORMULA")[0])
check("formula signal refused by a BOS robot", False, L.entry_ok({"entry": {"event": "bos"}}, "FORMULA")[0])
check("no memory = filter refuses", False, L.filters_ok(rules, 12, 2, None, None, d=1, C=None)[0])
print("checked %d candles, %d entry edges, %d comparisons" % (len(probe), len([i for i in edges if i >= 1500]), checks))
print("FORMULA LIVE vs BENCH: " + ("OK" if not fails else "%d FAILS" % fails))
sys.exit(1 if fails else 0)
