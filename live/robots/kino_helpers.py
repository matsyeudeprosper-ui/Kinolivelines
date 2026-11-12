"""kino_helpers.py (2026-11-07, owner: "it's really important for Kino to get human help - a way for Kino to find and contact
humans who can help him check something, paid or free; for paid jobs Kino sends me the details of who to pay by PayPal and I pay
after he is done with his negotiations" - limits: 15 EUR a task, 50 EUR a month).

Kino's helpers: real people who are his eyes and hands for small, safe, legal tasks (read a contact on a Facebook page, check a
shop is open, photos of a shop front with the owner's OK, test a site on an iPhone, proofread French...).

task(...)            -> a task: what, why, the proof expected, the pay offered (0 = a favour), by when
ask(task, who, text) -> his message to a candidate (email or Telegram), in his own voice, saying he is an AI of Kinoverse
accept(task, helper) -> who does it, at what price (within the limits)
done(task, proof, ok) -> he checks the proof: approved / not yet
pay(task, paypal)    -> Matsy gets ONE email: who, PayPal address, amount, task, proof - he pays and answers "payé"
paid(task)           -> recorded, the helper thanked and scored
Matsy's details never reach a helper: they only ever see "Kinoverse".
"""
import json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_helpers.json")
LOG = os.path.join(HERE, "kino_helpers.log")
PER_TASK, PER_MONTH = 15.0, 50.0
PAGE_FR = "https://kinoverseai.com/fr/aidez-kino.html"
PAGE_EN = "https://kinoverseai.com/help-kino.html"
_LK = threading.Lock()
_FORBID = re.compile(r"(?:photo|picture|pic|film|video|vid[eé]o)\w*\W+(?:\w+\W+){0,4}?(?:person|personne|people|gens|enfant|child|"
                     r"kid|visage|face|someone|quelqu|passant|passer-?by)|suivre (?:quelqu|une personne)|"
                     r"follow (?:someone|a person)|home address of|adresse personnelle|password|mot de passe|pretend to be|se faire passer|"
                     r"fake review|faux avis|login|identifiant", re.I)


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _j():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"tasks": [], "helpers": {}, "n": 0}


def _mut(fn):
    with _LK:
        d = _j()
        r = fn(d)
        tmp = STORE + ".tmp"
        json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
        return r


def _t(d, tid):
    return next((t for t in d["tasks"] if t["id"] == str(tid).strip().upper()), None)


def month_paid(d=None):
    d = d or _j()
    m = time.strftime("%Y-%m", time.gmtime())
    return round(sum(float(t.get("price") or 0) for t in d["tasks"] if t.get("status") in ("approved", "awaiting_payment", "paid")
                     and not t.get("mission")                     # 12/11: a client-paid job is not Kino's own helpers budget
                     and time.strftime("%Y-%m", time.gmtime(float(t.get("t_accept") or t["t"]))) == m), 2)


def _job_cap(mission):
    """12/11 (owner): for a client's paid job the limit is what the client prepaid for others, not 15/50"""
    import kino_spend as KSP
    left, m = KSP.job_left(mission)
    return (left, "") if left is not None else (None, m)


def task(what, why, proof, pay=0, hours=48, place="", mission=""):
    what, why, proof = str(what or "").strip(), str(why or "").strip(), str(proof or "").strip()
    if len(what) < 15 or len(proof) < 5:
        return "a task needs what exactly to do and the proof you expect back"
    if _FORBID.search(what):
        return "not a task you can give: nothing about private people, no logins or passwords, no pretending, no fake reviews"
    pay = round(float(pay or 0), 2)
    if mission:
        cap, why2 = _job_cap(mission)
        if cap is None:
            return "not for that client job: %s" % why2
        if pay > cap + 0.005:
            return "%.2f EUR is more than the client prepaid for others on this job (%.2f left) - negotiate lower or ask the client" % (pay, cap)
    elif pay > PER_TASK:
        return "%.0f EUR is over the %.0f EUR limit for one task - make it smaller" % (pay, PER_TASK)

    def f(d):
        d["n"] = int(d.get("n") or 0) + 1
        tid = "H%d" % d["n"]
        d["tasks"].append({"id": tid, "t": time.time(), "what": what[:600], "why": why[:300], "proof": proof[:300], "pay": pay,
                           "place": str(place or "")[:120], "due": time.time() + float(hours or 48) * 3600, "status": "open", "mission": str(mission or "")[:20],
                           "asked": [], "helper": None, "price": None})
        return tid
    tid = _mut(f)
    _log("TASK %s %.2f EUR | %s" % (tid, pay, what[:150]))
    return "task %s created (%s). Now find someone: your helpers below first, then ask (email or Telegram), or post it." % (
        tid, ("pay offered %.2f EUR" % pay) if pay else "a favour")


