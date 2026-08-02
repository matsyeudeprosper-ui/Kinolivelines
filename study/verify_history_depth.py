"""Integrity check on the census's EXACT history labels.

WHY THIS EXISTS
The census asks MetaTrader for deep D1 history and records the first bar it gets
back as the symbol's history start. That is only trustworthy if the terminal had
actually finished building its D1 cache for that symbol when the request landed.

It had not, for some symbols. EURCHFm is the clearest case: the census recorded
403 D1 bars starting 2025-04-18, yet the terminal's own on-disk minute-history
cache holds files for 2021 through 2026. Minute data from 2021 cannot coexist
with a genuine D1 history that begins in 2025 - so the returned series was a
partially-built cache, not the symbol's real depth.

WHAT THIS DOES
Compares, for every symbol the census labelled EXACT, the year of the reported
first D1 bar against the earliest year present in the terminal's history cache
directory. If the cache reaches further back than the reported start, the
reported depth is a LOWER BOUND, not the truth, and the row is reflagged.

This reads only the filesystem. It issues no terminal calls, so it cannot
compete with the running bot for the terminal.

WHAT IT DOES NOT CHANGE
Only depth-of-history fields are affected. ATR(20) uses the most recent 20 bars
and is unaffected. Sizing, margin, notional, spread, swap and the risk/exposure
tests never touch history depth. The >= 250 bar adequacy test is unaffected for
any flagged symbol that already clears 250 bars on the short count, since the
true count can only be larger.

Understated history can only push a symbol DOWN the group A ranking (one of the
four rank inputs is "most history"), never falsely promote one - so the ranking
is conservative with respect to this defect, not inflated.
"""
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "results", "exness_feasibility_census.csv")
OUT = os.path.join(HERE, "results", "history_depth_audit.csv")

CACHE = os.path.join(
    os.environ.get("APPDATA", r"C:\Users\Administrator\AppData\Roaming"),
    "MetaQuotes", "Terminal", "D0E8209F77C8CF37AD8BF550E51FF075",
    "bases", "Exness-MT5Trial9", "history",
)

# A tiny year-file can be a stub with no usable bars; anything this size or above
# is real history. EURUSDm's genuine 2018 file is 53 KB, so the floor sits well
# below that.
MIN_REAL_BYTES = 20_000


def earliest_cache_year(symbol):
    d = os.path.join(CACHE, symbol)
    if not os.path.isdir(d):
        return None, 0
    years = []
    for fn in os.listdir(d):
        m = re.fullmatch(r"(\d{4})\.hcc", fn)
        if not m:
            continue
        if os.path.getsize(os.path.join(d, fn)) >= MIN_REAL_BYTES:
            years.append(int(m.group(1)))
    return (min(years) if years else None), len(years)


def main():
    if not os.path.isfile(CSV):
        sys.exit(f"census csv not found: {CSV}")
    if not os.path.isdir(CACHE):
        sys.exit(f"terminal history cache not found: {CACHE}")

    df = pd.read_csv(CSV)
    rows = []
    for _, r in df.iterrows():
        sym = r["symbol"]
        yr, nfiles = earliest_cache_year(sym)
        start = str(r.get("d1_start", "") or "")
        reported_yr = int(start[:4]) if re.match(r"\d{4}-", start) else None
        suspect = (
            r.get("history_depth") == "EXACT"
            and yr is not None
            and reported_yr is not None
            and yr < reported_yr
        )
        rows.append({
            "symbol": sym,
            "group": r.get("group"),
            "history_depth": r.get("history_depth"),
            "d1_bars": r.get("d1_bars"),
            "d1_start": start,
            "reported_start_year": reported_yr,
            "earliest_cache_year": yr,
            "cache_year_files": nfiles,
            "years_missing": (reported_yr - yr) if suspect else 0,
            "history_suspect": bool(suspect),
        })

    audit = pd.DataFrame(rows)
    audit.to_csv(OUT, index=False)

    # Write the finding back into the census itself. A reader of the CSV must not
    # be able to take an understated d1_start at face value just because they did
    # not also open the audit file.
    flags = audit.set_index("symbol")[["earliest_cache_year", "history_suspect"]]
    df = df.drop(columns=[c for c in ("earliest_cache_year", "history_suspect")
                          if c in df.columns])
    df = df.merge(flags, left_on="symbol", right_index=True, how="left")
    df.loc[df["history_suspect"] == True, "history_depth"] = "EXACT_LOWER_BOUND"  # noqa: E712
    df.to_csv(CSV, index=False)

    exact = audit[audit["history_depth"] == "EXACT"]
    bad = exact[exact["history_suspect"]]

    print("=" * 92)
    print("HISTORY DEPTH AUDIT  (filesystem only - no terminal calls)")
    print("=" * 92)
    print(f"rows in census            : {len(audit)}")
    print(f"labelled EXACT            : {len(exact)}")
    print(f"EXACT but understated     : {len(bad)}")
    print(f"EXACT and corroborated    : {len(exact) - len(bad)}")
    print()
    if len(bad):
        print("Symbols whose real history reaches further back than the census recorded.")
        print("For these, d1_start and d1_bars are LOWER BOUNDS, not exact values:")
        print()
        cols = ["symbol", "group", "d1_bars", "d1_start",
                "earliest_cache_year", "years_missing"]
        print(bad.sort_values(["group", "years_missing"], ascending=[True, False])
              [cols].to_string(index=False))
        print()
        by_group = bad.groupby("group").size()
        print("affected by group:")
        for g, n in by_group.items():
            tot = int((audit["group"] == g).sum())
            print(f"  {g:24s} {n:3d} of {tot}")
    else:
        print("No EXACT row is contradicted by the on-disk cache.")
    print()
    print(f"audit table -> {OUT}")


if __name__ == "__main__":
    main()
