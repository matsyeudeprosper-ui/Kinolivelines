"""harvest_journal.py - v2. Cycle-aware journals for the harvest bots.

Three files per account, as recommended in review:

  *_deals.csv   one row per POSITION, with every broker cost and the market
                context at entry
  *_cycles.csv  one row per CYCLE - the summary you actually judge the
                strategy on
  *_events.csv  every signal, skip, order attempt and basket close, parsed
                from the bot's own log

READ ONLY. Never sends an order.

WHAT v1 GOT WRONG (all fixed here, all confirmed against broker history)

  1. balance_after was accumulated in OPEN order, but the balance moves in
     CLOSE order. In live cycle 2 the third position closed FIRST on its
     take-profit, so every intermediate balance in that cycle was wrong. The
     running balance is now accumulated over deals sorted by close time.

  2. `points` held a raw price difference, not MT5 points. BTCUSDm has a point
     of 0.01, so "4.54" was really 454 points. Both are now recorded:
     price_move (dollars of BTC) and broker_points (price_move / point).

  3. `fee` was never read and entry-side commission was ignored. Both are zero
     on this account today, so no past number changes - but a broker that
     charges either would have been silently under-reported.

  4. Partial closes were half-handled. All OUT deals for a position are now
     aggregated: costs summed, exit price volume-weighted, and the number of
     exit deals recorded so a partial close is visible rather than hidden.

  5. `ticket` was a position_id wearing the wrong name. position_id,
     entry_deal, exit_deal and order tickets are now separate columns.

  6. Exit reason was missing entirely. MT5 stores it on the deal: reason 5 is
     a take-profit, 3 is the expert closing it. That distinction is the whole
     difference between "harvested" and "recovered", and it was invisible.

SLIPPAGE. The bot logs the price it asked for; the deal carries the price it
got. Matching them gives real slippage without touching the trading bot. This
is not cosmetic: live cycle 2 was decided at a floating -1.87 and filled at
-2.04, so 0.17 of a 0.47 result - a third of it - happened during execution.

ORDER-TIME DATA (v3). Spread, latency, retcode, request id and free margin
cannot be recovered from history at all - they exist only at the instant the
order goes out. The bots now write them to `*_events.jsonl` and this file joins
them in ON THE DEAL TICKET, never on time.

Broker history stays the authority for money. MT5's order result is what the
server said at send time, and an accepted order can still finish differently,
so the events supply context only - never a P&L figure.

v3 also fixed, per review 2026-08-07:
  - cycle_id is now the first position's ticket. A sequence number changed
    whenever LOOKBACK_DAYS changed, quietly breaking any earlier join.
  - avg_entry is volume-weighted; first_entry and last_exit come from the
    positions that actually opened first and closed last, not from list order.
  - money conversion asks the broker via order_calc_profit instead of assuming
    $0.01 per price unit.
  - MAE/MFE renamed m1_estimated_*: they are read off M1 bars, so they miss
    part of the entry minute and can include movement after the exit.
  - exit_reason covers stop-out, rollover and margin events, which must never
    be lumped in with an ordinary bot close.
"""
import os
import re
import sys
import csv
import json
import time
import calendar
from datetime import datetime, timedelta

import numpy as np
import MetaTrader5 as mt5

HERE = os.path.dirname(os.path.abspath(__file__))
ALIVE = os.path.join(HERE, "harvest_journal_alive.json")
LOG = os.path.join(HERE, "harvest_journal.log")
POLL = 120
LOOKBACK_DAYS = 90
STRATEGY_VERSION = "harvest-same-direction-v1"

FEEDS = (
    dict(name="live",
         terminal=r"C:\Projects\MT5-KinoliveTrader\terminal64.exe",
         login=134499778, magic=770407,
         botlog=os.path.join(HERE, "harvest_live.log"),
         prefix=os.path.join(HERE, "harvest_live")),
    dict(name="demo",
         terminal=r"C:\Program Files\MetaTrader 5\terminal64.exe",
         login=436771046, magic=770405,
         botlog=os.path.join(HERE, "renko_recovery.log"),
         prefix=os.path.join(HERE, "harvest_demo")),
)

