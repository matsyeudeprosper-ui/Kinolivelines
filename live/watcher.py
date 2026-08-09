"""Event-driven watcher for BTCUSDm. Costs nothing until something matters.

Polls MT5 locally every 30s and stays SILENT unless a decision is genuinely
needed. Each stdout line becomes one wake-up, so every trigger is latched:
it fires once, then re-arms only after the condition properly clears.

Triggers
  OPENED    a position appeared (pending filled, or a manual click)
  CLOSED    a position went away (SL, TP or manual) - I am flat, look for next
  AT_1R     open position reached ~1R profit -> move stop to break-even
  LEVEL     price broke a level I flagged in watch_config.json -> read is dead
  SETUP     flat, and price arrived at a KinoliveLines level -> possible trade

watch_config.json is re-read every poll, so levels can be changed without a
restart. Nothing here ever sends an order.
"""
import MetaTrader5 as mt5
import json, os, time, sys
from datetime import datetime

# The model writes real Unicode into its watch-level notes - non-breaking
# hyphens (U+2011), en/em dashes, x and ~ - and those notes are quoted verbatim
# into every alert. Windows stdout defaults to cp1252, so ONE such character
# raised UnicodeEncodeError inside emit(), before the file write, killing the
# whole alert: no notification AND no alerts.log row. It then retried every
# poll, so the blindness was permanent, not momentary. Force UTF-8 and never
# let an unencodable glyph cost an event.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TERMINAL   = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN      = 436771046
SYM        = "BTCUSDm"
POLL       = 30
MIN_GAP    = 180          # seconds between non-critical events, anti-spam
HERE       = os.path.dirname(os.path.abspath(__file__))
CONFIG     = os.path.join(HERE, "watch_config.json")
HEARTBEAT  = os.path.join(HERE, "watcher_alive.json")

ALERTS = os.path.join(HERE, "alerts.log")

def emit(tag, msg):
    """Wake the session AND persist to disk. Events that fire while no Claude
    session is attached would otherwise be lost entirely - this file is the
    catch-up log for whoever picks the work back up."""
    line = f"[{datetime.now():%H:%M:%S}] {tag}: {msg}"
    # Belt and braces with the stdout reconfigure above: the file write is the
    # durable record, so it must happen even if stdout is somehow still hostile.
    try:
        print(line, flush=True)
    except Exception:
        try:
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)
        except Exception:
            pass
    try:
        with open(ALERTS, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}\t{tag}\t{msg}\n")
    except Exception:
        pass    # never let logging kill the watcher

def load_config():
    try:
        with open(CONFIG) as f: return json.load(f)
    except Exception:
        return {"watch_levels": [], "be_trigger_r": 1.0, "setup_proximity_atr": 0.15}

def connect():
    while True:
        if mt5.initialize(path=TERMINAL):
            a = mt5.account_info()
            if a and a.login == LOGIN:
                mt5.symbol_select(SYM, True)
                return
            mt5.shutdown()
        time.sleep(15)

def atr_h1():
    r = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H1, 0, 30)
    if r is None or len(r) < 16: return None
    tr, pc = [], None
    for b in r:
        if pc is not None:
            tr.append(max(b['high']-b['low'], abs(b['high']-pc), abs(b['low']-pc)))
        pc = b['close']
    return sum(tr[-14:]) / 14 if len(tr) >= 14 else None

def levels():
    """KinoliveLines set: prev closed H4/H1/M15 high+low, merged."""
    out = []
    a = atr_h1()
    t = mt5.symbol_info_tick(SYM)
    if a is None or t is None: return out
    spread = t.ask - t.bid
    raw = []
    for tf, prio, nm in ((mt5.TIMEFRAME_H4,3,'H4'), (mt5.TIMEFRAME_H1,2,'H1'), (mt5.TIMEFRAME_M15,1,'M15')):
        r = mt5.copy_rates_from_pos(SYM, tf, 1, 1)
        if r is None or len(r) == 0: continue
        raw.append([r[0]['high'], True, prio, nm]); raw.append([r[0]['low'], False, prio, nm])
    if not raw: return out
    tol = max(spread*3.0, a*0.12)
    raw.sort(key=lambda x: x[0]); keep = [True]*len(raw)
    for i in range(len(raw)):
        if not keep[i]: continue
        for j in range(i+1, len(raw)):
            if not keep[j]: continue
            if abs(raw[i][0]-raw[j][0]) <= tol:
                if raw[j][2] > raw[i][2]: raw[i] = raw[j]
                keep[j] = False
    merged = [r for i, r in enumerate(raw) if keep[i]]
    md = merged[0][0]*0.001
    for r in merged:
        if not out or r[1] != out[-1][1] or abs(r[0]-out[-1][0]) >= md: out.append(r)
        if len(out) >= 6: break
    return out

connect()
emit("START", f"watching {SYM} on {LOGIN}, poll {POLL}s - silent until something needs a decision")

def own_positions():
    # KL-loop trades only (act.py sends magic 0). The harvest/renko bots
    # (7704xx) run their own exits on this account - a 1R stop suggestion or
    # an open/close notice for THEIR positions is noise at best and a wrong
    # instruction at worst. Same fix as daemon.py, 2026-08-08.
    return [p for p in (mt5.positions_get(symbol=SYM) or []) if p.magic == 0]

