"""Forward tracker (read-only): does the Compte indicator's state at entry
say anything about the trade that follows?  Pre-registered 2026-10-08.

The state at a trade's entry is a pure function of the trades that CLOSED
before it (one position at a time), so it is rebuilt here exactly as the
stats worker builds the progression chart: cumulative result per trade,
silence filter (owl_chart_feed.build), structure engine with the same
cold-start windows. Features per trade:
  trend      +1 rising / -1 falling / 0 none (the results' structure)
  choch_up   a CHoCH up is pending inside a downtrend
  last_red   the last shown candle is red (at a trade boundary the total is
             ALWAYS inside the last shown candle - a close outside it would
             have become the new candle - so "inside" carries nothing here)
  near_low   the next new low is within one average loss

Two parts:
  HISTORY  every account's real trades in lab/wealth/ (informational only:
           the accounts share signals, so pooled they are ONE sample).
  FORWARD  the reference account u477508138 (fixed size, every signal),
           trades closed after START. The VERDICT uses this part only.

Pre-registered verdict, at 60 forward trades on the reference account:
  PASS if trades entered in a DOWNTREND average at least $0.50 less than
  trades entered in an UPTREND (at 0.02 lot) AND a label permutation puts
  that gap at the 90th percentile or higher. Otherwise the state carries no
  usable information and every rule built on it stays closed. No retuning."""
import glob, json, os, random, sys
from datetime import datetime, timezone

LIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "live")
sys.path.insert(0, LIVE)
from owl_chart_feed import build, engine   # noqa: E402

REF = "u477508138"
START = datetime(2026, 10, 8, 18, 0, tzinfo=timezone.utc).timestamp()
MIN_N = 60


def state(P):
    raw, cum = [], 0.0
    for i, p in enumerate(P):
        o = cum; cum += p
        raw.append({"time": i + 1, "open": o, "high": max(o, cum), "low": min(o, cum), "close": cum})
    k = build(raw)
    if len(k) < 3:
        return None
    tr = ch = 0; nb = None
    for w in (len(k), 120, 80, 50, 30, 20):
        out = engine(k[-w:], brk_out=[])
        if out[2]:
            tr, ch, nb = out[2], out[3], out[4]
            break
    lh, ll = k[-1][2], k[-1][3]
    losses = [-p for p in P if p < 0]
    al = sum(losses) / len(losses) if losses else 1.0
    dn = (cum - nb) if (tr == -1 and nb is not None) else None
    return {"trend": tr, "choch_up": tr == -1 and ch == 1,
            "last_red": k[-1][4] < k[-1][1],
            "near_low": dn is not None and dn <= al}


def rows_for(path):
    w = json.load(open(path))
    T = sorted(w.get("trades") or [], key=lambda x: x[0])
    out = []
    for i in range(len(T)):
        s = state([x[1] for x in T[:i]])
        if s:
            out.append({"t": T[i][0], "p": T[i][1], "lot": T[i][2], **s})
    return w.get("uid") or os.path.basename(path)[:-5], out


def table(rows, title):
    print(title)
    def line(lbl, xs):
        if not xs:
            print("   %-26s n   0" % lbl); return
        n = len(xs); w = sum(1 for x in xs if x["p"] > 0)
        print("   %-26s n %4d  win %4.1f%%  avg %+.2f  net %8.2f" % (lbl, n, 100 * w / n, sum(x["p"] for x in xs) / n, sum(x["p"] for x in xs)))
    line("results rising", [r for r in rows if r["trend"] == 1])
    line("results falling", [r for r in rows if r["trend"] == -1])
    line("  ... with CHoCH up pending", [r for r in rows if r["choch_up"]])
    line("no trend yet", [r for r in rows if r["trend"] == 0])
    line("last candle red", [r for r in rows if r["last_red"]])
    line("last candle green", [r for r in rows if not r["last_red"]])
    line("near the next low", [r for r in rows if r["near_low"]])


def main():
    hist = {}
    for f in sorted(glob.glob(os.path.join(LIVE, "lab", "wealth", "*.json"))):
        uid, rows = rows_for(f)
        hist[uid] = rows
    allrows = [r for u, rs in hist.items() if u not in (REF, "std") for r in rs]
    table(allrows, "HISTORY - all bot accounts, real trades (informational, one shared sample):")
    ref = [r for r in hist.get(REF, []) if r["t"] >= START]
    # the reference trades at a fixed 0.02; scale anything else to it
    for r in ref:
        r["p"] = r["p"] * 0.02 / (r["lot"] or 0.02)
    table(ref, "\nFORWARD - reference account %s since 2026-10-08 18:00 UTC:" % REF)
    up = [r["p"] for r in ref if r["trend"] == 1]; dn = [r["p"] for r in ref if r["trend"] == -1]
    if len(ref) < MIN_N or not up or not dn:
        print("\nNO VERDICT YET: %d/%d forward trades on the reference account" % (len(ref), MIN_N)); return
    gap = sum(up) / len(up) - sum(dn) / len(dn)
    lab = [r["trend"] for r in ref if r["trend"] in (1, -1)]; P = [r["p"] for r in ref if r["trend"] in (1, -1)]
    random.seed(7); hits = 0
    for _ in range(5000):
        random.shuffle(lab)
        u = [p for p, l in zip(P, lab) if l == 1]; d = [p for p, l in zip(P, lab) if l == -1]
        if u and d and (sum(u) / len(u) - sum(d) / len(d)) < gap: hits += 1
    pct = 100 * hits / 5000
    print("\nuptrend minus downtrend: $%.2f per trade | permutation percentile %.0f" % (gap, pct))
    print("VERDICT:", "PASS" if (gap >= 0.50 and pct >= 90) else "CLOSED (fails pre-registered test)")


if __name__ == "__main__":
    main()
