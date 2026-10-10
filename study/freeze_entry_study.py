"""FREEZE the entry study (review 17, item 4): rebuild + hash the isolated bundle, then stamp the
manifest FROZEN with fixed balances (each account's balance at this moment, read from the nest's
wealth files - read-only, no credentials), the nominated costs, the initialisation, the arms incl.
the selected challenger, and a PROSPECTIVE 42-day window that starts AFTER this freeze (the next
whole 10-minute boundary at least two minutes ahead, so the freeze commit precedes it; the actual
timestamps are recorded; nothing is backdated).

    python freeze_entry_study.py            (refuses if the fixture verification file is missing or failed)
"""
import os, sys, json, time, subprocess
ROOT = r"C:\Projects\KinoliveLines"; MAN = os.path.join(ROOT, "review", "entry_study_manifest.json")
VERIFY = os.path.join(ROOT, "study", "frozen_entry_study", "frozen_fixture_verify.json")
WEALTH = {"infinity": "infinity", "u224016179": "u224016179", "bos": "bos", "reference_uncapped": "u477508138"}


def main():
    v = json.load(open(VERIFY)) if os.path.exists(VERIFY) else None
    if not v or not v.get("all_checks_pass"):
        raise SystemExit("the fixture verification (frozen_fixture_verify.json) is missing or did not pass - not freezing")
    subprocess.check_call([sys.executable, os.path.join(ROOT, "study", "build_frozen_bundle.py")])
    man = json.load(open(MAN, encoding="utf-8"))
    now = int(time.time()); frozen_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    start = ((now + 120) // 600 + 1) * 600; end = start + 42 * 86400
    bal = {}; src = {}
    for reg, uid in WEALTH.items():
        p = os.path.join(ROOT, "live", "lab", "wealth", uid + ".json"); d = json.load(open(p, encoding="utf-8"))
        bal[reg] = round(float(d["balance"]), 2); src[reg] = {"nest_id": uid, "file": "live/lab/wealth/%s.json" % uid, "read_at": frozen_at}
    man.update({"status": "FROZEN", "frozen_at": frozen_at, "scored_start": start, "scored_end": end,
                "scored_utc": [time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(start)), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(end))],
                "balances_at_freeze": bal, "balances_source": src, "balances_dev": man["package_mapping"]["regimes"],
                "costs": {"drags_per_0_02_lot": [0.0, 0.35], "nominated": 0.35, "spread": "the quote at the fill (bid/ask ticks)"},
                "arms_scored": {"baseline": "frozen package snapshot, market order at the signal (tick_engine.run_regime)",
                                "delayed": "recovery-only delayed MAIN - the original comparator (tick_engine.run_regime)",
                                "half_main": "original-entry MAIN at half lot in debt, floored 0.01 - control (tick_engine.run_regime)",
                                "cell:immediate|current|cap_on": "the baseline through tick_engine_matrix.run_cells - engine-identity check",
                                "cell:delay_always|all_bos|cap_on": "the SELECTED CHALLENGER (review 15/16): midpoint delay for EVERY eligible MAIN entry, every otherwise-eligible confirmed MAIN BOS admitted while in debt, package daily cap kept"},
                "challenger_checks": "every run: delayed_out_debt > 0 (delay outside recovery), debt_gate == 0 (no eligible recovery BOS refused), policy cap on and cap_waived_off == 0 (cap retained); engine identity: matrix baseline == engine baseline",
                "baseline_note": "the baseline is the EARLIER package snapshot (compte_frozen_manifest.json, pinned and hashed in the bundle), NOT today's live configuration (the live bots since 2026-10-10 carry the pullback-direction/trend gate, the day-cap waiver switch and the sticky pullback chain - none of that is in this study)",
                "scope": "research / demo only - nothing here changes a live bot, and the reference demo is never changed to match the replay",
                "fixture_verification": {"file": "study/frozen_entry_study/frozen_fixture_verify.json", "generated_at": v["generated_at"], "all_checks_pass": v["all_checks_pass"],
                                         "reproduced": {k: c.get("reproduced") for k, c in v["checks"].items()}},
                "forward_data": {"ticks": "study/ticks_forward/ (daily task OwlForwardTicks 03:10 local, std BTCUSDm account)", "bars": "fetched at the end of the window from the same terminal; warm-up = bars before scored_start"},
                "reporting": "at scored_end (and interim status only): win rate, profit factor, net, closed DD (cc_dd), floating DD (mtm_dd), trade counts, missed winners, coverage - per arm, per regime, both cost bases; the two prereg checkpoints; no retuning"})
    json.dump(man, open(MAN, "w", encoding="utf-8"), indent=1)
    print("FROZEN at", frozen_at, "| scored", man["scored_utc"], "| balances", bal)


if __name__ == "__main__":
    main()