# the bot's own parameters, so the journal can state the parameter set it is
# describing rather than leaving the reader to guess
PARAMS = dict(brick=50.0, reversal=2, tp_bricks=5, sl_bricks=3,
              max_basket=4, lots=0.01)
PARAM_ID = "b50-r2-tp5-sl3-cap4-l0.01"

DEAL_COLS = [
    "strategy_version", "param_id", "cycle_id", "cycle", "seq", "role",
    "position_id", "entry_deal", "exit_deal", "entry_order", "exit_order",
    "side", "lots", "n_exit_deals",
    "open_time", "open_price", "requested_price", "slippage_price",
    "slippage_points", "slippage_usd",
    "close_time", "close_price", "minutes",
    "price_move", "broker_points",
    "profit", "swap", "commission", "fee", "net",
    "exit_reason", "exit_comment",
    "m1_estimated_mae_price", "m1_estimated_mfe_price",
    "m1_estimated_mae_usd", "m1_estimated_mfe_usd",
    "atr_m1_14", "atr_m5_14", "atr_over_brick",
    "ema20", "ema50", "dist_ema20_atr", "dist_ema50_atr",
    "utc_hour", "dow", "session",
    # from the bots' order-time JSONL - none of this exists in broker history
    "spread_at_entry", "latency_ms_entry", "retcode_entry",
    "broker_comment_entry", "request_id", "free_margin_at_entry",
    "spread_at_exit", "latency_ms_exit", "retcode_exit", "decided_cycle_pnl",
    "balance_after",
]

CYCLE_COLS = [
    "strategy_version", "param_id", "cycle_id", "cycle", "direction",
    "opened", "closed", "hours", "trades", "adds", "max_concurrent",
    "tp_exits", "bot_exits",
    "gross_profit", "swap", "commission", "fee", "cycle_net",
    "max_floating_loss", "mae_usd", "recovery", "minutes_in_recovery",
    "skipped_opposite", "first_entry", "avg_entry", "last_exit",
    "balance_after",
]

EVENT_COLS = ["time", "kind", "detail"]

SESSIONS = ((0, 7, "asia"), (7, 13, "europe"), (13, 21, "us"), (21, 24, "late"))

# DEAL_REASON_*. Stop-out and margin events must be distinguishable from an
# ordinary bot close - they mean something completely different happened.
EXIT_REASON = {0: "client", 1: "mobile", 2: "web", 3: "bot",
               4: "stop_loss", 5: "take_profit", 6: "stop_out",
               7: "rollover", 8: "external_vmargin", 9: "split"}


