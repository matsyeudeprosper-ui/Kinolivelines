"""Is there ANY condition that unbalances which barrier gets hit first?

The question is well posed: direction does not need predicting, only imbalance. A filter
that reliably produced 65% losers is worth exactly as much as one producing 65% winners,
because the trade can simply be flipped. So this scans for deviation from 50/50 in either
direction.

TWO BARS, and the first is the one that kills most candidates.

  ECONOMIC. At the live geometry - win $1.00, lose $2.00 - breakeven needs 66.7%. A
  condition showing 56% is real information and still loses money. Anything between about
  33% and 67% is unprofitable in BOTH directions, flipped or not.

  STATISTICAL. Around a dozen conditions are tested here. At 2SE, roughly one in twenty
  cells crosses by chance, so a single crossing proves nothing - the cell count is printed
  so that can be judged rather than assumed.

Only DECIDED trades count. Ambiguous bars, where price touched both barriers inside one
M5 bar, are excluded rather than guessed: including them under any convention would move
the win rate by the convention rather than by the condition.
"""
import os, csv, math, random
import numpy as np, pandas as pd
import MetaTrader5 as mt5

SYM, LOTS = "BTCUSDm", 0.05
TP_PTS, SL_PTS, MAX_BARS = 20.0, 40.0, 24
BREAKEVEN = SL_PTS / (SL_PTS + TP_PTS)          # 0.667
rng = random.Random(8080)

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select(SYM, True)
tk = mt5.symbol_info_tick(SYM); SPREAD = tk.ask - tk.bid
r5 = None
for w in (200000, 120000, 60000, 30000):
    r5 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 0, w)
    if r5 is not None and len(r5): break
mt5.shutdown()
d5 = pd.DataFrame(r5); d5["t"] = pd.to_datetime(d5["time"], unit="s")
T5 = d5["t"].to_numpy(); H5 = d5.high.to_numpy(float)
L5 = d5.low.to_numpy(float); C5 = d5.close.to_numpy(float)
pc = d5.close.shift(1)
atr5 = pd.concat([d5.high-d5.low, (d5.high-pc).abs(),
                  (d5.low-pc).abs()], axis=1).max(axis=1).rolling(14).mean().to_numpy()
FAV, ADV = TP_PTS + SPREAD, SL_PTS - SPREAD

su = pd.read_csv(r"C:\Projects\KinoliveLines\study\setups.csv", parse_dates=["time"])
su = su[su.time >= d5.t.min()].reset_index(drop=True)
idx = np.searchsorted(T5, su["time"].to_numpy(), side="left")

# funding, joined by hour - the one non-price input available for the whole span
fh = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "recorder", "data", "hist_BTC_PERPETUAL.csv"))
fv = fh["interest_1h"].to_numpy(float)
frank = np.full(len(fv), np.nan)
win = np.lib.stride_tricks.sliding_window_view(fv, 720)[:-1]
frank[720:] = (win < fv[720:, None]).mean(axis=1)
f_ms = fh["ts"].to_numpy() + 3600_000

recs, busy = [], -1
for k, i0 in enumerate(idx):
    if i0 <= busy or i0 >= len(C5) - MAX_BARS - 1 or i0 < 300:
        continue
    side = 1 if rng.random() < 0.5 else -1
    b0 = C5[i0]
    tp, sl = b0 + side*FAV, b0 - side*ADV
    out = None
    for j in range(i0+1, i0+1+MAX_BARS):
        ht = (H5[j] >= tp) if side > 0 else (L5[j] <= tp)
        hs = (L5[j] <= sl) if side > 0 else (H5[j] >= sl)
        if ht and hs: out = "ambig"; break
        if hs: out = "loss"; break
        if ht: out = "win"; break
    busy = i0 + MAX_BARS
    if out not in ("win", "loss"):
        continue                                   # decided trades only
    ts = pd.Timestamp(T5[i0])
    ms = np.datetime64(ts).astype("datetime64[ms]").astype(np.int64)
    fj = np.searchsorted(f_ms, ms, side="right") - 1
    recs.append({
        "win": 1 if out == "win" else 0,
        "hour": ts.hour, "dow": ts.dayofweek,
        "atr": atr5[i0],
        "tf": su["tf"].iloc[k], "isHigh": bool(su["isHigh"].iloc[k]),
        "dist": abs(su["mid"].iloc[k] - su["level"].iloc[k]) / max(su["atr15"].iloc[k], 1e-9),
        "prior1h": (C5[i0] - C5[i0-12]) / max(atr5[i0], 1e-9),
        "prior4h": (C5[i0] - C5[i0-48]) / max(atr5[i0], 1e-9),
        "frank": frank[fj] if 0 <= fj < len(frank) else np.nan,
        "side": side,
    })

