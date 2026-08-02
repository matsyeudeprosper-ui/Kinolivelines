"""Backtest: random direction at the hlines, TP = the fee, SL = 2x TP, $500 account.

Requested parameters, taken literally:
    entry        random side, at the hline setups the daemon would genuinely wake for
    TP           just large enough to cover the fee - $0.10 at 0.01 lots, i.e. 10 points
    SL           twice the TP - 20 points, $0.20
    balance      $500 starting, 0.01 lots fixed
    cost         the real Exness BTCUSDm spread, which at 0.01 lots IS the $0.10 fee
    reporting    win rate, profit and drawdown per day, week and month

WHAT THE SPREAD DOES TO THESE BARRIERS - this is the whole result, so it is worth
stating before the numbers.

A long is entered at ASK and its stop and target trigger on BID, one spread lower. With
a $10 spread on a bid-quoted chart:

    entry ask   = bid + 10
    TP at entry + 10  =>  bid must reach  bid_0 + 20
    SL at entry - 20  =>  bid must reach  bid_0 - 10

A short is the mirror and lands in exactly the same place. So in the price series the
favourable barrier is TWENTY points away and the adverse one is TEN. Price has to travel
twice as far to win as to lose, and the payoff is +$0.10 against -$0.20.

For a driftless random walk the chance of touching +20 before -10 is 10/30 = 33%, while
breaking even at 1:2 payoff needs 67%. That is the arithmetic; the simulation below is
whether the real series behaves differently.

THE MEASUREMENT PROBLEM, stated honestly: 10 and 20-point barriers are far smaller than
a typical M5 bar range on BTCUSDm, so many bars span BOTH. Bar data cannot say which was
touched first. Every figure is therefore reported under all three tie conventions and
the tie rate is printed - if the sign depends on the convention, bar data cannot answer
this question and only tick data could.
"""
import os, csv, math, random
import numpy as np, pandas as pd
import MetaTrader5 as mt5

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYM = "BTCUSDm"
BAL0, LOTS = 500.0, 0.01
MAX_BARS = 24                        # 2 hours of M5, matching live max_hold
rng = random.Random(8080)

# TP, SL and an optional spread override, from the command line so any variant can be
# tried without editing the file:
#     python backtest_tight_2to1.py 10 30       TP 10, SL 30, real live spread
#     python backtest_tight_2to1.py 10 30 0     the same with the spread set to zero
#
# The zero-spread case is not a tradeable scenario - no broker quotes both sides at the
# same price - but it isolates what the cost is actually doing, which is the only way to
# see whether a barrier arrangement has any merit of its own.
import sys
TP_PTS = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
SL_PTS = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
SPREAD_OVERRIDE = float(sys.argv[3]) if len(sys.argv) > 3 else None

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select(SYM, True)
tick = mt5.symbol_info_tick(SYM)
info = mt5.symbol_info(SYM)
SPREAD = tick.ask - tick.bid if SPREAD_OVERRIDE is None else SPREAD_OVERRIDE
# MT5 returns nothing rather than a short series when the request is too large, and
# the ceiling moves. Step down until something comes back.
r5 = None
for want in (200000, 120000, 60000, 30000):
    r5 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 0, want)
    if r5 is not None and len(r5):
        break
mt5.shutdown()
if r5 is None or not len(r5):
    raise SystemExit("no M5 data returned")

d5 = pd.DataFrame(r5)
d5["t"] = pd.to_datetime(d5["time"], unit="s")
T5 = d5["t"].to_numpy()
H5, L5, C5 = (d5[c].to_numpy(float) for c in ("high", "low", "close"))
print("M5 history: %s bars, %s -> %s   live spread $%.2f, $%.2f at %.2f lots"
      % (f"{len(d5):,}", d5.t.min().date(), d5.t.max().date(), SPREAD, SPREAD * LOTS, LOTS))

# barriers in BID terms, identical for both sides once the spread is applied
FAV, ADV = TP_PTS + SPREAD, SL_PTS - SPREAD
if ADV <= 0:
    raise SystemExit("SL of %.0f pts is inside the %.0f spread - unplaceable" % (SL_PTS, SPREAD))
p_rw = ADV / (FAV + ADV)             # random-walk chance of touching FAV before ADV
ev = p_rw * TP_PTS * LOTS - (1 - p_rw) * SL_PTS * LOTS
print("TP %.0f pts ($%.2f)   SL %.0f pts ($%.2f)   ratio 1:%.1f"
      % (TP_PTS, TP_PTS * LOTS, SL_PTS, SL_PTS * LOTS, SL_PTS / TP_PTS))
print("in bid terms: favourable barrier %.0f pts away, adverse %.0f pts away" % (FAV, ADV))
print("breakeven win rate %.0f%%   random-walk win rate %.0f%%   theoretical EV $%+.3f/trade\n"
      % (100 * SL_PTS / (SL_PTS + TP_PTS), 100 * p_rw, ev))

setups = pd.read_csv(os.path.join(BASE, "study", "setups.csv"), parse_dates=["time"])
setups = setups[setups.time >= d5.t.min()].reset_index(drop=True)
print("hline setups inside the M5 window: %s" % f"{len(setups):,}")

idx = np.searchsorted(T5, setups["time"].to_numpy(), side="left")

