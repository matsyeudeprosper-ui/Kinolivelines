"""Pure logic of the reference ledger (ChatGPT review 4) - no MT5, no I/O,
so every rule here is unit-tested in lab/test_reference_ledger.py.

Ledger = append-only JSONL. Row phases: start, restart, entry, close,
blocked, gap, quarantine. event_id is causal (feed:strategy:bar:dir:kind).
Lifecycle: an event_id with ANY row is final, except entry -> close (once).
Closed ids never reopen; at most one open entry; malformed or inconsistent
input quarantines the stream instead of being skipped."""
import json, math

ENTRY_NUM = ("dir", "entry", "sl", "tp", "lot", "t_fill_msc")
CLOSE_NUM = ("exit", "t_close", "pnl_usd_gross")


def _finite_fields(r, names):
    for k in names:
        v = r.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            return k
    return None

RECORDING_VERSION = "rec-3"
MAX_TICK_GAP_MS = 5000          # longer unobserved interval = coverage not certified
FILL_MAX_AGE_MS = 5000          # the fill tick must be this fresh vs the decision


# ---------------------------------------------------------------- ledger
def parse_ledger(lines):
    """-> dict(rows, open{id: entry}, closed{id}, seen{id: [phases]}, errors[])"""
    st = {"rows": [], "open": {}, "closed": set(), "seen": {}, "errors": []}
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        try:
            r = json.loads(s)
            if not isinstance(r, dict) or "phase" not in r:
                raise ValueError("not a row")
        except Exception as e:
            st["errors"].append((i, "malformed", str(e)[:60])); continue
        st["rows"].append(r)
        ev, ph = r.get("event_id"), r["phase"]
        if ev is None:
            continue
        ph_seen = st["seen"].setdefault(ev, [])
        if ph == "entry":
            if "close" in ph_seen:
                st["errors"].append((i, "entry_after_close", ev)); continue
            if "entry" in ph_seen:
                st["errors"].append((i, "duplicate_entry", ev)); continue
            if "blocked" in ph_seen:
                st["errors"].append((i, "entry_after_blocked", ev)); continue
            bad = _finite_fields(r, ENTRY_NUM)
            if bad or r.get("dir") not in (1, -1):
                st["errors"].append((i, "entry_schema", f"{ev}:{bad or 'dir'}")); continue
            st["open"][ev] = r
        elif ph == "close":
            if "close" in ph_seen:
                st["errors"].append((i, "duplicate_close", ev)); continue
            if "entry" not in ph_seen:
                st["errors"].append((i, "close_without_entry", ev)); continue
            bad = _finite_fields(r, CLOSE_NUM)
            if bad:
                st["errors"].append((i, "close_schema", f"{ev}:{bad}")); continue
            st["open"].pop(ev, None); st["closed"].add(ev)
        elif ph == "blocked":
            if ph_seen:
                st["errors"].append((i, "blocked_after_" + ph_seen[-1], ev)); continue
        ph_seen.append(ph)
    if len(st["open"]) > 1:
        st["errors"].append((-1, "multiple_open", sorted(st["open"])))
    return st


def entry_allowed(st, event_id):
    """An event with any row is final (blocked stays blocked, closed stays closed)."""
    return event_id not in st["seen"] and not st["open"]


def reconcile(st, runtime):
    """The ledger wins over the runtime checkpoint (a crash can happen after
    the append and before the checkpoint). Returns the open entry or None."""
    if st["errors"]:
        return None
    opens = list(st["open"].values())
    if not opens:
        return None
    pos = opens[0]
    runtime["open_event"] = pos["event_id"]              # the checkpoint may be stale or empty
    return pos


