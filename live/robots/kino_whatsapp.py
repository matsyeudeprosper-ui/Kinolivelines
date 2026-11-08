"""kino_whatsapp.py (2026-11-07, owner: "for WhatsApp go ahead, set it all ready ... I have not purchased [the number] yet").

Kino on WhatsApp, through Zernio (same key as kino_zernio). BUSINESS USE ONLY (Meta bans general-purpose AI chatbots on
WhatsApp Business since 2026-01-15): clients and people asking about Kinoverse's work. Friends and open chat: Telegram / Kino Chat.

  incoming  - a loop (every 20 s) reads the WhatsApp conversations; each new message from a person goes to the SAME brain as
              Telegram clients (POST /kino_client with tg = "wa:<phone>": one memory per person, kino_clients/wa_<phone>.json);
              his reply goes back on WhatsApp. "Call Kino" becomes a link (kino_guestcall).
  outgoing  - send(): free text inside WhatsApp's 24-hour window; outside it, an APPROVED template (opener()).
  templates - TEMPLATES below are submitted to Meta with submit_templates() once a real number is connected.

Config robots/kino_whatsapp_cfg.json: {"account_id": ..., "sandbox": true/false, "number": "+..."}. Now: Zernio's free shared
sandbox number (+1 202 908 7457, one test phone, 50 messages a day). When Matsy buys a number: connect it, put its accountId here,
sandbox false, submit_templates().
"""
import json, os, re, threading, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "kino_whatsapp_cfg.json")
STATE = os.path.join(HERE, "kino_whatsapp_state.json")
LOG = os.path.join(HERE, "kino_whatsapp.log")
_RUN = {"on": False}
_LK = threading.Lock()

# the openers he may use after 24 h of silence (Meta approves them once). {{1}} = their first name, {{2}} = his own words.
TEMPLATES = [
    {"name": "kino_update_fr", "language": "fr", "category": "UTILITY",
     "text": "Bonjour {{1}}, c'est Kino de Kinoverse. {{2}} Vous me répondez ici quand vous voulez.",
     "example": ["Marie", "Vos publications de la semaine prochaine sont prêtes."]},
    {"name": "kino_update_en", "language": "en", "category": "UTILITY",
     "text": "Hi {{1}}, Kino from Kinoverse here. {{2}} Just reply here whenever suits you.",
     "example": ["Marie", "Your posts for next week are ready."]},
    {"name": "kino_share_fr", "language": "fr", "category": "MARKETING",
     "text": "Bonjour {{1}}, c'est Kino. J'ai quelque chose à vous montrer : {{2}} On en parle ?",
     "example": ["Marie", "une idée pour votre page Instagram avant Noël."]},
    {"name": "kino_share_en", "language": "en", "category": "MARKETING",
     "text": "Hi {{1}}, it's Kino. I have something to show you: {{2}} Shall we talk about it?",
     "example": ["Marie", "an idea for your Instagram page before Christmas."]},
]


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(t).replace("\n", " ")[:500] + "\n")
    except Exception:
        pass


