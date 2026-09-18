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


def _path(uid):
    return os.path.join(DIR, f"owl_shadow_{uid}.json")


def _load(uid):
    try:
        with open(_path(uid), encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("open", [])
        d.setdefault("done", [])
        return d
    except Exception:
        return {"open": [], "done": [], "started": int(time.time())}


def _save(uid, d):
    try:
        p = _path(uid)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, p)
    except Exception:
        pass


def open_trade(uid, d, entry, sl, tp, why, lot=0.02):
    """Note a trade the gate refused. Returns nothing; never raises."""
    try:
        st = _load(uid)
        if len(st["open"]) >= MAX_OPEN:
            return
        st["open"].append({"t": int(time.time()), "d": int(d),
                           "e": round(float(entry), 2),
                           "sl": round(float(sl), 2),
                           "tp": round(float(tp), 2),
                           "lot": lot, "why": why})
        _save(uid, st)
    except Exception:
        pass


def settle(uid, high, low):
    """Close any virtual trade this bar's range would have finished.

    A bar that spans BOTH the stop and the target counts as a LOSS - the
    pessimistic side, so this record can never flatter the counterfactual
    it exists to test.
    """
    try:
        st = _load(uid)
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
            _save(uid, st)
    except Exception:
        pass


def summary(uid):
    try:
        st = _load(uid)
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


if __name__ == "__main__":
    import sys
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
