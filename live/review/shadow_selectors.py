"""Forward record for the two selectors the owner asked to watch.

Owner 2026-09-20, after selector_test.py:
  A  "only one trade after each virtual loss"   replay +0.141 R, 6/6 anchors,
     halves agree, shuffle p=0.034 - but FOUND in that data, CI spans zero.
  B  "only the 2nd trade of a trend"            replay +0.060 R, halves
     DISAGREE, and it is the Sniper variant that hit its -$80 kill line
     live on 2026-09-18 after 25 real fills.

Both are pure SELECTORS over signals the bot already produces, so neither
needs a parallel simulation: the "fvg" shadow book already records every
qualifying signal and settles it on raw bars. A is a slice of that book's
own virtual outcomes - which is exactly the owner's wording, "after each
VIRTUAL loss". B needs the trend ordinal, which the bot now writes into
the record as ord=N (ord=i for internal trades).

NOT INDEPENDENT: every account runs the same bot on the same symbol, so
the books repeat the same market signals. Accounts are printed separately
and must never be pooled into one sample size.

The book stores R gross (0.8 win / -1.0 loss). dist is recovered from
usd = R * dist * lot, so a spread can be charged to match the replay.

    python review/shadow_selectors.py [spread_points]
"""
import glob
import json
import os
import statistics as st
import sys

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPREAD = float(sys.argv[1]) if len(sys.argv) > 1 else 7.0
RR = 0.8


def net_R(rec, spread):
    """Re-price one settled record at a spread. Returns None if unrecoverable."""
    R, usd, lot = rec.get("R"), rec.get("usd"), 0.02
    if not R or usd is None:
        return None
    dist = usd / (R * lot) if R else 0.0
    if dist <= 0:
        return None
    return ((RR * dist - spread) / dist if rec["win"]
            else -(dist + spread) / dist)


def load(path, spread):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        print(f"  ! {os.path.basename(path)}: {e}")
        return []
    out = []
    for x in d.get("done", []):
        r = net_R(x, spread)
        if r is None:
            continue
        why = x.get("why", "")
        ordt = None
        for tok in why.split():
            if tok.startswith("ord="):
                ordt = tok[4:]
        if ordt is None and " INT" in f" {why} ":
            ordt = "i"          # records written before the tag existed
        out.append({"t": x["t"], "win": bool(x["win"]), "R": r,
                    "usd": r * (x["usd"] / (x["R"] * 0.02)) * 0.02
                           if x["R"] else 0.0,
                    "ord": ordt, "why": why})
    out.sort(key=lambda z: z["t"])
    return out


def sel_after_loss(tr):
    out, armed = [], False
    for x in tr:
        if armed:
            out.append(x)
            armed = False
        if not x["win"]:
            armed = True
    return out


def line(lab, tr, days):
    if not tr:
        print(f"  {lab:<26}{'-':>7}{'':>7}{'':>8}{'':>10}   not yet")
        return
    r = [x["R"] for x in tr]
    per = sum(r) / len(r)
    se = (st.pstdev(r) / len(r) ** 0.5) if len(r) > 1 else 0.0
    wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
    usd = sum(x["usd"] for x in tr)
    print(f"  {lab:<26}{len(tr):>7}{len(tr)/days if days else 0:>7.2f}"
          f"{wr:>7.1f}%{per:>+10.3f}"
          f"   [{per-1.96*se:+.3f},{per+1.96*se:+.3f}]{usd:>9.2f}")


def main():
    books = sorted(glob.glob(os.path.join(LIVE, "owl_shadow_*_fvg.json")))
    if not books:
        raise SystemExit("no fvg shadow book yet")
    print(f"\n  FORWARD selector record   spread {SPREAD:.0f}   "
          f"(replay was: all +0.003 / A +0.141 / B +0.060)")
    print("  accounts are the SAME signals - never pool them\n")
    for p in books:
        uid = os.path.basename(p)[len("owl_shadow_"):-len("_fvg.json")]
        tr = load(p, SPREAD)
        main_tr = [x for x in tr if x["ord"] != "i"]
        tagged = [x for x in main_tr if x["ord"] is not None]
        days = ((tr[-1]["t"] - tr[0]["t"]) / 86400) if len(tr) > 1 else 0
        print(f"  --- {uid}   {len(tr)} settled over {days:.1f} days "
              f"({len(tagged)} carry an ordinal tag) ---")
        print(f"  {'rule':<26}{'trades':>7}{'/day':>7}{'win%':>8}"
              f"{'R/trade':>10}{'95% interval':>20}{'$':>9}")
        line("all main signals", main_tr, days)
        line("A: after each v-loss", sel_after_loss(main_tr), days)
        line("B: 2nd of each trend", [x for x in tagged if x["ord"] == "2"],
             days)
        line("internal (separate)", [x for x in tr if x["ord"] == "i"], days)
        print()
    print("  No verdict before the tagged count passes ~100 per account,")
    print("  and A still has to beat 'take everything' in DOLLARS, which")
    print("  it did not in the replay ($39.28 vs $50.60).\n")


if __name__ == "__main__":
    main()
