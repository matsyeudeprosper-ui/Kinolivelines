"""Do the signals work in TRENDING markets and reverse in RANGING ones?

Twelve conditions were tested pooled across all market states and every one came
back near zero. That is exactly what a real behaviour looks like when it cancels
itself out:

    works in trends    +0.05
    reverses in ranges -0.05
    pooled              0.00   -> "nothing here"

Volatility regimes were tested and found nothing, but volatility is not the same
axis as trend-versus-range. A market can be quiet and trending, or violent and
going nowhere. This splits on DIRECTIONAL PERSISTENCE instead.

REGIME DEFINITION - deliberately crude and computed only from past bars:
  ADX-like: the ratio of net movement to total movement over the last 24 hours.
  A market that travels 500 points net while covering 600 total is trending; one
  that covers 600 to end up 50 from where it started is ranging. No parameters
  tuned - the split is at the sample median, so each regime holds half the data.

SIGNALS TESTED - the two that came closest before:
  momentum follow / fade   enter with or against a >=0.35x ATR(H1) 6-hour move
  break follow / fade      enter with or against a confirmed H1/H4 level break

DISCIPLINE (all five traps):
  non-overlapping windows, tie rate reported under three conventions, live spread,
  timeouts settled at the close, and every symbol carries its own control. A result
  must hold on SEVERAL symbols and keep its sign under all tie conventions.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYMBOLS = ["BTCUSDm", "JP225m", "XAUUSDm", "US30m", "DE30m", "USTECm"]
STOP_M, TMULT, HOLD, LOOK, REG = 1.0, 1.5, 8, 6, 24

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def load(sym):
    mt5.symbol_select(sym, True)
    tick = mt5.symbol_info_tick(sym)
    if tick is None or tick.ask <= 0:
        return None
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 20000)
    if r is None or len(r) < 5000:
        return None
    d = pd.DataFrame(r)
    d["time"] = pd.to_datetime(d["time"], unit="s")
    pc = d["close"].shift(1)
    d["atr"] = pd.concat([d.high - d.low, (d.high - pc).abs(),
                          (d.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
    # trendiness: net travel / total travel over REG hours, strictly backward
    step = d["close"].diff().abs()
    net = (d["close"] - d["close"].shift(REG)).abs()
    tot = step.rolling(REG).sum()
    d["trendy"] = (net / tot.replace(0, np.nan)).shift(1)
    h4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 8000)
    h4 = pd.DataFrame(h4) if h4 is not None else None
    if h4 is not None:
        h4["time"] = pd.to_datetime(h4["time"], unit="s")
    return d.dropna(subset=["atr", "trendy"]).reset_index(drop=True), tick.ask - tick.bid, h4


def build(sym):
    got = load(sym)
    if got is None:
        return None
    d, spread, h4 = got
    hi, lo, cl = d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float)
    atr, trendy = d.atr.to_numpy(float), d.trendy.to_numpy(float)
    n = len(cl)
    mv = np.full(n, np.nan); mv[LOOK:] = cl[LOOK:] - cl[:-LOOK]

    brk = np.zeros(n, np.int8)
    for src, per in ((d, 1), (h4, 4)):
        if src is None:
            continue
        H = src["high"].to_numpy(); L = src["low"].to_numpy()
        if per == 1:
            for i in range(2, n):
                if cl[i - 1] < H[i - 1] < cl[i]: brk[i] = 1
                elif cl[i - 1] > L[i - 1] > cl[i]: brk[i] = -1
        else:
            j = np.searchsorted((src["time"] + pd.Timedelta(hours=4)).values,
                                d["time"].values, side="right") - 1
            ok = np.where(j >= 1)[0]
            q = j[ok]
            brk[ok[(cl[ok - 1] < H[q]) & (cl[ok] > H[q])]] = 1
            brk[ok[(cl[ok - 1] > L[q]) & (cl[ok] < L[q])]] = -1

    WIN, LOSS = STOP_M * TMULT, -STOP_M
    recs = []
    for i in range(50, n - HOLD, HOLD):                  # NON-OVERLAPPING
        A = atr[i]
        if not np.isfinite(A) or A <= 0 or not np.isfinite(mv[i]) or not np.isfinite(trendy[i]):
            continue
        sd, td = STOP_M * A, STOP_M * A * TMULT
        w = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[w]); rmin = np.minimum.accumulate(lo[w])
        mid, endp = cl[i], cl[i + HOLD]
        rec = {"trendy": trendy[i], "mom": abs(mv[i]) >= 0.35 * A,
               "dir": np.sign(mv[i]), "brk": brk[i]}
        for sgn, tag in ((1, "L"), (-1, "S")):
            e = mid + sgn * spread / 2
            tp, s_ = e + sgn * td, e - sgn * sd
            if sgn > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                hs = np.argmax(rmin <= s_) if rmin[-1] <= s_ else 10 ** 6
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                hs = np.argmax(rmax >= s_) if rmax[-1] >= s_ else 10 ** 6
            if ht == 10 ** 6 and hs == 10 ** 6:
                v = sgn * (endp - e) / A; rec[tag] = (v, v, v)
            elif ht == hs:
                rec[tag] = ((WIN + LOSS) / 2, LOSS, WIN)
            elif hs < ht:
                rec[tag] = (LOSS, LOSS, LOSS)
            else:
                rec[tag] = (WIN, WIN, WIN)
        recs.append(rec)
    return recs


def cell(recs, keep, direction):
    v = [[], [], []]
    for r in recs:
        if not keep(r):
            continue
        dd = direction(r)
        if dd == 0:
            continue
        t = "L" if dd > 0 else "S"
        for k in range(3):
            v[k].append(r[t][k])
    if len(v[0]) < 120:
        return None
    a = np.array(v[0])
    return a.mean(), np.mean(v[1]), np.mean(v[2]), len(a), a.std() / math.sqrt(len(a))


print("REGIME SPLIT - does a signal work in TRENDS and reverse in RANGES?")
print("non-overlapping 8h windows, stop 1.0x ATR(H1), target 1.5x, live spread\n")

TESTS = [
    ("momentum follow", lambda r: r["mom"], lambda r: r["dir"]),
    ("momentum fade",   lambda r: r["mom"], lambda r: -r["dir"]),
    ("break follow",    lambda r: r["brk"] != 0, lambda r: r["brk"]),
    ("break fade",      lambda r: r["brk"] != 0, lambda r: -r["brk"]),
]
tally = {t[0]: {"trend": [], "range": []} for t in TESTS}

for sym in SYMBOLS:
    recs = build(sym)
    if not recs:
        print("%-9s no data" % sym); continue
    med = float(np.median([r["trendy"] for r in recs]))
    print("%-9s %s windows, trend/range split at trendiness %.3f" % (sym, f"{len(recs):,}", med))
    for label, regsel in (("TREND", lambda r: r["trendy"] >= med),
                          ("RANGE", lambda r: r["trendy"] < med)):
        base = cell(recs, regsel, lambda r: 1)
        base_s = cell(recs, regsel, lambda r: -1)
        rnd = (base[0] + base_s[0]) / 2 if base and base_s else None
        line = "   %-6s random %+.4f |" % (label, rnd if rnd is not None else float("nan"))
        for name, keep, dirn in TESTS:
            c = cell(recs, lambda r: regsel(r) and keep(r), dirn)
            if c is None or rnd is None:
                line += " %-16s" % (name + " -"); continue
            diff = c[0] - rnd
            signs_agree = (c[1] - rnd > 0) == (c[2] - rnd > 0) == (diff > 0)
            tally[name]["trend" if label == "TREND" else "range"].append(diff if signs_agree else 0.0)
            line += " %s %+.4f " % (name.split()[0][:4] + name.split()[1][:3], diff)
        print(line)
    print()
mt5.shutdown()

print("=" * 78)
print("SIGNAL BEHAVIOUR BY REGIME - mean difference from that regime's own random\n")
print("%-18s %12s %12s %10s  %s" % ("signal", "TREND", "RANGE", "flips?", "symbols agreeing"))
print("-" * 78)
for name in tally:
    t, r = tally[name]["trend"], tally[name]["range"]
    if not t or not r:
        continue
    mt_, mr = float(np.mean(t)), float(np.mean(r))
    flips = "YES" if (mt_ > 0) != (mr > 0) else "no"
    agree_t = sum(1 for x in t if (x > 0) == (mt_ > 0) and x != 0)
    print("%-18s %12.4f %12.4f %10s  %d/%d in trend" % (name, mt_, mr, flips, agree_t, len(t)))
print("-" * 78)
print("""
A signal that FLIPS sign between regimes and does so on most symbols is the
behaviour the pooled tests would have averaged to zero. A signal with the same
sign in both regimes was simply never there - splitting cannot rescue it.""")
