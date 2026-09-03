"""OWL — manual-trade assistant on LIVE account 134499778 (2026-08-20).

Jobs:
1. TP manager with RECOVERY system (user spec 2026-08-20):
   Golden rule: exit at NO LOSS or keep trades open. Never sets SL.
   - Single manual position (or any position not in recovery): TP = entry
     +/- $3-worth (dist = 3.0/volume).
   - 2 same-direction positions and the OLDER one is losing: newest keeps
     the $3 TP, older one's TP moves to its own breakeven + $0.10-worth
     buffer (never closes red; buffer beats the spread).
   - 3+ same-direction with multiple older losers: newest keeps $3 TP;
     older losers are PAIRED deepest-with-shallowest, each pair's TPs set
     to their volume-weighted midpoint + buffer so the pair closes together
     at net ~zero. Odd leftover -> own breakeven. Pairs are STICKY once
     formed (stored in state; only re-evaluated when a position opens or
     closes, so price wiggle can't yank a pair's TP away).
   - Recovery only applies when the older trade is in LOSS; profitable
     older trades keep the normal $3 TP.
   - Positions where the USER set their own TP (tp already set at first
     sight, or changed away from what Owl set) are left alone forever.
   Never opens positions. Never touches bot positions (magic!=0).
1b. HOUR-GROUP cleanup (user spec 2026-08-20, "yes build it"): every manual
   position belongs to the hour it was opened in (server time). When a
   group's hour is OVER, Owl checks continuously: if the group's total P&L
   (realized profits of its already-closed members + floating P&L incl.
   swap of its open members) >= +$0.10 buffer, it CLOSES all remaining
   open positions of that group at market ("OWL-hour-clean"). Group-level
   no-loss: an individual leg may close red only when the group as a whole
   exits positive. Below the line -> everything stays open (golden rule).
   The current hour's positions are never touched by cleanup.
2. Scribe: full market snapshot at ENTRY and EXIT of every manual trade
   (ATR14 M1/H1, EMA20/50/200 M1 + EMA20/50 H1, 24h range %, spread,
   M1+H1 candle anatomy, H1 higher-high/lower-low flags, sweep distances,
   duration, exit reason) -> owl_manual_journal.csv, entry_*/exit_* cols.
State (pending entries, assignments, counters) survives restarts.
"""
import json, os, time, csv, traceback
from datetime import datetime, timezone, timedelta
import numpy as np
import MetaTrader5 as mt5

LOGIN = 81725152
PASSWORD = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "owl_secrets.json"), encoding="utf-8"))["mt5_password"]  # not in git
SERVER = 'Exness-MT5Trial10'
TERMINAL = r"C:\Projects\MT5-Forge\terminal64.exe"
SYMBOL = "BTCUSDz"         # RAW demo symbol (0 spread + $0.09 RT commission measured)
TP_USD = 3.0
HOUR_FLAT = True           # 2026-08-23 user: "no trade position carried over the
                           # next hour" - at each hour boundary ALL manual
                           # positions are closed at market, win or lose
                           # (sanctioned red closes; retires the no-loss rule).
                           # Auto-hedge/escape become obsolete and are disabled
                           # while this is on.
RUNNER_LIVE = False        # 2026-08-23 (later same day): user moving the Runner
                           # to its own dedicated live account - real runner OFF
                           # here; paper runner keeps rehearsing.
                           # Original note: real Aligned Partial Runner ON TOP
                           # of the scalps. At CLOCKS ALIGNED: open 2x0.01
                           # (leg A TP +150pts = $1.50; leg B no TP). When A
                           # banks, B's SL moves to its entry (risk-free) and
                           # rides until the D1 clock flips. If alignment
                           # breaks in phase 1, both legs close at market.
                           # Runner legs are EXEMPT from hour-flat, recovery,
                           # hour-clean and normal TP management.
AUTO_ENTRY = False  # PRO: pure Croc, no dip clone          # 2026-08-22 user: "implement my entry" - the Owl
                           # trades the user's 3-step recipe itself, but ONLY:
                           # green light (H4==D1), no active escape, stack < 3,
                           # max 1 entry/hour, balance >= $50. Yellow light =
                           # bot stands aside (user may still trade by hand).
AUTO_LOTS = 0.02
AUTO_MAX_STACK = 3
AUTO_MIN_BAL = 50.0
DIP_GATE = False            # 2026-08-23 user: dip-in-trend gate on auto entries.
                           # BUY only if last closed H1 green AND M15 red AND
                           # M5 red (mirror for SELL). Backtest: best per-trade
                           # coin found (-3.1c); with split TP the combo is the
                           # first positive fast config (+$1.60/mo, 0 deaths).
SPLIT_TP = False            # 2026-08-23 user: split entry - 2x0.01 instead of
                           # 1x0.02. CORRECTED 2026-08-24: the backtest-positive
                           # design is BOTH legs TP +150pts ($1.50 each) with
                           # the normal recovery system managing them (a losing
                           # leg walks out at breakeven) - NOT fixed +75/+150.
                           # Split legs use SPLIT_TP_USD as their tp3 target and
                           # are swept by hour-flat like everything else.
SPLIT_TP_USD = 1.50        # per-leg prize: $1.50 / 0.01 lot = +150 pts
SPLIT_TICKETS = set()      # refreshed each loop; read by tp3_price()
LONDON_OFF = False          # 2026-08-24 user-approved: NO new auto entries
                           # 08-16 UTC (London). Session backtest by ENTRY hour:
                           # London = -2.2c/trade, negative 2/3 eras; without it
                           # +$2.06/mo and ALL 3 eras positive (first ever).
                           # Asia removal tested and REJECTED (NY-only worse).
SWEEP_ENTRY = True         # 2026-08-24 user: Range Sweep V1 at HALF size.
                           # Range = high/low of last 12 CLOSED H1s. M1 pokes
                           # outside then CLOSES back inside -> enter toward the
                           # middle. No light/session/trend filter (pure form
                           # backtested +$23.53/mo at 2x0.01, all eras green,
                           # 0 deaths; half size ~ +$12/mo, worst hour ~ -$66).
                           # Exits: $1.50 TP via the split machinery + recovery,
                           # 30-min time stop, hour-flat. Max 1 entry/hour.
SWEEP_LOTS = 0.01
SWEEP_RANGE_N = 12
SWEEP_STOP_SEC = 1800      # 30-minute time stop
SWEEP_MIN_RANGE = 50.0     # dead-range guard (price points)
SWEEP_EARLY_ONLY = False   # 2026-08-24: REJECTED after the three-way control.
                           # The gated "late half loses" test was contaminated
                           # (stale sweep flags fired fake entries); clean
                           # attribution shows real late entries earn +$230/6yr
                           # (:30-:44 ~zero, :45-:59 +6.1c). Pure form wins:
                           # +$23.53/mo vs +$21.99 early-only. Keep pure.
