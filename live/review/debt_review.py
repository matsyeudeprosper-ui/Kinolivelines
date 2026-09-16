"""Replay the CURRENT debt system over the real closed trades and measure
whether the war chest ever had ammunition while in debt. Read-only."""
import sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_manual_trader as M

assert mt5.initialize(path=M.TERMINAL, login=M.LOGIN, password=M.PASSWORD,
                      server=M.SERVER, timeout=60000), mt5.last_error()
ds = mt5.history_deals_get(M.ERA_START,
                           dt.datetime.utcnow() + dt.timedelta(days=1)) or []
closes = sorted([d for d in ds if d.entry == 1 and d.symbol == M.SYMBOL],
                key=lambda d: d.time)
mt5.shutdown()

banked = peak = chest = 0.0
in_debt = armed = 0
wins = losses = 0
win_sum = loss_sum = 0.0
chest_while_debt = []
for d in closes:
    pnl = d.profit + d.swap + d.commission
    if pnl > 0: wins += 1; win_sum += pnl
    else: losses += 1; loss_sum += -pnl
    debt_before = round(max(0.0, peak - banked), 2)
    if debt_before > 0.5:
        in_debt += 1
        chest_while_debt.append(chest)
        if chest >= 1.0: armed += 1
    banked = round(banked + pnl, 2)
    if pnl < 0 and d.volume > M.BASE_LOT + 0.001:
        chest = round(max(0.0, chest + pnl * (1.0 - M.BASE_LOT / d.volume)), 2)
    if banked > peak:
        chest = round(min(M.CHEST_CAP, chest + banked - peak), 2)
        peak = banked
debt = round(max(0.0, peak - banked), 2)

print(f"{len(closes)} trades clotures depuis {M.ERA_START:%Y-%m-%d}")
print(f"  gains {wins} (+${win_sum:.2f})   pertes {losses} (-${loss_sum:.2f})")
print(f"  net ${banked:.2f}   sommet ${peak:.2f}   DETTE ${debt:.2f}   "
      f"coffre ${chest:.2f}")
print()
print(f"  trades pris ALORS QUE la dette etait ouverte : {in_debt}")
print(f"  ... dont avec au moins $1 dans le coffre     : {armed} "
      f"({armed/max(in_debt,1):.0%})")
if chest_while_debt:
    cw = sorted(chest_while_debt)
    print(f"  coffre median pendant la dette : ${cw[len(cw)//2]:.2f}   "
          f"max ${max(cw):.2f}")
print()
print("  regle actuelle : le coffre ne grossit QUE sur un nouveau sommet")
print("  -> pendant une dette, banked < peak, donc il ne grossit jamais")
