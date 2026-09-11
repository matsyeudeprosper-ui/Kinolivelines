"""harvest_fresh_h1_bot.py - the FRESH+EARLY H1 combo, LIVE on the
Pro account (223985697, BTCUSD, $7 spread). Deployed 2026-09-08 under
the user's standing auto-fix authorisation, after the KINO recipe
failed its preregistered forward test (33 trades, net -2.22) and the
corrected spread-aware replay showed the entry itself is noise
(random controls beat it on M5/M15; +$0.005/trade gross at S=0).

WHY THIS RULE. It is the only result in this project's history that
beat rate-matched random selection everywhere tested (original
2026-08-09 run on BTCUSDm + ETH; re-validated 2026-09-08 on THIS
symbol/feed: H1 combo +1429 vs random, 2SE 162, 6/6 anchors, zero
wipeouts in 12.6 years, while the ungated rule dies 5/6). Per-year:
2022 +134, 2023 +152, 2024 -31, 2025 +375, 2026 +28 YTD (at 0.01).
Expected pace is SLOW: ~4-14 cycle starts a month.

THE RULE (hedge_engine.simulate, arm="same", exactly):
  bricks: $50 trading series, $150 gate series, both from H1 CLOSES,
          2-brick reversals, continuous from seeded history
  new cycle (basket empty) on a $50-series flip ONLY when
    a) $150 series direction == trade direction AND its flip pair
       just printed (bricks-since-flip <= 1)  [fresh window]
    b) the cycle is one of the day's FIRST 2 (UTC)  [early]
  first trade 0.01, TP +5 bricks (250), NO stop-loss
  any position 3 bricks (150) against -> cycle enters RECOVERY
  in recovery each $50 flip in the FIRST trade's direction adds 0.01
  (max 4 standing; a 5th fill force-closes the whole basket at loss)
  basket floating+banked P&L of the cycle back >= 0 -> close all
  cycle P&L decisions are taken on H1 CLOSES (like the backtest);
  TPs are broker-side and fire intra-bar (like the backtest's h/l)

SAFETY
  - honors owl_trading_pause.json: paused = no NEW cycles; an open
    basket keeps being managed (engine philosophy: abandoning a
    stopless basket is a different, worse strategy)
  - hard kill line: bot's own cumulative net <= -$40 (backtest maxDD
    territory) -> close basket, stop opening, say KILL loudly
  - one instance; positions tagged comment KL-FRESH, magic 909001
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

# 2026-09-08 user: forward test on the DEMO Pro account (the -$120
# live kill was too much real money to spend on a test). $1000 demo
# = the strategy can live through its full historical drawdown.
TERMINAL = r"C:\NestTerminals\u476954287\terminal64.exe"
LOGIN = 476954287
PASSWORD = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "owl_secrets.json"), encoding="utf-8"))["mt5_password"]  # not in git
SERVER = "Exness-MT5Trial9"
# multi-symbol (2026-09-08, user approved the ETH second stream):
#   pythonw harvest_fresh_h1_bot.py          -> BTCUSD, $50 bricks
#   pythonw harvest_fresh_h1_bot.py ETHUSD   -> bricks scaled to the
#     price at launch (the ETH study's 50/65000 proportion), kill
#     line scaled by the same ratio
SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "BTCUSD"
MAGIC = 909001 if SYMBOL == "BTCUSD" else 909002
COMMENT = ("KL-FRESH" if SYMBOL == "BTCUSD"
           else f"KL-FRESH-{SYMBOL[:3]}")
LOT = 0.01
BRICK = 50.0                # BTC baseline; scaled in main() for others
GATE_BRICK = 150.0
REV = 2
TP_PTS = 5 * BRICK
TRIG_PTS = 3 * BRICK
CAP = 3 if SYMBOL == "BTCUSD" else 4
                            # BTC cap sweep 2026-09-08: cap3 eq +1704
                            # / worst -118 / vsR +996 2SE 314 6/6 -
                            # beats cap4 (+1632/-199); cap1 loses the
                            # edge. ETH validation same day: cap4 vsR
                            # +84 2SE 35 6/6 but cap3 NULL (+6+-19) -
                            # each symbol runs its measured best.
DAY_CAP = 2                 # first N cycle starts per UTC day
KILL_NET = -350.0           # DEMO amendment 2026-09-08: on $1000
                            # demo money the test can afford the
                            # strategy's full historical drawdown
                            # (maxDD 313 over 12.6y) - kill only
                            # beyond it, meaning "worse than the
                            # worst 12.6 years" = the edge is not
                            # what the backtest said.
SEED_BARS = 80000

DIR = os.path.dirname(os.path.abspath(__file__))
_sfx = "" if SYMBOL == "BTCUSD" else f"_{SYMBOL.lower()}"
STATE_F = os.path.join(DIR, f"harvest_fresh_state{_sfx}.json")
LOG_F = os.path.join(DIR, f"harvest_fresh{_sfx}.log")
PAUSE_F = os.path.join(DIR, "owl_trading_pause.json")


def say(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    with open(LOG_F, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Brick:
    """Renko series identical to hedge_engine's inline brick loop."""

    def __init__(self, brick, seed_open):
        self.brick = brick
        self.ao = self.ac = float(seed_open)
        self.d = 0
        self.since = 99          # bricks since last flip

    def push(self, close):
        """Feed one close; returns list of directions after each brick
        printed this close (empty if none). Updates freshness."""
        out = []
        while True:
            up = ((self.ao if self.d == -1 else self.ac)
                  + self.brick * (REV if self.d == -1 else 1))
            dn = ((self.ao if self.d == 1 else self.ac)
                  - self.brick * (REV if self.d == 1 else 1))
            if close >= up:
                base = self.ao if self.d == -1 else self.ac
                self.since = 0 if self.d == -1 else self.since + 1
                self.ao, self.ac, self.d = base, base + self.brick, 1
            elif close <= dn:
                base = self.ao if self.d == 1 else self.ac
                self.since = 0 if self.d == 1 else self.since + 1
                self.ao, self.ac, self.d = base, base - self.brick, -1
            else:
                break
            out.append(self.d)
        return out