BUFFER_USD = 0.10          # guaranteed min profit on breakeven/midpoint exits
CLEAN_PTS_HEADROOM = 50.0  # hour-clean: group must be up 50pts-worth per lot of volume
                           # (>= ~2x the worst observed check-to-fill slippage, which
                           # turned a +0.12 check into a -0.44 close on 2026-08-21)
CLEAN_MIN_USD = 1.00       # ...and never less than $1 total
TP_TOL = 1.0               # pts tolerance before (re)sending a TP modify
DIR = r"C:\Projects\KinoliveLines\live"
LOG = os.path.join(DIR, "owl_raw.log")
ALIVE = os.path.join(DIR, "owl_raw_alive.json")
STATE = os.path.join(DIR, "owl_raw_state.json")
JOURNAL = os.path.join(DIR, "owl_raw_journal.csv")
MARKETLOG = os.path.join(DIR, "owl_raw_market_log.csv")

def say(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")

def load_state():
    try:
        st = json.load(open(STATE))
    except Exception:
        st = {}
    st.setdefault("pending", {})
    st.setdefault("tp_set_total", 0)
    st.setdefault("trades_logged", 0)
    st.setdefault("assign", {})       # ticket(str) -> {mode, partner, tp}
    st.setdefault("owned", {})        # ticket(str) -> last tp Owl set
    st.setdefault("user_owned", [])   # tickets Owl must never touch
    st.setdefault("last_tickets", [])
    st.setdefault("groups", {})       # hour_id(str) -> {start_equity, realized, tickets}
    return st

def save_state(st):
    with open(STATE, "w") as f:
        json.dump(st, f)

def ema(a, n):
    k = 2.0 / (n + 1)
    e = a[0]
    for x in a[1:]:
        e = x * k + e * (1 - k)
    return float(e)

def atr(h, l, c, n=14):
    tr = np.maximum(h[1:], c[:-1]) - np.minimum(l[1:], c[:-1])
    if len(tr) < n:
        return float(np.mean(tr)) if len(tr) else 0.0
    return float(np.mean(tr[-n:]))

def candle_anatomy(o, h, l, c):
    body = c - o
    color = "green" if body > 0 else ("red" if body < 0 else "doji")
    return color, abs(body), h - max(o, c), min(o, c) - l

def rsi(closes, n=14):
    d = np.diff(np.asarray(closes[-(n * 10):], dtype=float))
    if len(d) < n:
        return 50.0
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au, ad = float(np.mean(up[-n:])), float(np.mean(dn[-n:]))
    if ad == 0:
        return 100.0
    return round(100.0 - 100.0 / (1.0 + au / ad), 1)

def snapshot(prefix):
    d = {}
    tick = mt5.symbol_info_tick(SYMBOL)
    m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 1500)
    h1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 250)
    if tick is None or m1 is None or len(m1) < 100 or h1 is None or len(h1) < 10:
        return None
    price = (tick.bid + tick.ask) / 2
    if not price:
        return None
    d[prefix + "price_bid"] = round(tick.bid, 2)
    d[prefix + "price_ask"] = round(tick.ask, 2)
    d[prefix + "spread_pts"] = round(tick.ask - tick.bid, 2)
    c1 = m1["close"]; o1 = m1["open"]; hi1 = m1["high"]; lo1 = m1["low"]
    lo24, hi24 = float(np.min(lo1[-1440:])), float(np.max(hi1[-1440:]))
    d[prefix + "range24h_pct"] = round(100 * (hi24 - lo24) / price, 3)
    d[prefix + "atr14_m1"] = round(atr(hi1, lo1, c1), 2)
    d[prefix + "atr14_h1"] = round(atr(h1["high"], h1["low"], h1["close"]), 2)
    for n in (20, 50, 200):
        v = ema(c1[-max(4 * n, 200):], n)
        d[prefix + f"ema{n}_m1"] = round(v, 2)
        d[prefix + f"px_vs_ema{n}_m1"] = "above" if price > v else "below"
    ch = h1["close"][:-1]
    for n in (20, 50):
        v = ema(ch[-max(4 * n, 60):], n)
        d[prefix + f"ema{n}_h1"] = round(v, 2)
        d[prefix + f"px_vs_ema{n}_h1"] = "above" if price > v else "below"
    col, body, uw, dw = candle_anatomy(o1[-2], hi1[-2], lo1[-2], c1[-2])
    d[prefix + "m1_candle"] = col
    d[prefix + "m1_body_pts"] = round(body, 2)
    d[prefix + "m1_upwick_pts"] = round(uw, 2)
    d[prefix + "m1_downwick_pts"] = round(dw, 2)
    d[prefix + "m1_low_minus_prevlow"] = round(lo1[-2] - lo1[-3], 2)
    d[prefix + "m1_high_minus_prevhigh"] = round(hi1[-2] - hi1[-3], 2)
    col, body, uw, dw = candle_anatomy(h1["open"][-2], h1["high"][-2], h1["low"][-2], h1["close"][-2])
    d[prefix + "h1_candle"] = col
    d[prefix + "h1_body_pts"] = round(body, 2)
    d[prefix + "h1_upwick_pts"] = round(uw, 2)
    d[prefix + "h1_downwick_pts"] = round(dw, 2)
    d[prefix + "h1_higher_high"] = bool(h1["high"][-2] > h1["high"][-3])
    d[prefix + "h1_lower_low"] = bool(h1["low"][-2] < h1["low"][-3])
    d[prefix + "h1_forming"] = candle_anatomy(
        h1["open"][-1], h1["high"][-1], h1["low"][-1], h1["close"][-1])[0]
    d[prefix + "rsi14_m1"] = rsi(c1)
    d[prefix + "rsi14_h1"] = rsi(ch)
    for tf, name in ((mt5.TIMEFRAME_M5, "m5"), (mt5.TIMEFRAME_M15, "m15")):
        b = mt5.copy_rates_from_pos(SYMBOL, tf, 0, 3)
        if b is not None and len(b) >= 2:
            d[prefix + name + "_candle"] = candle_anatomy(
                b["open"][-2], b["high"][-2], b["low"][-2], b["close"][-2])[0]
            d[prefix + name + "_forming"] = candle_anatomy(
                b["open"][-1], b["high"][-1], b["low"][-1], b["close"][-1])[0]
    d[prefix + "minute_of_hour"] = datetime.now(timezone.utc).minute
    ai = mt5.account_info()
    if ai:
        d[prefix + "equity"] = ai.equity
        d[prefix + "balance"] = ai.balance
    return d

