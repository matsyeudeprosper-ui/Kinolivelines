"""If the current setup loses consistently, does trading the opposite side win?

The intuition is reasonable and worth measuring. The reason it usually fails is
geometry, not philosophy:

    a long with stop -0.8R and target +1.5R gets stopped when price falls 0.8R
    its mirror short has target -1.5R and stop +0.8R
    price falling 0.8R takes the short only HALF WAY to its target
    price can then turn and stop the short out too

So the mirror of a loss is most often a TIMEOUT, not a win. Both sides pay the spread.
Whether that dominates is an empirical question, answered here two ways:

  1 the 20 real trades of the current config, re-simulated with sides flipped and
    barriers mirrored, walking actual M5 bars from each entry
  2 the properly powered version, which already exists: sim_variants.py ran the same
    5,892 reconstructed setups under BOTH direction conventions, fade and follow,
    which is precisely the inversion at 3,400 trades per side instead of 20

Barriers are reconstructed per trade: the stop distance is taken from the actual stop
price in exit_reason where the trade was stopped, and otherwise from the rulebook
(0.8 x ATR-M15 at entry). Target is 1.5R of that stop, per rule 6.
"""
import csv, os, math
from datetime import datetime, timedelta
import numpy as np
import MetaTrader5 as mt5

J = r"C:\Projects\KinoliveLines\live\trades_journal.csv"
SYM = "BTCUSDm"
RR = 1.5

rows = []
with open(J, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r.get("instrumentation") == "True":
            continue                      # never count measurement artefacts
        if r["opened"][:10] < "2026-07-30":
            continue                      # current config only
        try:
            r["pnl"] = float(r["pnl"])
            r["entry"] = float(r["entry"])
            r["atr15"] = float(r["M15_atr"]) if r.get("M15_atr") else None
            rows.append(r)
        except (ValueError, TypeError):
            pass

print("CURRENT CONFIG, real trades only: %d" % len(rows))
orig_net = sum(r["pnl"] for r in rows)
orig_win = sum(1 for r in rows if r["pnl"] > 0)
print("  as traded: %d wins (%.0f%%), net %+.2f\n" % (orig_win, 100*orig_win/len(rows), orig_net))

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select(SYM, True)
tick = mt5.symbol_info_tick(SYM)
SPREAD = tick.ask - tick.bid
m5 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 0, 60000)
mt5.shutdown()
import pandas as pd
d5 = pd.DataFrame(m5)
d5["t"] = pd.to_datetime(d5["time"], unit="s")
T = d5["t"].to_numpy()
H, L = d5["high"].to_numpy(float), d5["low"].to_numpy(float)


def stop_distance(r):
    """From the real stop price where available, else the rulebook 0.8x ATR-M15."""
    e = (r.get("exit_reason") or "")
    if e.startswith("[sl"):
        try:
            return abs(r["entry"] - float(e.strip("[]").split()[1]))
        except (ValueError, IndexError):
            pass
    return 0.8 * r["atr15"] if r["atr15"] else None


# The inverse must run under the SAME time limit as the trade it mirrors. The first
# version of this allowed 24 hours against the live max_hold_minutes of 120, which
# handed the inverse four times the opportunity to reach its target and inflated its
# win rate. A mirror test that gives one side more time is not a mirror test.
MAXBARS = 120 // 5         # 120 minutes of M5 bars, matching watch_config max_hold
res = {"win": 0, "loss": 0, "timeout": 0}
pnls = []
print("%-20s %-5s %8s %9s %9s  %s"
      % ("entry time", "side", "stop", "target", "orig pnl", "INVERTED outcome"))
print("-" * 88)
for r in rows:
    sd = stop_distance(r)
    if not sd or sd <= 0:
        continue
    t0 = pd.Timestamp(r["opened"])
    i0 = int(np.searchsorted(T, np.datetime64(t0), side="left"))
    if i0 >= len(T) - 2:
        continue
    inv_side = -1 if r["side"] == "BUY" else 1          # flip
    e = r["entry"] + inv_side * SPREAD / 2              # pay the spread again
    tgt = e + inv_side * sd * RR
    stp = e - inv_side * sd
    out = "timeout"
    for k in range(1, MAXBARS + 1):
        j = i0 + k
        if j >= len(H):
            break
        hs = (L[j] <= stp) if inv_side > 0 else (H[j] >= stp)
        ht = (H[j] >= tgt) if inv_side > 0 else (L[j] <= tgt)
        if hs:                       # stop checked first: ambiguous bar counts against
            out = "loss"; break
        if ht:
            out = "win"; break
    res[out] += 1
    pnls.append(RR * 0.01 * sd if out == "win" else
                -1.0 * 0.01 * sd if out == "loss" else 0.0)
    print("%-20s %-5s %8.1f %9.1f %9.2f  %s"
          % (r["opened"][:19], "SELL" if inv_side < 0 else "BUY", sd, sd*RR, r["pnl"], out.upper()))

n = sum(res.values())
print("-" * 88)
print("INVERTED: %d wins, %d losses, %d timeouts (n=%d)   net %+.2f"
      % (res["win"], res["loss"], res["timeout"], n, sum(pnls)))
print("  original net %+.2f   inverted net %+.2f" % (orig_net, sum(pnls)))
print("""
NOTE ON POWER: n is about twenty. Twenty trades cannot establish an edge in either
direction, and this is the sample that produced the misleading numbers earlier today.

The powered answer already exists. sim_variants.py ran the SAME 5,892 reconstructed
setups under both direction conventions - fade and follow - which is exactly this
inversion at roughly 3,400 trades per side:

    fade   development -88.79%   holdout -23.82%
    follow development -42.27%   holdout -43.45%

Both lose heavily. Inverting the side does not rescue it, because the spread is paid
whichever way round the trade is placed and the mirror of a stop-out is usually a
timeout rather than a target.""")
