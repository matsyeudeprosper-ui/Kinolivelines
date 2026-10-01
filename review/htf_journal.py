"""Read the multi-timeframe snapshots out of the trade journals.

From 2026-10-01 every entry and every exit records the state of M15, H1, H4
and the minute at that moment (`htf_entry` / `htf_exit` in the journals).
This turns that into something answerable, and exists so the data is not
write-only.

It deliberately does NOT draw conclusions. With a handful of trades any
split looks meaningful, and this desk has been wrong twice this week by
believing a first half. It reports counts and says how far it is from a
sample worth reading.

Run:  python review/htf_journal.py
"""
import collections
import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(os.path.dirname(HERE), "live")
MIN_PER_CELL = 20          # below this a cell is not worth a sentence


def rows():
    out = []
    for f in sorted(os.listdir(LIVE)):
        if not (f.startswith("bos_journal") and f.endswith(".csv")):
            continue
        try:
            with io.open(os.path.join(LIVE, f), newline="",
                         encoding="utf-8", errors="replace") as fh:
                for r in csv.DictReader(fh):
                    r["_file"] = f
                    out.append(r)
        except Exception:
            continue
    return out


def snap(r, which):
    try:
        v = json.loads(r.get(which) or "")
        return v if isinstance(v, dict) else None
    except Exception:
        return None


def pnl(r):
    try:
        return float(r.get("profit_usd") or "")
    except Exception:
        return None


def main():
    R = rows()
    withsnap = [r for r in R if snap(r, "htf_entry")]
    print(f"journals: {len(R)} rows, {len(withsnap)} with an entry snapshot")
    if not withsnap:
        print("")
        print("No snapshot yet. Recording started 2026-10-01 and a row is")
        print("written when a trade CLOSES, so the first ones appear as")
        print("today's open trades finish. Nothing is wrong.")
        return 0

    # how the market looked at entry, against what the trade did
    cells = collections.defaultdict(lambda: [0, 0.0, 0])
    flips = [0, 0]
    for r in withsnap:
        e = snap(r, "htf_entry")
        p = pnl(r)
        if p is None:
            continue
        d = 1 if (r.get("direction") == "BUY") else -1
        hi = [e[k]["t"] for k in ("m15", "h1", "h4") if k in e]
        with_trade = sum(1 for t in hi if t and t == d)
        key = f"{with_trade}/{len(hi)} timeframes with the trade"
        c = cells[key]
        c[0] += 1
        c[1] += p
        c[2] += 1 if p > 0 else 0
        x = snap(r, "htf_exit")
        if x:
            flips[0] += 1
            e_m1 = (e.get("m1") or {}).get("t")
            x_m1 = (x.get("m1") or {}).get("t")
            if e_m1 and x_m1 and e_m1 != x_m1:
                flips[1] += 1

    print("")
    print("at ENTRY, how many higher timeframes pointed the trade's way")
    for k in sorted(cells):
        n, net, w = cells[k]
        enough = "" if n >= MIN_PER_CELL else \
            f"   (only {n} - need {MIN_PER_CELL} before this means anything)"
        print(f"  {k:<34} n {n:4d}  net {net:+8.2f}  "
              f"win {w/n*100:4.0f}%{enough}")
    if flips[0]:
        print("")
        print(f"the minute changed direction between entry and exit in "
              f"{flips[1]} of {flips[0]} trades")
    small = [k for k in cells if cells[k][0] < MIN_PER_CELL]
    print("")
    if small:
        print(f"{len(small)} of {len(cells)} cells are still too small to "
              f"read. No conclusion yet, on purpose.")
    else:
        print("every cell has a readable sample - worth a proper study now, "
              "with halves and a control.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
