"""Session and calendar effects, done properly. Last item on the list.

An earlier pass looked at 12 hour-buckets on BTC, used the biased tie scoring, had
no correction for testing twelve things at once, and compared everything to a
fixed breakeven that assumed a constant timeout rate. Four buckets "cleared" it
and none of that survived inspection.

This redo fixes all of it:
  * M1 bars where ties are negligible
  * each symbol against its OWN random control
  * cross-instrument replication built in from the start, not bolted on after
  * an explicit note of how many buckets are being tested, so the reader can
    judge how much apparent significance to discount

Three calendar cuts:
  HOUR      six 4-hour blocks, which maps onto Asia / London / New York
  WEEKDAY   Monday through Sunday (crypto trades all week, indices do not)
  WEEKEND   crypto only - is Saturday/Sunday different from the working week?

Entries are long AND short from every qualifying bar, so no direction is being
supplied; a calendar effect would show as a shift in the base rate of which
barrier gets hit first, not as a directional call.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYMBOLS = ["BTCUSDm", "XAUUSDm", "JP225m", "US30m"]
HOLD, STOP_ATR, TMULT = 120, 0.40, 1.50
WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(sym, tf, want):
    mt5.symbol_select(sym, True)
    for k in (want, 90000, 45000, 20000, 10000):
        r = mt5.copy_rates_from_pos(sym, tf, 0, k)
        if r is not None and len(r) > 2000:
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


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
    hour = d["time"].dt.hour.to_numpy()
    dow = d["time"].dt.dayofweek.to_numpy()
    n = len(cl)

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
    rm, rse, _ = sim(base)
    res = {"random": rm}
    for lbl, mask in [("H%02d-%02d" % (h, h + 4), (hour >= h) & (hour < h + 4)) for h in range(0, 24, 4)]:
        e = base[mask[base]]
        if len(e) < 2000:
            continue
        m_, se_, tot_ = sim(e)
        res[lbl] = (m_ - rm, 2 * math.sqrt(se_ ** 2 + rse ** 2), tot_)
    for i, lbl in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        e = base[(dow[base] == i)]
        if len(e) < 2000:
            continue
        m_, se_, tot_ = sim(e)
        res[lbl] = (m_ - rm, 2 * math.sqrt(se_ ** 2 + rse ** 2), tot_)
    return res


all_res = {}
for s in SYMBOLS:
    try:
        r = analyse(s)
    except Exception as ex:
        print("%-9s failed: %s" % (s, type(ex).__name__)); continue
    if r:
        all_res[s] = r
        print("%-9s random control %+.4f" % (s, r["random"]))
mt5.shutdown()

buckets = [k for k in all_res.get("BTCUSDm", {}) if k != "random"]
print("\nvs each symbol's OWN random control. %d buckets x %d symbols = %d tests -"
      % (len(buckets), len(all_res), len(buckets) * len(all_res)))
print("expect roughly %.1f to clear 2 SE by chance alone.\n" % (len(buckets) * len(all_res) * 0.05))

hdr = "%-10s" % "bucket" + "".join("%14s" % s for s in all_res)
print(hdr); print("-" * len(hdr))
consistent = []
for b in buckets:
    row = "%-10s" % b
    signs = []
    for s in all_res:
        v = all_res[s].get(b)
        if v is None:
            row += "%14s" % "-"; signs.append(0); continue
        diff, two, tot = v
        star = "*" if abs(diff) > two else " "
        row += "%13.4f%s" % (diff, star)
        signs.append((1 if diff > 0 else -1) if abs(diff) > two else 0)
    print(row)
    if signs.count(1) >= 3 or signs.count(-1) >= 3:
        consistent.append(b)
print("-" * len(hdr))
print("* = beyond 2 SE of that symbol's own random control")
print("\nbuckets significant in the SAME direction on 3+ symbols: %s"
      % (", ".join(consistent) if consistent else "NONE"))
print("""
A calendar effect that is real should appear on several instruments at the same
clock time, since sessions are a property of when people trade, not of one symbol.
Scattered single-symbol hits at the rate chance predicts are not findings.""")
