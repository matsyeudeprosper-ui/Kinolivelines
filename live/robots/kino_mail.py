"""kino_mail.py (2026-11-01, owner: "we get him an email address") - Kino's own mailbox, kino@kinoverseai.com (read in the kinoverse26 Gmail box).

Like a person with an email address: new mail arrives in his inbox (a copy goes to C:\\KinoWorld\\inbox so his hands can read
it), it reaches him as a reason to talk or to act, and he can write. Writing to someone he has already been allowed to write to
goes out at once; writing to anyone new becomes a request the owner approves (kino_hands.request, kind "email") - then it goes.
The login (an app password) is in C:\\ProgramData\\kino_secret\\gmail.json, readable by administrators only - never by the kino
user, never in the repo or a log.

Store robots/kino_mail.json (git-ignored): seen ids, approved contacts, sent copies. Log robots/kino_mail.log.
"""
import email, email.header, email.utils, imaplib, json, os, re, smtplib, threading, time
from email.mime.text import MIMEText

HERE = os.path.dirname(os.path.abspath(__file__))
SECRET = r"C:\ProgramData\kino_secret\gmail.json"
WORLD = r"C:\KinoWorld"
STORE = os.path.join(HERE, "kino_mail.json")
LOG = os.path.join(HERE, "kino_mail.log")
_LK = threading.Lock()
OWNER_EMAIL = "matsyeudeprosper@gmail.com"     # the owner: always allowed
# 2026-11-12 (owner: "update all places where we have Gmail to point to the @kinoverse one"): Kino's public address is on his
# own domain. Mail to it (and to any *@kinoverseai.com) is forwarded by Cloudflare Email Routing into the Gmail box, which IMAP
# still reads. Sending goes through Resend SMTP (domain verified, DKIM/SPF), Gmail SMTP only as a fallback.
PUBLIC = "kino@kinoverseai.com"
RESEND = os.path.join(os.path.dirname(SECRET), "resend.json")


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LK:
        d = _load()
        r = fn(d)
        tmp = STORE + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
        os.replace(tmp, STORE)
        return r


def _cred():
    return json.load(open(SECRET, encoding="utf-8"))


def address():
    return PUBLIC


def _dec(s):
    try:
        return str(email.header.make_header(email.header.decode_header(s or "")))
    except Exception:
        return str(s or "")


