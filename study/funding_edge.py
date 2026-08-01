"""FIRST TEST OF THE NEW QUESTION: is one side of the market forced or trapped?

Fourteen tests on price history came back null and the OHLC space is closed. This is
the first look at a variable that is NOT a transformation of price.

WHAT FUNDING IS. A perpetual swap never expires, so an hourly payment keeps it tied to
spot. Positive funding means longs pay shorts; negative means shorts pay longs. The
size of that payment is set by how badly one side wants its position. It is a direct
readout of crowding - the closest thing available to "who is trapped".

THE HYPOTHESES, each with its own mirror as a control:
  CROWD FADE     funding in the top of its recent range -> longs are crowded and
                 paying to stay -> take the other side. Mirror: join the crowd.
  SPIKE FADE     the largest 24h JUMP in funding, regardless of level - new money
                 piling in late. Mirror: follow the spike.
  DIVERGENCE     funding rising while price goes nowhere - longs are accumulating
                 without being rewarded, the textbook trapped-side setup.

NO-LOOKAHEAD RULE, and this is the trap that would fake a result here: "extreme
funding" is ranked against a TRAILING 30-day window only. Ranking against the whole
sample would let 2021's funding levels decide what counted as extreme in 2019, and
would manufacture an edge out of nothing.

Two horizons, because funding is a slow variable and the horizon work showed cost
drag nearly vanishes at day scale:
    8 hours   one funding cycle
    3 days    nine cycles

COSTS ARE THE EXNESS ONES WE ACTUALLY PAY, read live from the terminal - not
Deribit's tighter spread. A signal that only survives on a cheaper venue is not
something this account can trade.

Discipline unchanged: non-overlapping windows, three tie conventions, random control
per instrument and per horizon, sign consistency required over raw size.
"""
import os, math
import pandas as pd, numpy as np
import MetaTrader5 as mt5

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recorder", "data")
PAIRS = [("BTC-PERPETUAL", "BTCUSDm"), ("ETH-PERPETUAL", "ETHUSDm")]
TMULT, RANK_W, TOPQ = 1.5, 720, 0.20        # 720h trailing rank; top/bottom 20%
HORIZONS = [("8 hours", 8), ("3 days", 72)]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def live_spread(sym, fallback_px):
    """The spread this account really pays; falls back to a conservative guess."""
    if mt5.symbol_select(sym, True):
        t = mt5.symbol_info_tick(sym)
        if t and t.ask > 0 and t.ask > t.bid:
            return t.ask - t.bid, sym
    return fallback_px * 0.0003, sym + " (est)"


