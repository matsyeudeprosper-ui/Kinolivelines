"""structure_bos_bot.py - the user's STRUCTURE rules, LIVE on real
account 223995441 (Exness-MT5Real30, BTCUSD, $7 spread).

DEPLOYED 2026-09-08 ON THE USER'S EXPLICIT DECISION with the
backtest evidence stated and accepted beforehand: over 69 days at
$7 spread the exact rule scored +$56 at 0.02 lots, INSIDE the
random-entry control band (-92..+113); the RR probe grid was
sign-unstable and its best cell collapsed in walk-forward (+176
first half -> +11 blind half). The user chose to forward-run their
exact rules anyway. Guard rails below keep the experiment cheap.

THE RULES (user 2026-09-08, verbatim intent):
  - the chart's structure engine IS the brain (silence filter:
    close beyond last shown high/low; swing dots confirmed only by
    full closes; 2-dot bootstrap; CHoCH then first fresh BOS flips
    the trend)
  - enter EVERY BOS of a confirmed trend, in the trend's direction
  - SL at the glowing dot; TP at 0.8 x risk
  - ONE trade at a time; base lot 0.02
  - fighters use available bullets: while there is a debt book,
    extra 0.01 lots ride along ONLY if the chest can pre-pay their
    full risk at this trade's stop distance (max +0.03). A losing
    fighter's extra share is paid by the chest; the base share goes
    to the debt. Wins pay the debt first, overflow fills the chest
    (cap $5).

GUARD RAILS
  - hard kill: bot net (banked+floating, own magic) <= -$60 ->
    close, stop, say KILL. Preregistered review at 100 trades.
  - honors owl_trading_pause.json for new entries
  - waits quietly while balance < $20 (account starts unfunded)
"""
import json
import os
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

TERMINAL = r"C:\NestTerminals\u223995441\terminal64.exe"
LOGIN = 223995441
PASSWORD = "M@tsy1983"
SERVER = "Exness-MT5Real30"
SYMBOL = "BTCUSD"
MAGIC = 909101
COMMENT = "KL-BOS"
BASE_LOT = 0.02
RR = 0.8
MAX_EXTRA = 3            # bullets that may ride along (0.01 each)
CHEST_CAP = 5.0
KILL_NET = -60.0
MIN_BALANCE = 20.0
SEED_BARS = 3000
S_MIN_DIST = 10.0        # dot inside the spread zone = no trade

DIR = os.path.dirname(os.path.abspath(__file__))
STATE_F = os.path.join(DIR, "bos_state.json")
LOG_F = os.path.join(DIR, "bos_bot.log")
PAUSE_F = os.path.join(DIR, "owl_trading_pause.json")


