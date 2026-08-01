"""Split-half the one promising result: momentum-follow at H1 scale.

At H1 scale, momentum-follow measured ABSOLUTELY POSITIVE on two symbols -
JP225 +0.0161 and gold +0.0328, against baselines of roughly zero. That is the
first positive expectancy in the project that was predicted in advance rather
than found by searching: the same signal measured +0.019 at M15 scale but sat
under a -0.029 spread drag, so it lost. Remove the drag and it clears.

What is missing is proof. Each signal fires on a fraction of bars, so n per
symbol is ~1,500-2,800 and the error bar is about the size of the effect. Three
leads tonight looked exactly this good and died.

THE BAR, set before seeing results:
  * positive in BOTH halves of the period, on BOTH symbols - four cells
  * the FADE arm negative in those same cells (a real directional effect has a
    mirror; a fluke does not)
  * BTC and US30 reported alongside as out-of-sample context, not as evidence

Split-half is the right check HERE because the known failure modes are already
excluded: ties are negligible at this geometry, timeouts settle at the close, and
the effect has already replicated across instruments. What remains to rule out is
one lucky stretch of market.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYMBOLS = ["JP225m", "XAUUSDm", "BTCUSDm", "US30m"]
PRIMARY = {"JP225m", "XAUUSDm"}
STOP_ATR_H1, TMULT, HOLD, STEP, LOOK = 1.0, 1.5, 96, 5, 6

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


def run(sym):
    tick = mt5.symbol_info_tick(sym)
    if tick is None or tick.ask <= 0:
        return None
    spread = tick.ask - tick.bid
    m5 = bars(sym, mt5.TIMEFRAME_M5, 50000)
    h1 = bars(sym, mt5.TIMEFRAME_H1, 45000)
    if m5 is None or h1 is None:
        return None
    h1 = h1.copy(); h1["atr"] = atr_of(h1)
    j = h1[["time", "atr"]].dropna().copy()
    j["time"] = (j["time"] + pd.Timedelta(minutes=60)).astype("datetime64[ns]")
    d = pd.merge_asof(m5, j, on="time", direction="backward").dropna(subset=["atr"]).reset_index(drop=True)
    if len(d) < 12000:
        return None

    hi, lo, cl = d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float)
    atr = d.atr.to_numpy(float)
    n = len(cl)
    mv = np.full(n, np.nan)
    mv[LOOK:] = cl[LOOK:] - cl[:-LOOK]

    idx = np.arange(300, n - HOLD, STEP)
    rl = np.full(len(idx), np.nan); rs = np.full(len(idx), np.nan)
    for k, i in enumerate(idx):
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        sd, td = STOP_ATR_H1 * A, STOP_ATR_H1 * A * TMULT
        w = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[w]); rmin = np.minimum.accumulate(lo[w])
        mid, endp = cl[i], cl[i + HOLD]
        for sgn in (1, -1):
            e = mid + sgn * spread / 2
            tp, sl = e + sgn * td, e - sgn * sd
            if sgn > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                hs = np.argmax(rmin <= sl) if rmin[-1] <= sl else 10 ** 6
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                hs = np.argmax(rmax >= sl) if rmax[-1] >= sl else 10 ** 6
            if ht == 10 ** 6 and hs == 10 ** 6:
                r = sgn * (endp - e) / A
            elif ht == hs:
                r = (TMULT - 1.0) / 2 * STOP_ATR_H1
            elif hs < ht:
                r = -STOP_ATR_H1
            else:
                r = STOP_ATR_H1 * TMULT
            if sgn > 0: rl[k] = r
            else: rs[k] = r

    mvv = mv[idx]
    dirn = np.sign(mvv)
    mom = np.abs(mvv) >= 0.35 * atr[idx]
    half = len(idx) // 2

    def cell(sel, sign_arr):
        pick = np.where(sign_arr > 0, rl, rs)
        v = pick[sel & np.isfinite(pick)]
        if len(v) < 150:
            return None
        return v.mean(), v.std() / math.sqrt(len(v)), len(v)

    out = {}
    for lbl, sl_ in (("A", np.arange(len(idx)) < half), ("B", np.arange(len(idx)) >= half)):
        base = np.concatenate([rl[sl_], rs[sl_]])
        base = base[np.isfinite(base)]
        out[lbl] = {
            "random": (base.mean(), base.std() / math.sqrt(len(base)), len(base)),
            "follow": cell(sl_ & mom, dirn),
            "fade":   cell(sl_ & mom, -dirn),
        }
    return out


print("MOMENTUM-FOLLOW AT H1 SCALE, split in half")
print("stop 1.0x ATR(H1), target 1.5x, 8h hold, real spread, random-entry control\n")
print("%-9s %-6s %10s %10s %11s %10s  %s"
      % ("symbol", "half", "random", "follow", "fade", "n follow", "verdict"))
print("-" * 76)

verdicts = {}
for s in SYMBOLS:
    try:
        r = run(s)
    except Exception as ex:
        print("%-9s failed: %s" % (s, type(ex).__name__)); continue
    if r is None:
        print("%-9s no usable data" % s); continue
    ok = []
    for h in ("A", "B"):
        rnd, fol, fad = r[h]["random"], r[h]["follow"], r[h]["fade"]
        if fol is None:
            print("%-9s %-6s too few" % (s if h == "A" else "", h)); ok.append(False); continue
        pos = fol[0] > 0
        mirror = fad is not None and fad[0] < fol[0]
        ok.append(pos and mirror)
        tag = ("POSITIVE" if pos else "negative") + (", mirrored" if mirror else ", NO mirror")
        print("%-9s %-6s %10.4f %10.4f %11.4f %10s  %s"
              % (s if h == "A" else "", h, rnd[0], fol[0],
                 fad[0] if fad else float("nan"), f"{fol[2]:,}", tag))
    verdicts[s] = all(ok)
    print()
mt5.shutdown()
print("-" * 76)
print("\nBAR: positive in BOTH halves with the fade arm below it, on BOTH primaries.\n")
for s, v in verdicts.items():
    role = "PRIMARY" if s in PRIMARY else "context"
    print("  %-9s %-8s %s" % (s, role, "PASSES" if v else "fails"))
prim = [verdicts.get(s) for s in PRIMARY if s in verdicts]
print("\nRESULT: %s" % ("BOTH primaries pass - worth taking further"
                        if prim and all(prim) else
                        "did not clear the bar - joins the pile"))
