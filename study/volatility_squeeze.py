"""Does a volatility contraction predict the expansion that follows it?

Volatility was tested earlier as a FILTER - "is now a good time to trade" - and
came back empty. This is a different question: a squeeze as a TRIGGER. The classic
claim is that quiet ranges resolve into moves, so entering as the range breaks
catches the expansion.

Three definitions of a squeeze, each strictly backward-looking:
  NR          the last N bars have the narrowest combined range of the last 120
  ATR RATIO   short-window ATR has fallen below X of the long-window ATR
  BB SQUEEZE  rolling standard deviation at a 120-bar low

Two arms per definition, because a squeeze itself has no direction:
  BREAKOUT    enter when price leaves the squeeze range, in that direction
  FADE        the mirror, entering against the break

Cross-instrument replication is applied from the start rather than at the end.
Three straight leads tonight passed a split-half on BTC and then failed on other
symbols, so a BTC-only result is not reported as anything. Each symbol carries its
own random control since win rates and spreads differ.

M1 bars where ties are negligible, live spread per symbol, stop 0.4x ATR(M15),
target 1.5x stop, 120-minute cap, timeouts settled at the closing price.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYMBOLS = ["BTCUSDm", "XAUUSDm", "JP225m", "DE30m", "US30m"]
HOLD, STOP_ATR, TMULT = 120, 0.40, 1.50

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(sym, tf, want):
    mt5.symbol_select(sym, True)
    for k in (want, 90000, 45000, 20000, 10000):
        r = mt5.copy_rates_from_pos(sym, tf, 0, k)
        if r is not None and len(r) > 2000:
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR


def analyse(sym):
    tick = mt5.symbol_info_tick(sym)
    if tick is None or tick.ask <= 0:
        return None
    spread = tick.ask - tick.bid
    m1 = bars(sym, mt5.TIMEFRAME_M1, 99000)
    m15 = bars(sym, mt5.TIMEFRAME_M15, 50000)
    if m1 is None or m15 is None:
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

    def sim(entries, dirs):
        w = l = ti = to = 0
        s1 = s2 = 0.0
        for i, dirn in zip(entries, dirs):
            A = atr[i]
            if not np.isfinite(A) or A <= 0 or i + HOLD >= n or dirn == 0:
                continue
            sd, td = STOP_ATR * A, STOP_ATR * A * TMULT
            win = slice(i + 1, i + 1 + HOLD)
            rmax = np.maximum.accumulate(hi[win]); rmin = np.minimum.accumulate(lo[win])
            mid, endp = cl[i], cl[i + HOLD]
            s_ = int(dirn)
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
        return m, math.sqrt(max(s2 / tot - m * m, 0) / tot), tot

    base = np.arange(800, n - HOLD - 2)
    rm, rse, _ = sim(np.tile(base, 2),
                     np.r_[np.ones(len(base), np.int8), -np.ones(len(base), np.int8)])

    hs30 = pd.Series(hi).rolling(30).max().to_numpy()
    ls30 = pd.Series(lo).rolling(30).min().to_numpy()
    rng30 = hs30 - ls30
    rng_lo = pd.Series(rng30).rolling(120).min().shift(1).to_numpy()
    atr_s = pd.Series(np.abs(np.r_[0, np.diff(cl)])).rolling(30).mean().to_numpy()
    atr_l = pd.Series(np.abs(np.r_[0, np.diff(cl)])).rolling(240).mean().shift(1).to_numpy()
    sd_s = pd.Series(cl).rolling(30).std().to_numpy()
    sd_lo = pd.Series(sd_s).rolling(120).min().shift(1).to_numpy()

    defs = {
        "NR30": rng30 <= rng_lo * 1.02,
        "ATRratio": (atr_s <= 0.6 * atr_l) & np.isfinite(atr_l),
        "BBsqueeze": (sd_s <= sd_lo * 1.02) & np.isfinite(sd_lo),
    }
    # breakout direction: which side of the squeeze range price leaves
    out = {}
    for name, sq in defs.items():
        prev = np.r_[False, sq[:-1]]
        brk_up = prev & (cl > np.r_[np.nan, hs30[:-1]])
        brk_dn = prev & (cl < np.r_[np.nan, ls30[:-1]])
        sig = np.zeros(n, np.int8)
        sig[brk_up] = 1
        sig[brk_dn] = -1
        e = base[sig[base] != 0]
        if len(e) < 250:
            out[name] = None
            continue
        dirn = sig[e]
        bm, bse, btot = sim(e, dirn)
        fm, fse, _ = sim(e, -dirn)
        two = 2 * math.sqrt(bse ** 2 + rse ** 2)
        out[name] = (btot, bm - rm, fm - rm, two)
    return dict(sym=sym, rm=rm, out=out)


print("%-9s %-11s %8s %12s %12s  %s"
      % ("symbol", "squeeze", "trades", "BREAKOUT", "FADE", "verdict"))
print("-" * 78)
tally = {}
for s in SYMBOLS:
    try:
        r = analyse(s)
    except Exception as ex:
        print("%-9s failed: %s" % (s, type(ex).__name__)); continue
    if r is None:
        print("%-9s no usable data" % s); continue
    first = True
    for name, v in r["out"].items():
        if v is None:
            print("%-9s %-11s too few" % (s if first else "", name)); first = False; continue
        tot, db, df, two = v
        verdict = ""
        if abs(db) > two:
            verdict = "BREAKOUT %s" % ("better" if db > 0 else "worse")
            tally.setdefault(name, []).append(1 if db > 0 else -1)
        else:
            tally.setdefault(name, []).append(0)
        print("%-9s %-11s %8s %+12.4f %+12.4f  %s"
              % (s if first else "", name, f"{tot:,}", db, df, verdict))
        first = False
mt5.shutdown()
print("-" * 78)
print("\nvs each symbol's OWN random control. Consistency across symbols is the test:")
for name, v in tally.items():
    pos = sum(1 for x in v if x > 0); neg = sum(1 for x in v if x < 0)
    print("  %-11s %d symbols better, %d worse, %d nothing (of %d)"
          % (name, pos, neg, len(v) - pos - neg, len(v)))
print("""
Three leads tonight passed on BTC alone and died on other symbols. A squeeze
result matters only if the same sign appears on most symbols tested.""")
