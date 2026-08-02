"""What does the demo+live pair net now that the exits no longer match?

The previous mirror put both accounts' barriers on the SAME two prices, so they closed
on the same tick and the pair cost exactly one spread - a fixed, known number. The user
has now asked for fixed dollar exits on the live side instead ($1 target, $2 stop from
its own entry), accepting that the two sides no longer close together.

Once they stop closing together the combined result is no longer a fixed number. It
depends on the path price takes. So it is simulated on real M5 bars rather than argued.

  demo   BUY at E (ask)          SL E-20  (-$1)   TP E+40  (+$2)
  live   SELL at E-spread        TP -$1 from its entry, SL -$2 from its entry

Each side is followed independently to its own barrier. A side that never reaches one
inside the hold is settled at the closing price, which is what the broker's 120-minute
force-close actually does.
"""
import math, random
import numpy as np, pandas as pd
import MetaTrader5 as mt5

SYM, LOTS = "BTCUSDm", 0.05
# M1, NOT M5. A 20-point target on a $63,000 instrument is smaller than a typical M5
# bar's range, so on M5 both barriers land inside the same candle most of the time and
# the order they were touched in is unknowable. A first run on M5 was 84% ambiguous and
# its numbers were meaningless. M1 is the finest data this broker exposes; the ambiguity
# rate is printed below so the remaining artifact is visible rather than assumed away.
TF, MAX_BARS = mt5.TIMEFRAME_M1, 120     # 120 minutes
DEMO_SL, DEMO_TP = 20.0, 40.0       # points; $1 risk / $2 reward at 0.05 lots
rng = random.Random(1717)

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select(SYM, True)
tk = mt5.symbol_info_tick(SYM)
SPREAD = tk.ask - tk.bid
r5 = None
for w in (400000, 200000, 120000, 60000):
    r5 = mt5.copy_rates_from_pos(SYM, TF, 0, w)
    if r5 is not None and len(r5):
        break
mt5.shutdown()

d5 = pd.DataFrame(r5)
d5["t"] = pd.to_datetime(d5["time"], unit="s")
H = d5.high.to_numpy(float); L = d5.low.to_numpy(float); C = d5.close.to_numpy(float)

# money per 1.0 of price movement, the same calc the EA now does
PER_UNIT = LOTS                                  # BTCUSDm: 1.0 lot = $1 per price unit
LIVE_TP = 1.00 / PER_UNIT                        # 20 points
LIVE_SL = 2.00 / PER_UNIT                        # 40 points


def walk(i0, entry, up_barrier, dn_barrier):
    """Return which barrier is touched first, or None if neither inside the hold."""
    for j in range(i0 + 1, min(i0 + 1 + MAX_BARS, len(C))):
        hit_up = H[j] >= up_barrier
        hit_dn = L[j] <= dn_barrier
        if hit_up and hit_dn:
            return "ambig"
        if hit_up:
            return "up"
        if hit_dn:
            return "dn"
    return None


rows = []
busy = -1
for i0 in range(300, len(C) - MAX_BARS - 1):
    if i0 <= busy:
        continue                                  # non-overlapping windows
    busy = i0 + MAX_BARS
    demo_buy = rng.random() < 0.5
    E = C[i0] + (SPREAD if demo_buy else 0.0)     # demo fill
    M = E - SPREAD if demo_buy else E + SPREAD    # live fill, other side of the book
    end = C[min(i0 + MAX_BARS, len(C) - 1)]

    # ---- demo side -------------------------------------------------------------
    if demo_buy:
        up, dn = E + DEMO_TP, E - DEMO_SL
    else:
        up, dn = E + DEMO_SL, E - DEMO_TP
    demo_r = r = walk(i0, E, up, dn)
    if r == "ambig":
        demo = (DEMO_TP - DEMO_SL) / 2 * LOTS
    elif r == "up":
        demo = (DEMO_TP if demo_buy else -DEMO_SL) * LOTS
    elif r == "dn":
        demo = (-DEMO_SL if demo_buy else DEMO_TP) * LOTS
    else:
        demo = ((end - E) if demo_buy else (E - end)) * LOTS

    # ---- live side, opposite direction, its own dollar barriers ----------------
    live_buy = not demo_buy
    if live_buy:
        up, dn = M + LIVE_TP, M - LIVE_SL
    else:
        up, dn = M + LIVE_SL, M - LIVE_TP
    r = walk(i0, M, up, dn)
    if r == "ambig":
        live = (1.00 - 2.00) / 2
    elif r == "up":
        live = 1.00 if live_buy else -2.00
    elif r == "dn":
        live = -2.00 if live_buy else 1.00
    else:
        live = ((end - M) if live_buy else (M - end)) * LOTS

    rows.append({"demo": demo, "live": live, "pair": demo + live,
                 "demo_ambig": demo_r == "ambig", "live_ambig": r == "ambig",
                 "live_timeout": r is None})

df = pd.DataFrame(rows)
print("UNLINKED PAIR - live exits at fixed $1 / $2, demo runs its own 20/40")
print("%d non-overlapping trades, %s to %s, spread %.2f\n"
      % (len(df), d5.t.min().date(), d5.t.max().date(), SPREAD))

for name in ("demo", "live", "pair"):
    v = df[name]
    se2 = 2 * v.std() / math.sqrt(len(v))
    print("  %-5s  mean $%+.4f  +/-%.4f   total $%+8.2f   win %.0f%%"
          % (name, v.mean(), se2, v.sum(), 100 * (v > 0).mean()))

print("\nHOW MUCH OF THIS IS ARTIFACT")
print("  demo both-barriers-in-one-bar: %.0f%%   live: %.0f%%   live never resolved: %.0f%%"
      % (100 * df.demo_ambig.mean(), 100 * df.live_ambig.mean(), 100 * df.live_timeout.mean()))
if df.live_ambig.mean() > 0.20:
    print("  >20% ambiguous - these numbers are NOT trustworthy, the bar data is too coarse")

print("\nLIVE ALONE - the account that holds real money")
w = (df.live > 0).sum(); l = (df.live < 0).sum()
print("  %d wins at ~+$1, %d losses at ~-$2, breakeven needs %.0f%%, actual %.0f%%"
      % (w, l, 100 * 2 / 3, 100 * w / max(w + l, 1)))

print("\nHOW THE PAIR LANDS")
print(df["pair"].round(2).value_counts().head(8).to_string())
print("""
The pair mean is the number that matters. If it is near -$1.00 the two sides are simply
paying two spreads with no offset left; the old matched-barrier version paid -$0.50.""")
