"""CANONICAL REFERENCE LEDGER runner (ChatGPT brief 2026-10-09, reviews 2-3).
    pythonw bos_reference_ledger.py <control uid>        (default: infinity)

Trades the frozen control strategy VIRTUALLY on the control account's OWN
price feed (attached read-only to its terminal) with the money-dependent
restrictions removed: no debt gate, no caps, no kill line, no recovery, no
scaling, fixed 0.02 lot. Same engine, awake window, storm and movement gates
as structure_bos_bot, one virtual position at a time, exits on executable
ticks, swept on the closed bar only where ticks were missing (flagged).

THIS FILE CONTAINS NO ORDER CODE PATH. It never calls order_send, never logs
in (attach by terminal path only) and aborts if the terminal's account is not
the control's. It reads prices and symbol specifications; nothing else.

Ledger: lab/reference_ledger_<uid>.jsonl, append-only, one JSON object per
line: phase "entry" at fill, "close" at exit (same event_id), "blocked" for a
candidate not taken (reason), "gap" when the feed was stale/invalid. On
restart the open opportunity and seen event ids are rebuilt from the ledger.
Costs: the symbol's swap fields are recorded; commission is "unknown" (MT5's
python API exposes no schedule) - pnl_usd is GROSS of commission, stated.
"""
import hashlib, json, os, sys, time
from datetime import datetime, timezone
import MetaTrader5 as mt5
UID = sys.argv[1] if len(sys.argv) > 1 else "infinity"
sys.argv = [sys.argv[0], "paper"]            # structure_bos_bot resolves a harmless variant at import
import structure_bos_bot as B                 # noqa: E402  (engine, gates, constants - no main())
DIR = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(DIR, "lab")
LEDGER = os.path.join(LAB, f"reference_ledger_{UID}.jsonl")
RUNTIME = os.path.join(LAB, f"reference_runtime_{UID}.json")
LOG = os.path.join(LAB, f"reference_{UID}.log")
FEED = os.path.join(DIR, "owl_chart_btc.json")
SNAP = os.path.join(LAB, f"reference_snapshot_{UID}.json")
LOT = 0.02
STALE_S = 120.0          # a tick older than this at a bar close = gap, no entry
# no-order guard: this file must never acquire a trading call
import re as _re
assert not _re.search("mt5" + r"\.order_" + "send", open(__file__, encoding="utf-8").read()), "no-order guard"


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {m}\n")


def rec(obj):
    obj["written_at"] = time.time()
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


