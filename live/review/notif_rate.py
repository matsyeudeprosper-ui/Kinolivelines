"""How many notifications would this actually send per day? Replay the
production engine over the recent history and count."""
import sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import structure_bos_bot as B
assert mt5.initialize(path=B.TERMINAL, login=B.LOGIN, password=B.PASSWORD,
                      server=B.SERVER, timeout=60000), mt5.last_error()
R = mt5.copy_rates_from_pos(B.SYMBOL, mt5.TIMEFRAME_M1, 0, 20000)
mt5.shutdown()
eng = B.Struct()
prev = 0
last_ch = 0
flips = bos = choch = 0
for r in R:
    sig = eng.step(int(r["time"]), float(r["open"]), float(r["high"]),
                   float(r["low"]), float(r["close"]))
    if eng.choch != 0 and eng.choch != last_ch:
        choch += 1
    last_ch = eng.choch
    if eng.trend != prev and eng.trend != 0:
        flips += 1
    prev = eng.trend
    if sig:
        bos += 1
days = (int(R[-1]["time"]) - int(R[0]["time"])) / 86400
print(f"{len(R)} minutes = {days:.1f} jours\n")
print(f"  {'evenement':<12s} {'total':>6s} {'par jour':>9s}")
for name, n in (("CHoCH", choch), ("FLIP", flips), ("BOS", bos)):
    print(f"  {name:<12s} {n:6d} {n/days:9.1f}")
print(f"\n  total des notifications : {(choch+flips+bos)/days:.1f} par jour")
