"""Backtest of the user's discretionary rule set as reverse-engineered from
the Owl journal + user's own description (2026-08-21). NOT a confirmed
strategy - exploratory ("just to see what that gives").

Rules encoded:
- H4 regime: BUY mode until a red H4 CLOSES below the open of the last green
  H4 (tide provably turned) -> SELL mode; mirror to flip back.
- H1 gate (buy side): last closed H1 green -> ok; red -> only if price is
  back above that red H1's close. Never when closed+forming H1 both red.
  (mirrored for sells)
- M15 trigger (buy): last closed M15 red AND forming M15 green. (mirror)
- Max 1 entry per clock hour. LOTS=0.02, TP $3 (150pts), NO SL.
- Owl exits: recovery (newest keeps TP150; older losers paired deepest/
  shallowest at midpoint+5pts, odd one BE+5pts; sticky, re-evaluated on
  open/close), hour-team cleanup: group older than current hour closes when
  its net P&L >= max($1, 50pts*group volume).
- Spread 10pts on buy entries (same convention as all project sims).
Start balance $157 (user's deposits). Tracks min equity / max combined
floating DD / would-be margin deaths (equity < $8/open position approx).
"""
import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = 10.0
LOTS = 0.02
TP_PTS = 3.0 / LOTS          # 150
BE_PTS = 0.10 / LOTS         # 5
CLEAN_USD = 1.00
CLEAN_PTS = 50.0
import sys as _sys
START_BAL = float(_sys.argv[1]) if len(_sys.argv) > 1 else 157.0
GATE_PCT = float(_sys.argv[2]) if len(_sys.argv) > 2 else 3.0
print(f'START_BAL {START_BAL}  CALM GATE {GATE_PCT}%', flush=True)
from collections import deque
maxq = deque()
minq = deque()

files = ['coinbase_m1_2yr_partneg1.json','coinbase_m1_2yr_part0.json','coinbase_m1_2yr_part1.json',
         'coinbase_m1_2yr_part2.json','coinbase_m1_extra_year.json','coinbase_m1_pilot.json']
rows = {}
for f in files:
    for t, lo, hi, op, cl, vol in json.load(open(f)):
        rows[int(t)] = (op, hi, lo, cl)
ok = mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select("BTCUSDm", True)
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 99000)
mt5.shutdown()
for i in range(len(r)):
    rows[int(r["time"][i])] = (float(r["open"][i]), float(r["high"][i]), float(r["low"][i]), float(r["close"][i]))
times = sorted(rows.keys())
o = np.array([rows[t][0] for t in times]); h = np.array([rows[t][1] for t in times])
l = np.array([rows[t][2] for t in times]); c = np.array([rows[t][3] for t in times])
tm = np.array(times); N = len(times)
print(f"{N} M1 bars", flush=True)

eras = [("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
        ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
        ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,22).timestamp())]

# --- state ---
mode = 0  # +1 buy mode, -1 sell mode, 0 undecided (first H4 sets it)
last_green_h4_open = None
last_red_h4_open = None
mode_d1 = 0
lg_d1 = None
lr_d1 = None
# user's 3-step M1 recipe state (reset each hour)
rcp_hour = -1
rcp_setup = None       # trigger high (re-anchored on each green-green-hh)
rcp_pulled = False
print("KINO-CLONE FULL SYSTEM: recipe + escape v2 + auto-hedge + deadline cuts", flush=True)
BE_PTS = 5.0
escape_active = False
prev_mode = 0
esc_start = -1
# rolling candle builders: (window_id, open, high, low, close)
cur = {}
closed = {}   # tf -> (open, high, low, close)
def upd(tf, sec, i):
    wid = tm[i] // sec
    e = cur.get(tf)
    out = None
    if e is None or e[0] != wid:
        if e is not None:
            out = (e[1], e[2], e[3], e[4])
        cur[tf] = [wid, o[i], h[i], l[i], c[i]]
    else:
        if h[i] > e[2]: e[2] = h[i]
        if l[i] < e[3]: e[3] = l[i]
        e[4] = c[i]
    return out

