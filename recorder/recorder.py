"""KinoliveLines recorder - read-only continuous capture of BTCUSDm.

Fills the blind spot between conversations. Runs detached, appends to daily
CSVs, and never sends an order (it only ever calls copy_* / *_get).

Writes to  C:\\Projects\\KinoliveLines\\recorder\\data\\
  ticks_<SYMBOL>_<YYYYMMDD>.csv    every tick, no sampling
  bars_<SYMBOL>_M1.csv             every closed M1 bar
  fills_<SYMBOL>.csv               every deal on the account
  status.json                      heartbeat, so staleness is detectable
"""
import MetaTrader5 as mt5
import os, json, time, csv
from datetime import datetime, timedelta

SYMBOL   = "BTCUSDm"
DATA     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
POLL_SEC = 5
os.makedirs(DATA, exist_ok=True)

def p(name): return os.path.join(DATA, name)

def append_rows(path, header, rows):
    if not rows:
        return
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerows(rows)

# Pin the terminal AND the account. With more than one MT5 running, a bare
# mt5.initialize() attaches to whichever instance it feels like - on
# 2026-07-30 it silently returned a different account (134499778, $42.70)
# while the trade being looked for sat on 436771046. Recording the wrong
# account is worse than recording nothing, so refuse to run if the login
# does not match.
TERMINAL_PATH  = r"C:\Program Files\MetaTrader 5\terminal64.exe"
EXPECTED_LOGIN = 436771046

def connect():
    """Reconnect loop - the terminal can be closed and reopened under us."""
    while True:
        if mt5.initialize(path=TERMINAL_PATH):
            acc = mt5.account_info()
            if acc and acc.login == EXPECTED_LOGIN:
                mt5.symbol_select(SYMBOL, True)
                return
            with open(p("recorder_errors.log"), "a", encoding="utf-8") as f:
                f.write(f"{datetime.utcnow().isoformat()}  wrong account "
                        f"{acc.login if acc else None}, want {EXPECTED_LOGIN} - waiting\n")
            mt5.shutdown()
        time.sleep(15)

connect()

state_path = p("state.json")
state = {"last_tick_msc": 0, "last_bar": 0, "last_deal_scan": 0}
if os.path.exists(state_path):
    try:
        state.update(json.load(open(state_path)))
    except Exception:
        pass

# Cold start: begin from now rather than back-filling days of ticks.
if state["last_tick_msc"] == 0:
    t = mt5.symbol_info_tick(SYMBOL)
    state["last_tick_msc"] = (t.time_msc - 60_000) if t else int(time.time() * 1000)

BAR_HDR  = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
TICK_HDR = ["time_msc", "time", "bid", "ask", "last", "volume", "flags"]
# NB: a TradeDeal carries no sl/tp - those belong to the order that produced
# it, not to the fill. Record what a deal actually has.
FILL_HDR = ["time", "deal", "order", "position", "symbol", "type", "entry",
            "volume", "price", "profit", "commission", "fee", "swap", "magic", "comment"]

DEAL_T  = {0: "BUY", 1: "SELL", 2: "BALANCE", 3: "CREDIT"}
ENTRY_T = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}

seen_deals = set()
fills_path = p(f"fills_{SYMBOL}.csv")
if os.path.exists(fills_path):
    try:
        with open(fills_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                seen_deals.add(int(row["deal"]))
    except Exception:
        pass

while True:
    try:
        if not mt5.terminal_info():
            mt5.shutdown()
            connect()

        # ---------- ticks ----------
        ticks = mt5.copy_ticks_from(
            SYMBOL, datetime.fromtimestamp(state["last_tick_msc"] / 1000.0),
            100000, mt5.COPY_TICKS_ALL)
        if ticks is not None and len(ticks):
            rows, newest = [], state["last_tick_msc"]
            for t in ticks:
                if t["time_msc"] <= state["last_tick_msc"]:
                    continue
                rows.append([t["time_msc"], t["time"], t["bid"], t["ask"],
                             t["last"], t["volume"], t["flags"]])
                newest = max(newest, int(t["time_msc"]))
            if rows:
                day = datetime.utcfromtimestamp(rows[-1][1]).strftime("%Y%m%d")
                append_rows(p(f"ticks_{SYMBOL}_{day}.csv"), TICK_HDR, rows)
                state["last_tick_msc"] = newest

        # ---------- closed M1 bars ----------
        bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 300)
        if bars is not None and len(bars):
            rows = [[b["time"], b["open"], b["high"], b["low"], b["close"],
                     b["tick_volume"], b["spread"], b["real_volume"]]
                    for b in bars if b["time"] > state["last_bar"]]
            if rows:
                append_rows(p(f"bars_{SYMBOL}_M1.csv"), BAR_HDR, rows)
                state["last_bar"] = int(rows[-1][0])

        # ---------- fills ----------
        now = int(time.time())
        if now - state["last_deal_scan"] > 30:
            state["last_deal_scan"] = now
            deals = mt5.history_deals_get(datetime.now() - timedelta(days=3),
                                          datetime.now() + timedelta(hours=6))
            rows = []
            for d in (deals or []):
                if d.ticket in seen_deals or d.symbol != SYMBOL:
                    continue
                seen_deals.add(d.ticket)
                rows.append([datetime.utcfromtimestamp(d.time).isoformat(), d.ticket,
                             d.order, d.position_id, d.symbol,
                             DEAL_T.get(d.type, d.type), ENTRY_T.get(d.entry, d.entry),
                             d.volume, d.price, d.profit,
                             d.commission, getattr(d, "fee", 0.0), d.swap,
                             d.magic, d.comment])
            append_rows(fills_path, FILL_HDR, rows)

        # ---------- heartbeat ----------
        tk = mt5.symbol_info_tick(SYMBOL)
        acc = mt5.account_info()
        pos = mt5.positions_get(symbol=SYMBOL) or []
        json.dump({
            "updated_utc": datetime.utcnow().isoformat(),
            "symbol": SYMBOL,
            "bid": tk.bid if tk else None,
            "ask": tk.ask if tk else None,
            "spread": round(tk.ask - tk.bid, 2) if tk else None,
            "server_time": datetime.utcfromtimestamp(tk.time).isoformat() if tk else None,
            "equity": acc.equity if acc else None,
            "balance": acc.balance if acc else None,
            "open_positions": [
                {"ticket": x.ticket, "type": "BUY" if x.type == 0 else "SELL",
                 "volume": x.volume, "open": x.price_open, "sl": x.sl, "tp": x.tp,
                 "profit": x.profit} for x in pos],
            "last_bar_utc": datetime.utcfromtimestamp(state["last_bar"]).isoformat() if state["last_bar"] else None,
        }, open(p("status.json"), "w"), indent=2)

        json.dump(state, open(state_path, "w"))

    except Exception as e:
        try:
            with open(p("recorder_errors.log"), "a", encoding="utf-8") as f:
                f.write(f"{datetime.utcnow().isoformat()}  {type(e).__name__}: {e}\n")
        except Exception:
            pass
        try:
            mt5.shutdown()
        except Exception:
            pass
        time.sleep(10)
        connect()

    time.sleep(POLL_SEC)
