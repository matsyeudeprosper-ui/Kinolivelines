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

LOGIN = 134499778
TERMINAL = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
SYMBOL = "BTCUSDm"
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
AUTO_ENTRY = False         # 2026-08-27 user: WOLF RETIRED (weak link, -$2-3/mo
                           # at true costs; -$1.90 actual over 5 live hunts).
                           # The recipe experiment continues via the Kingfisher
                           # on demo2. Original note: the Owl
                           # trades the user's 3-step recipe itself, but ONLY:
                           # green light (H4==D1), no active escape, stack < 3,
                           # max 1 entry/hour, balance >= $50. Yellow light =
                           # bot stands aside (user may still trade by hand).
AUTO_LOTS = 0.02
AUTO_MAX_STACK = 3
AUTO_MIN_BAL = 50.0
DIP_GATE = True            # 2026-08-23 user: dip-in-trend gate on auto entries.
                           # BUY only if last closed H1 green AND M15 red AND
                           # M5 red (mirror for SELL). Backtest: best per-trade
                           # coin found (-3.1c); with split TP the combo is the
                           # first positive fast config (+$1.60/mo, 0 deaths).
SPLIT_TP = True            # 2026-08-23 user: split entry - 2x0.01 instead of
                           # 1x0.02. CORRECTED 2026-08-24: the backtest-positive
                           # design is BOTH legs TP +150pts ($1.50 each) with
                           # the normal recovery system managing them (a losing
                           # leg walks out at breakeven) - NOT fixed +75/+150.
                           # Split legs use SPLIT_TP_USD as their tp3 target and
                           # are swept by hour-flat like everything else.
SPLIT_TP_USD = 1.50        # per-leg prize: $1.50 / 0.01 lot = +150 pts
SPLIT_TICKETS = set()      # refreshed each loop; read by tp3_price()
LONDON_OFF = True          # 2026-08-24 user-approved: NO new auto entries
                           # 08-16 UTC (London). Session backtest by ENTRY hour:
                           # London = -2.2c/trade, negative 2/3 eras; without it
                           # +$2.06/mo and ALL 3 eras positive (first ever).
                           # Asia removal tested and REJECTED (NY-only worse).
SWEEP_ENTRY = False        # 2026-08-27 user: ALL auto bots moved to DEMO
                           # accounts for monitored validation. Live Croc
                           # retired at +$7.61/16 hunts. The Croc lives on at
                           # full size on the Pro and Raw demos.
                           # Original note: Range Sweep V1 at HALF size.
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
KINO_ENTRY = True          # 2026-08-31 user: auto-trade THEIR entry system.
                           # M1 only. UP: 2 consecutive greens, 2nd CLOSES
                           # above 1st's high = leg born; the leg's PEAK
                           # becomes official when a candle CLOSES below the
                           # last green's low; when a later M1 CLOSES back
                           # above that peak -> BUY (entry at the return to
                           # the proven extreme). Mirror for SELL. SL = the
                           # pullback's dip/peak, TP near-1:1 (same discount
                           # as RECOV). Guarded by the two-door chains like
                           # any page. NO page/hour caps (user rule); only
                           # the 0.04 chain gate + $100/page cap. Base lot:
KINO_LOTS = 0.02           # page base lot (0.01 below the soft floor)
PAGE_RISK_USD = 3.0        # 2026-09-04 user, v2: lots do NOT scale.
                           # Target risk $3 at 0.02 lots, half ($1.50)
                           # at 0.01. A wall too far to fit the target
                           # (risk > 1.5x) SKIPS the page entirely.
                           # Fighters keep their ladder untouched.
MANUAL_HANDS_OFF = True    # 2026-08-25 user: NEVER modify/close/TP the
                           # user's own hand trades. Bot-opened positions
                           # (comment OWL-*) keep full management. Hand trades
                           # are only JOURNALED. They also no longer count
                           # toward the auto stack cap.
def is_bot_pos(p):
    return (p.comment or "").startswith("OWL-")

RECOV_ENTRY = True         # 2026-08-31 user spec: automated RECOVERY CHAIN.
                           # When a trade (user's hand trade or a chain link)
                           # exits by SL: wait for an M1 candle to CLOSE beyond
                           # the SL line, then open the OPPOSITE direction at
                           # last lot + 0.01. New SL = the peak/dip the breaking
                           # leg created (M1 extreme since the stopped trade's
                           # entry). TP = same distance (1:1 RR). If the chain
                           # link also SLs, repeat. Chain stops when the next
                           # link's risk would reach $100, or on any TP/manual
                           # close. One chain at a time. Watch expires after
                           # 60 min without confirmation.
RECOV_STEP = 0.01
RECOV_MAX_RISK_USD = 100.0
DEEP_LOT = 0.04            # 2026-09-01 user "build both": fighters at/above
                           # this lot get the two deep-fighter rules:
RATCHET_LOCK = 0.40        # profit >= 40% of prize -> wall moves to entry
RATCHET_BANK = 0.70        # profit >= 70% of prize -> bank at market
HEAL_EXTRA_USD = 3.0       # heal target = page losses repaid + this
MAX_OPEN_PAGES = 3         # 2026-09-01 user: never more than 3 open Owl
                           # trades (pages + fighters) at once; extra doors
                           # wait their turn.
GROUP_HEAL_ENABLED = False  # 2026-09-01 user: "rethink it later, dont
                           # apply yet" - dormant until re-decided.
GROUP_HEAL_PCT = 0.10      # 2026-09-01 user "the pain should pay off":
GROUP_HEAL_MIN = 5.0       # group heal fires when floating profit covers
                           # ALL fighting pages' losses PLUS a reward of
                           # 10% of those losses (min $5) - the army comes
                           # home whole AND paid.
RECOV_MIN_WALL_PTS = 60.0  # 2026-09-01 user ("do the 1"): raised from
                           # 10 after the midnight corridor lesson -
                           # walls inside the noise die by accident and
                           # the spread eats the micro-prizes. No entry
                           # or chain link unless the wall is >= 60pts.
PARTIAL_FRAC = 0.85        # 2026-09-03 user: at 85% of prize, close HALF
                           # (0.01 steps, so lots >= 0.02 only). Measured on
                           # the 124-trade replay: +$62 vs +$42 for lock40
                           # alone; a near-miss round trip still pays half.
                           # Deep fighters (>= DEEP_LOT) keep their full
                           # 70% bank instead - do not stack both.
BUFFER_USD = 0.10          # guaranteed min profit on breakeven/midpoint exits
CLEAN_PTS_HEADROOM = 50.0  # hour-clean: group must be up 50pts-worth per lot of volume
                           # (>= ~2x the worst observed check-to-fill slippage, which
                           # turned a +0.12 check into a -0.44 close on 2026-08-21)
