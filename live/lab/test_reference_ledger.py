"""Ledger lifecycle / chronology / batch-invariance tests (ChatGPT reviews 4-5).
python test_reference_ledger.py"""
import itertools, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import reference_ledger_lib as L

fails = []
def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)
J = lambda **k: json.dumps(k)
E = lambda ev, d=1, **o: J(**{**dict(phase="entry", event_id=ev, dir=d, entry=100.0, sl=90.0, tp=108.0, lot=0.02, t_fill_msc=1000), **o})
C = lambda ev, pnl=1.0, ok_=True, why="tp", **o: J(**{**dict(phase="close", event_id=ev, exit=108.0, t_close=2.0, pnl_usd_gross=pnl, ticks_ok=ok_, exit_why=why), **o})
T = lambda ms, b, a: {"time_msc": ms, "bid": b, "ask": a}
POS = {"dir": 1, "entry": 100.0, "sl": 90.0, "tp": 108.0, "lot": 0.02, "t_fill_msc": 1000}

# ---- lifecycle in the parser
st = L.parse_ledger([E("a"), E("a")]); ok("duplicate entry flagged", any(e[1] == "duplicate_entry" for e in st["errors"]))
st = L.parse_ledger([E("a"), C("a"), C("a")]); ok("duplicate close flagged", any(e[1] == "duplicate_close" for e in st["errors"]))
st = L.parse_ledger([E("a"), C("a"), E("a")]); ok("entry after close flagged", any(e[1] == "entry_after_close" for e in st["errors"]))
st = L.parse_ledger([J(phase="blocked", event_id="x", reason="r"), E("x")]); ok("entry after blocked flagged (review 5)", any(e[1] == "entry_after_blocked" for e in st["errors"]) and not st["open"])
st = L.parse_ledger([E("a"), E("b")]); ok("two open ids flagged", any(e[1] == "multiple_open" for e in st["errors"]))
st = L.parse_ledger([E("a"), C("a"), '{"phase": "entry", "event_id": "b"']); ok("truncated tail flagged", any(e[1] == "malformed" for e in st["errors"]) and L.reconcile(st, {}) is None)
st = L.parse_ledger([E("a"), "garbage", C("a")]); ok("corrupt middle flagged", any(e[1] == "malformed" for e in st["errors"]))
st = L.parse_ledger([E("a", sl=float("nan"))]); ok("entry with non-finite field flagged", any(e[1] == "entry_schema" for e in st["errors"]))
st = L.parse_ledger([J(phase="entry", event_id="old", dir=-1, entry=100.0, sl=110.0, tp=92.0, lot=0.02, t_fill=1791554460.5)])
ok("rec-1 entry (no t_fill_msc, no recording_version) accepted with the field derived", not st["errors"] and st["open"]["old"]["t_fill_msc"] == 1791554460500)
st = L.parse_ledger([E("a", d=2)]); ok("entry with bad dir flagged", any(e[1] == "entry_schema" for e in st["errors"]))
st = L.parse_ledger([E("a"), C("a", pnl=float("inf"))]); ok("close with non-finite pnl flagged", any(e[1] == "close_schema" for e in st["errors"]))
st = L.parse_ledger([E("a")]); ok("entry_allowed refuses a seen event", not L.entry_allowed(st, "a"))
st = L.parse_ledger([E("a"), C("a")]); ok("closed id cannot reopen", not L.entry_allowed(st, "a") and not st["open"])
st = L.parse_ledger([E("a")]); rt = {"open_event": None}; pos = L.reconcile(st, rt); ok("ledger restores the open entry the checkpoint missed", pos is not None and rt["open_event"] == "a")
# ---- outcomes: unresolved = gap, not omission
st = L.parse_ledger([E("a"), C("a", 2.0), E("b"), C("b", -1.0, ok_=False), E("c"), C("c", 3.0, why="ambiguous")])
outs = L.closed_outcomes(st); ok("all closes returned with a resolved flag", [o[3] for o in outs] == [True, False, False] and len(outs) == 3)
rep = L.exclusion_report(outs); ok("exclusion report counts", rep["unresolved"] == 2 and rep["resolved"] == 1)
# ---- chronology
ticks = [T(900, 99, 100), T(1100, 101, 102), T(1200, 103, 104)]
t, why = L.fill_tick(ticks, 1000); ok("fill = first tick AT/AFTER the decision", t is not None and t["time_msc"] == 1100)
t, why = L.fill_tick([T(900, 99, 100)], 1000); ok("no tick after decision -> no fill", t is None)
ok("fill age check", L.fill_age_ok(1100, 1000, 3000) and not L.fill_age_ok(1100, 1000, 9000))
ok("wrong-side stop rejected", not L.stop_side_ok(1, 100, 101) and not L.stop_side_ok(-1, 100, 99) and L.stop_side_ok(1, 100, 90))
ok("nan/zero/inverted ticks rejected", not L.tick_ok(T(1, float("nan"), 1)) and not L.tick_ok(T(1, 0, 1)) and not L.tick_ok(T(1, 101, 100)))
seq = [T(900, 80, 81), T(1500, 95, 96), T(2000, 89, 90), T(2500, 110, 111)]
cov = L.new_coverage(1000); why, px, msc, cs = L.first_barrier_hit(seq, POS, cov)
ok("SL first in chronology beats a later TP; pre-fill tick ignored", why == "sl" and msc == 2000 and cs["ticks"] == 2)
sell = dict(POS, dir=-1, sl=110.0, tp=92.0); why, px, msc, cs = L.first_barrier_hit([T(1500, 109.5, 110.2)], sell, L.new_coverage(1000)); ok("sell barriers judged at ASK", why == "sl" and px == 110.2)
# ---- BATCH INVARIANCE (review 5's fixture): fill 1000, ticks 2000..6000, TP at 7000
fx = [T(2000, 100, 101), T(3000, 100, 101), T(4000, 100, 101), T(5000, 100, 101), T(6000, 100, 101), T(7000, 108.5, 109)]
def run_batches(batches):
    cov = L.new_coverage(1000); res = None
    for b in batches:
        why, px, msc, cs = L.first_barrier_hit(b, POS, cov)
        if why: res = (why, px, msc, cs["max_gap_ms"], cs["ticks"], cs["certified"]); break
    return res
