"""Recompute the bot's own setups the RIGHT way - stratified by entry volatility.

The interaction test inside sim_variants.py compared crowded against normal stop-out
rates on the bot's real setups and reported -2.3pp, "wrong sign", and the branch was
closed on it. That comparison was NOT stratified by entry volatility.

This project has already established, and written into FINDINGS.md as trap #5, that the
unstratified version of exactly this comparison inverts the sign: funding extremes arrive
after violent moves, so crowded entries sit at systematically higher ATR, and on raw
numbers ETH said crowded markets were SAFER (34.9% vs 35.6%) while the stratified version
said riskier (+2.00pp). Reporting the raw number here repeated the mistake the file warns
about.

So: same setups, same management, same funding series, but the crowded-versus-normal
comparison made INSIDE quintiles of entry volatility.

Volatility rank uses a 2,880-bar M15 window - 30 days, matching the 720-hour window the
funding rank uses, so the two conditions are measured over comparable horizons.

Both direction conventions are reported, and the power is stated plainly: with ~920
crowded setups this sample resolves roughly 3-4pp, so a 2-3pp effect sits near the edge
of what it can see. That is a limit of 1.4 years of M15 history, not a verdict.
"""
import os, math
import numpy as np, pandas as pd
import MetaTrader5 as mt5

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "recorder", "data")
SYM = "BTCUSDm"
STOP_ATR, RR, BE_R, HOLD = 0.8, 1.5, 1.0, 16
RANK_W_F, RANK_W_V, TOPQ, NQ = 720, 2880, 0.05, 5

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select(SYM, True)
tk = mt5.symbol_info_tick(SYM)
SPREAD = tk.ask - tk.bid
r = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M15, 0, 50000)
mt5.shutdown()
m = pd.DataFrame(r)
m["time"] = pd.to_datetime(m["time"], unit="s")
mH, mL, mC = m.high.to_numpy(float), m.low.to_numpy(float), m.close.to_numpy(float)
pc = m.close.shift(1)
atr = pd.concat([m.high - m.low, (m.high - pc).abs(),
                 (m.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean().to_numpy()
N = len(mC)


def trailing_rank(v, w):
    out = np.full(len(v), np.nan)
    vv = np.where(np.isfinite(v), v, 0.0)
    win = np.lib.stride_tricks.sliding_window_view(vv, w)[:-1]
    out[w:] = (win < vv[w:, None]).mean(axis=1)
    return out


vrank = trailing_rank(atr, RANK_W_V)

fh = pd.read_csv(os.path.join(DATA, "hist_BTC_PERPETUAL.csv"))
fv = fh["interest_1h"].to_numpy(float)
fr = np.full(len(fv), np.nan)
w = np.lib.stride_tricks.sliding_window_view(fv, RANK_W_F)[:-1]
fr[RANK_W_F:] = (w < fv[RANK_W_F:, None]).mean(axis=1)
avail = fh["ts"].to_numpy() + 3600_000
bms = m["time"].to_numpy().astype("datetime64[ms]").astype(np.int64)
j = np.searchsorted(avail, bms, side="right") - 1
brank = np.where((j >= RANK_W_F) & (j < len(fr)), fr[np.clip(j, 0, len(fr) - 1)], np.nan)


def run(i0, side, stop_d):
    entry = mC[i0] + side * SPREAD / 2
    stop, tgt = entry - side * stop_d, entry + side * stop_d * RR
    be_at = entry + side * stop_d * BE_R
    moved = False
    for k in range(1, HOLD + 1):
        i = i0 + k
        if i >= N:
            break
        hs = (mL[i] <= stop) if side > 0 else (mH[i] >= stop)
        ht = (mH[i] >= tgt) if side > 0 else (mL[i] <= tgt)
        if hs:
            return (0.0 if moved else -1.0), True
        if ht:
            return float(RR), False
        if not moved and ((mH[i] >= be_at) if side > 0 else (mL[i] <= be_at)):
            stop, moved = entry, True
    i = min(i0 + HOLD, N - 1)
    return side * (mC[i] - entry) / stop_d, False


su = pd.read_csv(os.path.join(BASE, "study", "setups.csv"), parse_dates=["time"])
su = su[[np.isfinite(brank[int(i)]) and np.isfinite(vrank[int(i)]) and
         np.isfinite(atr[int(i)]) and atr[int(i)] > 0 for i in su["i"]]].reset_index(drop=True)

print("THE BOT'S OWN SETUPS, STRATIFIED BY ENTRY VOLATILITY")
print("%s setups with a usable funding and volatility rank\n" % f"{len(su):,}")

cuts = np.quantile([vrank[int(i)] for i in su["i"]], np.linspace(0, 1, NQ + 1)[1:-1])

for conv in ("fade", "follow", "prior-move"):
    so, rk, vq = [], [], []
    busy = -1
    for _, s in su.iterrows():
        i = int(s["i"])
        if i <= busy:                 # one position at a time, as live
            continue
        if conv == "prior-move":
            side = np.sign(mC[i] - mC[i - HOLD]) if i >= HOLD else 0
        else:
            base = -1 if s["isHigh"] else 1
            side = base if conv == "fade" else -base
        if side == 0:
            continue
        R, stopped = run(i, side, STOP_ATR * s["atr15"])
        so.append(float(stopped)); rk.append(brank[i]); vq.append(int(np.searchsorted(cuts, vrank[i])))
        busy = i + HOLD
    so, rk, vq = np.array(so), np.array(rk), np.array(vq)
    crowd = (rk <= TOPQ) | (rk >= 1 - TOPQ)
    norm = (rk > 0.2) & (rk < 0.8)

    raw = so[crowd].mean() - so[norm].mean()
    num = den = var = 0.0
    cells = []
    for q in range(NQ):
        mq = vq == q
        e, o = so[mq & crowd], so[mq & norm]
        if len(e) < 20 or len(o) < 40:
            cells.append(None); continue
        pe, po = e.mean(), o.mean()
        num += len(e) * (pe - po); den += len(e)
        var += len(e) ** 2 * (pe * (1 - pe) / len(e) + po * (1 - po) / len(o))
        cells.append((pe - po, len(e)))
    est, two = num / den, 2 * math.sqrt(var) / den
    agree = sum(1 for c in cells if c and (c[0] > 0) == (est > 0))
    got = sum(1 for c in cells if c)
    print("  %-11s trades %-5d crowded %-4d | RAW %+.1fpp | STRATIFIED %+.1fpp  2SE %.1fpp"
          "  %d of %d quintiles agree"
          % (conv, len(so), int(crowd.sum()), 100 * raw, 100 * est, 100 * two, agree, got))
    print("     per quintile: " + "  ".join(
        ("%+.1fpp" % (100 * c[0])) if c else "-" for c in cells))

print("""
Compare RAW with STRATIFIED on each row. Where they disagree in sign, the raw figure was
measuring the fact that crowded entries happen at higher volatility, not anything about
crowding itself.

Note the power: with roughly 900 crowded setups the interval is 3-4pp wide, so a genuine
2-3pp effect cannot be confirmed here even if present. This sample can rule out a LARGE
effect; it cannot rule out the one we are looking for.""")
