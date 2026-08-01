"""Which instrument has the SHALLOWEST hole to climb out of?

Every test so far hunted for a signal strong enough to beat BTC's spread drag.
That was the wrong question. The random-entry baseline - what you lose knowing
nothing at all - varies six-fold across instruments:

    DE30m   -0.0051      almost breakeven
    BTCUSDm -0.0316      the worst of the six looked at so far

A signal worth half a point of edge is invisible on BTC and tradeable on DE30.
Same signal, different battlefield. So before hunting more signals, find where the
hunting is easiest.

WHAT IS MEASURED: random entry, long AND short, stop 1.0x ATR(H1), target 1.5x,
8-hour hold, the symbol's real live spread. No signal at all - this is the floor
every strategy on that instrument starts from.

DISCIPLINE, learned the hard way tonight:
  * non-overlapping windows only (trap #5 - overlapping ones shrink the error bar
    without adding information and flipped a gold result from negative to positive)
  * tie rate reported, and the estimate shown under all three conventions; a
    symbol whose sign depends on how ambiguous bars are scored is not measurable
    at this resolution (trap #1)
  * spread taken live from the terminal, not assumed
  * symbols where the spread exceeds the stop are flagged UNTRADEABLE rather than
    reported - they return exactly -1.0 stop on every trade and their error bars
    collapse to nothing, which reads as spurious significance
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

STOP_M, TMULT, HOLD = 1.0, 1.5, 8
MIN_BARS = 5000

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
all_syms = mt5.symbols_get()
print("account carries %d symbols" % len(all_syms))

# Screen the liquid, sizeable ones: indices, metals, majors, the big cryptos.
WANT = ("Indices", "Metals", "Forex", "Crypto", "Energies", "Stocks")
cands = [s.name for s in all_syms
         if any(w.lower() in (s.path or "").lower() for w in WANT)]
print("screening %d candidates\n" % len(cands))

rows = []
skipped = {"no data": 0, "untradeable spread": 0, "error": 0}
for name in cands:
    try:
        if not mt5.symbol_select(name, True):
            skipped["no data"] += 1; continue
        tick = mt5.symbol_info_tick(name)
        info = mt5.symbol_info(name)
        if tick is None or info is None or tick.ask <= 0:
            skipped["no data"] += 1; continue
        spread = tick.ask - tick.bid
        r = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H1, 0, 20000)
        if r is None or len(r) < MIN_BARS:
            skipped["no data"] += 1; continue
        d = pd.DataFrame(r)
        pc = d["close"].shift(1)
        d["atr"] = pd.concat([d.high - d.low, (d.high - pc).abs(),
                              (d.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
        d = d.dropna(subset=["atr"]).reset_index(drop=True)
        hi, lo, cl, atr = (d.high.to_numpy(float), d.low.to_numpy(float),
                           d.close.to_numpy(float), d.atr.to_numpy(float))
        med_atr = float(np.nanmedian(atr))
        if med_atr <= 0 or spread >= STOP_M * med_atr * 0.5:
            skipped["untradeable spread"] += 1; continue

        WIN, LOSS = STOP_M * TMULT, -STOP_M
        sp, sl_, sw = [], [], []
        ties = 0
        for i in range(50, len(cl) - HOLD, HOLD):          # NON-OVERLAPPING
            A = atr[i]
            if not np.isfinite(A) or A <= 0:
                continue
            sd, td = STOP_M * A, STOP_M * A * TMULT
            w = slice(i + 1, i + 1 + HOLD)
            rmax = np.maximum.accumulate(hi[w]); rmin = np.minimum.accumulate(lo[w])
            mid, endp = cl[i], cl[i + HOLD]
            for sgn in (1, -1):
                e = mid + sgn * spread / 2
                tp, s_ = e + sgn * td, e - sgn * sd
                if sgn > 0:
                    ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                    hs = np.argmax(rmin <= s_) if rmin[-1] <= s_ else 10 ** 6
                else:
                    ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                    hs = np.argmax(rmax >= s_) if rmax[-1] >= s_ else 10 ** 6
                if ht == 10 ** 6 and hs == 10 ** 6:
                    v = sgn * (endp - e) / A; sp.append(v); sl_.append(v); sw.append(v)
                elif ht == hs:
                    ties += 1
                    sp.append((WIN + LOSS) / 2); sl_.append(LOSS); sw.append(WIN)
                elif hs < ht:
                    sp.append(LOSS); sl_.append(LOSS); sw.append(LOSS)
                else:
                    sp.append(WIN); sl_.append(WIN); sw.append(WIN)
        if len(sp) < 400:
            skipped["no data"] += 1; continue
        a = np.array(sp)
        rows.append(dict(sym=name, n=len(a), split=a.mean(),
                         loss=float(np.mean(sl_)), win=float(np.mean(sw)),
                         se=a.std() / math.sqrt(len(a)), tie=ties / len(a) * 100,
                         spread_pct=spread / med_atr * 100,
                         risk=STOP_M * med_atr * info.trade_contract_size * 0.01))
    except Exception:
        skipped["error"] += 1

mt5.shutdown()
rows.sort(key=lambda r: -r["split"])
print("skipped: %s\n" % skipped)

print("SHALLOWEST BASELINES - the floor a strategy starts from, no signal at all")
print("%-12s %8s %6s %10s %10s %10s %8s %9s %8s"
      % ("symbol", "windows", "tie%", "TIE-SPLIT", "TIE-LOSS", "TIE-WIN", "+/-SE", "spread%ATR", "$risk"))
print("-" * 96)
for r in rows[:20]:
    stable = "" if (r["loss"] < 0) == (r["win"] < 0) or abs(r["split"]) > 0.02 else "  sign depends on ties"
    print("%-12s %8s %5.1f%% %10.4f %10.4f %10.4f %8.4f %8.1f%% %8.2f%s"
          % (r["sym"], f"{r['n']:,}", r["tie"], r["split"], r["loss"], r["win"],
             r["se"], r["spread_pct"], r["risk"], stable))
print("-" * 96)

btc = next((r for r in rows if r["sym"] == "BTCUSDm"), None)
if btc:
    rank = rows.index(btc) + 1
    print("\nBTCUSDm ranks %d of %d, baseline %.4f" % (rank, len(rows), btc["split"]))
    best = rows[0]
    print("best is %s at %.4f - a hole %.1fx shallower"
          % (best["sym"], best["split"], abs(btc["split"]) / max(abs(best["split"]), 1e-9)))
print("""
A baseline near zero means a weak signal could pay there. It does NOT mean the
instrument is profitable - random entry is still random. And a shallow baseline
with a high tie%% is not trustworthy: check the three tie columns agree in sign.""")
