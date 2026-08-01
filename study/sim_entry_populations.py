"""Do the hlines destroy the crowding effect, or does it simply not reach any strategy?

The crowding result is real on the general population - +2.90pp stop-out on BTC, +2.00pp
on ETH, five of five volatility quintiles, rotation nulls at 1.0% and 0.0%. It then
vanished, and reversed, on the 5,892 setups KinoliveLines would actually have taken.

Two explanations were left open and they have very different consequences:

  A  the hline filter destroys it. Being within 0.06 x ATR_H1 of a previous bar's high
     or low is itself a market state, and conditioning on it removes whatever crowding
     was measuring. If so, the hlines are actively costing us a real effect and there is
     a concrete reason to abandon them.

  B  it does not survive ANY entry conditioning, or 920 crowded setups was simply too
     small - 2SE was 3.4pp against an effect of 2-3pp. If so, the hlines are exonerated.

THE DESIGN. Hold everything constant except WHEN the trade is opened. Same instrument,
same management rules, same funding series, same direction convention, same horizon.
Only the entry population changes:

    all bars     every M15 bar - the population the effect was found on
    hline        the daemon's real setups, rebuilt mechanically
    breakout     close beyond the high/low of the previous 24 M15 bars. A genuinely
                 different trigger: momentum expansion rather than proximity to a level
    random       uniformly sampled bars, matched in count to the hline population.
                 The control for "does ANY sparse sampling lose the effect"

DIRECTION IS HELD CONSTANT at the sign of the prior 4-hour move, which is the convention
the original finding used. That matters: if hline trades were fade-directional and the
others were not, direction rather than timing would explain any difference.

OVERLAP is removed the same way everywhere - greedily, one position at a time, exactly as
the live daemon behaves. A 4-hour outcome never shares bars with the next.

POWER is reported for every population, because the honest answer to "the effect is
absent here" is often "this sample could never have seen it".
"""
import os, math, random
import numpy as np, pandas as pd
import MetaTrader5 as mt5

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "recorder", "data")
SYM = "BTCUSDm"
STOP_ATR, RR, BE_R, HOLD = 0.8, 1.5, 1.0, 16      # 16 M15 bars = 4 hours
RANK_W, TOPQ, BRK_LOOK = 720, 0.05, 24
rng = random.Random(60606)

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select(SYM, True)
tk = mt5.symbol_info_tick(SYM)
SPREAD = tk.ask - tk.bid
r = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M15, 0, 50000)
mt5.shutdown()
m15 = pd.DataFrame(r)
m15["time"] = pd.to_datetime(m15["time"], unit="s")
mH, mL, mC = m15.high.to_numpy(float), m15.low.to_numpy(float), m15.close.to_numpy(float)
pc = m15.close.shift(1)
atr15 = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                   (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean().to_numpy()
N = len(mC)

# ---------------------------------------------------------------- funding rank
fh = pd.read_csv(os.path.join(DATA, "hist_BTC_PERPETUAL.csv"))
fval = fh["interest_1h"].to_numpy(float)
frank = np.full(len(fval), np.nan)
win = np.lib.stride_tricks.sliding_window_view(fval, RANK_W)[:-1]
frank[RANK_W:] = (win < fval[RANK_W:, None]).mean(axis=1)
f_avail = fh["ts"].to_numpy() + 3600_000                  # hour must have CLOSED
bar_ms = m15["time"].to_numpy().astype("datetime64[ms]").astype(np.int64)
j = np.searchsorted(f_avail, bar_ms, side="right") - 1
bar_rank = np.where((j >= RANK_W) & (j < len(frank)), frank[np.clip(j, 0, len(frank) - 1)], np.nan)

# ---------------------------------------------------------------- trade
def run(i0, side, stop_d):
    entry = mC[i0] + side * SPREAD / 2
    stop, tgt = entry - side * stop_d, entry + side * stop_d * RR
    be_at = entry + side * stop_d * BE_R
    moved = False
    for k in range(1, HOLD + 1):
        j2 = i0 + k
        if j2 >= N:
            break
        hi, lo = mH[j2], mL[j2]
        hs = (lo <= stop) if side > 0 else (hi >= stop)
        ht = (hi >= tgt) if side > 0 else (lo <= tgt)
        if hs:
            return (0.0 if moved else -1.0), k, True       # stop first on ambiguity
        if ht:
            return float(RR), k, False
        if not moved and ((hi >= be_at) if side > 0 else (lo <= be_at)):
            stop, moved = entry, True
    j2 = min(i0 + HOLD, N - 1)
    return side * (mC[j2] - entry) / stop_d, HOLD, False


# ---------------------------------------------------------------- populations
valid = np.where(np.isfinite(atr15) & (atr15 > 0) & np.isfinite(bar_rank))[0]
valid = valid[(valid > BRK_LOOK + 2) & (valid < N - HOLD - 1)]

pops = {"all bars": valid}

su = pd.read_csv(os.path.join(BASE, "study", "setups.csv"))
pops["hline"] = np.array(sorted(set(su["i"].astype(int)) & set(valid.tolist())))

brk = []
for i in valid:
    w = slice(i - BRK_LOOK, i)
    if mC[i] > mH[w].max() or mC[i] < mL[w].min():
        brk.append(i)
pops["breakout"] = np.array(brk)

pool = [int(x) for x in valid]
rng.shuffle(pool)
pops["random"] = np.array(sorted(pool[:len(pops["hline"])]))


def non_overlapping(idx):
    out, busy = [], -1
    for i in idx:
        if i > busy:
            out.append(int(i)); busy = i + HOLD
    return out


print("DOES THE ENTRY POPULATION DESTROY THE CROWDING EFFECT?")
print("direction = sign of the prior 4h move (the convention the effect was found on)")
print("management = the bot's own: stop %.1fx ATR(M15), target %.1fR, BE at %.1fR, %dh cap\n"
      % (STOP_ATR, RR, BE_R, HOLD // 4))
print("%-11s %8s %8s %9s %9s %11s %8s  %s"
      % ("population", "trades", "crowded", "crowd SO", "norm SO", "difference", "2SE", "verdict"))
print("-" * 104)

for name, idx in pops.items():
    seq = non_overlapping(idx)
    rows = []
    for i in seq:
        d = np.sign(mC[i] - mC[i - HOLD]) if i >= HOLD else 0
        if d == 0:
            continue
        R, bars, stopped = run(i, d, STOP_ATR * atr15[i])
        rows.append((bar_rank[i], stopped, R))
    if len(rows) < 200:
        print("%-11s too few" % name); continue
    rk = np.array([x[0] for x in rows])
    so = np.array([float(x[1]) for x in rows])
    cm = (rk <= TOPQ) | (rk >= 1 - TOPQ)
    nm = (rk > 0.2) & (rk < 0.8)
    if cm.sum() < 60 or nm.sum() < 120:
        print("%-11s too few in a bucket" % name); continue
    pc_, pn = so[cm].mean(), so[nm].mean()
    two = 2 * math.sqrt(pc_ * (1 - pc_) / cm.sum() + pn * (1 - pn) / nm.sum())
    d = pc_ - pn
    v = ("EFFECT PRESENT" if d > two else
         "wrong sign" if d < -two else
         "absent (could see it)" if two < 0.02 else "INCONCLUSIVE - underpowered")
    print("%-11s %8d %8d %8.1f%% %8.1f%% %+10.1fpp %7.1fpp  %s"
          % (name, len(rows), int(cm.sum()), 100 * pc_, 100 * pn, 100 * d, 100 * two, v))

print("""
READ THE 2SE COLUMN BEFORE THE VERDICT. The effect being hunted is +2 to +3pp. Any
population whose 2SE exceeds that could not have detected it however real it is, and
"absent" there means nothing at all.

If the effect is present on all bars and on random sampling but absent on hline setups,
the hline condition is destroying it and that is a concrete reason to drop them. If it
is absent on random sampling too, then sparse entry selection is not the problem and the
hlines are exonerated - the effect simply does not survive being traded.""")
