"""Forward tracker (read-only): the pullback-chart TOUCH rule on real trades.
Pre-registered 2026-10-07. Rule: a trade is "kept" when the last touched main
pullback-chart level (live/pb_touch_events.csv, from pb_touch_logger.py) points
the same way as the trade. Trades before the logger's first event are ignored.
Reference account = bos_journal.csv (the same signals repeat on the others).

No verdict before 40 KEPT trades. Then the rule PASSES only if BOTH:
  1. kept trades make more per trade than skipped trades, and
  2. kept trades sit at the 90th percentile or higher vs random picks of the
     same size from all trades.
Otherwise it is closed. Do not retune the rule or the thresholds."""
import os, random
import pandas as pd

LIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "live")
MIN_KEPT = 40


def main():
    ev = pd.read_csv(os.path.join(LIVE, "pb_touch_events.csv"))
    if ev.empty:
        print("no touch events logged yet"); return
    ev["t"] = pd.to_datetime(ev.time_utc, utc=True)
    ev = ev.sort_values("t")
    j = pd.read_csv(os.path.join(LIVE, "bos_journal.csv"))
    j = j[(j.is_add.astype(str) != "True") & j.outcome.notna()].copy()
    j["t"] = pd.to_datetime(j.entry_time_utc, utc=True, format="mixed")
    j = j[j.t > ev.t.iloc[0]].sort_values("t")
    if j.empty:
        print("touch log since", ev.t.iloc[0], "- no closed trades since then"); return
    j["d"] = j.direction.map({"BUY": 1, "SELL": -1})
    last = pd.merge_asof(j[["t"]], ev[["t", "dir"]], on="t", direction="backward")
    j["kept"] = (last["dir"].values == j["d"].values)
    k, s = j[j.kept], j[~j.kept]
    def line(name, x):
        if x.empty: return f"  {name:8s} n   0"
        return (f"  {name:8s} n {len(x):3d}  win {100 * (x.profit_usd > 0).mean():4.1f}%  "
                f"net {x.profit_usd.sum():8.2f}  per trade {x.profit_usd.mean():+.2f}")
    print(f"touch log since {ev.t.iloc[0]:%Y-%m-%d %H:%M} UTC, {len(ev)} touches; reference account trades {len(j)}")
    print(line("all", j)); print(line("kept", k)); print(line("skipped", s))
    if len(k) < MIN_KEPT:
        print(f"\nNO VERDICT YET: {len(k)}/{MIN_KEPT} kept trades"); return
    P = list(j.profit_usd); n = len(k); tot = k.profit_usd.sum()
    random.seed(7)
    pct = 100 * sum(1 for _ in range(5000) if sum(random.sample(P, n)) < tot) / 5000
    c1 = k.profit_usd.mean() > (s.profit_usd.mean() if len(s) else -1e9)
    print(f"\nrandom percentile {pct:.0f}  | kept beats skipped per trade: {c1}")
    print("VERDICT:", "PASS" if (c1 and pct >= 90) else "CLOSED (fails pre-registered test)")


if __name__ == "__main__":
    main()
