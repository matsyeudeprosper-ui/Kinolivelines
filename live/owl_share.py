"""The profit share (2026-10-03, owner): "I take 30 % of their profit; if
they made no profit I get nothing."

For every member whose account the robot trades (the Automatique package):
  - profit = the robot's CLOSED trades on that account, net, from its own
    journal (bos_journal_<uid>.csv) - never the balance, so deposits and
    withdrawals cannot pollute it;
  - a HIGH-WATER MARK: the share is taken only on profit ABOVE the
    account's previous best cumulative result, so nobody pays for getting
    back to where they were;
  - a small fixed base per month (covers the VPS and a losing month);
  - a statement on the 1st for the month that just ended, 7 days of
    grace, then the robot pauses on that account until it is settled;
    paying lifts the pause by itself.

Everything lives in owl_share.json:
  {"cfg": {"on": true, "pct": 30, "base_usd": 9, "grace_days": 7},
   "accounts": {uid: {"hwm": 12.3, "since": ts,
                      "periods": [{"ym": "2026-10", "profit": .., "above": .., "share": .., "base": ..,
                                   "due": .., "status": "open|paid|waived|overdue", "issued": ts, "paid": ts, "how": ".."}]}}}

    python owl_share.py                 # every account, this month so far
    python owl_share.py --close 2026-09 # issue September's statements (idempotent)
"""
import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(DIR, "owl_share.json")
USERS = os.path.join(DIR, "owl_nest_users.json")
ENTS = os.path.join(DIR, "owl_entitlements.json")
OWNER_UIDS = ("kino", "std", "expenses")
DEFAULT_CFG = {"on": True, "pct": 30.0, "base_usd": 9.0, "grace_days": 7}


def _lj(p, d):
    try:
        v = json.load(io.open(p, encoding="utf-8"))
        return v if v is not None else d
    except Exception:
        return d


def _sj(p, obj):
    tmp = p + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def load():
    doc = _lj(FILE, {})
    if not isinstance(doc, dict):
        doc = {}
    cfg = dict(DEFAULT_CFG)
    cfg.update(doc.get("cfg") or {})
    doc["cfg"] = cfg
    doc.setdefault("accounts", {})
    return doc


def save(doc):
    _sj(FILE, doc)


def cfg():
    return load()["cfg"]


def on():
    return bool(cfg().get("on"))


# ---------------------------------------------------------------- the journal
# the same mapping the app uses (two accounts predate the naming rule)
JOURNAL_OF = {"u224016179": "bos_journal_valere.csv", "bos": "bos_journal.csv"}


def journal(uid):
    return os.path.join(DIR, JOURNAL_OF.get(uid, f"bos_journal_{uid}.csv"))


