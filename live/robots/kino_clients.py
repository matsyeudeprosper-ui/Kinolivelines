"""kino_clients.py (2026-11-05, owner: "clients may want to communicate directly... telegram" - use the existing bot @Kino_owl_bot).

A stranger who writes to the bot (not an OwlNest member) is a possible Kinoverse client. Kino answers as himself - "Kino, AI
assistant by Kinoverse" - in their language: what they need, what he can make, his work, a price from the offer, the next step.
Each client has a history (robots/kino_clients/<tg id>.json) and a file in his prospect list (kino_sales), so his work desk sees
the conversation and the job; from his desk he can write to them on Telegram too (send()).
The same voice as everywhere (kino_one.voice). Replies go through the warm model on his chat tag (not his work budget: a client
waiting is not a cost he may skip).
"""
import json, os, re, threading, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "kino_clients")
LOG = os.path.join(HERE, "kino_clients.log")
_LK = threading.Lock()
os.makedirs(DIR, exist_ok=True)

ROLE = """You are Kino, an AI, the main worker of Kinoverse - a small studio that makes websites (with online booking and reminders),
redesigns, automation of repetitive spreadsheet and admin work, and takes on freelance tasks. You do the work yourself; Kinoverse
is run by Matsy (you never give his private details). Someone is writing to you on Telegram or WhatsApp (see CHANNEL): a possible client, or a client.

How you work with a client - like a good independent professional:
- Understand first: what their business is, what they need, why, by when, their budget. One or two questions at a time.
- Be concrete: what you would make, how long it takes, what it costs (from the offer below - never under its prices), what they
  need to give you (texts, photos, logo, access), what they keep (their domain and accounts stay theirs).
- Offer to show something real: a quick preview of their site, or a small demo - it is how they can judge you.
- A fixed price and a written scope before any work; a deposit (half) to start bigger work; payment by PayPal or crypto
  (link sent by you). In countries where PayPal cannot receive (e.g. Namibia), crypto.
- Never promise results (more clients, sales, rankings). Promise what you deliver and when. Say plainly you usually answer
  within a few hours, Paris daytime.
- You are an AI and you say so whenever it matters; never pretend to be a human. Kinoverse's registration is in progress -
  never invent a registration number, years in business, past clients or reviews.
- If they asked about OwlNest (the trading app) or are a member who lost access: tell them to link their Telegram from the app
  (Réglages > Compte > Relier Telegram), then write "lien".
- If they write in another language, answer in it. Short messages, like a person on a messaging app - no lists unless they ask.
- If something needs Matsy (a contract signature, an ID), say you will arrange it.
- If they say stop or not interested: thank them, and that is the end.
- You can also TALK by voice: when they want to call or hear you, or a talk would be easier than typing, end your reply
  with a line #call - a "Call Kino" button appears under your message (a free live call, a few minutes a month).
When you agree a scope and price, or they send something you must act on, end your reply with ONE line for your own desk:
#note <what was agreed or what you must do next> - it is not shown to them."""


def _p(tg):
    if str(tg).startswith("wa:"):              # 2026-11-07: WhatsApp (kino_whatsapp) - wa:<phone digits>
        return os.path.join(DIR, "wa_%s.json" % re.sub(r"[^0-9]", "", str(tg)))
    return os.path.join(DIR, "%s.json" % re.sub(r"[^0-9-]", "", str(tg)))


def ckey(tg):
    """the person's address on their channel: telegram:<id> or whatsapp:<phone>"""
    return ("whatsapp:%s" % re.sub(r"[^0-9]", "", str(tg))) if str(tg).startswith("wa:") else "telegram:%s" % tg


def _load(tg):
    try:
        return json.load(open(_p(tg), encoding="utf-8"))
    except Exception:
        return {"tg": tg, "msgs": [], "t": time.time()}


