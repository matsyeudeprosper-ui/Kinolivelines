"""kino_patterns.py (2026-11-03, owner: "a proper engine - and Kino deals with many fields of life"). Patterns in a person's own
record, found the way a careful friend would: notice something, keep it as a hunch, check it again on what happens next,
and keep only what survives.

Any record works - trades, sales of a shop, workouts, sleep - as long as each entry has a time, an outcome (a number: the
money of a trade, the takings of a day, the minutes run) and some attributes (what kind, what side, what size...). An
ADAPTER turns a source into records; the engine knows nothing about trading.

  find     for each attribute and each of its values (plus hour-of-day and weekday, from the time), compare the mean
           outcome of that slice with the rest; a slice of >= 6 entries whose difference is large for its spread becomes a
           HUNCH, stamped with the records it was seen on
  recheck  when at least 8 new records arrived since the hunch was formed, the same slice is measured on the NEW records
           only: same direction -> it holds (confirmed count +1); opposite or flat -> it fails, and is dropped after 2 fails
  read     what he can say: hunches first seen (plainly called hunches), patterns that held on new data, and how many times
"""
import io, json, math, os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_patterns.json")
_LOCK = threading.Lock()
MIN_N = 6
MIN_NEW = 8


def _load():
    try:
        return json.load(io.open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = STORE + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def _attrs(r):
    a = dict(r.get("attrs") or {})
    g = time.gmtime(float(r["t"]))
    a["hours (UTC)"] = "%02d-%02d h" % (g.tm_hour // 4 * 4, g.tm_hour // 4 * 4 + 4)
    a["weekday"] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[g.tm_wday]
    return a


def _slices(R):
    S = {}
    for r in R:
        for k, v in _attrs(r).items():
            S.setdefault((k, str(v)), []).append(float(r["y"]))
    return S


def _stat(R, key):
    ins = [float(r["y"]) for r in R if str(_attrs(r).get(key[0])) == key[1]]
    outs = [float(r["y"]) for r in R if str(_attrs(r).get(key[0])) != key[1]]
    if len(ins) < 3 or len(outs) < 3:
        return None
    m_in, m_out = sum(ins) / len(ins), sum(outs) / len(outs)
    allv = ins + outs
    mu = sum(allv) / len(allv)
    sd = math.sqrt(sum((x - mu) ** 2 for x in allv) / max(1, len(allv) - 1)) or 1e-9
    se = sd * math.sqrt(1.0 / len(ins) + 1.0 / len(outs))
    return {"n": len(ins), "m_in": m_in, "m_out": m_out, "z": (m_in - m_out) / (se or 1e-9)}


def update(person, source, records, unit=""):
    """records: [{"t": epoch, "y": outcome, "attrs": {...}}] oldest first, the person's whole recent record of that source"""
    R = sorted([r for r in records if r.get("t") is not None and r.get("y") is not None], key=lambda r: float(r["t"]))
    if len(R) < 2 * MIN_N:
        return
    now = time.time()
    with _LOCK:
        d = _load()
        P = d.setdefault(person, {}).setdefault(source, {"hyp": {}, "unit": unit})
        H = P["hyp"]
        last_t = float(R[-1]["t"])
        # recheck what is old enough to be tested on new records
        for hk, h in list(H.items()):
            new = [r for r in R if float(r["t"]) > float(h["seen_to"])]
            if len(new) < MIN_NEW:
                continue
            st = _stat(new, tuple(h["key"]))
            same = st is not None and st["n"] >= 3 and (st["m_in"] - st["m_out"]) * h["sign"] > 0 and abs(st["z"]) >= 0.8
            if same:
                h["held"] = int(h.get("held", 0)) + 1
            else:
                h["failed"] = int(h.get("failed", 0)) + 1
            h["seen_to"], h["checked"] = last_t, now
            if h.get("failed", 0) >= 2 and h.get("failed", 0) > h.get("held", 0):
                del H[hk]
        # find new hunches on everything seen so far
        SL = _slices(R)
        nvals = {}
        for (k, v) in SL:
            nvals[k] = nvals.get(k, 0) + 1
        for key, ys in SL.items():
            if len(ys) < MIN_N:
                continue
            hk = "%s=%s" % key
            if hk in H:
                continue
            if nvals.get(key[0]) == 2 and any(h["key"][0] == key[0] for h in H.values()):
                continue                       # a two-valued attribute: "buys win" already says "sells lose"
            st = _stat(R, key)
            if st and abs(st["z"]) >= 2.0:
                H[hk] = {"key": list(key), "sign": 1 if st["m_in"] > st["m_out"] else -1, "n": st["n"],
                         "m_in": round(st["m_in"], 2), "m_out": round(st["m_out"], 2), "seen_to": last_t, "t": now, "held": 0, "failed": 0}
        # keep the strongest few
        if len(H) > 12:
            for hk in sorted(H, key=lambda k: (H[k].get("held", 0), abs(H[k]["m_in"] - H[k]["m_out"])))[:len(H) - 12]:
                del H[hk]
        P["n"], P["t"] = len(R), now
        _save(d)


def block(person):
    d = (_load().get(person) or {})
    L = []
    for src, P in d.items():
        H = P.get("hyp") or {}
        if not H:
            continue
        u = P.get("unit") or ""
        rows = []
        for h in sorted(H.values(), key=lambda h: (-h.get("held", 0), -abs(h["m_in"] - h["m_out"])))[:4]:
            k, v = h["key"]
            state = ("held on new data %d time%s" % (h["held"], "" if h["held"] == 1 else "s") if h.get("held") else
                     "a hunch, not re-checked yet" if not h.get("failed") else "shaky (failed a re-check)")
            rows.append("%s %s: %+.2f%s on average vs %+.2f%s otherwise (%d entries) - %s" % (k, v, h["m_in"], u, h["m_out"], u, h["n"], state))
        L.append("Patterns in his own %s (found in his record, re-checked on what came after; raise one only when it is useful to "
                 "him now): %s." % (src, " | ".join(rows)))
    return "\n".join(L)


# ---- adapters: a source -> records. The engine above knows nothing about any of them. -------------------------------
def from_trades(nd):
    """nest_data trades: 'w' = 'dd/mm HH:MM' UTC, p = money, dir A/V, lot, dur (min)"""
    import calendar
    R = []
    yr = time.gmtime().tm_year
    for t in nd.get("trades") or []:
        try:
            ts = calendar.timegm(time.strptime("%s/%d %s" % (str(t["w"])[:5], yr, str(t["w"])[6:11]), "%d/%m/%Y %H:%M"))
        except Exception:
            continue
        if ts > time.time() + 86400:
            ts -= 365 * 86400
        dur = t.get("dur")
        R.append({"t": ts, "y": float(t.get("p") or 0), "attrs": {
            "side": "buy" if t.get("dir") == "A" else "sell", "lot": str(t.get("lot")),
            "length": ("under 15 min" if (dur or 0) < 15 else "15-60 min" if (dur or 0) < 60 else "over 1 h") if dur is not None else "?"}})
    return R