positions = []   # dicts: dir, entry, vol, hour, tp, idx
groups = {}      # hour_id -> realized
balance = 0.0
trades = []      # (t, pnl, kind)
pending = None
last_entry_hour = -1
min_equity = 1e9
max_float_dd = 0.0
deaths = 0
death_dates = []
max_conc = 0

def reassign():
    if not positions:
        return
    if escape_active:
        for p in positions:
            if p['dir'] != mode:
                p['tp'] = p['entry'] + p['dir'] * BE_PTS
            elif p.get('holder'):
                p['tp'] = None
            else:
                p['tp'] = p['entry'] + p['dir'] * TP_PTS
        return
    for d in (1, -1):
        grp = [p for p in positions if p['dir'] == d]
        if not grp:
            continue
        grp.sort(key=lambda p: p['idx'])
        newest = grp[-1]
        newest['tp'] = newest['entry'] + d * TP_PTS
        older = grp[:-1]
        price = c[i]
        losers = [p for p in older if (d == 1 and price < p['entry']) or (d == -1 and price > p['entry'])]
        winners = [p for p in older if p not in losers]
        for p in winners:
            p['tp'] = p['entry'] + d * TP_PTS
        losers.sort(key=lambda p: p['entry'], reverse=(d == 1))
        a, b = 0, len(losers) - 1
        while a < b:
            m = (losers[a]['entry'] + losers[b]['entry']) / 2 + d * BE_PTS
            losers[a]['tp'] = m; losers[b]['tp'] = m
            a += 1; b -= 1
        if a == b:
            losers[a]['tp'] = losers[a]['entry'] + d * BE_PTS

