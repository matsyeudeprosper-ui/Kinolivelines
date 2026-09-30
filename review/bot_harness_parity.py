"""Does the backtest still describe the bot that is actually running?

This exists because of what happened on 2026-09-30. The live bot took
internal-structure entries for weeks; `lab/harness.py` had never modelled
one. Nothing noticed, because nothing was looking. The proof page compared a
backtest of one strategy against live results of another, and the only
reason it surfaced is that the owner asked an unrelated question.

That class of drift is cheap to detect and expensive to miss, so this checks
it directly, on facts rather than on opinions:

  1. RULE FLAGS - every switch the bot reads out of its package is compared
     with the dial the harness would use. A rule the bot has and the harness
     does not know about is the exact failure that happened.
  2. TRADE KINDS - every kind of trade in the live journals is checked
     against the kinds the harness can produce. A kind the harness cannot
     produce means the backtest is missing a trade type again.
  3. ENTRY RATE - trades per day, live against simulated, over the same
     window. An order-of-magnitude gap means one of them is not doing what
     the other does, whatever the flags say.

It prints a verdict and exits non-zero on a mismatch, so it can be wired to
the nightly researcher later.

Run:  python review/bot_harness_parity.py
"""
import collections
import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(os.path.dirname(HERE), "live")
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(LIVE, "lab"))

import harness as H            # noqa: E402
import owl_package as PK       # noqa: E402

# Package switches that change WHICH TRADES ARE TAKEN, and the harness dial
# that models each. None = the harness cannot express it, which is a finding.
RULE_MAP = {
    "internal_entries": "internal",
    "risk_fit_pct": "risk_fit",
    "max_risk_pct": "risk_pct",
    "nervosity": "nerv_gate",
    "day_cap": "day_cap",
    "kill_net": "kill_net",
    "jar": "jar",
    "base_lot": "lot",
    "scale_with_balance": "balance",
    # these three have no dial. That is only DRIFT when the live value
    # differs from what the harness silently assumes - recorded here so the
    # check reports a real risk instead of a scary-looking list.
    "max_trades_day": None,
    "movement": None,
    "debt_mode": None,
}
# what the harness hard-codes for the rules it cannot switch. A live value
# equal to this is equivalent, not drift.
ASSUMES = {
    "max_trades_day": [None],      # harness caps nothing
    "movement": [True],            # harness always applies the moves_2h gate
    "debt_mode": ["hwm"],          # harness debt/jar follows the high-water mark
}
ACCOUNTS = ("u224016179", "infinity", "expenses", "bos", "kino", "demo")
JOURNALS = ("bos_journal_valere.csv", "bos_journal_infinity.csv",
            "bos_journal.csv", "bos_journal_kino.csv",
            "bos_journal_demo.csv")
# the kinds the harness can produce today
HARNESS_KINDS = {"FLIP-BOS", "BOS", "CONT", "INT", ""}


def check_rules():
    print("1. RULE FLAGS the bot reads vs dials the harness has")
    cfg = H.cfg_of({})
    missing = []
    for key, dial in RULE_MAP.items():
        vals = set()
        for uid in ACCOUNTS:
            try:
                vals.add(repr(PK.for_account(uid).get(key)))
            except Exception:
                pass
        known = (dial in cfg) if dial else False
        if dial and known:
            tag = "ok"
        elif dial:
            tag = "DIAL MISSING"
            missing.append(key)
        else:
            ok_vals = {repr(v) for v in ASSUMES.get(key, [])}
            if vals and vals <= ok_vals:
                tag = "no dial, matches assumption"
            else:
                tag = "DRIFT: live value not assumed"
                missing.append(key)
        print(f"   {key:<22} -> harness {str(dial):<12} {tag:<14}"
              f" live values {sorted(vals)}")
    return missing


def check_kinds():
    print("")
    print("2. TRADE KINDS in the live journals vs kinds the harness produces")
    seen = collections.Counter()
    internal = 0
    for f in JOURNALS:
        p = os.path.join(LIVE, f)
        if not os.path.exists(p):
            continue
        for r in csv.DictReader(io.open(p, encoding="utf-8",
                                        errors="replace")):
            if (r.get("is_add") or "") == "True":
                continue
            seen[(r.get("kind") or "").strip()] += 1
            if (r.get("internal") or "").strip() == "True":
                internal += 1
    unknown = [k for k in seen if k not in HARNESS_KINDS]
    for k, n in seen.most_common():
        print(f"   {k or '(blank)':<12} {n:4d}  "
              f"{'ok' if k in HARNESS_KINDS else 'NOT IN HARNESS'}")
    print(f"   internal-flagged live trades: {internal}")
    return unknown


def check_rate():
    print("")
    print("3. ENTRY RATE, live vs simulated")
    T = H.real_entries()
    if not T:
        print("   no real entries in the journals - cannot compare")
        return []
    span_d = max(1.0, (T[-1]["t"] - T[0]["t"]) / 86400.0)
    live_rate = len(T) / span_d
    sym, R = H.bars()
    cfg = H.package_cfg("valere", {"balance": 270.75, "scale_ref": 230.0})
    sim = H.simulate(R, 7.0, cfg)
    sim_days = max(1.0, len(R) / 1440.0)
    sim_rate = sim["trades"] / sim_days
    ratio = sim_rate / live_rate if live_rate else 0
    print(f"   live      {len(T):4d} entries over {span_d:5.1f} d"
          f"  = {live_rate:5.2f}/day")
    print(f"   simulated {sim['trades']:4d} entries over {sim_days:5.1f} d"
          f"  = {sim_rate:5.2f}/day")
    print(f"   ratio sim/live: {ratio:.2f}x")
    return [] if 0.4 <= ratio <= 2.5 else ["entry rate"]


def main():
    print("BOT vs HARNESS parity -", H.ENGINE)
    print("")
    bad = []
    bad += [f"rule:{k}" for k in check_rules()]
    bad += [f"kind:{k}" for k in check_kinds()]
    bad += check_rate()
    print("")
    if bad:
        print("PARITY: DRIFT ->", ", ".join(bad))
        print("A 'NOT MODELLED' rule is not automatically a bug - some rules")
        print("cannot change which trades are taken. It IS a thing to look at")
        print("before quoting a backtest number as if it described the bot.")
    else:
        print("PARITY: OK - every rule the bot reads has a dial, every live")
        print("trade kind can be produced, entry rates agree.")
    json.dump({"engine": H.ENGINE, "drift": bad},
              open(os.path.join(HERE, "bot_harness_parity.json"), "w"),
              indent=1)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