def say(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    with open(LOG_F, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Struct:
    """The chart's structure engine, incremental (same code that ran
    the backtests in scratchpad bt_bos*)."""

    def __init__(self):
        self.kept = []
        self.ref_h = self.ref_l = None
        self.hi_i = self.lo_i = 0
        self.hi_v = self.lo_v = None
        self.trend = 0
        self.choch = 0
        self.last_lo = self.last_hi = None
        self.up_st = self.dn_st = 0
        self.prot_lo = self.prot_hi = None

    def step(self, t, o, h, l, c):
        if self.ref_h is not None and not (c > self.ref_h
                                           or c < self.ref_l):
            return None
        k = self.kept
        k.append([t, o, h, l, c, 1 if c >= o else -1])
        self.ref_h, self.ref_l = h, l
        i = len(k) - 1
        if i == 0:
            self.hi_v, self.lo_v = h, l
            return None
        sig = None
        if (self.trend == 1 and self.prot_lo is not None
                and c < self.prot_lo[1]):
            self.choch = -1
            self.prot_lo = None
            self.lo_i, self.lo_v = i, l
            say(f"CHoCH bearish at {self.kept[i][4]:.2f}")
        elif (self.trend == -1 and self.prot_hi is not None
                and c > self.prot_hi[1]):
            self.choch = 1
            self.prot_hi = None
            self.hi_i, self.hi_v = i, h
            say(f"CHoCH bullish at {self.kept[i][4]:.2f}")
        if c > self.hi_v:
            span = k[self.hi_i + 1:i]
            if span and any(x[5] == -1 for x in span):
                m = min(span, key=lambda x: x[3])
                nd = [m[0], m[3], 1]
                if self.choch == 1 and self.trend != 1:
                    self.trend = 1
                    self.choch = 0
                    self.prot_lo = nd
                    self.up_st = self.dn_st = 0
                    sig = (1, m[3])
                elif self.trend == 1:
                    self.prot_lo = nd
                    self.choch = 0
                    sig = (1, m[3])
                elif self.trend == 0:
                    if (self.last_lo is not None
                            and m[3] > self.last_lo):
                        self.up_st += 1
                        if self.up_st >= 2:
                            self.trend = 1
                            self.prot_lo = nd
                            self.dn_st = 0
                            sig = (1, m[3])
                    else:
                        self.up_st = 0
                self.last_lo = m[3]
                self.lo_i = k.index(m)
                self.lo_v = m[3]
            self.hi_i, self.hi_v = i, h
        elif c < self.lo_v:
            span = k[self.lo_i + 1:i]
            if span and any(x[5] == 1 for x in span):
                m = max(span, key=lambda x: x[2])
                nd = [m[0], m[2], -1]
                if self.choch == -1 and self.trend != -1:
                    self.trend = -1
                    self.choch = 0
                    self.prot_hi = nd
                    self.up_st = self.dn_st = 0
                    sig = (-1, m[2])
                elif self.trend == -1:
                    self.prot_hi = nd
                    self.choch = 0
                    sig = (-1, m[2])
                elif self.trend == 0:
                    if (self.last_hi is not None
                            and m[2] < self.last_hi):
                        self.dn_st += 1
                        if self.dn_st >= 2:
                            self.trend = -1
                            self.prot_hi = nd
                            self.up_st = 0
                            sig = (-1, m[2])
                    else:
                        self.dn_st = 0
                self.last_hi = m[2]
                self.hi_i = k.index(m)
                self.hi_v = m[2]
            self.lo_i, self.lo_v = i, l
        return sig


def paused():
    try:
        return bool(json.load(open(PAUSE_F)).get("paused"))
    except Exception:
        return False


def load_state():
    try:
        return json.load(open(STATE_F))
    except Exception:
        return {"debt": 0.0, "chest": 0.0, "banked": 0.0,
                "trades": 0, "killed": False, "last_bar": 0,
                "open_lot": 0.0}


def save_state(st):
    json.dump(st, open(STATE_F, "w"))


def ensure_algo():
    ti = mt5.terminal_info()
    if ti is not None and ti.trade_allowed:
        return True
    try:
        import ctypes
        import ctypes.wintypes as wt
        import subprocess
        tok = os.path.basename(os.path.dirname(TERMINAL))
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter "
             "\"Name='terminal64.exe'\" | Where-Object "
             "{ $_.CommandLine -match '" + tok + "' } | "
             "Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=30)
        pid = int(out.stdout.strip().splitlines()[0])
        user32 = ctypes.windll.user32
        hwnds = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def cb(hh, ll):
            p = wt.DWORD()
            user32.GetWindowThreadProcessId(hh, ctypes.byref(p))
            if p.value == pid and user32.IsWindowVisible(hh):
                hwnds.append(hh)
            return True

        user32.EnumWindows(cb, 0)
        for hh in hwnds:
            user32.PostMessageW(hh, 0x0111, 32851, 0)
        time.sleep(3)
        ti = mt5.terminal_info()
        ok = ti is not None and ti.trade_allowed
        say(f"ensure_algo -> trade_allowed={ok}")
        return ok
    except Exception as e:
        say(f"ensure_algo FAILED {type(e).__name__}: {e}")
        return False


def my_positions():
    return [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
            if p.magic == MAGIC]


def floating():
    return sum(p.profit + p.swap for p in my_positions())


def book_closes(st, t_from):
    """Ledger bookkeeping for deals closed since t_from."""
    ds = mt5.history_deals_get(
        datetime.fromtimestamp(t_from, tz=timezone.utc),
        datetime.now(timezone.utc)) or []
    for d in ds:
        if d.magic != MAGIC or d.entry != mt5.DEAL_ENTRY_OUT:
            continue
        pnl = d.profit + d.swap + d.commission
        lot = float(d.volume)
        st["banked"] = round(st.get("banked", 0.0) + pnl, 2)
        st["trades"] = st.get("trades", 0) + 1
        if pnl < 0:
            base_sh = pnl * min(1.0, BASE_LOT / max(lot, 0.01))
            extra_sh = pnl - base_sh
            st["debt"] = round(st["debt"] - base_sh, 2)
            st["chest"] = round(max(0.0, st["chest"] + extra_sh), 2)
            say(f"LOSS {pnl:+.2f} (lot {lot:.2f}): debt "
                f"${st['debt']:.2f}, chest ${st['chest']:.2f}")
        elif pnl > 0:
            if st["debt"] > 0:
                pay = min(st["debt"], pnl)
                st["debt"] = round(st["debt"] - pay, 2)
                left = pnl - pay
            else:
                left = pnl
            if left > 0:
                st["chest"] = round(min(CHEST_CAP,
                                        st["chest"] + left), 2)
            say(f"WIN {pnl:+.2f} (lot {lot:.2f}): debt "
                f"${st['debt']:.2f}, chest ${st['chest']:.2f} "
                f"- bot net {st['banked']:+.2f} "
                f"({st['trades']} trades)")


def main():
    assert mt5.initialize(path=TERMINAL, login=LOGIN,
                          password=PASSWORD, server=SERVER,
                          timeout=60000), "MT5 init failed"
    ai = mt5.account_info()
    assert ai and ai.login == LOGIN, f"wrong account {ai}"
    mt5.symbol_select(SYMBOL, True)
    say(f"BOS-BOT starting on {ai.login} balance {ai.balance:.2f} "
        f"base {BASE_LOT} RR {RR} kill {KILL_NET}")
    ensure_algo()

    eng = Struct()
    R = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1,
                                SEED_BARS)
    assert R is not None and len(R) > 100, "no history"
    for r in R:
        eng.step(int(r["time"]), float(r["open"]), float(r["high"]),
                 float(r["low"]), float(r["close"]))
    st = load_state()
    st["last_bar"] = int(R["time"][-1])
    save_state(st)
    say(f"seeded {len(R)} bars: trend {eng.trend} "
        f"choch {eng.choch} kept {len(eng.kept)}")
    last_book = time.time() - 60
    warned_funds = 0.0

    while True:
        time.sleep(10)
        try:
            if st.get("killed"):
                time.sleep(300)
                continue
            book_closes(st, last_book - 30)
            last_book = time.time()
            save_state(st)
            net = st.get("banked", 0.0) + floating()
            if net <= KILL_NET:
                say(f"KILL LINE: net {net:.2f} <= {KILL_NET} - "
                    f"closing and stopping")
                for p in my_positions():
                    tick = mt5.symbol_info_tick(SYMBOL)
                    mt5.order_send({
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": SYMBOL, "volume": p.volume,
                        "position": p.ticket,
                        "type": (mt5.ORDER_TYPE_SELL
                                 if p.type == mt5.POSITION_TYPE_BUY
                                 else mt5.ORDER_TYPE_BUY),
                        "price": (tick.bid
                                  if p.type == mt5.POSITION_TYPE_BUY
                                  else tick.ask),
                        "deviation": 200, "magic": MAGIC,
                        "comment": COMMENT + "-kill",
                        "type_filling": mt5.ORDER_FILLING_IOC})
                st["killed"] = True
                save_state(st)
                continue
            kb = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1,
                                         1, 2)
            if kb is None or len(kb) < 2:
                continue
            bar = kb[-1]
            bt = int(bar["time"])
            if bt == st.get("last_bar"):
                continue
            st["last_bar"] = bt
            sig = eng.step(bt, float(bar["open"]),
                           float(bar["high"]), float(bar["low"]),
                           float(bar["close"]))
            save_state(st)
            if sig is None:
                continue
            d, slp = sig
            if my_positions():
                continue                     # one trade at a time
            if paused():
                say("BOS signal skipped - trading paused (app)")
                continue
            ai = mt5.account_info()
            if ai is None or ai.balance < MIN_BALANCE:
                if time.time() - warned_funds > 3600:
                    warned_funds = time.time()
                    say(f"BOS signal but balance "
                        f"{ai.balance if ai else 0:.2f} < "
                        f"{MIN_BALANCE} - waiting for funds")
                continue
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                continue
            e_ref = tick.ask if d == 1 else tick.bid
            dist = abs(e_ref - slp)
            if dist <= S_MIN_DIST:
                say(f"signal skipped: dot {dist:.0f}pts inside "
                    f"the spread zone")
                continue
            lot = BASE_LOT
            if st["debt"] > 0.5:
                risk001 = dist * 0.01
                extra = min(MAX_EXTRA,
                            int(st["chest"] // max(risk001, 0.01)))
                lot = round(BASE_LOT + extra * 0.01, 2)
                if extra > 0:
                    say(f"FIGHTER: {extra} bullet(s) ride along -> "
                        f"lot {lot:.2f} (chest ${st['chest']:.2f} "
                        f"covers {extra} x ${risk001:.2f})")
            tp = e_ref + d * RR * dist
            r = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
                "volume": lot,
                "type": (mt5.ORDER_TYPE_BUY if d == 1
                         else mt5.ORDER_TYPE_SELL),
                "price": e_ref, "sl": round(slp, 2),
                "tp": round(tp, 2),
                "deviation": 200, "magic": MAGIC,
                "comment": COMMENT,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC})
            if r is not None and r.retcode == 10027 and ensure_algo():
                r = mt5.order_send({
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": SYMBOL, "volume": lot,
                    "type": (mt5.ORDER_TYPE_BUY if d == 1
                             else mt5.ORDER_TYPE_SELL),
                    "price": e_ref, "sl": round(slp, 2),
                    "tp": round(tp, 2),
                    "deviation": 200, "magic": MAGIC,
                    "comment": COMMENT,
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC})
            if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
                say(f"ENTRY FAILED retcode="
                    f"{r.retcode if r else None}")
            else:
                say(f"BOS ENTRY: {'BUY' if d == 1 else 'SELL'} "
                    f"{lot} @ ~{e_ref:.2f} SL {slp:.2f} "
                    f"TP {tp:.2f} (risk ${dist * lot:.2f}, "
                    f"trend {'up' if d == 1 else 'down'})")
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
