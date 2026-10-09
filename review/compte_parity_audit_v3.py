"""Compte parity audit v3 (ChatGPT review 3 qualifications).

Still an APPROXIMATE JOURNAL RECONSTRUCTION (bos_journal*.csv), not the
production deal query. Changes vs v2:
  * BEFORE-ENTRY = outcomes whose close time is STRICTLY before this main
    trade's entry time (ties broken by ticket), not "earlier rows";
  * opportunities = MAIN trades; an add is grouped with the main whose
    [entry, exit] contains the add's entry, and its result joins that
    opportunity's outcome at the opportunity's LAST close;
  * a trend flip counts as 'with mark' only if the adaptive engine's marks
    include one dated at the NEW observation with the confirming direction;
  * origin divergence = replay the PREVIOUSLY selected window's origin with
    the new observation (same origin), against the adaptive re-selection."""
import glob, os, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "..", "live")
sys.path.insert(0, LIVE)
from owl_chart_feed import build, engine   # noqa: E402

WINDOWS = ("all", 120, 80, 50, 30, 20)


def kept_of(P):
    raw, c = [], 0.0
    for i, p in enumerate(P):
        o = c; c += p
        raw.append({"time": i + 1, "open": o, "high": max(o, c), "low": min(o, c), "close": c})
    return build(raw)


def adaptive(k):
    """(trend, choch, origin index, marks) with the display's window order."""
    if len(k) < 3:
        return (0, 0, None, [])
    for w in WINDOWS:
        start = 0 if w == "all" else max(0, len(k) - w)
        out = engine(k[start:], brk_out=[])
        if out[2]:
            return (out[2], out[3], start, out[1])
    return (0, 0, None, [])


def opportunities(j):
    """main trades with their adds folded in; outcome known at the last close."""
    mains = j[~j.is_add].copy(); adds = j[j.is_add]
    rows = []
    for m in mains.itertuples():
        # an add's entry time may be missing in the journal: fall back to its
        # exit inside the main's life (adds share the main's SL/TP)
        t_ref = adds.t_in.fillna(adds.t_out)
        grp = adds[(t_ref >= m.t_in) & (t_ref <= m.t_out)]
        t_close = max([m.t_out] + list(grp.t_out)) if len(grp) else m.t_out
        rows.append({"t_in": m.t_in, "t_close": t_close, "ticket": m.ticket,
                     "p_main": m.profit_usd, "p_all": m.profit_usd + grp.profit_usd.sum(),
                     "adds": len(grp), "lot": m.lot})
    return sorted(rows, key=lambda r: (r["t_close"], r["ticket"]))


def audit(f):
    j = pd.read_csv(f); j = j[j.profit_usd.notna()].copy()
    j["is_add"] = j.is_add.astype(str) == "True"
    j["t_in"] = pd.to_datetime(j.entry_time_utc, utc=True, format="mixed")
    j["t_out"] = pd.to_datetime(j.exit_time_utc, utc=True, format="mixed")
    ops = opportunities(j)
    dAB = 0; flips_mark = flips_nomark = origin_div = 0; prev = None; stale = 0
    for i, op in enumerate(sorted(ops, key=lambda r: (r["t_in"], r["ticket"]))):
        known = [o for o in ops if o["t_close"] < op["t_in"]]          # strictly before entry
        stale += sum(1 for o in ops if o is not op and o["t_in"] < op["t_in"] and o["t_close"] >= op["t_in"])
        kA = kept_of([o["p_all"] for o in known])                        # display input
        kB = kept_of([o["p_main"] * 0.02 / o["lot"] for o in known])     # eq_state input
        sa, sb = adaptive(kA), adaptive(kB)
        dAB += (sa[0], sa[1]) != (sb[0], sb[1])
        if prev is not None and prev[0] and sa[0] and sa[0] == -prev[0]:
            new_obs = kA[-1][0] if kA else None          # marks are dated by the outcome index
            confirmed = any(m[0] == new_obs and m[2] == "bos" and m[3] == sa[0] for m in sa[3])
            if confirmed:
                flips_mark += 1
            else:
                flips_nomark += 1
                # replay the previous origin with the new observation
                if prev[2] is not None:
                    out_same = engine(kA[prev[2]:], brk_out=[])
                    if out_same[2] != sa[0]:
                        origin_div += 1
        prev = sa
    name = os.path.basename(f).replace("bos_journal", "").replace(".csv", "").strip("_") or "dad"
    print("%-11s opportunities %3d (adds folded %2d) | overlapping-at-entry cases %2d | display vs eq_state differ %3d | flips: confirmed BOS at the new obs %d / unconfirmed %d / origin-induced %d"
          % (name, len(ops), sum(o["adds"] for o in ops), stale, dAB, flips_mark, flips_nomark, origin_div))


if __name__ == "__main__":
    print("APPROXIMATE JOURNAL RECONSTRUCTION v3 - before-entry = closed strictly before t_entry, adds folded into their main")
    for f in sorted(glob.glob(os.path.join(LIVE, "bos_journal*.csv"))):
        try:
            audit(f)
        except Exception as e:
            print(os.path.basename(f), "skipped:", type(e).__name__, e)
