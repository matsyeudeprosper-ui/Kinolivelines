"""Cost census across every symbol on the account.

Decides whether cross-sectional (rank-and-spread) strategies are feasible
here, which needs BREADTH of economically tradeable instruments.

Two independent filters - a symbol must pass both:

  1. COST     median spread as % of median ATR(H1). This is the toll per
              round trip relative to how far the thing actually moves.
              Above ~10% nothing survives.
  2. SIZING   account-currency P&L of a 1-ATR(H1) move at the MINIMUM lot.
              If the smallest position you can open swings $200 on a $990
              account, you cannot risk-manage it regardless of how cheap
              the spread is.

Uses the historical spread recorded on each H1 bar rather than a single live
tick - a snapshot at one quiet moment misled badly earlier today.

Market Watch is restored to its original selection on exit.
"""
import MetaTrader5 as mt5, pandas as pd, numpy as np, os

ACCOUNT_RISK_CAP = 0.02      # a 1-ATR move at min lot must fit inside 2% of equity
COST_CAP_PCT     = 10.0
OUT = os.path.dirname(os.path.abspath(__file__))

if not mt5.initialize():
    raise SystemExit(mt5.last_error())

acc = mt5.account_info()
equity = acc.equity
print(f"account {acc.login}  equity {equity} {acc.currency}")

all_syms = mt5.symbols_get()
original_visible = {s.name for s in all_syms if s.visible}
print(f"symbols on account : {len(all_syms)}")
print(f"originally visible : {len(original_visible)}")

rows = []
for n, s in enumerate(all_syms):
    name = s.name
    try:
        if not s.visible and not mt5.symbol_select(name, True):
            continue
        r = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H1, 0, 300)
        if r is None or len(r) < 100:
            rows.append({'symbol': name, 'category': s.path.split('\\')[1] if '\\' in s.path else '?',
                         'status': 'no_history'})
            continue
        d = pd.DataFrame(r)
        pc = d['close'].shift(1)
        tr = pd.concat([d['high']-d['low'], (d['high']-pc).abs(), (d['low']-pc).abs()], axis=1).max(axis=1)
        a = tr.rolling(14).mean().median()

        si = mt5.symbol_info(name)
        point = si.point
        spread_px = np.median(d['spread'].values) * point      # historical, not a snapshot
        if a is None or not np.isfinite(a) or a <= 0 or spread_px <= 0:
            rows.append({'symbol': name, 'category': s.path.split('\\')[1] if '\\' in s.path else '?',
                         'status': 'bad_data'})
            continue

        tick_v, tick_s = si.trade_tick_value, si.trade_tick_size
        atr_value = (a / tick_s) * tick_v * si.volume_min if tick_s > 0 else np.nan

        rows.append({
            'symbol': name,
            'category': s.path.split('\\')[1] if '\\' in s.path else '?',
            'status': 'ok',
            'price': d['close'].iloc[-1],
            'spread_px': spread_px,
            'atr_h1': a,
            'cost_pct': spread_px / a * 100.0,
            'vol_min': si.volume_min,
            'atr_val_min_lot': atr_value,
            'risk_pct_equity': atr_value / equity * 100.0 if np.isfinite(atr_value) else np.nan,
        })
    except Exception as ex:
        rows.append({'symbol': name, 'category': '?', 'status': f'err:{type(ex).__name__}'})
    if (n + 1) % 50 == 0:
        print(f"  ...{n+1}/{len(all_syms)}")

# restore Market Watch
for s in all_syms:
    if s.name not in original_visible:
        mt5.symbol_select(s.name, False)
mt5.shutdown()

df = pd.DataFrame(rows)
df.to_csv(os.path.join(OUT, "cost_census.csv"), index=False)
ok = df[df['status'] == 'ok'].copy()
print(f"\nmeasured OK: {len(ok)}   |   no history: {(df['status']=='no_history').sum()}   "
      f"other: {(~df['status'].isin(['ok','no_history'])).sum()}")

ok['pass_cost'] = ok['cost_pct'] <= COST_CAP_PCT
ok['pass_size'] = ok['risk_pct_equity'] <= ACCOUNT_RISK_CAP * 100
ok['tradeable'] = ok['pass_cost'] & ok['pass_size']

print("\n" + "="*100)
print("BY CATEGORY")
print("="*100)
g = ok.groupby('category').agg(
    n=('symbol','size'),
    median_cost=('cost_pct','median'),
    pass_cost=('pass_cost','sum'),
    pass_size=('pass_size','sum'),
    tradeable=('tradeable','sum')).sort_values('tradeable', ascending=False)
print(g.to_string())

print("\n" + "="*100)
print(f"FULLY TRADEABLE  (cost <= {COST_CAP_PCT}% of ATR  AND  1-ATR move at min lot <= {ACCOUNT_RISK_CAP*100}% of equity)")
print("="*100)
t = ok[ok['tradeable']].sort_values('cost_pct')
if len(t):
    print(t[['symbol','category','price','spread_px','atr_h1','cost_pct','vol_min',
             'atr_val_min_lot','risk_pct_equity']].to_string(index=False,
             float_format=lambda x: f"{x:,.4g}"))
print(f"\n>>> TRADEABLE COUNT: {len(t)} of {len(ok)} measured ({len(all_syms)} on account)")

print("\n" + "="*100)
print("CHEAP ON COST BUT TOO BIG TO SIZE  (the near-misses)")
print("="*100)
nm = ok[ok['pass_cost'] & ~ok['pass_size']].sort_values('cost_pct').head(25)
if len(nm):
    print(nm[['symbol','category','cost_pct','vol_min','atr_val_min_lot','risk_pct_equity']]
          .to_string(index=False, float_format=lambda x: f"{x:,.4g}"))

print("\n" + "="*100)
print("TOP 30 BY COST ALONE (ignoring sizing)")
print("="*100)
print(ok.nsmallest(30, 'cost_pct')[['symbol','category','cost_pct','risk_pct_equity']]
      .to_string(index=False, float_format=lambda x: f"{x:,.4g}"))
print(f"\nfull table -> {os.path.join(OUT, 'cost_census.csv')}")