def closed(uid):
    """[(exit_ts, profit_usd)] of the robot's closed trades on that account,
    adds included (they are the robot's money too), sorted."""
    out = []
    try:
        with open(journal(uid), encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                x = r.get("exit_time_utc")
                if not x:
                    continue
                try:
                    t = datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()
                    out.append((t, float(r.get("profit_usd") or 0.0)))
                except Exception:
                    continue
    except Exception:
        pass
    out.sort()
    return out


def cum_at(rows, t):
    return round(sum(p for x, p in rows if x < t), 2)


def month_bounds(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    a = datetime(y, m, 1, tzinfo=timezone.utc)
    b = datetime(y + (m // 12), (m % 12) + 1, 1, tzinfo=timezone.utc)
    return a.timestamp(), b.timestamp()


def ym_of(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")


def prev_ym(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


# ---------------------------------------------------------------- who pays
def _users():
    u = _lj(USERS, [])
    return {x.get("id"): x for x in u} if isinstance(u, list) else {}


def family(uid, ents=None, now=None):
    """The robot trades this account (the Automatique package). With the
    share on, the package has no end date: it runs while statements are
    settled (share_blocked is set by the overdue sweep)."""
    now = now or time.time()
    e = (ents if ents is not None else _lj(ENTS, {})).get(uid) or {}
    if not (e.get("family") or e.get("family_until")):
        return False
    if on():
        return not e.get("share_blocked")
    if e.get("family_until"):
        return float(e["family_until"]) > now
    return bool(e.get("family"))


def eligible(now=None):
    """uid -> user, for every account the share applies to."""
    now = now or time.time()
    users, ents = _users(), _lj(ENTS, {})
    out = {}
    for uid, u in users.items():
        if uid in OWNER_UIDS or u.get("public") or not u.get("trade"):
            continue
        e = ents.get(uid) or {}
        if not (e.get("family") or e.get("family_until")):
            continue
        out[uid] = u
    return out


# ---------------------------------------------------------------- the numbers
def preview(uid, now=None, doc=None):
    """This month so far, for one account."""
    now = now or time.time()
    doc = doc or load()
    c = doc["cfg"]
    acc = doc["accounts"].get(uid) or {}
    rows = closed(uid)
    a, _ = month_bounds(ym_of(now))
    cum_now = cum_at(rows, now + 1)
    cum_start = cum_at(rows, a)
    hwm = float(acc.get("hwm") or 0.0)
    above = max(0.0, cum_now - max(hwm, 0.0))
    share = round(above * float(c["pct"]) / 100.0, 2)
    return {"ym": ym_of(now), "profit": round(cum_now - cum_start, 2), "cum": cum_now, "hwm": round(hwm, 2),
            "above": round(above, 2), "share": share, "base": float(c["base_usd"]),
            "due": round(share + float(c["base_usd"]), 2), "pct": float(c["pct"]), "trades": sum(1 for x, _ in rows if a <= x < now + 1)}


def close_month(ym, now=None):
    """Issue the statement of month `ym` for every eligible account. Safe
    to call twice: a period already issued is left alone. Returns the
    periods issued this call: [(uid, period)]."""
    now = now or time.time()
    doc = load()
    c = doc["cfg"]
    a, b = month_bounds(ym)
    issued = []
    for uid in eligible(now):
        acc = doc["accounts"].setdefault(uid, {"hwm": 0.0, "since": int(now), "periods": []})
        if any(p.get("ym") == ym for p in acc["periods"]):
            continue
        rows = closed(uid)
        if not any(a <= x < b for x, _ in rows) and not acc["periods"]:
            continue                      # nothing traded yet: no statement, no base
        cum_end, cum_start = cum_at(rows, b), cum_at(rows, a)
        hwm = float(acc.get("hwm") or 0.0)
        above = max(0.0, cum_end - max(hwm, 0.0))
        share = round(above * float(c["pct"]) / 100.0, 2)
        p = {"ym": ym, "profit": round(cum_end - cum_start, 2), "hwm_before": round(hwm, 2), "above": round(above, 2),
             "share": share, "base": float(c["base_usd"]), "due": round(share + float(c["base_usd"]), 2),
             "pct": float(c["pct"]), "status": "open", "issued": int(now)}
        acc["hwm"] = round(max(hwm, cum_end), 2)
        acc["periods"].append(p)
        issued.append((uid, p))
    save(doc)
    return issued


def latest(uid, doc=None):
    doc = doc or load()
    ps = (doc["accounts"].get(uid) or {}).get("periods") or []
    return ps[-1] if ps else None


def open_periods(doc=None):
    doc = doc or load()
    out = []
    for uid, acc in doc["accounts"].items():
        for p in acc.get("periods") or []:
            if p.get("status") in ("open", "overdue"):
                out.append((uid, p))
    return out


def statement(uid, now=None):
    """What the member sees: the current month so far + the last
    statement (open, overdue, paid...)."""
    doc = load()
    return {"on": bool(doc["cfg"].get("on")), "pct": float(doc["cfg"]["pct"]), "base": float(doc["cfg"]["base_usd"]),
            "grace_days": int(doc["cfg"]["grace_days"]),
            "now": preview(uid, now, doc), "last": latest(uid, doc),
            "blocked": bool((_lj(ENTS, {}).get(uid) or {}).get("share_blocked"))}


# ---------------------------------------------------------------- settlement
def _pause(uid, paused, by):
    p = os.path.join(DIR, f"owl_trading_pause_{uid}.json")
    if paused:
        _sj(p, {"paused": True, "by": by, "t": int(time.time())})
        return True
    cur = _lj(p, {})
    if cur.get("paused") and cur.get("by") in ("share", "expiry"):
        _sj(p, {"paused": False, "by": by, "t": int(time.time())})
        return True
    return False


def _block(uid, blocked):
    ents = _lj(ENTS, {})
    e = ents.setdefault(uid, {})
    if blocked:
        e["share_blocked"] = int(time.time())
    else:
        e.pop("share_blocked", None)
    e["updated"] = int(time.time())
    _sj(ENTS, ents)


def mark_paid(uid, ym, how="kino", amount=None):
    """The owner's "Marquer payé" or a finished NOWPayments invoice. Lifts
    the share pause and the block. Returns the period or None."""
    doc = load()
    acc = doc["accounts"].get(uid)
    if not acc:
        return None
    p = next((x for x in acc.get("periods") or [] if x.get("ym") == ym), None)
    if not p:
        return None
    p["status"] = "paid"
    p["paid"] = int(time.time())
    p["how"] = how
    if amount is not None:
        p["paid_amount"] = float(amount)
    save(doc)
    if not open_periods(doc):
        _block(uid, False)
        _pause(uid, False, "share_paid")
    return p


def waive(uid, ym, why="kino"):
    doc = load()
    acc = doc["accounts"].get(uid)
    p = next((x for x in (acc or {}).get("periods") or [] if x.get("ym") == ym), None)
    if not p:
        return None
    p["status"] = "waived"
    p["paid"] = int(time.time())
    p["how"] = why
    save(doc)
    if not open_periods(doc):
        _block(uid, False)
        _pause(uid, False, "share_waived")
    return p


def overdue_sweep(now=None):
    """Open statements past their grace: mark overdue, block the package,
    pause the robot on that account. Returns [(uid, period)] newly overdue."""
    now = now or time.time()
    doc = load()
    grace = int(doc["cfg"]["grace_days"]) * 86400
    newly = []
    for uid, acc in doc["accounts"].items():
        for p in acc.get("periods") or []:
            if p.get("status") == "open" and float(p.get("due") or 0) > 0 and now - float(p.get("issued") or now) > grace:
                p["status"] = "overdue"
                p["overdue"] = int(now)
                newly.append((uid, p))
    if newly:
        save(doc)
        for uid, p in newly:
            _block(uid, True)
            _pause(uid, True, "share")
    return newly


def owner_view(now=None):
    """For Le Nid: every account's month so far and its open statements."""
    now = now or time.time()
    doc = load()
    users = _users()
    rows = []
    for uid in eligible(now):
        pv = preview(uid, now, doc)
        last = latest(uid, doc)
        rows.append({"uid": uid, "name": (users.get(uid) or {}).get("name") or uid, "now": pv, "last": last})
    opn = open_periods(doc)
    return {"cfg": doc["cfg"], "rows": rows,
            "expected": round(sum(r["now"]["due"] for r in rows), 2),
            "open": round(sum(float(p.get("due") or 0) for _, p in opn if p.get("status") == "open"), 2),
            "overdue": [uid for uid, p in opn if p.get("status") == "overdue"]}


if __name__ == "__main__":
    if "--close" in sys.argv:
        ym = sys.argv[sys.argv.index("--close") + 1]
        for uid, p in close_month(ym):
            print(uid, p)
        print("closed", ym)
    else:
        v = owner_view()
        for r in v["rows"]:
            print(f"{r['name']:12s} month {r['now']['profit']:+8.2f}  above hwm {r['now']['above']:7.2f}  share {r['now']['share']:6.2f} + base {r['now']['base']:.0f} = {r['now']['due']:.2f}")
        print("expected this month:", v["expected"], "| open:", v["open"], "| overdue:", v["overdue"])
