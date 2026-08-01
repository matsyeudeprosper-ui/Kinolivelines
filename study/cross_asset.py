"""Does information from OTHER instruments predict BTC?

Everything tested so far has been BTC's own price rearranged - levels, breaks,
momentum, volume, volatility. All of it is the same information viewed different
ways, which is probably why it keeps coming back empty. Cross-asset is the first
test using data BTC's own chart does not contain.

Two mechanisms, opposite in character, both classic:

  DIVERGENCE   BTC and a correlated partner normally move together. When the
               partner moves and BTC does not, does BTC catch up? Entry is in
               the direction of the PARTNER's move.
  LEAD-LAG     the partner's recent return simply predicts BTC's next move,
               independent of any correlation story.

Partners: ETH (closest cousin), gold, the US indices, and the dollar index proxy
if present. Each is tested separately - a partner that works only in combination
with others is a curve-fit.

Every partner gets both arms (FOLLOW the partner, FADE it) and BTC's own random
control. And the lesson from the last test is applied: a result on one partner
proves little; what matters is whether SEVERAL agree.

M1 bars, real spread, stop 0.4x ATR(M15), target 1.5x stop, 120-minute cap,
timeouts settled at the closing price, ties negligible at this grain.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

TARGET = "BTCUSDm"
PARTNERS = ["ETHUSDm", "XAUUSDm", "USTECm", "US500m", "US30m", "JP225m", "DE30m"]
HOLD, STOP_ATR, TMULT, LOOK = 120, 0.40, 1.50, 30

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(sym, tf, want):
    mt5.symbol_select(sym, True)
    for k in (want, 90000, 45000, 20000, 10000):
        r = mt5.copy_rates_from_pos(sym, tf, 0, k)
        if r is not None and len(r) > 2000:
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m1 = bars(TARGET, mt5.TIMEFRAME_M1, 99000)
m15 = bars(TARGET, mt5.TIMEFRAME_M15, 50000)
tick = mt5.symbol_info_tick(TARGET)
SPREAD = tick.ask - tick.bid

pc = m15["close"].shift(1)
m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                        (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
a = m15[["time", "atr"]].dropna().copy()
a["time"] = (a["time"] + pd.Timedelta(minutes=15)).astype("datetime64[ns]")
d = pd.merge_asof(m1, a, on="time", direction="backward").dropna(subset=["atr"]).reset_index(drop=True)

hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                   d["close"].to_numpy(float), d["atr"].to_numpy(float))
n = len(cl)
btc_ret = np.full(n, np.nan)
btc_ret[LOOK:] = (cl[LOOK:] - cl[:-LOOK]) / cl[:-LOOK]
print("%s: %s M1 bars, %d days, spread %.2f\n" % (TARGET, f"{n:,}",
      (d["time"].max() - d["time"].min()).days, SPREAD))

WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR


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


base = np.arange(800, n - HOLD - 2)
both = np.tile(base, 2)
dirs_both = np.r_[np.ones(len(base), np.int8), -np.ones(len(base), np.int8)]
rw, rm, rse, rtot = sim(both, dirs_both)
print("BTC random control: %s trades, %.2f%% wins, expectancy %+.4f\n" % (f"{rtot:,}", rw, rm))

print("%-9s %-10s %8s %7s %11s %10s  %s"
      % ("partner", "arm", "trades", "win%", "expectancy", "vs random", "verdict"))
print("-" * 80)

hits = 0
tested = 0
for p in PARTNERS:
    pm1 = bars(p, mt5.TIMEFRAME_M1, 99000)
    if pm1 is None:
        print("%-9s no data" % p); continue
    pj = pd.merge_asof(d[["time"]], pm1[["time", "close"]].rename(columns={"close": "p"}),
                       on="time", direction="backward", tolerance=pd.Timedelta(minutes=5))
    pcl = pj["p"].to_numpy(float)
    pret = np.full(n, np.nan)
    pret[LOOK:] = (pcl[LOOK:] - pcl[:-LOOK]) / pcl[:-LOOK]
    ok = np.isfinite(pret) & np.isfinite(btc_ret)
    if ok.sum() < 20000:
        print("%-9s too little overlap (%s bars)" % (p, f"{int(ok.sum()):,}")); continue
    corr = np.corrcoef(pret[ok], btc_ret[ok])[0, 1]

    # DIVERGENCE: partner moved a lot, BTC did not - enter in the PARTNER's direction
    psd = pd.Series(pret).rolling(720).std().shift(1).to_numpy()
    bsd = pd.Series(btc_ret).rolling(720).std().shift(1).to_numpy()
    div = (np.abs(pret) >= 1.5 * psd) & (np.abs(btc_ret) <= 0.5 * bsd) & np.isfinite(psd) & np.isfinite(bsd)
    # LEAD-LAG: partner simply moved, take BTC in the same direction
    lead = (np.abs(pret) >= 1.5 * psd) & np.isfinite(psd)

    for label, mask in (("DIVERGE", div), ("LEAD-LAG", lead)):
        e = base[mask[base]]
        if len(e) < 400:
            print("%-9s %-10s only %s" % (p if label == "DIVERGE" else "", label, f"{len(e):,}"))
            continue
        dirn = np.sign(pret[e]).astype(np.int8)
        for arm, dd in (("follow", dirn), ("fade", -dirn)):
            w_, m_, se_, tot_ = sim(e, dd)
            two = 2 * math.sqrt(se_ ** 2 + rse ** 2)
            diff = m_ - rm
            sig = abs(diff) > two
            if arm == "follow":
                tested += 1
                hits += 1 if sig and diff > 0 else 0
            print("%-9s %-10s %8s %6.2f%% %+11.4f %+10.4f  %s"
                  % (p if (label == "DIVERGE" and arm == "follow") else "",
                     "%s %s" % (label, arm), f"{tot_:,}", w_, m_, diff,
                     ("REAL %s" % ("better" if diff > 0 else "worse")) if sig else ""))
    print("%-9s corr(partner, BTC) over 30-min returns = %+.3f" % ("", corr))
mt5.shutdown()
print("-" * 80)
print("\n%d of %d 'follow' arms beat BTC's own random control significantly." % (hits, tested))
print("""
One hit out of many is what chance produces - the last test taught that the hard
way. Only a mechanism appearing across SEVERAL partners is worth anything, and it
should appear more strongly in the partners that are more correlated.""")
