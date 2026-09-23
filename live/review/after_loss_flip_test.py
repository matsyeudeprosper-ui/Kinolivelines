"""Stop after every loss; resume only on a new trend; stop at the day's
target. Applied to the REAL trades each account actually took.

Owner 2026-09-23: "stop trading after each loss and only resume in a new
trend after a flip, until the daily profit target is reached. What would
have happened if we did that from day one of those accounts?"

Read straight from the live logs, in order. An ENTRY line carries its
kind, and FLIP-BOS is by definition the first trade of a new trend - that
is the "resume" event. The WIN/LOSS line that follows an entry is that
trade's result (the bots hold one position at a time), and any ADD line
on the same close is the recovery bullet, counted with it.

HONEST LIMIT, stated up front: the logs only contain trades that were
TAKEN. A signal that was skipped because a position was already open was
never written down, so this cannot credit the rule with trades it would
have freed up. It measures the rule on the real sequence, which is what
was asked, and that is a floor not a ceiling.

    python review/after_loss_flip_test.py [target]
"""
import os
import re
import sys

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = float(sys.argv[1]) if len(sys.argv) > 1 else None

ENT = re.compile(r"^(\S+) ((?:FLIP-)?BOS|TOUCH|INT) ENTRY:")
RES = re.compile(r"^(\S+) (WIN|LOSS) ([+-][0-9.]+) \(lot")
ADD = re.compile(r"^(\S+) ADD ([+-][0-9.]+) \(lot")


def trades(path):
    """(day, kind, pnl) for every real trade, in order."""
    out, pend = [], None
    for line in open(path, encoding="utf-8", errors="ignore"):
        m = ENT.match(line)
        if m:
            pend = (m.group(1)[:10], m.group(2))
            continue
        m = RES.match(line)
        if m and pend:
            out.append([pend[0], pend[1], float(m.group(3))])
            pend = None
            continue
        m = ADD.match(line)
        if m and out:
            out[-1][2] += float(m.group(2))     # bullet rides with its trade
    return out


def apply_rule(tr, target):
    kept, armed, day, dpnl = [], True, None, 0.0
    for d, kind, p in tr:
        if d != day:
            day, dpnl = d, 0.0
        if target is not None and dpnl >= target:
            continue                            # done for the day
        if not armed:
            if kind != "FLIP-BOS":
                continue                        # wait for a new trend
            armed = True
        kept.append(p)
        dpnl += p
        if p < 0:
            armed = False
    return kept


def main():
    print()
    hdr = f"  {'account':<11}{'real trades':>12}{'real $':>10}"
    for T in (None, 3.0, 5.0, 10.0):
        hdr += f"{('rule T=' + (str(int(T)) if T else 'none')):>14}"
    print(hdr)
    tot = {}
    for v in ("valere", "kino", "demo", "infinity"):
        p = os.path.join(LIVE, f"bos_bot_{v}.log")
        if not os.path.exists(p):
            continue
        tr = trades(p)
        row = f"  {v:<11}{len(tr):>12}{sum(x[2] for x in tr):>10.2f}"
        tot.setdefault("real", 0.0)
        tot["real"] += sum(x[2] for x in tr)
        for T in (None, 3.0, 5.0, 10.0):
            k = apply_rule(tr, T)
            row += f"{sum(k):>9.2f}({len(k):>2})"
            tot[T] = tot.get(T, 0.0) + sum(k)
        print(row)
    row = f"  {'TOTAL':<11}{'':>12}{tot['real']:>10.2f}"
    for T in (None, 3.0, 5.0, 10.0):
        row += f"{tot[T]:>13.2f}"
    print(row)
    print("\n  T = stop opening once the day has made that much.")
    print("  Every column also stops after a loss until the next FLIP-BOS.\n")


if __name__ == "__main__":
    main()