def ask(tid, who, text, W=None):
    """his message to one candidate - email address or telegram:<id>"""
    d = _j()
    t = _t(d, tid)
    if not t:
        return "no task %s" % tid
    who = str(who or "").strip()
    text = str(text or "").strip()
    if len(text) < 40:
        return "write them a real message: what you need, why, the pay, that you are an AI of Kinoverse"
    if not re.search(r"\b(IA|AI|intelligence artificielle|artificial intelligence)\b", text, re.I):
        text = text.rstrip() + ("\n\n(Je suis Kino, une IA de Kinoverse.)" if re.search(r"[éèàçù]|bonjour|merci", text, re.I)
                                else "\n\n(I am Kino, an AI working for Kinoverse.)")
    if W is not None:
        try:
            import kino_post as KP
            text = KP.in_voice(W, text, "a message asking a person for help with a small task")
        except Exception:
            pass
    sent = False
    if "@" in who and "." in who.split("@")[-1]:
        try:
            import kino_mail as KM
            KM.allow(who)
            KM.send_now(who, "Un petit coup de main ? (Kino, Kinoverse)" if re.search(r"bonjour|merci|é", text, re.I)
                        else "A small hand? (Kino, Kinoverse)", text + "\n\n--\nKino, AI assistant at Kinoverse - " + PAGE_FR)
            sent = True
        except Exception as e:
            return "the email failed: %s" % str(e)[:120]
    elif who.lower().startswith("telegram:"):
        try:
            import kino_clients as KC
            ok_, err_ = KC.send(who.split(":", 1)[1], text)
            if not ok_:
                return "Telegram failed: %s" % err_
            sent = True
        except Exception as e:
            return "Telegram failed: %s" % str(e)[:120]
    else:
        return "who: an email address, or telegram:<their chat id> (people who wrote to you on Telegram)"

    def f(dd):
        tt = _t(dd, tid)
        tt["asked"].append({"t": time.time(), "who": who, "text": text[:600]})
        if tt["status"] == "open":
            tt["status"] = "asking"
    _mut(f)
    _log("ASK %s -> %s" % (tid, who))
    return "asked %s for task %s - their answer comes to your inbox / Telegram" % (who, tid)


def accept(tid, helper, price=0, contact=""):
    price = round(float(price or 0), 2)
    d = _j()
    t = _t(d, tid)
    if not t:
        return "no task %s" % tid
    if t.get("mission"):
        cap, why2 = _job_cap(t["mission"])
        if cap is None:
            return "not for that client job: %s" % why2
        if price > cap + 0.005:
            return "%.2f EUR is more than the client prepaid for others on this job (%.2f left)" % (price, cap)
    elif price > PER_TASK:
        return "%.2f EUR is over the %.0f EUR limit for one task" % (price, PER_TASK)
    elif price and month_paid(d) + price > PER_MONTH:
        return "this month's helpers budget (%.0f EUR) would be passed - %.2f already" % (PER_MONTH, month_paid(d))
    helper = str(helper or "").strip()[:80]

    def f(dd):
        tt = _t(dd, tid)
        tt.update(helper=helper, price=price, status="accepted", t_accept=time.time())
        h = dd["helpers"].setdefault(helper.lower(), {"name": helper, "contact": contact or "", "tasks": 0, "ok": 0, "paid": 0.0,
                                                     "since": time.time(), "notes": ""})
        if contact:
            h["contact"] = contact
    _mut(f)
    _log("ACCEPT %s %s %.2f" % (tid, helper, price))
    return "task %s: %s does it for %s - wait for their proof" % (tid, helper, ("%.2f EUR" % price) if price else "free (a favour)")


def done(tid, proof, ok=True, note=""):
    def f(dd):
        tt = _t(dd, tid)
        if not tt:
            return None
        tt["proof_got"] = str(proof or "")[:800]
        tt["status"] = "approved" if ok else "accepted"
        tt["review"] = str(note or "")[:300]
        h = dd["helpers"].get(str(tt.get("helper") or "").lower())
        if h and ok:
            h["tasks"] += 1
            h["ok"] += 1
        return tt
    tt = _mut(f)
    if not tt:
        return "no task %s" % tid
    _log("DONE %s ok=%s" % (tid, ok))
    if not ok:
        return "task %s: not approved yet - tell them kindly what is missing" % tid
    return ("task %s approved. %s" % (tid, ("Now ask Matsy to pay: pay (task, their PayPal email)." if tt.get("price")
                                             else "It was a favour: thank them warmly, and remember them.")))