whole = run_batches([fx])
parts_ok = True
for cuts in itertools.product([0, 1], repeat=len(fx) - 1):     # every partition of the 6 ticks
    batches, cur = [], [fx[0]]
    for c, t in zip(cuts, fx[1:]):
        if c: batches.append(cur); cur = [t]
        else: cur.append(t)
    batches.append(cur)
    if run_batches(batches) != whole:
        parts_ok = False; break
ok("review-5 fixture: all 32 partitions give the same outcome and coverage", parts_ok and whole[0] == "tp" and whole[3] == 1000 and whole[5] is True)
gap = [T(2000, 100, 101), T(9000, 100, 101), T(9100, 100, 101), T(9200, 100, 101), T(9300, 108.5, 109)]
r1 = run_batches([gap]); r2 = run_batches([[gap[0]], [gap[1]], gap[2:]])
ok("a true middle gap is preserved through later dense ticks, in any batching", r1 == r2 and r1[3] == 7000 and r1[5] is False)
cov = L.new_coverage(1000); L.first_barrier_hit(fx[:3], POS, cov); saved = json.loads(json.dumps(cov))   # restart halfway
why, px, msc, cs = L.first_barrier_hit(fx[3:], POS, saved); ok("restart halfway through an open trade keeps coverage", why == "tp" and cs["max_gap_ms"] == 1000 and cs["ticks"] == 6)
# ---- watermark with several ticks at the same millisecond
same = [T(1000, 1, 2), T(1000, 1, 2), T(1000, 1, 2), T(1001, 1, 2)]
new, dropped, mk, n_at = L.ordered_new_ticks(same[:2], 0, 0); ok("first batch: mark at 1000 with 2 seen", mk == 1000 and n_at == 2 and len(new) == 2)
new, dropped, mk, n_at = L.ordered_new_ticks(same, mk, n_at); ok("late arrival sharing the watermark ms is new, earlier ones are not", [t["time_msc"] for t in new] == [1000, 1001] and mk == 1001 and n_at == 1)
new, dropped, mk2, n2 = L.ordered_new_ticks([T(1200, 1, 2), T(1100, 1, 2), T(1000, 1, 2), T(1300, float("inf"), 2)], 1000, 1)
ok("ticks after the watermark, ordered, invalid dropped", [t["time_msc"] for t in new] == [1100, 1200] and dropped == 1)
# ---- ambiguity, bars, rollover
amb = L.bar_ambiguity({"dir": -1, "entry": 100.0, "sl": 110.0, "tp": 92.0, "lot": 0.02, "contract_size": 1.0}, {"high": 111, "low": 91})
ok("sell ambiguity: bounds sorted, ask-side caveat recorded", amb["status"] == "ambiguous" and amb["pnl_lo"] < amb["pnl_hi"] and "uncertified" in amb["provenance"])
ok("bar touching neither barrier -> None", L.bar_ambiguity(POS, {"high": 105, "low": 95}) is None)
ok("missed bars chronological, watermark excluded", [b["time"] for b in L.missing_bars(120, [{"time": 180}, {"time": 60}, {"time": 120}, {"time": 240}])] == [180, 240])
r = L.rollover_exposure(86000, 90000); ok("rollover: proxy flag, net never validated while costs unknown", r["utc_days_crossed"] == 1 and r["swap_exposure_proxy_clear"] is False and r["net_validated"] is False)
r = L.rollover_exposure(1000, 2000); ok("same-day: proxy clear, net still not validated", r["swap_exposure_proxy_clear"] is True and r["net_validated"] is False)
print("\nRESULT:", "ALL PASS" if not fails else "FAILED: " + ", ".join(fails)); sys.exit(1 if fails else 0)