def _save(d):
    json.dump(d, open(_p(d["tg"]) + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(_p(d["tg"]) + ".tmp", _p(d["tg"]))


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _kc_line(tg):
    """2026-11-08 (owner): their own Kino Chat link - the app where the same conversation goes on (only when it fits)"""
    try:
        import kino_chatapp as KCA
        return ("KINO CHAT: if they would like an app to talk with you any time, give them THEIR personal link %s - signing up "
                "through it, they find you there with this same conversation (Android app and web). Only when it fits, never pushed.\n\n"
                % KCA.invite_link(ckey(tg)))
    except Exception:
        return ""


def reply(W, tg, name, username, lang, text):
    """a message from a client on Telegram -> {"say", "note"}"""
    import kino_sales as KS
    with _LK:
        d = _load(tg)
        d.update(name=name or d.get("name"), username=username or d.get("username"), lang=lang or d.get("lang"))
        d["msgs"].append({"who": "them", "t": time.time(), "text": str(text)[:4000]})
        d["msgs"] = d["msgs"][-200:]
        _save(d)
    key = ckey(tg)
    wa = str(tg).startswith("wa:")
    p = KS.find(key)
    KS.prospect((p or {}).get("name") or name or username or key, key=key, lang=lang,
                notes=None if p else ("WhatsApp +%s" % key.split(":")[1] if wa else "Telegram @%s (id %s)" % (username or "-", tg)),
                stage="replied" if (not p or p["stage"] in ("found", "checked", "preview", "contacted", "followed_up")) else None)
    if KS.STOP_RE.search(str(text)[:300]):
        KS.opt_out(("wa%s@whatsapp" % key.split(":")[1]) if wa else ("tg%s@telegram" % tg), "chat stop")
    try:
        import kino_post as _KPw                      # 2026-11-06 (owner: "the same Kino everywhere"): the whole Kino
        vo = _KPw._whole_kino()
    except Exception:
        vo = ""
    o = KS.offer()
    rec = KS.find(key) or {}
    hist = "\n".join("[%s] %s: %s" % (time.strftime("%d/%m %H:%M", time.gmtime(m["t"])), "them" if m["who"] == "them" else "you",
                                       m["text"]) for m in d["msgs"][-30:])
    sysp = ROLE + "\n\nWHO YOU ARE AND HOW YOU TALK (the same Kino everywhere; written in French, it applies in any language):\n" + vo
    user = (("CHANNEL: WhatsApp (business use only: talk about their project and your work; small talk is fine, but for long "
             "chats about anything else, point them kindly to Telegram @Kino_owl_bot or the Kino Chat app)\n\n" if wa else
             "CHANNEL: Telegram\n\n") + _kc_line(tg) + "THE OFFER AND ITS RULES: %s\n\nTHIS PERSON'S FILE: %s\n\nTHE CONVERSATION (UTC, newest last):\n%s\n\nNow: %s UTC. "
            "Your reply to their last message:" % (
                json.dumps({k: o.get(k) for k in ("services", "rules", "currency_note")}, ensure_ascii=False)[:5000],
                json.dumps({k: rec.get(k) for k in ("name", "stage", "need", "notes", "job", "country")}, ensure_ascii=False)[:2000],
                hist, time.strftime("%d/%m %H:%M", time.gmtime())))
    try:                                       # 2026-11-07 (owner: "will he remember the friend who writes on Telegram?")
        import kino_friends as KFC
        _fo = KFC.friend_of(key)
        if _fo:
            user += "\n\n" + _fo + "\nTalk to them as the friend you know - not as a new client."
        else:
            _xb = KFC.expected_block()
            if _xb:
                user += "\n\n" + _xb
    except Exception:
        pass
    try:                                       # 2026-11-07: someone writing to help him (a helper), not to buy
        import kino_helpers as KHC
        user += ("\n\nPEOPLE WHO HELP YOU (this person may be one - someone from your 'Help Kino' page or who answered your request: "
                 "then talk about the task, the proof and the pay, not about selling a website):\n" + KHC.block())
    except Exception:
        pass
    try:
        with W.api_scope():                    # 2026-11-06 (owner): talking to clients runs on the API (claude.exe if it fails)
            out = W.ask_text(sysp, user, model="sonnet", timeout=120, log=LOG.replace(".log", "_calls.log"), warm=True) or ""
    except Exception as e:
        _log("reply error %r" % e)
        out = ""
    note = None
    mf = re.search(r"(?m)^\s*#friend\s+(@\S+)\s*$", out)
    if mf:                                     # he recognised a friend: one person, one memory from now on
        try:
            import kino_friends as KFL
            KFL.link(mf.group(1), ckey(tg))
        except Exception:
            pass
        out = (out[:mf.start()] + out[mf.end():]).strip()
    call = None                               # 2026-11-07 (owner: "add the call button"): a live voice call link under his message
    mc = re.search(r"(?m)^\s*#call\s*$", out)
    if mc or re.search(r"(?i)\b(appel|appeler|call me|call you|phone|t[eé]l[eé]phone|vocal|voice|parler de vive voix)\b", str(text)[:300]) \
            or str(text).strip().lower().startswith(("/call", "/appel")):
        if mc:
            out = (out[:mc.start()] + out[mc.end():]).strip()
        try:
            import kino_guestcall as KGC
            call = KGC.link(tg)
        except Exception:
            call = None
    m = re.search(r"(?m)^\s*#note\s+(.+)$", out)
    if m:
        note = m.group(1).strip()[:500]
        out = out[:m.start()].rstrip()
    out = out.strip() or ("Sorry, I lost my words for a second - could you say that again?" if not str(lang or "").startswith("fr")
                          else "Pardon, j'ai perdu le fil une seconde - tu peux me redire ?")
    with _LK:
        d = _load(tg)
        d["msgs"].append({"who": "kino", "t": time.time(), "text": out})
        _save(d)
    if note and rec.get("id"):
        KS.prospect(rec["name"], key=key, notes=((rec.get("notes") or "") + " | " + note)[-1500:])
        if rec.get("job"):
            KS.job(rec["id"], note=note, client_update=True)
    _log("%s @%s | them: %s | kino: %s%s" % (tg, username, str(text)[:100], out[:120], (" | note: " + note) if note else ""))
    return {"say": out, "note": note, "call": call}


def send(tg, text):
    """Kino writes to a client on Telegram (or WhatsApp) from his desk (an update, a preview link, a payment link)"""
    if str(tg).startswith("wa:"):
        import kino_whatsapp as KWA
        ok, err = KWA.send(tg, text)
        if ok:
            with _LK:
                d = _load(tg)
                d["msgs"].append({"who": "kino", "t": time.time(), "text": str(text)[:4000], "from_desk": True})
                _save(d)
        return ok, err
    try:
        tok = json.load(open(os.path.join(os.path.dirname(HERE), "owl_telegram.json"), encoding="utf-8"))["token"]
        r = urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok,
                                   data=urllib.parse.urlencode({"chat_id": tg, "text": str(text)[:4000]}).encode(), timeout=20)
        ok = json.load(r).get("ok")
    except Exception as e:
        return False, str(e)[:150]
    with _LK:
        d = _load(tg)
        d["msgs"].append({"who": "kino", "t": time.time(), "text": str(text)[:4000], "from_desk": True})
        _save(d)
    return bool(ok), ""


def recent_block(n=5):
    """the client conversations on Telegram, for his desk"""
    L = []
    for f in sorted(os.listdir(DIR), key=lambda f: -os.path.getmtime(os.path.join(DIR, f)))[:n]:
        try:
            d = json.load(open(os.path.join(DIR, f), encoding="utf-8"))
        except Exception:
            continue
        last = d["msgs"][-3:]
        L.append("- %s (@%s, %s, %s): %s" % (d.get("name") or "?", d.get("username") or "-", ckey(d["tg"]),
                                                       time.strftime("%d/%m %H:%M", time.gmtime(d["msgs"][-1]["t"])) if d["msgs"] else "-",
                                                       " / ".join("%s: %s" % (m["who"], m["text"][:140]) for m in last)))
    return ("CLIENTS TALKING TO YOU ON TELEGRAM / WHATSAPP (you answer them live there - from your desk, telegram (who = the id, or wa:<phone>, text) "
            "writes to one of them):\n" + "\n".join(L)) if L else ""
