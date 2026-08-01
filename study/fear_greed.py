"""Does crowd sentiment change how intraday trades behave?

The Fear & Greed index is the only deep free dataset reachable from this machine -
3,099 daily readings back to 2018. It is built from volatility, volume, social
media and search trends, so unlike every test so far it is NOT a rearrangement of
BTC's own price.

It updates ONCE PER DAY, so the honest sample size is the number of overlapping
DAYS (~520), not the ~50,000 M15 bars. Treating every bar as independent is the
exact trap that made the weekly-level test meaningless earlier - the same handful
of distinct values repeated thousands of times. Both counts are printed so the
difference is visible.

Tested as a REGIME FILTER, not a direction call: entries are long AND short from
every qualifying bar, so a real effect shows as a shift in which barrier gets hit
first, not as a view on where price goes.

Buckets follow the index's own classification boundaries rather than quantiles of
the sample, so the result is not tuned to this period.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math, json, urllib.request
from datetime import datetime, timezone

SYM, HOLD, STOP_ATR, TMULT = "BTCUSDm", 8, 0.80, 1.50      # M15 grain, live geometry
WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR

req = urllib.request.Request("https://api.alternative.me/fng/?limit=0",
                             headers={"User-Agent": "Mozilla/5.0 (research)"})
fng_raw = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())["data"]
fng = pd.DataFrame([{"date": datetime.fromtimestamp(int(r["timestamp"]), timezone.utc).date(),
                     "fng": int(r["value"])} for r in fng_raw])
print("Fear & Greed: %s daily readings, %s .. %s" % (f"{len(fng):,}", fng.date.min(), fng.date.max()))

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
tick = mt5.symbol_info_tick(SYM)
SPREAD = tick.ask - tick.bid


def bars(tf, want):
    for k in (want, 45000, 20000, 10000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r) > 2000:
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m15 = bars(mt5.TIMEFRAME_M15, 50000)
mt5.shutdown()

pc = m15["close"].shift(1)
m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                        (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
d = m15.dropna(subset=["atr"]).reset_index(drop=True)
# yesterday's reading, so nothing is known that would not have been known live
fng["date"] = pd.to_datetime(fng["date"])
fng = fng.sort_values("date")
fng["prev"] = fng["fng"].shift(1)
d["date"] = d["time"].dt.normalize()
d = d.merge(fng[["date", "prev"]], on="date", how="left").dropna(subset=["prev"]).reset_index(drop=True)

hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                   d["close"].to_numpy(float), d["atr"].to_numpy(float))
val = d["prev"].to_numpy(float)
n = len(cl)
ndays = d["date"].nunique()
print("overlap: %s M15 bars across %d DISTINCT DAYS" % (f"{n:,}", ndays))
print("the honest sample size is %d, not %s - the reading is constant within a day\n"
      % (ndays, f"{n:,}"))


def sim(entries):
    w = l = ti = to = 0
    s1 = s2 = 0.0
    for i in entries:
        A = atr[i]
        if not np.isfinite(A) or A <= 0 or i + HOLD >= n:
            continue
        sd, td = STOP_ATR * A, STOP_ATR * A * TMULT
        win = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[win]); rmin = np.minimum.accumulate(lo[win])
        mid, endp = cl[i], cl[i + HOLD]
        for s_ in (1, -1):
            e = mid + s_ * SPREAD / 2
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


base = np.arange(300, n - HOLD - 2)
rw, rm, rse, rtot = sim(base)
print("%-18s %6s %9s %8s %11s %11s  %s"
      % ("regime", "days", "trades", "win%", "expectancy", "vs random", "verdict"))
print("-" * 82)
print("%-18s %6d %9s %7.2f%% %+11.4f" % ("ALL (random)", ndays, f"{rtot:,}", rw, rm))

BUCKETS = [("Extreme Fear 0-24", 0, 25), ("Fear 25-44", 25, 45), ("Neutral 45-54", 45, 55),
           ("Greed 55-74", 55, 75), ("Extreme Greed 75+", 75, 101)]
for name, a_, b_ in BUCKETS:
    mask = (val >= a_) & (val < b_)
    e = base[mask[base]]
    dd = d.loc[e, "date"].nunique() if len(e) else 0
    if dd < 30:
        print("%-18s %6d only %d days - too few to judge" % (name, dd, dd)); continue
    w_, m_, se_, tot_ = sim(e)
    # error bar inflated by the day-clustering: effective n is days, not bars
    eff = math.sqrt(len(e) / max(dd, 1))
    two = 2 * math.sqrt((se_ * eff) ** 2 + rse ** 2)
    diff = m_ - rm
    print("%-18s %6d %9s %7.2f%% %+11.4f %+11.4f  %s"
          % (name, dd, f"{tot_:,}", w_, m_, diff,
             ("REAL %s" % ("better" if diff > 0 else "worse")) if abs(diff) > two else ""))
print("-" * 82)
print("""
Error bars here are widened to account for day-clustering: bars within one day
share the same reading, so they are not independent observations. Without that
correction every bucket would look significant, which is how the weekly-level
test fooled us earlier.""")
