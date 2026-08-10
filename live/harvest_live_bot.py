"""renko_recovery_bot.py - the CAPPED RECOVERY design, on the DEMO account.

THE RULE (user's design + the cap that makes it survive)
  1. a reversal brick opens ONE trade, take profit 5 bricks (250 pts)
  2. wins  -> banked, new cycle
  3. price goes 3 bricks (150 pts) against it -> do NOT close. Enter RECOVERY.
  4. in recovery, each new reversal adds another 0.01 lot, up to MAX_BASKET,
     BUT ONLY IF IT POINTS THE SAME WAY AS THE FIRST TRADE OF THE CYCLE
  5. equity back to where the cycle started -> close everything, new cycle
  6. basket would exceed MAX_BASKET -> close everything at a loss, new cycle

*** THIS STRATEGY LOSES MONEY IN BACKTEST. READ BEFORE CHANGING ANYTHING. ***

2026-08-05. The backtest that justified this design was wrong. Entries were
priced at the NEXT bar's open while the take profit and stop were tested against
the SIGNAL bar - the bar that closed before the trade existed. Re-run with that
one thing corrected and nothing else changed:

  7.6 years of H1, cap 4:  $1,000 -> $415  (-59%)
                           worst drawdown $966, equity reached $204
  the version this file used to quote:  $1,000 -> $3,631

Survival is not robust either. Corrected, caps 2, 5, 6, 8, 12 and no-cap all go
to ZERO; cap 3 survives at $177 having touched $3; cap 4 is the only setting
left with anything, and it still lost 59%. Six of eight settings die. The old
docstring called caps 2-12 "a broad plateau" - it is one lucky cell surrounded
by ruin, which is what noise looks like.

Also corrected: the bot cannot act on 11.3% of signals because it is holding a
basket (the broken run said 0.8%). Holding losers means missing winners, and
that cost is real - it showed up live before the measurement did.

VOID, do not resurrect from an old note: +263%, 83% or 74% of months positive,
median month +$9 or +$33, max drawdown $384 / 11.7%, "equity never fell below
the starting deposit", "743 of 744 recoveries succeeded", "caps 2-12 all
survived", the capital-sizing result and the compounding study.

2026-08-06 CHANGE - SAME-DIRECTION RECOVERY ADDS, at the user's instruction.

Rule 4 now skips any reversal pointing against the FIRST trade of the cycle. The
old behaviour added on every reversal, which builds a straddled basket - seen
live this morning, four positions all losing at once with price sitting between
them, paying the 10-point spread on every leg while the group could not move
anywhere together.

Backtested, same brick and spread, paired across brick anchors:

                current (any)      SAME direction
  M1  1.8 mo          -             +$145  (8/8 anchors)
  M5  9.1 mo       $530             $1,174 (6/6)
  H1   55 mo     $0 DEAD            $506   (5/6)

Cap hits fall from 38-41/month to 15-17. On H1 the old rule takes the account to
zero and this one survives.

IT STILL LOSES MONEY. H1 ends at half the deposit. The H1 breakdown: 1,888 target
wins at +$2.84 and 1,164 recoveries at +$1.61, against 112 cap hits at -$70.34 -
so 3.5% of cycles erase everything the other 96.5% earn. This turns a dying
design into a surviving one, nothing more. It is also NOT out-of-sample: every
window used had already been looked at.

This process keeps running only as forward MEASUREMENT on a demo account. It is
not a strategy, it has no validated edge, and no live money should follow it.
See FINDINGS.md section 7 and trap 15.

NO BROKER STOP LOSS. Positions carry a take profit but no stop, because the
exit logic lives here. If this process dies while holding a basket, those
positions sit unmanaged until it restarts. That is the main operational risk
and the reason for the heartbeat file.

2026-08-05 FIX - "recovered" used to mean the wrong thing.
Rule 5 says close when the money is back to where the cycle started. The
original code tested mt5.account_info().equity, which is the WHOLE ACCOUNT -
including renko_bot.py's positions and its realised wins and losses. The two
bots share account 436771046, so the other bot's P&L decided this bot's exits.
It happened live on 2026-08-04: this bot's basket was -$1.13, the plain bot
banked +$2.46 at 19:05, account equity touched the target, and the basket was
closed at a LOSS while the rule said it should close at zero or better.
The reverse is the dangerous case - when the plain bot is losing, the target
becomes unreachable and this bot holds its basket LONGER than the rule allows,
adding positions toward the cap. The backtest never saw any of this because the
simulation had only one strategy in it.
Now the cycle is measured from THIS BOT'S OWN money only: every position opened
in the cycle is tracked by ticket, and cycle P&L = realised on those tickets +
floating on the ones still open. Nothing else on the account can move it.
"""
import json, os, sys, time
from datetime import datetime, timedelta

import MetaTrader5 as mt5

TERMINAL    = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"   # the LIVE install
LOGIN       = 134499778
SYMBOL      = "BTCUSDm"
LOTS        = 0.01
MAGIC       = 770407            # live-only; 770404/5 are demo, 770406 was the retired hedge bot
BRICK       = 50.0
REVERSAL    = 2
TP_BRICKS   = 5
SL_BRICKS   = 3                 # a TRIGGER level, not a broker stop
MAX_BASKET  = 4
POLL        = 20
FRESH_MIN   = 6
ANCHOR      = datetime(2026, 7, 17)

# Bot-only daily protection. It never reads whole-account P&L, so deposits,
# withdrawals and any other EA on the account cannot arm or fire it.
TRAIL_ACTIVATE   = 7.00
TRAIL_GIVEBACK   = 4.00
DAILY_LOSS_LIMIT = 20.00
PROTECTION_EPOCH = ANCHOR

# If the terminal dies, this process stays alive and keeps failing quietly - and
# the 5-minute scheduled-task watchdog will NOT help, because IgnoreNew sees a
# running process and does nothing. So after this many consecutive failures the
# bot exits deliberately. The watchdog then restarts it, and mt5.initialize(path)
# relaunches the terminal on the way back up.
# Exiting while holding a basket sounds worse than it is: a disconnected bot
# cannot manage those positions anyway, and this bot carries NO broker stop, so
# getting the connection back is the only thing that helps them.
MAX_FAILS   = 10                # 10 x 20s = ~3.5 min before giving up