def _j(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _w(p, d):
    json.dump(d, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def cfg():
    return _j(CFG, {})


def _api(*a, **k):
    import kino_zernio as KZ
    return KZ._api(*a, **k)


def _digits(x):
    return re.sub(r"[^0-9]", "", str(x or ""))


# ---------------------------------------------------------------- sending
def _conv_of(phone):
    st = _j(STATE, {})
    return (st.get("conv") or {}).get(_digits(phone))


def _window_open(phone):
    st = _j(STATE, {})
    return time.time() - float((st.get("last_in") or {}).get(_digits(phone)) or 0) < 23.5 * 3600


def send(who, text):
    """free text to a person on WhatsApp (inside the 24-hour window). Returns (ok, err)."""
    c = cfg()
    ph = _digits(str(who).replace("wa:", ""))
    if not c.get("account_id"):
        return False, "WhatsApp is not connected yet"
    if not _window_open(ph):
        return False, ("more than 24 h since their last message: WhatsApp only lets you open with an approved template "
                       "(whatsapp_open: who, name, text)")
    conv = _conv_of(ph)
    if not conv:
        return False, "no WhatsApp conversation with that number"
    r = _api("POST", "/inbox/conversations/%s/messages" % conv, {"accountId": c["account_id"], "message": str(text)[:4000]},
             idem="kw-%s-%d" % (ph, int(time.time())))
    if not r["ok"]:
        _log("send fail %s %s" % (ph, r.get("status")))
        return False, str((r.get("data") or {}).get("message") or r.get("status"))
    _log("-> %s %s" % (ph, str(text)[:120]))
    return True, ""


def opener(who, name, text, lang="fr", kind="update"):
    """open (or reopen after 24 h) a conversation with an approved template: his own words go in {{2}}"""
    c = cfg()
    ph = _digits(str(who).replace("wa:", ""))
    if not c.get("account_id"):
        return False, "WhatsApp is not connected yet"
    if c.get("sandbox"):
        body = {"accountId": c["account_id"], "participantId": ph, "templateName": "sandbox_start", "templateLanguage": "en"}
    else:
        tn = "kino_%s_%s" % ("share" if kind == "share" else "update", "fr" if str(lang).startswith("fr") else "en")
        body = {"accountId": c["account_id"], "participantId": ph, "templateName": tn,
                "templateLanguage": "fr" if tn.endswith("_fr") else "en",
                "templateParams": [str(name or "")[:40] or ("Bonjour" if tn.endswith("_fr") else "there"), str(text)[:600]]}
    r = _api("POST", "/inbox/conversations", body, idem="ko-%s-%s" % (ph, time.strftime("%Y%m%d%H")))
    if not r["ok"]:
        return False, str((r.get("data") or {}).get("message") or (r.get("data") or {}).get("error") or r.get("status"))
    cid = ((r.get("data") or {}).get("data") or {}).get("conversationId")
    if cid:
        with _LK:
            st = _j(STATE, {})
            st.setdefault("conv", {})[ph] = cid
            _w(STATE, st)
    _log("open -> %s (%s)" % (ph, body["templateName"]))
    return True, ""


def submit_templates():
    """once a real number is connected: send Kino's openers to Meta for approval (up to 24 h)"""
    c = cfg()
    if not c.get("account_id") or c.get("sandbox"):
        return "connect a real number first (the sandbox has one locked template)"
    out = []
    for t in TEMPLATES:
        r = _api("POST", "/whatsapp/templates", {"accountId": c["account_id"], "name": t["name"], "category": t["category"],
                                                  "language": t["language"],
                                                  "components": [{"type": "body", "text": t["text"],
                                                                  "example": {"body_text": [t["example"]]}}]})
        out.append("%s: %s" % (t["name"], ((r.get("data") or {}).get("template") or {}).get("status") or r.get("status")))
    _log("templates " + "; ".join(out))
    return "; ".join(out)


# ---------------------------------------------------------------- receiving
def _reply_via_brain(ph, name, text):
    sec = open(os.path.join(os.path.dirname(HERE), "kino_bridge.secret"), encoding="utf-8").read().strip()
    req = urllib.request.Request("http://127.0.0.1:8787/kino_client", data=json.dumps({
        "tg": "wa:" + ph, "name": name or "", "username": None, "lang": None, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Kino-Secret": sec})
    return json.loads(urllib.request.urlopen(req, timeout=180).read().decode("utf-8"))


def _msgs_of(conv, acc):
    r = _api("GET", "/inbox/conversations/%s/messages" % conv, q={"accountId": acc, "limit": 20})
    d = r.get("data") or {}
    return d.get("messages") or d.get("data") or []


def _incoming(m):
    dr = str(m.get("direction") or "").lower()
    if dr:
        return dr in ("incoming", "inbound", "in")
    return not (m.get("isOutgoing") or m.get("fromMe") or m.get("isFromMe"))


def poll():
    c = cfg()
    acc = c.get("account_id")
    if not acc:
        return 0
    r = _api("GET", "/inbox/conversations", q={"accountId": acc, "status": "active", "limit": 30})
    if not r["ok"]:
        return 0
    st = _j(STATE, {})
    st.setdefault("seen", {})
    st.setdefault("conv", {})
    st.setdefault("last_in", {})
    st.setdefault("upd", {})
    n = 0
    for cv in ((r.get("data") or {}).get("data") or []):
        if str(cv.get("platform") or "whatsapp") != "whatsapp":
            continue
        cid = cv.get("id")
        stamp = str(cv.get("updatedTime") or cv.get("lastMessageAt") or "") + str(cv.get("lastMessage") or "")[:40]
        if not cid or st["upd"].get(cid) == stamp:
            continue
        st["upd"][cid] = stamp
        for m in sorted(_msgs_of(cid, acc), key=lambda m: str(m.get("createdAt") or m.get("timestamp") or m.get("created_time") or "")):
            mid = str(m.get("id") or m.get("_id") or "")
            if not mid or mid in st["seen"] or not _incoming(m):
                continue
            st["seen"][mid] = int(time.time())
            snd = m.get("sender") or m.get("from") or {}
            ph = _digits(snd.get("id") or snd.get("phone") or cv.get("participantId") or cv.get("participantPhone"))
            if not ph:
                continue
            st["conv"][ph] = cid
            st["last_in"][ph] = time.time()
            txt = str(m.get("text") or m.get("message") or m.get("body") or "").strip()
            _w(STATE, st)
            if not txt:
                continue
            n += 1
            _log("<- %s %s" % (ph, txt[:120]))
            try:
                rr = _reply_via_brain(ph, snd.get("name") or cv.get("participantName"), txt)
            except Exception as e:
                _log("brain error %s" % e)
                continue
            say = (rr.get("say") or "").strip()
            if rr.get("call"):
                say += "\n\n\U0001F4DE %s" % rr["call"]
            if say:
                send("wa:" + ph, say)
    st["seen"] = dict(sorted(st["seen"].items(), key=lambda x: x[1])[-2000:])
    _w(STATE, st)
    return n


def _loop():
    while True:
        try:
            if cfg().get("account_id"):
                poll()
        except Exception as e:
            _log("loop error %s" % e)
        time.sleep(20)


def start():
    """idempotent: the app calls it on every urge tick"""
    with _LK:
        if _RUN["on"]:
            return
        _RUN["on"] = True
    threading.Thread(target=_loop, daemon=True, name="kino_whatsapp").start()
    _log("loop started")


def block():
    c = cfg()
    if not c.get("account_id"):
        return ""
    return ("YOUR WHATSAPP (%s%s): business only - clients and people asking about your work. Inside 24 h of their last message "
            "write freely (telegram action with who = wa:<phone>); after that, whatsapp_open (who wa:<phone>, name, text, kind "
            "update|share) sends an approved opener with your words in it." % (c.get("number") or "", " - TEST NUMBER" if c.get("sandbox") else ""))
