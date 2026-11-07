"""Kino's trading lab - the test bench (2026-11-07, owner: "a real project, permanently, until he finds a strategy that works,
tested and everything - we need a positive P&L each month; he must prove it").

A strategy is a small Python file in his world with ONE function:
    def signals(bars):  ->  [(i, side, stop, target), ...]   or (i, side, stop, target, max_bars)
bars = dict of numpy arrays: time (UTC seconds), open, high, low, close, spread (price units), all 1-minute candles. i = the
index of the candle whose CLOSE triggers the trade (it may only use bars[:i+1]); side +1 buy / -1 sell; stop and target are
prices. Only numpy and math may be imported; no files, no network, no eval (checked before it runs).

What the bench does (the same for every idea, so ideas can be compared):
  - LOOKAHEAD check: the signals are computed on the whole data and on 3 cut versions; a signal before a cut that changes
    when the future is removed = the strategy peeks -> refused
  - fills: entry at the close of candle i (a buy pays the spread), one trade at a time, exit at the stop or the target on the
    next candles' high/low (both in one candle = the stop: the worse case), or at max_bars (default 1440) at the close
  - money at 0.01 lot (BTCUSD: 1 point of price = 0.01 $ at 0.01 lot)
  - RANDOM CONTROL: the same number of trades at random times, same sides, same stop/target distances, same max hold;
    N draws. The strategy must beat at least 95 % of them.
  - per month and per week results; max drawdown
Stages: quick (2 research months, 50 random), full (all research months, 100 random), final (the LOCKED months - never shown
to him - one try per frozen file; run only by the app).
    python engine.py <strategy.py> <stage> [--json out.json]
"""
import ast, importlib.util, json, math, os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD_DATA = r"C:\KinoWorld\lab\data\btc_m1_research.npz"
LOCKED = os.path.join(HERE, "locked_btc_m1.npz")
LOT_USD = 0.01                       # 0.01 lot of BTCUSD: 1.00 of price = 0.01 $
ALLOWED_IMPORTS = {"numpy", "math"}
BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr", "delattr",
                "input", "breakpoint", "exit", "quit", "memoryview", "help"}


def check_code(path):
    """the strategy may compute, nothing else -> None or why not"""
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
    except Exception as e:
        return "it does not parse: %s" % str(e)[:150]
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    return "import %s is not allowed (numpy and math only)" % a.name
        elif isinstance(n, ast.ImportFrom):
            if (n.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                return "from %s import is not allowed (numpy and math only)" % n.module
        elif isinstance(n, ast.Name) and n.id in BANNED_NAMES:
            return "%s() is not allowed in a strategy" % n.id
        elif isinstance(n, ast.Attribute) and (n.attr.startswith("__") or n.attr in ("load", "save", "savez", "fromfile",
                                                                                      "tofile", "loadtxt", "savetxt", "genfromtxt")):
            return "%s is not allowed in a strategy" % n.attr
    if not any(isinstance(n, ast.FunctionDef) and n.name == "signals" for n in tree.body):
        return "no function signals(bars)"
    return None


def load(path):
    R = np.load(path)
    return {k: R[k] for k in ("time", "open", "high", "low", "close", "spread")}


def months_of(bars, months):
    ym = np.array([time.strftime("%Y-%m", time.gmtime(t)) for t in bars["time"][::1440]])
    keep = np.zeros(len(bars["time"]), bool)
    tt = bars["time"]
    for m in months:
        y, mo = int(m[:4]), int(m[5:])
        a = time.mktime((y, mo, 1, 0, 0, 0, 0, 0, 0)) - time.timezone
        b = time.mktime((y + (mo == 12), mo % 12 + 1, 1, 0, 0, 0, 0, 0, 0)) - time.timezone
        keep |= (tt >= a) & (tt < b)
    return {k: v[keep] for k, v in bars.items()}


def strategy(path):
    spec = importlib.util.spec_from_file_location("kino_strategy", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.signals


def _norm(S, n):
    out = []
    for s in S or []:
        i, side, sl, tp = int(s[0]), int(s[1]), float(s[2]), float(s[3])
        mb = int(s[4]) if len(s) > 4 else 1440
        if 0 <= i < n - 1 and side in (1, -1) and math.isfinite(sl) and math.isfinite(tp):
            out.append((i, side, sl, tp, max(1, min(mb, 20000))))
    return sorted(out)


def lookahead(fn, bars):
    n = len(bars["time"])
    full = _norm(fn(bars), n)
    for frac in (0.35, 0.6, 0.85):
        k = int(n * frac)
        cut = {kk: v[:k] for kk, v in bars.items()}
        part = _norm(fn(cut), k)
        a = [s for s in full if s[0] < k - 1]
        b = [s for s in part if s[0] < k - 1]
        if a != b:
            return "LOOKAHEAD: the signals before candle %d change when the later candles are removed - the strategy uses the future" % k
    return None


def simulate(bars, sigs):
    """one trade at a time -> list of trades (entry_i, exit_i, side, pnl_price)"""
    H, L, C, SP = bars["high"], bars["low"], bars["close"], bars["spread"]
    n = len(C)
    T = []
    free_at = -1
    for i, side, sl, tp, mb in sigs:
        if i <= free_at:
            continue
        e = C[i] + (SP[i] if side == 1 else 0.0)         # a buy pays the spread at entry, a sell at its exit
        if (side == 1 and not (sl < e < tp)) or (side == -1 and not (tp < e < sl)):
            continue                                      # a stop or target on the wrong side: no trade
        end = min(n - 1, i + mb)
        hs, ls = H[i + 1:end + 1], L[i + 1:end + 1]
        if side == 1:
            hit_sl = np.nonzero(ls <= sl)[0]
            hit_tp = np.nonzero(hs >= tp)[0]
        else:
            hit_sl = np.nonzero(hs + SP[i + 1:end + 1] >= sl)[0]   # a sell closes at the ask
            hit_tp = np.nonzero(ls + SP[i + 1:end + 1] <= tp)[0]
        a = hit_sl[0] if len(hit_sl) else 10 ** 9
        b = hit_tp[0] if len(hit_tp) else 10 ** 9
        if a == b == 10 ** 9:
            j = end
            px = C[j] + (SP[j] if side == -1 else 0.0)
        elif a <= b:                                      # the same candle: the stop (the worse case)
            j, px = i + 1 + a, sl
        else:
            j, px = i + 1 + b, tp
        T.append((i, j, side, (px - e) * side))
        free_at = j
    return T


def stats(bars, T):
    tt = bars["time"]
    pnl = np.array([t[3] for t in T]) * LOT_USD
    out = {"trades": len(T), "net": round(float(pnl.sum()), 2)}
    if not len(T):
        return dict(out, win=0, pf=0, dd=0, months={}, weeks_pos=0, weeks=0, months_pos=0)
    eq = np.cumsum(pnl)
    out["win"] = round(float((pnl > 0).mean() * 100), 1)
    g, l = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    out["pf"] = round(float(g / l), 2) if l > 0 else 99.0
    out["dd"] = round(float((np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq])).max()), 2)
    M, Wk = {}, {}
    for t, p in zip(T, pnl):
        ts = time.gmtime(tt[t[1]])
        M[time.strftime("%Y-%m", ts)] = M.get(time.strftime("%Y-%m", ts), 0.0) + p
        Wk[time.strftime("%G-W%V", ts)] = Wk.get(time.strftime("%G-W%V", ts), 0.0) + p
    out["months"] = {k: round(v, 2) for k, v in sorted(M.items())}
    out["months_pos"] = sum(1 for v in M.values() if v > 0)
    out["weeks"] = len(Wk)
    out["weeks_pos"] = sum(1 for v in Wk.values() if v > 0)
    return out


