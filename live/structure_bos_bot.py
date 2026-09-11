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

AWAKE GATE (user 2026-09-09, measured before deploy): entries only
when at least one trend FLIP happened in the last 2 hours. The
sleepy-market trades were the losers: gated backtest +207 over 69d
vs all-negative random controls (5 seeds), walk-forward winner
picked on days 1-35 scored +116 blind on days 36-69 (scratchpad
bt_chop*.py). Sleeping market = no fishing.
"""
import json
import os
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

# --- variants (2026-09-09): argv[1] picks the account/config.
#     "live" (default) = the FROZEN real config.
#     "sniper"  = demo 476989735: ONLY the 2nd trade of each trend,
#        flat 0.06, no chest features (backtest: 65% wr, +106 at
#        0.02 -> ~+318 at 0.06, maxDD ~78, halves +44/+63).
#     "halfdebt" = demo 476989740: full live config but per-loss
#        debt at 0.5x (backtest +372 vs +335, DD 80, chest richer,
#        3x more adds) - the queued upgrade, auditioning forward.
import sys as _sys
VARIANT = _sys.argv[1] if len(_sys.argv) > 1 else "live"
PASSWORD = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "owl_secrets.json"), encoding="utf-8"))["mt5_password"]  # not in git
SYMBOL = "BTCUSD"
RR = 0.8
BASE_LOT = 0.02
MAX_EXTRA = 3            # bullets that may ride along (0.01 each)
CHEST_CAP = 10.0         # cap sweep 2026-09-09: $10 = sweet spot
KILL_NET = -60.0
MIN_BALANCE = 20.0
SEED_BARS = 3000
S_MIN_DIST = 10.0        # dot inside the spread zone = no trade
AWAKE_WIN = 7200         # awake gate: >=1 flip within this window
DEBT_MODE = "hwm"        # hwm (peak) | half (0.5x per loss)
SNIPER = False           # only the 2nd trade of each trend
ADDS_ON = True
TOUCH_ENTRIES = True     # continuation on level TOUCH (False = candle close)
_SFX = ""
if VARIANT == "sniper":
    TERMINAL = r"C:\NestTerminals\u476989735\terminal64.exe"
    LOGIN = 476989735
    SERVER = "Exness-MT5Trial9"
    MAGIC = 909201
    COMMENT = "KL-SNIPER"
    BASE_LOT = 0.06
    MAX_EXTRA = 0
    ADDS_ON = False
    SNIPER = True
    KILL_NET = -80.0
    _SFX = "_sniper"
elif VARIANT == "halfdebt":
    TERMINAL = r"C:\NestTerminals\u476989740\terminal64.exe"
    LOGIN = 476989740
    SERVER = "Exness-MT5Trial9"
    MAGIC = 909301
    COMMENT = "KL-HALF"
    DEBT_MODE = "half"
    _SFX = "_half"
else:
    TERMINAL = r"C:\NestTerminals\u223995441\terminal64.exe"
    LOGIN = 223995441
    SERVER = "Exness-MT5Real30"
    MAGIC = 909101
    COMMENT = "KL-BOS"
    # user 2026-09-11 after the execution audit (Owl/study/audit):
    # continuation entries go back to the candle CLOSE (no execution
    # bias, +237 on ticks vs +206 touch); the touch rule keeps running
    # as a paper twin in bos_paper_touch.py for a side-by-side record.
    TOUCH_ENTRIES = False

DIR = os.path.dirname(os.path.abspath(__file__))
STATE_F = os.path.join(DIR, f"bos_state{_SFX}.json")
LOG_F = os.path.join(DIR, f"bos_bot{_SFX}.log")
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
        self.quiet = False       # True during the seed replay

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
            if not self.quiet:
                say(f"CHoCH bearish at {self.kept[i][4]:.2f}")
        elif (self.trend == -1 and self.prot_hi is not None
                and c > self.prot_hi[1]):
            self.choch = 1
            self.prot_hi = None
            self.hi_i, self.hi_v = i, h
            if not self.quiet:
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
    seen = st.setdefault("seen_deals", [])
    for d in ds:
        if d.magic != MAGIC or d.entry != mt5.DEAL_ENTRY_OUT:
            continue
        if d.ticket in seen:
            continue          # the query window overlaps on purpose;
        seen.append(d.ticket)  # each deal books exactly once
        del seen[:-200]
        pnl = d.profit + d.swap + d.commission
        lot = float(d.volume)
        st["banked"] = round(st.get("banked", 0.0) + pnl, 2)
        # HIGH-WATER-MARK ledger (user 2026-09-09, measured: same
        # net as the per-loss ledger, maxDD 72 vs 80): the debt IS
        # the drawdown from the equity peak; fighters hunt until
        # the peak is reclaimed. Chest fills from new-high overflow
        # (cap $10) and pays every bullet's losses.
        is_add = d.position_id in (st.get("add_ids") or [])
        if pnl < 0:
            if is_add:
                st["chest"] = round(max(0.0, st["chest"] + pnl), 2)
            elif lot > BASE_LOT + 0.001:
                extra_sh = pnl * (1.0 - BASE_LOT / lot)
                st["chest"] = round(max(0.0,
                                        st["chest"] + extra_sh), 2)
        if DEBT_MODE == "half":
            # per-loss debt at 0.5x; wins pay it, overflow -> chest
            if pnl < 0:
                st["debt"] = round(st["debt"] + 0.5 * (-pnl), 2)
            elif pnl > 0:
                pay = min(st["debt"], pnl)
                st["debt"] = round(st["debt"] - pay, 2)
                st["chest"] = round(min(CHEST_CAP,
                                        st["chest"] + pnl - pay), 2)
        else:
            pk = st.get("peak", 0.0)
            if st["banked"] > pk:
                st["chest"] = round(min(CHEST_CAP,
                                        st["chest"]
                                        + st["banked"] - pk), 2)
                st["peak"] = st["banked"]
            st["debt"] = round(max(0.0, st.get("peak", 0.0)
                                   - st["banked"]), 2)
        if not is_add:
            st["trades"] = st.get("trades", 0) + 1
        tag = "ADD" if is_add else ("WIN" if pnl > 0 else
                                    "LOSS" if pnl < 0 else "FLAT")
        say(f"{tag} {pnl:+.2f} (lot {lot:.2f}): debt "
            f"${st['debt']:.2f} (peak {st.get('peak', 0.0):+.2f}), "
            f"chest ${st['chest']:.2f} - bot net "
            f"{st['banked']:+.2f} ({st.get('trades', 0)} trades)")


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
    eng.quiet = True
    flips = []               # epoch times of trend flips (awake gate)
    R = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1,
                                SEED_BARS)
    assert R is not None and len(R) > 100, "no history"
    for r in R:
        _pt = eng.trend
        eng.step(int(r["time"]), float(r["open"]), float(r["high"]),
                 float(r["low"]), float(r["close"]))
        if eng.trend != _pt and eng.trend != 0 and _pt != 0:
            flips.append(int(r["time"]))
    flips = flips[-20:]
    eng.quiet = False
    st = load_state()
    st["last_bar"] = int(R["time"][-1])
    save_state(st)
    say(f"seeded {len(R)} bars: trend {eng.trend} "
        f"choch {eng.choch} kept {len(eng.kept)}")

    def enter(d, slp, kind):
        """Shared entry executor (close-BOS, flip-BOS and touch)."""
        if my_positions():
            return False
        if paused():
            return False
        ai2 = mt5.account_info()
        if ai2 is None or ai2.balance < MIN_BALANCE:
            return False
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return False
        e_ref = tick.ask if d == 1 else tick.bid
        dist = abs(e_ref - slp)
        if dist <= S_MIN_DIST:
            say(f"{kind} skipped: dot {dist:.0f}pts inside the "
                f"spread zone")
            return False
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
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
               "volume": lot,
               "type": (mt5.ORDER_TYPE_BUY if d == 1
                        else mt5.ORDER_TYPE_SELL),
               "price": e_ref, "sl": round(slp, 2),
               "tp": round(tp, 2), "deviation": 200,
               "magic": MAGIC, "comment": COMMENT,
               "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": mt5.ORDER_FILLING_IOC}
        r = mt5.order_send(req)
        if r is not None and r.retcode == 10027 and ensure_algo():
            r = mt5.order_send(req)
        if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
            say(f"ENTRY FAILED retcode={r.retcode if r else None}")
            return False
        say(f"{kind} ENTRY: {'BUY' if d == 1 else 'SELL'} {lot} @ "
            f"~{e_ref:.2f} SL {slp:.2f} TP {tp:.2f} "
            f"(risk ${dist * lot:.2f}, "
            f"trend {'up' if d == 1 else 'down'})")
        # arm the 50%-pullback add (user 2026-09-09, measured:
        # +343/+422 vs +263 without; chest-funded bullets only)
        if ADDS_ON:
            st["add"] = {"d": d,
                         "lvl": round(e_ref - d * 0.5 * dist, 2),
                         "sl": round(slp, 2), "tp": round(tp, 2),
                         "risk001": round(0.5 * dist * 0.01, 2),
                         "done": False}
        save_state(st)
        return True
    last_book = time.time() - 60
    warned_funds = 0.0
    last_house = 0.0

    while True:
        # user 2026-09-08: act ON the candle close - wake right
        # after each broker minute boundary (max ~0.2s + processing
        # lag), light 1s ticks in between
        _to_min = 60.0 - (time.time() % 60.0) + 0.2
        time.sleep(min(_to_min, 1.0))
        try:
            if st.get("killed"):
                time.sleep(300)
                continue
            if time.time() - last_house >= 10.0:
                last_house = time.time()
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
            # 50%-PULLBACK ADD on the open trade (chest bullets)
            _ad = st.get("add")
            if _ad and not _ad.get("done") and my_positions():
                tk3 = mt5.symbol_info_tick(SYMBOL)
                if tk3 is not None:
                    _hit = (tk3.bid <= _ad["lvl"] if _ad["d"] == 1
                            else tk3.bid >= _ad["lvl"])
                    if _hit:
                        _ad["done"] = True
                        _n = min(2, int(st["chest"]
                                        // max(_ad["risk001"], 0.01)))
                        if _n > 0:
                            _al = round(_n * 0.01, 2)
                            _r3 = mt5.order_send({
                                "action": mt5.TRADE_ACTION_DEAL,
                                "symbol": SYMBOL, "volume": _al,
                                "type": (mt5.ORDER_TYPE_BUY
                                         if _ad["d"] == 1
                                         else mt5.ORDER_TYPE_SELL),
                                "price": (tk3.ask if _ad["d"] == 1
                                          else tk3.bid),
                                "sl": _ad["sl"], "tp": _ad["tp"],
                                "deviation": 200, "magic": MAGIC,
                                "comment": COMMENT + "-ADD",
                                "type_time": mt5.ORDER_TIME_GTC,
                                "type_filling":
                                    mt5.ORDER_FILLING_IOC})
                            if (_r3 is not None and _r3.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                st.setdefault("add_ids", [])\
                                    .append(_r3.order)
                                del st["add_ids"][:-40]
                                say(f"PULLBACK ADD: {_al} bullet"
                                    f"{'s' if _n > 1 else ''} at "
                                    f"50% ({_ad['lvl']:.2f}), same "
                                    f"SL/TP - chest covers "
                                    f"${_n * _ad['risk001']:.2f}")
                            else:
                                say(f"ADD FAILED retcode="
                                    f"{_r3.retcode if _r3 else None}")
                        save_state(st)
            if st.get("add") and not my_positions():
                st["add"] = None
                save_state(st)
            # TOUCH continuation (user 2026-09-09, measured first:
            # +263/DD67 vs +207/DD85 close-only; flips keep the
            # close rule). Checked every ~1s wake on live ticks.
            if (TOUCH_ENTRIES and not my_positions()
                    and any(f > time.time() - AWAKE_WIN
                            for f in flips)):
                tk2 = mt5.symbol_info_tick(SYMBOL)
                if tk2 is not None:
                    if (eng.trend == 1 and eng.hi_v is not None
                            and tk2.bid > eng.hi_v
                            and st.get("used_hi") != eng.hi_v):
                        span = eng.kept[eng.hi_i + 1:]
                        if span and any(x[5] == -1 for x in span):
                            m = min(span, key=lambda x: x[3])
                            st["used_hi"] = eng.hi_v
                            st["ord"] = st.get("ord", 0) + 1
                            save_state(st)
                            if not SNIPER or st["ord"] == 2:
                                enter(1, m[3], "TOUCH")
                    elif (eng.trend == -1 and eng.lo_v is not None
                            and tk2.bid < eng.lo_v
                            and st.get("used_lo") != eng.lo_v):
                        span = eng.kept[eng.lo_i + 1:]
                        if span and any(x[5] == 1 for x in span):
                            m = max(span, key=lambda x: x[2])
                            st["used_lo"] = eng.lo_v
                            st["ord"] = st.get("ord", 0) + 1
                            save_state(st)
                            if not SNIPER or st["ord"] == 2:
                                enter(-1, m[2], "TOUCH")
            kb = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1,
                                         1, 2)
            if kb is None or len(kb) < 2:
                continue
            bar = kb[-1]
            bt = int(bar["time"])
            if bt == st.get("last_bar"):
                continue
            st["last_bar"] = bt
            _pt = eng.trend
            _hv, _lv = eng.hi_v, eng.lo_v
            sig = eng.step(bt, float(bar["open"]),
                           float(bar["high"]), float(bar["low"]),
                           float(bar["close"]))
            if eng.trend != _pt and eng.trend != 0 and _pt != 0:
                flips.append(bt)
                del flips[:-20]
                say(f"FLIP: trend now "
                    f"{'up' if eng.trend == 1 else 'down'}")
            awake = any(f > bt - AWAKE_WIN for f in flips)
            try:
                # live bullet price estimate: distance to the
                # trend's protected dot = the likely next stop
                _c = float(bar["close"])
                _pd = (eng.prot_lo if eng.trend == 1
                       else eng.prot_hi if eng.trend == -1 else None)
                _blt = (round(max(0.5, min(3.0,
                        abs(_c - _pd[1]) * 0.01)), 2)
                        if _pd else 3.0)
                json.dump({"awake": awake, "trend": eng.trend,
                           "choch": eng.choch,
                           "flips_2h": sum(1 for f in flips
                                           if f > bt - AWAKE_WIN),
                           "bullet": _blt,
                           "updated": int(time.time())},
                          open(os.path.join(
                              DIR, "bos_weather.json"), "w"))
            except Exception:
                pass
            save_state(st)
            if sig is None:
                continue
            if not awake:
                say("BOS signal skipped - market asleep (no flip "
                    "in 2h)")
                continue
            d, slp = sig
            flip = eng.trend != _pt
            if flip:
                st["ord"] = 1
                save_state(st)
                if SNIPER:
                    continue      # sniper skips the flip trade
            else:
                # touch owns continuations; close-entry only as the
                # fallback when the level was never touched (gap,
                # downtime)
                lvl = _hv if d == 1 else _lv
                if (d == 1 and st.get("used_hi") == lvl) or \
                        (d == -1 and st.get("used_lo") == lvl):
                    continue
                st["ord"] = st.get("ord", 0) + 1
                save_state(st)
                if SNIPER and st["ord"] != 2:
                    continue
            enter(d, slp, "FLIP-BOS" if flip else "BOS")
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