def closed_outcomes(st):
    """Every close in order as (event_id, dir, gross pnl, resolved). The
    PRIMARY curve treats an unresolved close (ambiguous / uncertified) as a
    GAP: the controller is fed valid=False there and latches invalid until
    the complete chronology is replayed resolved. A FILTERED diagnostic
    curve (named so) uses the resolved ones only. Nothing is silently erased."""
    out = []
    entries = {r["event_id"]: r for r in st["rows"] if r["phase"] == "entry"}
    for r in st["rows"]:
        if r["phase"] != "close":
            continue
        e = entries.get(r["event_id"])
        resolved = (e is not None and r.get("exit_why") != "ambiguous" and bool(r.get("ticks_ok", False)))
        out.append((r["event_id"], e["dir"] if e else 0, float(r["pnl_usd_gross"]), resolved,
                    {"why": r.get("exit_why"), "hold_s": r.get("hold_s"), "win": float(r["pnl_usd_gross"]) > 0}))
    return out


def exclusion_report(outcomes):
    """How unresolved outcomes relate to duration, direction and win/loss."""
    un = [o for o in outcomes if not o[3]]; res = [o for o in outcomes if o[3]]
    def m(xs, f):
        xs = [f(x) for x in xs if f(x) is not None]
        return (sum(xs) / len(xs)) if xs else None
    return {"unresolved": len(un), "resolved": len(res),
            "unresolved_mean_hold_s": m(un, lambda o: o[4]["hold_s"]), "resolved_mean_hold_s": m(res, lambda o: o[4]["hold_s"]),
            "unresolved_buy_share": m(un, lambda o: 1.0 if o[1] == 1 else 0.0), "resolved_buy_share": m(res, lambda o: 1.0 if o[1] == 1 else 0.0),
            "unresolved_win_share": m(un, lambda o: 1.0 if o[4]["win"] else 0.0), "resolved_win_share": m(res, lambda o: 1.0 if o[4]["win"] else 0.0)}


# ---------------------------------------------------------------- chronology
def tick_ok(t):
    b, a = t["bid"], t["ask"]
    return (isinstance(b, (int, float)) and isinstance(a, (int, float))
            and math.isfinite(b) and math.isfinite(a) and b > 0 and a >= b)


def ordered_new_ticks(ticks, watermark_msc, seen_at_mark=0):
    """New ticks in (msc, arrival) order: strictly after the watermark, plus
    those AT the watermark millisecond beyond the `seen_at_mark` already
    processed (late arrivals sharing a timestamp). Invalid dropped+counted.
    -> (list, dropped, new_mark_msc, new_seen_at_mark)"""
    out, dropped, at_mark = [], 0, 0
    for i, t in enumerate(ticks):
        if t["time_msc"] < watermark_msc:
            continue
        if not tick_ok(t):
            dropped += 1; continue
        if t["time_msc"] == watermark_msc:
            at_mark += 1
            if at_mark <= seen_at_mark:
                continue
        out.append((t["time_msc"], i, t))
    out.sort(key=lambda x: (x[0], x[1]))
    lst = [t for _, _, t in out]
    if lst:
        last = lst[-1]["time_msc"]
        n_last = (seen_at_mark if last == watermark_msc else 0) + sum(1 for t in lst if t["time_msc"] == last)
        return lst, dropped, last, n_last
    return lst, dropped, watermark_msc, seen_at_mark


def stop_side_ok(d, entry, sl):
    return (sl < entry) if d == 1 else (sl > entry)


def fill_tick(ticks, decision_msc, max_age_ms=FILL_MAX_AGE_MS):
    """The first valid tick AT OR AFTER the decision - never an earlier quote.
    -> (tick, reason)"""
    for t in ticks:
        if t["time_msc"] < decision_msc or not tick_ok(t):
            continue
        return t, None
    return None, "no_tick_after_decision"


def fill_age_ok(fill_msc, decision_msc, now_msc, max_age_ms=FILL_MAX_AGE_MS):
    return fill_msc >= decision_msc and (now_msc - fill_msc) <= max_age_ms


