"""Read the per-trade journals (bos_journal*.csv) written by
structure_bos_bot.py since 2026-09-24 and break results down by the
market context the bot actually used at entry: nervosity, movement
count, storm flag, kind (FLIP-BOS/TOUCH/INT), account.

Owner 2026-09-24: "we need to record ATR, nervosity, movement... so with
more data we can figure out what works better." This is the "figure out"
half - the journal itself is written live by the bot, this just reads it.

Expect THIN results for a while - the journal only started 2026-09-24,
so early runs of this script will have few rows. That's expected, not a
bug; re-run it as real trades accumulate.

    python review/journal_report.py
"""
import csv
import glob
import os
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)


def load_all():
    rows = []
    for f in glob.glob(os.path.join(LIVE, "bos_journal*.csv")):
        with open(f, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("outcome") in ("WIN", "LOSS", "FLAT"):
                    r["_file"] = os.path.basename(f)
                    rows.append(r)
    return rows


def fnum(r, k):
    v = r.get(k)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def summarize(rows, label):
    if not rows:
        print(f"  {label:<28} (no rows yet)")
        return
    n = len(rows)
    wins = sum(1 for r in rows if r["outcome"] == "WIN")
    pnls = [fnum(r, "profit_usd") for r in rows if fnum(r, "profit_usd") is not None]
    net = sum(pnls) if pnls else 0.0
    print(f"  {label:<28} n={n:<4} win%={100*wins/n:5.1f}  net=${net:+.2f}")


def main():
    rows = load_all()
    print(f"\n  {len(rows)} closed trades with journal rows found "
          f"(feature started 2026-09-24 - will be thin at first)\n")
    if not rows:
        print("  Nothing to break down yet. Re-run once real trades "
              "have closed since deployment.\n")
        return

    print("  BY ACCOUNT")
    accts = sorted(set(r.get("account", "") for r in rows))
    for a in accts:
        summarize([r for r in rows if r.get("account") == a], a or "(unknown)")

    print("\n  BY KIND (entry type)")
    kinds = sorted(set(r.get("kind", "") for r in rows if r.get("kind")))
    for k in kinds:
        summarize([r for r in rows if r.get("kind") == k], k)

    print("\n  BY NERVOSITY BAND (vol_now/vol_ref at entry)")
    bands = [("calme <1.00", lambda v: v < 1.00),
             ("soutenu 1.00-1.30", lambda v: 1.00 <= v < 1.30),
             ("rapide 1.30-1.85", lambda v: 1.30 <= v < 1.85),
             ("tres rapide >=1.85", lambda v: v >= 1.85)]
    with_nerv = [r for r in rows if fnum(r, "nervosity") is not None]
    for lab, f in bands:
        bucket = [r for r in with_nerv if f(fnum(r, "nervosity"))]
        summarize(bucket, lab)

    print("\n  BY MOVEMENT COUNT AT ENTRY (moves_2h main / int_brk_1h internal)")
    with_mv = [r for r in rows if fnum(r, "movement_count") is not None]
    counts = sorted(set(int(fnum(r, "movement_count")) for r in with_mv))
    for c in counts:
        summarize([r for r in with_mv if int(fnum(r, "movement_count")) == c],
                  f"{c} move(s)")

    print("\n  BY STORM FLAG (first trade after nervosity dropped below 1.85x)")
    for s in ("0", "1"):
        summarize([r for r in rows if r.get("storm") == s],
                  "storm=" + s)

    print("\n  MAIN vs INTERNAL")
    for iv, lab in (("False", "main"), ("True", "internal")):
        summarize([r for r in rows if r.get("internal") == iv], lab)
    print()


if __name__ == "__main__":
    main()
