"""Simulate the PROPOSED recovery bank over the same real trades.
Only the LOT changes, never the stop or target, so a trade's P&L scales
linearly with lot size - the owner's own constraint makes this exact."""
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
BASE, STEP, LMAX = M.BASE_LOT, 0.01, 0.10
RR = 0.8

def run(skim, stake_frac, cap_mult, label):
    banked = peak = bank = 0.0
    armed = attempts = 0
    for d in closes:
        vol = max(d.volume, 0.01)
        unit = (d.profit + d.swap + d.commission) / vol      # P&L per lot
        debt = max(0.0, peak - banked)
        # ---- size this trade
        lot, extra = BASE, 0.0
        if debt > 0.5 and bank > 0.5:
            risk_per_lot = abs(unit) if unit < 0 else abs(unit) / RR
            if risk_per_lot > 0:
                budget = bank * stake_frac
                want = budget / risk_per_lot
                need = debt / (RR * risk_per_lot)            # enough to clear
                extra = min(want, max(0.0, need - BASE), LMAX - BASE)
                extra = int(extra / STEP) * STEP
        if extra > 0:
            lot = round(BASE + extra, 2); attempts += 1
        if bank >= 1.0 and debt > 0.5:
            armed += 1
        pnl = unit * lot
        # ---- book it
        if pnl > 0:
            bank += skim * pnl
        else:
            bank = max(0.0, bank + unit * extra)             # the bank's stake
        bank = min(bank, max(cap_mult * max(debt, 1.0), 10.0))
        banked = round(banked + pnl, 2)
        peak = max(peak, banked)
    debt = round(max(0.0, peak - banked), 2)
    print(f"  {label:<34s} net ${banked:8.2f}  sommet ${peak:6.2f}  "
          f"dette ${debt:6.2f}  banque ${bank:5.2f}  "
          f"armes {armed:3d}/{len(closes)}  tentatives {attempts:3d}")

print(f"{len(closes)} trades reels, lot de base {BASE}\n")
print("  ACTUEL (coffre alimente seulement sur un nouveau sommet) :")
run(0.0, 0.0, 0.0, "coffre starve")
print("\n  PROPOSE (banque alimentee par CHAQUE gain) :")
for sk in (0.25, 0.40, 0.50):
    run(sk, 0.50, 0.5, f"skim {sk:.0%}, mise 50% de la banque")
print("\n  sensibilite a la mise par tentative (skim 40%) :")
for st in (0.25, 0.50, 1.00):
    run(0.40, st, 0.5, f"mise {st:.0%} de la banque")
