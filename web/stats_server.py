"""stats_server.py - public read-only dashboard for the harvest bots.

One process, two jobs:
  - a collector thread rebuilds web/stats.json every REFRESH seconds from the
    broker (both terminals), the journals and the heartbeat files
  - a ThreadingHTTPServer serves this folder (index.html + stats.json)

READ ONLY against MT5 - no order_send anywhere. Serves only this folder, GET
only. The page shows account numbers the owner chose to publish; it contains
no credentials, no tickets to act on, and nothing that can place a trade.
"""
import csv
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import MetaTrader5 as mt5

HERE = os.path.dirname(os.path.abspath(__file__))
LIVEDIR = r"C:\Projects\KinoliveLines\live"
STUDYDIR = r"C:\Projects\KinoliveLines\study"
PORT = 8899
REFRESH = 60
LIVE_TERMINAL = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
DEMO_TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LIVE_LOGIN, DEMO_LOGIN = 134499778, 436771046
MAGIC_LIVE, MAGIC_CTRL, MAGIC_TRAIL, MAGIC_PLAIN = 770407, 770405, 770408, 770404
EPOCH = datetime(2026, 8, 1)

# Backtest expectations, M1, 0.01 lots - static by design: these are the
# preregistered reference numbers, not live data, and must not drift with it.
EXPECT = dict(
    daily=dict(mean=0.53, median=2.89, green=60, best=38.96, worst=-53.25),
    daily_dd=dict(typical=15.42, p90=41.46, worst=96.46),
    monthly=dict(note="one whole month (July) x 6 anchors",
                 mean=-12.11, lo=-61.87, hi=46.88),
    verdict="Backtest says the rule LOSES long-term. Live deployment was an "
            "informed decision; every brake tested (trails, spacing) only "
            "moves losses between regimes.")


def say(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def jread(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_account(terminal, login, magics):
    """Balance/equity/positions + per-magic realised P&L for today / yesterday /
    7 days / since EPOCH, all in UTC day buckets."""
    if not mt5.initialize(path=terminal):
        return None
    try:
        a = mt5.account_info()
        if a is None or a.login != login:
            return None
        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(EPOCH, datetime.now() + timedelta(days=1)) or []
        out = dict(balance=round(a.balance, 2), equity=round(a.equity, 2),
                   margin_free=round(a.margin_free, 2), magics={})
        for mg in magics:
            rows = [d for d in deals if d.magic == mg]
            def s(pred):
                return round(sum(d.profit + d.swap + d.commission +
                                 getattr(d, "fee", 0.0)
                                 for d in rows if pred(d)), 2)
            today = now.strftime("%Y-%m-%d")
            yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            def day_of(d):
                return datetime.fromtimestamp(d.time, tz=timezone.utc).strftime("%Y-%m-%d")
            wins = [d for d in rows if d.entry == mt5.DEAL_ENTRY_OUT and d.profit > 0]
            outs = [d for d in rows if d.entry == mt5.DEAL_ENTRY_OUT]
            out["magics"][str(mg)] = dict(
                today=s(lambda d: day_of(d) == today),
                yesterday=s(lambda d: day_of(d) == yday),
                week=s(lambda d: (now - datetime.fromtimestamp(d.time, tz=timezone.utc)).days < 7),
                total=s(lambda d: True),
                closed=len(outs), wins=len(wins))
        ps = mt5.positions_get(symbol="BTCUSDm") or []
        out["positions"] = [dict(magic=p.magic,
                                 side="BUY" if p.type == 0 else "SELL",
                                 entry=round(p.price_open, 2),
                                 pnl=round(p.profit, 2),
                                 age_h=round((datetime.now() -
                                              datetime.fromtimestamp(p.time)).total_seconds() / 3600, 1))
                           for p in ps]
        t = mt5.symbol_info_tick("BTCUSDm")
        out["btc"] = round(t.bid, 2) if t else None
        return out
    finally:
        mt5.shutdown()


def read_cycles(n=12):
    path = os.path.join(LIVEDIR, "harvest_live_cycles.csv")
    try:
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
        return [dict(id=r["cycle_id"], dir=r["direction"], trades=r["trades"],
                     hours=r["hours"], net=r["cycle_net"],
                     worst=r["max_floating_loss"], recovery=r["recovery"],
                     closed=r["closed"], balance=r["balance_after"])
                for r in rows[-n:]]
    except Exception:
        return []


def collect():
    live = read_account(LIVE_TERMINAL, LIVE_LOGIN, [MAGIC_LIVE])
    demo = read_account(DEMO_TERMINAL, DEMO_LOGIN,
                        [MAGIC_CTRL, MAGIC_TRAIL, MAGIC_PLAIN])
    hb = {k: jread(p) for k, p in (
        ("live_bot", os.path.join(LIVEDIR, "harvest_live_alive.json")),
        ("ctrl_bot", os.path.join(LIVEDIR, "renko_recovery_alive.json")),
        ("trail_bot", os.path.join(LIVEDIR, "harvest_trail_demo_alive.json")),
        ("shadow", os.path.join(STUDYDIR, "shadow_trail_alive.json")),
        ("observer", os.path.join(STUDYDIR, "signal_observer_alive.json")),
        ("drift", os.path.join(LIVEDIR, "brick_watch_status.json")))}

    def age(j):
        if not j or "alive_utc" not in j:
            return None
        t = datetime.fromisoformat(j["alive_utc"]).replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - t).total_seconds())

    return dict(
        generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        refresh_seconds=REFRESH,
        live=live, demo=demo, cycles=read_cycles(),
        heartbeats={k: age(v) for k, v in hb.items() if k != "drift"},
        state=dict(
            live=hb["live_bot"], trail=hb["trail_bot"], shadow=hb["shadow"],
            observer=hb["observer"],
            drift=(hb["drift"] or {}).get("drift_pct"),
            drift_action=(hb["drift"] or {}).get("action_needed")),
        expect=EXPECT,
        deployed=dict(start=30.95, deposits=50.00))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def log_message(self, *a):                       # quiet
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):                               # GET-only service
        self.send_error(405)


def loop():
    while True:
        try:
            data = collect()
            tmp = os.path.join(HERE, "stats.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, os.path.join(HERE, "stats.json"))
            with open(os.path.join(HERE, "stats_alive.json"), "w") as f:
                json.dump(dict(alive_utc=datetime.utcnow().isoformat()), f)
        except Exception as e:
            say(f"collect error {type(e).__name__}: {e}")
        time.sleep(REFRESH)


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    say(f"stats server on 0.0.0.0:{PORT}, refresh {REFRESH}s, read-only")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