def _text(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition") or ""):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                except Exception:
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    h = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")
    except Exception:
        return str(msg.get_payload())


def check(first_run_quiet=True):
    """new mail since last time -> list of {id, from, subject, text, t}; copies saved in his inbox folder"""
    c = _cred()
    M = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=40)
    M.login(c["address"], c["app_password"])
    M.select("INBOX", readonly=True)
    ids = M.search(None, "ALL")[1][0].split()
    d = _load()
    seen = set(d.get("seen") or [])
    baseline = not d.get("seen") and first_run_quiet           # the first look: what is there already is not "new"
    new = []
    for i in ids[-30:]:
        typ, data = M.fetch(i, "(BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            continue
        msg = email.message_from_bytes(data[0][1])
        mid = str(msg.get("Message-ID") or i.decode())
        if mid in seen:
            continue
        seen.add(mid)
        item = {"id": mid[-60:], "from": _dec(msg.get("From")), "subject": _dec(msg.get("Subject")), "date": str(msg.get("Date") or ""),
                "text": " ".join(_text(msg).split())[:4000], "t": time.time()}
        try:
            fn = os.path.join(WORLD, "inbox", "%s_%s.txt" % (time.strftime("%Y%m%d_%H%M%S"), re.sub(r"\W+", "", mid)[-12:]))
            open(fn, "w", encoding="utf-8").write("From: %s\nDate: %s\nSubject: %s\n\n%s\n" % (item["from"], item["date"], item["subject"], item["text"]))
        except Exception:
            pass
        if not baseline:
            new.append(item)
    M.logout()

    def f(dd):
        dd["seen"] = sorted(seen)[-2000:]
        dd.setdefault("received", []).extend(new)
        dd["received"] = dd["received"][-100:]
        dd["checked_t"] = time.time()
    _mut(f)
    for x in new:
        _log("IN from %s | %s" % (x["from"], x["subject"][:120]))
        # 2026-11-01 (owner: clients write to him): who writes to him can be answered, and the mail waits for his answer
        a = email.utils.parseaddr(x["from"])[1].lower()
        try:                                       # 2026-11-05 (Kinoverse sales): STOP is honoured at once; a prospect's answer counts
            import kino_sales as KSL
            KSL.on_mail(a, x["subject"], x["text"])
        except Exception:
            pass
        if a == OWNER_EMAIL:                       # 2026-11-07: "payé H3" - Matsy paid a helper
            try:
                import kino_helpers as KHL
                KHL.on_owner_mail(x["subject"], x["text"])
            except Exception:
                pass
        # 2026-11-07: a service's welcome/billing mail ("accounts@dynadot.com", an HTML newsletter) is not a person waiting for him
        _auto = (re.match(r"(accounts?|billing|support|info|news|newsletter|hello|team|mailer|postmaster|bounce|alerts?|security|"
                          r"donotreply|do-not-reply|verify|verification|invoice|receipts?|statements?|notify|notifications?)[@.+-]", a)
                 or re.search(r"@(x\.com|twitter\.com|stripe\.com|paypal\.com|google\.com|merci-facteur[\w.-]*|dynadot\.com|github\.com|"
                              r"cloudflare\.com|amazonses\.com)$", a)
                 or str(x.get("text") or "").lstrip().startswith("<"))
        if a and a != OWNER_EMAIL and not _auto and "noreply" not in a and "no-reply" not in a and "notification" not in a:
            allow(a)
            try:
                import kino_online as KON
                KON.note(a, "email", "%s - %s" % (x["subject"], x["text"][:300]), "in", "mail:" + x["id"], kind="reply")
            except Exception:
                pass
    return new


def contacts():
    return sorted(set(_load().get("contacts") or []) | {OWNER_EMAIL})


def allow(addr):
    a = email.utils.parseaddr(addr)[1].lower()
    if a:
        _mut(lambda d: d.__setitem__("contacts", sorted(set(d.get("contacts") or []) | {a})))
    return a


def _html(body, link, img_cid):
    """the same words as the text version, with the picture of their new site where the link is"""
    import html as _h
    paras = []
    for block in str(body).split("\n\n"):
        t = _h.escape(block).replace("\n", "<br>")
        if link and link in block:
            t = t.replace(_h.escape(link), '<a href="%s">%s</a>' % (link, _h.escape(link)))
            paras.append('<p style="margin:0 0 14px">%s</p><p style="margin:0 0 18px"><a href="%s"><img src="cid:%s" alt="Aperçu de votre nouveau site" '
                         'width="560" style="max-width:100%%;height:auto;border-radius:10px;border:1px solid #ddd"></a></p>' % (t, link, img_cid))
        else:
            paras.append('<p style="margin:0 0 14px">%s</p>' % t)
    return ('<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.55;color:#222;max-width:600px">%s</div>'
            % "".join(paras))


def send_now(to, subject, body, image=None, link=None, files=None):
    """2026-11-07 (owner: "include an image preview of their new site in the email - some people are afraid of links"): with
    image (a file) the email is text + HTML, the picture inline next to the link, clickable"""
    c = _cred()
    if image and os.path.isfile(image):
        from email.mime.multipart import MIMEMultipart
        from email.mime.image import MIMEImage
        cid = "preview%d" % int(time.time())
        m = MIMEMultipart("related")
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(str(body), "plain", "utf-8"))
        alt.attach(MIMEText(_html(body, link, cid), "html", "utf-8"))
        m.attach(alt)
        im = MIMEImage(open(image, "rb").read())
        im.add_header("Content-ID", "<%s>" % cid)
        im.add_header("Content-Disposition", "inline", filename="apercu.jpg")
        m.attach(im)
    else:
        m = MIMEText(str(body), "plain", "utf-8")
    files = [f for f in (files or []) if f and os.path.isfile(f[0] if isinstance(f, (list, tuple)) else f)][:5]
    if files:                                       # 2026-11-08 (owner): a client's CV / letter goes WITH the application
        from email.mime.multipart import MIMEMultipart
        from email.mime.application import MIMEApplication
        outer = MIMEMultipart("mixed")
        outer.attach(m)
        for f in files:
            path, name = (f[0], f[1]) if isinstance(f, (list, tuple)) else (f, os.path.basename(f))
            part = MIMEApplication(open(path, "rb").read(), _subtype="pdf" if path.lower().endswith(".pdf") else "octet-stream")
            part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", name))
            outer.attach(part)
        m = outer
    m["To"] = to
    m["Subject"] = str(subject)[:200]
    m["Reply-To"] = PUBLIC
    rcpt = [email.utils.parseaddr(to)[1]]
    try:
        rk = json.load(open(RESEND, encoding="utf-8"))
        rk = rk.get("send_key") or rk.get("api_key")
        m["From"] = "Kino <%s>" % PUBLIC
        S = smtplib.SMTP_SSL("smtp.resend.com", 465, timeout=40)
        S.login("resend", rk)
        S.sendmail(PUBLIC, rcpt, m.as_string())
        S.quit()
    except Exception as e:
        _log("RESEND FAILED (%s) - via Gmail" % str(e)[:120])
        del m["From"]
        m["From"] = "Kino <%s>" % c["address"]
        S = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=40)
        S.login(c["address"], c["app_password"])
        S.sendmail(c["address"], rcpt, m.as_string())
        S.quit()
    item = {"t": time.time(), "to": to, "subject": str(subject)[:200], "text": str(body)[:4000],
            "files": [(f[1] if isinstance(f, (list, tuple)) else os.path.basename(f)) for f in files]}
    _mut(lambda d: d.setdefault("sent", []).append(item))
    try:
        open(os.path.join(WORLD, "outbox", "%s_sent.txt" % time.strftime("%Y%m%d_%H%M%S")), "w", encoding="utf-8").write(
            "To: %s\nSubject: %s\n\n%s\n" % (to, subject, body))
    except Exception:
        pass
    _log("OUT to %s | %s" % (to, str(subject)[:120]))
    return True


