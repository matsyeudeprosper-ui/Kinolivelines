"""fakemt5.py - a MetaTrader5 stand-in for the REAL bot (botsim, 2026-10-25).

Prices are the broker's own: closed M1 candles from a broker bar file, the live (forming) candle and every quote from
the broker's recorded ticks. Orders fill at the ask (buy) / bid (sell) of the tick at the virtual moment the order is
sent; a stop closes at the first tick that crosses it (its price - slippage included), a target at its level. The
account (balance, positions, deals) lives here. Only the calls the bots make are implemented.
"""
import bisect
from collections import namedtuple

import numpy as np

# ---- the constants the bots read --------------------------------------------------------------------------------------
TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = 1, 5, 15, 30
TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = 16385, 16388, 16408
_TF_S = {1: 60, 5: 300, 15: 900, 30: 1800, 16385: 3600, 16388: 14400, 16408: 86400}
ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
ORDER_TIME_GTC = 0
ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
TRADE_RETCODE_DONE = 10009
DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1
DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1
ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2

RATES = np.dtype([("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
                  ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")])
Tick = namedtuple("Tick", "time bid ask last volume time_msc flags volume_real")
Account = namedtuple("Account", "login server company currency leverage margin_mode balance equity profit margin "
                                "margin_free trade_allowed trade_expert name")
Terminal = namedtuple("Terminal", "trade_allowed connected path")
Symbol = namedtuple("Symbol", "name description path digits point trade_contract_size trade_tick_size trade_tick_value "
                              "volume_min volume_step volume_max filling_mode trade_stops_level trade_freeze_level "
                              "trade_mode spread currency_profit visible select bid ask")
Result = namedtuple("Result", "retcode order deal price volume comment request_id")
_PosT = namedtuple("TradePosition", "ticket time time_msc type magic identifier volume price_open sl tp price_current "
                                    "swap profit symbol comment")
_DealT = namedtuple("TradeDeal", "ticket order time time_msc type entry magic position_id volume price commission "
                                 "swap profit fee symbol comment")


class Broker:
    def __init__(self, clock, bars_m1, ticks, symbol="BTCUSD", login=224016179, server="Exness-MT5Real30",
                 balance=200.0, log=None):
        self.clock = clock
        self.B = bars_m1                                  # closed broker M1 candles (structured, RATES dtype)
        self.tt, self.bid, self.ask = ticks               # ms, bid, ask (sorted)
        self.symbol, self.login, self.server = symbol, login, server
        self.balance = float(balance)
        self.pos = {}                                     # ticket -> dict
        self.deals = []
        self.n = 1000
        self.log = log or (lambda *a: None)
        self.fills = []                                   # (t, what, price) for the report
        clock.walkers.append(self.walk)
        self._agg = {}
        self.net_lag = 0.0          # s between a tick's time and the terminal having it (set by the runner)

    # ---- prices -------------------------------------------------------------------------------------------------------
    def _i(self, t):                                      # index of the last tick at or before t (seconds)
        return bisect.bisect_right(self.tt, int(t * 1000)) - 1

    def quote(self, t=None):
        i = self._i(self.clock.now if t is None else t)
        if i < 0:
            return None
        return float(self.bid[i]), float(self.ask[i]), int(self.tt[i])

    def m1_upto(self, t):
        """closed M1 bars before t, plus the forming bar built from ticks"""
        cut = int(t) // 60 * 60
        j = int(np.searchsorted(self.B["time"], cut))     # bars with open time < cut are closed
        closed = self.B[:j]
        if self.net_lag and j > 0 and t - cut < self.net_lag + 2.0:
            # the terminal receives a tick `net_lag` s after its time: a candle read right after its close may still
            # miss its last ticks - rebuild that candle from the ticks the terminal had at t
            lt = int(closed["time"][-1])
            a0 = bisect.bisect_left(self.tt, lt * 1000)
            b0 = bisect.bisect_right(self.tt, int((t - self.net_lag) * 1000))
            b0 = min(b0, bisect.bisect_left(self.tt, (lt + 60) * 1000))
            if b0 > a0:
                seg = self.bid[a0:b0]
                last = closed[-1:].copy()
                last["open"], last["high"], last["low"], last["close"] = seg[0], seg.max(), seg.min(), seg[-1]
                closed = np.concatenate([closed[:-1], last])
        a = bisect.bisect_left(self.tt, cut * 1000)
        b = bisect.bisect_right(self.tt, int(t * 1000))
        if b > a:
            seg = self.bid[a:b]
            f = np.zeros(1, dtype=RATES)
            f["time"] = cut
            f["open"], f["high"], f["low"], f["close"] = seg[0], seg.max(), seg.min(), seg[-1]
            f["tick_volume"] = b - a
            f["spread"] = int(round(float(np.median(self.ask[a:b] - self.bid[a:b])) * 100))
            return np.concatenate([closed, f])
        return closed

    def rates(self, tf, start, count):
        t = self.clock.now
        R = self.m1_upto(t)
        s = _TF_S.get(tf, 60)
        if s != 60:
            key = (tf, int(t) // 60)
            if key in self._agg:
                R = self._agg[key]
            else:
                g = R["time"] // s
                idx = np.nonzero(np.diff(np.concatenate([[-1], g])))[0]
                out = np.zeros(len(idx), dtype=RATES)
                out["time"] = g[idx] * s
                out["open"] = R["open"][idx]
                out["close"] = R["close"][np.append(idx[1:] - 1, len(R) - 1)]
                out["high"] = np.maximum.reduceat(R["high"], idx)
                out["low"] = np.minimum.reduceat(R["low"], idx)
                out["tick_volume"] = np.add.reduceat(R["tick_volume"], idx)
                self._agg = {key: out}
                R = out
        end = len(R) - int(start)
        if end <= 0:
            return None
        return R[max(0, end - int(count)):end].copy()

    # ---- the account --------------------------------------------------------------------------------------------------
    def _profit(self, p, bid, ask):
        px = bid if p["type"] == POSITION_TYPE_BUY else ask
        return (px - p["price"]) * p["volume"] * (1 if p["type"] == POSITION_TYPE_BUY else -1)

    def floating(self):
        q = self.quote()
        if not q:
            return 0.0
        return sum(self._profit(p, q[0], q[1]) for p in self.pos.values())

    def _close(self, tk, price, t, why, volume=None):
        p = self.pos[tk]
        vol = min(p["volume"], float(volume or p["volume"]))
        pnl = round((price - p["price"]) * vol * (1 if p["type"] == POSITION_TYPE_BUY else -1), 2)
        self.balance = round(self.balance + pnl, 2)
        self.n += 1
        self.deals.append(_DealT(self.n, self.n, int(t), int(t * 1000), DEAL_TYPE_SELL if p["type"] == POSITION_TYPE_BUY else DEAL_TYPE_BUY,
                                 DEAL_ENTRY_OUT, p["magic"], tk, vol, price, 0.0, 0.0, pnl, 0.0, self.symbol, why))
        self.fills.append((t, "close %s %s" % (tk, why), price, pnl))
        p["volume"] = round(p["volume"] - vol, 2)
        if p["volume"] <= 1e-9:
            del self.pos[tk]

    def walk(self, t0, t1):
        """stops and targets between t0 and t1, tick by tick for the open positions"""
        if not self.pos:
            return
        a = bisect.bisect_right(self.tt, int(t0 * 1000))
        b = bisect.bisect_right(self.tt, int(t1 * 1000))
        if b <= a:
            return
        bd, ak, tt = self.bid[a:b], self.ask[a:b], self.tt[a:b]
        for tk in list(self.pos):
            p = self.pos.get(tk)
            if p is None:
                continue
            buy = p["type"] == POSITION_TYPE_BUY
            px = bd if buy else ak
            hits = []
            if p["sl"]:
                w = np.nonzero(px <= p["sl"] if buy else px >= p["sl"])[0]
                if len(w):
                    hits.append((w[0], "sl"))
            if p["tp"]:
                w = np.nonzero(px >= p["tp"] if buy else px <= p["tp"])[0]
                if len(w):
                    hits.append((w[0], "tp"))
            if hits:
                k, why = min(hits)
                price = float(px[k]) if why == "sl" else float(p["tp"])
                self._close(tk, price, tt[k] / 1000.0, "[%s %s]" % (why, p["sl"] if why == "sl" else p["tp"]))

    def send(self, r):
        t = self.clock.t()
        q = self.quote(t)
        if q is None:
            return Result(10004, 0, 0, 0.0, 0.0, "no quote", 0)
        bid, ask, _ = q
        act = r.get("action")
        if act == TRADE_ACTION_SLTP:
            p = self.pos.get(int(r.get("position") or 0))
            if p is None:
                return Result(10013, 0, 0, 0.0, 0.0, "no position", 0)
            p["sl"], p["tp"] = float(r.get("sl") or 0.0), float(r.get("tp") or 0.0)
            self.fills.append((t, "sltp %s" % r.get("position"), p["sl"], p["tp"]))
            return Result(TRADE_RETCODE_DONE, 0, 0, 0.0, 0.0, "done", 0)
        if act != TRADE_ACTION_DEAL:
            return Result(10013, 0, 0, 0.0, 0.0, "unsupported", 0)
        if r.get("position"):
            tk = int(r["position"])
            if tk not in self.pos:
                return Result(10013, 0, 0, 0.0, 0.0, "no position", 0)
            price = bid if self.pos[tk]["type"] == POSITION_TYPE_BUY else ask
            self._close(tk, price, t, "[close]", r.get("volume"))
            return Result(TRADE_RETCODE_DONE, tk, self.n, price, float(r.get("volume") or 0), "done", 0)
        buy = r.get("type") == ORDER_TYPE_BUY
        price = ask if buy else bid
        self.n += 1
        tk = self.n
        self.pos[tk] = {"type": POSITION_TYPE_BUY if buy else POSITION_TYPE_SELL, "price": price, "volume": float(r["volume"]),
                        "sl": float(r.get("sl") or 0.0), "tp": float(r.get("tp") or 0.0), "magic": int(r.get("magic") or 0),
                        "comment": str(r.get("comment") or ""), "t": t}
        self.deals.append(_DealT(tk, tk, int(t), int(t * 1000), DEAL_TYPE_BUY if buy else DEAL_TYPE_SELL, DEAL_ENTRY_IN,
                                 int(r.get("magic") or 0), tk, float(r["volume"]), price, 0.0, 0.0, 0.0, 0.0, self.symbol,
                                 str(r.get("comment") or "")))
        self.fills.append((t, "open %s %s %s" % (tk, "BUY" if buy else "SELL", r["volume"]), price, None))
        return Result(TRADE_RETCODE_DONE, tk, tk, price, float(r["volume"]), "done", 0)


class FakeMT5:
    """the module object the bots import as MetaTrader5"""

    def __init__(self, broker):
        self.b = broker
        g = globals()
        for k, v in g.items():
            if k.isupper():
                setattr(self, k, v)
        self._err = (1, "Success")

    # session
    def initialize(self, *a, **k):
        return True

    def shutdown(self):
        return True

    def last_error(self):
        return self._err

    def terminal_info(self):
        return Terminal(True, True, "SIM")

    def account_info(self):
        b = self.b
        fl = round(b.floating(), 2)
        return Account(b.login, b.server, "Exness Technologies Ltd", "USD", 2000, ACCOUNT_MARGIN_MODE_RETAIL_HEDGING,
                       round(b.balance, 2), round(b.balance + fl, 2), fl, 0.0, round(b.balance + fl, 2), True, True, "sim")

    # symbols
    def _sym(self):
        q = self.b.quote() or (0.0, 0.0, 0)
        return Symbol(self.b.symbol, "Bitcoin vs US Dollar", "Crypto\\" + self.b.symbol, 2, 0.01, 1.0, 0.01, 0.01,
                      0.01, 0.01, 200.0, 3, 0, 0, 4, int(round((q[1] - q[0]) * 100)), "USD", True, True, q[0], q[1])

    def symbol_info(self, name):
        return self._sym() if name == self.b.symbol else None

    def symbols_get(self, *a, **k):
        return [self._sym()]

    def symbol_select(self, *a, **k):
        return True

    def symbol_info_tick(self, name):
        if name != self.b.symbol:
            return None
        q = self.b.quote()
        if not q:
            return None
        return Tick(q[2] // 1000, q[0], q[1], 0.0, 0, q[2], 6, 0.0)

    def lot_factor(self):
        return 1.0

    # prices
    def copy_rates_from_pos(self, symbol, tf, start, count):
        return self.b.rates(tf, start, count) if symbol == self.b.symbol else None

    def copy_rates_range(self, symbol, tf, frm, to):
        R = self.b.rates(tf, 0, 10 ** 7)
        if R is None:
            return None
        a, z = int(frm.timestamp()), int(to.timestamp())
        return R[(R["time"] >= a) & (R["time"] <= z)]

    # trading
    def positions_get(self, symbol=None, **k):
        b = self.b
        q = b.quote() or (0.0, 0.0, 0)
        out = []
        for tk, p in sorted(b.pos.items()):
            if symbol and symbol != b.symbol:
                continue
            cur = q[0] if p["type"] == POSITION_TYPE_BUY else q[1]
            out.append(_PosT(tk, int(p["t"]), int(p["t"] * 1000), p["type"], p["magic"], tk, p["volume"], p["price"], p["sl"],
                             p["tp"], cur, 0.0, round(b._profit(p, q[0], q[1]), 2), b.symbol, p["comment"]))
        return tuple(out)

    def order_send(self, request):
        return self.b.send(dict(request))

    def history_deals_get(self, frm, to, **k):
        a = frm.timestamp() if hasattr(frm, "timestamp") else float(frm)
        z = to.timestamp() if hasattr(to, "timestamp") else float(to)
        return tuple(d for d in self.b.deals if a <= d.time <= z)

    def history_orders_get(self, *a, **k):
        return tuple()