def random_control(bars, T, sigs, draws, seed=7):
    """the same trades at random times -> list of nets"""
    rng = np.random.default_rng(seed)
    n = len(bars["close"])
    C = bars["close"]
    used = [s for s in sigs if any(s[0] == t[0] for t in T)]
    if not used:
        return []
    dists = [(s[1], abs(s[2] - C[s[0]]), abs(s[3] - C[s[0]]), s[4]) for s in used]
    nets = []
    for _ in range(draws):
        pos = np.sort(rng.choice(np.arange(60, n - 2), size=len(dists) * 3, replace=False))
        order = rng.permutation(len(dists))
        R = []
        k = 0
        for p in pos:
            if k >= len(dists):
                break
            side, ds, dt, mb = dists[order[k]]
            R.append((int(p), side, C[p] - side * ds, C[p] + side * dt, mb))
            k += 1
        nets.append(round(float(sum(t[3] for t in simulate(bars, R)) * LOT_USD), 2))
    return nets


def run(path, stage, data=None):
    why = check_code(path)
    if why:
        return {"ok": False, "stage": stage, "why": why}
    bars = load(data or (LOCKED if stage == "final" else WORLD_DATA))
    allm = sorted({time.strftime("%Y-%m", time.gmtime(t)) for t in bars["time"][::1440]})
    if stage == "quick":
        bars = months_of(bars, allm[-2:])
        draws = 50
    else:
        draws = 100
    fn = strategy(path)
    t0 = time.time()
    try:
        la = lookahead(fn, bars)
    except Exception as e:
        return {"ok": False, "stage": stage, "why": "signals() failed: %s" % str(e)[:200]}
    if la:
        return {"ok": False, "stage": stage, "why": la}
    sigs = _norm(fn(bars), len(bars["close"]))
    T = simulate(bars, sigs)
    S = stats(bars, T)
    nets = random_control(bars, T, sigs, draws) if T else []
    beat = sum(1 for x in nets if x >= S["net"])
    S.update(ok=True, stage=stage, months_tested=sorted(S.get("months", {}).keys()) or allm, signals=len(sigs), random_draws=len(nets),
             random_as_good=beat, random_median=round(float(np.median(nets)), 2) if nets else None,
             seconds=round(time.time() - t0, 1))
    wk = S["weeks_pos"] / S["weeks"] if S.get("weeks") else 0
    allpos = S["trades"] > 0 and S["months_pos"] == len(S["months"])
    if stage == "quick":
        S["pass"] = S["trades"] >= 20 and S["net"] > 0 and beat <= max(2, int(0.05 * len(nets)))
        S["gate"] = "quick: 20+ trades, positive, beats 95% of random trades"
    elif stage == "full":
        S["pass"] = S["trades"] >= 60 and allpos and wk >= 0.6 and beat <= 5
        S["gate"] = "full: 60+ trades, EVERY research month positive, 60%+ weeks positive, beats 95% of random"
    else:
        S["pass"] = S["trades"] >= 40 and allpos and wk >= 0.75 and beat <= 5
        S["gate"] = "final (locked months): EVERY month positive, 75%+ weeks positive, beats 95% of random"
    return S


if __name__ == "__main__":
    a = sys.argv[1:]
    r = run(a[0], a[1] if len(a) > 1 else "quick")
    if "--json" in a:
        json.dump(r, open(a[a.index("--json") + 1], "w"), indent=1)
    print(json.dumps(r))
