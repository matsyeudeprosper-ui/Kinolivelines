"""Standalone ENTRY-STUDY manifest (review 14): everything the delayed-recovery-entry
replay depends on, hashed, so the untouched-period test runs the frozen implementation.
    python entry_study_manifest.py          -> review/entry_study_manifest.json (status DRAFT until the lead confirms)
"""
import json, hashlib, os, time, sys
ROOT = r"C:\Projects\KinoliveLines"
def h(rel): return hashlib.sha256(open(os.path.join(ROOT, rel), "rb").read()).hexdigest()[:16]
sys.argv = ["x"]; sys.path.insert(0, os.path.join(ROOT, "study")); import dev_dataset
_s, R, META = dev_dataset.load("b")
tman = json.load(open(os.path.join(ROOT, "study", "ticks", "manifest.json")))
cm = json.load(open(os.path.join(ROOT, "review", "compte_frozen_manifest.json"), encoding="utf-8"))
man = {
  "study": "delayed recovery MAIN entry - three-arm chronological tick engine",
  "status": "DRAFT",
  "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "frozen_at": None,
  "sources": {k: h(k) for k in ["study/tick_engine.py", "study/tick_engine_stats.py", "study/manifest_runner.py", "study/dev_dataset.py", "study/fetch_ticks.py",
                                "live/lab/harness.py", "live/structure_bos_bot.py", "live/owl_package.py", "live/lab/test_tick_engine.py", "review/compte_frozen_manifest.json"]},
  "development_data": {"bars": {"file": "study/dev_bars_2026-10-09b.npz", "sha256": META["sha256"], "first_bar": int(R["time"][0]), "closed_bar_cutoff": int(META["closed_bar_cutoff"])},
                        "ticks": {"manifest": "study/ticks/manifest.json", "days": len(tman["days"]), "total": sum(v.get("n", 0) for v in tman["days"].values()),
                                  "per_day_sha256": {k: v.get("sha256") for k, v in tman["days"].items()}, "window_ms": [int(R["time"][0]) * 1000, int(META["closed_bar_cutoff"]) * 1000]}},
  "opportunity_generation": "harness.simulate on closed M1 bars with OPPHOOK (every engine signal: t, d, stop, close, flip, awake, nervosity, movement count, level) and BARHOOK (protected-dot touch, bar nervosity); kill off for the stream; identical stream for all arms",
  "package_mapping": {"source": "manifest_runner.effective_cfg over compte_frozen_manifest.json package_regimes (live-order limits, strict field coverage)",
                      "regimes": {"infinity": 175.70, "u224016179": 267.42, "bos": 360.37, "reference_uncapped": 1000.0},
                      "balances_note": "development balances; the untouched-period run records each account's balance at the FROZEN line",
                      "package_regimes": cm["arms"]["baseline"]["package_regimes"]},
  "arms": {"baseline": "frozen package, market order at the signal",
           "delayed": "in debt (> $0.50) the MAIN waits at the recovery midpoint of the setup frozen at the signal quote (original stop/target/lot); one pending setup; no other signal while waiting; cancelled with a missed winner when the target prints first on the exit side; cancelled (no order) when the stop is breached on the trigger quote",
           "half_main": "original-entry MAIN at half lot in debt, floored 0.01 (control)"},
  "quote_model": {"side": "buy fills/adds at ask, exits at bid; sell mirror", "spread": "embedded in bid/ask", "drag_per_0_02_lot": [0.0, 0.35], "nominated_cost_basis": 0.35,
                  "invalid_quotes": "bid <= 0, ask < bid, non-finite dropped and counted"},
  "delays_ms": {"signal_processing": 1000, "trigger_to_execution": 1000},
  "execution_rules": {"main": "fill at the first tick >= trigger + 1 s; broker geometry at the fill quote (stop beyond the exit quote, target not reached) else reject; lots/limits/caps revalidated at the fill quote in the live enter() order",
                      "adds": "funded and reserved at the actual midpoint trigger tick (debt, jar, streak, that bar's nervosity; harness arithmetic); filled at the next executable quote after 1 s; rejected when the parent is stopped/targeted on the fill quote; exit with the main",
                      "barriers": "first tick whose exit side crosses; a tick through both = stop", "pending": "see arms.delayed", "end_of_window": "open positions marked at the last in-window quote; pending counted"},
  "gap_treatment": {"flag_ms": 5000, "unresolved_ms": 30000, "rule": "largest incoming gap per pending/open state recorded; > 30 s flags the trade (none in development)"},
  "metrics": ["net", "closed-trade DD", "MTM DD with open exposure", "trades", "wins", "MAIN/add attribution", "main risk", "later half", "missed winners", "wait", "skipped signals", "rejects", "kills", "gap flags"],
  "uncertainty": "paired exact-horizon block bootstrap over the dataset calendar (5-day nominated, 3/10 sensitivities, seed 7, 3000); conditional on the realised paths; rows share one history",
  "prohibited": ["parameter search", "changing delays, gap rules, trigger level or arms after FROZEN", "reselecting the primary regime after results", "extending or shortening the horizon after inspecting P&L", "live deployment on development evidence"],
}
out = os.path.join(ROOT, "review", "entry_study_manifest.json")
json.dump(man, open(out, "w", encoding="utf-8"), indent=1)
print("written", out, "sources", man["sources"])
