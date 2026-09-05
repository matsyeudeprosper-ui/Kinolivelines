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
        data = {
            "t": time.time(),
            "balance": ai.balance,
            "positions": [{
                "ticket": p.ticket,
                "dir": 1 if p.type == mt5.POSITION_TYPE_BUY else -1,
                "volume": p.volume,
                "entry": p.price_open,
                "sl": p.sl, "tp": p.tp,
            } for p in pos if (p.comment or "").startswith("OWL-")],
        }
        tmp = OUT + ".tmp"
        json.dump(data, open(tmp, "w"))
        os.replace(tmp, OUT)
    except Exception as e:
        say(f"error: {e}")
        time.sleep(5)
    time.sleep(1)
