"""Quick-glance forward tracker for the minute-of-hour pattern (owner
2026-09-24: "forward track it closely... every time we are seeing the
pattern confirming you speak about it").

Owner, same day, after seeing the historical breakdown split by entry
type: "the confirmed BOS entries is what we are concerned about." Plain
"BOS" entries (continuation breaks - NOT FLIP-BOS, TOUCH, or INT, which
are separate entry types the bot also uses) are the primary view here;
"all kinds pooled" stays as secondary context only, never the headline.

Reads the live bos_journal<acct>.csv files (deployed 2026-09-24 -
records entry_time_utc AND kind for every real closed trade going
forward) and reports win/loss/net by minute-of-hour range. Same data
source used for reporting trades, so "forward-tracked" means the live
record itself, not a side-channel that could drift from what's real.

    python review/minute_pattern_tracker.py
"""
import csv
import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)


def load():
    rows = []
    for f in glob.glob(os.path.join(LIVE, "bos_journal*.csv")):
        with open(f, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("outcome") in ("WIN", "LOSS") and r.get("entry_time_utc"):
                    try:
                        minute = int(r["entry_time_utc"][14:16])
                    except (ValueError, IndexError):
                        continue
                    r["_minute"] = minute
                    r["_file"] = os.path.basename(f)
                    rows.append(r)
    return rows


def summarize(rows, label, width=14):
    if not rows:
        print(f"    {label:<{width}} (no trades yet)")
        return
    n = len(rows)
    wins = sum(1 for r in rows if r["outcome"] == "WIN")
    net = sum(float(r.get("profit_usd") or 0) for r in rows)
    print(f"    {label:<{width}} n={n:<4} win%={100*wins/n:5.1f}  net=${net:+.2f}")


def main():
    rows = load()
    print(f"\n  {len(rows)} real journal trades since the journal started "
          f"2026-09-24 - will be thin for a while\n")

    bos = [r for r in rows if r.get("kind") == "BOS"]
    print(f"  ===== CONFIRMED BOS ENTRIES ONLY ({len(bos)} trades) - "
          f"the one we care about =====")
    summarize([r for r in bos if r["_minute"] < 30], "minute 0-29")
    summarize([r for r in bos if r["_minute"] >= 30], "minute 30-59")
    accts = sorted(set(r.get("account", "") for r in bos))
    for a in accts:
        arows = [r for r in bos if r.get("account") == a]
        print(f"\n    {a}")
        summarize([r for r in arows if r["_minute"] < 30], "minute 0-29", 16)
        summarize([r for r in arows if r["_minute"] >= 30], "minute 30-59", 16)

    print(f"\n  ===== all entry kinds pooled ({len(rows)} trades) - "
          f"context only, not the headline =====")
    summarize([r for r in rows if r["_minute"] < 30], "minute 0-29")
    summarize([r for r in rows if r["_minute"] >= 30], "minute 30-59")
    for kind in sorted(set(r.get("kind", "") for r in rows if r.get("kind"))):
        krows = [r for r in rows if r.get("kind") == kind]
        print(f"\n    kind={kind} ({len(krows)} trades)")
        summarize([r for r in krows if r["_minute"] < 30], "minute 0-29", 16)
        summarize([r for r in krows if r["_minute"] >= 30], "minute 30-59", 16)
    print()


if __name__ == "__main__":
    main()