def say(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def session_of(hour):
    for lo, hi, nm in SESSIONS:
        if lo <= hour < hi:
            return nm
    return "late"


# ---------------------------------------------------------------- log parsing
RE_OPEN = re.compile(r"^\[(.+?)\] OPEN (BUY|SELL) ([\d.]+) @ ([\d.]+) TP ([\d.]+)\s+\[(.+?)\]")
RE_RET = re.compile(r"^\[(.+?)\]\s+retcode (\S+) ->\s*(\w+)")
RE_TICKET = re.compile(r"^\[(.+?)\]\s+position ticket (\d+)")
RE_SKIP = re.compile(r"^\[(.+?)\] skip add: (.+)$")
RE_REC = re.compile(r"^\[(.+?)\] RECOVERY ON - (.+)$")
RE_CLOSE = re.compile(r"^\[(.+?)\] CLOSE BASKET of (\d+)\s+pnl ([-+\d.]+)\s+\[(.+?)\]")
RE_FLOOR = re.compile(r"^\[(.+?)\] EQUITY FLOOR: (.+)$")


def load_order_events(botlog_path):
    """The bots' structured order-time records, keyed by broker deal ticket.

    Joined on the DEAL id, not on time. The order result MT5 hands back at send
    time is not the last word - an accepted order can still finish differently -
    so broker history stays the authority for money, and these events supply
    only what history cannot know: spread, latency, retcode and free margin.
    """
    path = botlog_path.replace(".log", "_events.jsonl")
    op, cl, dec = {}, {}, []
    if not os.path.exists(path):
        return op, cl, dec
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    e = json.loads(ln)
                except Exception:
                    continue          # a torn last line while the bot writes
                k = e.get("kind")
                if k == "order_open" and e.get("deal"):
                    op[int(e["deal"])] = e
                elif k == "order_close" and e.get("deal"):
                    cl[int(e["deal"])] = e
                elif k == "close_decided":
                    dec.append(e)
    except Exception:
        pass
    return op, cl, dec


def parse_botlog(path, tz_shift_hours):
    """Pull events out of the bot's text log.

    The log stamps BOX local time while every broker timestamp is UTC, so the
    two are reconciled here once rather than at each use. Getting this backwards
    would silently mis-pair every requested price with its fill.
    """
    events, requested = [], []
    if not os.path.exists(path):
        return events, requested
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except Exception:
        return events, requested

    pending = None
    for ln in lines:
        ln = ln.rstrip("\n")
        for rx, kind in ((RE_OPEN, "open"), (RE_RET, "retcode"),
                         (RE_TICKET, "ticket"), (RE_SKIP, "skip"),
                         (RE_REC, "recovery_on"), (RE_CLOSE, "close_basket"),
                         (RE_FLOOR, "equity_floor")):
            m = rx.match(ln)
            if not m:
                continue
            try:
                t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") \
                    + timedelta(hours=tz_shift_hours)
            except ValueError:
                break
            events.append(dict(time=t.strftime("%Y-%m-%d %H:%M:%S"),
                               kind=kind, detail=ln.split("] ", 1)[-1]))
            if kind == "open":
                pending = dict(t=t, side=m.group(2), price=float(m.group(4)),
                               why=m.group(6), ticket=None)
            elif kind == "ticket" and pending is not None:
                pending["ticket"] = int(m.group(2))
                requested.append(pending)
                pending = None
            break
    return events, requested


# ------------------------------------------------------------ market context
def context_frames(terminal_open_already, symbol="BTCUSDm"):
    """M1 and M5 frames with ATR(14) and EMAs, computed on CLOSED bars only."""
    out = {}
    for key, tf, n, secs in (("m1", mt5.TIMEFRAME_M1, 40000, 60),
                             ("m5", mt5.TIMEFRAME_M5, 20000, 300)):
        r = mt5.copy_rates_from_pos(symbol, tf, 0, n)
        if r is None or len(r) < 60:
            out[key] = None
            continue
        h, l, c = (r[k].astype(float) for k in ("high", "low", "close"))
        pc = np.concatenate([[c[0]], c[:-1]])
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        atr = np.convolve(tr, np.ones(14) / 14, mode="full")[:len(tr)]
        atr[:14] = np.nan

        def ema(x, span):
            a = 2.0 / (span + 1)
            e = np.empty_like(x)
            e[0] = x[0]
            for i in range(1, len(x)):
                e[i] = a * x[i] + (1 - a) * e[i - 1]
            return e

        out[key] = dict(t=r["time"].astype(np.int64), atr=atr, close=c,
                        ema20=ema(c, 20), ema50=ema(c, 50),
                        high=h, low=l, secs=secs)
    return out


def last_closed_before(frame, ts):
    """Index of the last bar that had FULLY CLOSED before ts.

    The obvious version - searchsorted minus one - returns the bar that CONTAINS
    ts, and that bar has not finished when the order goes out. Its high, low and
    close include price action from after the entry, so any ATR or EMA taken
    from it is reading the future. Requiring open_time + duration <= ts removes
    that: the context is what the bot could actually have known.
    """
    if frame is None:
        return None
    i = int(np.searchsorted(frame["t"], ts - frame["secs"], side="right")) - 1
    return i if 0 <= i < len(frame["t"]) else None


def basket_mae(frame, grp, usd):
    """Worst floating P&L the CYCLE ever showed, as a basket.

    Summing each position's own worst excursion is not the same number and is
    always harsher: the positions do not all reach their worst point at the same
    instant. Live cycle 2 sums to -19.95 that way, but the basket never actually
    showed worse than about -15. Since this column is meant to be the loss the
    account really displayed, it has to be evaluated bar by bar over the whole
    basket.
    """
    if frame is None or not grp:
        return 0.0
    t0 = min(t["t_in"] for t in grp)
    t1 = max(t["t_out"] for t in grp)
    a = int(np.searchsorted(frame["t"], t0, side="left"))
    b = int(np.searchsorted(frame["t"], t1, side="right"))
    if b <= a:
        return 0.0
    ts = frame["t"][a:b]
    hi, lo = frame["high"][a:b], frame["low"][a:b]
    worst = 0.0
    for k in range(len(ts)):
        tot = 0.0
        for t in grp:
            if not (t["t_in"] <= ts[k] <= t["t_out"]):
                continue
            # the worst this bar could have shown for this position
            adverse = lo[k] if t["long"] else hi[k]
            move = (adverse - t["p_in"]) if t["long"] else (t["p_in"] - adverse)
            tot += usd(move, t["lots"])
        worst = min(worst, tot)
    return worst


def excursion(frame, t_in, t_out, entry, is_long):
    """Worst and best price reached while the position was open (MAE / MFE)."""
    if frame is None or t_out <= t_in:
        return 0.0, 0.0
    a = int(np.searchsorted(frame["t"], t_in, side="left"))
    b = int(np.searchsorted(frame["t"], t_out, side="right"))
    if b <= a or a >= len(frame["t"]):
        return 0.0, 0.0
    hi = float(np.max(frame["high"][a:b]))
    lo = float(np.min(frame["low"][a:b]))
    if is_long:
        return entry - lo, hi - entry
    return hi - entry, entry - lo


# ----------------------------------------------------------------- collection
def collect(feed):
    if not mt5.initialize(path=feed["terminal"]):
        return None, f"terminal unreachable: {mt5.last_error()}"
    try:
        a = mt5.account_info()
        if a is None:
            return None, "no account_info"
        if a.login != feed["login"]:
            return None, f"WRONG ACCOUNT {a.login}, expected {feed['login']}"
        sym = mt5.symbol_info("BTCUSDm")
        point = sym.point if sym else 0.01
        # Ask the broker what one price unit is worth rather than assuming
        # $0.01 per 1.00 at 0.01 lots. The assumption happens to be right for
        # BTCUSDm on Exness and would be wrong on anything else, including this
        # symbol if the contract size ever changes.
        px = sym.bid if (sym and sym.bid) else 60000.0
        calc = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, "BTCUSDm", 0.01, px, px + 1.0)
        usd_per_unit = calc if (calc is not None and calc > 0) else 0.01
        deals = mt5.history_deals_get(datetime.now() - timedelta(days=LOOKBACK_DAYS),
                                      datetime.now() + timedelta(days=1))
        if deals is None:
            return None, f"history_deals_get failed: {mt5.last_error()}"
        balance = a.balance
        frames = context_frames(True)
    finally:
        mt5.shutdown()

    # box local time -> UTC, measured from this machine rather than assumed
    tz_shift = round((datetime.utcnow() - datetime.now()).total_seconds() / 3600)
    events, requested = parse_botlog(feed["botlog"], tz_shift)
    ev_open, ev_close, ev_decided = load_order_events(feed["botlog"])
    req_by_ticket = {r["ticket"]: r for r in requested if r["ticket"]}

    ours = [d for d in deals if d.magic == feed["magic"]]
    ins = {d.position_id: d for d in ours if d.entry == mt5.DEAL_ENTRY_IN}

    outs = {}
    for d in ours:
        if d.entry != mt5.DEAL_ENTRY_OUT:
            continue
        o = outs.setdefault(d.position_id, dict(
            time=0, vol=0.0, pxvol=0.0, profit=0.0, swap=0.0,
            commission=0.0, fee=0.0, n=0, reason=None, comment="",
            deal=None, order=None))
        o["n"] += 1
        o["vol"] += d.volume
        o["pxvol"] += d.price * d.volume          # volume-weighted exit price
        o["profit"] += d.profit
        o["swap"] += d.swap
        o["commission"] += d.commission
        o["fee"] += getattr(d, "fee", 0.0)
        if d.time >= o["time"]:                   # keep the LAST leg's identity
            o.update(time=d.time, reason=getattr(d, "reason", None),
                     comment=d.comment, deal=d.ticket, order=d.order)

    done = []
    for pid, di in ins.items():
        do = outs.get(pid)
        if do is None:
            continue
        done.append(dict(
            pid=pid, side="BUY" if di.type == mt5.DEAL_TYPE_BUY else "SELL",
            long=(di.type == mt5.DEAL_TYPE_BUY), lots=di.volume,
            t_in=di.time, p_in=di.price, entry_deal=di.ticket,
            entry_order=di.order,
            entry_comm=di.commission, entry_fee=getattr(di, "fee", 0.0),
            t_out=do["time"], p_out=(do["pxvol"] / do["vol"]) if do["vol"] else do["pxvol"],
            exit_deal=do["deal"], exit_order=do["order"], n_out=do["n"],
            profit=do["profit"], swap=do["swap"],
            commission=do["commission"] + di.commission,
            fee=do["fee"] + getattr(di, "fee", 0.0),
            reason=do["reason"], comment=do["comment"]))
    done.sort(key=lambda x: (x["t_in"], x["pid"]))

    # ---- cycles, from the position set (rule 7), not from the clock --------
    cycle = 0
    open_until = []
    for t in done:
        open_until = [c for c in open_until if c > t["t_in"]]
        if not open_until:
            cycle += 1
            seq = 0
        seq += 1
        t["cycle"] = cycle
        t["seq"] = seq
        t["role"] = "first" if seq == 1 else f"add {seq - 1}"
        open_until.append(t["t_out"])

    for t in done:
        t["net"] = t["profit"] + t["swap"] + t["commission"] + t["fee"]

    # Stable identity: the ticket of the cycle's FIRST position. A sequence
    # number is not stable - changing LOOKBACK_DAYS renumbers every cycle and
    # silently invalidates anything joined to an earlier export.
    cyc_uid = {}
    for t in done:
        cyc_uid.setdefault(t["cycle"], t["pid"])

    # ---- running balance in CLOSE order (v1 bug) --------------------------
    by_close = sorted(done, key=lambda x: (x["t_out"], x["exit_deal"] or 0))
    running = balance - sum(t["net"] for t in done)
    for t in by_close:
        running += t["net"]
        t["balance_after"] = running

    def usd(pricemove, lots):
        """Price movement -> account currency, using the broker's own figure."""
        return pricemove * (lots / 0.01) * usd_per_unit

    m1, m5 = frames.get("m1"), frames.get("m5")
    drows = []
    for t in done:
        i1 = last_closed_before(m1, t["t_in"])
        i5 = last_closed_before(m5, t["t_in"])
        atr1 = float(m1["atr"][i1]) if i1 is not None and not np.isnan(m1["atr"][i1]) else None
        atr5 = float(m5["atr"][i5]) if i5 is not None and not np.isnan(m5["atr"][i5]) else None
        e20 = float(m1["ema20"][i1]) if i1 is not None else None
        e50 = float(m1["ema50"][i1]) if i1 is not None else None
        mae_p, mfe_p = excursion(m1, t["t_in"], t["t_out"], t["p_in"], t["long"])

        rq = req_by_ticket.get(t["pid"])
        slip_price = slip_pts = slip_usd = ""
        if rq is not None:
            sp = (t["p_in"] - rq["price"]) if t["long"] else (rq["price"] - t["p_in"])
            slip_price = f"{sp:.2f}"
            slip_pts = f"{sp / point:.0f}"
            # signed as P&L impact: POSITIVE means the fill was better than
            # asked for. Getting this backwards would make good execution look
            # like a cost.
            slip_usd = f"{-usd(sp, t['lots']):.2f}"

        eo = ev_open.get(t["entry_deal"], {})
        ec = ev_close.get(t["exit_deal"], {})
        move = (t["p_out"] - t["p_in"]) if t["long"] else (t["p_in"] - t["p_out"])
        dt_in = datetime.utcfromtimestamp(t["t_in"])
        drows.append({
            "strategy_version": STRATEGY_VERSION, "param_id": PARAM_ID,
            "cycle_id": f'{feed["name"]}-{cyc_uid[t["cycle"]]}', "cycle": t["cycle"],
            "seq": t["seq"], "role": t["role"],
            "position_id": t["pid"], "entry_deal": t["entry_deal"],
            "exit_deal": t["exit_deal"], "entry_order": t["entry_order"],
            "exit_order": t["exit_order"],
            "side": t["side"], "lots": f'{t["lots"]:.2f}', "n_exit_deals": t["n_out"],
            "open_time": dt_in.strftime("%Y-%m-%d %H:%M:%S"),
            "open_price": f'{t["p_in"]:.2f}',
            "requested_price": f'{rq["price"]:.2f}' if rq else "",
            "slippage_price": slip_price, "slippage_points": slip_pts,
            "slippage_usd": slip_usd,
            "close_time": datetime.utcfromtimestamp(t["t_out"]).strftime("%Y-%m-%d %H:%M:%S"),
            "close_price": f'{t["p_out"]:.2f}',
            "minutes": f'{(t["t_out"] - t["t_in"]) / 60:.1f}',
            "price_move": f"{move:.2f}", "broker_points": f"{move / point:.0f}",
            "profit": f'{t["profit"]:.2f}', "swap": f'{t["swap"]:.2f}',
            "commission": f'{t["commission"]:.2f}', "fee": f'{t["fee"]:.2f}',
            "net": f'{t["net"]:.2f}',
            "exit_reason": EXIT_REASON.get(t["reason"], f'other_{t["reason"]}'),
            "exit_comment": t["comment"],
            "m1_estimated_mae_price": f"{mae_p:.2f}",
            "m1_estimated_mfe_price": f"{mfe_p:.2f}",
            "m1_estimated_mae_usd": f'{-usd(mae_p, t["lots"]):.2f}',
            "m1_estimated_mfe_usd": f'{usd(mfe_p, t["lots"]):.2f}',
            "atr_m1_14": f"{atr1:.2f}" if atr1 else "",
            "atr_m5_14": f"{atr5:.2f}" if atr5 else "",
            "atr_over_brick": f"{atr1 / PARAMS['brick']:.2f}" if atr1 else "",
            "ema20": f"{e20:.2f}" if e20 else "",
            "ema50": f"{e50:.2f}" if e50 else "",
            "dist_ema20_atr": f'{(t["p_in"] - e20) / atr1:.2f}' if (e20 and atr1) else "",
            "dist_ema50_atr": f'{(t["p_in"] - e50) / atr1:.2f}' if (e50 and atr1) else "",
            "utc_hour": dt_in.hour, "dow": dt_in.strftime("%a"),
            "session": session_of(dt_in.hour),
            "spread_at_entry": eo.get("spread", ""),
            "latency_ms_entry": eo.get("latency_ms", ""),
            "retcode_entry": eo.get("retcode", ""),
            "broker_comment_entry": eo.get("broker_comment", ""),
            "request_id": eo.get("request_id", ""),
            "free_margin_at_entry": eo.get("margin_free", ""),
            "spread_at_exit": ec.get("spread", ""),
            "latency_ms_exit": ec.get("latency_ms", ""),
            "retcode_exit": ec.get("retcode", ""),
            "decided_cycle_pnl": ec.get("pos_profit", ""),
            "balance_after": f'{t["balance_after"]:.2f}',
        })

    # ---- one row per cycle -------------------------------------------------
    skips = [e for e in events if e["kind"] == "skip"]
    recs = [e for e in events if e["kind"] == "recovery_on"]
    crows = []
    for cy in sorted({t["cycle"] for t in done}):
        grp = [t for t in done if t["cycle"] == cy]
        t0 = min(t["t_in"] for t in grp)
        t1 = max(t["t_out"] for t in grp)
        # max concurrent: walk the open/close boundaries
        pts = sorted([(t["t_in"], 1) for t in grp] + [(t["t_out"], -1) for t in grp])
        cur = mx = 0
        for _, dlt in pts:
            cur += dlt
            mx = max(mx, cur)
        s0 = datetime.utcfromtimestamp(t0).strftime("%Y-%m-%d %H:%M:%S")
        s1 = datetime.utcfromtimestamp(t1).strftime("%Y-%m-%d %H:%M:%S")
        n_skip = sum(1 for e in skips if s0 <= e["time"] <= s1)
        # parse_botlog already shifted these to UTC. Feeding the string back
        # through .timestamp() would read it as LOCAL time and shift it a second
        # time - that double correction is what produced -534.5 minutes for a
        # cycle whose real answer is 65.5.
        rec_epoch = [calendar.timegm(
            datetime.strptime(e["time"], "%Y-%m-%d %H:%M:%S").timetuple())
            for e in recs if s0 <= e["time"] <= s1]
        rec_at = sorted(rec_epoch)
        mae_tot = basket_mae(m1, grp, usd)
        mae_sum = sum(float(r["m1_estimated_mae_usd"])
                      for r in drows if r["cycle"] == cy)
        crows.append({
            "strategy_version": STRATEGY_VERSION, "param_id": PARAM_ID,
            "cycle_id": f'{feed["name"]}-{cyc_uid[cy]}', "cycle": cy,
            "direction": grp[0]["side"],
            "opened": s0, "closed": s1,
            "hours": f"{(t1 - t0) / 3600:.1f}",
            "trades": len(grp), "adds": len(grp) - 1, "max_concurrent": mx,
            "tp_exits": sum(1 for t in grp if t["reason"] == 5),
            "bot_exits": sum(1 for t in grp if t["reason"] != 5),
            "gross_profit": f'{sum(t["profit"] for t in grp):.2f}',
            "swap": f'{sum(t["swap"] for t in grp):.2f}',
            "commission": f'{sum(t["commission"] for t in grp):.2f}',
            "fee": f'{sum(t["fee"] for t in grp):.2f}',
            "cycle_net": f'{sum(t["net"] for t in grp):.2f}',
            "max_floating_loss": f"{mae_tot:.2f}",     # the basket, bar by bar
            "mae_usd": f"{mae_sum:.2f}",               # sum of each leg's worst
            "recovery": "yes" if rec_at else "no",
            "minutes_in_recovery": f"{(t1 - rec_at[0]) / 60:.1f}" if rec_at else "0.0",
            "skipped_opposite": n_skip,
            "first_entry": f'{min(grp, key=lambda x: x["t_in"])["p_in"]:.2f}',
            # volume-weighted: a plain mean is only right while every leg is
            # the same size, which is true today and will not stay true
            "avg_entry": f'{sum(t["p_in"] * t["lots"] for t in grp) / sum(t["lots"] for t in grp):.2f}',
            # the position that actually closed LAST, not the last one opened
            "last_exit": f'{max(grp, key=lambda x: x["t_out"])["p_out"]:.2f}',
            # the balance after the LAST of this cycle's positions to close,
            # which is the only moment the cycle is really finished
            "balance_after": f'{max(grp, key=lambda x: x["t_out"])["balance_after"]:.2f}',
        })

    return dict(deals=drows, cycles=crows, events=events), None


def write(path, cols, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def main():
    say(f"harvest journal v2 up | poll {POLL}s | {len(FEEDS)} accounts")
    fails = 0
    while True:
        counts = {}
        for feed in FEEDS:
            got, err = collect(feed)
            if err:
                say(f"{feed['name']}: {err}")
                fails += 1
                continue
            write(feed["prefix"] + "_deals.csv", DEAL_COLS, got["deals"])
            write(feed["prefix"] + "_cycles.csv", CYCLE_COLS, got["cycles"])
            write(feed["prefix"] + "_events.csv", EVENT_COLS, got["events"])
            counts[feed["name"]] = dict(deals=len(got["deals"]),
                                        cycles=len(got["cycles"]),
                                        events=len(got["events"]))
            fails = 0
        if counts:
            with open(ALIVE, "w") as fh:
                json.dump(dict(alive_utc=datetime.utcnow().isoformat(),
                               version=2, counts=counts), fh)
        if fails >= 10:
            say("10 consecutive failures - exiting so the watchdog restarts me")
            sys.exit(1)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