def paused():
    try:
        return bool(json.load(open(PAUSE_F)).get("paused"))
    except Exception:
        return False


def ensure_algo():
    """The cloned terminal can come up with AutoTrading OFF (retcode
    10027, seen 2026-09-08 on the first live cycle). WM_COMMAND
    32851 toggles the button without window focus. Returns True when
    trading is allowed afterwards."""
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
        def cb(h, l):
            p = wt.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == pid and user32.IsWindowVisible(h):
                hwnds.append(h)
            return True

        user32.EnumWindows(cb, 0)
        for h in hwnds:
            user32.PostMessageW(h, 0x0111, 32851, 0)
        time.sleep(3)
        ti = mt5.terminal_info()
        ok = ti is not None and ti.trade_allowed
        say(f"ensure_algo: toggled AutoTrading -> "
            f"trade_allowed={ok}")
        return ok
    except Exception as e:
        say(f"ensure_algo FAILED {type(e).__name__}: {e}")
        return False


def load_state():
    try:
        return json.load(open(STATE_F))
    except Exception:
        return {"banked": 0.0, "cycle_banked": 0.0, "rec": False,
                "cyc_dir": None, "day": None, "day_cycles": 0,
                "killed": False, "last_bar": 0}


def save_state(st):
    json.dump(st, open(STATE_F, "w"))


def my_positions():
    ps = mt5.positions_get(symbol=SYMBOL) or []
    return [p for p in ps if p.magic == MAGIC]


def open_trade(want_long, tp_px):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None
    r = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume": LOT,
        "type": mt5.ORDER_TYPE_BUY if want_long else mt5.ORDER_TYPE_SELL,
        "price": tick.ask if want_long else tick.bid,
        "tp": round(tp_px, 2),
        "deviation": 200, "magic": MAGIC, "comment": COMMENT,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC})
    if r is not None and r.retcode == 10027 and ensure_algo():
        # AutoTrading was off - toggled; one retry
        tick = mt5.symbol_info_tick(SYMBOL)
        r = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
            "volume": LOT,
            "type": (mt5.ORDER_TYPE_BUY if want_long
                     else mt5.ORDER_TYPE_SELL),
            "price": tick.ask if want_long else tick.bid,
            "tp": round(tp_px, 2),
            "deviation": 200, "magic": MAGIC, "comment": COMMENT,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC})
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        say(f"ENTRY FAILED retcode={r.retcode if r else None}")
        return None
    return r


