"""CANONICAL REFERENCE LEDGER runner, recording version rec-2 (ChatGPT brief
2026-10-09, reviews 2-4).      pythonw bos_reference_ledger.py <control uid>

Trades the frozen control strategy VIRTUALLY on the control account's OWN
price feed (attached read-only to its terminal) with the money-dependent
restrictions removed: no debt gate, no caps, no kill line, no recovery, no
scaling, fixed 0.02 lot. Same engine, awake window, storm and movement gates
as structure_bos_bot, one virtual position at a time.

THIS FILE CONTAINS NO ORDER CODE PATH (asserted at import; reads only).

rec-2 integrity rules (all logic in reference_ledger_lib, unit-tested):
 * ordered tick history (copy_ticks_range) from a persisted millisecond
   watermark; the FIRST executable barrier touch in chronology closes a
   position; coverage certified only if no unobserved gap > 5 s;
 * a fill is the first valid tick AT OR AFTER the decision time, fresh,
   with the stop on the correct side - else the candidate is blocked;
 * every missed closed bar is replayed in order; only the newest bar can
   open a trade; restart = seed to the latest closed bar (documented
   watermark, same cold-start behaviour as the production bot), runtime
   checkpoint never replays an older bar;
 * code/config drift vs the frozen snapshot aborts the runner;
 * ledger errors (duplicate, orphan close, two open, malformed) quarantine
   the file (renamed, kept) and start a fresh one - never skipped;
 * entry rows carry the controller states (global / buy / sell) built from
   validated CLOSED outcomes only, with version and origin; gate inputs
   carry their source, timestamp and freshness ('unknown' blocks);
 * costs: commission unknown (stated), swap exposure recorded, not applied.
"""
import hashlib, json, os, re as _re, sys, time
from datetime import datetime, timezone
import MetaTrader5 as mt5
UID = sys.argv[1] if len(sys.argv) > 1 else "infinity"
sys.argv = [sys.argv[0], "paper"]
import structure_bos_bot as B                 # noqa: E402  (engine, gates, constants)
import reference_ledger_lib as L              # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lab"))
from compte_controller import CompteController   # noqa: E402
assert not _re.search("mt5" + r"\.order_" + "send", open(__file__, encoding="utf-8").read()), "no-order guard"
DIR = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(DIR, "lab")
LEDGER = os.path.join(LAB, f"reference_ledger_{UID}.jsonl")
RUNTIME = os.path.join(LAB, f"reference_runtime_{UID}.json")
LOG = os.path.join(LAB, f"reference_{UID}.log")
FEED = os.path.join(DIR, "owl_chart_btc.json")
SNAP = os.path.join(LAB, f"reference_snapshot_{UID}.json")
LOCK = os.path.join(LAB, f"reference_{UID}.lock")
LOT = 0.02
GATE_MAX_AGE_S = 120.0
SIGNAL_MAX_AGE_S = 90.0        # a bar older than this at observation is a missed bar: never entered


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {m}\n")


def rec(obj):
    obj["written_at"] = time.time(); obj["recording_version"] = L.RECORDING_VERSION
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n"); f.flush(); os.fsync(f.fileno())


def checkpoint(rt):
    json.dump(rt, open(RUNTIME + ".tmp", "w", encoding="utf-8")); os.replace(RUNTIME + ".tmp", RUNTIME)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


def dt(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def single_writer():
    """One writer per ledger (review 4). The lock holds the owner's PID; a
    lock whose PID is dead is stale and taken over, a live one aborts us."""
    try:
        old = int(open(LOCK, encoding="utf-8").read().strip() or 0)
    except Exception:
        old = 0
    if old and old != os.getpid():
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, old)   # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            say(f"ABORT: another writer holds the ledger (pid {old})")
            return False
    open(LOCK, "w", encoding="utf-8").write(str(os.getpid()))
    return True


