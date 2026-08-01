"""Is the missing edge a HORIZON problem?

Everything so far was measured at one time scale: hourly-sized barriers held for
about eight hours. A real behaviour can be exactly zero there and alive somewhere
else - momentum is famously a multi-week effect in academic work and pure noise
intraday. So before declaring price history exhausted, run the same candidates at
four scales spanning three orders of magnitude in time.

THE RULE THAT MAKES THIS A FAIR TEST: barriers scale WITH the horizon. A 2-week
hold with hourly-sized stops is not a long-horizon test - it is an 8-hour test that
happens to wait longer, and every stop gets hit in the first afternoon. So each
horizon uses its own bar size, its own ATR, and a hold matched to it:

    minutes   M5 bars   stop 1.0x ATR(M5)    hold 12 bars =  1 hour
    hours     H1 bars   stop 1.0x ATR(H1)    hold  8 bars =  8 hours
    days      H4 bars   stop 1.0x ATR(H4)    hold 18 bars =  3 days
    weeks     D1 bars   stop 1.0x ATR(D1)    hold 10 bars =  2 weeks

CANDIDATES - the two that came closest across twelve tests, each with its mirror
as a built-in control:
    momentum follow / fade   price moved >=0.35x ATR over the previous 6 bars
    break follow / fade      close crossed the prior bar's high or low

Also reported per horizon: the RANDOM baseline. That number is the cost of doing
business at that scale, and it is interesting on its own - if the drag shrinks as
horizons lengthen, a weak signal that is invisible intraday could pay weekly.

Discipline unchanged: non-overlapping windows, live spread, timeouts settled at
the close, three tie conventions, several symbols, sign consistency over size.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYMBOLS = ["BTCUSDm", "JP225m", "XAUUSDm", "US30m", "DE30m", "USTECm"]
TMULT, LOOK = 1.5, 6

HORIZONS = [
    ("minutes", mt5.TIMEFRAME_M5,  12, 50000, "1 hour"),
    ("hours",   mt5.TIMEFRAME_H1,   8, 20000, "8 hours"),
    ("days",    mt5.TIMEFRAME_H4,  18, 20000, "3 days"),
    ("weeks",   mt5.TIMEFRAME_D1,  10,  5000, "2 weeks"),
]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def build(sym, tf, hold, want):
    mt5.symbol_select(sym, True)
    tick = mt5.symbol_info_tick(sym)
    if tick is None or tick.ask <= 0:
        return None, None
    r = mt5.copy_rates_from_pos(sym, tf, 0, want)
    if r is None or len(r) < 400:
        return None, None
    spread = tick.ask - tick.bid
    d = pd.DataFrame(r)
    d["time"] = pd.to_datetime(d["time"], unit="s")
    pc = d["close"].shift(1)
    d["atr"] = pd.concat([d.high - d.low, (d.high - pc).abs(),
                          (d.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
    d = d.dropna(subset=["atr"]).reset_index(drop=True)

    hi, lo, cl = d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float)
    atr = d.atr.to_numpy(float)
    n = len(cl)
    if n < hold * 40:
        return None, None
    mv = np.full(n, np.nan); mv[LOOK:] = cl[LOOK:] - cl[:-LOOK]
    brk = np.zeros(n, np.int8)
    for i in range(2, n):
        if cl[i - 1] < hi[i - 1] < cl[i]: brk[i] = 1
        elif cl[i - 1] > lo[i - 1] > cl[i]: brk[i] = -1

    WIN, LOSS = TMULT, -1.0
    recs = []
    for i in range(30, n - hold, hold):                    # NON-OVERLAPPING
        A = atr[i]
        if not np.isfinite(A) or A <= 0 or not np.isfinite(mv[i]):
            continue
        sd, td = A, A * TMULT
        w = slice(i + 1, i + 1 + hold)
        rmax = np.maximum.accumulate(hi[w]); rmin = np.minimum.accumulate(lo[w])
        mid, endp = cl[i], cl[i + hold]
        rec = {"mom": abs(mv[i]) >= 0.35 * A, "dir": np.sign(mv[i]), "brk": brk[i]}
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
    span = (d.time.max() - d.time.min()).days / 365.25
    return recs, span


def cell(recs, keep, direction, floor=100):
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


TESTS = [
    ("mom follow", lambda r: r["mom"], lambda r: r["dir"]),
    ("mom fade",   lambda r: r["mom"], lambda r: -r["dir"]),
    ("brk follow", lambda r: r["brk"] != 0, lambda r: r["brk"]),
    ("brk fade",   lambda r: r["brk"] != 0, lambda r: -r["brk"]),
]

print("HORIZON TEST - the same candidates at four time scales, barriers scaled to match")
print("stop 1.0x ATR(of that timeframe), target 1.5x, live spread, non-overlapping\n")

grand = {h[0]: {t[0]: [] for t in TESTS} for h in HORIZONS}
base = {h[0]: [] for h in HORIZONS}

for hname, tf, hold, want, human in HORIZONS:
    print("=" * 92)
    print("HORIZON: %s   (hold %s, %d bars)" % (hname.upper(), human, hold))
    print("%-9s %9s %7s %10s   %s" % ("symbol", "windows", "years", "random", "signal minus random"))
    print("-" * 92)
    for sym in SYMBOLS:
        recs, span = build(sym, tf, hold, want)
        if not recs:
            print("%-9s %9s" % (sym, "no data")); continue
        rnd = cell(recs, lambda r: True, lambda r: 1)
        rnd_s = cell(recs, lambda r: True, lambda r: -1)
        if rnd is None or rnd_s is None:
            print("%-9s %9s" % (sym, "too few")); continue
        rmean = (rnd[0] + rnd_s[0]) / 2
        base[hname].append(rmean)
        line = "%-9s %9s %7.1f %+10.4f  " % (sym, f"{len(recs):,}", span, rmean)
        for name, keep, dirn in TESTS:
            c = cell(recs, keep, dirn)
            if c is None:
                line += " %s -" % name; continue
            diff = c[0] - rmean
            ok = (c[1] - rnd[1] > 0) == (c[2] - rnd[2] > 0) == (diff > 0)
            grand[hname][name].append(diff if ok else 0.0)
            line += " %s %+.4f%s " % (name, diff, "" if ok else "?")
        print(line)
    print()
mt5.shutdown()

print("=" * 92)
print("SUMMARY - mean across symbols, by horizon  ('?' above = sign flipped under tie convention)\n")
print("%-9s %12s   %s" % ("horizon", "RANDOM", "  ".join("%-14s" % t[0] for t in TESTS)))
print("-" * 92)
for hname, _, _, _, human in HORIZONS:
    if not base[hname]: continue
    row = "%-9s %12.4f   " % (hname, float(np.mean(base[hname])))
    for name, _, _ in TESTS:
        v = grand[hname][name]
        if not v:
            row += "%-16s" % "-"; continue
        m = float(np.mean(v))
        agree = sum(1 for x in v if x != 0 and (x > 0) == (m > 0))
        row += "%+.4f (%d/%d)  " % (m, agree, len(v))
    print(row)
print("-" * 92)
print("""
Read the RANDOM column first: that is the cost floor at each scale, and it should
shrink as horizons lengthen because the spread is paid once regardless of how long
the trade lives. A signal only counts if it beats its own horizon's random by a
clear margin AND does so on most symbols with the same sign.

If every horizon is null, the holding period was never the problem - the feature
was. Price history would then be exhausted for this instrument set.""")
