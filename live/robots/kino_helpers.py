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
    own = False
    if mission and pay > 0:
        cap, why2 = _job_cap(mission)
        if cap is None:
            # 2026-11-13 (Pekos's toys: "the helper task was refused because he hasn't prepaid" -> Kino fell back to a plain
            # request and Matsy got no gig card): a job nobody prepaid for others is paid from Kino's own helper budget
            if pay > PER_TASK:
                return ("nothing was prepaid for others on that job, so it comes from your own budget: %.0f EUR is over your "
                        "%.0f EUR a task - make it smaller, or quote the client for it (#prix ... | tiers N)" % (pay, PER_TASK))
            own = True
        elif pay > cap + 0.005:
            return "%.2f EUR is more than the client prepaid for others on this job (%.2f left) - negotiate lower or ask the client" % (pay, cap)
    elif pay > PER_TASK:
        return "%.0f EUR is over the %.0f EUR limit for one task - make it smaller" % (pay, PER_TASK)

    # 2026-11-14 (watch: H2 = the same Leboncoin ad as H1, which Matsy had already accepted): a task that looks like one
    # still open / accepted for the same job is that task
    _d0 = _j()
    _wd = lambda s_: set(re.findall(r"\w{4,}", str(s_).lower()))
    for t0 in _d0["tasks"]:
        # one task at a time per job (words do not compare across languages: H1 English, H2 French)
        if t0["status"] in ("open", "asking", "accepted") and mission and mission in (t0.get("mission"), t0.get("for_mission")):
            return ("task %s is already %s for this job (%s) - one at a time: finish it (help_done) or cancel it first"
                    % (t0["id"], t0["status"], t0.get("helper") or "waiting"))

    def f(d):
        d["n"] = int(d.get("n") or 0) + 1
        tid = "H%d" % d["n"]
        d["tasks"].append({"id": tid, "t": time.time(), "what": what[:600], "why": why[:300], "proof": proof[:300], "pay": pay,
                           "place": str(place or "")[:120], "due": time.time() + float(hours or 48) * 3600, "status": "open", "mission": "" if own else str(mission or "")[:20], "for_mission": str(mission or "")[:20],
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
    try:                                       # 2026-11-13: Kino Chat users open to paid gigs
        L.append(workers_line())
    except Exception:
        pass
    return "\n".join(L)


def week_line(now=None):
    now = now or time.time()
    d = _j()
    W = [t for t in d["tasks"] if float(t["t"]) >= now - 7 * 86400]
    paid_ = [t for t in W if t["status"] == "paid"]
    return "tasks given %d, done %d, paid %d (%.2f EUR), helpers in all %d" % (
        len(W), sum(1 for t in W if t["status"] in ("approved", "awaiting_payment", "paid")), len(paid_),
        sum(float(t.get("price") or 0) for t in paid_), len(d["helpers"]))


# ---------------------------------------------------------------- gigs in Kino Chat (2026-11-13)
# Owner: "build it - so even existing users who use Kino Chat for whatever can also, if they want, accept gig offers".
# A Kino Chat user opts in (menu: small paid missions) -> Kino can OFFER them a task: a card in their chat with accept /
# decline, then "send the proof" (text + photo). Every answer reaches Kino at once (an urge) and moves the task.
ON_OFFER = None                     # set by the app: (uid, gig dict) -> posts the card in their chat
ON_GIG_UPDATE = None                # set by the app: (uid, tid, status) -> updates the card's status in their chat
PROOFS = os.path.join(HERE, "helper_proofs")


def gig_optin(uid, on=True, name="", skills="", city="", email=""):
    def f(d):
        W = d.setdefault("workers", {})
        w = W.setdefault(uid, {"since": time.time()})
        w.update(on=bool(on), name=str(name or w.get("name") or uid)[:60], t=time.time())
        if skills:
            w["skills"] = str(skills)[:160]
        if city:
            w["city"] = str(city)[:60]
        if "@" in str(email or ""):
            w["email"] = str(email).strip()[:120]      # 13/11: gig offers also go by email
        return w
    w = _mut(f)
    _log("OPTIN %s %s" % (uid, "on" if on else "off"))
    return w


def workers(on_only=True):
    return {u: w for u, w in (_j().get("workers") or {}).items() if w.get("on") or not on_only}


def workers_line():
    W = workers()
    if not W:
        return "Kino Chat users open to paid gigs: none yet"
    return "Kino Chat users open to paid gigs (offer with help_offer task + uid): " + "; ".join(
        "%s uid=%s%s%s (done %d)" % (w.get("name") or u, u, (", " + w["city"]) if w.get("city") else "",
                                     (", " + w["skills"]) if w.get("skills") else "", int(w.get("done") or 0)) for u, w in list(W.items())[:12])


def offer(tid, uid):
    """Kino offers task tid to a Kino Chat user who opted in: a card in their chat"""
    d = _j()
    t = _t(d, tid)
    if not t:
        return "no task %s" % tid
    w = (d.get("workers") or {}).get(uid)
    if not w or not w.get("on"):
        return "%s has not opted in to paid gigs - only people who said yes in their menu get offers" % uid
    if t["status"] not in ("open", "asking"):
        return "task %s is already %s" % (tid, t["status"])
    if any(o.get("uid") == uid for o in t.get("offers") or []):
        return "already offered to %s" % uid
    gig = {"tid": t["id"], "what": t["what"], "place": t.get("place") or "", "due": int(t.get("due") or 0),
           "pay": float(t.get("pay") or 0), "proof": t.get("proof") or "", "status": "sent"}

    def f(dd):
        tt = _t(dd, tid)
        tt.setdefault("offers", []).append({"uid": uid, "t": time.time(), "status": "sent"})
        if tt["status"] == "open":
            tt["status"] = "asking"
    _mut(f)
    try:
        if ON_OFFER:
            ON_OFFER(uid, gig)
    except Exception as e:
        _log("ON_OFFER error %s" % e)
        return "the card could not be posted: %s" % e
    _log("OFFER %s -> %s" % (tid, uid))
    return "offered %s to %s - a card with accept / decline is in their chat; their answer reaches you at once" % (tid, w.get("name") or uid)


def gig_answer(uid, tid, act, text="", photo=""):
    """the person's tap on the card: accept | decline | proof"""
    d = _j()
    t = _t(d, tid)
    if not t or t.get("status") == "cancelled":
        return {"ok": False, "err": "gone"}
    o = next((x for x in t.get("offers") or [] if x.get("uid") == uid), None)
    if o is None:
        return {"ok": False, "err": "not offered"}
    w = (d.get("workers") or {}).get(uid) or {}
    name = w.get("name") or uid
    path = ""                                  # the proof photo (set below only for a proof - the urge text uses it)
    if act == "accept":
        if t.get("helper") and t["helper"].lower() != name.lower():
            st = "taken"
        else:
            accept(tid, name, t.get("pay") or 0, "chat:" + uid)
            st = "accepted"
    elif act == "decline":
        st = "declined"
    elif act == "proof":
        if o.get("status") != "accepted" and not (t.get("helper") or "").lower() == name.lower():
            return {"ok": False, "err": "accept first"}
        path = ""
        if photo and str(photo).startswith("data:image"):
            try:
                import base64
                os.makedirs(PROOFS, exist_ok=True)
                path = os.path.join(PROOFS, "%s_%d.jpg" % (tid, int(time.time())))
                open(path, "wb").write(base64.b64decode(str(photo).split(",", 1)[1]))
            except Exception:
                path = ""
        st = "proof_sent"

        def fp(dd):
            tt = _t(dd, tid)
            tt.setdefault("proofs_in", []).append({"t": time.time(), "uid": uid, "text": str(text or "")[:1000], "photo": path})
        _mut(fp)
    else:
        return {"ok": False, "err": "act"}

    def f(dd):
        tt = _t(dd, tid)
        for x in tt.get("offers") or []:
            if x.get("uid") == uid:
                x["status"] = st
                x["t_answer"] = time.time()
    _mut(f)
    _log("GIG %s %s %s" % (tid, uid, st))
    # 2026-11-13 (watch: Matsy accepted the Leboncoin gig at 21:48; at 23:36 the toys job still told Pekos "nobody has agreed"):
    # the client's job this task serves hears it at once and wakes up
    _mid = t.get("mission") or t.get("for_mission")
    if _mid:
        try:
            import kino_missions as KMg
            KMg.update(_mid, next_h=0.25, note={"accepted": "HELPER %s ACCEPTED task %s (%s) - it is being done; tell the client "
                                                            "plainly that it is in hand, no 'paste it yourself'" % (name, tid, t["what"][:80]),
                                                "taken": "", "declined": "helper %s declined task %s - offer it to someone else" % (name, tid),
                                                "proof_sent": "HELPER %s SENT THE PROOF for task %s: \"%s\"%s - check it, then tell the client the "
                                                              "result" % (name, tid, str(text or "")[:200], " + photo" if path else "")}.get(st) or "")
        except Exception:
            pass
    try:
        if ON_GIG_UPDATE:
            ON_GIG_UPDATE(uid, tid, st)
    except Exception:
        pass
    try:
        import kino_urge as KU
        msg = {"accepted": "accepted your task %s - it is theirs now, tell them anything they need" % tid,
               "taken": "wanted task %s but someone already has it - thank them, next time" % tid,
               "declined": "cannot do task %s - offer it to someone else" % tid,
               "proof_sent": "sent the proof for task %s: \"%s\"%s - check it (help_done ok true/false), then help_pay" % (
                   tid, str(text or "")[:300], " + a photo (%s)" % path if path else "")}[st]
        KU.add("kino", "A HELPER ANSWERED - %s %s" % (name, msg))
    except Exception:
        pass
    return {"ok": True, "status": st}
