src = open('kino_demo2compass_backtest.py', encoding='utf-8').read()

def rep(old, new):
    global src
    assert old in src, f"NOT FOUND: {old[:70]!r}"
    src = src.replace(old, new)

rep("print(f'DEMO2 CANDLE-COMPASS: H4 candle + H1 candle same color = direction, no lights | START {START_BAL}', flush=True)",
    "GROUP_TP = float(_sys.argv[4]) if len(_sys.argv) > 4 else 1.0\n"
    "print(f'FIB LADDER: H4+H1 compass, entries at prev-H1 fib retracements, group exit at +${GROUP_TP} | START {START_BAL}', flush=True)\n"
    "fib_hour = -1\nfib_used = set()\nFIBS = (0.236, 0.382, 0.5, 0.618, 0.786)")

# group exit: whenever total open PnL >= GROUP_TP, close everything at bar close
rep("""        last_flat_hour = hr_now
    h4c = upd('h4', 14400, i)""",
"""        last_flat_hour = hr_now
    if positions:
        _tot = sum((c[i] - p['entry']) * p['vol'] * p['dir'] for p in positions)
        if _tot >= GROUP_TP:
            for p in positions[:]:
                pnl = (c[i] - p['entry']) * p['vol'] * p['dir']
                balance += pnl
                groups[p['hour']] = groups.get(p['hour'], 0.0) + pnl
                trades.append((tm[i], pnl, 'hour_clean'))
                positions.remove(p)
    h4c = upd('h4', 14400, i)""")

# replace the whole recipe entry with the fib ladder
old_entry = src[src.index("    if cur_hour == last_entry_hour or i < 1 or i + 1 >= N:"):
               src.index("# close remaining at end")]
new_entry = """    if i < 1 or i + 1 >= N:
        continue
    if cur_hour != fib_hour:
        fib_hour = cur_hour
        fib_used = set()
    _W = _h1[1] - _h1[2]
    if _W <= 20:
        continue
    for _k, _f in enumerate(FIBS):
        if _k in fib_used:
            continue
        if h1dir == 1:
            _lvl = _h1[1] - _f * _W
            if l[i] <= _lvl:
                fib_used.add(_k)
                _ep = _lvl + SPREAD
                positions.append({'dir': 1, 'entry': _ep, 'vol': LOTS, 'tp_custom': None,
                                  'tp': None, 'hour': tm[i] // 3600, 'idx': i})
                groups.setdefault(tm[i] // 3600, 0.0)
        else:
            _lvl = _h1[2] + _f * _W
            if h[i] >= _lvl:
                fib_used.add(_k)
                positions.append({'dir': -1, 'entry': _lvl, 'vol': LOTS, 'tp_custom': None,
                                  'tp': None, 'hour': tm[i] // 3600, 'idx': i})
                groups.setdefault(tm[i] // 3600, 0.0)
    max_conc = max(max_conc, len(positions))

"""
src = src.replace(old_entry, new_entry)
open('kino_fibladder_backtest.py', 'w', encoding='utf-8').write(src)
import ast
ast.parse(src)
print("fib-ladder variant OK")
