"""Same recovery bank, but only ARMED when the recent record justifies it."""
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
BASE, STEP, LMAX, RR = M.BASE_LOT, 0.01, 0.10, 0.8

def run(skim, stake, window, label):
    banked = peak = bank = 0.0
    hist = []; attempts = 0
    for d in closes:
        vol = max(d.volume, 0.01)
        unit = (d.profit + d.swap + d.commission) / vol
        debt = max(0.0, peak - banked)
        gate = True
        if window:
            gate = len(hist) >= window and sum(hist[-window:]) > 0
        lot, extra = BASE, 0.0
        if gate and debt > 0.5 and bank > 0.5:
            rpl = abs(unit) if unit < 0 else abs(unit) / RR
            if rpl > 0:
                extra = min(bank * stake / rpl,
                            max(0.0, debt / (RR * rpl) - BASE), LMAX - BASE)
                extra = int(extra / STEP) * STEP
        if extra > 0:
            lot = round(BASE + extra, 2); attempts += 1
        pnl = unit * lot
        hist.append(unit * BASE)          # judge the EDGE at base size
        if pnl > 0: bank += skim * pnl
        else: bank = max(0.0, bank + unit * extra)
        bank = min(bank, max(0.5 * max(debt, 1.0), 10.0))
        banked = round(banked + pnl, 2); peak = max(peak, banked)
    print(f"  {label:<40s} net ${banked:8.2f}  dette "
          f"${max(0.0,peak-banked):6.2f}  tentatives {attempts:3d}")

print(f"{len(closes)} trades reels\n")
run(0.0, 0.0, None, "lot de base fixe, aucune recuperation")
run(0.40, 0.50, None, "banque active en permanence")
for w in (10, 20, 30):
    run(0.40, 0.50, w, f"banque armee seulement si {w} derniers > 0")
