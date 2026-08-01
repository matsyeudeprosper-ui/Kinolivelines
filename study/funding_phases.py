"""Does 'join the crowded side' survive using ALL the data instead of 1/72nd of it?

The first funding test found the only sign-consistent result of this entire search:
joining the crowded side beat random by +0.086 on BTC and +0.086 on ETH at a 3-day
horizon. It was 0.6 standard errors from zero - suggestive, not proven - because
non-overlapping 72-hour windows leave only ~870 samples out of 62,844 hours.

The tempting fix is overlapping windows. That is trap #5, the mistake that shrank
every error bar in this project by 5.3x and flipped a gold result from negative to
positive. Not doing that again.

THE HONEST FIX - PHASE SHIFTING. There are 72 different places to start a chain of
non-overlapping 72-hour windows. Each phase is a complete, clean, non-overlapping
sample in its own right. Running all 72 uses every hour of history without ever
comparing two windows that share a bar.

What it buys is not a smaller error bar - each phase still has ~870 windows and its
own honest SE. What it buys is STABILITY: if the effect is real it appears in most
of the 72 phases. If it came from a handful of lucky windows, some phases will show
it strongly and others will show nothing or the reverse, and the spread across phases
exposes that. A number that survives 72 independent slicings of the same history is
a very different thing from a number seen once.

Also fixed here: the first run tested "top 20% vs bottom 20%" as one combined signal.
That conflates two different states. This separates them - crowded LONGS and crowded
SHORTS are reported apart, because there is no reason to assume they behave alike.
"""
import os, math
import pandas as pd, numpy as np
import MetaTrader5 as mt5

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recorder", "data")
PAIRS = [("BTC-PERPETUAL", "BTCUSDm"), ("ETH-PERPETUAL", "ETHUSDm")]
TMULT, RANK_W, TOPQ, HOLD = 1.5, 720, 0.20, 72

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def live_spread(sym, px):
    if mt5.symbol_select(sym, True):
        t = mt5.symbol_info_tick(sym)
        if t and t.ask > t.bid > 0:
            return t.ask - t.bid
    return px * 0.0003


def load(fname):
    d = pd.read_csv(os.path.join(DATA, fname))
    pc = d["close"].shift(1)
    d["atr"] = pd.concat([d.high - d.low, (d.high - pc).abs(),
                          (d.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
    f = d["interest_8h"]
    d["rank"] = f.rolling(RANK_W).apply(lambda w: (w[:-1] < w.iloc[-1]).mean(), raw=False)
    return d.dropna(subset=["atr", "rank"]).reset_index(drop=True)


def outcomes(d, spread):
    """Per-bar barrier outcome for a long and a short started at that bar."""
    hi, lo, cl = d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float)
    atr, rank = d.atr.to_numpy(float), d["rank"].to_numpy(float)
    n, WIN, LOSS = len(cl), TMULT, -1.0
    L = np.full((n, 3), np.nan); S = np.full((n, 3), np.nan)
    for i in range(30, n - HOLD):
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        sd, td = A, A * TMULT
        w = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[w]); rmin = np.minimum.accumulate(lo[w])
        mid, endp = cl[i], cl[i + HOLD]
        for sgn, arr in ((1, L), (-1, S)):
            e = mid + sgn * spread / 2
            tp, s_ = e + sgn * td, e - sgn * sd
            if sgn > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                hs = np.argmax(rmin <= s_) if rmin[-1] <= s_ else 10 ** 6
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                hs = np.argmax(rmax >= s_) if rmax[-1] >= s_ else 10 ** 6
            if ht == 10 ** 6 and hs == 10 ** 6:
                v = sgn * (endp - e) / A; arr[i] = (v, v, v)
            elif ht == hs:
                arr[i] = ((WIN + LOSS) / 2, LOSS, WIN)
            elif hs < ht:
                arr[i] = (LOSS, LOSS, LOSS)
            else:
                arr[i] = (WIN, WIN, WIN)
    return L, S, rank


HI, LO = 1 - TOPQ, TOPQ
STATES = [
    ("crowded LONGS  join", lambda rk: rk >= HI, +1),
    ("crowded LONGS  fade", lambda rk: rk >= HI, -1),
    ("crowded SHORTS join", lambda rk: rk <= LO, -1),
    ("crowded SHORTS fade", lambda rk: rk <= LO, +1),
]

print("PHASE-SHIFT TEST - 'join the crowd' across all 72 non-overlapping slicings")
print("3-day hold, stop 1.0x ATR(H1), target 1.5x, Exness spread, trailing-720h rank\n")

for inst, mt5sym in PAIRS:
    fn = "hist_%s.csv" % inst.replace("-", "_")
    if not os.path.exists(os.path.join(DATA, fn)):
        print("%s: no cache\n" % inst); continue
    d = load(fn)
    spread = live_spread(mt5sym, float(d["close"].iloc[-1]))
    L, S, rank = outcomes(d, spread)
    n = len(d)
    print("=" * 98)
    print("%s   %s hours, spread %.2f" % (inst, f"{n:,}", spread))
    print("%-21s %9s %11s %11s %11s  %s"
          % ("signal", "avg n", "vs random", "worst phase", "best phase", "phases positive"))
    print("-" * 98)

    idx_all = np.arange(30, n - HOLD)
    for name, sel, side in STATES:
        per_phase, rnd_phase = [], []
        for ph in range(HOLD):
            take = idx_all[(idx_all - 30) % HOLD == ph]
            take = take[np.isfinite(L[take, 0]) & np.isfinite(S[take, 0])]
            if len(take) < 100:
                continue
            rnd = (L[take, 0].mean() + S[take, 0].mean()) / 2
            hit = take[sel(rank[take])]
            if len(hit) < 40:
                continue
            arr = L if side > 0 else S
            per_phase.append(arr[hit, 0].mean() - rnd)
            rnd_phase.append(len(hit))
        if not per_phase:
            print("%-21s too few" % name); continue
        v = np.array(per_phase)
        print("%-21s %9.0f %+11.4f %+11.4f %+11.4f  %d of %d"
              % (name, np.mean(rnd_phase), v.mean(), v.min(), v.max(),
                 int((v > 0).sum()), len(v)))
    print()
mt5.shutdown()

print("""
HOW TO READ THIS. "phases positive" is the number that matters. A real effect shows
up in nearly all 72 slicings - 65+ of 72. Around half is noise dressed up as a mean.
And check the worst-phase column: if the effect is real, even the unluckiest slicing
of seven years should not be badly negative.

Note the two crowded states are reported separately. If joining works when longs are
crowded but not when shorts are, that is not "join the crowd" - it is a long bias
picking up crypto's upward drift, and the random-entry control would already have
absorbed a genuine one.""")
