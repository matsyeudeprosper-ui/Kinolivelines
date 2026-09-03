"""Mean-reversion-in-chop backtest (2026-09-03, user idea).

Question: during CHOP, does fading the range extremes make money that the
trend-continuation KINO engine loses?

Method:
- Pull M1 history for BTCUSDm.
- Rolling range over N bars (default 60). Regime = CHOP if that range is
  tight (< CHOP_PTS) for the lookback; else TREND (skip - not our test).
- In chop, entries FADE the box:
    price pokes into top TOP_FRAC of the range -> SELL toward the middle
    price pokes into bottom -> BUY toward the middle
  TP = middle of the range; SL = just beyond the box edge (+ buffer).
- One position at a time. Costs: SPREAD_PTS each side.
- BAR-ORDERING TRAP: each M1 bar we don't know if high or low came first.
  Run TWICE: 'optimistic' (assume TP-favourable extreme first) and
  'pessimistic' (assume SL-favourable extreme first). Trust only what is
  green in BOTH.

Reports net, trades, win%, and both-ordering verdict.
"""
import sys
import numpy as np
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

TERMINAL = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
SYMBOL = "BTCUSDm"
N = 60                 # range lookback (minutes)
CHOP_PTS = 900.0       # box tighter than this = chop (~1.1% of price)
TOP_FRAC = 0.15        # poke into top/bottom 15% of the box to fade
BUFFER = 40.0          # SL beyond the edge
SPREAD_PTS = 10.0      # round-trip-ish per side (Standard BTCUSDm truth)
LOT = 0.02
DOLLAR_PER_PT = LOT / 0.01 * 0.01   # 0.02 lot => $0.02 per point... (BTC $1/pt/0.01)
# BTCUSDm: 1.00 price point = $0.01 per 0.01 lot => per 0.02 lot: $0.02/pt
PT_USD = 0.02

BARS = int(sys.argv[1]) if len(sys.argv) > 1 else 200000

mt5.initialize(path=TERMINAL)
rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, BARS)
mt5.shutdown()
if rates is None or len(rates) < N + 100:
    print("no data")
    sys.exit()

hi = np.asarray(rates["high"], float)
lo = np.asarray(rates["low"], float)
op = np.asarray(rates["open"], float)
cl = np.asarray(rates["close"], float)
n = len(cl)
print(f"bars: {n} (~{n/1440:.1f} days)")


def run(order):
    """order='opt' assumes the favourable extreme hits first each bar;
    'pess' assumes the adverse one first."""
    net = 0.0
    trades = wins = 0
    pos = None  # dict: dir, entry, sl, tp
    chop_bars = 0
    for i in range(N, n):
        win_hi = hi[i - N:i].max()
        win_lo = lo[i - N:i].min()
        box = win_hi - win_lo
        is_chop = box < CHOP_PTS
        if is_chop:
            chop_bars += 1
        # manage open position with this bar's range
        if pos is not None:
            hit_tp = lo[i] <= pos["tp"] if pos["dir"] == 1 else hi[i] >= pos["tp"]
            hit_sl = lo[i] <= pos["sl"] if pos["dir"] == -1 else hi[i] >= pos["sl"]
            # note: BUY tp is above? no—mean rev BUY from bottom, tp=middle>entry
            if pos["dir"] == 1:      # BUY (from bottom), tp above, sl below
                hit_tp = hi[i] >= pos["tp"]
                hit_sl = lo[i] <= pos["sl"]
            else:                    # SELL (from top), tp below, sl above
                hit_tp = lo[i] <= pos["tp"]
                hit_sl = hi[i] >= pos["sl"]
            done = None
            if hit_tp and hit_sl:
                done = "tp" if order == "opt" else "sl"
            elif hit_tp:
                done = "tp"
            elif hit_sl:
                done = "sl"
            if done:
                px = pos["tp"] if done == "tp" else pos["sl"]
                pnl = (px - pos["entry"]) * pos["dir"] * PT_USD
                pnl -= SPREAD_PTS * PT_USD
                net += pnl
                trades += 1
                wins += 1 if pnl > 0 else 0
                pos = None
        # new entry only in chop, flat
        if pos is None and is_chop and box > 3 * BUFFER:
            mid = (win_hi + win_lo) / 2
            top_edge = win_hi - TOP_FRAC * box
            bot_edge = win_lo + TOP_FRAC * box
            if cl[i] >= top_edge:          # in top zone -> fade SELL
                pos = {"dir": -1, "entry": cl[i],
                       "tp": mid, "sl": win_hi + BUFFER}
            elif cl[i] <= bot_edge:        # in bottom zone -> fade BUY
                pos = {"dir": 1, "entry": cl[i],
                       "tp": mid, "sl": win_lo - BUFFER}
    return net, trades, wins, chop_bars


for order in ("opt", "pess"):
    net, tr, w, chop = run(order)
    wr = (100.0 * w / tr) if tr else 0
    print(f"[{order:4}] chop-bars {chop} ({100*chop/n:.0f}% of time) | "
          f"trades {tr} | win% {wr:.0f} | net ${net:.2f} "
          f"(${net/(n/1440):.2f}/day)")
print("VERDICT: trust only if BOTH lines are positive.")
