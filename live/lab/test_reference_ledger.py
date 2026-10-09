"""Ledger lifecycle / chronology tests (ChatGPT review 4).  python test_reference_ledger.py"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import reference_ledger_lib as L

fails = []
def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)
J = lambda **k: json.dumps(k)
E = lambda ev, d=1: J(phase="entry", event_id=ev, dir=d, entry=100.0, sl=90.0, tp=108.0, lot=0.02, t_fill_msc=1000)
C = lambda ev, pnl=1.0, ok_=True, why="tp": J(phase="close", event_id=ev, pnl_usd_gross=pnl, ticks_ok=ok_, exit_why=why)

# duplicate signal (same event entered twice) -> refused, error flagged
st = L.parse_ledger([E("a"), E("a")]); ok("duplicate entry flagged", any(e[1] == "duplicate_entry" for e in st["errors"]))
st = L.parse_ledger([E("a")]); ok("entry_allowed refuses a seen event", not L.entry_allowed(st, "a"))
# duplicate close
st = L.parse_ledger([E("a"), C("a"), C("a")]); ok("duplicate close flagged", any(e[1] == "duplicate_close" for e in st["errors"]))
# already-closed event repeated as a new entry -> never reopens
st = L.parse_ledger([E("a"), C("a"), E("a")]); ok("entry after close flagged", any(e[1] == "entry_after_close" for e in st["errors"]))
st = L.parse_ledger([E("a"), C("a")]); ok("closed id cannot reopen", not L.entry_allowed(st, "a") and not st["open"])
# blocked stays blocked
st = L.parse_ledger([J(phase="blocked", event_id="b", reason="storm")]); ok("blocked id is final", not L.entry_allowed(st, "b"))
# two open ids -> stream invalid
st = L.parse_ledger([E("a"), E("b")]); ok("two open ids flagged", any(e[1] == "multiple_open" for e in st["errors"]))
# crash after append, before checkpoint: ledger wins
st = L.parse_ledger([E("a")]); rt = {"open_event": None}; pos = L.reconcile(st, rt)
ok("ledger restores the open entry the checkpoint missed", pos is not None and rt["open_event"] == "a")
# truncated tail / corrupt middle -> quarantine, nothing silently continues
st = L.parse_ledger([E("a"), C("a"), '{"phase": "entry", "event_id": "b", "dir": 1']); ok("truncated tail flagged", any(e[1] == "malformed" for e in st["errors"]) and L.reconcile(st, {}) is None)
st = L.parse_ledger([E("a"), "garbage", C("a")]); ok("corrupt middle flagged", any(e[1] == "malformed" for e in st["errors"]))
# closed outcomes exclude ambiguous / uncertified
st = L.parse_ledger([E("a"), C("a", 2.0), E("b"), C("b", -1.0, ok_=False), E("c"), C("c", 3.0, why="ambiguous")])
used, exc = L.closed_outcomes(st); ok("ambiguous/uncertified closes excluded from states", [u[2] for u in used] == [2.0] and exc == 2)
# chronology: ticks before the decision never fill; stop side checked
T = lambda ms, b, a: {"time_msc": ms, "bid": b, "ask": a}
ticks = [T(900, 99, 100), T(1100, 101, 102), T(1200, 103, 104)]
t, why = L.fill_tick(ticks, 1000); ok("fill = first tick AT/AFTER the decision", t is not None and t["time_msc"] == 1100)
t, why = L.fill_tick([T(900, 99, 100)], 1000); ok("no tick after decision -> no fill", t is None and why == "no_tick_after_decision")
ok("fill age check", L.fill_age_ok(1100, 1000, 3000) and not L.fill_age_ok(1100, 1000, 9000))
ok("wrong-side stop rejected", not L.stop_side_ok(1, 100, 101) and not L.stop_side_ok(-1, 100, 99) and L.stop_side_ok(1, 100, 90))
ok("nan/zero/inverted ticks rejected", not L.tick_ok(T(1, float("nan"), 1)) and not L.tick_ok(T(1, 0, 1)) and not L.tick_ok(T(1, 101, 100)))
# first barrier hit in order: SL touched first wins even if TP crossed later
pos = {"dir": 1, "entry": 100.0, "sl": 90.0, "tp": 108.0, "lot": 0.02, "t_fill_msc": 1000}
seq = [T(900, 80, 81), T(1500, 95, 96), T(2000, 89, 90), T(2500, 110, 111)]
why, px, msc, cov = L.first_barrier_hit(seq, pos); ok("SL first in chronology beats a later TP; pre-fill tick ignored", why == "sl" and msc == 2000 and cov["ticks"] == 2)
why, px, msc, cov = L.first_barrier_hit([T(1500, 95, 96), T(9000, 110, 111)], pos); ok("a long unobserved gap is NOT certified", why == "tp" and cov["certified"] is False)
sell = dict(pos, dir=-1, sl=110.0, tp=92.0); why, px, msc, cov = L.first_barrier_hit([T(1500, 109.5, 110.2)], sell); ok("sell barriers judged at ASK", why == "sl" and px == 110.2)
# watermark ordering and dedup
new, dropped = L.ordered_new_ticks([T(1200, 1, 2), T(1100, 1, 2), T(1000, 1, 2), T(1300, float("inf"), 2)], 1000)
ok("ticks after the watermark, ordered, invalid dropped", [t["time_msc"] for t in new] == [1100, 1200] and dropped == 1)
# bar ambiguity bounds sorted numerically, sell provenance stated
amb = L.bar_ambiguity({"dir": -1, "entry": 100.0, "sl": 110.0, "tp": 92.0, "lot": 0.02, "contract_size": 1.0}, {"high": 111, "low": 91})
ok("sell ambiguity: bounds sorted, ask-side caveat recorded", amb["status"] == "ambiguous" and amb["pnl_lo"] < amb["pnl_hi"] and "uncertified" in amb["provenance"])
ok("bar touching neither barrier -> None", L.bar_ambiguity(pos, {"high": 105, "low": 95}) is None)
# missed bars replay in order
bars = [{"time": 180}, {"time": 60}, {"time": 120}, {"time": 240}]
ok("missed bars chronological, watermark excluded", [b["time"] for b in L.missing_bars(120, bars)] == [180, 240])
# rollover exposure
r = L.rollover_exposure(86000, 90000); ok("rollover crossing flagged, net not validated", r["utc_days_crossed"] == 1 and not r["net_validated"])
print("\nRESULT:", "ALL PASS" if not fails else "FAILED: " + ", ".join(fails)); sys.exit(1 if fails else 0)