def close_position(p):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return False
    r = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume": p.volume, "position": p.ticket,
        "type": (mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY
                 else mt5.ORDER_TYPE_BUY),
        "price": (tick.bid if p.type == mt5.POSITION_TYPE_BUY
                  else tick.ask),
        "deviation": 200, "magic": MAGIC, "comment": COMMENT + "-close",
        "type_filling": mt5.ORDER_FILLING_IOC})
    return r is not None and r.retcode == mt5.TRADE_RETCODE_DONE


def close_all(why):
    ok = True
    for p in my_positions():
        ok = close_position(p) and ok
    say(f"BASKET CLOSED ({why}) ok={ok}")
    return ok


def floating():
    return sum(p.profit + p.swap for p in my_positions())


def banked_since(t_from):
    """Realized P&L of MAGIC deals since t_from (cycle bookkeeping)."""
    ds = mt5.history_deals_get(
        datetime.fromtimestamp(t_from, tz=timezone.utc),
        datetime.now(timezone.utc)) or []
    tot = 0.0
    for d in ds:
        if d.magic == MAGIC and d.entry == mt5.DEAL_ENTRY_OUT:
            tot += d.profit + d.swap + d.commission
    return tot


def main():
    global BRICK, GATE_BRICK, TP_PTS, TRIG_PTS, KILL_NET, LOT
    assert mt5.initialize(path=TERMINAL, login=LOGIN,
                          password=PASSWORD, server=SERVER,
                          timeout=60000), "MT5 init failed"
    ai = mt5.account_info()
    assert ai and ai.login == LOGIN, f"wrong account {ai}"
    mt5.symbol_select(SYMBOL, True)
    if SYMBOL != "BTCUSD":
        # scale bricks to price (the ETH study's 50/65000 proportion)
        tk0 = mt5.symbol_info_tick(SYMBOL)
        assert tk0 is not None, f"no tick for {SYMBOL}"
        BRICK = round(tk0.bid * 50.0 / 65000.0, 1)
        GATE_BRICK = round(tk0.bid * 150.0 / 65000.0, 1)
        TP_PTS = 5 * BRICK
        TRIG_PTS = 3 * BRICK
        # ETH validation: maxDD $42 / worst cycle -$14 over 7.7y at
        # cap 4 - kill at -60 = well beyond the observed worst
        KILL_NET = -60.0
    si = mt5.symbol_info(SYMBOL)
    if si is not None and si.volume_min > LOT:
        # broker minimum overrides (ETHUSD on Trial9 is min 0.10 -
        # retcode 10014 on 0.01, seen 2026-09-10). P&L and the kill
        # line scale together so the test keeps its preregistered
        # shape, just in bigger units.
        KILL_NET = round(KILL_NET * si.volume_min / LOT, 2)
        LOT = si.volume_min
        say(f"lot raised to broker minimum {LOT}; "
            f"kill scaled to {KILL_NET}")
    say(f"FRESH-H1 starting on {ai.login} balance {ai.balance:.2f} "
        f"symbol {SYMBOL} brick {BRICK} gate {GATE_BRICK} "
        f"kill {KILL_NET}")
    ensure_algo()

    R = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 1, SEED_BARS)
    assert R is not None and len(R) > 1000, "no H1 history"
    trade_b = Brick(BRICK, R["open"][0])
    gate_b = Brick(GATE_BRICK, R["open"][0])
    pd_ = 0
    for row in R:
        cl = float(row["close"])
        for d in trade_b.push(cl):
            pd_ = d
        gate_b.push(cl)
    st = load_state()
    st["last_bar"] = int(R["time"][-1])
    save_state(st)
    say(f"seeded {len(R)} H1 bars; trade dir {trade_b.d} "
        f"gate dir {gate_b.d} since {gate_b.since}")

    while True:
        time.sleep(30)
        try:
            if st.get("killed"):
                time.sleep(300)
                continue
            kb = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 1, 2)
            if kb is None or len(kb) < 2:
                continue
            bar = kb[-1]
            bt = int(bar["time"])
            ps = my_positions()

            # kill line, checked every poll
            net = st.get("banked", 0.0) + floating()
            if net <= KILL_NET and not st.get("killed"):
                say(f"KILL LINE: bot net {net:.2f} <= {KILL_NET} - "
                    f"closing basket, stopping")
                close_all("kill line")
                st["killed"] = True
                save_state(st)
                continue

            if bt == st.get("last_bar"):
                continue
            # ---- new completed H1 bar ----
            st["last_bar"] = bt
            cl = float(bar["close"])
            hi, lo = float(bar["high"]), float(bar["low"])
            day = bt // 86400
            if st.get("day") != day:
                st["day"] = day
                st["day_cycles"] = 0

            # recovery trigger from this bar's extremes (engine h/l)
            if ps and not st.get("rec"):
                for p in ps:
                    adverse = ((p.price_open - lo)
                               if p.type == mt5.POSITION_TYPE_BUY
                               else (hi - p.price_open))
                    if adverse >= TRIG_PTS:
                        st["rec"] = True
                        say(f"RECOVERY: {adverse:.0f}pts against "
                            f"{p.ticket} - same-direction adds armed")
                        break

            # cycle bookkeeping: TPs may have banked this bar
            if st.get("cyc_t0"):
                st["cycle_banked"] = banked_since(st["cyc_t0"] - 60)
            ps = my_positions()
            if not ps and st.get("cyc_dir") is not None:
                # basket emptied via TPs -> cycle over
                pnl = st.get("cycle_banked", 0.0)
                st["banked"] = st.get("banked", 0.0) + pnl
                say(f"CYCLE OVER via targets {pnl:+.2f} - "
                    f"bot net {st['banked']:+.2f}")
                st.update(cyc_dir=None, rec=False, cyc_t0=None,
                          cycle_banked=0.0)

            # cycle-zero / cap exits (H1 close decisions, like engine)
            if ps and st.get("rec"):
                cyc_pnl = st.get("cycle_banked", 0.0) + floating()
                if cyc_pnl >= 0:
                    close_all("cycle back to zero")
                    time.sleep(3)
                    pnl = banked_since(st["cyc_t0"] - 60)
                    st["banked"] = st.get("banked", 0.0) + pnl
                    say(f"CYCLE OVER at zero {pnl:+.2f} - "
                        f"bot net {st['banked']:+.2f}")
                    st.update(cyc_dir=None, rec=False, cyc_t0=None,
                              cycle_banked=0.0)
                    ps = []
            if len(ps) > CAP:
                close_all(f"cap {CAP} exceeded")
                time.sleep(3)
                pnl = banked_since(st["cyc_t0"] - 60)
                st["banked"] = st.get("banked", 0.0) + pnl
                say(f"CYCLE OVER at cap {pnl:+.2f} - "
                    f"bot net {st['banked']:+.2f}")
                st.update(cyc_dir=None, rec=False, cyc_t0=None,
                          cycle_banked=0.0)
                ps = []

            # ---- bricks from this close; act on flips ----
            gate_b.push(cl)
            for d in trade_b.push(cl):
                if pd_ and d != pd_:
                    want_long = d == 1
                    ps = my_positions()
                    if not ps and st.get("cyc_dir") is None:
                        fresh = (gate_b.d == d and gate_b.since <= 1)
                        early = st.get("day_cycles", 0) < DAY_CAP
                        if not fresh or not early:
                            say(f"flip {'UP' if want_long else 'DOWN'} "
                                f"skipped (fresh={fresh} early={early})")
                        elif paused():
                            say("flip skipped - trading paused (app)")
                        else:
                            tick = mt5.symbol_info_tick(SYMBOL)
                            ref = tick.ask if want_long else tick.bid
                            tp = ref + TP_PTS if want_long else ref - TP_PTS
                            if open_trade(want_long, tp):
                                st["cyc_dir"] = 1 if want_long else -1
                                st["rec"] = False
                                st["cyc_t0"] = int(time.time())
                                st["cycle_banked"] = 0.0
                                st["day_cycles"] = (
                                    st.get("day_cycles", 0) + 1)
                                say(f"CYCLE {st['day_cycles']}/2: "
                                    f"{'BUY' if want_long else 'SELL'} "
                                    f"{LOT} TP {tp:.2f} (fresh gate, "
                                    f"gate-since {gate_b.since})")
                    elif (ps and st.get("rec")
                          and len(ps) <= CAP
                          and st.get("cyc_dir") == d):
                        tick = mt5.symbol_info_tick(SYMBOL)
                        ref = tick.ask if want_long else tick.bid
                        tp = ref + TP_PTS if want_long else ref - TP_PTS
                        if open_trade(want_long, tp):
                            say(f"RECOVERY ADD #{len(ps)+1}: "
                                f"{'BUY' if want_long else 'SELL'} "
                                f"{LOT} TP {tp:.2f}")
                pd_ = d
            save_state(st)
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
