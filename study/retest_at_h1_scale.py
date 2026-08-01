"""Re-run the entry signals at H1 scale, where the spread drag is nearly gone.

Every earlier test measured entries at M15 scale, where a fixed $10 spread costs
about 5 win-rate points. A signal worth 2 or 3 points would have read as nothing -
not because it was absent, but because it was swamped by the drag it was swimming
against. At H1 scale the drag falls to near zero (JP225 measured -0.0008 with
RANDOM entries), so the same signal could now be visible.

    old:  signal +2 pts  -  drag 5 pts  =  -3   "nothing here"
    new:  signal +2 pts  -  drag 0 pts  =  +2   tradeable

Only ENTRY signals are retested. Geometry, hold time and reward-to-risk are exit
rules, and for a series without drift no exit rule can create expectancy - that is
arithmetic, not an empirical question, and it is exactly why those came back
neutral. Retesting them would be theatre.

EFFICIENCY: the geometry is fixed, so the outcome of a long and a short from every
bar is computed ONCE per symbol, then each signal simply selects a subset. That
turns six signals x four symbols into one pass instead of twenty-four.

Cross-instrument replication is built in from the start. Three leads tonight
passed on BTC alone and died elsewhere; a signal that works on one symbol is not
a finding.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYMBOLS = ["BTCUSDm", "JP225m", "XAUUSDm", "US30m"]
STOP_ATR_H1, TMULT, HOLD, STEP = 1.0, 1.5, 96, 7      # 96 M5 bars = 8 hours
LOOK = 6                                              # 6 M5 bars = 30 min momentum window

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


def prep(sym):
    tick = mt5.symbol_info_tick(sym)
    if tick is None or tick.ask <= 0:
        return None
    spread = tick.ask - tick.bid
    m5 = bars(sym, mt5.TIMEFRAME_M5, 50000)
    h1 = bars(sym, mt5.TIMEFRAME_H1, 45000)
    h4 = bars(sym, mt5.TIMEFRAME_H4, 20000)
    if any(x is None for x in (m5, h1, h4)):
        return None
    h1 = h1.copy(); h1["atr"] = atr_of(h1)
    j = h1[["time", "atr"]].dropna().copy()
    j["time"] = (j["time"] + pd.Timedelta(minutes=60)).astype("datetime64[ns]")
    d = pd.merge_asof(m5, j, on="time", direction="backward").dropna(subset=["atr"]).reset_index(drop=True)
    if len(d) < 12000:
        return None

    hi, lo, cl = d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float)
    atr, vol = d.atr.to_numpy(float), d.tick_volume.to_numpy(float)
    n = len(cl)

    # ---- outcome of a long and a short from every sampled bar, computed once ----
    idx = np.arange(300, n - HOLD, STEP)
    rl = np.full(len(idx), np.nan)
    rs = np.full(len(idx), np.nan)
    for k, i in enumerate(idx):
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        sd, td = STOP_ATR_H1 * A, STOP_ATR_H1 * A * TMULT
        w = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[w]); rmin = np.minimum.accumulate(lo[w])
        mid, endp = cl[i], cl[i + HOLD]
        for sgn, store in ((1, "l"), (-1, "s")):
            e = mid + sgn * spread / 2
            tp, sl = e + sgn * td, e - sgn * sd
            if sgn > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                hs = np.argmax(rmin <= sl) if rmin[-1] <= sl else 10 ** 6
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                hs = np.argmax(rmax >= sl) if rmax[-1] >= sl else 10 ** 6
            if ht == 10 ** 6 and hs == 10 ** 6:
                r = sgn * (endp - e) / A                      # settled at the cap
            elif ht == hs:
                r = (TMULT - 1.0) / 2 * STOP_ATR_H1           # ambiguous bar, neutral
            elif hs < ht:
                r = -STOP_ATR_H1
            else:
                r = STOP_ATR_H1 * TMULT
            if store == "l": rl[k] = r
            else: rs[k] = r

    # ---- signals, all strictly backward-looking ----
    mv = np.full(n, np.nan)
    mv[LOOK:] = cl[LOOK:] - cl[:-LOOK]
    lvl = np.zeros(n, bool)
    brk = np.zeros(n, np.int8)
    for src, mins in ((h1, 60), (h4, 240)):
        jj = np.searchsorted((src["time"] + pd.Timedelta(minutes=mins)).values,
                             d["time"].values, side="right") - 1
        H, L = src["high"].to_numpy(), src["low"].to_numpy()
        ok = np.where(jj >= 1)[0]
        q = jj[ok]
        lvl[ok] |= ((lo[ok] <= H[q]) & (hi[ok] >= H[q])) | ((lo[ok] <= L[q]) & (hi[ok] >= L[q]))
        brk[ok[(cl[ok - 1] < H[q]) & (cl[ok] > H[q])]] = 1
        brk[ok[(cl[ok - 1] > L[q]) & (cl[ok] < L[q])]] = -1
    vq = pd.Series(vol).rolling(288).quantile(0.80).shift(1).to_numpy()
    vmed = pd.Series(vol).rolling(288).median().shift(1).to_numpy()
    rng = pd.Series(hi).rolling(12).max().to_numpy() - pd.Series(lo).rolling(12).min().to_numpy()
    rlo = pd.Series(rng).rolling(96).min().shift(1).to_numpy()

    return dict(sym=sym, idx=idx, rl=rl, rs=rs, spread=spread,
                mv=mv, lvl=lvl, brk=brk, atr=atr,
                highvol=vol >= vq, spike=vol >= 3 * vmed, squeeze=rng <= rlo * 1.02,
                hi=hi, lo=lo, cl=cl)


def stat(vals):
    v = vals[np.isfinite(vals)]
    if len(v) < 200:
        return None
    m = v.mean()
    return m, v.std() / math.sqrt(len(v)), len(v)


def evaluate(P):
    """Return {signal: (mean, se, n)} using the precomputed outcomes."""
    i, rl, rs = P["idx"], P["rl"], P["rs"]
    both = np.concatenate([rl, rs])
    out = {"RANDOM": stat(both)}

    mvv, lvlv, brkv = P["mv"][i], P["lvl"][i], P["brk"][i]
    dirn = np.sign(mvv)
    mom = np.abs(mvv) >= 1.0 * P["atr"][i] * 0.35     # ~1x ATR(M15)-equivalent move

    def directed(mask, sign_arr):
        pick = np.where(sign_arr > 0, rl, rs)
        return stat(np.where(mask, pick, np.nan))

    def located(mask):
        return stat(np.concatenate([np.where(mask, rl, np.nan),
                                    np.where(mask, rs, np.nan)]))

    out["level touch"] = located(lvlv)
    out["high volume"] = located(P["highvol"][i])
    out["vol spike"] = located(P["spike"][i])
    out["squeeze"] = located(P["squeeze"][i])
    out["momentum follow"] = directed(mom, dirn)
    out["momentum fade"] = directed(mom, -dirn)
    out["mom at level"] = directed(mom & lvlv, dirn)
    out["break follow"] = directed(brkv != 0, brkv)
    out["break fade"] = directed(brkv != 0, -brkv)
    return out


print("Retesting entry signals at H1 scale: stop 1.0x ATR(H1), target 1.5x, 8h hold\n")
res = {}
for s in SYMBOLS:
    try:
        P = prep(s)
    except Exception as ex:
        print("%-9s failed: %s" % (s, type(ex).__name__)); continue
    if P is None:
        print("%-9s no usable data" % s); continue
    res[s] = evaluate(P)
    r = res[s]["RANDOM"]
    print("%-9s random baseline %+.4f  (n=%s, spread %.2f)" % (s, r[0], f"{r[2]:,}", P["spread"]))
mt5.shutdown()

if not res:
    raise SystemExit("no symbols usable")

signals = [k for k in res[SYMBOLS[0]] if k != "RANDOM"]
print("\n%-18s" % "signal" + "".join("%13s" % s.replace("USDm", "").replace("m", "") for s in res)
      + "%10s" % "verdict")
print("-" * (18 + 13 * len(res) + 10))
for sig in signals:
    row = "%-18s" % sig
    votes = 0
    for s in res:
        v, rnd = res[s].get(sig), res[s]["RANDOM"]
        if v is None:
            row += "%13s" % "-"; continue
        diff = v[0] - rnd[0]
        two = 2 * math.sqrt(v[1] ** 2 + rnd[1] ** 2)
        star = "*" if abs(diff) > two else " "
        row += "%12.4f%s" % (diff, star)
        if abs(diff) > two:
            votes += 1 if diff > 0 else -1
    verdict = "REAL" if votes >= 3 else ("worse" if votes <= -3 else "")
    print(row + "%10s" % verdict)
print("-" * (18 + 13 * len(res) + 10))
print("""
Figures are the difference from that symbol's OWN random baseline, in units of the
stop. * marks beyond 2 standard errors. A verdict needs the SAME direction on at
least three of the four symbols - one symbol agreeing is what chance produces, and
that is precisely how three leads died earlier tonight.""")
