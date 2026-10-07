"""Forward tracker (read-only): win/loss by trade position inside a trend.
#1 = FLIP-BOS, #2 = first BOS after it in the same direction, and so on.
Pre-registered 2026-10-07: question is whether #3 wins more than the rest
(replay: 13/19 = 68% vs 60% overall, within noise). No verdict before 40
real #3 trades on the reference account (bos_journal.csv); do not retune.
Pooling accounts would double count the same signals, so the table is for
ONE reference account; others are shown for a sanity count only."""
import math, os, sys
import pandas as pd

LIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "live")
REF = "bos_journal.csv"
OTHERS = ["bos_journal_valere.csv", "bos_journal_expenses.csv", "bos_journal_infinity.csv", "bos_journal_kino.csv"]
MIN_N3 = 40


def positions(f):
    j = pd.read_csv(os.path.join(LIVE, f))
    j = j[(j.is_add.astype(str) != "True") & (j.kind.isin(["FLIP-BOS", "BOS"]))].copy()
    j["x"] = pd.to_datetime(j.exit_time_utc, utc=True)
    j = j.sort_values("entry_time_utc").reset_index(drop=True)
    pos, k, last = [], None, None
    for r in j.itertuples():
        if r.kind == "FLIP-BOS": k = 1
        elif k is not None and r.direction == last: k += 1
        else: k = None
        last = r.direction; pos.append(k)
    j["pos"] = pos
    return j


def wilson(w, n):
    if n == 0: return (0, 0)
    z, p = 1.96, w / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (100 * (c - h) / d, 100 * (c + h) / d)


def line(name, s):
    n = len(s); w = int((s.profit_usd > 0).sum())
    lo, hi = wilson(w, n)
    return "%-8s n %3d  win %3.0f%% (95%% range %2.0f-%3.0f)  loss %3.0f%%  avg %+6.2f  net %+8.2f" % (
        name, n, 100 * w / max(n, 1), lo, hi, 100 * (n - w) / max(n, 1), s.profit_usd.mean() if n else 0, s.profit_usd.sum())


def main():
    j = positions(REF)
    print("reference account:", REF, "| main trades", len(j), "| position unknown", int(j.pos.isna().sum()))
    print(line("all", j))
    for p in (1, 2, 3, 4):
        print(line("#%d" % p, j[j.pos == p]))
    print(line("#5+", j[j.pos >= 5]))
    n3 = int((j.pos == 3).sum())
    print("\n#3 trades so far: %d of the %d needed for a verdict%s" % (n3, MIN_N3, "  -> ENOUGH, judge it" if n3 >= MIN_N3 else ""))
    print("replay reference: #1 63% (128) | #2 57% (69) | #3 68% (19) | all 60% (260)")
    print("\nother accounts (count check only):")
    for f in OTHERS:
        try:
            o = positions(f); print("  %-26s #3 trades %d of %d" % (f, int((o.pos == 3).sum()), len(o)))
        except Exception as e:
            print("  %-26s %s" % (f, e))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