CLEAN_MIN_USD = 1.00       # ...and never less than $1 total
TP_TOL = 1.0               # pts tolerance before (re)sending a TP modify
DIR = r"C:\Projects\KinoliveLines\live"
LOG = os.path.join(DIR, "owl_manual.log")
ALIVE = os.path.join(DIR, "owl_manual_alive.json")
STATE = os.path.join(DIR, "owl_manual_state.json")
JOURNAL = os.path.join(DIR, "owl_manual_journal.csv")
MARKETLOG = os.path.join(DIR, "owl_market_log.csv")

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
    st.setdefault("bal_seen", 0)        # epoch of last processed deposit/
                                        # withdrawal deal (deposit watcher)
    st.setdefault("kino", {"up": {}, "dn": {}})  # peak/dip detector state
    st.setdefault("kino_tickets", [])   # open KINO entries (page trades)
    st.setdefault("kino_walls", {})     # ticket(str) -> [sl, tp] babysitter
    _bf = {"1047817831": 66.02, "1047817853": 27.60,
           "1047817902": 60.25}   # one-time ledger backfill (2026-09-01)
    for _k, _v in _bf.items():
        _lk = (st.get("recov_links") or {}).get(_k)
        if _lk is not None and not _lk.get("loss"):
            _lk["loss"] = _v
    st.setdefault("wx", {"ls": 0, "forced": False})  # weather v2:
                                        # real-loss streak + forced shelter
    st.setdefault("recov_watches", [])  # armed watches, one per chain:
                                        # [{dir, sl, lot, t0, t_sl, chain}]
    st.setdefault("recov_links", {})    # open links: ticket(str) ->
                                        # {sl, tp, lot, chain}
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

def close_at_market(p, comment="OWL-hour-clean", volume=None):
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return None
    return mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": p.symbol,
        "volume": round(volume if volume else p.volume, 2),
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

def owl_dir_conflict(direction, manual, st):
    """RETIRED (user 2026-08-31 final: "pages can go opposite directions
    that's fine") - the one-page-at-a-time 0.04 gate governs instead.
    Kept as a stub so call sites stay harmless."""
    return None

def same_signal_taken(direction, entry_px, manual, st, pts=100.0):
    """One signal = one trade (user 2026-09-01: "the signals should not
    be at the same level"): if an OWL position (kino page or chain link)
    is already open in the SAME direction from within `pts` points of
    this entry, the signal is already taken - do not duplicate it."""
    own = ({int(k) for k in (st.get("recov_links") or {})}
           | set(st.get("kino_tickets") or []))
    for p in manual:
        if p.ticket in own:
            d = 1 if p.type == mt5.POSITION_TYPE_BUY else -1
            if d == direction and abs(p.price_open - entry_px) <= pts:
                return p.ticket
    return None


def kino_open(direction, wall, st, ai, manual, runner_tickets,
              split_tickets, recov_tickets, conf_bar, fired=None):
    """Open one KINO entry (the user's peak/dip-return system). Guards:
    max 2 pages (hand + kino, chains excluded), 1 fire/hour, balance,
    min wall distance. SL = wall, TP = near-1:1 with the strength discount.
    Returns the ticket or None."""
    # ONE PAGE AT A TIME (user 2026-08-31 final + clarification): the
    # 0.04 lot UNLOCKS the next page. Only the LAST active Owl page is
    # checked: if it is still below 0.04, no new page; once it reaches
    # 0.04 (or finishes), a new page may start - older pages don't block.
    # User hand trades and their chains never count. Direction is free.
    _links = st.get("recov_links") or {}
    _watches = st.get("recov_watches") or []
    _stage = None
    for _pg in reversed(st.get("kino_born") or []):
        _pos = next((p for p in manual if p.ticket == _pg), None)
        if _pos is not None:
            _stage = float(_pos.volume)
            break
        _ln = next((v for v in _links.values() if v.get("kino")
                    and str(v.get("chain")) == str(_pg)), None)
        if _ln is not None:
            _stage = float(_ln.get("lot", 0))
            break
        _wt = next((w for w in _watches if w.get("kino")
                    and str(w.get("chain")) == str(_pg)), None)
        if _wt is not None:
            _stage = float(_wt.get("lot", 0)) + RECOV_STEP
            break
    if _stage is not None and _stage < 0.04:
        _kmsg = (f"KINO skipped: last page at {_stage:.2f} - "
                 f"0.04 unlocks the next page")
        if st.get("kino_last_skip") != _kmsg:
            st["kino_last_skip"] = _kmsg
            say(_kmsg)
        return None
    # (user 2026-08-31: NO page-count cap, NO per-hour cap - entries
    # anytime; only the 0.04 chain gate above and the $100/page chain cap.)
    if ai is None or ai.balance < AUTO_MIN_BAL:
        _kmsg = f"KINO skipped: balance < {AUTO_MIN_BAL}"
        if st.get("kino_last_skip") != _kmsg:
            st["kino_last_skip"] = _kmsg
            say(_kmsg)
        return None
    _own = ({int(k) for k in (st.get("recov_links") or {})}
            | set(st.get("kino_tickets") or []))
    _nopen = len([p for p in manual if p.ticket in _own])
    if _nopen >= MAX_OPEN_PAGES:
        _kmsg = f"KINO skipped: {MAX_OPEN_PAGES} open pages already"
        if st.get("kino_last_skip") != _kmsg:
            st["kino_last_skip"] = _kmsg
            say(_kmsg)
        return None
    # SAME-WALL BLOCK (2026-09-04 user): a page that duplicates an open
    # fighter's stop is the same bet doubled - when the wall breaks both
    # die in the same second (2026-09-04 03:48: -$4.64 and -$1.20 on the
    # identical SL 80948.32). Skip the page; the fighter carries the bet.
    _links2 = st.get("recov_links") or {}
    for _p2 in manual:
        if str(_p2.ticket) not in _links2 or not _p2.sl:
            continue
        _pd2 = 1 if _p2.type == mt5.POSITION_TYPE_BUY else -1
        if _pd2 == direction and abs(_p2.sl - wall) <= 50.0:
            _kmsg = (f"KINO skipped: same wall as open fighter "
                     f"{_p2.ticket} (SL {_p2.sl:.2f})")
            if st.get("kino_last_skip") != _kmsg:
                st["kino_last_skip"] = _kmsg
                say(_kmsg)
            return None
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None
    entry_px = tick.ask if direction == 1 else tick.bid
    _dup = same_signal_taken(direction, entry_px, manual, st)
    if _dup is None and fired:
        for _fd, _fp in fired:
            if _fd == direction and abs(_fp - entry_px) <= 100.0:
                _dup = -1
                break
    if _dup is not None:
        _kmsg = (f"KINO skipped: same signal already taken by {_dup} "
                 f"(one signal = one trade)")
        if st.get("kino_last_skip") != _kmsg:
            st["kino_last_skip"] = _kmsg
            say(_kmsg)
        return None
    st["kino_last_skip"] = None
    # HALF-SIZE CHOP MODE: base 0.01 below the soft floor, else 0.02
    try:
        _cfj0 = json.load(open(os.path.join(DIR, "owl_chain_floor.json")))
        _softfloor = float(_cfj0.get("floor", 0.0))
        _hardfloor = float(_cfj0.get("hard_floor", 0.0))
    except Exception:
        _softfloor = 0.0
        _hardfloor = 0.0
    # $3-target pages v3 (2026-09-04 user final): lots never scale
    # (0.02 base, 0.01 below soft floor). SL stays at the structure
    # wall - risk MAY exceed $3. The $3 is the PROFIT side: TP is the
    # normal near-1:1 target but capped at $3 profit ($1.50 at 0.01).
    # No far-wall skip. Fighters untouched.
    blot = (0.01 if (_softfloor and ai is not None
                     and ai.balance < _softfloor) else KINO_LOTS)
    _rtarget = PAGE_RISK_USD * (blot / 0.02)
    _below_hard = (_hardfloor and ai is not None
                   and ai.balance < _hardfloor)
    if (((st.get("wx") or {}).get("forced") or _below_hard)
            and (st.get("shadow") or {}).get("streak", 0) < 2):
        _sh = st.setdefault("shadow", {"links": [], "streak": 0})
        _sdist = abs(entry_px - wall)
        _stpd = max(RECOV_MIN_WALL_PTS / 2.0,
                    _sdist - 0.75 / blot)
        _stp = (entry_px + _stpd if direction == 1
                else entry_px - _stpd)
        _sh["links"].append({"dir": direction, "lot": blot,
                             "entry": entry_px, "sl": round(wall, 2),
                             "tp": round(_stp, 2), "chain": "page"})
        save_state(st)
        say(f"SHADOW page ENTRY: "
            f"{'BUY' if direction == 1 else 'SELL'} {blot} @ "
            f"{entry_px:.2f} (virtual - shelter mode)")
        return -1
    dist = abs(entry_px - wall)
    if dist < RECOV_MIN_WALL_PTS:
        say(f"KINO skipped: wall {wall:.2f} too close ({dist:.1f}pts)")
        return None
    risk = dist * blot
    r = open_at_market(direction, blot, "OWL-kino")
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        say(f"KINO entry FAILED retcode={r.retcode if r else None}")
        return None
    tkt = r.order
    body = abs(float(conf_bar["close"]) - float(conf_bar["open"]))
    m1b = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 120)
    a14 = (atr(m1b["high"], m1b["low"], m1b["close"])
           if m1b is not None and len(m1b) > 20 else 0.0)
    strong = a14 > 0 and body >= a14
    disc = min(0.5 if strong else 1.0, 0.25 * risk)
    tp_dist = dist - disc / blot
    # profit cap: aim/cut at $3 ($1.50 at 0.01) even when the wall is far
    tp_dist = min(tp_dist, _rtarget / blot)
    tp = entry_px + tp_dist if direction == 1 else entry_px - tp_dist
    slp = round(wall, 2)
    mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": tkt,
                    "symbol": SYMBOL, "sl": slp, "tp": round(tp, 2)})
    if fired is not None:
        fired.append((direction, entry_px))
    st.setdefault("kino_tickets", []).append(tkt)
    st.setdefault("kino_born", []).append(tkt)
    if len(st["kino_born"]) > 300:
        del st["kino_born"][:100]
    st.setdefault("kino_walls", {})[str(tkt)] = [slp, round(tp, 2)]
    if str(tkt) not in st["user_owned"]:
        st["user_owned"].append(str(tkt))
    save_state(st)
    say(f"KINO ENTRY: {'BUY' if direction == 1 else 'SELL'} {blot} @ "
        f"~{entry_px:.2f} SL {slp} TP {tp:.2f} (risk ${risk:.2f}, prize "
        f"${tp_dist * blot:.2f}, return to "
        f"{'peak' if direction == 1 else 'dip'}, "
        f"{'strong' if strong else 'calm'} mkt)")
    return tkt