def send(to, subject, body, why="", files=None):
    """he writes: to an allowed contact it goes now; to someone new it waits for the owner's yes"""
    a = email.utils.parseaddr(to)[1].lower()
    if not a or "@" not in a:
        return {"ok": False, "why": "no valid address"}
    if a in contacts():
        if a != OWNER_EMAIL:                       # 2026-11-01: a mail to a client goes through the same second mind as his posts
            try:
                import kino_post as KP, robot_warm as W
                ok, why2 = KP.check(W, "EMAIL to %s\nSubject: %s\n\n%s" % (a, subject, body))
                if not ok:
                    return {"ok": False, "why": "not sent - the check said: %s" % why2}
            except Exception:
                pass
        if a != OWNER_EMAIL and "/kinochat" not in str(body):
            try:                                   # 2026-11-08 (owner): their own Kino Chat link - the same conversation goes on there
                import kino_chatapp as KCA
                fr = bool(re.search(r"[éèàçù]|\b(bonjour|merci|vous|je|tu)\b", str(body), re.I))
                body = str(body).rstrip() + ("\n\n--\nKino · Pour discuter avec moi à tout moment : %s" if fr else
                                             "\n\n--\nKino · To chat with me any time: %s") % KCA.invite_link("mailto:" + a)
            except Exception:
                pass
        send_now(a, subject, body, files=files)
        try:                                       # 2026-11-05: a mail to a client with a running job is news for them
            import kino_sales as KSL
            KSL.client_wrote(a)
        except Exception:
            pass
        try:
            import kino_online as KON
            KON.answered_by(a)
            KON.note(a, "email", "%s - %s" % (subject, str(body)[:300]), "out")
        except Exception:
            pass
        return {"ok": True, "sent": True}
    import kino_hands as KH
    try:                                           # 2026-11-08 (owner refused 2 mails; Kino asked again 90 min later): a refused
        for x in KH._rload():                      # address is not asked again for 14 days
            if x.get("kind") == "email" and x.get("status") in ("refused", "waiting") and time.time() - float(x.get("t") or 0) < 14 * 86400:
                if json.loads(x.get("command") or "{}").get("to", "").lower() == a:
                    return {"ok": False, "why": ("the owner declined an email to %s - do not ask again" % a) if x["status"] == "refused"
                            else "an email to %s already waits for the owner's OK" % a}
    except Exception:
        pass
    r = KH.request("send an email to %s: %s%s" % (a, str(subject)[:100], (" (+%d attached)" % len(files)) if files else ""),
                   why or "Kino wants to write to someone new",
                   command=json.dumps({"to": a, "subject": subject, "body": body, "files": [list(f) if isinstance(f, (list, tuple)) else f for f in (files or [])]},
                                      ensure_ascii=False), kind="email")
    return {"ok": True, "sent": False, "request": (r or {}).get("id")}


def block(lang="fr"):
    """what he knows of his mailbox right now"""
    d = _load()
    en = lang == "en"
    R = [x for x in d.get("received") or [] if time.time() - x["t"] < 3 * 86400][-4:]
    S = [x for x in d.get("sent") or [] if time.time() - x["t"] < 3 * 86400][-2:]
    # 2026-11-01 01:33 (watch): he told the owner "it might wait for the owner's OK" about the owner's own address - he must know
    # who he can write to at once (and that the person in this conversation IS the owner, so it goes)
    L = [("Your own email address: %s (yours - you write with #email <address> | <subject> | <message>). Goes out at once to: %s "
          "(%s is HIS address - he is the owner of the app). Anyone else: it waits for his OK first." if en else
          "Ton adresse mail à toi : %s (la tienne - tu écris avec #email <adresse> | <sujet> | <message>). Part tout de suite vers : %s "
          "(%s est SON adresse - c'est lui le propriétaire de l'appli). Quelqu'un d'autre : ça attend d'abord son accord.") % (
        address(), ", ".join(contacts()), OWNER_EMAIL)]
    if R:
        # 2026-11-01 01:44 (watch): he only had sender + subject, said "got your reply" and could not tell what it said - a person
        # who has mail reads it: the text is part of what he knows (the owner's chats only - see the server)
        L.append(("Recent mail you received (you have read these): " if en else "Courriers reçus récemment (tu les as lus) : ") +
                 " | ".join("%s from %s, «%s»: %s" % (time.strftime("%d/%m %H:%M", time.gmtime(x["t"])), x["from"][:60], x["subject"][:90],
                                                      re.split(r"\s(?:On|Le) .{5,80}?(?:wrote|a écrit)\s?:", x.get("text") or "")[0][:600])
                            for x in R[-3:]))
    if S:
        L.append(("Mail you sent: " if en else "Courriers que tu as envoyés : ") +
                 " | ".join("to %s: %s" % (x["to"], x["subject"][:80]) for x in S))
    return "\n".join(L)
