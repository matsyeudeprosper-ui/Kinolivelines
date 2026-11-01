"""kino_mail.py (2026-11-01, owner: "we get him an email address") - Kino's own mailbox, kinoverse26@gmail.com.

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
    try:
        return _cred()["address"]
    except Exception:
        return None


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
    return new


def contacts():
    return sorted(set(_load().get("contacts") or []) | {OWNER_EMAIL})


def allow(addr):
    a = email.utils.parseaddr(addr)[1].lower()
    if a:
        _mut(lambda d: d.__setitem__("contacts", sorted(set(d.get("contacts") or []) | {a})))
    return a


def send_now(to, subject, body):
    c = _cred()
    m = MIMEText(str(body), "plain", "utf-8")
    m["From"] = "Kino <%s>" % c["address"]
    m["To"] = to
    m["Subject"] = str(subject)[:200]
    S = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=40)
    S.login(c["address"], c["app_password"])
    S.sendmail(c["address"], [email.utils.parseaddr(to)[1]], m.as_string())
    S.quit()
    item = {"t": time.time(), "to": to, "subject": str(subject)[:200], "text": str(body)[:4000]}
    _mut(lambda d: d.setdefault("sent", []).append(item))
    try:
        open(os.path.join(WORLD, "outbox", "%s_sent.txt" % time.strftime("%Y%m%d_%H%M%S")), "w", encoding="utf-8").write(
            "To: %s\nSubject: %s\n\n%s\n" % (to, subject, body))
    except Exception:
        pass
    _log("OUT to %s | %s" % (to, str(subject)[:120]))
    return True


def send(to, subject, body, why=""):
    """he writes: to an allowed contact it goes now; to someone new it waits for the owner's yes"""
    a = email.utils.parseaddr(to)[1].lower()
    if not a or "@" not in a:
        return {"ok": False, "why": "no valid address"}
    if a in contacts():
        send_now(a, subject, body)
        return {"ok": True, "sent": True}
    import kino_hands as KH
    r = KH.request("send an email to %s: %s" % (a, str(subject)[:100]), why or "Kino wants to write to someone new",
                   command=json.dumps({"to": a, "subject": subject, "body": body}, ensure_ascii=False), kind="email")
    return {"ok": True, "sent": False, "request": (r or {}).get("id")}


def block(lang="fr"):
    """what he knows of his mailbox right now"""
    d = _load()
    en = lang == "en"
    R = [x for x in d.get("received") or [] if time.time() - x["t"] < 3 * 86400][-4:]
    S = [x for x in d.get("sent") or [] if time.time() - x["t"] < 3 * 86400][-2:]
    L = [("Your own email address: %s (yours - you can write with #email <address> | <subject> | <message>; to someone new it "
          "waits for his OK)." if en else
          "Ton adresse mail à toi : %s (la tienne - tu peux écrire avec #email <adresse> | <sujet> | <message> ; à quelqu'un de "
          "nouveau, ça attend son accord).") % (address() or "kinoverse26@gmail.com")]
    if R:
        L.append(("Recent mail you received: " if en else "Courriers reçus récemment : ") +
                 " | ".join("%s from %s: %s" % (time.strftime("%d/%m %H:%M", time.gmtime(x["t"])), x["from"][:60], x["subject"][:90]) for x in R))
    if S:
        L.append(("Mail you sent: " if en else "Courriers que tu as envoyés : ") +
                 " | ".join("to %s: %s" % (x["to"], x["subject"][:80]) for x in S))
    return "\n".join(L)
