"""Forward tracker (read-only): the LOSS-PAUSE rule on real trades.
Pre-registered 2026-10-08 (owner chose a live test; shadow mode, no bot change).

Rule: after a losing trade, real trading pauses and the system trades
"virtually" until one (virtual) trade wins; the trade after that win is real
again. In shadow mode every trade is still taken, so a "paused" trade's
result is exactly what the virtual trade would have shown.

Basis (study/candle_gate_test.py): on the 6 real journals up to 2026-10-08 the
rule raised net and cut the worst drop on every account, but the accounts share
signals (one sample of ~65 trades) and the replay was mixed.

Reference account = bos_journal.csv (Dad, 223995441); trades closed after
START only. Others printed for a sanity count, not for the verdict.
No verdict before 40 trades. PASS only if ALL:
  1. paused trades lose money in total (net < 0),
  2. kept trades make more per trade than paused trades,
  3. the kept set sits at the 90th percentile or higher vs random picks of
     the same size.
Otherwise the rule is closed. Do not retune."""
import glob, os, random
import pandas as pd

LIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "live")
START = pd.Timestamp("2026-10-08T15:00:00Z")
MIN_N = 40


def load(f):
    j = pd.read_csv(f)
    j = j[j.profit_usd.notna()].copy()
    j["t"] = pd.to_datetime(j.exit_time_utc, utc=True, format="mixed")
    return j.sort_values("t")


def tag(j):
    # the state carries in from the trades BEFORE START, so the first test
    # trade is judged exactly as it would have been live
    keep, last = [], 1
    for p in j.profit_usd:
        keep.append(last >= 0)
        if p > 0: last = 1
        elif p < 0: last = -1
    j = j.copy(); j["kept"] = keep
    return j[j.t >= START]


def line(name, x):
    if x.empty: return f"  {name:7s} n   0"
    return (f"  {name:7s} n {len(x):3d}  win {100 * (x.profit_usd > 0).mean():4.1f}%  "
            f"net {x.profit_usd.sum():8.2f}  per trade {x.profit_usd.mean():+.2f}")


def main():
    ref = os.path.join(LIVE, "bos_journal.csv")
    for f in sorted(glob.glob(os.path.join(LIVE, "bos_journal*.csv"))):
        j = tag(load(f))
        k, s = j[j.kept], j[~j.kept]
        print(("REFERENCE " if f == ref else "") + os.path.basename(f), f"- {len(j)} trades since {START:%Y-%m-%d %H:%M} UTC")
        print(line("all", j)); print(line("kept", k)); print(line("paused", s))
        if f != ref: continue
        if len(j) < MIN_N:
            print(f"  NO VERDICT YET: {len(j)}/{MIN_N} trades\n"); continue
        P = list(j.profit_usd); tot = k.profit_usd.sum(); n = len(k)
        random.seed(7)
        pct = 100 * sum(1 for _ in range(5000) if sum(random.sample(P, n)) < tot) / 5000 if n else 0
        c1 = s.profit_usd.sum() < 0
        c2 = len(s) and k.profit_usd.mean() > s.profit_usd.mean()
        print(f"  paused lose: {c1} | kept beats paused: {bool(c2)} | random pct {pct:.0f}")
        print("  VERDICT:", "PASS" if (c1 and c2 and pct >= 90) else "CLOSED (fails pre-registered test)", "\n")


if __name__ == "__main__":
    main()