def new_coverage(fill_msc):
    """Per-open-position coverage state, persisted by the caller (runtime
    checkpoint) and advanced on every batch, exit or not."""
    return {"last_msc": fill_msc, "ticks": 0, "max_gap_ms": 0, "query_failures": 0}


def first_barrier_hit(ticks, pos, cov):
    """Advance `cov` with this batch (ticks before the fill ignored) and
    return the first executable barrier touch, or None. Buy exits at bid,
    sell at ask. Invariant to how identical chronology is split in batches.
    -> (why, px, msc, coverage_summary)"""
    for t in ticks:
        if t["time_msc"] < pos["t_fill_msc"]:
            continue
        gap = t["time_msc"] - cov["last_msc"]
        cov["ticks"] += 1; cov["max_gap_ms"] = max(cov["max_gap_ms"], gap); cov["last_msc"] = t["time_msc"]
        if pos["dir"] == 1:
            if t["bid"] <= pos["sl"]: return "sl", t["bid"], t["time_msc"], coverage_summary(cov)
            if t["bid"] >= pos["tp"]: return "tp", pos["tp"], t["time_msc"], coverage_summary(cov)
        else:
            if t["ask"] >= pos["sl"]: return "sl", t["ask"], t["time_msc"], coverage_summary(cov)
            if t["ask"] <= pos["tp"]: return "tp", pos["tp"], t["time_msc"], coverage_summary(cov)
    return None, None, None, coverage_summary(cov)


def coverage_summary(cov):
    return {"ticks": cov["ticks"], "max_gap_ms": cov["max_gap_ms"], "query_failures": cov["query_failures"],
            "certified": cov["max_gap_ms"] <= MAX_TICK_GAP_MS and cov["query_failures"] == 0,
            "basis": "tick spacing <= 5 s is a heuristic for continuity, not proof the server returned every tick; retrieval failures counted apart"}


def bar_ambiguity(pos, bar):
    """When tick coverage is NOT certified, what a BID-side bar can say.
    Returns None (bar touches neither barrier on the bid side) or a dict with
    sorted numeric bounds and provenance. Sell barriers execute at ask, which
    bid extrema cannot certify - said so in 'provenance'."""
    h, l = float(bar["high"]), float(bar["low"])
    if pos["dir"] == 1:
        hit_sl, hit_tp = l <= pos["sl"], h >= pos["tp"]
    else:
        hit_sl, hit_tp = h >= pos["sl"], l <= pos["tp"]
    if not (hit_sl or hit_tp):
        return None
    cands = []
    if hit_sl: cands.append(pos["sl"])
    if hit_tp: cands.append(pos["tp"])
    if hit_sl and hit_tp:
        status = "ambiguous"
    else:
        status = "sl_bar" if hit_sl else "tp_bar"
    mult = pos["lot"] * pos.get("contract_size", 1.0)
    pnls = sorted((px - pos["entry"]) * pos["dir"] * mult for px in cands)
    return {"status": status, "pnl_lo": pnls[0], "pnl_hi": pnls[-1],
            "provenance": "bid_extrema" + ("_sell_barrier_at_ask_uncertified" if pos["dir"] == -1 else ""),
            "cost_note": "gross; commission unknown; swap not applied"}


def missing_bars(last_bar, bars):
    """All closed bars after the watermark, chronological."""
    return sorted((b for b in bars if int(b["time"]) > last_bar), key=lambda b: int(b["time"]))


def rollover_exposure(t_fill, t_close):
    """Hold time and UTC-day boundaries crossed (swap exposure, not applied)."""
    hold = max(0.0, t_close - t_fill)
    days = int(t_close // 86400) - int(t_fill // 86400)
    return {"hold_s": round(hold, 1), "utc_days_crossed": days, "swap_applied": False,
            "swap_exposure_proxy_clear": days == 0,
            "rollover_note": "UTC-day proxy; the broker's dated rollover convention is not verified",
            "net_validated": False}