HERE  = os.path.dirname(os.path.abspath(__file__))
LOG   = os.path.join(HERE, "harvest_live.log")
ALIVE = os.path.join(HERE, "harvest_live_alive.json")
STATE = os.path.join(HERE, "harvest_live_state.json")


def say(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


FLOOR_USD = 15.00     # open nothing below this. See the note in the docstring.

# ---- BALANCE-PROPORTIONAL SCALING (user's decision, 2026-08-10) ------------
# One "unit" = 0.01 lots per BASE_BALANCE of account balance, so the whole
# system scales with the account WITHOUT changing the strategy's shape:
# at ~$270 the bot trades 0.02 with a $40 daily stop, at ~$1,080 it reaches
# 0.08 with a $160 stop, and every ratio (protection ~15%/day, floor, trail)
# stays what it is today. Two freeze rules keep the math honest:
#   - lots are FIXED PER CYCLE (equal-lot baskets are load-bearing - the
#     retired hedge bot proved unequal/mid-cycle changes break the geometry);
#   - the protection scale is FIXED PER UTC DAY (set at day start).
BASE_BALANCE = 135.0


def scale_units(balance):
    try:
        return max(1, int(float(balance) // BASE_BALANCE))
    except Exception:
        return 1


# ---- THE COMBO GATE (user's decision, 2026-08-10) --------------------------
# SPEC_FRESH_EARLY_COMBO - the only rule of ~20 tested that passed its
# preregistered criteria AND the ETH out-of-sample check: zero wipeouts on
# every timeframe of both instruments, small positive expectancy on M1/M5.
# A NEW CYCLE may only open when BOTH hold:
#   1. the $150-brick series is in a FRESH reversal window (its flip pair has
#      printed and nothing further - a 2-brick reversal always prints two
#      bricks atomically, so freshness = bricks-since-flip <= 1), in the
#      signal's direction;
#   2. it is one of the day's first MAX_CYCLES_PER_DAY cycles (UTC).
# Recovery adds are UNCHANGED - the gate is entries only.
BIG_BRICK = 150.0
MAX_CYCLES_PER_DAY = 2


def big_dir_at(closed, sig_time, brick=BIG_BRICK, rev=2):
    """(direction, fresh) of the $150-brick series at the signal bar's close.
    Exact brick loop the bots use; no lookahead. dir 0 = no brick yet."""
    ao = ac = float(closed[0]["open"])
    d = 0
    since = 99
    for r in closed:
        t, ci = int(r["time"]), float(r["close"])
        if t > sig_time:
            break
        while True:
            up = (ao if d == -1 else ac) + brick * (rev if d == -1 else 1)
            dn = (ao if d == 1 else ac) - brick * (rev if d == 1 else 1)
            if ci >= up:
                base = ao if d == -1 else ac
                since = 0 if d == -1 else since + 1
                ao, ac, d = base, base + brick, 1
            elif ci <= dn:
                base = ao if d == 1 else ac
                since = 0 if d == 1 else since + 1
                ao, ac, d = base, base - brick, -1
            else:
                break
    return d, (d != 0 and since <= 1)


def check_account():
    """REAL account 134499778 only, verified on EVERY loop rather than once at
    startup - a terminal can be re-logged into a different account while this is
    running, and this one places orders with real money."""
    a = mt5.account_info()
    if a is None:
        return None
    if a.login != LOGIN:
        say(f"*** WRONG ACCOUNT {a.login}, expected {LOGIN} - REFUSING TO TRADE ***")
        return False
    if a.trade_mode != 2:
        say(f"*** not a REAL account (trade_mode={a.trade_mode}) - REFUSING ***")
        return False
    return a


def connect():
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    a = check_account()
    if not a:
        mt5.shutdown(); raise SystemExit("account check failed at startup")
    return a


def build_bricks(rates):
    out = []
    ao = ac = float(rates[0]["open"]); d = 0
    for r in rates:
        t, c = int(r["time"]), float(r["close"])
        while True:
            up = (ao if d == -1 else ac) + BRICK * (REVERSAL if d == -1 else 1)
            dn = (ao if d == 1 else ac) - BRICK * (REVERSAL if d == 1 else 1)
            if c >= up:
                base = ao if d == -1 else ac; ao, ac, d = base, base + BRICK, 1
            elif c <= dn:
                base = ao if d == 1 else ac; ao, ac, d = base, base - BRICK, -1
            else:
                break
            out.append({"time": t, "dir": d, "close": ac})
    return out


def last_reversal(b):
    for k in range(len(b) - 1, 0, -1):
        if b[k]["dir"] != b[k - 1]["dir"]:
            # Return a copy so the observation fields do not alter the brick
            # list used by the strategy.
            out = dict(b[k])
            out["brick_index"] = k
            out["prior_dir"] = b[k - 1]["dir"]
            return out
    return None


class PositionsUnavailable(RuntimeError):
    """The terminal could not tell us what we hold."""


def mine():
    """Positions belonging to THIS bot. Raises if the terminal cannot answer.

    This used to be `positions_get(...) or []`. positions_get returns None on
    error, so `or []` reported NO POSITIONS - and every caller here reads no
    positions as FLAT. Flat clears the cycle tickets and lets the next reversal
    start a fresh cycle on top of a basket that is still open, untracked, and
    stopless. One dropped call was enough.

    Raising instead sends the whole poll into the main loop's handler, which
    logs and waits. Not knowing what we hold is a reason to do nothing, never a
    reason to assume the best case.
    """
    ps = mt5.positions_get(symbol=SYMBOL)
    if ps is None:
        raise PositionsUnavailable(f"positions_get failed: {mt5.last_error()}")
    return [p for p in ps if p.magic == MAGIC]


def close_all_verified(ps, why, tries=3):
    """close_all, then PROVE the book is empty. True only when confirmed.

    close_all fires the orders and never looks back, while the caller clears
    its cycle state immediately afterwards. A rejected close therefore leaves a
    live position that the bot has forgotten it owns. Verification costs one
    extra read and is a no-op whenever the close worked."""
    for attempt in range(1, tries + 1):
        close_all(ps, why if attempt == 1 else f"{why} (retry {attempt})")
        time.sleep(1.0)
        try:
            left = mine()
        except PositionsUnavailable as e:
            say(f"  cannot confirm the close: {e} - will re-check next poll")
            return False
        if not left:
            if attempt > 1:
                say(f"  confirmed flat after attempt {attempt}")
            return True
        say(f"  {len(left)} position(s) STILL OPEN after attempt {attempt}")
        ps = left
    say("  *** CLOSE UNCONFIRMED - state NOT cleared, will retry next poll ***")
    return False


def basket_pnl(ps):
    return sum(p.profit + p.swap for p in ps)


def cycle_realised(tickets):
    """Money already banked on THIS cycle's positions - the ones that hit their
    own take profit and left, plus anything closed by hand.

    Matched by position ticket, never by time. Deal timestamps are in BROKER
    server time while datetime.now() here is box time, and comparing the two
    silently drops or double-counts deals whenever the offset is not zero.
    The window below only has to be wide enough to contain the cycle."""
    if not tickets:
        return 0.0
    want = set(tickets)
    deals = mt5.history_deals_get(datetime.now() - timedelta(days=7),
                                  datetime.now() + timedelta(days=1))
    if deals is None:
        return None                     # unknown - caller must not act on it
    # ALL deals for these tickets, not just the exits. Commission and fee can
    # be charged on the ENTRY deal (profit is zero there, the costs are not),
    # and filtering to DEAL_ENTRY_OUT hid them - so "cycle P&L back to zero"
    # was really "back to zero before entry costs". Zero on this broker today,
    # wrong the day that changes.
    return sum(d.profit + d.swap + d.commission + getattr(d, "fee", 0.0)
               for d in deals
               if d.magic == MAGIC and d.position_id in want)


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_brick": 0, "recovery": False, "cycle_equity": None,
                "cycle_tickets": [], "cycle_dir": None}


def save_state(s):
    try:
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE)
        return True
    except Exception as exc:
        say(f"STATE SAVE FAILED: {exc}")
        return False



# ---------------------------------------------------------------------------
# Order-time instrumentation. These facts exist ONLY at the moment the order
# goes out and cannot be reconstructed from broker history afterwards: the
# spread we saw, how long the round trip took, the retcode of a REJECTED order
# (which leaves no deal at all), free margin at that instant, and the price we
# intended to close at.
#
# Everything here is wrapped so that a journalling failure can never stop or
# delay a trade. If the disk is full the bot keeps trading and loses only the
# record.
EVENTS = LOG.replace(".log", "_events.jsonl")


def acct_snapshot():
    try:
        a = mt5.account_info()
        if a is None:
            return {}
        return dict(balance=round(a.balance, 2), equity=round(a.equity, 2),
                    margin=round(a.margin, 2),
                    margin_free=round(a.margin_free, 2),
                    margin_level=round(a.margin_level or 0.0, 1))
    except Exception:
        return {}


def rec_event(kind, **kw):
    try:
        row = {"ts_utc": datetime.utcnow().isoformat(timespec="milliseconds"),
               "kind": kind, "magic": MAGIC}
        row.update(kw)
        with open(EVENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


def closed_m1_context(closed_rates, rev, tick=None, decision_time=None):
    """Facts known before an order is sent, using CLOSED M1 bars only.

    Positive chase means price has already moved beyond the reversal brick in
    the trade direction. Negative means the available quote is better than the
    brick price. These fields observe candidate filters; they do not gate an
    order.
    """
    decision_time = decision_time or datetime.utcnow()
    tick = tick or mt5.symbol_info_tick(SYMBOL)
    direction = int(rev["dir"])
    brick_price = float(rev["close"])
    quote = None
    if tick is not None:
        quote = float(tick.ask if direction == 1 else tick.bid)

    closes = [float(r["close"]) for r in closed_rates]

    def ema(period):
        if not closes:
            return None
        value = closes[0]
        alpha = 2.0 / (period + 1.0)
        for close in closes[1:]:
            value = alpha * close + (1.0 - alpha) * value
        return value

    atr = None
    if len(closed_rates) >= 15:
        trs = []
        for i in range(1, len(closed_rates)):
            hi = float(closed_rates[i]["high"])
            lo = float(closed_rates[i]["low"])
            prev = float(closed_rates[i - 1]["close"])
            trs.append(max(hi - lo, abs(hi - prev), abs(lo - prev)))
        atr = sum(trs[-14:]) / 14.0

    chase = None if quote is None else (quote - brick_price) * direction
    signal_dt = datetime.utcfromtimestamp(int(rev["time"]))
    last_bar_time = (datetime.utcfromtimestamp(int(closed_rates[-1]["time"]))
                     if len(closed_rates) else None)
    point = getattr(mt5.symbol_info(SYMBOL), "point", 0.01) or 0.01
    return {
        "signal_time_utc": signal_dt.isoformat(),
        "decision_time_utc": decision_time.isoformat(timespec="milliseconds"),
        "signal_age_seconds": round((decision_time - signal_dt).total_seconds(), 3),
        "reversal_direction": "BUY" if direction == 1 else "SELL",
        "reversal_brick_price": round(brick_price, 2),
        "reversal_brick_index": rev.get("brick_index"),
        "m1_closed_bar_time_utc": (last_bar_time.isoformat() if last_bar_time else None),
        "bid_at_decision": (float(tick.bid) if tick is not None else None),
        "ask_at_decision": (float(tick.ask) if tick is not None else None),
        "spread_at_decision": (round(float(tick.ask - tick.bid), 2)
                               if tick is not None else None),
        "quote_at_decision": (round(quote, 2) if quote is not None else None),
        "chase_price_signed": (round(chase, 2) if chase is not None else None),
        "chase_points_signed": (round(chase / point, 1) if chase is not None else None),
        "atr_m1_14_at_decision": (round(atr, 4) if atr is not None else None),
        "atr_over_brick_at_decision": (round(atr / BRICK, 4) if atr is not None else None),
        "ema20_at_decision": (round(ema(20), 4) if closes else None),
        "ema50_at_decision": (round(ema(50), 4) if closes else None),
        "shadow_chase_50_pass": (chase is not None and chase <= 50.0),
        "shadow_chase_100_pass": (chase is not None and chase <= 100.0),
    }


def open_one(direction, why, rev=None, closed_rates=None, lots=LOTS):
    """Returns the POSITION ticket on success, None on failure. The ticket is
    what ties the position to this cycle, so a failure to resolve it has to be
    treated as a failure to open - an untracked position would sit outside the
    cycle P&L and never be counted."""
    # counted BEFORE the send. Reading it afterwards includes the position we
    # just opened, which made every "new cycle" event report a basket of 1.
    _before = len(mine())
    tick = mt5.symbol_info_tick(SYMBOL)
    decision_time = datetime.utcnow()
    context = (closed_m1_context(closed_rates, rev, tick, decision_time)
               if rev is not None and closed_rates is not None else {})
    if tick is None:
        rec_event("open_blocked", why=why, reason="no tick", basket_before=_before,
                  **context)
        return None
    buy = (direction == 1)
    price = tick.ask if buy else tick.bid
    tp = price + BRICK * TP_BRICKS if buy else price - BRICK * TP_BRICKS
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": lots,
           "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
           "price": price, "tp": tp,           # NO sl - the exit logic is here
           "deviation": 30, "magic": MAGIC, "comment": "KL-recov",
           "type_time": mt5.ORDER_TIME_GTC}
    say(f"OPEN {'BUY' if buy else 'SELL'} {lots} @ {price:.2f} TP {tp:.2f}  [{why}]")
    _t0 = time.perf_counter()
    r = mt5.order_send(req)
    _lat = round((time.perf_counter() - _t0) * 1000, 1)
    ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    say(f"  retcode {getattr(r,'retcode','?')} -> {'OK' if ok else 'FAILED'}")
    _fill = getattr(r, "price", None) or None
    _after = mt5.symbol_info_tick(SYMBOL)
    _brick = float(rev["close"]) if rev is not None else None
    _fill_from_brick = ((_fill - _brick) * direction
                        if _fill is not None and _brick is not None else None)
    _adverse_slip = ((_fill - price) * direction if _fill is not None else None)
    _point = getattr(mt5.symbol_info(SYMBOL), "point", 0.01) or 0.01
    rec_event("order_open",
              side="BUY" if buy else "SELL", volume=lots, why=why, ok=ok,
              requested_price=round(price, 2), tp=round(tp, 2),
              bid=tick.bid, ask=tick.ask, spread=round(tick.ask - tick.bid, 2),
              bid_after_fill=(getattr(_after, "bid", None) if _after else None),
              ask_after_fill=(getattr(_after, "ask", None) if _after else None),
              spread_after_fill=(round(_after.ask - _after.bid, 2) if _after else None),
              fill_price=_fill, fill_volume=getattr(r, "volume", None),
              fill_distance_from_brick=(round(_fill_from_brick, 2)
                                        if _fill_from_brick is not None else None),
              adverse_slippage_price=(round(_adverse_slip, 2)
                                      if _adverse_slip is not None else None),
              adverse_slippage_points=(round(_adverse_slip / _point, 1)
                                       if _adverse_slip is not None else None),
              # signed as P&L impact: positive means a better fill than asked
              slippage_usd=(round((_fill - price) * (-1 if buy else 1) * lots, 4)
                            if _fill else None),
              retcode=getattr(r, "retcode", None),
              broker_comment=getattr(r, "comment", ""),
              deal=getattr(r, "deal", None), order=getattr(r, "order", None),
              request_id=getattr(r, "request_id", None),
              latency_ms=_lat, basket_before=_before, **context, **acct_snapshot())
    if not ok:
        return None
    ticket = None
    if getattr(r, "deal", 0):
        ds = mt5.history_deals_get(ticket=r.deal)
        if ds:
            ticket = ds[0].position_id
    if ticket is None:
        ticket = getattr(r, "order", None) or None   # market fills reuse the id
    if ticket is None:
        say("  WARNING could not resolve position ticket - not tracked in cycle")
    else:
        say(f"  position ticket {ticket}")
    return ticket


def close_all(ps, why):
    _decided = basket_pnl(ps)
    say(f"CLOSE BASKET of {len(ps)}  pnl {_decided:+.2f}  [{why}]")
    rec_event("close_decided", n=len(ps), decided_pnl=round(_decided, 2),
              why=why, **acct_snapshot())
    for p in ps:
        t = mt5.symbol_info_tick(SYMBOL)
        want = t.bid if p.type == 0 else t.ask
        req = {"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": SYMBOL,
               "volume": p.volume,
               "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
               "price": want,
               "deviation": 30, "magic": MAGIC, "comment": "KL-recov-close"}
        _t0 = time.perf_counter()
        r = mt5.order_send(req)
        _lat = round((time.perf_counter() - _t0) * 1000, 1)
        ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
        say(f"  close #{p.ticket} -> {'OK' if ok else 'FAILED ' + str(getattr(r,'retcode','?'))}")
        _fill = getattr(r, "price", None) or None
        rec_event("order_close", position=p.ticket, ok=ok,
                  side="BUY" if p.type == 0 else "SELL", volume=p.volume,
                  pos_profit=round(p.profit, 2), entry=p.price_open,
                  requested_price=round(want, 2), fill_price=_fill,
                  bid=t.bid, ask=t.ask, spread=round(t.ask - t.bid, 2),
                  # the exit-side gap the history journal could never see
                  slippage_usd=(round((_fill - want) * (1 if p.type == 0 else -1)
                                      * p.volume, 4) if _fill else None),
                  retcode=getattr(r, "retcode", None),
                  broker_comment=getattr(r, "comment", ""),
                  deal=getattr(r, "deal", None), order=getattr(r, "order", None),
                  latency_ms=_lat, why=why)


# ---------------------------------------------------------------------------
# Bot-only daily profit protection.
#
#   bot_value   = every realised dollar for this MAGIC + current floating P&L
#   daily_total = bot_value - bot_value when this protection day started
#
# The baseline is persisted, so an ordinary restart cannot reset the trail or
# the daily loss. A first deployment during a UTC day starts from the value at
# deployment; this prevents old, partly reconstructed P&L from closing an open
# position merely because the process was upgraded.

S_ACTIVE, S_LIQUIDATING, S_STOPPED = "ACTIVE", "LIQUIDATING", "STOPPED"


def all_realised():
    """All realised P&L for this bot since a fixed epoch.

    Entry deals are included because commission and fees may be charged there.
    None means history is unreadable; the caller must not pretend that is zero.
    """
    deals = mt5.history_deals_get(PROTECTION_EPOCH,
                                  datetime.now() + timedelta(days=1))
    if deals is None:
        return None
    return sum(d.profit + d.swap + d.commission + getattr(d, "fee", 0.0)
               for d in deals if d.magic == MAGIC and d.symbol == SYMBOL)


def reset_protection_day(st, day_id, bot_value):
    st["protection_day"] = day_id
    st["protection_day_start_value"] = bot_value
    st["protection_state"] = S_ACTIVE
    # protection scale is fixed for the whole UTC day from the balance now
    a = mt5.account_info()
    st["day_units"] = scale_units(a.balance if a else 0)
    st["protection_stop_reason"] = None
    st["protection_trigger_total"] = None
    st["protection_final_total"] = None
    st["trail_armed"] = False
    st["trail_peak"] = 0.0
    st["trail_floor"] = 0.0
    st["daily_total"] = 0.0
    save_state(st)
    say(f"  scale: {st['day_units']} unit(s) -> lots {0.01*st['day_units']:.2f}, "
        f"daily stop -${DAILY_LOSS_LIMIT*st['day_units']:.0f}, "
        f"trail +${TRAIL_ACTIVATE*st['day_units']:.0f}/"
        f"${TRAIL_GIVEBACK*st['day_units']:.0f}")
    rec_event("protection_day_start", day=day_id, units=st["day_units"],
              bot_value=round(bot_value, 4), activate=TRAIL_ACTIVATE,
              giveback=TRAIL_GIVEBACK, daily_loss_limit=DAILY_LOSS_LIMIT)
    say(f"PROTECTION DAY {day_id} starts at bot value {bot_value:+.2f}")


def protection_liquidate(st, ps, reason_code, why):
    """Persist the stop decision, close, and prove this bot is flat."""
    if st.get("protection_state") != S_LIQUIDATING:
        st["protection_state"] = S_LIQUIDATING
        st["protection_stop_reason"] = reason_code
        save_state(st)                       # decision survives a crash
        rec_event("protection_liquidating", reason=reason_code, why=why,
                  positions=len(ps), **acct_snapshot())
        say(f"  -> PROTECTION LIQUIDATING [{reason_code}] ({why})")

    done = (not ps) or close_all_verified(ps, why)
    if done:
        try:
            done = not mine()               # independent final confirmation
        except PositionsUnavailable as exc:
            say(f"  cannot confirm protection close: {exc}")
            done = False

    if not done:
        save_state(st)
        say("  *** protection close is not confirmed; all orders stay blocked ***")
        return False

    st["protection_state"] = S_STOPPED
    st["close_pending"] = None
    st["cycle_tickets"] = []
    st["cycle_dir"] = None
    st["cycle_equity"] = None
    st["recovery"] = False
    save_state(st)
    rec_event("protection_stopped", reason=st.get("protection_stop_reason"),
              day=st.get("protection_day"), **acct_snapshot())
    say("  -> PROTECTION STOPPED (flat confirmed; no trading until next UTC day)")
    return True


def finish_protection_measurement(st):
    """Record what was actually banked after a protection liquidation."""
    realised = all_realised()
    if realised is None:
        return
    final_total = realised - st.get("protection_day_start_value", realised)
    st["protection_final_total"] = round(final_total, 2)
    st["daily_total"] = round(final_total, 2)
    save_state(st)
    trigger_total = st.get("protection_trigger_total")
    trigger_number = trigger_total if isinstance(trigger_total, (int, float)) else 0.0
    rec_event("protection_final", reason=st.get("protection_stop_reason"),
              trigger_total=trigger_total,
              final_total=round(final_total, 4),
              execution_gap=round(final_total - trigger_number, 4))
    say(f"  final protected day P&L {final_total:+.2f} "
        f"(trigger was {trigger_number:+.2f})")


def main():
    acc = connect()
    say("=" * 70)
    say(f"HARVEST BOT UP - REAL MONEY - account {acc.login} {acc.server} "
        f"balance {acc.balance:.2f} {acc.currency}")
    say(f"rule: TP {TP_BRICKS} bricks, recovery at {SL_BRICKS} bricks, "
        f"MAX BASKET {MAX_BASKET}, {LOTS} lots, magic {MAGIC}")
    say("exit: OWN cycle P&L back to 0.00 (realised on this cycle's tickets + "
        "floating). Account equity is no longer used - the other bot's P&L "
        "used to move it.")
    _u0 = scale_units(acc.balance)
    say(f"BALANCE SCALING: {_u0} unit(s) at balance {acc.balance:.2f} "
        f"(1 unit per ${BASE_BALANCE:.0f}) -> lots {0.01*_u0:.2f}, "
        f"floor ${FLOOR_USD*_u0:.0f}, daily stop -${DAILY_LOSS_LIMIT*_u0:.0f}, "
        f"trail +${TRAIL_ACTIVATE*_u0:.0f}/${TRAIL_GIVEBACK*_u0:.0f}. "
        f"Lots freeze per cycle; protection scale freezes per UTC day.")
    say(f"EQUITY FLOOR ${FLOOR_USD*_u0:.2f} - no new cycle below this")
    say(f"COMBO GATE (2026-08-10): new cycles ONLY in a fresh ${BIG_BRICK:.0f}-brick "
        f"reversal window AND only the day's first {MAX_CYCLES_PER_DAY} cycles (UTC). "
        f"Recovery adds unchanged. SPEC_FRESH_EARLY_COMBO - passed prereg + ETH check.")
    say("history: the UNGATED rule lost in backtest and was run at the user's "
        "informed instruction until 2026-08-10 (week 1 live: -14.59, one "
        "protection stop). The combo-gated rule above is the first variant "
        "that PASSED its preregistered tests (both instruments, no wipeouts).")
    say("=" * 70)
    say("adds: SAME DIRECTION ONLY - a reversal against the first trade of the "
        "cycle is skipped. Deployed 2026-08-06.")
    say(f"PROFIT PROTECTION: arm +${TRAIL_ACTIVATE:.2f}, trail by "
        f"${TRAIL_GIVEBACK:.2f}; daily stop -${DAILY_LOSS_LIMIT:.2f}; "
        "close this bot only and stop until the next UTC day")
    st = load_state()
    fails = 0
    while True:
        try:
            rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, ANCHOR, datetime.utcnow())
            if rates is None or len(rates) < 2:
                fails += 1
                say(f"no bars from the terminal ({fails}/{MAX_FAILS}) "
                    f"last_error {mt5.last_error()}")
                if fails >= MAX_FAILS:
                    say("TERMINAL UNREACHABLE - exiting so the watchdog can "
                        "restart this bot and relaunch MT5")
                    mt5.shutdown(); sys.exit(1)
                time.sleep(POLL); continue
            bricks = build_bricks(rates[:-1])
            rev = last_reversal(bricks)
            ps = mine()
            acc = check_account()
            if acc is False:
                say("halting - wrong account. Fix and restart."); mt5.shutdown(); sys.exit(2)
            if acc is None:                     # connected enough for bars, not
                fails += 1                      # for the account - still broken
                say(f"no account_info ({fails}/{MAX_FAILS})")
                if fails >= MAX_FAILS:
                    say("TERMINAL UNREACHABLE - exiting for the watchdog")
                    mt5.shutdown(); sys.exit(1)
                time.sleep(POLL); continue
            eq = acc.equity
            fails = 0                           # a clean pass clears the counter

            # ---- profit protection and daily loss --------------------
            # A persisted liquidation is always completed first, even when
            # deal history is temporarily unavailable.
            if st.get("protection_state") == S_LIQUIDATING:
                reason = st.get("protection_stop_reason") or "protection"
                if protection_liquidate(st, ps, reason,
                                         f"resume {reason} liquidation"):
                    ps = []
                    finish_protection_measurement(st)
                else:
                    ps = mine()

            realised_all = all_realised()
            day_id = datetime.utcnow().strftime("%Y-%m-%d")
            protection_data_ok = realised_all is not None

            if protection_data_ok:
                if st.get("protection_history_ok") is False:
                    rec_event("protection_history_restored")
                    say("protection history is readable again")
                st["protection_history_ok"] = True
                bot_value = realised_all + basket_pnl(ps)

                if (st.get("protection_day") != day_id and
                        st.get("protection_state") != S_LIQUIDATING):
                    # If yesterday's trail was armed while a position crossed
                    # midnight, bank it before throwing yesterday's floor away.
                    if st.get("trail_armed") and ps:
                        old_day = st.get("protection_day")
                        say(f"UTC day changed with the trail armed and {len(ps)} "
                            "position(s); closing before reset")
                        st["protection_trigger_total"] = st.get("daily_total")
                        if not protection_liquidate(st, ps, "midnight_armed",
                                                    f"midnight after {old_day}"):
                            protection_data_ok = False
                        else:
                            ps = []
                            finish_protection_measurement(st)
                            realised_all = all_realised()
                            if realised_all is None:
                                protection_data_ok = False
                            else:
                                bot_value = realised_all
                    if (protection_data_ok and
                            st.get("protection_state") != S_LIQUIDATING):
                        reset_protection_day(st, day_id, bot_value)

                if (protection_data_ok and
                        st.get("protection_day") == day_id):
                    daily_total = bot_value - st.get(
                        "protection_day_start_value", bot_value)
                    st["daily_total"] = round(daily_total, 2)

                    # thresholds scaled by the day's frozen unit count
                    _du = st.get("day_units", 1) or 1
                    _limit = DAILY_LOSS_LIMIT * _du
                    _act = TRAIL_ACTIVATE * _du
                    _give = TRAIL_GIVEBACK * _du

                    if st.get("protection_state", S_ACTIVE) == S_ACTIVE:
                        stop_reason = None
                        stop_why = None

                        # The hard loss takes priority over the profit trail.
                        if daily_total <= -_limit:
                            stop_reason = "daily_loss"
                            stop_why = (f"daily bot P&L {daily_total:+.2f} <= "
                                        f"-${_limit:.2f}")
                        else:
                            if (not st.get("trail_armed") and
                                    daily_total >= _act):
                                st["trail_armed"] = True
                                st["trail_peak"] = daily_total
                                st["trail_floor"] = max(
                                    0.0, daily_total - _give)
                                save_state(st)
                                rec_event("trail_armed", day=day_id,
                                          daily_total=round(daily_total, 4),
                                          peak=round(st["trail_peak"], 4),
                                          floor=round(st["trail_floor"], 4))
                                say(f"TRAIL ARMED at {daily_total:+.2f}; "
                                    f"floor {st['trail_floor']:+.2f}")
                            elif (st.get("trail_armed") and
                                  daily_total > st.get("trail_peak", 0.0)):
                                st["trail_peak"] = daily_total
                                new_floor = max(0.0,
                                                daily_total - _give)
                                if new_floor > st.get("trail_floor", 0.0):
                                    st["trail_floor"] = new_floor
                                    rec_event("trail_peak", day=day_id,
                                              daily_total=round(daily_total, 4),
                                              peak=round(daily_total, 4),
                                              floor=round(new_floor, 4))
                                    say(f"trail peak {daily_total:+.2f}; "
                                        f"floor raised to {new_floor:+.2f}")
                                save_state(st)

                            if (st.get("trail_armed") and
                                    daily_total <= st.get("trail_floor", 0.0)):
                                stop_reason = "profit_trail"
                                stop_why = (f"daily bot P&L {daily_total:+.2f} <= "
                                            f"trail floor {st['trail_floor']:+.2f}")

                        if stop_reason:
                            st["protection_trigger_total"] = round(daily_total, 2)
                            save_state(st)
                            rec_event("protection_trigger", reason=stop_reason,
                                      day=day_id,
                                      daily_total=round(daily_total, 4),
                                      peak=round(st.get("trail_peak", 0.0), 4),
                                      floor=round(st.get("trail_floor", 0.0), 4),
                                      positions=len(ps), **acct_snapshot())
                            say(f"*** PROTECTION HIT: {stop_why}; closing "
                                f"{len(ps)} position(s) ***")
                            if protection_liquidate(st, ps, stop_reason, stop_why):
                                ps = []
                                finish_protection_measurement(st)
                    save_state(st)
            else:
                if st.get("protection_history_ok") is not False:
                    rec_event("protection_history_unavailable",
                              last_error=str(mt5.last_error()))
                    say("PROTECTION HISTORY UNAVAILABLE - blocking all new orders")
                st["protection_history_ok"] = False
                save_state(st)

            protection_blocks_orders = (
                not protection_data_ok or
                st.get("protection_state") in (S_LIQUIDATING, S_STOPPED))

            # ---- unconfirmed basket close: finish it FIRST ------------
            # The trigger condition (cyc >= 0, cap breach) may no longer hold
            # by now - price moved. The DECISION was already made and persisted,
            # so it is carried out unconditionally until the book is confirmed
            # empty. Nothing else happens while this is outstanding.
            if st.get("close_pending"):
                if ps:
                    say(f"resuming unconfirmed close [{st['close_pending']}] "
                        f"- {len(ps)} position(s) left")
                    if close_all_verified(ps, f"{st['close_pending']} (resumed)"):
                        st["close_pending"] = None
                        st["recovery"] = False; st["cycle_equity"] = None
                        st["cycle_tickets"] = []; save_state(st)
                        ps = []
                else:
                    # everything filled/closed on its own between polls
                    say(f"pending close [{st['close_pending']}] - book already empty")
                    st["close_pending"] = None
                    st["recovery"] = False; st["cycle_equity"] = None
                    st["cycle_tickets"] = []; save_state(st)

            # This bot's own cycle P&L: banked on this cycle's tickets, plus
            # what is still floating. NOT account equity - see the 2026-08-05
            # note at the top of this file.
            tickets = st.get("cycle_tickets") or []
            if ps and not tickets:
                # Restarted holding positions with no ticket list (state file
                # lost or pre-fix). Adopt what is open so the cycle is at least
                # measurable; anything banked before the restart is gone from
                # the count, so say so rather than pretend the number is clean.
                tickets = [p.ticket for p in ps]
                st["cycle_tickets"] = tickets
                # The cycle's direction is the OLDEST position's - that is the
                # trade the whole basket is supposed to be following.
                oldest = min(ps, key=lambda p: p.time)
                st["cycle_dir"] = 1 if oldest.type == 0 else -1
                say(f"adopted {len(tickets)} untracked position(s) into the cycle "
                    f"- realised P&L before this restart is not counted; "
                    f"cycle direction taken from the oldest position: "
                    f"{'BUY' if st['cycle_dir'] == 1 else 'SELL'}")
                save_state(st)
            realised = cycle_realised(tickets)
            cyc = None if realised is None else realised + basket_pnl(ps)

            if not ps:
                # flat: this is where a new cycle begins
                st["recovery"] = False
                st["cycle_equity"] = eq
                st["cycle_tickets"] = []
                st["cycle_dir"] = None          # next cycle sets its own
                save_state(st)
            else:
                # has anything gone SL_BRICKS against us? -> recovery
                if not st.get("recovery"):
                    tick = mt5.symbol_info_tick(SYMBOL)
                    for p in ps:
                        adverse = (p.price_open - tick.bid) if p.type == 0 else (tick.ask - p.price_open)
                        if adverse >= BRICK * SL_BRICKS:
                            st["recovery"] = True
                            shown = "unknown" if cyc is None else f"{cyc:+.2f}"
                            say(f"RECOVERY ON - #{p.ticket} is {adverse:.0f} pts "
                                f"against; own cycle P&L {shown}, recovering to 0.00")
                            save_state(st); break
                # exit conditions. cyc is None only when the deal history could
                # not be read - hold rather than guess, the next poll retries.
                if st.get("recovery") and cyc is not None and cyc >= 0:
                    # persist the DECISION before the attempt - if the close
                    # fails and price moves, cyc >= 0 may never be true again
                    st["close_pending"] = "recovered"; save_state(st)
                    if close_all_verified(ps,
                            f"recovered - own cycle P&L {cyc:+.2f} "
                            f"(realised {realised:+.2f} + floating {basket_pnl(ps):+.2f})"):
                        st["close_pending"] = None
                        st["recovery"] = False; st["cycle_equity"] = None
                        st["cycle_tickets"] = []; save_state(st)
                        ps = []
                elif len(ps) > MAX_BASKET:
                    st["close_pending"] = "basket cap"; save_state(st)
                    if close_all_verified(ps,
                            f"basket cap {MAX_BASKET} exceeded - taking the loss"
                            + (f", cycle P&L {cyc:+.2f}" if cyc is not None else "")):
                        st["close_pending"] = None
                        st["recovery"] = False; st["cycle_equity"] = None
                        st["cycle_tickets"] = []; save_state(st)
                        ps = []

            # entries: one when flat, more only while recovering.
            # A pending close blocks EVERYTHING - opening anything while the
            # book is half-closed rebuilds the basket the bot is trying to end.
            first_signal_observation = False
            signal_context = {}
            if (rev and rev["time"] > st.get("last_brick", 0) and
                    rev["time"] > st.get("last_signal_observed", 0)):
                signal_context = closed_m1_context(
                    rates[:-1], rev, mt5.symbol_info_tick(SYMBOL))
                first_signal_observation = True
                st["last_signal_observed"] = rev["time"]
                rec_event("signal_seen", **signal_context,
                          positions=len(ps), recovery=bool(st.get("recovery")),
                          cycle_direction=("BUY" if st.get("cycle_dir") == 1 else
                                           "SELL" if st.get("cycle_dir") == -1 else None),
                          protection_state=st.get("protection_state", S_ACTIVE),
                          daily_total=st.get("daily_total"),
                          trail_armed=bool(st.get("trail_armed")))
                save_state(st)

            block_reason = None
            if st.get("close_pending"):
                block_reason = "basket_close_unconfirmed"
            elif protection_blocks_orders:
                if not protection_data_ok:
                    block_reason = "protection_history_unavailable"
                else:
                    block_reason = ("protection_" +
                                    st.get("protection_state", S_STOPPED).lower())

            if block_reason and rev and rev["time"] > st.get("last_brick", 0):
                say(f"skip signal: {block_reason.replace('_', ' ')}")
                rec_event("signal_skipped", reason=block_reason, **signal_context)
                st["last_brick"] = rev["time"]; save_state(st)
                rev = None
            if rev and rev["time"] > st.get("last_brick", 0):
                age = (datetime.utcnow() - datetime.utcfromtimestamp(rev["time"])).total_seconds() / 60
                if age <= FRESH_MIN:
                    ps = mine()
                    _floor = FLOOR_USD * scale_units(acc.balance)
                    if not ps and eq <= _floor:
                        say(f"EQUITY FLOOR: {eq:.2f} <= {_floor:.2f} - no new cycle")
                        rec_event("signal_skipped", reason="account_equity_floor",
                                  equity=round(eq, 2), **signal_context)
                        st["last_brick"] = rev["time"]; save_state(st)
                    elif not ps:
                        # THE COMBO GATE - both conditions must hold before a
                        # new cycle may open. Recovery adds are untouched.
                        _today = datetime.utcnow().strftime("%Y-%m-%d")
                        if st.get("cycles_day") != _today:
                            st["cycles_day"] = _today
                            st["cycles_today"] = 0
                        _bd, _fresh = big_dir_at(rates[:-1], rev["time"])
                        _side = "BUY" if rev["dir"] == 1 else "SELL"
                        if st.get("cycles_today", 0) >= MAX_CYCLES_PER_DAY:
                            say(f"skip new cycle: day cap reached "
                                f"({st.get('cycles_today')}/{MAX_CYCLES_PER_DAY} cycles today)")
                            rec_event("signal_skipped", reason="combo_daily_cap",
                                      **signal_context)
                            st["last_brick"] = rev["time"]
                        elif _bd != rev["dir"] or not _fresh:
                            _big = {1: "UP", -1: "DOWN", 0: "NONE"}[_bd]
                            _why = ("stale (big series moved past its reversal)"
                                    if _bd == rev["dir"] else f"direction is {_big}")
                            say(f"skip new cycle: signal {_side} but $150-brick {_why}")
                            rec_event("signal_skipped", reason="combo_big_brick",
                                      big_dir=_big, fresh=_fresh, **signal_context)
                            st["last_brick"] = rev["time"]
                        else:
                            # a new cycle starts with an empty ticket list, so
                            # its P&L begins at exactly zero. Lots are set HERE
                            # from the balance and frozen for the whole cycle.
                            st["cycle_tickets"] = []
                            cyc_lots = round(0.01 * scale_units(acc.balance), 2)
                            tk = open_one(rev["dir"], "new cycle (combo pass)",
                                          rev, rates[:-1], lots=cyc_lots)
                            if tk:
                                st["last_brick"] = rev["time"]; st["cycle_equity"] = eq
                                st["cycle_tickets"] = [tk]
                                st["cycle_lots"] = cyc_lots
                                st["cycles_today"] = st.get("cycles_today", 0) + 1
                                st["cycle_dir"] = rev["dir"]   # the whole cycle follows this
                    elif st.get("recovery") and len(ps) <= MAX_BASKET:
                        # SAME-DIRECTION ONLY. A reversal pointing against the
                        # first trade is marked seen and skipped, not queued -
                        # otherwise it would be reconsidered on every poll.
                        if st.get("cycle_dir") is not None and rev["dir"] != st["cycle_dir"]:
                            say(f"skip add: reversal is "
                                f"{'BUY' if rev['dir'] == 1 else 'SELL'} but the cycle "
                                f"is {'BUY' if st['cycle_dir'] == 1 else 'SELL'}")
                            rec_event("signal_skipped", reason="opposite_to_cycle",
                                      **signal_context)
                            st["last_brick"] = rev["time"]
                        else:
                            tk = open_one(rev["dir"], f"recovery add #{len(ps)+1}",
                                          rev, rates[:-1],
                                          lots=st.get("cycle_lots", LOTS))
                            if tk:
                                st["last_brick"] = rev["time"]
                                st["cycle_tickets"] = (st.get("cycle_tickets") or []) + [tk]
                    elif first_signal_observation:
                        # Keep the signal eligible for the rest of FRESH_MIN in
                        # case this basket enters recovery, but record why it did
                        # not trade on its first observation.
                        rec_event("signal_waiting", reason="holding_not_in_recovery",
                                  **signal_context)
                    save_state(st)
                else:
                    if first_signal_observation:
                        rec_event("signal_skipped", reason="stale",
                                  age_minutes=round(age, 3), **signal_context)
                    st["last_brick"] = rev["time"]; save_state(st)

            ps = mine()
            realised = cycle_realised(st.get("cycle_tickets") or [])
            cyc = None if realised is None else realised + basket_pnl(ps)
            with open(ALIVE, "w", encoding="utf-8") as f:
                json.dump({"alive_utc": datetime.utcnow().isoformat(),
                           "positions": len(ps), "basket_pnl": round(basket_pnl(ps), 2),
                           "recovery": bool(st.get("recovery")),
                           "cycle_pnl": None if cyc is None else round(cyc, 2),
                           "cycle_realised": None if realised is None else round(realised, 2),
                           "cycle_tickets": len(st.get("cycle_tickets") or []),
                           "cycle_dir": ("BUY" if st.get("cycle_dir") == 1 else
                                         "SELL" if st.get("cycle_dir") == -1 else None),
                           "cycle_equity": st.get("cycle_equity"),
                           "protection_day": st.get("protection_day"),
                           "daily_total": st.get("daily_total"),
                           "protection_state": st.get("protection_state", S_ACTIVE),
                           "protection_stop_reason": st.get("protection_stop_reason"),
                           "protection_history_ok": st.get("protection_history_ok"),
                           "day_units": st.get("day_units", 1),
                           "cycle_lots": st.get("cycle_lots", LOTS),
                           "trail_activate": TRAIL_ACTIVATE * (st.get("day_units", 1) or 1),
                           "trail_giveback": TRAIL_GIVEBACK * (st.get("day_units", 1) or 1),
                           "daily_loss_limit": DAILY_LOSS_LIMIT * (st.get("day_units", 1) or 1),
                           "trail_armed": bool(st.get("trail_armed")),
                           "trail_peak": round(st.get("trail_peak", 0.0), 2),
                           "trail_floor": round(st.get("trail_floor", 0.0), 2),
                           "protection_trigger_total": st.get("protection_trigger_total"),
                           "protection_final_total": st.get("protection_final_total"),
                           "equity": eq}, f)
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
