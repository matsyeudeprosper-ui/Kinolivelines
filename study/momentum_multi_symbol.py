"""Does "momentum into a level" exist outside BTC - and on cheaper instruments?

On BTCUSDm the condition (30-minute move >= 1x ATR(M15), price touching but not
through an H1/H4 level, enter WITH the move) measured 41.4% wins in both halves
of the sample against a 40% breakeven. Real information, but the error bar on
expectancy is twice the effect, so profitability is unproven.

Other symbols answer two things at once. They are INDEPENDENT samples rather than
more slices of the same 68 days, so agreement is genuine confirmation; and the
cheapest of them cost 1.4-2.8% of ATR against BTC's 3.3%, so if the same edge
exists there it starts from a smaller hole.

Symbols come from the 355-instrument cost census, taking the cheapest that a
small account can size at minimum lot. Each gets its own random control, since
win rates and spreads differ - comparing a symbol to BTC's baseline would be
meaningless.

Method is unchanged: M1 bars where ties are negligible, real spread read live from
the symbol, stop 0.4x ATR(M15), target 1.5x stop, 120-minute cap, timeouts settled
at the closing price, CONTINUE and REVERT arms so each symbol carries its control.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

HOLD, STOP_ATR, TMULT, LOOK = 120, 0.40, 1.50, 30
SYMBOLS = ["BTCUSDm", "JP225m", "DE30m", "US30m", "USTECm", "US500m", "XAUUSDm", "ETHUSDm"]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(sym, tf, want):
    for k in (want, 90000, 45000, 20000, 10000, 5000):
        r = mt5.copy_rates_from_pos(sym, tf, 0, k)
        if r is not None and len(r) > 2000:
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


def analyse(sym):
    if not mt5.symbol_select(sym, True):
        return None
    si = mt5.symbol_info(sym)
    tick = mt5.symbol_info_tick(sym)
    if si is None or tick is None or tick.ask <= 0:
        return None
    spread = tick.ask - tick.bid

    m1 = bars(sym, mt5.TIMEFRAME_M1, 99000)
    m15 = bars(sym, mt5.TIMEFRAME_M15, 50000)
    h1 = bars(sym, mt5.TIMEFRAME_H1, 45000)
    h4 = bars(sym, mt5.TIMEFRAME_H4, 20000)
    if any(x is None for x in (m1, m15, h1, h4)):
        return None

    pc = m15["close"].shift(1)
    m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                            (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
    a = m15[["time", "atr"]].dropna().copy()
    a["time"] = (a["time"] + pd.Timedelta(minutes=15)).astype("datetime64[ns]")
    d = pd.merge_asof(m1, a, on="time", direction="backward").dropna(subset=["atr"]).reset_index(drop=True)
    if len(d) < 20000:
        return None

    hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                       d["close"].to_numpy(float), d["atr"].to_numpy(float))
    n = len(cl)
    move = np.full(n, np.nan)
    move[LOOK:] = cl[LOOK:] - cl[:-LOOK]

    at_level = np.zeros(n, bool)
    broke = np.zeros(n, np.int8)
    for src, mins in ((h1, 60), (h4, 240)):
        j = np.searchsorted((src["time"] + pd.Timedelta(minutes=mins)).values,
                            d["time"].values, side="right") - 1
        H, L = src["high"].to_numpy(), src["low"].to_numpy()
        ok = np.where(j >= 1)[0]
        jj = j[ok]
        at_level[ok] |= ((lo[ok] <= H[jj]) & (hi[ok] >= H[jj])) | ((lo[ok] <= L[jj]) & (hi[ok] >= L[jj]))
        broke[ok[(cl[ok - 1] < H[jj]) & (cl[ok] > H[jj])]] = 1
        broke[ok[(cl[ok - 1] > L[jj]) & (cl[ok] < L[jj])]] = -1

    WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR

    def sim(entries, dirs):
        w = l = ti = to = 0
        s1 = s2 = 0.0
        for i, dirn in zip(entries, dirs):
            A = atr[i]
            if not np.isfinite(A) or A <= 0 or i + HOLD >= n:
                continue
            sd, td = STOP_ATR * A, STOP_ATR * A * TMULT
            win = slice(i + 1, i + 1 + HOLD)
            rmax = np.maximum.accumulate(hi[win]); rmin = np.minimum.accumulate(lo[win])
            mid, endp = cl[i], cl[i + HOLD]
            for s_ in ((1, -1) if dirn == 0 else (dirn,)):
                e = mid + s_ * spread / 2
                tp, sl = e + s_ * td, e - s_ * sd
                if s_ > 0:
                    ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                    hs = np.argmax(rmin <= sl) if rmin[-1] <= sl else 10 ** 6
                else:
                    ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                    hs = np.argmax(rmax >= sl) if rmax[-1] >= sl else 10 ** 6
                if ht == 10 ** 6 and hs == 10 ** 6:
                    to += 1; r = s_ * (endp - e) / A
                elif ht == hs:
                    ti += 1; r = (WIN_R + LOSS_R) / 2
                elif hs < ht:
                    l += 1; r = LOSS_R
                else:
                    w += 1; r = WIN_R
                s1 += r; s2 += r * r
        tot = max(w + l + ti + to, 1)
        m = s1 / tot
        return w / tot * 100, m, math.sqrt(max(s2 / tot - m * m, 0) / tot), tot

    base = np.arange(800, n - HOLD - 2)
    rw, rm, rse, rtot = sim(base, np.zeros(len(base), np.int8))
    cond = (np.abs(move) >= 1.0 * atr) & at_level & (broke == 0)
    e = base[cond[base]]
    if len(e) < 250:
        return dict(sym=sym, few=len(e), spread_pct=spread / np.nanmedian(atr) * 100)
    dirn = np.sign(move[e]).astype(np.int8)
    cw, cm, cse, ctot = sim(e, dirn)
    fw, fm, fse, _ = sim(e, -dirn)
    return dict(sym=sym, spread_pct=spread / np.nanmedian(atr) * 100,
                days=(d["time"].max() - d["time"].min()).days,
                rw=rw, rm=rm, rse=rse, cw=cw, cm=cm, cse=cse, ctot=ctot,
                fm=fm, fse=fse,
                two=2 * math.sqrt(cse ** 2 + rse ** 2))


print("%-9s %6s %5s %8s %8s %9s %11s %10s  %s"
      % ("symbol", "cost%", "days", "trades", "rand w%", "cont w%", "expectancy", "vs rand", "verdict"))
print("-" * 92)
rows = []
for s in SYMBOLS:
    try:
        r = analyse(s)
    except Exception as ex:
        print("%-9s failed: %s" % (s, type(ex).__name__)); continue
    if r is None:
        print("%-9s no usable data" % s); continue
    if "few" in r:
        print("%-9s only %d qualifying entries" % (s, r["few"])); continue
    beats = r["cm"] - r["rm"] > r["two"]
    above0 = r["cm"] - 2 * r["cse"] > 0
    v = ("beats random" if beats else "not vs random") + (" + ABOVE ZERO" if above0 else "")
    print("%-9s %5.1f%% %5d %8s %7.2f%% %8.2f%% %+11.4f %+10.4f  %s"
          % (r["sym"], r["spread_pct"], r["days"], f"{r['ctot']:,}",
             r["rw"], r["cw"], r["cm"], r["cm"] - r["rm"], v))
    rows.append(r)
mt5.shutdown()
print("-" * 92)

if rows:
    n_beat = sum(1 for r in rows if r["cm"] - r["rm"] > r["two"])
    print("\n%d of %d symbols show CONTINUE significantly better than their own random control."
          % (n_beat, len(rows)))
    print("""
Each symbol is an INDEPENDENT sample, so agreement across several is far stronger
evidence than any single split-half on BTC. If the effect appears only on BTC it
is probably curve-fitting; if it appears broadly it is a property of markets, and
the cheapest symbol showing it is where to trade it.""")