def write_journal_row(row):
    """Append a row using the FILE's existing header (never a per-row column
    list - a partial snapshot would silently shift columns otherwise)."""
    exists = os.path.exists(JOURNAL)
    if exists:
        with open(JOURNAL, "r", encoding="utf-8") as f:
            cols = next(csv.reader(f))
    else:
        lead = ["ticket", "direction", "volume", "entry_time_utc", "entry_price",
                "exit_time_utc", "exit_price", "duration_min", "profit_usd", "exit_reason",
                "worst_drawdown_usd", "worst_drawdown_pts", "best_profit_usd",
                "time_to_worst_min", "time_to_best_min", "hour_id", "positions_open_at_entry"]
        cols = lead + sorted(k for k in row if k.startswith("entry_") and k not in lead) \
                    + sorted(k for k in row if k.startswith("exit_") and k not in lead)
    with open(JOURNAL, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(row)

def in_loss(p, tick):
    if p.type == mt5.POSITION_TYPE_BUY:
        return tick.bid < p.price_open
    return tick.ask > p.price_open

def tp3_price(p):
    tgt = SPLIT_TP_USD if p.ticket in SPLIT_TICKETS else TP_USD
    dist = tgt / p.volume
    return p.price_open + dist if p.type == mt5.POSITION_TYPE_BUY else p.price_open - dist

def be_price(p):
    dist = BUFFER_USD / p.volume
    return p.price_open + dist if p.type == mt5.POSITION_TYPE_BUY else p.price_open - dist

def mid_price(a, b):
    m = (a.price_open * a.volume + b.price_open * b.volume) / (a.volume + b.volume)
    dist = BUFFER_USD / (a.volume + b.volume)
    return m + dist if a.type == mt5.POSITION_TYPE_BUY else m - dist

def reassign(st, manual, tick):
    """Recompute TP assignments. Called only when the open-ticket set changes.
    Sticky pairs: existing mid pairs whose both legs are still open are kept."""
    new_assign = {}
    for side in (mt5.POSITION_TYPE_BUY, mt5.POSITION_TYPE_SELL):
        group = sorted([p for p in manual if p.type == side], key=lambda p: (p.time, p.ticket))
        if not group:
            continue
        open_ids = {p.ticket for p in group}
        newest = group[-1]
        older = group[:-1]
        # keep sticky pairs among older
        kept = {}
        for p in older:
            a = st["assign"].get(str(p.ticket))
            if (a and a.get("mode") == "mid" and a.get("partner") in open_ids
                    and a["partner"] != newest.ticket and str(p.ticket) not in kept):
                kept[str(p.ticket)] = a
        unassigned = [p for p in older if str(p.ticket) not in kept]
        losers = [p for p in unassigned if in_loss(p, tick)]
        winners = [p for p in unassigned if not in_loss(p, tick)]
        # pair losers: deepest with shallowest
        losers.sort(key=lambda p: p.price_open,
                    reverse=(side == mt5.POSITION_TYPE_BUY))  # deepest loss first
        i, j = 0, len(losers) - 1
        while i < j:
            a, b = losers[i], losers[j]
            tp = round(mid_price(a, b), 2)
            new_assign[str(a.ticket)] = {"mode": "mid", "partner": b.ticket, "tp": tp}
            new_assign[str(b.ticket)] = {"mode": "mid", "partner": a.ticket, "tp": tp}
            say(f"RECOVERY pair: {a.ticket}@{a.price_open} + {b.ticket}@{b.price_open} -> joint TP {tp}")
            i += 1; j -= 1
        if i == j:
            p = losers[i]
            new_assign[str(p.ticket)] = {"mode": "be", "partner": None, "tp": round(be_price(p), 2)}
            say(f"RECOVERY breakeven: {p.ticket}@{p.price_open} -> TP {new_assign[str(p.ticket)]['tp']}")
        for p in winners + [newest]:
            new_assign[str(p.ticket)] = {"mode": "tp3", "partner": None, "tp": round(tp3_price(p), 2)}
        new_assign.update(kept)
    st["assign"] = new_assign

def write_market_log(manual_open):
    """One market photo per minute, trading or not - the 'what did the user
    see and skip' dataset for the future entry-clone."""
    snap = snapshot("")
    if snap is None:
        return
    row = {"time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", ""),
           "manual_positions_open": manual_open}
    row.update(snap)
    exists = os.path.exists(MARKETLOG)
    if exists:
        with open(MARKETLOG, "r", encoding="utf-8") as f:
            cols = next(csv.reader(f))   # lock to file header, never shift columns
    else:
        cols = ["time_utc", "manual_positions_open"] + sorted(snap.keys())
    with open(MARKETLOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(row)

def open_at_market(direction, volume, comment):
    """Open a market position (used ONLY by the auto hedge-freeze, user
    authorized 2026-08-22: on a confirmed H4 flip against open positions,
    open the freeze-holder so escape v2 can manage the exit)."""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None
    return mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume": round(volume, 2),
        "type": mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL,
        "price": tick.ask if direction == 1 else tick.bid,
        "deviation": 50, "comment": comment,
        "type_filling": mt5.ORDER_FILLING_IOC,
    })

def close_at_market(p, comment="OWL-hour-clean"):
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return None
    return mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": p.symbol,
        "volume": p.volume,
        "type": mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "price": tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask,
        "deviation": 50, "comment": comment,
        "type_filling": mt5.ORDER_FILLING_IOC,
    })

def _regime(tf, count):
    bars = mt5.copy_rates_from_pos(SYMBOL, tf, 0, count)
    if bars is None or len(bars) < 3:
        return 0
    mode = 0
    last_green_open = None
    last_red_open = None
    for b in bars[:-1]:                      # closed candles only
        if b['close'] > b['open']:
            last_green_open = b['open']
            if mode == 0:
                mode = 1
            elif mode == -1 and last_red_open is not None and b['close'] > last_red_open:
                mode = 1
        elif b['close'] < b['open']:
            last_red_open = b['open']
            if mode == 0:
                mode = -1
            elif mode == 1 and last_green_open is not None and b['close'] < last_green_open:
                mode = -1
    return mode

def h4_regime():
    """Confirmed-flip rule on H4 (scalp direction + hedge escape)."""
    return _regime(mt5.TIMEFRAME_H4, 200)

def d1_regime():
    """Same confirmed-flip rule on DAILY candles - the runner's trend clock
    (paper-test phase, 2026-08-22)."""
    return _regime(mt5.TIMEFRAME_D1, 400)

