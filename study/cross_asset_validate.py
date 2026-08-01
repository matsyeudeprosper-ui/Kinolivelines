"""Validate the equity-divergence effect before believing it.

Four equity indices agreed that when they move and BTC does not, BTC then moves
AGAINST them. Some cells were absolutely positive - the largest effects measured
in this project. Three reasons that is not yet a finding:

  the indices are not independent   US30/US500/USTEC are largely one market, so
                                    four agreeing is closer to one observation
                                    repeated than to four confirmations
  DE30 contradicts                  same asset class, opposite sign
  26 cells were examined            some significance is guaranteed

THREE CHECKS:
  1 SPLIT-HALF   does each index's divergence-fade hold in both halves of the 68
                 days, independently?
  2 MORE INDICES bring in additional equity markets. Treat agreement as weak
                 evidence (they co-move) but DISAGREEMENT as strong evidence
                 against, since a real mechanism should not flip between venues.
  3 DE30         is its reversal stable across halves, or noise?

A finding survives only if the sign is consistent in both halves for most of the
indices tested. Anything that appears in one half and vanishes in the other
belonged to a stretch of market, not to markets.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

TARGET = "BTCUSDm"
INDICES = ["USTECm", "US500m", "US30m", "JP225m", "DE30m", "UK100m", "FRA40m", "AUS200m", "HK50m"]
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
SPREAD = mt5.symbol_info_tick(TARGET).ask - mt5.symbol_info_tick(TARGET).bid

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
bsd = pd.Series(btc_ret).rolling(720).std().shift(1).to_numpy()
WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR
half = n // 2


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
    return m, math.sqrt(max(s2 / tot - m * m, 0) / tot), tot


ctrl = {}
for lbl, rng in (("A", np.arange(800, half)), ("B", np.arange(half, n - HOLD - 2))):
    both = np.tile(rng, 2)
    ds = np.r_[np.ones(len(rng), np.int8), -np.ones(len(rng), np.int8)]
    ctrl[lbl] = sim(both, ds)
print("BTC random control   half A %+.4f   half B %+.4f\n" % (ctrl["A"][0], ctrl["B"][0]))

print("%-9s %6s  %-22s %-22s  %s" % ("index", "corr", "half A (fade)", "half B (fade)", "verdict"))
print("-" * 86)
agree = disagree = 0
for p in INDICES:
    pm1 = bars(p, mt5.TIMEFRAME_M1, 99000)
    if pm1 is None:
        print("%-9s not available" % p); continue
    pj = pd.merge_asof(d[["time"]], pm1[["time", "close"]].rename(columns={"close": "p"}),
                       on="time", direction="backward", tolerance=pd.Timedelta(minutes=5))
    pcl = pj["p"].to_numpy(float)
    pret = np.full(n, np.nan)
    pret[LOOK:] = (pcl[LOOK:] - pcl[:-LOOK]) / pcl[:-LOOK]
    ok = np.isfinite(pret) & np.isfinite(btc_ret)
    if ok.sum() < 15000:
        print("%-9s too little overlap" % p); continue
    corr = np.corrcoef(pret[ok], btc_ret[ok])[0, 1]
    psd = pd.Series(pret).rolling(720).std().shift(1).to_numpy()
    div = (np.abs(pret) >= 1.5 * psd) & (np.abs(btc_ret) <= 0.5 * bsd) & np.isfinite(psd) & np.isfinite(bsd)

    out, signs = [], []
    for lbl, rng in (("A", np.arange(800, half)), ("B", np.arange(half, n - HOLD - 2))):
        e = np.array([i for i in rng if div[i]])
        if len(e) < 150:
            out.append("n=%-4d too few        " % len(e)); signs.append(0); continue
        m_, se_, tot_ = sim(e, -np.sign(pret[e]).astype(np.int8))     # FADE the index
        rm_, rse_, _ = ctrl[lbl]
        two = 2 * math.sqrt(se_ ** 2 + rse_ ** 2)
        star = "*" if abs(m_ - rm_) > two else " "
        out.append("n=%-5d %+.4f%s" % (tot_, m_ - rm_, star))
        signs.append(1 if m_ - rm_ > 0 else -1)
    if signs[0] and signs[0] == signs[1]:
        v = "CONSISTENT (%s)" % ("fade better" if signs[0] > 0 else "fade worse")
        agree += 1 if signs[0] > 0 else 0
        disagree += 1 if signs[0] < 0 else 0
    else:
        v = "flips between halves"
    print("%-9s %+.3f  %-22s %-22s  %s" % (p, corr, out[0], out[1], v))
mt5.shutdown()
print("-" * 86)
print("\n* = significantly different from BTC's own random control in that half")
print("indices where FADE is consistently better across both halves: %d" % agree)
print("indices where FADE is consistently worse: %d" % disagree)
print("""
Remember these indices co-move, so agreement is weaker evidence than the count
suggests. Disagreement, though, is strong evidence against - a real mechanism
should not reverse from one equity venue to another.""")
