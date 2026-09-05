"""owl_master_publisher.py - publish the master's OWL positions (2026-09-05).

One tiny process attached to the MASTER terminal (kino, 134499778).
Every second it writes owl_master_positions.json (atomic) with every
OWL-* position's ticket/side/volume/entry/SL/TP plus the master
balance. Copiers (owl_copier.py <uid>) mirror from this file - local
disk, ~1s propagation. The strategy bot is untouched.
"""
import json
import os
import time
import MetaTrader5 as mt5

DIR = r"C:\Projects\KinoliveLines\live"
TERMINAL = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
LOGIN = 134499778
SYMBOL = "BTCUSDm"
OUT = os.path.join(DIR, "owl_master_positions.json")
LOG = os.path.join(DIR, "owl_master_publisher.log")


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")


say("publisher starting")
# event-push upgrade (2026-09-05 user): poll the terminal at 0.25s but
# WRITE only when something changed (plus a 5s heartbeat so copiers can
# tell a quiet master from a dead one). Copiers watch the file's mtime
# at 10Hz - a change propagates in ~0.1s instead of ~1s.
_last_payload = None
_last_write = 0.0
while True:
    try:
        if not mt5.initialize(path=TERMINAL):
            time.sleep(5)
            continue
        ai = mt5.account_info()
        if ai is None or ai.login != LOGIN:
            say(f"wrong account {ai.login if ai else None}")
            time.sleep(10)
            continue
        pos = mt5.positions_get(symbol=SYMBOL) or []
        payload = {
            "balance": ai.balance,
            "positions": [{
                "ticket": p.ticket,
                "dir": 1 if p.type == mt5.POSITION_TYPE_BUY else -1,
                "volume": p.volume,
                "entry": p.price_open,
                "sl": p.sl, "tp": p.tp,
            } for p in pos if (p.comment or "").startswith("OWL-")],
        }
        key = json.dumps(payload["positions"], sort_keys=True)
        now = time.time()
        if key != _last_payload or now - _last_write >= 5:
            data = dict(payload, t=now)
            tmp = OUT + ".tmp"
            json.dump(data, open(tmp, "w"))
            os.replace(tmp, OUT)
            _last_payload = key
            _last_write = now
    except Exception as e:
        say(f"error: {e}")
        time.sleep(5)
    time.sleep(0.25)