def closed_color(tf):
    """Color of the LAST CLOSED candle on tf: 1 green, -1 red, 0 doji/no data."""
    b = mt5.copy_rates_from_pos(SYMBOL, tf, 1, 1)
    if b is None or not len(b):
        return None
    if b["close"][0] > b["open"][0]:
        return 1
    if b["close"][0] < b["open"][0]:
        return -1
    return 0

def connect():
    if not mt5.initialize(path=TERMINAL, login=LOGIN, password=PASSWORD, server=SERVER):
        return False
    ai = mt5.account_info()
    if ai is None or ai.login != LOGIN:
        say(f"ERROR wrong account {ai.login if ai else None}, expected {LOGIN}")
        mt5.shutdown()
        return False
    mt5.symbol_select(SYMBOL, True)
    return True

def main():
    say("OWL starting (TP+recovery manager, trade scribe)")
    st = load_state()
    last_mktlog = 0.0
    # shadow-recipe state (clone step 2: log where the user's 3-step recipe
    # WOULD enter, no orders; reset each hour, max 1 fire/hour)
    sh_last_bar = 0
    sh_hour = -1
    sh_setup = None
    sh_pulled = False
    sh_fired = False
    sweep_last_bar = 0     # CROC: last processed closed M1 bar
    while True:
        try:
            if not connect():
                time.sleep(10)
                continue
            ai = mt5.account_info()
            tick = mt5.symbol_info_tick(SYMBOL)
            positions = mt5.positions_get(symbol=SYMBOL) or []
            manual = [p for p in positions if p.magic == 0]
            open_tickets = {p.ticket for p in manual}
            runner = st.get("runner") or {}
            runner_tickets = {runner.get("a"), runner.get("b")} - {None}
            split_tickets = {t for g in (st.get("splits") or [])
                             for t in (g.get("a"), g.get("b")) if t}
            SPLIT_TICKETS.clear()
            SPLIT_TICKETS.update(split_tickets)
            # --- HOUR-FLAT: close everything at each hour boundary ---
            if HOUR_FLAT and tick is not None:
                hid_now = int(tick.time) // 3600
                if st.get("flat_hour") != hid_now:
                    st["flat_hour"] = hid_now
                    save_state(st)
                    flatable = [p for p in manual if p.ticket not in runner_tickets]
                    if flatable:
                        say(f"HOUR-FLAT: hour ended -> closing {len(flatable)} position(s), win or lose")
                        for p in flatable:
                            r = close_at_market(p, "OWL-hour-flat")
                            if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                                say(f"  flat: ticket {p.ticket} ({p.profit:+.2f})")
                            else:
                                say(f"  flat FAILED ticket {p.ticket} retcode={r.retcode if r else None}")
                        positions = mt5.positions_get(symbol=SYMBOL) or []
                        manual = [p for p in positions if p.magic == 0]
                        open_tickets = {p.ticket for p in manual}
            # --- entry snapshots for new positions ---
            for p in manual:
                tkey = str(p.ticket)
                if tkey not in st["pending"]:
                    snap = snapshot("entry_")
                    hour_id = str(p.time // 3600)
                    ent = {"ticket": p.ticket,
                           "direction": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                           "volume": p.volume,
                           "entry_time_utc": datetime.utcfromtimestamp(p.time).isoformat(),
                           "entry_price": p.price_open,
                           "hour_id": hour_id,
                           "positions_open_at_entry": len(manual)}
                    if snap:
                        ent.update(snap)
                    st["pending"][tkey] = ent
                    g = st["groups"].setdefault(hour_id,
                        {"start_equity": ai.equity, "realized": 0.0, "tickets": []})
                    if p.ticket not in g["tickets"]:
                        g["tickets"].append(p.ticket)
                    save_state(st)
                    say(f"ENTRY logged: {ent['direction']} {p.volume} @ {p.price_open} ticket {p.ticket}")
                    # first sight with a TP already on it => user's own TP
                    if p.tp != 0.0 and tkey not in st["user_owned"]:
                        st["user_owned"].append(tkey)
                        say(f"ticket {p.ticket} has user TP {p.tp} at first sight - hands off")
            # --- (re)assign TPs when the set of open positions changes ---
            cur_ids = sorted(open_tickets)
            if cur_ids != st["last_tickets"] and tick is not None:
                reassign(st, manual, tick)
                st["last_tickets"] = cur_ids
                save_state(st)
            # --- HEDGE-ESCAPE v2 (2026-08-22): hedge + confirmed H4 flip ---
            buys = [p for p in manual if p.type == mt5.POSITION_TYPE_BUY]
            sells = [p for p in manual if p.type == mt5.POSITION_TYPE_SELL]
            hedge = bool(buys) and bool(sells)
            regime = h4_regime() if hedge else 0
            escape_active = hedge and regime != 0
            wrong_legs = []
            if escape_active:
                wrong_legs = buys if regime == -1 else sells
                trend_legs = sells if regime == -1 else buys
                if st.get("escape_dir") != regime:
                    st["escape_dir"] = regime
                    say(f"ESCAPE v2 armed: regime {'SELL' if regime==-1 else 'BUY'}-mode, "
                        f"wrong-way={'BUY' if regime==-1 else 'SELL'} -> BE TP; trend leg TP removed (freeze holder)")
                    save_state(st)
                for p in wrong_legs:      # wrong-way leg: breakeven escape
                    st["assign"][str(p.ticket)] = {"mode": "esc_be", "partner": None,
                                                   "tp": round(be_price(p), 2)}
                # only the OLDEST trend leg holds the freeze (no TP);
                # newer trend-side positions keep normal scalp management
                # (2026-08-22 fix: don't hijack the user's ongoing scalps)
                holder = min(trend_legs, key=lambda p: p.time)
                st["assign"][str(holder.ticket)] = {"mode": "hold", "partner": None, "tp": 0.0}
            elif st.get("escape_dir"):
                st["escape_dir"] = 0
                if tick is not None:
                    reassign(st, manual, tick)   # restore normal management
                say("ESCAPE v2 disarmed (hedge resolved) - normal management restored")
                save_state(st)
            # deadline: at each H1 close, if the closed candle went against the
            # escape, cut the wrong-way leg at market (sanctioned small red)
            if tick is not None:
                hid_h1 = int(tick.time) // 3600
                if st.get("h1_seen") != hid_h1:
                    st["h1_seen"] = hid_h1
                    save_state(st)
                    if escape_active and wrong_legs:
                        b = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 1, 1)
                        if b is not None and len(b):
                            red = b["close"][0] < b["open"][0]
                            green = b["close"][0] > b["open"][0]
                            if (regime == -1 and red) or (regime == 1 and green):
                                say(f"ESCAPE v2 deadline: H1 closed against the escape "
                                    f"-> cutting {len(wrong_legs)} wrong-way leg(s) at market")
                                for p in wrong_legs:
                                    r = close_at_market(p, "OWL-escape-cut")
                                    if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                                        say(f"  escape cut: ticket {p.ticket} ({p.profit:+.2f})")
                                    else:
                                        say(f"  escape cut FAILED ticket {p.ticket} "
                                            f"retcode={r.retcode if r else None} - will retry next close")
            # --- enforce assignments ---
            for p in manual:
                tkey = str(p.ticket)
                if p.ticket in runner_tickets:
                    continue          # runner legs have their own manager
                if tkey in st["user_owned"]:
                    continue
                a = st["assign"].get(tkey)
                if a is None:
                    continue
                # user changed a TP Owl had set -> hands off
                owned = st["owned"].get(tkey)
                if (p.tp != 0.0 and owned is not None and abs(p.tp - owned) > TP_TOL
                        and abs(p.tp - a["tp"]) > TP_TOL):
                    st["user_owned"].append(tkey)
                    say(f"ticket {p.ticket} TP changed by user to {p.tp} - hands off")
                    save_state(st)
                    continue
                if abs((p.tp or 0.0) - a["tp"]) > TP_TOL:
                    r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": p.ticket,
                                        "symbol": p.symbol, "sl": p.sl, "tp": a["tp"]})
                    if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                        st["tp_set_total"] += 1
                        st["owned"][tkey] = a["tp"]
                        save_state(st)
                        say(f"TP set ({a['mode']}): ticket {p.ticket} -> {a['tp']}")
                    else:
                        say(f"TP set FAILED ({a['mode']}) ticket {p.ticket} "
                            f"tp={a['tp']} retcode={r.retcode if r else None}")
            # --- exits: journal rows ---
            for tkey in list(st["pending"].keys()):
                if int(tkey) in open_tickets:
                    continue
                ent = st["pending"].pop(tkey)
                st["assign"].pop(tkey, None)
                st["owned"].pop(tkey, None)
                if tkey in st["user_owned"]:
                    st["user_owned"].remove(tkey)
                deals = mt5.history_deals_get(position=int(tkey)) or []
                closing = [dl for dl in deals if dl.entry == mt5.DEAL_ENTRY_OUT]
                row = dict(ent)
                if closing:
                    dl = closing[-1]
                    row["exit_time_utc"] = datetime.utcfromtimestamp(dl.time).isoformat()
                    row["exit_price"] = dl.price
                    row["profit_usd"] = sum(x.profit for x in closing)
                    cm = (dl.comment or "").lower()
                    row["exit_reason"] = ("runner" if "owl-runner" in cm else
                                          "sweep_stop" if "owl-sweep" in cm else
                                          "hour_flat" if "owl-hour-flat" in cm else
                                          "escape_cut" if "owl-escape" in cm else
                                          "hour_clean" if "owl-hour" in cm else
                                          "tp" if "tp" in cm else
                                          "sl" if "sl" in cm else
                                          "stopout" if "so" in cm else "manual")
                    g = st["groups"].get(ent.get("hour_id", ""))
                    if g is not None:
                        g["realized"] += row["profit_usd"]
                    t0 = datetime.fromisoformat(ent["entry_time_utc"])
                    t1 = datetime.utcfromtimestamp(dl.time)
                    row["duration_min"] = round((t1 - t0).total_seconds() / 60, 1)
                    # worst/best moment during the trade (from M1 bars, UTC-aware)
                    try:
                        bars = mt5.copy_rates_range(
                            SYMBOL, mt5.TIMEFRAME_M1,
                            t0.replace(tzinfo=timezone.utc) - timedelta(minutes=1),
                            t1.replace(tzinfo=timezone.utc) + timedelta(minutes=1))
                        if bars is not None and len(bars):
                            lows = np.asarray(bars["low"], dtype=float)
                            highs = np.asarray(bars["high"], dtype=float)
                            lo, hi = float(lows.min()), float(highs.max())
                            ep = ent["entry_price"]; vol = ent["volume"]
                            if ent["direction"] == "BUY":
                                mae, mfe = max(0.0, ep - lo), max(0.0, hi - ep)
                                iw, ib = int(lows.argmin()), int(highs.argmax())
                            else:
                                mae, mfe = max(0.0, hi - ep), max(0.0, ep - lo)
                                iw, ib = int(highs.argmax()), int(lows.argmin())
                            row["worst_drawdown_usd"] = round(-mae * vol, 2)
                            row["worst_drawdown_pts"] = round(-mae, 1)
                            row["best_profit_usd"] = round(mfe * vol, 2)
                            e0 = t0.replace(tzinfo=timezone.utc).timestamp()
                            row["time_to_worst_min"] = round((int(bars["time"][iw]) - e0) / 60, 1)
                            row["time_to_best_min"] = round((int(bars["time"][ib]) - e0) / 60, 1)
                    except Exception:
                        pass
                else:
                    row["exit_reason"] = "unknown"
                snap = snapshot("exit_")
                if snap:
                    row.update(snap)
                write_journal_row(row)
                st["trades_logged"] += 1
                save_state(st)
                say(f"EXIT logged: ticket {tkey} {row.get('exit_reason')} "
                    f"profit {row.get('profit_usd')} dur {row.get('duration_min')}min")
            # --- hour-group cleanup: past-hour groups close when net positive ---
            # (suspended while a hedge-escape is active: nothing may pop the freeze)
            if tick is not None and not escape_active:
                cur_hour = str(int(tick.time) // 3600)
                for hid in list(st["groups"].keys()):
                    g = st["groups"][hid]
                    if hid >= cur_hour:
                        continue           # current (or future) hour - never touch
                    members = [p for p in manual if p.ticket in g["tickets"]
                               and p.ticket not in runner_tickets]
                    if not members:
                        del st["groups"][hid]   # fully closed group - forget it
                        save_state(st)
                        continue
                    floating = sum(p.profit + p.swap for p in members)
                    total = g["realized"] + floating
                    needed = max(CLEAN_MIN_USD, CLEAN_PTS_HEADROOM * sum(p.volume for p in members))
                    if total >= needed:
                        say(f"HOUR-GROUP {hid} cleanup: realized {g['realized']:.2f} "
                            f"+ floating {floating:.2f} = {total:.2f} >= {needed:.2f} "
                            f"-> closing {len(members)} position(s)")
                        for p in members:
                            r = close_at_market(p)
                            if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                                say(f"  closed ticket {p.ticket} @ market ({p.profit:+.2f})")
                            else:
                                say(f"  close FAILED ticket {p.ticket} "
                                    f"retcode={r.retcode if r else None} - will retry")
            if time.time() - last_mktlog >= 60:
                write_market_log(len(manual))
                last_mktlog = time.time()
                # two-clock watch: flag D1 flips + H4/D1 alignment changes
                # (paper-test phase of the user's Aligned Partial Runner)
                d1 = d1_regime()
                h4r = h4_regime()
                # --- AUTO HEDGE-FREEZE (user authorized 2026-08-22): on a
                # confirmed H4 flip, if open positions are now wrong-way and
                # the trend side doesn't cover them, open the freeze-holder ---
                prev_h4 = st.get("h4_regime_prev", 0)
                if h4r != 0 and prev_h4 != 0 and h4r != prev_h4 and not HOUR_FLAT:
                    wrong = [p for p in manual
                             if (p.type == mt5.POSITION_TYPE_BUY) != (h4r == 1)]
                    trend_vol = sum(p.volume for p in manual
                                    if (p.type == mt5.POSITION_TYPE_BUY) == (h4r == 1))
                    need = sum(p.volume for p in wrong) - trend_vol
                    if wrong and need > 0.005:
                        say(f"AUTO HEDGE: H4 flipped {'UP' if h4r==1 else 'DOWN'} with "
                            f"{len(wrong)} wrong-way position(s) open -> opening freeze-holder "
                            f"{'BUY' if h4r==1 else 'SELL'} {need:.2f} lots")
                        r = open_at_market(h4r, need, "OWL-hedge-freeze")
                        if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                            say(f"AUTO HEDGE opened OK - escape v2 will now manage the exit")
                        else:
                            say(f"AUTO HEDGE FAILED retcode={r.retcode if r else None} "
                                f"- positions remain unhedged, user attention needed")
                if h4r != 0:
                    st["h4_regime_prev"] = h4r
                    save_state(st)
                if d1 != 0 and st.get("d1_regime") != d1:
                    if st.get("d1_regime") in (1, -1):
                        say(f"D1 FLIP: daily trend is now {'UP' if d1 == 1 else 'DOWN'}"
                            f" - if a runner leg is riding, this is its harvest signal")
                    st["d1_regime"] = d1
                    save_state(st)
                new_align = 0
                if d1 != 0 and h4r == d1:
                    new_align = d1
                if st.get("aligned") != new_align:
                    if new_align != 0:
                        say(f"CLOCKS ALIGNED: H4 and D1 both say "
                            f"{'UP - next BUY scalp is the runner candidate (2x0.01)' if new_align == 1 else 'DOWN - next SELL scalp is the runner candidate (2x0.01)'}")
                    elif st.get("aligned") in (1, -1):
                        say("CLOCKS DIVERGED: H4 and D1 disagree again - no new runner candidates")
                    st["aligned"] = new_align
                    save_state(st)
                # --- PAPER RUNNER: automatic no-money simulation of the
                # Aligned Partial Runner (user request 2026-08-22) ---
                pr = st.get("paper_runner")
                tot = st.setdefault("paper_totals",
                                    {"attempts": 0, "broke": 0, "be": 0, "rides": 0, "pnl": 0.0})
                bars2 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 3)
                if bars2 is not None and len(bars2) and tick is not None:
                    hi2 = float(max(b["high"] for b in bars2))
                    lo2 = float(min(b["low"] for b in bars2))
                    px = tick.bid
                    if pr is None and new_align != 0 and st.get("aligned_last_runner") != new_align:
                        d = new_align
                        ep = tick.ask if d == 1 else tick.bid
                        st["paper_runner"] = {"dir": d, "entry": ep, "stage": 0,
                                              "opened": datetime.now(timezone.utc).isoformat()}
                        st["aligned_last_runner"] = new_align
                        tot["attempts"] += 1
                        say(f"PAPER RUNNER opened: {'BUY' if d==1 else 'SELL'} 2x0.01 @ {ep:.2f} "
                            f"(virtual, no real money)")
                        # --- REAL RUNNER (user authorized 2026-08-23) ---
                        if RUNNER_LIVE and not st.get("runner"):
                            ra = open_at_market(d, 0.01, "OWL-runner-A")
                            rb = open_at_market(d, 0.01, "OWL-runner-B")
                            if (ra is not None and ra.retcode == mt5.TRADE_RETCODE_DONE and
                                    rb is not None and rb.retcode == mt5.TRADE_RETCODE_DONE):
                                st["runner"] = {"dir": d, "a": ra.order, "b": rb.order,
                                                "state": "phase1"}
                                say(f"REAL RUNNER opened: {'BUY' if d==1 else 'SELL'} 2x0.01 "
                                    f"(A={ra.order}, B={rb.order}) - phase 1")
                            else:
                                say(f"REAL RUNNER open FAILED "
                                    f"(a={ra.retcode if ra else None}, b={rb.retcode if rb else None})")
                        save_state(st)
                    elif pr is not None:
                        d = pr["dir"]; ep = pr["entry"]
                        if pr["stage"] == 0:
                            if new_align != d:      # alignment broke pre-TP
                                pnl = (px - ep) * 0.02 * d
                                tot["broke"] += 1; tot["pnl"] += pnl
                                say(f"PAPER RUNNER broke pre-TP: {pnl:+.2f} (virtual). "
                                    f"Ledger: {tot['pnl']:+.2f} over {tot['attempts']} attempts")
                                st["paper_runner"] = None
                            elif (hi2 >= ep + 150) if d == 1 else (lo2 <= ep - 150):
                                pr["stage"] = 1
                                pr["sl"] = ep + d * 5.0
                                pr["banked"] = 1.50
                                say(f"PAPER RUNNER banked $1.50 (leg A TP), leg B now "
                                    f"risk-free with BE stop @ {pr['sl']:.2f} (virtual)")
                            save_state(st)
                        else:
                            if (lo2 <= pr["sl"]) if d == 1 else (hi2 >= pr["sl"]):
                                pnl = pr["banked"] + 0.05
                                tot["be"] += 1; tot["pnl"] += pnl
                                say(f"PAPER RUNNER BE-stopped: total {pnl:+.2f} (virtual). "
                                    f"Ledger: {tot['pnl']:+.2f} over {tot['attempts']} attempts")
                                st["paper_runner"] = None
                            elif d1 != 0 and d1 != d:
                                pnl = pr["banked"] + (px - ep) * 0.01 * d
                                tot["rides"] += 1; tot["pnl"] += pnl
                                say(f"PAPER RUNNER RODE to D1 flip: total {pnl:+.2f} (virtual)! "
                                    f"Ledger: {tot['pnl']:+.2f} over {tot['attempts']} attempts")
                                st["paper_runner"] = None
                            save_state(st)
                    if new_align == 0:
                        st["aligned_last_runner"] = 0
            # --- SHADOW recipe watcher (no orders, log-only) ---
            b3 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 3)
            if b3 is not None and len(b3) >= 3:
                cb, pb = b3[-2], b3[-3]        # last closed bar + the one before
                cbt = int(cb["time"])
                if cbt != sh_last_bar:
                    sh_last_bar = cbt
                    hr = cbt // 3600
                    if hr != sh_hour:
                        sh_hour = hr
                        sh_setup = None
                        sh_pulled = False
                        sh_fired = False
                    al = st.get("aligned", 0)
                    def _auto_fire(direction):
                        if not AUTO_ENTRY:
                            return
                        if escape_active:
                            say("AUTO ENTRY skipped: escape active (red light)")
                            return
                        n_stack = (len([p for p in manual
                                        if p.ticket not in runner_tickets
                                        and p.ticket not in split_tickets])
                                   + len(st.get("splits") or []))
                        if n_stack >= AUTO_MAX_STACK:
                            say(f"AUTO ENTRY skipped: stack {n_stack} >= {AUTO_MAX_STACK}")
                            return
                        if ai.balance < AUTO_MIN_BAL:
                            say(f"AUTO ENTRY skipped: balance {ai.balance:.2f} < {AUTO_MIN_BAL}")
                            return
                        if LONDON_OFF and tick is not None:
                            h_utc = (int(tick.time) // 3600) % 24
                            if 8 <= h_utc < 16:
                                say(f"AUTO ENTRY skipped: London hours "
                                    f"({h_utc:02d}:xx UTC, no entries 08-16)")
                                return
                        if DIP_GATE:
                            h1c = closed_color(mt5.TIMEFRAME_H1)
                            m15c = closed_color(mt5.TIMEFRAME_M15)
                            m5c = closed_color(mt5.TIMEFRAME_M5)
                            if None in (h1c, m15c, m5c):
                                say("AUTO ENTRY skipped: dip gate has no candle data")
                                return
                            if not (h1c == direction and m15c == -direction
                                    and m5c == -direction):
                                say(f"AUTO ENTRY skipped: dip gate "
                                    f"(H1={h1c} M15={m15c} M5={m5c}, "
                                    f"need {direction}/{-direction}/{-direction})")
                                return
                        if SPLIT_TP:
                            half = round(AUTO_LOTS / 2, 2)
                            ra = open_at_market(direction, half, "OWL-split-A")
                            rb = open_at_market(direction, half, "OWL-split-B")
                            oka = ra is not None and ra.retcode == mt5.TRADE_RETCODE_DONE
                            okb = rb is not None and rb.retcode == mt5.TRADE_RETCODE_DONE
                            if oka or okb:
                                st.setdefault("splits", []).append(
                                    {"a": ra.order if oka else None,
                                     "b": rb.order if okb else None,
                                     "dir": direction, "t": time.time()})
                                save_state(st)
                                say(f"AUTO ENTRY (dip+split): recipe fired -> "
                                    f"{'BUY' if direction == 1 else 'SELL'} 2x{half} "
                                    f"(A={ra.order if oka else 'FAIL'}, "
                                    f"B={rb.order if okb else 'FAIL'})")
                            else:
                                say(f"AUTO ENTRY FAILED (a={ra.retcode if ra else None}, "
                                    f"b={rb.retcode if rb else None})")
                            return
                        r = open_at_market(direction, AUTO_LOTS, "OWL-auto-entry")
                        if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                            say(f"AUTO ENTRY: recipe fired -> "
                                f"{'BUY' if direction == 1 else 'SELL'} {AUTO_LOTS} opened")
                        else:
                            say(f"AUTO ENTRY FAILED retcode={r.retcode if r else None}")
                    if al == 1 and not sh_fired:
                        if sh_setup is not None and sh_pulled and cb["close"] > sh_setup:
                            sh_fired = True
                            say(f"SHADOW ENTRY: recipe fired -> would BUY @ ~{cb['close']:.2f} "
                                f"(setup {sh_setup:.2f})")
                            _auto_fire(1)
                        elif (pb["close"] > pb["open"] and cb["close"] > cb["open"]
                              and cb["high"] > pb["high"]):
                            sh_setup = float(cb["high"])
                            sh_pulled = cb["low"] <= pb["low"]
                        elif sh_setup is not None and cb["low"] <= pb["low"]:
                            sh_pulled = True
                    elif al == -1 and not sh_fired:
                        if sh_setup is not None and sh_pulled and cb["close"] < sh_setup:
                            sh_fired = True
                            say(f"SHADOW ENTRY: recipe fired -> would SELL @ ~{cb['close']:.2f} "
                                f"(setup {sh_setup:.2f})")
                            _auto_fire(-1)
                        elif (pb["close"] < pb["open"] and cb["close"] < cb["open"]
                              and cb["low"] < pb["low"]):
                            sh_setup = float(cb["low"])
                            sh_pulled = cb["high"] >= pb["high"]
                        elif sh_setup is not None and cb["high"] >= pb["high"]:
                            sh_pulled = True
            # --- CROC (Range Sweep V1, user authorized 2026-08-24) ---
            # range = last 12 closed H1s; M1 pokes outside then closes back
            # inside -> enter. No light/session filter (pure form). 1/hour.
            if SWEEP_ENTRY and tick is not None and not escape_active:
                cb1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 1)
                hrng = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 1, SWEEP_RANGE_N)
                if (cb1 is not None and len(cb1) and hrng is not None
                        and len(hrng) == SWEEP_RANGE_N):
                    bar = cb1[0]
                    bt = int(bar["time"])
                    if bt != sweep_last_bar:
                        sweep_last_bar = bt
                        hid = bt // 3600
                        if st.get("sweep_flag_hour") != hid:
                            st["sweep_flag_hour"] = hid
                            st["swept_lo"] = False
                            st["swept_hi"] = False
                        rhi = float(max(x["high"] for x in hrng))
                        rlo = float(min(x["low"] for x in hrng))
                        if rhi - rlo > SWEEP_MIN_RANGE:
                            if float(bar["low"]) < rlo:
                                st["swept_lo"] = True
                            if float(bar["high"]) > rhi:
                                st["swept_hi"] = True
                            bo, bc = float(bar["open"]), float(bar["close"])
                            d = 0
                            if st.get("swept_lo") and bc > rlo and bc > bo:
                                d = 1
                            elif st.get("swept_hi") and bc < rhi and bc < bo:
                                d = -1
                            if d != 0 and SWEEP_EARLY_ONLY and (bt // 60) % 60 >= 30:
                                d = 0     # late half of the hour: no new bites
                            if d != 0 and st.get("sweep_hour") != hid:
                                n_stack = (len([p for p in manual
                                                if p.ticket not in runner_tickets
                                                and p.ticket not in split_tickets])
                                           + len(st.get("splits") or []))
                                if n_stack >= AUTO_MAX_STACK:
                                    say(f"CROC skipped: stack {n_stack} >= {AUTO_MAX_STACK}")
                                elif ai.balance < AUTO_MIN_BAL:
                                    say(f"CROC skipped: balance {ai.balance:.2f} < {AUTO_MIN_BAL}")
                                else:
                                    r = open_at_market(d, SWEEP_LOTS, "OWL-sweep")
                                    r2 = open_at_market(d, SWEEP_LOTS, "OWL-sweep-B")
                                    okb = r2 is not None and r2.retcode == mt5.TRADE_RETCODE_DONE
                                    if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                                        st["sweep_hour"] = hid
                                        st.setdefault("splits", []).append(
                                            {"a": r.order, "b": r2.order if okb else None,
                                             "dir": d, "t": time.time(), "sweep": True})
                                        st["swept_lo"] = False
                                        st["swept_hi"] = False
                                        say(f"CROC ENTRY: {'BUY' if d == 1 else 'SELL'} "
                                            f"{SWEEP_LOTS} after sweep+reclaim of range "
                                            f"{rlo:.2f}/{rhi:.2f} (ticket {r.order})")
                                    else:
                                        say(f"CROC ENTRY FAILED retcode={r.retcode if r else None}")
                        save_state(st)
            # --- CROC 30-min time stop ---
            for grp in (st.get("splits") or []):
                if not grp.get("sweep"):
                    continue
                if time.time() - grp.get("t", 0) < SWEEP_STOP_SEC:
                    continue
                for _tk in (grp.get("a"), grp.get("b")):
                    p = next((q for q in manual if q.ticket == _tk), None)
                    if p is None:
                        continue
                    r = close_at_market(p, "OWL-sweep-stop")
                    if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                        say(f"CROC time-stop: ticket {p.ticket} closed ({p.profit:+.2f}) at 30min")
                    else:
                        say(f"CROC time-stop FAILED ticket {p.ticket} "
                            f"retcode={r.retcode if r else None}")
            # --- SPLIT group bookkeeping (TPs handled by normal recovery via
            # tp3_price's $1.50 split target; groups only count the stack) ---
            if st.get("splits"):
                # grace period: the entry's legs appear in `manual` only on the
                # NEXT loop pass (this pass's position list predates the order),
                # so never drop a group younger than 2 minutes
                keep = [g for g in st["splits"]
                        if any(q.ticket in (g.get("a"), g.get("b")) for q in manual)
                        or time.time() - g.get("t", 0) < 120]
                if len(keep) != len(st["splits"]):
                    st["splits"] = keep
                    save_state(st)
            # --- REAL RUNNER management ---
            if st.get("runner"):
                rn = st["runner"]
                d = rn["dir"]
                pa = next((p for p in manual if p.ticket == rn.get("a")), None)
                pb = next((p for p in manual if p.ticket == rn.get("b")), None)
                if pb is None:
                    if rn["state"] == "riding":
                        say("REAL RUNNER finished (leg B closed - SL shakeout or harvest filled)")
                    st["runner"] = None
                    save_state(st)
                elif rn["state"] == "phase1":
                    if pa is not None and pa.tp == 0.0:
                        tp_a = round(pa.price_open + d * 150.0, 2)
                        r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": pa.ticket,
                                            "symbol": SYMBOL, "sl": pa.sl, "tp": tp_a})
                        if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                            say(f"REAL RUNNER: leg A TP set at {tp_a}")
                    if st.get("aligned", 0) != d:
                        say("REAL RUNNER: alignment broke in phase 1 -> closing both legs")
                        for p in (pa, pb):
                            if p is not None:
                                close_at_market(p, "OWL-runner-abort")
                        st["runner"] = None
                        save_state(st)
                    elif pa is None:      # leg A gone = banked its $1.50
                        slb = round(pb.price_open, 2)
                        r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": pb.ticket,
                                            "symbol": SYMBOL, "sl": slb, "tp": 0.0})
                        if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                            rn["state"] = "riding"
                            say(f"REAL RUNNER: leg A banked! Leg B risk-free, SL @ {slb} - riding the daily clock")
                            save_state(st)
                elif rn["state"] == "riding":
                    d1_now = st.get("d1_regime", 0)
                    if d1_now != 0 and d1_now != d:
                        say(f"REAL RUNNER: D1 flipped -> harvesting leg B ({pb.profit:+.2f})")
                        close_at_market(pb, "OWL-runner-harvest")
                        st["runner"] = None
                        save_state(st)
            n_pairs = sum(1 for a in st["assign"].values() if a["mode"] == "mid") // 2
            n_be = sum(1 for a in st["assign"].values() if a["mode"] == "be")
            with open(ALIVE, "w") as f:
                json.dump({
                    "alive_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", ""),
                    "bot": "OWL-raw-CROC (DEMO 81725152, full size)",
                    "watches": "magic 0 (manual) on " + SYMBOL,
                    "tp_usd": TP_USD, "sl": "never (user request)",
                    "recovery": f"{n_pairs} pair(s), {n_be} breakeven solo(s)",
                    "hour_groups_open": len(st["groups"]),
                    "escape_active": bool(escape_active),
                    "hour_flat": HOUR_FLAT,
                    "dip_split": f"gate={DIP_GATE} split={SPLIT_TP} "
                                 f"london_off={LONDON_OFF} "
                                 f"groups_open={len(st.get('splits') or [])}",
                    "croc": f"sweep={SWEEP_ENTRY} lots={SWEEP_LOTS} "
                            f"range={SWEEP_RANGE_N}xH1 stop={SWEEP_STOP_SEC // 60}min",
                    "runner": (st.get("runner") or {}).get("state", "none"),
                    "d1_regime": {1: "UP", -1: "DOWN"}.get(st.get("d1_regime"), "unknown"),
                    "clocks_aligned": {1: "UP", -1: "DOWN"}.get(st.get("aligned"), "no"),
                    "paper_runner": ("none" if not st.get("paper_runner") else
                                     f"{'BUY' if st['paper_runner']['dir']==1 else 'SELL'} "
                                     f"stage{st['paper_runner']['stage']}"),
                    "paper_ledger": round(st.get("paper_totals", {}).get("pnl", 0.0), 2),
                    "manual_positions_open": len(manual),
                    "tp_set_total": st["tp_set_total"],
                    "trades_logged": st["trades_logged"],
                    "equity": ai.equity, "balance": ai.balance,
                }, f)
        except Exception:
            say("ERROR " + traceback.format_exc().replace("\n", " | "))
            time.sleep(10)
        time.sleep(2)

if __name__ == "__main__":
    main()