df = pd.DataFrame(recs)
n = len(df)
base = df["win"].mean()
print("DECIDED trades: %d   overall win rate %.1f%%   breakeven needs %.1f%%\n"
      % (n, 100*base, 100*BREAKEVEN))

def show(title, groups):
    print("=" * 84)
    print(title)
    print("  %-26s %7s %8s %8s   %s" % ("bucket", "n", "win%", "2SE", "verdict"))
    print("  " + "-" * 74)
    for lab, mask in groups:
        v = df[mask]
        if len(v) < 60:
            print("  %-26s %7d   too few" % (lab, len(v))); continue
        p = v["win"].mean()
        se2 = 2*math.sqrt(p*(1-p)/len(v))
        far = abs(p - 0.5) > se2
        econ = p > BREAKEVEN or p < (1-BREAKEVEN)
        verd = ("TRADEABLE" if econ else
                "imbalanced but unprofitable" if far else "balanced")
        print("  %-26s %7d %7.1f%% %7.1f%%   %s" % (lab, len(v), 100*p, 100*se2, verd))

q = lambda c, k: pd.qcut(df[c], k, labels=False, duplicates="drop")
show("BY HOUR (UTC)", [("%02d:00-%02d:59" % (h, h+3), df["hour"].between(h, h+3))
                       for h in range(0, 24, 4)])
show("BY WEEKDAY", [(d, df["dow"] == i) for i, d in
                    enumerate(["Mon","Tue","Wed","Thu","Fri","Sat","Sun"])])
show("BY VOLATILITY (ATR-M5 quintile)", [("Q%d" % (i+1), q("atr",5) == i) for i in range(5)])
show("BY LEVEL TIMEFRAME", [(t, df["tf"] == t) for t in df["tf"].unique()])
show("BY LEVEL TYPE", [("resistance", df["isHigh"]), ("support", ~df["isHigh"])])
show("BY DISTANCE TO LEVEL", [("Q%d" % (i+1), q("dist",4) == i) for i in range(4)])
show("BY PRIOR 1H MOVE", [("Q%d (down..up)" % (i+1), q("prior1h",5) == i) for i in range(5)])
show("BY PRIOR 4H MOVE", [("Q%d (down..up)" % (i+1), q("prior4h",5) == i) for i in range(5)])
show("BY FUNDING RANK", [("bottom 20%", df["frank"] <= .2),
                         ("middle", df["frank"].between(.2,.8)),
                         ("top 20%", df["frank"] >= .8)])
show("BY TRADE SIDE", [("long", df["side"] == 1), ("short", df["side"] == -1)])

print("""
=== HOW TO READ IT ===
"balanced" means the barrier touched first is a coin flip - no information.
"imbalanced but unprofitable" means real information that still loses money at 1:2,
flipped or not; it needs 66.7% or under 33.3% to pay.
Roughly 40 buckets are tested here, so one or two crossing 2SE is expected by chance.
A candidate worth anything must be TRADEABLE, hold on a second instrument or period,
and survive being re-tested out of sample.""")
