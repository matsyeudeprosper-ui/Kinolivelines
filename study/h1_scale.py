"""Does sizing trades to the HOURLY range instead of the 15-minute range help?

The spread is a fixed $10, so it is a bigger share of a small target than a large
one. Everything traded so far is sized to ATR(M15) (~120 pts), where $10 is about
8%. Sizing to ATR(H1) (~343 pts) drops that to ~3%.

This is NOT the hold-time test repeated. That one extended the CLOCK while leaving
the barriers at 0.4/0.6 ATR(M15) - the trade still finished in minutes, so the
extra time was irrelevant and the result was correctly flat. Here the BARRIERS
themselves grow. Holding longer does nothing; aiming further is the actual lever.

Still same-day: the longest variant caps at 8 hours, so nothing is held overnight.
That keeps it inside the intraday remit the user wants to exhaust before swing.

Two things must be reported together or the answer is misleading:
  EXPECTANCY per trade   bigger targets should suffer less spread drag
  DOLLAR RISK at 0.01 lots  a 1.0x ATR(H1) stop risks ~$3.43 on a $979 account,
                            which is 0.35% - inside rule 2's 0.5% cap, but a 1.5x
                            stop would breach it. A shape that cannot be sized is
                            not a shape.

Random entry throughout, long AND short, real spread, ties resolved neutrally,
timeouts settled at the closing price. Multi-symbol from the start, because three
leads tonight passed on BTC alone and died elsewhere.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYMBOLS = ["BTCUSDm", "XAUUSDm", "JP225m", "US30m"]
EQUITY = 979.0
TMULT = 1.50                      # target as a multiple of the stop, held constant

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(sym, tf, want):
    mt5.symbol_select(sym, True)
    for k in (want, 90000, 45000, 20000, 10000):
        r = mt5.copy_rates_from_pos(sym, tf, 0, k)
        if r is not None and len(r) > 2000:
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


def atr_of(df, n=14):
    pc = df["close"].shift(1)
    return pd.concat([df.high - df.low, (df.high - pc).abs(),
                      (df.low - pc).abs()], axis=1).max(axis=1).rolling(n).mean()


def analyse(sym):
    tick = mt5.symbol_info_tick(sym)
    if tick is None or tick.ask <= 0:
        return None
    spread = tick.ask - tick.bid
    m5 = bars(sym, mt5.TIMEFRAME_M5, 50000)
    m15 = bars(sym, mt5.TIMEFRAME_M15, 50000)
    h1 = bars(sym, mt5.TIMEFRAME_H1, 45000)
    if m5 is None or m15 is None or h1 is None:
        return None

    m15["atr"] = atr_of(m15)
    h1["atr"] = atr_of(h1)
    for src, mins in ((m15, 15), (h1, 60)):
        src["j"] = (src["time"] + pd.Timedelta(minutes=mins)).astype("datetime64[ns]")
    d = pd.merge_asof(m5, m15[["j", "atr"]].rename(columns={"j": "time", "atr": "atr15"}).dropna(),
                      on="time", direction="backward")
    d = pd.merge_asof(d, h1[["j", "atr"]].rename(columns={"j": "time", "atr": "atrh1"}).dropna(),
                      on="time", direction="backward").dropna(subset=["atr15", "atrh1"]).reset_index(drop=True)
    if len(d) < 15000:
        return None

    hi, lo, cl = d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float)
    a15, ah1 = d.atr15.to_numpy(float), d.atrh1.to_numpy(float)
    n = len(cl)

    def sim(atr_arr, stop_mult, hold_bars, step):
        w = l = ti = to = 0
        s1 = s2 = 0.0
        for i in range(300, n - hold_bars, step):
            A = atr_arr[i]
            if not np.isfinite(A) or A <= 0:
                continue
            sd, td = stop_mult * A, stop_mult * A * TMULT
            win = slice(i + 1, i + 1 + hold_bars)
            rmax = np.maximum.accumulate(hi[win]); rmin = np.minimum.accumulate(lo[win])
            mid, endp = cl[i], cl[i + hold_bars]
            for s_ in (1, -1):
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
                    ti += 1; r = (TMULT * stop_mult - stop_mult) / 2
                elif hs < ht:
                    l += 1; r = -stop_mult
                else:
                    w += 1; r = stop_mult * TMULT
                s1 += r; s2 += r * r
        tot = max(w + l + ti + to, 1)
        m = s1 / tot
        return w / tot * 100, m, math.sqrt(max(s2 / tot - m * m, 0) / tot), tot, to / tot * 100

    med15, medh1 = float(np.nanmedian(a15)), float(np.nanmedian(ah1))
    out = []
    # (label, atr array, stop multiple, hold in M5 bars, sampling step)
    for lbl, arr, sm, hold, med in (
            ("M15 x0.8 / 2h", a15, 0.8, 24, med15),
            ("H1  x0.5 / 4h", ah1, 0.5, 48, medh1),
            ("H1  x1.0 / 8h", ah1, 1.0, 96, medh1),
    ):
        wr, m, se, tot, tout = sim(arr, sm, hold, 7)
        stop_pts = sm * med
        risk = stop_pts * 0.01
        out.append(dict(lbl=lbl, wr=wr, m=m, se=se, tot=tot, tout=tout,
                        stop=stop_pts, risk=risk,
                        spread_pct=spread / stop_pts * 100,
                        pct_eq=risk / EQUITY * 100))
    return dict(sym=sym, spread=spread, out=out)


print("%-9s %-15s %8s %7s %8s %10s %9s %8s %7s"
      % ("symbol", "shape", "trades", "win%", "timeout", "expectancy", "stop pts", "$risk", "%eq"))
print("-" * 92)
for s in SYMBOLS:
    try:
        r = analyse(s)
    except Exception as ex:
        print("%-9s failed: %s" % (s, type(ex).__name__)); continue
    if r is None:
        print("%-9s no usable data" % s); continue
    base = r["out"][0]["m"]
    for i, o in enumerate(r["out"]):
        flag = ""
        if i > 0:
            two = 2 * math.sqrt(o["se"] ** 2 + r["out"][0]["se"] ** 2)
            if o["m"] - base > two:
                flag = "  BETTER"
            elif base - o["m"] > two:
                flag = "  worse"
        cap = " OVER 0.5% CAP" if o["pct_eq"] > 0.5 else ""
        print("%-9s %-15s %8s %6.1f%% %7.1f%% %+10.4f %9.0f %8.2f %6.2f%%%s%s"
              % (s if i == 0 else "", o["lbl"], f"{o['tot']:,}", o["wr"], o["tout"],
                 o["m"], o["stop"], o["risk"], o["pct_eq"], flag, cap))
    print()
mt5.shutdown()
print("-" * 92)
print("""
Expectancy is in units of the STOP, so the three shapes are directly comparable -
-0.03 means losing 3% of what you risk, whatever the absolute size.

If the H1 shapes are clearly less negative on MOST symbols, the spread drag really
is the constraint and trading bigger is the fix. If they are the same, then the
drag was never the binding problem and only the entry matters.""")