def reent_trigger(dirn, entry_price, t0):
    """Door-2 (fake-break re-entry, user 2026-08-31, simplified same day):
    trigger = EXACTLY the failed trade's entry price. A failed BUY re-arms
    as BUY when an M1 CLOSES back above it (mirror for SELL)."""
    return float(entry_price)

def connect():
    if not mt5.initialize(path=TERMINAL):
        return False
    ai = mt5.account_info()
    if ai is None or ai.login != LOGIN:
        say(f"ERROR wrong account {ai.login if ai else None}, expected {LOGIN}")
        mt5.shutdown()
        return False
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
            recov_tickets = {int(k) for k in (st.get("recov_links") or {})}
            if st.get("kino_tickets"):
                st["kino_tickets"] = [t for t in st["kino_tickets"]
                                      if t in open_tickets]
            kino_tickets = set(st.get("kino_tickets") or [])
            try:
                _cfj = json.load(open(os.path.join(
                    DIR, "owl_chain_floor.json")))
                chain_floor = float(_cfj.get("floor", 0.0))
                fighter_risk_cap = float(_cfj.get("risk_cap", 0.0))
                hard_floor = float(_cfj.get("hard_floor", 0.0))
            except Exception:
                chain_floor = 0.0
                fighter_risk_cap = 0.0
                hard_floor = 0.0
            owl_open_count = len([p for p in manual
                                  if p.ticket in recov_tickets
                                  or p.ticket in kino_tickets])
            # BELOW-HARD-FLOOR demands FRESH ghost proof: on first dropping
            # below the hard floor, reset the shadow streak so a stale
            # earlier clearing can't grant real trades in the danger zone.
            _wxf = st.setdefault("wx", {"ls": 0, "forced": False})
            _bh_now = bool(hard_floor and ai is not None
                           and ai.balance < hard_floor)
            if _bh_now and not _wxf.get("bh"):
                _wxf["bh"] = True
                _sh_r = st.setdefault("shadow", {"links": [], "streak": 0})
                _sh_r["streak"] = 0
                save_state(st)
                say(f"REST: dropped below hard floor {hard_floor:.0f} - "
                    f"real trading paused, ghosts must re-prove the weather")
            elif (not _bh_now) and _wxf.get("bh"):
                _wxf["bh"] = False
                save_state(st)
            split_tickets = {t for g in (st.get("splits") or [])
                             for t in (g.get("a"), g.get("b")) if t}
            SPLIT_TICKETS.clear()
            SPLIT_TICKETS.update(split_tickets)
            # --- DEPOSIT WATCHER (user 2026-08-31): deposits auto-raise the
            # Squirrel milestone target 1:1, so only PROFIT can complete a
            # milestone. Withdrawals are left to the assistant's ladder.
            try:
                if not st.get("bal_seen"):
                    st["bal_seen"] = int(time.time())
                    save_state(st)
                _dls = mt5.history_deals_get(
                    datetime.fromtimestamp(st["bal_seen"] + 1, tz=timezone.utc),
                    datetime.now(timezone.utc) + timedelta(minutes=5)) or []
                for _dl in _dls:
                    if _dl.type != mt5.DEAL_TYPE_BALANCE:
                        continue
                    st["bal_seen"] = max(st["bal_seen"], int(_dl.time))
                    save_state(st)
                    if _dl.profit > 0:
                        _mp = os.path.join(DIR, "owl_milestone.json")
                        try:
                            _mj = json.load(open(_mp))
                        except Exception:
                            _mj = {}
                        _old = float(_mj.get("milestone", 0) or 0)
                        if _old > 0:
                            _mj["milestone"] = round(_old + _dl.profit, 2)
                            _mj["note"] = (f"auto: +{_dl.profit:.2f} deposit "
                                           f"-> target {_old:.2f} -> "
                                           f"{_mj['milestone']:.2f}")
                            json.dump(_mj, open(_mp, "w"))
                            say(f"DEPOSIT detected: +{_dl.profit:.2f} -> "
                                f"Squirrel target auto-raised "
                                f"{_old:.2f} -> {_mj['milestone']:.2f} "
                                f"(deposits are floor, not progress)")
                    elif _dl.profit < 0:
                        say(f"WITHDRAWAL detected: {_dl.profit:.2f} "
                            f"(ladder handled by assistant)")
            except Exception:
                pass
            # --- EQUITY TRAIL SHIELD (user 2026-09-01: "trailing 310 usd
            # total equity such that we don't lose the 300 again"): once
            # equity touches `arm`, a guard line starts at arm-gap and then
            # TRAILS the equity peak (always `gap` below it, never down).
            # Equity falling back to the line -> cut ALL positions (user's
            # too, sanctioned), lock the money, fresh start, shield off.
            try:
                _et = json.load(open(os.path.join(DIR,
                                                  "owl_equity_trail.json")))
            except Exception:
                _et = {"enabled": False}
            if _et.get("enabled") and ai is not None:
                _pk = _et.get("peak")
                if _pk is None and ai.equity >= float(_et.get("arm", 9e9)):
                    _et["peak"] = ai.equity
                    json.dump(_et, open(os.path.join(
                        DIR, "owl_equity_trail.json"), "w"))
                    say(f"EQUITY SHIELD armed at {ai.equity:.2f} "
                        f"(guard {ai.equity - float(_et.get('gap', 10)):.2f})")
                elif _pk is not None:
                    if ai.equity > float(_pk):
                        _et["peak"] = ai.equity
                        json.dump(_et, open(os.path.join(
                            DIR, "owl_equity_trail.json"), "w"))
                    _guard = float(_et["peak"]) - float(_et.get("gap", 10))
                    if _et.get("floor") is not None:
                        _guard = max(_guard, float(_et["floor"]))
                    if ai.equity <= _guard:
                        say(f"EQUITY SHIELD FIRED: equity {ai.equity:.2f} "
                            f"touched guard {_guard:.2f} -> cutting ALL "
                            f"positions, money locked")
                        for p in manual:
                            r = close_at_market(p, "OWL-shield")
                            if (r is not None and r.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                say(f"  shield cut: {p.ticket} "
                                    f"({p.profit:+.2f})")
                            else:
                                say(f"  shield cut FAILED {p.ticket} "
                                    f"retcode={r.retcode if r else None}")
                        st["recov_watches"] = []
                        save_state(st)
                        _et["enabled"] = False
                        json.dump(_et, open(os.path.join(
                            DIR, "owl_equity_trail.json"), "w"))
                        positions = mt5.positions_get(symbol=SYMBOL) or []
                        manual = [p for p in positions if p.magic == 0]
                        open_tickets = {p.ticket for p in manual}
            # --- MILESTONE CUT (user order 2026-08-28: sanctioned exception
            # to hands-off): when EQUITY touches the Squirrel milestone, close
            # ALL positions (user's included) so the next journey starts fresh.
            # Milestone value maintained in owl_milestone.json by the assistant.
            try:
                _ms = json.load(open(os.path.join(DIR, "owl_milestone.json")))
            except Exception:
                _ms = {"enabled": False}
            if _ms.get("enabled") and ai is not None and ai.equity >= float(_ms.get("milestone", 9e9)):
                say(f"MILESTONE {_ms['milestone']} TOUCHED (equity {ai.equity:.2f}) -> cutting ALL trades")
                for p in manual:
                    r = close_at_market(p, "OWL-milestone")
                    if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                        say(f"  milestone cut: ticket {p.ticket} ({p.profit:+.2f})")
                    else:
                        say(f"  milestone cut FAILED ticket {p.ticket} retcode={r.retcode if r else None}")
                _ms["enabled"] = False
                json.dump(_ms, open(os.path.join(DIR, "owl_milestone.json"), "w"))
                positions = mt5.positions_get(symbol=SYMBOL) or []
                manual = [p for p in positions if p.magic == 0]
                open_tickets = {p.ticket for p in manual}
            # --- HOUR-FLAT: close everything at each hour boundary ---
            if HOUR_FLAT and tick is not None:
                hid_now = int(tick.time) // 3600
                if st.get("flat_hour") != hid_now:
                    st["flat_hour"] = hid_now
                    save_state(st)
                    flatable = [p for p in manual if p.ticket not in runner_tickets
                                and p.ticket not in recov_tickets
                                and p.ticket not in kino_tickets
                                and (is_bot_pos(p) or not MANUAL_HANDS_OFF)]
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
                           "entry_user_sl": p.sl, "entry_user_tp": p.tp,
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
            for p in manual:
                _tk = str(p.ticket)
                if _tk in st["pending"] and not is_bot_pos(p):
                    st["pending"][_tk]["final_user_sl"] = p.sl
                    st["pending"][_tk]["final_user_tp"] = p.tp
            # --- (re)assign TPs when the set of open positions changes ---
            cur_ids = sorted(open_tickets)
            if cur_ids != st["last_tickets"] and tick is not None:
                reassign(st, [p for p in manual if is_bot_pos(p) or not MANUAL_HANDS_OFF], tick)
                st["last_tickets"] = cur_ids
                save_state(st)
            # --- HEDGE-ESCAPE v2 (2026-08-22): hedge + confirmed H4 flip ---
            _mgd = [p for p in manual if (is_bot_pos(p) or not MANUAL_HANDS_OFF)
                    and p.ticket not in recov_tickets
                    and p.ticket not in kino_tickets]  # chains/pages: not hedges
            buys = [p for p in _mgd if p.type == mt5.POSITION_TYPE_BUY]
            sells = [p for p in _mgd if p.type == mt5.POSITION_TYPE_SELL]
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
                    reassign(st, [p for p in manual if is_bot_pos(p) or not MANUAL_HANDS_OFF], tick)
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
                if MANUAL_HANDS_OFF and not is_bot_pos(p):
                    continue          # user's hand trade: fully hands-off
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
                # --- WEATHER v2 storm detector ---
                if RECOV_ENTRY:
                    _wx = st.setdefault("wx", {"ls": 0, "forced": False})
                    _px2 = float(row.get("profit_usd") or 0.0)
                    if _px2 < -0.5:
                        _wx["ls"] += 1
                        if _wx["ls"] >= 3 and not _wx["forced"]:
                            _wx["forced"] = True
                            _sh0 = st.setdefault(
                                "shadow", {"links": [], "streak": 0})
                            _sh0["streak"] = 0
                            say("WEATHER: storm detected (3 straight "
                                "real losses) - FULL SHELTER, everything "
                                "goes virtual")
                            try:
                                json.dump({"mode": "shelter",
                                           "streak": 0},
                                          open(os.path.join(
                                              DIR, "owl_weather.json"),
                                              "w"))
                            except Exception:
                                pass
                    elif _px2 > 0.5:
                        _wx["ls"] = 0
                    save_state(st)
                # --- RECOVERY CHAIN trigger (user spec 2026-08-31;
                # 2026-08-31 amendment: MULTI-PAGE - every stopped trade gets
                # its OWN chain, tracked separately by origin ticket) ---
                if RECOV_ENTRY:
                    _t0 = None
                    try:
                        _t0 = int(datetime.fromisoformat(ent["entry_time_utc"])
                                  .replace(tzinfo=timezone.utc).timestamp())
                    except Exception:
                        pass
                    _links = st.setdefault("recov_links", {})
                    if tkey in _links:
                        _lk = _links.pop(tkey)
                        _cn = _lk.get("chain")
                        if row.get("exit_reason") == "sl" and _t0 is not None:
                            _d = 1 if ent["direction"] == "BUY" else -1
                            _tr = reent_trigger(_d, ent["entry_price"], _t0)
                            st.setdefault("recov_watches", []).append({
                                "dir": _d,
                                "sl": float(_lk.get("sl") or row.get("exit_price")
                                            or 0.0),
                                "lot": float(ent["volume"]),
                                "t0": _t0, "t_sl": int(time.time()),
                                "trig": _tr, "chain": _cn,
                                "kino": bool(_lk.get("kino")),
                                "loss": (float(_lk.get("loss") or 0.0)
                                         + abs(float(row.get("profit_usd")
                                                     or 0.0)))})
                            say(f"RECOV[{_cn}]: link {tkey} stopped -> two doors: "
                                f"M1 close beyond "
                                f"{float(_lk.get('sl') or 0.0):.2f} = flip, "
                                f"or back beyond {_tr:.2f} = re-enter")
                        else:
                            say(f"RECOV[{_cn}]: chain ENDED (link {tkey} exit="
                                f"{row.get('exit_reason')} {row.get('profit_usd')})")
                        save_state(st)
                    elif (row.get("exit_reason") == "sl"
                          and int(tkey) not in runner_tickets
                          and int(tkey) not in split_tickets
                          and _t0 is not None):
                        _sl = (ent.get("final_user_sl") or ent.get("entry_user_sl")
                               or row.get("exit_price"))
                        if _sl:
                            _d = 1 if ent["direction"] == "BUY" else -1
                            _tr = reent_trigger(_d, ent["entry_price"], _t0)
                            st.setdefault("recov_watches", []).append({
                                "dir": _d,
                                "sl": float(_sl), "lot": float(ent["volume"]),
                                "t0": _t0, "t_sl": int(time.time()),
                                "trig": _tr, "chain": tkey,
                                "kino": int(tkey) in
                                        (st.get("kino_born") or []),
                                "loss": abs(float(row.get("profit_usd")
                                                  or 0.0))})
                            save_state(st)
                            say(f"RECOV[{tkey}] armed: {ent['direction']} "
                                f"{ent['volume']} stopped at {float(_sl):.2f} -> "
                                f"two doors: M1 close beyond the line = flip, "
                                f"or back beyond {_tr:.2f} = re-enter")
            loop_fired = []
            # --- RECOVERY CHAIN: confirmation watches + entries (per chain) ---
            if RECOV_ENTRY and st.get("recov_watches") and tick is not None:
                b1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 1)
                _keep = []
                _dirty = False
                _fired = loop_fired   # shared same-loop entries (anti-race
                                      # across KINO and chain fires)
                for rw in st["recov_watches"]:
                    _cn = rw.get("chain")
                    done = False
                    if (b1 is not None and len(b1)
                            and int(b1["time"][0]) + 60 > rw["t_sl"]):
                        _cl = float(b1["close"][0])
                        _broke = (_cl < rw["sl"] if rw["dir"] == 1
                                  else _cl > rw["sl"])
                        _tg = rw.get("trig")
                        _reent = (not _broke and _tg is not None
                                  and (_cl > _tg if rw["dir"] == 1
                                       else _cl < _tg))
                        if _broke or _reent:
                            new_dir = rw["dir"] if _reent else -rw["dir"]
                            new_lot = round(rw["lot"] + RECOV_STEP, 2)
                            legbars = mt5.copy_rates_range(
                                SYMBOL, mt5.TIMEFRAME_M1,
                                datetime.fromtimestamp(
                                    (rw["t_sl"] - 120) if _reent
                                    else (rw["t0"] - 60),
                                    tz=timezone.utc),
                                datetime.now(timezone.utc))
                            if legbars is not None and len(legbars):
                                wall = (float(np.max(legbars["high"]))
                                        if new_dir == -1
                                        else float(np.min(legbars["low"])))
                                entry_px = (tick.bid if new_dir == -1
                                            else tick.ask)
                                dist = abs(entry_px - wall)
                                risk = dist * new_lot
                                if dist < RECOV_MIN_WALL_PTS:
                                    if not rw.get("wclose"):
                                        rw["wclose"] = True
                                        _dirty = True
                                        say(f"RECOV[{_cn}]: wall {wall:.2f} "
                                            f"too close ({dist:.1f}pts) - "
                                            f"waiting (log once)")
                                elif (fighter_risk_cap
                                        and risk > fighter_risk_cap):
                                    if not rw.get("held_cap"):
                                        rw["held_cap"] = True
                                        _dirty = True
                                        say(f"RECOV[{_cn}] held: fighter "
                                            f"would risk ${risk:.2f} > cap "
                                            f"${fighter_risk_cap:.2f} - "
                                            f"waiting for tighter structure")
                                elif risk >= RECOV_MAX_RISK_USD:
                                    say(f"RECOV[{_cn}] chain STOPPED: next link "
                                        f"would risk ${risk:.2f} >= "
                                        f"${RECOV_MAX_RISK_USD:.0f} cap "
                                        f"(lot {new_lot}, wall {wall:.2f})")
                                    done = True
                                    _dirty = True
                                elif (((st.get("wx") or {}).get("forced")
                                       or (hard_floor and ai is not None
                                           and ai.balance < hard_floor))
                                      and (st.get("shadow") or {})
                                      .get("streak", 0) < 2):
                                    # STORM / below-hard-floor: virtual
                                    _sh = st.setdefault(
                                        "shadow",
                                        {"links": [], "streak": 0})
                                    tpd = dist - min(
                                        0.75, 0.25 * risk) / new_lot
                                    if (new_lot >= DEEP_LOT
                                            and rw.get("loss")):
                                        _ghd = ((float(rw["loss"])
                                                 + HEAL_EXTRA_USD)
                                                / new_lot)
                                        if (RECOV_MIN_WALL_PTS < _ghd
                                                < tpd):
                                            tpd = _ghd
                                    _stp = (entry_px + tpd if new_dir == 1
                                            else entry_px - tpd)
                                    _sh["links"].append(
                                        {"dir": new_dir, "lot": new_lot,
                                         "entry": entry_px,
                                         "sl": round(wall, 2),
                                         "tp": round(_stp, 2),
                                         "chain": _cn})
                                    done = True
                                    _dirty = True
                                    say(f"SHADOW chain[{_cn}] ENTRY: "
                                        f"{'BUY' if new_dir == 1 else 'SELL'}"
                                        f" {new_lot} @ {entry_px:.2f} "
                                        f"(virtual - shelter mode)")
                                    try:
                                        _md = ("storm"
                                               if ((st.get("wx") or {})
                                                   .get("forced")
                                                   or (hard_floor
                                                       and ai is not None
                                                       and ai.balance
                                                       < hard_floor))
                                               else "floor")
                                        json.dump(
                                            {"mode": _md,
                                             "streak": _sh["streak"]},
                                            open(os.path.join(
                                                DIR, "owl_weather.json"),
                                                "w"))
                                    except Exception:
                                        pass
                                elif (owl_open_count + len(_fired)
                                        >= MAX_OPEN_PAGES):
                                    if not rw.get("held_pages"):
                                        rw["held_pages"] = True
                                        _dirty = True
                                        say(f"RECOV[{_cn}] held: "
                                            f"{MAX_OPEN_PAGES} open pages "
                                            f"already - door waits")
                                elif (same_signal_taken(
                                        new_dir, entry_px, manual,
                                        st) is not None
                                      or any(_d == new_dir
                                             and abs(_px - entry_px)
                                             <= 100.0
                                             for _d, _px in _fired)):
                                    if not rw.get("held"):
                                        rw["held"] = True
                                        _dirty = True
                                        say(f"RECOV[{_cn}] held: same signal "
                                            f"already taken by another page "
                                            f"(one signal = one trade); door "
                                            f"stays armed")
                                elif owl_dir_conflict(new_dir, manual,
                                                      st) is not None:
                                    if not rw.get("held"):
                                        rw["held"] = True
                                        _dirty = True
                                        say(f"RECOV[{_cn}] held: opposite Owl "
                                            f"trade still open - one must "
                                            f"close first (door stays armed)")
                                else:
                                    r = open_at_market(new_dir, new_lot,
                                                       "OWL-recov")
                                    if (r is not None and r.retcode
                                            == mt5.TRADE_RETCODE_DONE):
                                        tkt = r.order
                                        _body = abs(float(b1["close"][0])
                                                    - float(b1["open"][0]))
                                        _m1b = mt5.copy_rates_from_pos(
                                            SYMBOL, mt5.TIMEFRAME_M1, 1, 120)
                                        _a14 = (atr(_m1b["high"], _m1b["low"],
                                                    _m1b["close"])
                                                if _m1b is not None
                                                and len(_m1b) > 20 else 0.0)
                                        strong = _a14 > 0 and _body >= _a14
                                        disc_usd = min(0.5 if strong else 1.0,
                                                       0.25 * risk)
                                        tp_dist = dist - disc_usd / new_lot
                                        _healed = False
                                        if new_lot >= DEEP_LOT:
                                            _hd = ((float(rw.get("loss") or 0.0)
                                                    + HEAL_EXTRA_USD) / new_lot)
                                            if RECOV_MIN_WALL_PTS < _hd < tp_dist:
                                                tp_dist = _hd
                                                _healed = True
                                        tp = (entry_px - tp_dist
                                              if new_dir == -1
                                              else entry_px + tp_dist)
                                        st.setdefault("recov_links", {})[
                                            str(tkt)] = {
                                            "sl": round(wall, 2),
                                            "tp": round(tp, 2),
                                            "lot": new_lot, "chain": _cn,
                                            "kino": bool(rw.get("kino")),
                                            "loss": float(rw.get("loss")
                                                          or 0.0)}
                                        if str(tkt) not in st["user_owned"]:
                                            st["user_owned"].append(str(tkt))
                                        done = True
                                        _dirty = True
                                        _fired.append((new_dir, entry_px))
                                        mt5.order_send(
                                            {"action": mt5.TRADE_ACTION_SLTP,
                                             "position": tkt, "symbol": SYMBOL,
                                             "sl": round(wall, 2),
                                             "tp": round(tp, 2)})
                                        say(f"RECOV[{_cn}] "
                                            f"{'RE-ENTRY (fake break)' if _reent else 'ENTRY'}: "
                                            f"{'SELL' if new_dir == -1 else 'BUY'} "
                                            f"{new_lot} @ ~{entry_px:.2f} "
                                            f"SL {wall:.2f} TP {tp:.2f} "
                                            f"(risk ${risk:.2f}, prize "
                                            f"${tp_dist * new_lot:.2f}, "
                                            f"{'strong' if strong else 'calm'} "
                                            f"mkt -> -${disc_usd:.2f} early"
                                            + (", HEAL target" if _healed
                                               else "") + ")")
                                    else:
                                        say(f"RECOV[{_cn}] entry FAILED "
                                            f"retcode="
                                            f"{r.retcode if r else None}")
                    if not done and time.time() - rw["t_sl"] > 21600:
                        say(f"RECOV[{_cn}] watch EXPIRED (6 h, neither door "
                            f"opened)")
                        done = True
                        _dirty = True
                    if not done:
                        _keep.append(rw)
                st["recov_watches"] = _keep
                if _dirty:
                    save_state(st)
            # --- KINO ENTRY: the user's own peak/dip-return system ---
            # pause switch (owl_kino_pause.json, no restart needed to flip)
            try:
                _kp = json.load(open(os.path.join(DIR,
                                                  "owl_kino_pause.json")))
                _kino_paused = bool(_kp.get("paused"))
            except Exception:
                _kino_paused = False
            if KINO_ENTRY and not _kino_paused and tick is not None:
                for _tk in list((st.get("kino_walls") or {}).keys()):
                    if int(_tk) not in open_tickets:
                        st["kino_walls"].pop(_tk, None)
                        (st.get("kino_part") or {}).pop(_tk, None)
                        # FRESH PULLBACK RULE (2026-09-03 user): a closed
                        # KINO trade clears any armed pending - the next
                        # signal entry needs a NEW pullback (down close
                        # below the last green candle's low) to make the
                        # peak/dip official again. Measured before adding:
                        # would have cut 19/84 trades, win rate unchanged.
                        _ks = st.get("kino") or {}
                        for _side in ("up", "dn"):
                            if (_ks.get(_side) or {}).get("pending"):
                                _ks[_side]["pending"] = None
                                say(f"KINO: pending {_side} cleared - "
                                    f"fresh pullback required after "
                                    f"closed trade {_tk}")
                        save_state(st)
                        continue
                    _kp = next((p for p in manual
                                if p.ticket == int(_tk)), None)
                    _w = st["kino_walls"].get(_tk)
                    if (_kp is not None and _w
                            and (_kp.sl == 0.0 or _kp.tp == 0.0)):
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                        "position": _kp.ticket,
                                        "symbol": SYMBOL,
                                        "sl": _w[0], "tp": _w[1]})
                        say(f"KINO: re-sent SL/TP on {_tk}")
                    if (_kp is not None and _w and len(_w) < 3
                            and _kp.tp):
                        _d = (1 if _kp.type == mt5.POSITION_TYPE_BUY
                              else -1)
                        _prize = ((_kp.tp - _kp.price_open) * _d
                                  * _kp.volume)
                        # 2026-09-03 user: lock at 40% (was 80%). Replayed
                        # 123 trades first: +$77 total, helps pages AND
                        # fighters (study/owl_lockbank_replay.py).
                        if _prize > 0 and _kp.profit >= 0.40 * _prize:
                            r = mt5.order_send(
                                {"action": mt5.TRADE_ACTION_SLTP,
                                 "position": _kp.ticket,
                                 "symbol": SYMBOL,
                                 "sl": round(_kp.price_open, 2),
                                 "tp": _kp.tp})
                            if (r is not None and r.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                _w.append(1)
                                st["kino_walls"][_tk] = _w
                                save_state(st)
                                say(f"KINO 40% LOCK: {_tk} wall moved "
                                    f"to entry")
                    # PARTIAL at 85% (2026-09-03 user): close half, let the
                    # rest ride to the full TP. Lots >= 0.02 only.
                    if (_kp is not None and _kp.tp and _kp.volume >= 0.02
                            and not (st.get("kino_part") or {}).get(_tk)):
                        _d = (1 if _kp.type == mt5.POSITION_TYPE_BUY
                              else -1)
                        _przp = ((_kp.tp - _kp.price_open) * _d
                                 * _kp.volume)
                        if _przp > 0 and _kp.profit >= PARTIAL_FRAC * _przp:
                            _half = (int(round(_kp.volume / 0.01))
                                     // 2) * 0.01
                            r = close_at_market(_kp, "OWL-partial", _half)
                            if (r is not None and r.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                st.setdefault("kino_part", {})[_tk] = 1
                                save_state(st)
                                say(f"KINO PARTIAL 85%: {_tk} banked "
                                    f"{_half} lots, rest rides to TP")
                kb = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 2)
                if (kb is not None and len(kb) == 2
                        and int(kb[1]["time"]) != st.get("kino_last_bar")):
                    st["kino_last_bar"] = int(kb[1]["time"])
                    pv, cb = kb[0], kb[1]
                    po, pc = float(pv["open"]), float(pv["close"])
                    ph, pl = float(pv["high"]), float(pv["low"])
                    co, cc = float(cb["open"]), float(cb["close"])
                    ch, clo = float(cb["high"]), float(cb["low"])
                    ks = st.setdefault("kino", {"up": {}, "dn": {}})
                    up, dn = ks["up"], ks["dn"]
                    now_t = int(cb["time"])
                    # UP side: leg birth -> official peak -> return = BUY
                    if pc > po and cc > co and cc > ph:
                        up["leg"] = True
                        up["peak"] = ch
                        up["glow"] = clo
                    elif up.get("leg"):
                        up["peak"] = max(up.get("peak", ch), ch)
                        if cc > co:
                            up["glow"] = clo
                        elif cc < up.get("glow", float("-inf")):
                            up["pending"] = up["peak"]
                            up["pt"] = now_t
                            up["plow"] = clo
                            up["leg"] = False
                            say(f"KINO: peak {up['peak']:.2f} official -> "
                                f"pending BUY on M1 close back above it")
                    if up.get("pending"):
                        up["plow"] = min(up.get("plow", clo), clo)
                        if now_t - up.get("pt", now_t) > 21600:
                            say(f"KINO: pending BUY {up['pending']:.2f} "
                                f"expired (6h)")
                            up["pending"] = None
                        elif cc > up["pending"]:
                            if kino_open(1, up.get("plow", clo), st, ai,
                                         manual, runner_tickets,
                                         split_tickets, recov_tickets,
                                         cb) is not None:
                                up["pending"] = None
                    # DOWN side: mirror -> official dip -> return = SELL
                    if pc < po and cc < co and cc < pl:
                        dn["leg"] = True
                        dn["dip"] = clo
                        dn["rhigh"] = ch
                    elif dn.get("leg"):
                        dn["dip"] = min(dn.get("dip", clo), clo)
                        if cc < co:
                            dn["rhigh"] = ch
                        elif cc > dn.get("rhigh", float("inf")):
                            dn["pending"] = dn["dip"]
                            dn["pt"] = now_t
                            dn["phigh"] = ch
                            dn["leg"] = False
                            say(f"KINO: dip {dn['dip']:.2f} official -> "
                                f"pending SELL on M1 close back below it")
                    if dn.get("pending"):
                        dn["phigh"] = max(dn.get("phigh", ch), ch)
                        if now_t - dn.get("pt", now_t) > 21600:
                            say(f"KINO: pending SELL {dn['pending']:.2f} "
                                f"expired (6h)")
                            dn["pending"] = None
                        elif cc < dn["pending"]:
                            if kino_open(-1, dn.get("phigh", ch), st, ai,
                                         manual, runner_tickets,
                                         split_tickets, recov_tickets,
                                         cb) is not None:
                                dn["pending"] = None
                    save_state(st)
            # babysit open links: SL/TP stickiness + DEEP-FIGHTER RATCHET
            if RECOV_ENTRY and st.get("recov_links"):
                for _tk, _ri in list(st["recov_links"].items()):
                    _rp = next((p for p in manual if str(p.ticket) == _tk), None)
                    if _rp is None:
                        continue
                    if _rp.sl == 0.0 or _rp.tp == 0.0:
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                        "position": _rp.ticket,
                                        "symbol": SYMBOL,
                                        "sl": _ri["sl"], "tp": _ri["tp"]})
                        say(f"RECOV[{_ri.get('chain')}]: re-sent SL/TP on "
                            f"link {_tk}")
                        continue
                    if (_rp.volume < DEEP_LOT and _rp.tp
                            and not _ri.get("rat")):
                        _d = (1 if _rp.type == mt5.POSITION_TYPE_BUY
                              else -1)
                        _prize = ((_rp.tp - _rp.price_open) * _d
                                  * _rp.volume)
                        # 2026-09-03 user: lock at 40% (was 80%), same
                        # measured basis as the KINO lock above.
                        if _prize > 0 and _rp.profit >= 0.40 * _prize:
                            r = mt5.order_send(
                                {"action": mt5.TRADE_ACTION_SLTP,
                                 "position": _rp.ticket,
                                 "symbol": SYMBOL,
                                 "sl": round(_rp.price_open, 2),
                                 "tp": _rp.tp})
                            if (r is not None and r.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                _ri["rat"] = 1
                                _ri["sl"] = round(_rp.price_open, 2)
                                save_state(st)
                                say(f"RECOV[{_ri.get('chain')}] 40% "
                                    f"LOCK: link {_rp.ticket} wall "
                                    f"moved to entry")
                    # PARTIAL at 85% for small fighters (2026-09-03 user).
                    # Deep fighters (>= DEEP_LOT) keep the 70% full bank.
                    if (_rp.volume < DEEP_LOT and _rp.volume >= 0.02
                            and _rp.tp and not _ri.get("part")):
                        _d = (1 if _rp.type == mt5.POSITION_TYPE_BUY
                              else -1)
                        _przp = ((_rp.tp - _rp.price_open) * _d
                                 * _rp.volume)
                        if (_przp > 0
                                and _rp.profit >= PARTIAL_FRAC * _przp):
                            _half = (int(round(_rp.volume / 0.01))
                                     // 2) * 0.01
                            r = close_at_market(_rp, "OWL-partial", _half)
                            if (r is not None and r.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                _ri["part"] = 1
                                save_state(st)
                                say(f"RECOV[{_ri.get('chain')}] PARTIAL "
                                    f"85%: link {_rp.ticket} banked "
                                    f"{_half} lots, rest rides to TP")
                    if _rp.volume >= DEEP_LOT and _rp.tp:
                        _d = 1 if _rp.type == mt5.POSITION_TYPE_BUY else -1
                        _prize = ((_rp.tp - _rp.price_open) * _d
                                  * _rp.volume)
                        if _prize > 0 and _rp.profit >= RATCHET_BANK * _prize:
                            r = close_at_market(_rp, "OWL-ratchet-bank")
                            if (r is not None and r.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                say(f"RECOV[{_ri.get('chain')}] RATCHET "
                                    f"BANK: link {_tk} taken at "
                                    f"{_rp.profit:+.2f} "
                                    f"({RATCHET_BANK:.0%} of prize)")
                        elif (_prize > 0
                                and _rp.profit >= RATCHET_LOCK * _prize
                                and not _ri.get("rat")):
                            _be = round(_rp.price_open, 2)
                            r = mt5.order_send(
                                {"action": mt5.TRADE_ACTION_SLTP,
                                 "position": _rp.ticket, "symbol": SYMBOL,
                                 "sl": _be, "tp": _rp.tp})
                            if (r is not None and r.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                _ri["rat"] = 1
                                _ri["sl"] = _be
                                save_state(st)
                                say(f"RECOV[{_ri.get('chain')}] RATCHET "
                                    f"LOCK: link {_tk} wall moved to "
                                    f"entry {_be} (can no longer lose)")
            # --- WEATHER SYSTEM: resolve shadow fights, manage modes ---
            _sh = st.setdefault("shadow", {"links": [], "streak": 0})
            if tick is not None and ai is not None:
                if (ai.balance >= chain_floor
                        and not (st.get("wx") or {}).get("forced")
                        and (_sh["links"] or _sh["streak"])):
                    _sh["links"] = []
                    _sh["streak"] = 0
                    save_state(st)
                    say("WEATHER: balance back above the floor - "
                        "normal mode")
                    try:
                        json.dump({"mode": "normal", "streak": 0},
                                  open(os.path.join(
                                      DIR, "owl_weather.json"), "w"))
                    except Exception:
                        pass
                elif _sh["links"]:
                    _keepL = []
                    for L in _sh["links"]:
                        # SCOUTS SENSE FREELY: ghosts judge the RAW market
                        # (did the setup reach its target or its stop) - no
                        # 80% lock / breakeven, so a paying market resumes us.
                        _px = tick.bid if L["dir"] == 1 else tick.ask
                        _res = None
                        _hit_tp = (_px >= L["tp"] if L["dir"] == 1
                                   else _px <= L["tp"])
                        _hit_sl = (_px <= L["sl"] if L["dir"] == 1
                                   else _px >= L["sl"])
                        if _hit_tp:
                            _res = round((L["tp"] - L["entry"])
                                         * L["dir"] * L["lot"], 2)
                        elif _hit_sl:
                            _res = round((L["sl"] - L["entry"])
                                         * L["dir"] * L["lot"], 2)
                        if _res is not None:
                            _pnl = _res
                            if _pnl > 0.5:
                                _sh["streak"] += 1
                                say(f"SHADOW chain[{L['chain']}] WIN "
                                    f"{_pnl:+.2f} (streak "
                                    f"{_sh['streak']})")
                            elif _pnl < -0.5:
                                _sh["streak"] = 0
                                say(f"SHADOW chain[{L['chain']}] LOSS "
                                    f"{_pnl:+.2f} (streak reset)")
                            else:
                                say(f"SHADOW chain[{L['chain']}] "
                                    f"breakeven {_pnl:+.2f} "
                                    f"(streak kept)")
                            save_state(st)
                            _mode = ("clear" if _sh["streak"] >= 2
                                     else "shelter")
                            if _sh["streak"] == 2:
                                _wx2 = st.setdefault(
                                    "wx", {"ls": 0, "forced": False})
                                _wx2["forced"] = False
                                _wx2["ls"] = 0
                                say("WEATHER CLEAR: two shadow wins - "
                                    "everything real AUTO-RESUMES "
                                    "(hard floor still guards)")
                            try:
                                json.dump({"mode": _mode,
                                           "streak": _sh["streak"]},
                                          open(os.path.join(
                                              DIR, "owl_weather.json"),
                                              "w"))
                            except Exception:
                                pass
                        else:
                            _keepL.append(L)
                    if len(_keepL) != len(_sh["links"]):
                        _sh["links"] = _keepL
                        save_state(st)
            # --- GROUP HEAL (user 2026-09-01): whole-account escape ---
            if RECOV_ENTRY and ai is not None:
                _gl = st.get("recov_links") or {}
                _gw = st.get("recov_watches") or []
                _deep = any(float(v.get("lot", 0)) >= DEEP_LOT
                            for v in _gl.values())
                if GROUP_HEAL_ENABLED and _deep:
                    _tot_loss = (sum(float(v.get("loss") or 0.0)
                                     for v in _gl.values())
                                 + sum(float(w.get("loss") or 0.0)
                                       for w in _gw))
                    _float = ai.equity - ai.balance
                    _reward = max(GROUP_HEAL_MIN,
                                  GROUP_HEAL_PCT * _tot_loss)
                    if _float >= _tot_loss + _reward:
                        say(f"GROUP HEAL: floating {_float:+.2f} covers all "
                            f"fighting pages' losses ({_tot_loss:.2f}) "
                            f"+ reward {_reward:.2f} "
                            f"-> cutting ALL Owl trades, fresh start")
                        for p in manual:
                            if is_bot_pos(p):
                                r = close_at_market(p, "OWL-group-heal")
                                if (r is not None and r.retcode
                                        == mt5.TRADE_RETCODE_DONE):
                                    say(f"  healed: ticket {p.ticket} "
                                        f"({p.profit:+.2f})")
                                else:
                                    say(f"  heal cut FAILED {p.ticket} "
                                        f"retcode="
                                        f"{r.retcode if r else None}")
                        st["recov_watches"] = []
                        save_state(st)
            # --- hour-group cleanup: past-hour groups close when net positive ---
            # (suspended while a hedge-escape is active: nothing may pop the freeze)
            if tick is not None and not escape_active:
                cur_hour = str(int(tick.time) // 3600)
                for hid in list(st["groups"].keys()):
                    g = st["groups"][hid]
                    if hid >= cur_hour:
                        continue           # current (or future) hour - never touch
                    members = [p for p in manual if p.ticket in g["tickets"]
                               and p.ticket not in runner_tickets
                               and p.ticket not in recov_tickets
                               and p.ticket not in kino_tickets
                               and (is_bot_pos(p) or not MANUAL_HANDS_OFF)]
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
                                        and p.ticket not in split_tickets
                                        and (is_bot_pos(p) or not MANUAL_HANDS_OFF)])
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
                                                and p.ticket not in split_tickets
                                                and (is_bot_pos(p) or not MANUAL_HANDS_OFF)])
                                           + len(st.get("splits") or []))
                                if n_stack >= AUTO_MAX_STACK:
                                    say(f"CROC skipped: stack {n_stack} >= {AUTO_MAX_STACK}")
                                elif ai.balance < AUTO_MIN_BAL:
                                    say(f"CROC skipped: balance {ai.balance:.2f} < {AUTO_MIN_BAL}")
                                else:
                                    r = open_at_market(d, SWEEP_LOTS, "OWL-sweep")
                                    if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                                        st["sweep_hour"] = hid
                                        st.setdefault("splits", []).append(
                                            {"a": r.order, "b": None, "dir": d,
                                             "t": time.time(), "sweep": True})
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
                p = next((q for q in manual if q.ticket == grp.get("a")), None)
                if p is not None:
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
                    "bot": "OWL-manual-assistant-LIVE",
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