WIN, LOSS = TP_PTS * LOTS, -SL_PTS * LOTS
trades = {k: [] for k in ("split", "loss", "win")}
durations = []
ties = 0
busy = -1
for k, i0 in enumerate(idx):
    if i0 <= busy or i0 >= len(C5) - MAX_BARS - 1:
        continue
    side = 1 if rng.random() < 0.5 else -1          # RANDOM direction
    b0 = C5[i0]
    tp = b0 + side * FAV
    sl = b0 - side * ADV
    out = None
    for j in range(i0 + 1, i0 + 1 + MAX_BARS):
        hit_t = (H5[j] >= tp) if side > 0 else (L5[j] <= tp)
        hit_s = (L5[j] <= sl) if side > 0 else (H5[j] >= sl)
        if hit_t and hit_s:
            out = "tie"; break
        if hit_s:
            out = "loss"; break
        if hit_t:
            out = "win"; break
        busy_j = j
    when = T5[min(i0 + 1, len(T5) - 1)]
    if out is None:                                  # timed out - settle at the close
        v = side * (C5[min(i0 + MAX_BARS, len(C5) - 1)] - b0) * LOTS
        v = max(min(v, WIN), LOSS)
        for c in trades: trades[c].append((when, v))
    elif out == "tie":
        ties += 1
        trades["split"].append((when, (WIN + LOSS) / 2))
        trades["loss"].append((when, LOSS))
        trades["win"].append((when, WIN))
    else:
        v = WIN if out == "win" else LOSS
        for c in trades: trades[c].append((when, v))
    durations.append(min(j - i0, MAX_BARS) if out else MAX_BARS)
    busy = i0 + MAX_BARS

n = len(trades["split"])
print("trades taken (one at a time, non-overlapping): %s   ambiguous bars: %d (%.1f%%)"
      % (f"{n:,}", ties, 100 * ties / max(n, 1)))
# How long trades occupy the single position slot decides how many fit in a day.
if durations:
    dmin = np.array(durations) * 5.0
    print("hold time: mean %.0f min, median %.0f min, %.0f%% ran to the %d-min cap"
          % (dmin.mean(), np.median(dmin), 100*(dmin >= MAX_BARS*5).mean(), MAX_BARS*5))
    print("           -> at most %.1f trades/day can fit through one position slot\n"
          % (24 * 60 / max(dmin.mean(), 1)))


def report(pairs, label):
    df = pd.DataFrame(pairs, columns=["t", "pnl"]).set_index("t").sort_index()
    eq = BAL0 + df["pnl"].cumsum()
    peak = eq.cummax()
    dd = (eq - peak)
    wins = (df["pnl"] > 0).sum()
    print("=" * 92)
    print("%s   %d trades   win rate %.1f%%   net %+.2f   final balance %.2f"
          % (label, len(df), 100 * wins / len(df), df["pnl"].sum(), eq.iloc[-1]))
    print("   max drawdown %.2f USD (%.1f%% of starting balance)"
          % (dd.min(), abs(dd.min()) / BAL0 * 100))
    for freq, name in (("D", "PER DAY"), ("W", "PER WEEK"), ("ME", "PER MONTH")):
        g = df["pnl"].resample(freq)
        agg = pd.DataFrame({"trades": g.count(), "profit": g.sum(),
                            "wins": df["pnl"].gt(0).resample(freq).sum()})
        agg = agg[agg["trades"] > 0]
        if agg.empty:
            continue
        agg["win%"] = 100 * agg["wins"] / agg["trades"]
        # drawdown within each period
        ddp = []
        for per, sub in df["pnl"].groupby(pd.Grouper(freq=freq)):
            if len(sub) == 0:
                continue
            e = sub.cumsum()
            ddp.append((e - e.cummax()).min())
        agg["maxDD"] = ddp
        print("\n   %s  (%d periods)" % (name, len(agg)))
        print("     %-12s %7s %8s %7s %9s" % ("", "trades", "profit", "win%", "maxDD"))
        print("     mean         %7.1f %8.3f %7.1f %9.3f"
              % (agg["trades"].mean(), agg["profit"].mean(),
                 agg["win%"].mean(), agg["maxDD"].mean()))
        print("     best         %7.0f %8.3f %7.1f %9.3f"
              % (agg["trades"].max(), agg["profit"].max(),
                 agg["win%"].max(), agg["maxDD"].max()))
        print("     worst        %7.0f %8.3f %7.1f %9.3f"
              % (agg["trades"].min(), agg["profit"].min(),
                 agg["win%"].min(), agg["maxDD"].min()))
        print("     profitable periods: %d of %d (%.0f%%)"
              % ((agg["profit"] > 0).sum(), len(agg), 100*(agg["profit"] > 0).mean()))


for conv, label in (("split", "TIE -> SPLIT (neutral convention)"),
                    ("loss", "TIE -> LOSS (conservative)"),
                    ("win", "TIE -> WIN (optimistic)")):
    report(trades[conv], label)

print("""
=== READ THIS BEFORE THE NUMBERS ===
Check whether the sign of 'net' is the same under all three tie conventions. Where the
ambiguous-bar rate is high, bar data genuinely cannot tell which barrier was touched
first, and only the conventions agreeing makes the answer trustworthy.

The structural point stands regardless of the data: with a $10 spread, a 10-point target
and a 20-point stop put the favourable barrier twice as far away as the adverse one
while paying half as much. That needs a 67% win rate to break even against roughly 33%
available from a random walk.""")

