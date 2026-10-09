"""Pure logic of the reference ledger (ChatGPT review 4) - no MT5, no I/O,
so every rule here is unit-tested in lab/test_reference_ledger.py.

Ledger = append-only JSONL. Row phases: start, restart, entry, close,
blocked, gap, quarantine. event_id is causal (feed:strategy:bar:dir:kind).
Lifecycle: an event_id with ANY row is final, except entry -> close (once).
Closed ids never reopen; at most one open entry; malformed or inconsistent
input quarantines the stream instead of being skipped."""
import json, math

RECORDING_VERSION = "rec-2"
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
            st["open"][ev] = r
        elif ph == "close":
            if "close" in ph_seen:
                st["errors"].append((i, "duplicate_close", ev)); continue
            if "entry" not in ph_seen:
                st["errors"].append((i, "close_without_entry", ev)); continue
            st["open"].pop(ev, None); st["closed"].add(ev)
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
    """Validated closed outcomes in close order for the state controllers:
    (event_id, dir, gross pnl). Ambiguous or uncovered closes are EXCLUDED and
    counted, so a state is never built on an invented number."""
    used, excluded = [], 0
    entries = {r["event_id"]: r for r in st["rows"] if r["phase"] == "entry"}
    for r in st["rows"]:
        if r["phase"] != "close":
            continue
        if r.get("exit_why") == "ambiguous" or not r.get("ticks_ok", False):
            excluded += 1; continue
        e = entries.get(r["event_id"])
        if e is None:
            excluded += 1; continue
        used.append((r["event_id"], e["dir"], float(r["pnl_usd_gross"])))
    return used, excluded


# ---------------------------------------------------------------- chronology
def tick_ok(t):
    b, a = t["bid"], t["ask"]
    return (isinstance(b, (int, float)) and isinstance(a, (int, float))
            and math.isfinite(b) and math.isfinite(a) and b > 0 and a >= b)


def ordered_new_ticks(ticks, watermark_msc):
    """Ticks strictly after the watermark, in (msc, arrival) order, invalid
    ones dropped and counted. -> (list, dropped)"""
    out, dropped = [], 0
    for i, t in enumerate(ticks):
        if t["time_msc"] <= watermark_msc:
            continue
        if not tick_ok(t):
            dropped += 1; continue
        out.append((t["time_msc"], i, t))
    out.sort(key=lambda x: (x[0], x[1]))
    return [t for _, _, t in out], dropped


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


def first_barrier_hit(ticks, pos):
    """First executable barrier touch in chronological order, ticks before
    the fill ignored. Buy exits at bid, sell exits at ask.
    -> (why, px, msc, coverage) ; coverage = {ticks, max_gap_ms, certified}"""
    last = pos["t_fill_msc"]; max_gap = 0; n = 0
    for t in ticks:
        if t["time_msc"] < pos["t_fill_msc"]:
            continue
        n += 1; max_gap = max(max_gap, t["time_msc"] - last); last = t["time_msc"]
        cov = {"ticks": n, "max_gap_ms": max_gap, "certified": max_gap <= MAX_TICK_GAP_MS}
        if pos["dir"] == 1:
            if t["bid"] <= pos["sl"]: return "sl", t["bid"], t["time_msc"], cov
            if t["bid"] >= pos["tp"]: return "tp", pos["tp"], t["time_msc"], cov
        else:
            if t["ask"] >= pos["sl"]: return "sl", t["ask"], t["time_msc"], cov
            if t["ask"] <= pos["tp"]: return "tp", pos["tp"], t["time_msc"], cov
    return None, None, None, {"ticks": n, "max_gap_ms": max_gap, "certified": max_gap <= MAX_TICK_GAP_MS}


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
            "net_validated": days == 0}
