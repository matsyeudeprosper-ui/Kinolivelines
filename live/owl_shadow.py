"""owl_shadow.py - the trades the nervosity gate refused, tracked virtually.

Owner 2026-09-18: "if it's positive keep it... record virtual forward
trades of what we would have made without it so we can measure later."

The 41.7-day replay could not settle whether the gate helps: +0.019 R/trade
with it, +0.018 without, both error bars straddling zero, and the sign
flipping across window anchors. It would take roughly 1200 trades. So the
only way to answer it is forward, on real signals, one at a time.

This records ONLY the signals the gate refused FOR NERVOSITY, and only
when every other rule would have let the trade through. That is exactly
the counterfactual: what the account would have done without this one
brake. Nothing here places an order - it is a notebook.

    import owl_shadow as SH
    SH.open_trade(uid, d, entry, sl, tp, "trop nerveux (1.18x)")
    SH.settle(uid, high, low)         # every bar
    SH.summary(uid)                   # {"n":..,"wins":..,"R":..}

One file per account, owl_shadow_<uid>.json, written atomically. A
corrupt or missing file costs the record, never a trade: every call is
wrapped, and the caller is never given a reason to stop.
"""
import json
import os
import time

DIR = os.path.dirname(os.path.abspath(__file__))
MAX_OPEN = 40            # a runaway list would mean settle() is not running
MAX_DONE = 2000


def _path(uid, book=""):
    # book "" = the nervosity counterfactual (original file name kept);
    # any other name = a separate forward record, e.g. "fvg"
    sfx = f"_{book}" if book else ""
    return os.path.join(DIR, f"owl_shadow_{uid}{sfx}.json")


def _load(uid, book=""):
    try:
        with open(_path(uid, book), encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("open", [])
        d.setdefault("done", [])
        return d
    except Exception:
        return {"open": [], "done": [], "started": int(time.time())}


def _save(uid, d, book=""):
    try:
        p = _path(uid, book)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, p)
    except Exception:
        pass


def open_trade(uid, d, entry, sl, tp, why, lot=0.02, book=""):
    """Note a virtual trade. Returns nothing; never raises.
    book="" is the nervosity counterfactual; book="fvg" records EVERY
    qualifying signal tagged with its fair-value gap (owner 2026-09-19),
    so the FVG filter can be judged forward without touching a trade."""
    try:
        st = _load(uid, book)
        if len(st["open"]) >= MAX_OPEN:
            return
        st["open"].append({"t": int(time.time()), "d": int(d),
                           "e": round(float(entry), 2),
                           "sl": round(float(sl), 2),
                           "tp": round(float(tp), 2),
                           "lot": lot, "why": why})
        _save(uid, st, book)
    except Exception:
        pass


def settle(uid, high, low, book=""):
    """Close any virtual trade this bar's range would have finished.

    A bar that spans BOTH the stop and the target counts as a LOSS - the
    pessimistic side, so this record can never flatter the counterfactual
    it exists to test.
    """
    try:
        st = _load(uid, book)
        if not st["open"]:
            return
        high, low = float(high), float(low)
        still, closed = [], False
        for x in st["open"]:
            d, e, sl, tp = x["d"], x["e"], x["sl"], x["tp"]
            hit_sl = (low <= sl) if d == 1 else (high >= sl)
            hit_tp = (high >= tp) if d == 1 else (low <= tp)
            if not (hit_sl or hit_tp):
                still.append(x)
                continue
            win = bool(hit_tp and not hit_sl)
            dist = abs(e - sl)
            r = (abs(tp - e) / dist) if (win and dist) else -1.0
            st["done"].append({"t": x["t"], "closed": int(time.time()),
                               "win": win, "R": round(r, 3),
                               "usd": round(r * dist * x["lot"], 2),
                               "why": x.get("why", "")})
            closed = True
        if closed:
            st["open"] = still
            del st["done"][:-MAX_DONE]
            _save(uid, st, book)
    except Exception:
        pass


def summary(uid, book=""):
    try:
        st = _load(uid, book)
        dn = st["done"]
        n = len(dn)
        if not n:
            return {"n": 0, "open": len(st["open"]), "wins": 0,
                    "R": 0.0, "usd": 0.0, "wr": None,
                    "since": st.get("started")}
        w = sum(1 for x in dn if x["win"])
        return {"n": n, "open": len(st["open"]), "wins": w,
                "R": round(sum(x["R"] for x in dn), 2),
                "usd": round(sum(x["usd"] for x in dn), 2),
                "wr": round(100 * w / n, 1),
                "since": st.get("started")}
    except Exception:
        return {"n": 0, "open": 0, "wins": 0, "R": 0.0, "usd": 0.0,
                "wr": None, "since": None}


def fvg_report(uid):
    """The forward record of the FVG filter: every qualifying signal, split
    by whether its confirming candle left a gap. This is the data the two
    failed controls (halves, shuffle) need more of."""
    st = _load(uid, "fvg")
    dn = st["done"]
    def _g(x):
        try:
            return float(str(x.get("why", "")).split("fvg=")[1].split()[0])
        except Exception:
            return 0.0
    rows = []
    for lab, f in (("avec gap", lambda x: _g(x) > 0),
                   ("sans gap", lambda x: _g(x) <= 0)):
        sub = [x for x in dn if f(x)]
        if sub:
            w = sum(1 for x in sub if x["win"])
            rows.append((lab, len(sub), 100 * w / len(sub),
                         sum(x["R"] for x in sub) / len(sub)))
        else:
            rows.append((lab, 0, 0.0, 0.0))
    return rows, len(st["open"])


if __name__ == "__main__":
    import sys
    if "--fvg" in sys.argv:
        for uid in [a for a in sys.argv[1:] if a != "--fvg"] or ["kino", "u224016179"]:
            rows, op = fvg_report(uid)
            print(f"  {uid:<14} FVG forward - {op} en cours")
            for lab, n, wr, per in rows:
                print(f"    {lab:<10} {n:>4} termines  {wr:5.1f}%  {per:+.3f} R/trade")
            print("    il faut les deux moities d'accord et p < 0.01 avant d'y croire")
        raise SystemExit
    ids = sys.argv[1:] or ["bos", "u224016179"]
    print("  Trades refuses pour nervosite, suivis virtuellement")
    print("  (ce que le compte aurait fait SANS ce frein)\n")
    for uid in ids:
        s = summary(uid)
        since = (time.strftime("%Y-%m-%d", time.localtime(s["since"]))
                 if s["since"] else "?")
        print(f"  {uid:<14} depuis {since}  "
              f"{s['n']:>3} termines, {s['open']} en cours")
        if s["n"]:
            print(f"  {'':14} {s['wr']}% de reussite, {s['R']:+.2f} R, "
                  f"${s['usd']:+.2f}")
        print(f"  {'':14} il faut ~1200 trades pour trancher")
