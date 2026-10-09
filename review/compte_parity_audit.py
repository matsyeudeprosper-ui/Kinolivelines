"""Read-only Compte parity audit (ChatGPT brief 2026-10-09, task 2).

Three "Compte" inputs exist today:
  A display  - owl_nest_worker eqc: ALL closed deals (main + adds), raw $,
               minus spread_extra on the reference account
  B eq_state - structure_bos_bot: MAIN deals only, each scaled to 0.02 lot
  C tracker  - compte_state_tracker: all deals, lot-scaled to 0.02, no spread
Each is run through the same filter + engine + cold-start windows and the
states compared at every closed trade. Also reproduces the brief's synthetic
origin-switch case (a window change flipping the state with no new mark)."""
import glob, os, random, sys
import pandas as pd
LIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "live")
sys.path.insert(0, LIVE)
from owl_chart_feed import build, engine   # noqa: E402

WINDOWS = ("all", 120, 80, 50, 30, 20)


def state(P):
    raw, c = [], 0.0
    for i, p in enumerate(P):
        o = c; c += p
        raw.append({"time": i + 1, "open": o, "high": max(o, c), "low": min(o, c), "close": c})
    k = build(raw)
    if len(k) < 3:
        return (0, 0, None, len(k))
    for w in WINDOWS:
        kk = k if w == "all" else k[-w:]
        out = engine(kk, brk_out=[])
        if out[2]:
            return (out[2], out[3], w, len(k))
    return (0, 0, None, len(k))


def series(j, mode, spread_extra=0.0):
    out = []
    for r in j.itertuples():
        p = r.profit_usd - spread_extra * r.lot
        if mode == "B":
            if r.is_add: continue
            p = p * 0.02 / r.lot
        elif mode == "C":
            p = p * 0.02 / r.lot
        out.append(p)
    return out


def audit(f, spread_extra):
    j = pd.read_csv(f); j = j[j.profit_usd.notna()].copy()
    j["is_add"] = j.is_add.astype(str) == "True"
    j["t"] = pd.to_datetime(j.exit_time_utc, utc=True, format="mixed"); j = j.sort_values("t")
    A, B, C = series(j, "A", spread_extra), series(j, "B"), series(j, "C")
    n = len(A); dis_AB = dis_AC = switches = 0; prev = None
    for i in range(1, n + 1):
        sa = state(A[:i]); sb = state(B[:sum(1 for x in j.is_add[:i] if not x)]); sc = state(C[:i])
        dis_AB += (sa[0], sa[1]) != (sb[0], sb[1]); dis_AC += (sa[0], sa[1]) != (sc[0], sc[1])
        if prev and sa[2] != prev[2] and sa[0] != prev[0]:
            switches += 1                      # window changed AND trend changed
        prev = sa
    name = os.path.basename(f).replace("bos_journal", "").replace(".csv", "").strip("_") or "dad"
    print("%-12s trades %3d (adds %2d) | display vs eq_state differ at %3d/%d steps | display vs tracker %3d/%d | trend flips with a window change %d"
          % (name, n, int(j.is_add.sum()), dis_AB, n, dis_AC, n, switches))


def synthetic():
    r = random.Random(7)
    P = [r.choice([-1.0, 0.8]) * r.choice([1.0, 2.0, 3.0]) for _ in range(160)]
    hits = []
    prev = None
    for i in range(1, 161):
        s = state(P[:i])
        if prev and s[2] != prev[2] and s[0] != prev[0]:
            hits.append((i, prev[:3], s[:3]))
        prev = s
    print("synthetic 160 outcomes: %d trend flips caused by a window change" % len(hits))
    for h in hits[:5]:
        print("   outcome %3d: window %s trend %+d -> window %s trend %+d" % (h[0], h[1][2], h[1][0], h[2][2], h[2][0]))


if __name__ == "__main__":
    print("A display vs B eq_state vs C tracker, state = (trend, choch) at every closed trade:")
    for f in sorted(glob.glob(os.path.join(LIVE, "bos_journal*.csv"))):
        sx = 2.5 if "u477508138" in f else 0.0
        try:
            audit(f, sx)
        except Exception as e:
            print(os.path.basename(f), "skipped:", e)
    print()
    synthetic()
