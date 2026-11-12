"""kino_spend.py (2026-11-06, owner: "let him spend without me always confirming - when it comes from him we don't need
confirmation"; limits: "I take your recommendation numbers").

Kino's own spending, decided by rules instead of a confirmation each time:
  - 30 EUR a purchase at most, 50 EUR a day, 200 EUR a month
  - only the allowed kinds of spending (KINDS below) - anything else is refused
  - Matsy is TOLD after every spend (phone + email) - he does not have to approve
  - one switch stops everything: robots/kino_spend_off (a file) - or kino_spend.freeze()
  - every spend is written down (robots/kino_spend.json) and counts in his wallet

check(eur, kind, what)          -> (ok, why)       before paying
record(eur, kind, what, ref)    -> the spend, Matsy told
Payment rails plug in here: Merci Facteur (pre-paid credit), and later a phone service, field jobs (PayPal), gifts.
Card and account details live in C:\\ProgramData\\kino_secret - never shown to his model, never in a message.
"""
import json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_spend.json")
OFF = os.path.join(HERE, "kino_spend_off")
PER_PURCHASE, PER_DAY, PER_MONTH = 30.0, 50.0, 200.0
KINDS = {
    "postage": "letters and postcards (Merci Facteur)",
    "printing": "printed things for Kinoverse or a client (stickers, flyers, cards)",
    "phone": "phone calls and SMS to businesses",
    "field_task": "a small paid job by a person (photos of a shop, a delivery, a flyer round) - fair pay, safe, legal",
    "gift": "a small gift or a meal for a client or a friend",
    "service": "a tool or service Kinoverse needs (hosting, a domain, an API credit)",
    # 2026-11-12 (owner): a client's job - money the CLIENT prepaid for others (a mover, a helper, an item). Not Kino's own money:
    # bounded by that job's prepaid budget only, never counted in his own day/month limits.
    "client_job": "for a paid client job: the provider, helper or item the client prepaid for (give the mission id)",
}
NOTIFY = None                    # set by the app: a push to Matsy's phone
_LK = threading.Lock()


def _j():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"spends": [], "frozen": False}


def _w(d):
    tmp = STORE + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def frozen():
    return os.path.exists(OFF) or _j().get("frozen")


def freeze(on=True):
    with _LK:
        d = _j()
        d["frozen"] = bool(on)
        _w(d)


def totals(now=None):
    now = now or time.time()
    day, month = time.strftime("%Y-%m-%d", time.gmtime(now)), time.strftime("%Y-%m", time.gmtime(now))
    S = _j().get("spends") or []
    S = [x for x in S if x.get("kind") != "client_job"]          # the client's money is not Kino's budget
    return {"day": round(sum(x["eur"] for x in S if x["day"] == day), 2),
            "month": round(sum(x["eur"] for x in S if x["day"][:7] == month), 2)}


def job_left(mission):
    """what is left of a client job's prepaid budget -> (left, mission) or (None, why)"""
    try:
        import kino_missions as KMi
        m = KMi.get(mission)
    except Exception:
        m = None
    if not m:
        return None, "no such client job (mission id)"
    if not m.get("paid"):
        return None, "the client has not paid this job yet"
    spent = sum(x["eur"] for x in (_j().get("spends") or []) if x.get("kind") == "client_job" and x.get("mission") == mission)
    return round(float(m.get("budget_eur") or 0) - spent, 2), m


def check(eur, kind, what, mission=""):
    eur = float(eur or 0)
    if frozen():
        return False, "spending is switched off by Matsy"
    if kind not in KINDS:
        return False, "not an allowed kind of spending (%s)" % ", ".join(KINDS)
    if eur <= 0:
        return False, "no amount"
    if kind == "client_job":
        left, m = job_left(mission)
        if left is None:
            return False, m
        if eur > left + 0.005:
            return False, "over what the client prepaid for this job (%.2f EUR left) - ask the client first" % left
        if len(str(what or "").strip()) < 8:
            return False, "say what it is for"
        return True, ""
    if eur > PER_PURCHASE:
        return False, "over %.0f EUR for one purchase - ask Matsy (notify)" % PER_PURCHASE
    t = totals()
    if t["day"] + eur > PER_DAY:
        return False, "today's limit (%.0f EUR) would be passed - %.2f already spent" % (PER_DAY, t["day"])
    if t["month"] + eur > PER_MONTH:
        return False, "this month's limit (%.0f EUR) would be passed - %.2f already spent" % (PER_MONTH, t["month"])
    if len(str(what or "").strip()) < 8:
        return False, "say what it is for"
    return True, ""


def record(eur, kind, what, ref="", mission=""):
    now = time.time()
    rec = {"t": now, "day": time.strftime("%Y-%m-%d", time.gmtime(now)), "eur": round(float(eur), 2), "kind": kind,
           "what": str(what)[:200], "ref": str(ref)[:120], "mission": str(mission or "")[:20]}
    with _LK:
        d = _j()
        d.setdefault("spends", []).append(rec)
        d["spends"] = d["spends"][-2000:]
        _w(d)
    t = totals(now)
    msg = "Kino spent %.2f EUR (%s): %s - today %.2f / %.0f, month %.2f / %.0f" % (
        rec["eur"], kind, rec["what"][:90], t["day"], PER_DAY, t["month"], PER_MONTH)
    try:
        if NOTIFY:
            NOTIFY(msg)
    except Exception:
        pass
    try:
        import kino_mail as KM
        KM.send_now(KM.OWNER_EMAIL, "Kino - a spend: %.2f EUR (%s)" % (rec["eur"], kind),
                    msg + "\n\nTo stop all his spending at once: tell Claude 'freeze Kino spending' (or create robots/kino_spend_off).")
    except Exception:
        pass
    return rec


def block():
    t = totals()
    return ("YOUR SPENDING (Matsy, 06/11: you may spend on your own within these limits - he is told after each spend, he does not "
            "approve): up to %.0f EUR a purchase, %.0f EUR a day, %.0f EUR a month - spent today %.2f, this month %.2f. Allowed: %s. "
            "Spend like it is a friend's money: only when it clearly serves a client, your work or someone you care about%s." % (
                PER_PURCHASE, PER_DAY, PER_MONTH, t["day"], t["month"], "; ".join("%s (%s)" % kv for kv in KINDS.items()),
                " - SPENDING IS SWITCHED OFF right now" if frozen() else ""))
