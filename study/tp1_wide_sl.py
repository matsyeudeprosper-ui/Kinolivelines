"""User's idea: same live-bot entry (every reversal brick, A0), but:
  - TP = $1 (100 points at 0.01 lots)
  - SL = the worst adverse move ever observed in this backtest, plus a buffer
  - single position per signal (no recovery/cap basket)
  - no daily loss limit
Step 1: measure the true worst-case adverse excursion, unconstrained, across
every A0 signal over the full 4.6 years, to derive the SL size.
Step 2: run the actual TP/SL strategy with that SL and report results.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
TP_USD = 1.0
TP_PTS = TP_USD / PT
CALIBRATE_WINDOW = 2000  # hours, generous, to find the true worst case

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
N = len(c)


def signals_reversal():
    revs = {}; ao = ac = float(o[0]); d = 0; pd_ = 0
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                base = ao if d == -1 else ac; ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                base = ao if d == 1 else ac; ao, ac, d = base, base - B, -1
            else:
                break
            if pd_ and d != pd_:
                revs.setdefault(i, d)
            pd_ = d
    return revs


sigs = signals_reversal()

# ---- Step 1: calibrate SL from worst-ever unconstrained adverse move ----
worst = 0.0; worst_j = None
for j, dirn in sigs.items():
    if j + 1 >= N:
        continue
    ent_bar = j + 1
    SP = c[j] * SPCT
    L = (dirn == 1)
    entry = o[ent_bar] + SP if L else o[ent_bar]
    end = min(N, ent_bar + CALIBRATE_WINDOW)
    for k in range(ent_bar, end):
        adv = (entry - l[k]) if L else (h[k] - entry)
        if adv > worst:
            worst = adv; worst_j = j

BUFFER_MULT = 1.25  # 25% extra buffer on top of the worst ever seen
SL_PTS = worst * BUFFER_MULT
SL_USD = SL_PTS * PT
print(f"worst-ever adverse move observed (unconstrained, {CALIBRATE_WINDOW}h window): "
      f"{worst:.1f} pts (${worst*PT:.2f})  at signal {worst_j}")
print(f"SL with {int((BUFFER_MULT-1)*100)}% buffer: {SL_PTS:.1f} pts (${SL_USD:.2f})")
print(f"TP: {TP_PTS:.0f} pts (${TP_USD:.2f})")
print()

# ---- Step 2: run the actual TP/SL strategy, single position, no basket, no daily limit ----
PT_ = PT
bal = 1000.0
peak = bal; mdd = 0.0; lo = bal
wins = 0; losses = 0; open_at_end = 0
pnl_list = []
j2 = 0
sig_keys = sorted(sigs.keys())
i_sig = 0
in_pos = False
pos_L = None; pos_entry = None; pos_end_cap = None
skipped_busy = 0
n_sig_total = 0

# walk bar by bar so only one position is open at a time (skip signals while in a position)
pending = None
for j in range(N):
    if pending is not None:
        L, entry = pending
        in_pos = True; pos_L = L; pos_entry = entry; pending = None
    if j in sigs and j + 1 < N:
        n_sig_total += 1
        if not in_pos:
            L = (sigs[j] == 1)
            SP = c[j] * SPCT
            entry = o[j+1] + SP if L else o[j+1]
            pending = (L, entry)
        else:
            skipped_busy += 1
    if in_pos:
        tp_price = pos_entry + TP_PTS if pos_L else pos_entry - TP_PTS
        sl_price = pos_entry - SL_PTS if pos_L else pos_entry + SL_PTS
        hit_tp = (h[j] >= tp_price) if pos_L else (l[j] <= tp_price)
        hit_sl = (l[j] <= sl_price) if pos_L else (h[j] >= sl_price)
        if hit_tp and hit_sl:
            # ambiguous same-bar - conservative: assume SL first (worst case)
            bal -= SL_PTS * PT_; pnl_list.append(-SL_PTS*PT_); losses += 1; in_pos = False
        elif hit_tp:
            bal += TP_PTS * PT_; pnl_list.append(TP_PTS*PT_); wins += 1; in_pos = False
        elif hit_sl:
            bal -= SL_PTS * PT_; pnl_list.append(-SL_PTS*PT_); losses += 1; in_pos = False
    peak = max(peak, bal); mdd = max(mdd, peak-bal); lo = min(lo, bal)

if in_pos:
    open_at_end = 1

pnl = np.array(pnl_list)
print(f"signals: {n_sig_total}   trades opened: {len(pnl)}   skipped (already in a position): {skipped_busy}   still open at end: {open_at_end}")
print(f"wins: {wins} ({100*wins/max(1,len(pnl)):.1f}%)   losses: {losses} ({100*losses/max(1,len(pnl)):.1f}%)")
print(f"\nended: ${bal:,.2f} (from $1,000, {100*(bal/1000-1):+.1f}%)")
print(f"lowest equity: ${lo:,.2f}   worst drawdown: ${mdd:,.2f} ({100*mdd/peak:.1f}% from peak)")
print(f"expectancy per trade: ${pnl.mean():+.3f}")
print(f"math check: win% {100*wins/max(1,len(pnl)):.1f} needs > {100*SL_PTS/(SL_PTS+TP_PTS):.1f}% to break even given this TP:SL ratio")