def main():
    if not single_writer():
        return
    users = json.load(open(os.path.join(DIR, "owl_nest_users.json"), encoding="utf-8"))
    u = next(x for x in users if x.get("id") == UID)
    login, server, symbol, term = int(u["login"]), u["mt5_server"], u.get("symbol", "BTCUSD"), u["terminal"]
    snap = json.load(open(SNAP, encoding="utf-8")) if os.path.exists(SNAP) else {}
    # --- drift vs the frozen snapshot: abort, never run altered code as frozen
    for f, h in (snap.get("hashes") or {}).items():
        cur = sha(os.path.join(DIR, f)) if os.path.exists(os.path.join(DIR, f)) else None
        if h is not None and cur != h:
            say(f"ABORT drift: {f} {cur} != snapshot {h} - re-freeze deliberately (review/freeze_reference_snapshot.py --refreeze)")
            return
    rc = snap.get("research_config") or {}
    RR = float(rc.get("rr", B.RR)); STORM = float(B.NERV_STORM)
    NERV = bool(rc.get("nervosity", False)); MOVE = bool(rc.get("movement", True))
    ver = sha(os.path.join(DIR, "structure_bos_bot.py"))[:12]
    assert mt5.initialize(path=term, timeout=60000), "attach failed"     # attach by path, no login
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
    # --- ledger: parse, quarantine on any error
    lines = open(LEDGER, encoding="utf-8").read().splitlines() if os.path.exists(LEDGER) else []
    st = L.parse_ledger(lines)
    if st["errors"]:
        q = LEDGER + f".quarantined.{int(time.time())}"
        os.replace(LEDGER, q)
        say(f"QUARANTINE {len(st['errors'])} ledger errors -> {os.path.basename(q)}: {st['errors'][:5]}")
        rec({"phase": "quarantine", "event_id": None, "from": os.path.basename(q), "errors": st["errors"][:20]})
        st = L.parse_ledger([])
    rt = {"used_hi": None, "used_lo": None, "tick_msc": 0, "open_event": None}
    try:
        rt.update(json.load(open(RUNTIME, encoding="utf-8")))
    except Exception:
        pass
    pos = L.reconcile(st, rt)
    if pos and "t_fill_msc" not in pos:                   # a rec-1 entry: give it the fields rec-2 needs
        pos["t_fill_msc"] = int(float(pos["t_fill"]) * 1000)
    # --- engine: seed to the latest CLOSED bar = the documented watermark
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
    last_bar = int(R["time"][-1])                      # never an older checkpoint bar
    # tick watermark: the open position's fill, else the checkpoint, else NOW
    # (never 0: that would ask the terminal for its whole tick history)
    rt["tick_msc"] = max(int(rt.get("tick_msc") or 0), (int(pos["t_fill_msc"]) - 1) if pos else 0) or int(time.time() * 1000)
    checkpoint(rt)
    rec({"phase": "restart", "event_id": None, "feed": feed_id, "strategy_version": ver, "spec": spec,
         "research_config": rc, "snapshot_git": snap.get("git"), "engine_watermark": last_bar,
         "tick_watermark_msc": rt["tick_msc"], "open_event": pos["event_id"] if pos else None,
         "note": "engine cold-seeded to the watermark like the production bot on restart"})
    say(f"REFERENCE {UID} {L.RECORDING_VERSION} attached read-only to {feed_id} | strategy {ver} | watermark {last_bar} | open {pos['event_id'] if pos else None}")

    def states_before():
        used, excluded = L.closed_outcomes(st)
        out = {}
        for name, flt in (("global", lambda d: True), ("buy", lambda d: d == 1), ("sell", lambda d: d == -1)):
            c = CompteController()
            for ev, d, p in used:
                if flt(d):
                    c.feed(p, event=ev)
            s = c.state
            out[name] = {"trend": s["trend"], "choch": s["choch"], "status": s["status"], "origin": s["origin"],
                         "origin_window": s["origin_window"], "n": s["n"], "version": s["version"]}
        out["outcomes_used"] = len(used); out["outcomes_excluded"] = excluded
        out["basis"] = "gross pnl of validated closes (commission unknown)"
        return out

    def close(why, px, t_close, cov, bounds=None):
        nonlocal pos
        gross = (px - pos["entry"]) * pos["dir"] * LOT * spec["contract_size"]
        row = {"phase": "close", "event_id": pos["event_id"], "exit": px, "exit_why": why, "t_close": t_close,
               "ticks_ok": bool(cov.get("certified")), "coverage": cov, "pnl_usd_gross": round(gross, 6),
               "pnl_r": round(gross / pos["risk_usd"], 6) if pos.get("risk_usd") else None,
               "cost_note": "gross; commission unknown", **L.rollover_exposure(float(pos["t_fill"]), t_close)}
        if bounds:
            row.update({"pnl_lo": round(bounds["pnl_lo"], 6), "pnl_hi": round(bounds["pnl_hi"], 6), "provenance": bounds["provenance"]})
        if not pos.get("recording_version"):
            row["limitations"] = "entry recorded by rec-1 (snapshot ticks, 120 s tolerance)"
        rec(row); st["seen"].setdefault(row["event_id"], []).append("close")
        st["open"].pop(row["event_id"], None); st["closed"].add(row["event_id"]); st["rows"].append(row)
        say(f"CLOSE {pos['event_id']} {why} {gross:+.4f} certified={row['ticks_ok']}")
        pos = None; rt["open_event"] = None; checkpoint(rt)

    while True:
        time.sleep(min(60.0 - (time.time() % 60.0) + 0.2, 1.0))
        try:
            now = time.time()
            # --- 1. ordered ticks since the watermark; first barrier touch closes
            raw = mt5.copy_ticks_range(symbol, dt(max(0, rt["tick_msc"] / 1000.0 - 1)), dt(now + 1), mt5.COPY_TICKS_ALL)
            ticks, dropped = L.ordered_new_ticks(list(raw) if raw is not None else [], rt["tick_msc"])
            if pos and ticks:
                why, px, msc, cov = L.first_barrier_hit(ticks, pos)
                if why:
                    close(why, float(px), msc / 1000.0, cov)
            if ticks:
                rt["tick_msc"] = int(ticks[-1]["time_msc"]); checkpoint(rt)
            # --- 2. every missed closed bar, in order
            kb = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, dt(last_bar + 60), dt(now))
            bars = [b for b in (list(kb) if kb is not None else []) if int(b["time"]) + 60 <= now]
            for bar in L.missing_bars(last_bar, bars):
                bt = int(bar["time"]); last_bar = bt
                # no tick coverage at all for a bar while open: only then the bid-side bar speaks
                if pos and bt >= float(pos["t_fill"]) and not ticks and (now - rt["tick_msc"] / 1000.0) > 60:
                    amb = L.bar_ambiguity(dict(pos, contract_size=spec["contract_size"]), bar)
                    if amb:
                        close(amb["status"], pos["sl"] if "sl" in amb["status"] else pos["tp"], bt + 60,
                              {"ticks": 0, "max_gap_ms": None, "certified": False}, amb)
                pt = eng.trend; hv, lv = eng.hi_v, eng.lo_v
                sig = eng.step(bt, float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
                flip = eng.trend != pt and eng.trend != 0 and pt != 0
                if flip:
                    flips.append(bt); del flips[:-20]
                if sig is None:
                    continue
                d, slp = sig; kind = "FLIP-BOS" if flip else "BOS"
                ev = f"{feed_id}:{ver}:{bt}:{d}:{kind}"

                def blocked(reason, extra=None):
                    if ev in st["seen"]:
                        return
                    row = {"phase": "blocked", "event_id": ev, "dir": d, "kind": kind, "t_bar_open": bt,
                           "t_bar_close": bt + 60, "t_obs": now, "reason": reason}
                    if extra:
                        row.update(extra)
                    rec(row); st["seen"][ev] = ["blocked"]; st["rows"].append(row)
                if now - (bt + 60) > SIGNAL_MAX_AGE_S:
                    blocked("missed_bar_replay", {"bar_age_s": round(now - bt - 60, 1)}); continue
                if not L.entry_allowed(st, ev):
                    blocked("position_open" if pos else "event_seen"); continue
                if not any(f > bt - B.AWAKE_WIN for f in flips):
                    blocked("not_awake"); continue
                if not flip:
                    lvl = hv if d == 1 else lv
                    if (d == 1 and rt.get("used_hi") == lvl) or (d == -1 and rt.get("used_lo") == lvl):
                        blocked("level_used"); continue
                    if d == 1:
                        rt["used_hi"] = lvl
                    else:
                        rt["used_lo"] = lvl
                    checkpoint(rt)
                # gate input: source, timestamp, freshness - unknown blocks
                try:
                    cj = json.load(open(FEED, encoding="utf-8")); gate_age = now - float(cj.get("updated") or 0)
                except Exception:
                    cj, gate_age = {}, None
                gate = {"source": "owl_chart_btc.json (the chart feed's terminal; the same file the production bot reads)",
                        "updated": cj.get("updated"), "age_s": round(gate_age, 1) if gate_age is not None else None,
                        "vol_now": cj.get("vol_now"), "vol_ref": cj.get("vol_ref"), "moves_2h": cj.get("moves_2h")}
                if gate_age is None or gate_age > GATE_MAX_AGE_S or not cj.get("vol_now"):
                    blocked("gate_unknown", {"gate": gate}); continue
                nv = cj["vol_now"] / max(cj.get("vol_ref") or 1, 1)
                if nv >= STORM:
                    blocked(f"storm {nv:.2f}x", {"gate": gate}); continue
                if NERV and nv > 1.0:
                    blocked(f"nervous {nv:.2f}x", {"gate": gate}); continue
                if MOVE and (cj.get("moves_2h") or 0) < 1:
                    blocked("no_move_2h", {"gate": gate}); continue
                # decision -> fill: the first valid tick at/after the decision, fresh
                decision_ms = int(time.time() * 1000)
                ft, why = None, None
                for _ in range(6):
                    fr = mt5.copy_ticks_range(symbol, dt(decision_ms / 1000.0 - 1), dt(time.time() + 1), mt5.COPY_TICKS_ALL)
                    cand, _ = L.ordered_new_ticks(list(fr) if fr is not None else [], decision_ms - 1)
                    ft, why = L.fill_tick(cand, decision_ms)
                    if ft:
                        break
                    time.sleep(0.5)
                if not ft:
                    blocked("no_tick_after_decision", {"gate": gate}); continue
                if not L.fill_age_ok(int(ft["time_msc"]), decision_ms, int(time.time() * 1000)):
                    blocked("fill_tick_stale", {"gate": gate}); continue
                e = float(ft["ask"] if d == 1 else ft["bid"])
                if not L.stop_side_ok(d, e, slp):
                    blocked("wrong_side_stop", {"gate": gate, "entry": e, "sl": slp}); continue
                dist = abs(e - slp)
                if dist <= B.S_MIN_DIST:
                    blocked(f"min_dist {dist:.1f}", {"gate": gate}); continue
                tp = e + d * RR * dist
                risk = dist * LOT * spec["contract_size"]
                pos = {"phase": "entry", "event_id": ev, "dir": d, "kind": kind, "t_bar_open": bt, "t_bar_close": bt + 60,
                       "t_obs": now, "t_decision_msc": decision_ms, "t_fill_msc": int(ft["time_msc"]),
                       "t_fill": ft["time_msc"] / 1000.0, "entry": e, "sl": round(slp, 2), "tp": round(tp, 2), "lot": LOT,
                       "risk_usd": round(risk, 6), "spread_at_fill": round(float(ft["ask"] - ft["bid"]), 2),
                       "bar_close_px": float(bar["close"]), "strategy_version": ver, "feed": feed_id,
                       "gate": gate, "state_before": states_before(), "eligible": True, "valid": True}
                rec(pos); st["seen"][ev] = ["entry"]; st["open"][ev] = pos; st["rows"].append(pos)
                rt["open_event"] = ev; rt["tick_msc"] = max(rt["tick_msc"], int(ft["time_msc"])); checkpoint(rt)
                sb = pos["state_before"]
                say(f"ENTRY {ev} {'BUY' if d == 1 else 'SELL'} @ {e:.2f} SL {slp:.2f} TP {tp:.2f} risk {risk:.4f} | states g/b/s {sb['global']['trend']}/{sb['buy']['trend']}/{sb['sell']['trend']}")
        except Exception as ex:
            say(f"ERROR {type(ex).__name__}: {ex}")
            time.sleep(30)


if __name__ == "__main__":
    main()