def load(fname):
    d = pd.read_csv(os.path.join(DATA, fname))
    pc = d["close"].shift(1)
    d["atr"] = pd.concat([d.high - d.low, (d.high - pc).abs(),
                          (d.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
    f = d["interest_8h"]
    # trailing percentile rank of funding - strictly backward looking
    d["rank"] = f.rolling(RANK_W).apply(lambda w: (w[:-1] < w.iloc[-1]).mean(), raw=False)
    d["jump"] = f - f.shift(24)
    d["jrank"] = d["jump"].rolling(RANK_W).apply(lambda w: (w[:-1] < w.iloc[-1]).mean(), raw=False)
    d["px_move"] = (d["close"] - d["close"].shift(24)).abs() / d["atr"]
    return d.dropna(subset=["atr", "rank", "jrank", "px_move"]).reset_index(drop=True)


def barriers(d, spread, hold):
    hi, lo, cl = d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float)
    atr = d.atr.to_numpy(float)
    rank, jrank, pxm = (d["rank"].to_numpy(float), d["jrank"].to_numpy(float),
                        d["px_move"].to_numpy(float))
    n, WIN, LOSS = len(cl), TMULT, -1.0
    recs = []
    for i in range(30, n - hold, hold):                     # NON-OVERLAPPING
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        sd, td = A, A * TMULT
        w = slice(i + 1, i + 1 + hold)
        rmax = np.maximum.accumulate(hi[w]); rmin = np.minimum.accumulate(lo[w])
        mid, endp = cl[i], cl[i + hold]
        rec = {"rank": rank[i], "jrank": jrank[i], "quiet": pxm[i] < 0.5}
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


def cell(recs, keep, direction, floor=80):
    v = [[], [], []]
    for r in recs:
        if not keep(r):
            continue
        dd = direction(r)
        if dd == 0: continue
        t = "L" if dd > 0 else "S"
        for k in range(3): v[k].append(r[t][k])
    if len(v[0]) < floor:
        return None
    a = np.array(v[0])
    return a.mean(), float(np.mean(v[1])), float(np.mean(v[2])), len(a), a.std() / math.sqrt(len(a))


HI, LO = 1 - TOPQ, TOPQ
TESTS = [
    # name, when it applies, which way to trade
    ("crowd FADE",  lambda r: r["rank"] >= HI or r["rank"] <= LO,
                    lambda r: -1 if r["rank"] >= HI else 1),
    ("crowd JOIN",  lambda r: r["rank"] >= HI or r["rank"] <= LO,
                    lambda r: 1 if r["rank"] >= HI else -1),
    ("spike FADE",  lambda r: r["jrank"] >= HI or r["jrank"] <= LO,
                    lambda r: -1 if r["jrank"] >= HI else 1),
    ("spike FOLLOW", lambda r: r["jrank"] >= HI or r["jrank"] <= LO,
                    lambda r: 1 if r["jrank"] >= HI else -1),
    ("diverg FADE", lambda r: r["quiet"] and (r["jrank"] >= HI or r["jrank"] <= LO),
                    lambda r: -1 if r["jrank"] >= HI else 1),
]

print("FUNDING RATE - is the crowded side forced?")
print("7.3 years hourly, trailing-%dh rank (no lookahead), Exness spreads, "
      "non-overlapping\n" % RANK_W)

summary = {h[0]: {t[0]: [] for t in TESTS} for h in HORIZONS}

for inst, mt5sym in PAIRS:
    fn = "hist_%s.csv" % inst.replace("-", "_")
    if not os.path.exists(os.path.join(DATA, fn)):
        print("%s: no cache\n" % inst); continue
    d = load(fn)
    spread, src = live_spread(mt5sym, float(d["close"].iloc[-1]))
    print("=" * 96)
    print("%s   %s rows, %s to %s   spread %.2f from %s"
          % (inst, f"{len(d):,}", d["utc"].iloc[0][:10], d["utc"].iloc[-1][:10], spread, src))
    for hname, hold in HORIZONS:
        recs = barriers(d, spread, hold)
        rl = cell(recs, lambda r: True, lambda r: 1)
        rs = cell(recs, lambda r: True, lambda r: -1)
        if not rl or not rs:
            continue
        rnd = (rl[0] + rs[0]) / 2
        rnd_se = math.sqrt(rl[4] ** 2 + rs[4] ** 2) / 2
        print("  %-8s %s windows | random %+.4f" % (hname, f"{len(recs):,}", rnd))
        for name, keep, dirn in TESTS:
            c = cell(recs, keep, dirn)
            if c is None:
                print("     %-14s too few" % name); continue
            diff = c[0] - rnd
            two = 2 * math.sqrt(c[4] ** 2 + rnd_se ** 2)
            ok = (c[1] - rnd > 0) == (c[2] - rnd > 0) == (diff > 0)
            summary[hname][name].append(diff if ok else 0.0)
            flag = "  <== BEATS RANDOM" if (diff > two and ok) else \
                   ("  (sign flips on ties)" if not ok else "")
            print("     %-14s n=%-6s %+.4f  +/-2SE %.4f%s"
                  % (name, f"{c[3]:,}", diff, two, flag))
    print()
mt5.shutdown()

print("=" * 96)
print("ACROSS BOTH INSTRUMENTS - mean difference from random\n")
print("%-9s %-15s %10s   %s" % ("horizon", "signal", "mean", "both agree?"))
print("-" * 60)
for hname, _ in HORIZONS:
    for name, _, _ in TESTS:
        v = summary[hname][name]
        if not v: continue
        m = float(np.mean(v))
        agree = sum(1 for x in v if x != 0 and (x > 0) == (m > 0))
        print("%-9s %-15s %+10.4f   %d of %d" % (hname, name, m, agree, len(v)))
    print("-" * 60)
print("""
FADE and JOIN are the same trades with opposite signs, so they must come out roughly
mirrored - if both look good, the filter is picking easy windows rather than a side,
and the result is about WHEN not WHICH WAY. Only a signal that beats random by more
than 2SE, keeps its sign under all three tie conventions, and does so on BTC and ETH
both, is worth taking to the next stage.""")
