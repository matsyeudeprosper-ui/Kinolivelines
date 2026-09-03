src = open('owl_manual_bot.py', encoding='utf-8').read()

def rep(old, new):
    global src
    assert old in src, f"NOT FOUND: {old[:70]!r}"
    assert src.count(old) == 1, f"NOT UNIQUE: {old[:70]!r}"
    src = src.replace(old, new)

# helper: door-2 trigger level
rep("def connect():",
    '''def reent_trigger(dirn, entry_price, t0):
    """Door-2 (fake-break re-entry, user 2026-08-31): trigger = the first
    entry price, or the closest M1 extreme just before it (15-min window).
    A failed BUY re-arms as BUY when an M1 CLOSES back above this level
    (mirror for SELL)."""
    try:
        bars = mt5.copy_rates_range(
            SYMBOL, mt5.TIMEFRAME_M1,
            datetime.fromtimestamp(t0 - 900, tz=timezone.utc),
            datetime.fromtimestamp(t0, tz=timezone.utc))
        if bars is not None and len(bars):
            if dirn == 1:
                return max(float(entry_price), float(np.max(bars["high"])))
            return min(float(entry_price), float(np.min(bars["low"])))
    except Exception:
        pass
    return float(entry_price)

def connect():''')

# arm site A: chain-link re-arm gets the door-2 trigger too
rep('''                        if row.get("exit_reason") == "sl" and _t0 is not None:
                            st.setdefault("recov_watches", []).append({
                                "dir": 1 if ent["direction"] == "BUY" else -1,
                                "sl": float(_lk.get("sl") or row.get("exit_price")
                                            or 0.0),
                                "lot": float(ent["volume"]),
                                "t0": _t0, "t_sl": int(time.time()),
                                "chain": _cn})
                            say(f"RECOV[{_cn}]: link {tkey} stopped -> watching "
                                f"for M1 close beyond "
                                f"{float(_lk.get('sl') or 0.0):.2f}")''',
    '''                        if row.get("exit_reason") == "sl" and _t0 is not None:
                            _d = 1 if ent["direction"] == "BUY" else -1
                            _tr = reent_trigger(_d, ent["entry_price"], _t0)
                            st.setdefault("recov_watches", []).append({
                                "dir": _d,
                                "sl": float(_lk.get("sl") or row.get("exit_price")
                                            or 0.0),
                                "lot": float(ent["volume"]),
                                "t0": _t0, "t_sl": int(time.time()),
                                "trig": _tr, "chain": _cn})
                            say(f"RECOV[{_cn}]: link {tkey} stopped -> two doors: "
                                f"M1 close beyond "
                                f"{float(_lk.get('sl') or 0.0):.2f} = flip, "
                                f"or back beyond {_tr:.2f} = re-enter")''')

# arm site B: user-trade arm gets the door-2 trigger too
rep('''                        if _sl:
                            st.setdefault("recov_watches", []).append({
                                "dir": 1 if ent["direction"] == "BUY" else -1,
                                "sl": float(_sl), "lot": float(ent["volume"]),
                                "t0": _t0, "t_sl": int(time.time()),
                                "chain": tkey})
                            save_state(st)
                            say(f"RECOV[{tkey}] armed: {ent['direction']} "
                                f"{ent['volume']} stopped at {float(_sl):.2f} -> "
                                f"waiting for an M1 CLOSE beyond the line")''',
    '''                        if _sl:
                            _d = 1 if ent["direction"] == "BUY" else -1
                            _tr = reent_trigger(_d, ent["entry_price"], _t0)
                            st.setdefault("recov_watches", []).append({
                                "dir": _d,
                                "sl": float(_sl), "lot": float(ent["volume"]),
                                "t0": _t0, "t_sl": int(time.time()),
                                "trig": _tr, "chain": tkey})
                            save_state(st)
                            say(f"RECOV[{tkey}] armed: {ent['direction']} "
                                f"{ent['volume']} stopped at {float(_sl):.2f} -> "
                                f"two doors: M1 close beyond the line = flip, "
                                f"or back beyond {_tr:.2f} = re-enter")''')

# watch loop: two doors decide direction and wall window
rep('''                        _cl = float(b1["close"][0])
                        _broke = (_cl < rw["sl"] if rw["dir"] == 1
                                  else _cl > rw["sl"])
                        if _broke:
                            new_dir = -rw["dir"]
                            new_lot = round(rw["lot"] + RECOV_STEP, 2)
                            legbars = mt5.copy_rates_range(
                                SYMBOL, mt5.TIMEFRAME_M1,
                                datetime.fromtimestamp(rw["t0"] - 60,
                                                       tz=timezone.utc),
                                datetime.now(timezone.utc))''',
    '''                        _cl = float(b1["close"][0])
                        _broke = (_cl < rw["sl"] if rw["dir"] == 1
                                  else _cl > rw["sl"])
                        _tg = rw.get("trig")
                        _reent = (not _broke and _tg is not None
                                  and (_cl > _tg if rw["dir"] == 1
                                       else _cl < _tg))
                        if _broke or _reent:
                            new_dir = rw["dir"] if _reent else -rw["dir"]
                            new_lot = round(rw["lot"] + RECOV_STEP, 2)
                            legbars = mt5.copy_rates_range(
                                SYMBOL, mt5.TIMEFRAME_M1,
                                datetime.fromtimestamp(
                                    (rw["t_sl"] - 120) if _reent
                                    else (rw["t0"] - 60),
                                    tz=timezone.utc),
                                datetime.now(timezone.utc))''')

# entry log line: label which door fired
rep('''                                        say(f"RECOV[{_cn}] ENTRY: "''',
    '''                                        say(f"RECOV[{_cn}] "
                                            f"{'RE-ENTRY (fake break)' if _reent else 'ENTRY'}: "''')

# watch lifetime: 60 min -> 6 h (two doors need time)
rep('''                    if not done and time.time() - rw["t_sl"] > 3600:
                        say(f"RECOV[{_cn}] watch EXPIRED (60 min, no M1 close "
                            f"beyond the line)")''',
    '''                    if not done and time.time() - rw["t_sl"] > 21600:
                        say(f"RECOV[{_cn}] watch EXPIRED (6 h, neither door "
                            f"opened)")''')

open('owl_manual_bot.py', 'w', encoding='utf-8').write(src)
import ast
ast.parse(src)
open('owl_manual_bot.py', encoding='cp1252').read()
print("two-door patch applied, syntax OK, cp1252-safe")
