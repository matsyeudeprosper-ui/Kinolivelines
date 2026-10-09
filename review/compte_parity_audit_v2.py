"""Compte parity audit v2 (ChatGPT corrections of 2026-10-09).

Approximate JOURNAL reconstruction (bos_journal*.csv), not the production
deal query - labelled as such. Fixes vs v1:
  1. the tracker series is computed EXACTLY as review/compte_state_tracker.py
     does it: its own state() on RAW money, before any lot normalisation;
  2. trend flips are classified: initialisation excluded (old and new trend
     must be nonzero and opposite); 'mark' = the adaptive engine confirmed a
     new BOS/CHoCH on that observation; 'no_mark' = it did not; and
     'origin_induced' = no mark AND the pinned-origin controller fed the
     same prefix did NOT flip - the divergence the brief asked to isolate.
States are the BEFORE-entry states: computed on the prefix of trades closed
before each trade, on the same opportunity index for every input."""
import glob, os, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "..", "live")
sys.path.insert(0, LIVE); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(LIVE, "lab"))
from owl_chart_feed import build, engine                 # noqa: E402
from compte_state_tracker import state as tracker_state   # noqa: E402  (the real one)
from compte_controller import CompteController             # noqa: E402

WINDOWS = ("all", 120, 80, 50, 30, 20)


def adaptive(P):
    """display / eq_state path: build() (2 dp) + first window with a direction."""
    raw, c = [], 0.0
    for i, p in enumerate(P):
        o = c; c += p
        raw.append({"time": i + 1, "open": o, "high": max(o, c), "low": min(o, c), "close": c})
    k = build(raw)
    if len(k) < 3:
        return (0, 0, None, 0)
    for w in WINDOWS:
        kk = k if w == "all" else k[-w:]
        bk = []; out = engine(kk, brk_out=bk)
        if out[2]:
            return (out[2], out[3], w, len(out[1]))
    return (0, 0, None, 0)


def audit(f, spread_extra):
    j = pd.read_csv(f); j = j[j.profit_usd.notna()].copy()
    j["is_add"] = j.is_add.astype(str) == "True"
    j["t"] = pd.to_datetime(j.exit_time_utc, utc=True, format="mixed"); j = j.sort_values("t")
    A = [r.profit_usd - spread_extra * r.lot for r in j.itertuples()]        # display
    Bm = [(r.profit_usd * 0.02 / r.lot, r.is_add) for r in j.itertuples()]  # eq_state input
    C = [r.profit_usd for r in j.itertuples()]                               # tracker input (raw)
    n = len(A)
    dAB = dAC = 0; coinc = mark = nomark = origin = 0
    ctl = CompteController(); prev = None
    for i in range(n):                        # BEFORE-entry state of trade i
        sa = adaptive(A[:i])
        sb = adaptive([p for p, add in Bm[:i] if not add])
        tc = tracker_state(C[:i]); sc = (tc["trend"], 1 if tc["choch_up"] else 0) if tc else (0, 0)
        dAB += (sa[0], sa[1]) != (sb[0], sb[1])
        dAC += sa[0] != sc[0]
        if i > 0:
            ctl.feed(A[i - 1])
        if prev and prev[0] and sa[0] and sa[0] == -prev[0]:
            new_marks = sa[3] > prev[3] and sa[2] == prev[2]
            if sa[2] != prev[2]:
                if new_marks or sa[3] > prev[3]:
                    mark += 1
                else:
                    nomark += 1
                    if not (ctl.transitions and ctl.transitions[-1][0] == i):
                        origin += 1
            else:
                mark += 1 if sa[3] > prev[3] else 0
                coinc += 0 if sa[3] > prev[3] else 1
        prev = sa
    name = os.path.basename(f).replace("bos_journal", "").replace(".csv", "").strip("_") or "dad"
    print("%-11s n %3d | display vs eq_state differ %3d | display vs tracker trend differ %3d | flips: with mark %d, window change no mark %d (origin-induced %d), same window no mark %d | ctl origin %s/%s"
          % (name, n, dAB, dAC, mark, nomark, origin, coinc, ctl.origin, ctl.origin_window))


if __name__ == "__main__":
    print("APPROXIMATE JOURNAL RECONSTRUCTION - before-entry states on the same opportunity index")
    for f in sorted(glob.glob(os.path.join(LIVE, "bos_journal*.csv"))):
        audit(f, 2.5 if "u477508138" in f else 0.0)