known_pos   = {p.ticket: p.price_open for p in own_positions()}
known_ord   = {o.ticket for o in (mt5.orders_get(symbol=SYM) or [])}
fired_1r    = set()      # tickets already flagged at 1R
level_side  = {}         # flagged level -> which side price was on last poll
setup_armed = {}         # level price -> True once price has moved away again
last_event  = 0.0

while True:
    try:
        if not mt5.terminal_info():
            mt5.shutdown(); connect()

        cfg  = load_config()
        tick = mt5.symbol_info_tick(SYM)
        if tick is None:
            time.sleep(POLL); continue
        mid  = (tick.bid + tick.ask) / 2
        pos  = own_positions()
        ords = list(mt5.orders_get(symbol=SYM) or [])
        now  = time.time()

        # ---- position appeared / disappeared: always critical, no rate limit ----
        cur = {p.ticket: p.price_open for p in pos}
        for t in cur:
            if t not in known_pos:
                p = next(x for x in pos if x.ticket == t)
                emit("OPENED", f"#{t} {'BUY' if p.type==0 else 'SELL'} {p.volume} @ {p.price_open:.2f} "
                               f"SL {p.sl or 'NONE'} TP {p.tp or 'NONE'} - now managing")
                last_event = now
        for t in known_pos:
            if t not in cur:
                emit("CLOSED", f"#{t} (opened @ {known_pos[t]:.2f}) is gone - flat now, bid {tick.bid:.2f}. "
                               f"Look for the next setup.")
                fired_1r.discard(t); last_event = now
        known_pos = cur

        curo = {o.ticket for o in ords}
        for t in curo - known_ord:
            emit("PENDING", f"order #{t} placed")
        known_ord = curo

        # ---- 1R reached -> break-even move ----
        for p in pos:
            if p.ticket in fired_1r or not p.sl: continue
            risk = abs(p.price_open - p.sl)
            if risk <= 0: continue
            gain = (tick.bid - p.price_open) if p.type == 0 else (p.price_open - tick.ask)
            if gain >= risk * cfg.get("be_trigger_r", 1.0):
                fired_1r.add(p.ticket)
                emit("AT_1R", f"#{p.ticket} is +{gain:.0f}px = {gain/risk:.2f}R (risk {risk:.0f}px). "
                              f"bid {tick.bid:.2f}. Consider moving stop to break-even {p.price_open:.2f}.")
                last_event = now

        # ---- flagged level broken ----
        # Test against the M1 bar EXTREMES since the last poll, not just the
        # current mid: on 2026-07-30 price wicked to 64681 through a flagged
        # 64693 and was back above it before the next 30s sample, so a real
        # break went unreported. A level that only trades through for seconds
        # is exactly the one worth waking for.
        recent = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M1, 0, 3)
        lo_since = min([b['low'] for b in recent]) if recent is not None and len(recent) else mid
        hi_since = max([b['high'] for b in recent]) if recent is not None and len(recent) else mid

        for wl in cfg.get("watch_levels", []):
            price, side = float(wl["price"]), wl.get("dir", "below")
            key = f"{price}:{side}"
            broken = (lo_since < price) if side == "below" else (hi_since > price)
            was = level_side.get(key)
            if was is None:
                level_side[key] = broken
            elif broken and not was and now - last_event > MIN_GAP:
                ext = lo_since if side == "below" else hi_since
                emit("LEVEL", f"broke {side} {price:.2f} (reached {ext:.2f}, now {mid:.2f}) - {wl.get('note','')}")
                level_side[key] = True; last_event = now
            elif not broken:
                level_side[key] = False          # re-arm once it recovers

        # ---- flat and price arrived at a level -> possible setup ----
        if not pos and not ords and now - last_event > MIN_GAP:
            a = atr_h1()
            if a:
                near = cfg.get("setup_proximity_atr", 0.15) * a
                for lp, isHigh, prio, nm in levels():
                    k = round(lp, 2)
                    # Only wake for a level where a Rule 3 order could actually
                    # REST. A SELL LIMIT fades a resistance at the level itself and
                    # must sit above the bid; a BUY LIMIT fades a support at
                    # level+spread and must sit below the ask, which reduces to the
                    # level being below the bid. Once price is on the wrong side,
                    # the broker rejects the order as behind the market, so the
                    # wake can never produce a trade.
                    #
                    # Added 2026-08-02: H1 resistance 63,431.55 fired four SETUP
                    # events in 26 minutes while price sat ABOVE it, every one of
                    # them un-actionable. Un-actionable wakes are worse than no
                    # wake - they train whoever is on the other end to skim.
                    tradeable = (lp > tick.bid) if isHigh else (lp < tick.bid)
                    if abs(mid - lp) <= near and tradeable:
                        if setup_armed.get(k, True):
                            setup_armed[k] = False
                            emit("SETUP", f"flat, price {mid:.2f} at {nm} "
                                          f"{'RESIST' if isHigh else 'SUPPORT'} {lp:.2f} "
                                          f"({abs(mid-lp):.0f}px away). Assess for a trade.")
                            last_event = now
                    elif abs(mid - lp) > near * 2.5:
                        setup_armed[k] = True    # moved away, re-arm this level

        with open(HEARTBEAT, "w") as f:
            json.dump({"alive_utc": datetime.utcnow().isoformat(), "bid": tick.bid,
                       "positions": len(pos), "orders": len(ords)}, f)

    except Exception as e:
        emit("ERROR", f"{type(e).__name__}: {e}")
        try: mt5.shutdown()
        except Exception: pass
        time.sleep(10); connect()

    time.sleep(POLL)
