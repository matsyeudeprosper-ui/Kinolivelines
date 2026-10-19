"""The bot's own formula code path, offline (owner 2026-10-19). No MT5: the functions fx_seed / fx_catch_up /
robot_formula_exit and the Struct engine are lifted out of structure_bos_bot.py and run against the bench's
candles with a fake terminal that "lives" at a moving candle. Checks: the memory equals the candles (also after
missed candles), formula entries fire on the same candles as the bench's edges, the close formula closes.
    python live/robots/test_bot_formula_path.py"""
import ast, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); LIVE = os.path.dirname(HERE)
sys.path[:0] = [HERE, r"C:\Projects\KinoliveLines\study", LIVE, os.path.join(LIVE, "lab")]
_argv = sys.argv; sys.argv = ["x"]
import numpy as np
import robot_expr as X
import robot_live as RL
import tick_engine as E
sys.argv = _argv

src = open(os.path.join(LIVE, "structure_bos_bot.py"), encoding="utf-8-sig").read()
tree = ast.parse(src)
want = {"Struct", "fx_seed", "fx_catch_up", "robot_formula_exit"}
nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in want]
assert {n.name for n in nodes} == want, [n.name for n in nodes]
# module-level constants Struct may read
consts = [n for n in tree.body if isinstance(n, ast.Assign) and all(isinstance(t, ast.Name) and t.id.isupper() for t in n.targets)
          and isinstance(n.value, (ast.Constant, ast.UnaryOp, ast.BinOp))]

Rall = E.R
NOW = {"k": 0}
LOG, CLOSED = [], []


class FakeMT5:
    TIMEFRAME_M1 = 1
    POSITION_TYPE_BUY = 0


class Pos:
    def __init__(self, d):
        self.ticket = 1; self.type = 0 if d == 1 else 1


POS = []
ROBOT = {"entry": {"event": "formula", "buy": "cross_up(close, ema(close, 30))", "sell": "cross_down(close, ema(close, 30))"},
         "exit": {"target": None, "choch": False, "time_min": None, "breakeven_at": None,
                  "close_buy": "rsi(close, 14) > 70", "close_sell": "rsi(close, 14) < 30"}}
G = {"mt5": FakeMT5, "_RL": RL, "_FX": None, "ROBOT_RULES": ROBOT, "say": LOG.append, "pb_trend_now": lambda: 1,
     "rates_utc": lambda tf, start, n: Rall[max(0, NOW["k"] - n):NOW["k"]],          # the n newest CLOSED candles
     "my_positions": lambda: list(POS), "robot_close_all": lambda why: (CLOSED.append((NOW["k"], why)), POS.clear())}
for n in consts:
    try:
        exec(compile(ast.Module([n], []), "c", "exec"), G)
    except Exception:
        pass
exec(compile(ast.Module(nodes, []), "bot", "exec"), G)

RL.Candles.KEEP = 20000                     # a smaller memory keeps the test quick
G["_FX"] = RL.Candles()
k0 = len(Rall) - 6000
NOW["k"] = k0
G["fx_seed"]()
FX = G["_FX"]
fails = 0


def check(name, ok):
    global fails
    if not ok:
        fails += 1; print("  FAIL", name)


check("seed size", len(FX.rows) == 20000 and FX.rows[-1][0] == int(Rall["time"][k0 - 1]))
eng = G["Struct"](); eng.quiet = True
for r in Rall[k0 - 3000:k0]:
    eng.step(int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
entries = []
skip = set(range(k0 + 2000, k0 + 2010))     # a 10-minute stall: the loop sees nothing, then catches up
for k in range(k0 + 1, k0 + 5000):
    NOW["k"] = k
    if k in skip:
        continue
    kb = Rall[k - 3:k]; bar = kb[-1]
    pt = eng.trend
    sig = eng.step(int(bar["time"]), float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
    G["fx_catch_up"](kb, sig[0] if sig else 0, sig is not None and eng.trend != pt, 1 if sig else None)
    if POS:
        G["robot_formula_exit"]({})
    fe = RL.formula_entry(ROBOT, FX)
    if fe:
        entries.append((k - 1, fe[0]))
        if not POS:
            POS.append(Pos(fe[0]))

# the memory = the candles, no hole, no double
T = np.array([r[0] for r in FX.rows])
seg = Rall["time"][k0 + 4999 - len(T):k0 + 4999]
check("memory equals the candles after the stall", len(T) == len(seg) and bool((T == seg).all()))
# entries = the bench's edges over the same candles (formulas that do not read the eyes)
B = X.Bars.from_rates(Rall[k0 - 20000:k0 + 4999])
off = k0 - 20000
bench = []
for d, f in ((-1, ROBOT["entry"]["sell"]), (1, ROBOT["entry"]["buy"])):
    t = X.truth(f, B); e = t & ~np.r_[False, t[:-1]]
    bench += [(int(i) + off, d) for i in np.flatnonzero(e) if k0 <= int(i) + off < k0 + 4999 and not (k0 + 1999 <= int(i) + off < k0 + 2009)]
bench.sort()
got = sorted(x for x in entries if not (k0 + 1999 <= x[0] < k0 + 2009))
check("entries on the bench's candles (%d bench, %d bot)" % (len(bench), len(got)), bench == got)
check("the close formula closed trades", len(CLOSED) > 0)
check("seed said its size", any("bougies en memoire" in x for x in LOG))
print("entries %d, closes %d" % (len(got), len(CLOSED)))
print("BOT FORMULA PATH: " + ("OK" if not fails else "%d FAILS" % fails))
sys.exit(1 if fails else 0)