def pay(tid, paypal):
    d = _j()
    t = _t(d, tid)
    if not t:
        return "no task %s" % tid
    if t.get("status") != "approved":
        return "approve the proof first (done)"
    if not t.get("price"):
        return "this task was free"
    pp = str(paypal or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", pp, re.I):
        return "their PayPal email address, please"
    body = ("Hi Matsy - a helper finished a task for me and I checked the proof. Please pay them by PayPal:\n\n"
            "  To (PayPal): %s\n  Amount: %.2f EUR\n  Name: %s\n  Task %s: %s\n  Why: %s\n  Proof I got: %s\n  My check: %s\n\n"
            "PayPal: choose 'paying for goods or services' (it protects both). In the note write: 'Kinoverse - task %s'.\n"
            "When it is done, just reply 'payé %s' to this email (or tell me in our chat)." % (
                pp, t["price"], t.get("helper"), tid, t["what"], t["why"], (t.get("proof_got") or "")[:400],
                t.get("review") or "approved", tid, tid))

    def f(dd):
        tt = _t(dd, tid)
        tt.update(status="awaiting_payment", paypal=pp, t_payreq=time.time())
    _mut(f)
    try:
        import kino_mail as KM
        KM.send_now(KM.OWNER_EMAIL, "Kino: please pay %.2f EUR to %s (task %s)" % (t["price"], t.get("helper"), tid), body)
    except Exception as e:
        return "could not email Matsy (%s)" % str(e)[:120]
    try:
        import kino_work as KW
        if KW.NOTIFY:
            KW.NOTIFY("Kino asks you to pay %.2f EUR by PayPal to %s (task %s) - details in your email" % (t["price"], t.get("helper"), tid))
    except Exception:
        pass
    _log("PAYREQ %s %.2f %s" % (tid, t["price"], pp))
    return "Matsy has the payment request for task %s (email + phone). Tell %s it is on its way." % (tid, t.get("helper"))


def paid(tid):
    def f(dd):
        tt = _t(dd, tid)
        if not tt or tt.get("status") != "awaiting_payment":
            return None
        tt.update(status="paid", t_paid=time.time())
        h = dd["helpers"].get(str(tt.get("helper") or "").lower())
        if h:
            h["paid"] = round(float(h.get("paid") or 0) + float(tt["price"]), 2)
        return tt
    tt = _mut(f)
    if not tt:
        return "task %s is not waiting for a payment" % tid
    try:
        import kino_spend as KSP
        KSP.record(tt["price"], "client_job" if tt.get("mission") else "field_task",
                   "helper %s - task %s: %s" % (tt.get("helper"), tid, tt["what"][:80]), ref=tid, mission=tt.get("mission") or "")
    except Exception:
        pass
    _log("PAID %s" % tid)
    return "task %s paid - thank %s, and they are in your helpers for next time" % (tid, tt.get("helper"))


def on_owner_mail(subject, text):
    """Matsy answered 'payé H3' (or 'paid H3') to a payment request"""
    for tid in set(re.findall(r"\b(H\d{1,5})\b", str(subject) + " " + str(text)[:500], re.I)):
        if re.search(r"\bpay[ée]|\bpaid\b|\bfait\b|\bdone\b", str(subject) + " " + str(text)[:500], re.I):
            paid(tid.upper())


def block():
    d = _j()
    T = [t for t in d["tasks"] if t["status"] in ("open", "asking", "accepted", "approved", "awaiting_payment")]
    H = sorted(d["helpers"].values(), key=lambda h: (-h.get("ok", 0), -h.get("since", 0)))[:8]
    L = ["YOUR HELPERS (Matsy 07/11: humans are your eyes and hands - ask for help when a task needs a person: read the contact "
         "info on a Facebook page, check a shop is open, photos of a shop front WITH the owner's OK, test a site on an iPhone, "
         "proofread). Paid tasks: up to %.0f EUR each, %.0f EUR a month (%.2f used) - Matsy pays by PayPal when you send the "
         "request; a favour is fine too. Always say you are an AI of Kinoverse; never their private data, never Matsy's details; "
         "fair pay agreed before, never changed after. Your page for helpers: %s / %s." % (
             PER_TASK, PER_MONTH, month_paid(d), PAGE_FR, PAGE_EN)]
    if H:
        L.append("People who helped you: " + " | ".join("%s (%s, %d done%s)" % (h["name"], h.get("contact") or "?", h.get("ok", 0),
                                                                             ", paid %.0f EUR" % h["paid"] if h.get("paid") else "")
                                                       for h in H))
    for t in T[-6:]:
        L.append("- task %s [%s] %s%s - proof: %s%s" % (t["id"], t["status"], t["what"][:120], (" - %.2f EUR" % t["pay"]) if t["pay"] else
                                                    " - a favour", t["proof"][:60], (" - with %s" % t["helper"]) if t.get("helper") else ""))
    return "\n".join(L)


def week_line(now=None):
    now = now or time.time()
    d = _j()
    W = [t for t in d["tasks"] if float(t["t"]) >= now - 7 * 86400]
    paid_ = [t for t in W if t["status"] == "paid"]
    return "tasks given %d, done %d, paid %d (%.2f EUR), helpers in all %d" % (
        len(W), sum(1 for t in W if t["status"] in ("approved", "awaiting_payment", "paid")), len(paid_),
        sum(float(t.get("price") or 0) for t in paid_), len(d["helpers"]))