for i in range(N):
    h4c = upd('h4', 14400, i)
    h1c = upd('h1', 3600, i)
    m15c = upd('m15', 900, i)
    d1c = upd('d1', 86400, i)
    if d1c is not None:
        op1, _, _, cl1 = d1c
        if cl1 > op1:
            lg_d1 = op1
            if mode_d1 == 0: mode_d1 = 1
            elif mode_d1 == -1 and lr_d1 is not None and cl1 > lr_d1: mode_d1 = 1
        elif cl1 < op1:
            lr_d1 = op1
            if mode_d1 == 0: mode_d1 = -1
            elif mode_d1 == 1 and lg_d1 is not None and cl1 < lg_d1: mode_d1 = -1
    if h4c is not None:
        closed['h4'] = h4c
        op4, _, _, cl4 = h4c
        green = cl4 > op4
        if green:
            last_green_h4_open = op4
            if mode == 0: mode = 1
            if mode == -1 and last_red_h4_open is not None and cl4 > last_red_h4_open:
                mode = 1
        else:
            last_red_h4_open = op4
            if mode == 0: mode = -1
            if mode == 1 and last_green_h4_open is not None and cl4 < last_green_h4_open:
                mode = -1
    if mode != 0 and prev_mode != 0 and mode != prev_mode:
        wrong = [p for p in positions if p['dir'] != mode]
        trend_vol = sum(p['vol'] for p in positions if p['dir'] == mode)
        need = sum(p['vol'] for p in wrong) - trend_vol
        if wrong and need > 0.005 and i + 1 < N:
            ep = o[i] + (SPREAD if mode == 1 else 0.0)
            positions.append({'dir': mode, 'entry': ep, 'vol': round(need, 2),
                              'hour': tm[i] // 3600, 'tp': None, 'idx': i, 'holder': True})
            groups.setdefault(tm[i] // 3600, 0.0)
            for p in wrong:
                p['tp'] = p['entry'] + p['dir'] * BE_PTS
            escape_active = True
            esc_start = i
    if mode != 0:
        prev_mode = mode
    if escape_active and not ([p for p in positions if p['dir'] != mode] and
                              [p for p in positions if p['dir'] == mode]):
        escape_active = False
        reassign()
    if h1c is not None:
        closed['h1'] = h1c
        # escape deadline: H1 closed AGAINST an active escape -> cut wrong legs
        if escape_active and mode != 0 and i > esc_start + 60:
            h1o_, _, _, h1cl_ = h1c
            h1dir = 1 if h1cl_ > h1o_ else (-1 if h1cl_ < h1o_ else 0)
            if h1dir == mode:
                for p in [x for x in positions if x['dir'] != mode]:
                    pnl = (c[i] - p['entry']) * p['vol'] * p['dir']
                    balance += pnl
                    groups[p['hour']] = groups.get(p['hour'], 0.0) + pnl
                    trades.append((tm[i], pnl, 'escape_cut'))
                    positions.remove(p)
                escape_active = False
                reassign()
    if m15c is not None: closed['m15'] = m15c

    # fill pending entry at this bar's open
    if pending is not None:
        d = pending
        ep = o[i] + (SPREAD if d == 1 else 0.0)
        positions.append({'dir': d, 'entry': ep, 'vol': LOTS,
                          'hour': tm[i] // 3600, 'tp': ep + d * TP_PTS, 'idx': i})
        groups.setdefault(tm[i] // 3600, 0.0)
        pending = None
        reassign()
        max_conc = max(max_conc, len(positions))

    # --- exits: TP touches ---
    closed_any = False
    for p in positions[:]:
        if p['tp'] is None:
            continue
        hit = (h[i] >= p['tp']) if p['dir'] == 1 else (l[i] <= p['tp'])
        if hit:
            pnl = (p['tp'] - p['entry']) * p['vol'] * p['dir']
            balance += pnl
            groups[p['hour']] = groups.get(p['hour'], 0.0) + pnl
            kind = 'tp' if abs(pnl - 3.0) < 0.5 else 'be'
            trades.append((tm[i], pnl, kind))
            positions.remove(p)
            closed_any = True
    # --- hour-team cleanup ---
    cur_hour = tm[i] // 3600
    if escape_active:
        groups_iter = []
    else:
        groups_iter = list(groups.keys())
    for hid in groups_iter:
        mem = [p for p in positions if p['hour'] == hid]
        if hid >= cur_hour:
            continue
        if not mem:
            del groups[hid]
            continue
        floating = sum((c[i] - p['entry']) * p['vol'] * p['dir'] for p in mem)
        total = groups[hid] + floating
        need = max(CLEAN_USD, CLEAN_PTS * sum(p['vol'] for p in mem))
        if total >= need:
            for p in mem:
                pnl = (c[i] - p['entry']) * p['vol'] * p['dir']
                balance += pnl
                trades.append((tm[i], pnl, 'hour_clean'))
                positions.remove(p)
            del groups[hid]
            closed_any = True
    if closed_any:
        reassign()

    # --- equity / death tracking ---
    if positions:
        floating = sum((c[i] - p['entry']) * p['vol'] * p['dir'] for p in positions)
        eq = START_BAL + balance + floating
        if floating < -max_float_dd: max_float_dd = -floating
        if eq < min_equity: min_equity = eq
        # lifecycle: margin stop (~$8 margin per 0.02 position) kills the
        # account - lose whole remaining equity, redeposit $157, start fresh
        if eq < 8.0 * len(positions):
            deaths += 1
            death_dates.append(datetime.utcfromtimestamp(int(tm[i])).strftime('%Y-%m-%d'))
            trades.append((tm[i], balance, 'account_death'))  # banked-at-death
            balance = 0.0          # deposit + banked all gone; new $157 life starts
            positions.clear(); groups.clear()

    # --- entry signal (evaluated at bar close, filled next open) ---
    # rolling 24h range (monotonic deques)
    while maxq and maxq[0][0] <= i - 1440: maxq.popleft()
    while minq and minq[0][0] <= i - 1440: minq.popleft()
    while maxq and maxq[-1][1] <= h[i]: maxq.pop()
    maxq.append((i, h[i]))
    while minq and minq[-1][1] >= l[i]: minq.pop()
    minq.append((i, l[i]))
    range24_pct = 100.0 * (maxq[0][1] - minq[0][1]) / c[i] if c[i] else 99.0
    # --- KINO-CLONE entry: user's 3-step recipe on closed M1 bars ---
    if cur_hour != rcp_hour:
        rcp_hour = cur_hour
        rcp_setup = None
        rcp_pulled = False
    if range24_pct >= GATE_PCT:
        continue                      # calm gate: storms = no entries
    if mode == 0 or mode != mode_d1 or pending is not None or escape_active:
        continue                      # green light only, never during escape
    if cur_hour == last_entry_hour or i < 1 or i + 1 >= N:
        continue
    d = mode
    if d == 1:
        g_prev = c[i-1] > o[i-1]
        g_cur = c[i] > o[i]
        hh = h[i] > h[i-1]
        fire = (rcp_setup is not None and rcp_pulled and c[i] > rcp_setup)
        if fire:
            pending = d
            last_entry_hour = cur_hour
            rcp_setup = None
            rcp_pulled = False
        elif g_prev and g_cur and hh:
            rcp_setup = h[i]
            rcp_pulled = l[i] <= l[i-1]
        elif rcp_setup is not None and l[i] <= l[i-1]:
            rcp_pulled = True
    else:
        r_prev = c[i-1] < o[i-1]
        r_cur = c[i] < o[i]
        ll = l[i] < l[i-1]
        fire = (rcp_setup is not None and rcp_pulled and c[i] < rcp_setup)
        if fire:
            pending = d
            last_entry_hour = cur_hour
            rcp_setup = None
            rcp_pulled = False
        elif r_prev and r_cur and ll:
            rcp_setup = l[i]
            rcp_pulled = h[i] >= h[i-1]
        elif rcp_setup is not None and h[i] >= h[i-1]:
            rcp_pulled = True

# close remaining at end
for p in positions:
    pnl = (c[-1] - p['entry']) * p['vol'] * p['dir']
    balance += pnl
    trades.append((tm[-1], pnl, 'open_end'))

engine = [t for t in trades if t[2] in ('tp', 'be', 'hour_clean', 'open_end')]
cuts = [t for t in trades if t[2] == 'escape_cut']
print(f"escape cuts: {len(cuts)} totalling ${sum(t[1] for t in cuts):,.2f}")
tp_wins = sum(1 for t in trades if t[2] == 'tp')
be = sum(1 for t in trades if t[2] == 'be')
hc = sum(1 for t in trades if t[2] == 'hour_clean')
deaths_l = [t for t in trades if t[2] == 'account_death']
span_mo = (tm[-1] - tm[0]) / 86400 / 30.44
engine_pnl = sum(t[1] for t in engine)
print(f"\nENGINE: closes {len(engine)}  tp-wins {tp_wins}  BE/mid {be}  hour_clean {hc}")
print(f"engine pnl (ignoring deaths) ${engine_pnl:,.2f}  (${engine_pnl/span_mo:,.2f}/mo)")
print(f"max concurrent positions: {max_conc}")
print(f"max combined floating DD: ${max_float_dd:,.2f}")
print(f"\nACCOUNT LIVES (start $157 each, death = lose deposit + banked):")
print(f"deaths: {deaths}")
if deaths_l:
    bk = [t[1] for t in deaths_l]
    print(f"banked-at-death: avg ${sum(bk)/len(bk):,.2f}  max ${max(bk):,.2f}")
    print(f"death dates: {death_dates}")
    prev = tm[0]
    lens = []
    for t in deaths_l:
        lens.append((t[0]-prev)/86400); prev = t[0]
    print(f"life length days: avg {sum(lens)/len(lens):,.1f}  min {min(lens):,.1f}  max {max(lens):,.1f}")
net_deposits = (deaths + 1) * START_BAL
final_life_banked = balance
print(f"\nTOTAL: deposited ${net_deposits:,.0f} over {deaths+1} lives; "
      f"final life banked ${final_life_banked:,.2f} -> overall net ${final_life_banked + START_BAL - net_deposits:,.2f}")
for lbl, d0, d1 in eras:
    n = sum(1 for t in engine if d0 <= t[0] < d1)
    g = sum(t[1] for t in engine if d0 <= t[0] < d1)
    dd = sum(1 for t in deaths_l if d0 <= t[0] < d1)
    print(f"  {lbl}: engine closes={n} engine pnl=${g:,.2f} deaths={dd}")