def load_ledger():
    opened, seen = {}, set()
    if os.path.exists(LEDGER):
        for line in open(LEDGER, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            seen.add((r.get("event_id"), r.get("phase")))
            if r.get("phase") == "entry":
                opened[r["event_id"]] = r
            elif r.get("phase") == "close":
                opened.pop(r["event_id"], None)
    return opened, seen


def main():
    users = json.load(open(os.path.join(DIR, "owl_nest_users.json"), encoding="utf-8"))
    u = next(x for x in users if x.get("id") == UID)
    login, server, symbol, term = int(u["login"]), u["mt5_server"], u.get("symbol", "BTCUSD"), u["terminal"]
    snap = json.load(open(SNAP, encoding="utf-8")) if os.path.exists(SNAP) else {}
    rc = snap.get("research_config") or {}
    RR = float(rc.get("rr", B.RR)); STORM = float(B.NERV_STORM); NERV = bool(rc.get("nervosity", False)); MOVE = bool(rc.get("movement", True))
    ver = hashlib.sha256(open(os.path.join(DIR, "structure_bos_bot.py"), "rb").read()).hexdigest()[:12]
    # ATTACH, never log in: initialize(path) joins the running terminal as it is
    assert mt5.initialize(path=term, timeout=60000), "attach failed"
    ai = mt5.account_info()
    if ai is None or ai.login != login or ai.server != server:
        say(f"ABORT: terminal {term} holds {getattr(ai, 'login', None)}@{getattr(ai, 'server', None)}, expected {login}@{server}")
        mt5.shutdown(); return
    mt5.symbol_select(symbol, True)
    si = mt5.symbol_info(symbol)
    spec = {"contract_size": si.trade_contract_size, "volume_min": si.volume_min, "volume_step": si.volume_step,
            "swap_long": si.swap_long, "swap_short": si.swap_short, "swap_mode": si.swap_mode,
            "commission": "unknown (not exposed by the MT5 python API)", "spec_read_at": time.time()}
    feed_id = f"{server}:{login}:{symbol}"
    say(f"REFERENCE {UID} attached read-only to {feed_id} | strategy {ver} | rr {RR} lot {LOT} | nervosity gate {NERV} movement {MOVE} | spec {spec}")
    rec({"phase": "start", "event_id": None, "feed": feed_id, "strategy_version": ver, "spec": spec,
         "research_config": rc, "snapshot_git": snap.get("git")})
    eng = B.Struct(); eng.quiet = True
    flips = []
    R = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, B.SEED_BARS)
    assert R is not None and len(R) > 100, "no history"
    for r in R:
        pt = eng.trend
        eng.step(int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        if eng.trend != pt and eng.trend != 0 and pt != 0:
            flips.append(int(r["time"]))
    flips = flips[-20:]
    opened, seen = load_ledger()
    pos = next(iter(opened.values()), None)        # at most one by construction
    rt = {"used_hi": None, "used_lo": None, "last_bar": int(R["time"][-1])}
    try:
        rt.update(json.load(open(RUNTIME, encoding="utf-8")))
    except Exception:
        pass
    say(f"seeded {len(R)} bars: trend {eng.trend} | open opportunity: {pos['event_id'] if pos else None} | {len(seen)} ledger rows")

    def save_rt():
        json.dump(rt, open(RUNTIME + ".tmp", "w", encoding="utf-8")); os.replace(RUNTIME + ".tmp", RUNTIME)

    def close(px, why, t_close, ticks_ok, lo=None, hi=None):
        nonlocal pos
        d = pos["dir"]; gross = (px - pos["entry"]) * d * LOT * spec["contract_size"]
        row = {"phase": "close", "event_id": pos["event_id"], "exit": px, "exit_why": why, "t_close": t_close,
               "ticks_ok": ticks_ok, "pnl_usd_gross": round(gross, 6),
               "pnl_r": round(gross / pos["risk_usd"], 6) if pos["risk_usd"] else None,
               "cost_note": "commission unknown; swap not applied (intraday)"}
        if lo is not None:
            row.update({"pnl_lo": round((lo - pos["entry"]) * d * LOT * spec["contract_size"], 6),
                        "pnl_hi": round((hi - pos["entry"]) * d * LOT * spec["contract_size"], 6)})
        if (row["event_id"], "close") not in seen:
            rec(row); seen.add((row["event_id"], "close"))
        say(f"CLOSE {pos['event_id']} {why} {gross:+.4f} ticks_ok={ticks_ok}")
        pos = None

    while True:
        time.sleep(min(60.0 - (time.time() % 60.0) + 0.2, 1.0))
        try:
            tick = mt5.symbol_info_tick(symbol)
            now = time.time()
            if tick is None:
                continue
            t_tick = tick.time_msc / 1000.0 if tick.time_msc else float(tick.time)
            # --- open opportunity: exits on executable ticks
            if pos and t_tick >= pos["t_fill"]:
                if pos["dir"] == 1:
                    if tick.bid <= pos["sl"]: close(tick.bid, "sl", t_tick, True)
                    elif tick.bid >= pos["tp"]: close(pos["tp"], "tp", t_tick, True)
                else:
                    if tick.ask >= pos["sl"]: close(tick.ask, "sl", t_tick, True)
                    elif tick.ask <= pos["tp"]: close(pos["tp"], "tp", t_tick, True)
            kb = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, 2)
            if kb is None or len(kb) < 2:
                continue
            bar = kb[-1]; bt = int(bar["time"])
            if bt == rt.get("last_bar"):
                continue
            rt["last_bar"] = bt
            stale = (now - t_tick) > STALE_S
            # --- bar sweep ONLY for bars entirely after the fill, when ticks may have gapped
            if pos and bt >= pos["t_fill"]:
                h, l = float(bar["high"]), float(bar["low"])
                hit_sl = (l <= pos["sl"]) if pos["dir"] == 1 else (h >= pos["sl"])
                hit_tp = (h >= pos["tp"]) if pos["dir"] == 1 else (l <= pos["tp"])
                if hit_sl and hit_tp:
                    close(pos["sl"], "ambiguous", bt + 60, False, lo=pos["sl"], hi=pos["tp"])
                elif hit_sl:
                    close(pos["sl"], "sl-bar", bt + 60, False)
                elif hit_tp:
                    close(pos["tp"], "tp-bar", bt + 60, False)
            # --- the engine sees every closed bar
            pt = eng.trend
            hv, lv = eng.hi_v, eng.lo_v
            sig = eng.step(bt, float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
            flip = eng.trend != pt and eng.trend != 0 and pt != 0
            if flip:
                flips.append(bt); del flips[:-20]
            save_rt()
            if sig is None:
                continue
            d, slp = sig
            kind = "FLIP-BOS" if flip else "BOS"
            ev = f"{feed_id}:{ver}:{bt}:{d}:{kind}"
            def blocked(reason):
                if (ev, "blocked") not in seen:
                    rec({"phase": "blocked", "event_id": ev, "dir": d, "kind": kind, "t_bar_open": bt,
                         "t_bar_close": bt + 60, "t_obs": now, "reason": reason}); seen.add((ev, "blocked"))
            if stale:
                rec({"phase": "gap", "event_id": ev, "t_obs": now, "tick_age_s": round(now - t_tick, 1)}); say(f"GAP stale tick {now - t_tick:.0f}s at {bt}"); continue
            if pos:
                blocked("position_open"); continue
            if not any(f > bt - B.AWAKE_WIN for f in flips):
                blocked("not_awake"); continue
            if not flip:
                lvl = hv if d == 1 else lv
                if (d == 1 and rt.get("used_hi") == lvl) or (d == -1 and rt.get("used_lo") == lvl):
                    blocked("level_used"); continue
                if d == 1: rt["used_hi"] = lvl
                else: rt["used_lo"] = lvl
                save_rt()
            try:
                cj = json.load(open(FEED, encoding="utf-8"))
            except Exception:
                cj = {}
            vn, vr = cj.get("vol_now"), cj.get("vol_ref")
            nv = (vn / max(vr, 1)) if vn and vr else 1.0
            if nv >= STORM:
                blocked(f"storm {nv:.2f}x"); continue
            if NERV and nv > 1.0:
                blocked(f"nervous {nv:.2f}x"); continue
            if MOVE and (cj.get("moves_2h") or 0) < 1:
                blocked("no_move_2h"); continue
            tk = mt5.symbol_info_tick(symbol)
            if tk is None:
                blocked("no_tick"); continue
            t_fill = tk.time_msc / 1000.0 if tk.time_msc else float(tk.time)
            e = tk.ask if d == 1 else tk.bid                     # executable, embeds the spread
            dist = abs(e - slp)
            if dist <= B.S_MIN_DIST:
                blocked(f"min_dist {dist:.1f}"); continue
            tp = e + d * RR * dist                                # production anchoring: stop at the level, target from the fill
            risk = dist * LOT * spec["contract_size"]
            pos = {"phase": "entry", "event_id": ev, "dir": d, "kind": kind, "t_bar_open": bt, "t_bar_close": bt + 60,
                   "t_obs": now, "t_fill": t_fill, "entry": e, "sl": round(slp, 2), "tp": round(tp, 2), "lot": LOT,
                   "risk_usd": round(risk, 6), "spread_at_fill": round(tk.ask - tk.bid, 2),
                   "bar_close_px": float(bar["close"]), "strategy_version": ver, "feed": feed_id,
                   "eligible": True, "valid": True}
            if (ev, "entry") not in seen:
                rec(pos); seen.add((ev, "entry"))
            say(f"ENTRY {ev} {'BUY' if d == 1 else 'SELL'} @ {e:.2f} SL {slp:.2f} TP {tp:.2f} risk {risk:.4f} spread {tk.ask - tk.bid:.2f}")
        except Exception as ex:
            say(f"ERROR {type(ex).__name__}: {ex}")
            time.sleep(30)


if __name__ == "__main__":
    main()
