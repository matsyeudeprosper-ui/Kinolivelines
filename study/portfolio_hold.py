"""A diversified hold portfolio - the one thing never actually optimised here.

Every test in this project held ONE instrument at a time and asked whether some signal
predicted it. This asks a different question: given that holding works arithmetically
(measured in leveraged_hold.py) but every single instrument has a 30-78% drawdown, does
combining them produce the same return at a drawdown a person can actually sit through?

That is not an edge and this file does not claim one. It is diversification, which is the
only genuinely free improvement in finance: uncorrelated assets combine to give the
average return at less than the average risk. Real money is overwhelmingly managed this
way rather than by prediction, and it is the piece this project skipped while chasing
signals.

THREE WEIGHTINGS, tested against each single instrument
  * equal weight            - the naive version
  * inverse volatility      - each asset sized so it contributes similar risk, which stops
                              BTC and silver dominating the drawdown
  * inverse vol, swap-aware - the same, tilted toward instruments that are cheap to hold,
                              since financing is a certain cost and returns are not

COSTS ARE REAL AND SIDE-CORRECT: spread once on entry, then financing every night on the
notional, using the point-mode conversion (swap * point * contract / notional).

THE HONEST CAVEAT, stated before the numbers rather than after. This window is 2019-2026,
one of the strongest equity and gold runs on record. JP225 returned 23%/yr and USTEC 21%/yr
in it. Long-run realistic equity returns are 7-10%/yr. Every figure below should be read
as "what this mix did in a good period", not as a forecast. Drawdowns, by contrast, tend
to be UNDERSTATED by short windows - the worst is usually still ahead.
"""
import numpy as np, pandas as pd
import MetaTrader5 as mt5

SYMS = ["JP225m", "XAUUSDm", "US500m", "USTECm", "DE30m", "UK100m",
        "XAGUSDm", "USOILm", "BTCUSDm"]
LEVS = [1.0, 1.5, 2.0]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
px, swap, spr = {}, {}, {}
for s in SYMS:
    if not mt5.symbol_select(s, True):
        continue
    i = mt5.symbol_info(s)
    r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 5000)
    if i is None or r is None or len(r) < 500 or i.ask <= 0:
        continue
    d = pd.DataFrame(r)
    d["t"] = pd.to_datetime(d["time"], unit="s").dt.normalize()
    px[s] = d.set_index("t")["close"].astype(float)
    unit = i.point * i.trade_contract_size
    notional = i.ask * i.trade_contract_size
    swap[s] = (abs(i.swap_long) * unit / notional) if i.swap_long < 0 else 0.0
    spr[s] = (i.ask - i.bid) / i.ask
mt5.shutdown()

P = pd.DataFrame(px).sort_index().dropna()
R = P.pct_change().fillna(0.0)
SW = pd.Series(swap).reindex(P.columns)
SP = pd.Series(spr).reindex(P.columns)
yrs = (P.index[-1] - P.index[0]).days / 365.25
print("UNIVERSE: %d instruments, %s to %s (%.1f years)"
      % (P.shape[1], P.index.min().date(), P.index.max().date(), yrs))
print("   %s\n" % ", ".join(P.columns))


def path(weights, lev):
    """Daily equity path for a fixed-weight leveraged long book, net of costs."""
    w = np.asarray(weights, float)
    w = w / w.sum()
    gross = (R.to_numpy() * w).sum(axis=1)            # portfolio daily return
    daily_swap = float((SW.to_numpy() * w).sum())
    eq = np.cumprod(1.0 + lev * gross) * (1.0 - lev * float((SP.to_numpy() * w).sum()))
    eq = eq * np.exp(-lev * daily_swap * np.arange(len(eq)))   # financing drag
    return eq


def report(name, weights, lev):
    eq = path(weights, lev)
    if eq[-1] <= 0:
        return name, lev, None, 1.0, None
    peak = np.maximum.accumulate(eq)
    dd = float(np.max(1.0 - eq / peak))
    cagr = eq[-1] ** (1 / yrs) - 1
    dr = np.diff(np.log(eq))
    sharpe = dr.mean() / dr.std(ddof=1) * np.sqrt(252) if dr.std(ddof=1) > 0 else float("nan")
    return name, lev, cagr, dd, sharpe


vol = R.std().to_numpy()
inv_vol = 1.0 / vol
cheap = 1.0 / (SW.to_numpy() * 365 + 0.02)            # tilt toward low financing
mixes = {
    "equal weight": np.ones(P.shape[1]),
    "inverse vol": inv_vol,
    "inv vol + swap-aware": inv_vol * cheap,
}

print("%-24s %5s %9s %9s %8s   %s"
      % ("portfolio", "lev", "CAGR", "max DD", "Sharpe", "return per unit of drawdown"))
print("-" * 92)
rows = []
for nm, w in mixes.items():
    for lev in LEVS:
        n, l, c, d, sh = report(nm, w, lev)
        if c is None:
            print("%-24s %5.1f %9s" % (n, l, "BLOWN")); continue
        rows.append((n, l, c, d, sh))
        print("%-24s %5.1f %8.1f%% %8.0f%% %8.2f   %.2f"
              % (n, l, 100 * c, 100 * d, sh, c / d))

print("\nSINGLE INSTRUMENTS at 1x, for comparison")
print("%-24s %5s %9s %9s %8s   %s" % ("", "lev", "CAGR", "max DD", "Sharpe", "ret/DD"))
print("-" * 92)
for k, s in enumerate(P.columns):
    w = np.zeros(P.shape[1]); w[k] = 1.0
    n, l, c, d, sh = report(s, w, 1.0)
    if c is not None:
        print("%-24s %5.1f %8.1f%% %8.0f%% %8.2f   %.2f" % (s, l, 100 * c, 100 * d, sh, c / d))

best = max(rows, key=lambda z: z[4])
print("""
WHAT TO LOOK AT: the last column, return per unit of drawdown, and the Sharpe. A mix that
earns less than BTC but survives a drawdown you would actually sit through is the better
strategy, because the return you get is the one you stay invested for.""")
print("Best risk-adjusted mix here: %s at %.1fx - %.1f%%/yr, %.0f%% max drawdown, Sharpe %.2f"
      % (best[0], best[1], 100 * best[2], 100 * best[3], best[4]))
print("""
Read that against the caveat at the top of this file. The period flatters the returns and
almost certainly understates the drawdowns.""")
