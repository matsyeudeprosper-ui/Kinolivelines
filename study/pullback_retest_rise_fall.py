"""For each Swing Reclaim entry: how far does price rise (peak favorable
move) before it turns and falls back? Window 72h (matches earlier table).
For each trade: find the peak, note how many hours it took to get there,
then measure how much it gave back from that peak by the end of the window,
and whether it ever fell all the way back to (or below) the entry price."""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
WINDOW = 72

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
N = len(c)


def signals_pullback_retest():
    sigs = {}; ao = ac = float(o[0]); d = 0
    last_high = None; last_low = None
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                if d == -1:
                    last_low = ac
                base = ao if d == -1 else ac; ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                if d == 1:
                    last_high = ac
                base = ao if d == 1 else ac; ao, ac, d = base, base - B, -1
            else:
                break
        if last_high is not None and h[i] >= last_high:
            sigs.setdefault(i, 1); last_high = None
        if last_low is not None and l[i] <= last_low:
            sigs.setdefault(i, -1); last_low = None
    return sigs


sigs = signals_pullback_retest()
peak_pts = []; hrs_to_peak = []; giveback_pts = []; back_to_entry = []; usd_peak = []; usd_giveback = []

for j, dirn in sigs.items():
    if j + 1 >= N:
        continue
    ent_bar = j + 1
    SP = c[j] * SPCT
    L = (dirn == 1)
    entry = o[ent_bar] + SP if L else o[ent_bar]
    end = min(N, ent_bar + WINDOW)
    best = 0.0; best_k = ent_bar
    hit_entry_after_peak = False
    for k in range(ent_bar, end):
        fav = (h[k] - entry) if L else (entry - l[k])
        if fav > best:
            best = fav; best_k = k
        # after the peak bar, check if price fell back to/below entry
        if k > best_k:
            adv = (c[k] - entry) if L else (entry - c[k])
            if adv <= 0:
                hit_entry_after_peak = True
    # giveback = peak minus wherever price closed at window end
    final_adv = (c[end-1] - entry) if L else (entry - c[end-1])
    giveback = best - final_adv
    peak_pts.append(best); hrs_to_peak.append(best_k - ent_bar)
    giveback_pts.append(giveback); back_to_entry.append(hit_entry_after_peak)
    usd_peak.append(best*PT); usd_giveback.append(giveback*PT)

peak_pts = np.array(peak_pts); hrs_to_peak = np.array(hrs_to_peak)
giveback_pts = np.array(giveback_pts); back_to_entry = np.array(back_to_entry)
usd_peak = np.array(usd_peak); usd_giveback = np.array(usd_giveback)

print(f"n = {len(peak_pts)} entries, window {WINDOW}h\n")
print("THE RISE (peak favorable move before it turns):")
print(f"  average peak   {peak_pts.mean():7.1f} pts  (${usd_peak.mean():6.2f})")
print(f"  median peak    {np.median(peak_pts):7.1f} pts  (${np.median(usd_peak):6.2f})")
print(f"  average time to reach the peak: {hrs_to_peak.mean():5.1f} hours  (median {np.median(hrs_to_peak):.0f}h)")
print()
print("THE FALL (giveback from that peak, by 72h later):")
print(f"  average giveback  {giveback_pts.mean():7.1f} pts  (${usd_giveback.mean():6.2f})")
print(f"  median giveback   {np.median(giveback_pts):7.1f} pts  (${np.median(usd_giveback):6.2f})")
print(f"  giveback as a share of the peak: {100*giveback_pts.mean()/peak_pts.mean():.0f}%")
print(f"  trades that fell ALL THE WAY back to entry (or worse) after peaking: {100*back_to_entry.mean():.1f}%")
