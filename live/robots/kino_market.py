"""kino_market.py (2026-11-12, owner: "I want Kino to make himself known... the smartest plan... give him that independence and
power to go out there and sell himself... and like any good marketer he needs to know where to find helpers - a whole planned
system").

THE PROJECT "KINO MAKES HIMSELF KNOWN" - one daily MARKET TIME session (kino_work, care="market"), four jobs in it:
  1. HELP-HUNT   answer people who ASK for something he does (kino_friends scouts them, [ASKED FOR HELP]) - the warmest door.
  2. SHOW        one post a day about real work done (before/after, a problem solved) on every channel that is live.
  3. BENCH       find and record helpers BEFORE a mission needs them: by skill and city, with contact, price, source.
  4. NUMBERS     what each channel brought; a channel with nothing after 2 weeks loses its time (Sunday report).

Channels: CHANNELS below, status in robots/kino_market.json ("live" / "needs_account" / "off"). Social accounts of Kinoverse
are a Zernio client of our own ("kinoverse": Matsy connects each network once on its page, Kino posts with social_post).
Marketplaces (ComeUp, Fiverr, Malt) and Reddit have no Zernio door: Matsy opens the account, then signs in once in Kino's
browser profile (or gives an API app for Reddit); until then they stay "needs_account".

ADS: built, OFF. ads_on() is False until Matsy switches it on with a monthly cap (set_ads); boosts go through kino_zernio.boost
on the "kinoverse" client and are refused above the month's cap.

Store robots/kino_market.json:
  {channels: {name: {status, note, since}}, bench: [{name, skill, city, contact, price, source, ok, t, tried}],
   ads: {on, cap_eur_month, spent: {YYYY-MM: eur}}, log: [{t, kind, channel, text}]}
"""
import json
import os
import re
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_market.json")
_LK = threading.Lock()

CHANNELS = {
    "bluesky":   {"status": "live", "note": "his own account - skeet"},
    "mastodon":  {"status": "live", "note": "his own account - toot"},
    "blog":      {"status": "live", "note": "kinoverse26-byte.github.io - post"},
    "facebook":  {"status": "needs_account", "note": "Kinoverse page via Zernio (social_post who=kinoverse)"},
    "instagram": {"status": "needs_account", "note": "via Zernio"},
    "linkedin":  {"status": "needs_account", "note": "Kinoverse page via Zernio"},
    "tiktok":    {"status": "needs_account", "note": "via Zernio"},
    "threads":   {"status": "needs_account", "note": "via Zernio"},
    "twitter":   {"status": "needs_account", "note": "X via Zernio"},
    "youtube":   {"status": "needs_account", "note": "Shorts via Zernio"},
    "pinterest": {"status": "needs_account", "note": "via Zernio"},
    "reddit":    {"status": "needs_account", "note": "r/forhire, r/smallbusiness, local subs - API app from Matsy"},
    "comeup":    {"status": "needs_account", "note": "French gig market - Matsy signs in once in Kino's browser"},
    "fiverr":    {"status": "needs_account", "note": "gig market - Matsy signs in once in Kino's browser"},
    "malt":      {"status": "needs_account", "note": "French freelance market - Matsy signs in once in Kino's browser"},
}
SKILLS = ("repair", "moving", "cleaning", "delivery", "photo", "translation", "design", "writing", "typing", "web", "legal",
          "accounting", "tutoring", "errands", "phone", "community", "other")
# 2026-11-13 (owner: "the operators / community managers hunting system - properly implemented and working"): two kinds on the
# bench - PROVIDERS (a business he books FOR a client: plumber, mover) and OPERATORS (a person who works FOR KINO on small paid
# tasks: calls a shop, runs an errand, runs a client's social media). Operators go through a pipeline:
#   found -> contacted (his email, max RECRUIT_PER_DAY a day, STOP honoured) -> interested (they answered: rate, hours) ->
#   tested (a first small paid task, help_task) -> ok (reliable) | no
OPERATOR_ROLES = ("phone", "community", "errands", "translation", "writing", "design", "delivery", "photo", "typing")
STATUSES = ("found", "contacted", "interested", "tested", "ok", "no")
RECRUIT_PER_DAY = 5


def _load():
    try:
        d = json.load(open(STORE, encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("channels", {})
    for k, v in CHANNELS.items():
        d["channels"].setdefault(k, dict(v, since=time.strftime("%Y-%m-%d")))
    d.setdefault("bench", [])
    d.setdefault("ads", {"on": False, "cap_eur_month": 0.0, "spent": {}})
    d.setdefault("log", [])
    return d


def _save(d):
    tmp = STORE + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def _mut(fn):
    with _LK:
        d = _load()
        r = fn(d)
        _save(d)
        return r


def note(kind, channel, text):
    """what he did for being known (post / answer / lead / sale) - the weekly numbers come from here"""
    _mut(lambda d: d.__setitem__("log", (d["log"] + [{"t": int(time.time()), "kind": str(kind)[:20],
                                                      "channel": str(channel)[:20], "text": str(text)[:200]}])[-2000:]))
    return "noted"


def set_channel(name, status, note_=""):
    name = str(name or "").lower().strip()
    if status not in ("live", "needs_account", "off"):
        return "status is live, needs_account or off"

    def f(d):
        c = d["channels"].setdefault(name, {})
        c.update(status=status, since=time.strftime("%Y-%m-%d"))
        if note_:
            c["note"] = note_
    _mut(f)
    return "%s: %s" % (name, status)


# ---------------------------------------------------------------- the bench (helpers ready before he needs them)
def _email_in(*xs):
    for x in xs:
        m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", str(x or ""))
        if m:
            return m.group(0).lower()
    return ""


def bench_add(name, skill, city="", contact="", price="", source="", ok=False, about="", kind="", email=""):
    name = " ".join(str(name or "").split())[:80]
    skill = str(skill or "other").lower().strip()
    if not name or not (contact or source or email):
        return "a bench entry needs a name and how to reach them (contact) or where you found them (source)"
    if skill not in SKILLS:
        skill = "other"
    kind = kind if kind in ("provider", "operator") else ("operator" if skill in ("phone", "community") else "provider")
    em = _email_in(email, contact)

    def f(d):
        for b in d["bench"]:
            if b["name"].lower() == name.lower() and (b.get("city") or "").lower() == str(city or "").lower():
                b.update({k: v for k, v in (("contact", contact), ("price", price), ("source", source), ("about", about),
                                            ("email", em)) if v})
                if ok:
                    b["ok"] = True
                    b["status"] = "ok"
                return "updated %s on your bench" % name
        d["bench"].append({"name": name, "skill": skill, "city": str(city or "")[:60], "contact": str(contact or "")[:160],
                           "price": str(price or "")[:60], "source": str(source or "")[:200], "about": str(about or "")[:200],
                           "ok": bool(ok), "t": int(time.time()), "tried": 0, "kind": kind, "email": em,
                           "status": "ok" if ok else "found"})
        d["bench"] = d["bench"][-800:]
        return "%s is on your bench (%s %s%s)%s" % (name, kind, skill, (", " + city) if city else "",
                                                    " - recruit them with recruit (name, subject, text)" if kind == "operator" and em else "")
    return _mut(f)


def recruit(name, subject, text, lang="fr"):
    """his first email to an OPERATOR he found: who he is, the kind of small paid tasks, their rate and availability"""
    import kino_sales as KS
    d = _load()
    b = next((x for x in d["bench"] if x["name"].lower() == str(name or "").strip().lower()), None)
    if b is None:
        return "nobody called %s on your bench - bench_add them first (kind operator, with their public email)" % name
    if b.get("kind") != "operator":
        return "%s is a provider (a business you book for clients), not someone you recruit" % b["name"]
    if not b.get("email"):
        return "no public email for %s - recruit only through a public professional address" % b["name"]
    if KS.opted_out(b["email"]):
        return "%s asked not to be written to - never again" % b["name"]
    if b.get("status") not in ("found", None):
        return "%s is already %s - no second first email" % (b["name"], b.get("status"))
    today = [x for x in d["bench"] if x.get("contacted_t") and time.time() - float(x["contacted_t"]) < 86400]
    if len(today) >= RECRUIT_PER_DAY:
        return "not sent - %d operators contacted in the last 24 h, that is enough; more tomorrow" % RECRUIT_PER_DAY
    body = str(text or "").strip()
    if len(body) < 80:
        return "not sent - write a real short message (who you are, the kind of paid tasks, ask their rate and availability)"
    import kino_mail as KM
    KM.send_now(b["email"], str(subject or "Petites missions rémunérées")[:120], body + "\n\n" + KS.footer(lang))

    def f(dd):
        for x in dd["bench"]:
            if x["name"] == b["name"]:
                x.update(status="contacted", contacted_t=int(time.time()))
    _mut(f)
    note("recruit", "email", "%s (%s)" % (b["name"], b["skill"]))
    return "sent to %s <%s> - their answer will come to your inbox and to this bench" % (b["name"], b["email"])


def bench_status(name, status, price="", note_=""):
    """what you learned: interested (their rate, hours), tested (first task done), ok (reliable), no"""
    if status not in STATUSES:
        return "status is one of %s" % ", ".join(STATUSES)

    def f(d):
        for x in d["bench"]:
            if x["name"].lower() == str(name or "").strip().lower():
                x["status"] = status
                if status == "ok":
                    x["ok"] = True
                if price:
                    x["price"] = str(price)[:60]
                if note_:
                    x["about"] = (str(x.get("about") or "") + " | " + str(note_))[-300:]
                return "%s is now %s" % (x["name"], status)
        return "nobody called %s on your bench" % name
    return _mut(f)


def on_mail(addr, subject, text):
    """kino_mail: an email from someone on the bench - STOP is honoured, an answer moves them to 'interested'"""
    a = _email_in(addr)
    if not a:
        return
    d = _load()
    b = next((x for x in d["bench"] if x.get("email") == a), None)
    if b is None:
        return
    import kino_sales as KS
    stop = bool(KS.STOP_RE.search(str(subject or "") + " " + str(text or "")[:400]))
    if stop:
        KS.opt_out(a, "operator said stop")

    def f(dd):
        for x in dd["bench"]:
            if x.get("email") == a:
                x["reply"] = (str(subject or "") + " | " + str(text or ""))[:600]
                x["reply_t"] = int(time.time())
                if stop:
                    x["status"] = "no"
                elif x.get("status") in ("found", "contacted"):
                    x["status"] = "interested"
    _mut(f)
    note("recruit_reply", "email", "%s %s" % (b["name"], "STOP" if stop else "answered"))
    if not stop:
        try:
            import kino_urge as KU
            KU.add("kino", "AN OPERATOR ANSWERED - %s (%s) replied to your recruiting email: \"%s\". Answer them (your email "
                           "action), note their rate and hours (bench_status interested), and give them a first small paid "
                           "task when a mission needs one." % (b["name"], b["skill"], str(text or "")[:400]))
        except Exception:
            pass


def operators_line():
    d = _load()
    O = [b for b in d["bench"] if b.get("kind") == "operator"]
    c = {}
    for b in O:
        c[b.get("status") or "found"] = c.get(b.get("status") or "found", 0) + 1
    waiting = [b for b in O if b.get("status") == "interested"]
    return "OPERATORS (people who work for you): %d - %s%s" % (
        len(O), ", ".join("%s %d" % (k, c[k]) for k in STATUSES if c.get(k)) or "none yet",
        ("\nANSWERS TO HANDLE: " + "; ".join("%s (%s): %s" % (b["name"], b["skill"], (b.get("reply") or "")[:160]) for b in waiting[:5]))
        if waiting else "")


def bench_find(skill="", city=""):
    d = _load()
    s, c = str(skill or "").lower(), str(city or "").lower()
    B = [b for b in d["bench"] if (not s or b["skill"] == s or s in (b.get("about") or "").lower())
         and (not c or c in (b.get("city") or "").lower() or not b.get("city"))]
    B.sort(key=lambda b: (not b.get("ok"), -b["t"]))
    if not B:
        return "nobody on your bench for %s%s yet - find some (bench_add) before you need them" % (skill or "that", (" in " + city) if city else "")
    return "\n".join("- %s (%s%s) %s | %s | price %s%s" % (b["name"], b["skill"], (", " + b["city"]) if b.get("city") else "",
                                                        "OK'd" if b.get("ok") else "not tested yet", b.get("contact") or b.get("source"),
                                                        b.get("price") or "?", (" | " + b["about"]) if b.get("about") else "")
                     for b in B[:12])


def bench_gaps():
    """skills with nobody on the bench - where to look next"""
    d = _load()
    have = {b["skill"] for b in d["bench"]}
    return [s for s in SKILLS if s not in have and s != "other"]


# ---------------------------------------------------------------- ads (built, OFF until Matsy switches them on)
def ads_on():
    a = _load()["ads"]
    return bool(a.get("on")) and float(a.get("cap_eur_month") or 0) > 0


def set_ads(on, cap_eur_month=0.0):
    def f(d):
        d["ads"]["on"] = bool(on)
        d["ads"]["cap_eur_month"] = float(cap_eur_month or 0)
    _mut(f)
    try:                                       # the Zernio client "kinoverse" carries the same cap (its boost checks it)
        import kino_zernio as KZ
        zd = KZ._load()
        k = KZ._find(zd, "kinoverse")
        if k:
            zd["clients"][k]["ads_cap_eur"] = float(cap_eur_month or 0) if on else 0
            KZ._save(zd)
    except Exception:
        pass
    return "ads %s, cap %.0f EUR a month" % ("ON" if on else "OFF", float(cap_eur_month or 0))


def ads_left():
    a = _load()["ads"]
    return max(0.0, float(a.get("cap_eur_month") or 0) - float((a.get("spent") or {}).get(time.strftime("%Y-%m"), 0)))


def ads_spend(eur):
    _mut(lambda d: d["ads"].setdefault("spent", {}).__setitem__(
        time.strftime("%Y-%m"), float(d["ads"]["spent"].get(time.strftime("%Y-%m"), 0)) + float(eur)))


def boost(post, account, ad_account, budget_eur, days):
    """a boost of one of Kinoverse's own posts - only when Matsy switched ads on, inside the month's cap"""
    if not ads_on():
        return "not done - ads are OFF (Matsy switches them on when the money is ready); grow without them for now"
    total = float(budget_eur or 0) * max(1, int(days or 1))
    if total > ads_left():
        return "not done - %.0f EUR is over what is left this month (%.0f EUR)" % (total, ads_left())
    import kino_zernio as KZ
    r = KZ.boost("kinoverse", post, account, ad_account, budget_eur, days)
    if str(r).lower().startswith("boost submitted"):
        ads_spend(total)
        note("ad", "zernio", "%s EUR x %s days on %s" % (budget_eur, days, post))
    return r


# ---------------------------------------------------------------- his session and his numbers
def refresh_from_zernio():
    """a network Matsy connected on the Kinoverse Zernio page becomes a LIVE channel by itself"""
    try:
        import kino_zernio as KZ
        acc = KZ.sync("kinoverse")
    except Exception:
        return
    plats = {a.get("platform") for a in acc if a.get("active", True)}

    def f(d):
        for p in plats:
            if p in d["channels"] and d["channels"][p].get("status") != "live":
                d["channels"][p].update(status="live", since=time.strftime("%Y-%m-%d"),
                                        note="Kinoverse account connected on Zernio - social_post who=kinoverse nets=[%s]" % p)
    _mut(f)


def block():
    """MARKET TIME - what his session needs in front of him"""
    refresh_from_zernio()
    d = _load()
    live = [k for k, v in d["channels"].items() if v.get("status") == "live"]
    wait = [k for k, v in d["channels"].items() if v.get("status") == "needs_account"]
    wk = [x for x in d["log"] if time.time() - x["t"] < 7 * 86400]
    by = {}
    for x in wk:
        by.setdefault(x["channel"], {}).setdefault(x["kind"], 0)
        by[x["channel"]][x["kind"]] += 1
    try:
        import kino_friends as KF
        asks = [c for c in KF._load()["cands"] if c.get("asked")]
        ask_s = "\n".join("- [ASKED FOR HELP] %s on %s: \"%s\" url=%s" % (c["who"], c["where"], c["text"][:200], c["url"]) for c in asks[:8])
    except Exception:
        ask_s = ""
    gaps = bench_gaps()
    try:                                       # 2026-11-12 (first run: "no real client work in view to show"): his real work
        import kino_missions as KMs
        W = [m for m in KMs._load()["missions"] if time.time() - m["t"] < 14 * 86400 and m.get("log")
             and m["status"] != "cancelled" and not re.search(r"fichiers|files|bluesky|mastodon", m["what"], re.I)][-8:]
        work = "\n".join("- %s (%s)%s" % (m["what"][:140], m["status"], (" - last: " + m["log"][-1]["text"][:160]) if m["log"] else "")
                         for m in W)
    except Exception:
        work = ""
    try:
        import kino_sales as KSs
        P = KSs._j(KSs.STORE, {"items": []})["items"]
        pv = [p for p in P if p.get("preview")]
        work += "\n- website previews built for %d businesses (e.g. %s)" % (len(pv), ", ".join(
            str(p.get("kind") or p.get("type") or "a shop") for p in pv[:4])) if pv else ""
    except Exception:
        pass
    head = ("REAL WORK YOU CAN SHOW (no names, no private details - 'a man near Paris', 'a barber'):\n" + (work or "(none yet)")
            + "\n\n")
    try:
        head += operators_line() + "\n\n"
    except Exception:
        pass
    return head + ("CHANNELS LIVE: %s\nWAITING FOR AN ACCOUNT (Matsy opens them - do not try them): %s\n"
            "THIS WEEK SO FAR: %s\n\nPEOPLE ASKING FOR HELP RIGHT NOW:\n%s\n\nYOUR BENCH: %d people (%d tested OK). Skills with "
            "nobody yet: %s\nADS: %s" % (
                ", ".join(live), ", ".join(wait) or "none",
                "; ".join("%s %s" % (ch, ", ".join("%s %d" % kv for kv in k.items())) for ch, k in by.items()) or "nothing yet",
                ask_s or "(none found yet this round - search for more: xsearch / search with words like 'need help with', "
                         "'cherche quelqu'un pour', 'busco ayuda')",
                len(d["bench"]), sum(1 for b in d["bench"] if b.get("ok")), ", ".join(gaps[:8]) or "none",
                ("ON, %.0f EUR left this month (ads_boost on your own best post)" % ads_left()) if ads_on() else "OFF"))


def week_line(now=None):
    now = now or time.time()
    d = _load()
    wk = [x for x in d["log"] if now - x["t"] < 7 * 86400]
    kinds = {}
    for x in wk:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    newb = sum(1 for b in d["bench"] if now - b["t"] < 7 * 86400)
    return "%s | bench: %d people (+%d this week, %d tested OK) | %s | ads %s" % (
        ", ".join("%s %d" % kv for kv in sorted(kinds.items())) or "no marketing actions recorded",
        len(d["bench"]), newb, sum(1 for b in d["bench"] if b.get("ok")), operators_line().split("\n")[0],
        ("ON %.0f EUR/month" % float(d["ads"]["cap_eur_month"])) if ads_on() else "OFF")


MARKET_TIME = (
    "MARKET TIME - I make myself known (Matsy 12/11: \"go out there and sell yourself; like any good marketer, know where to "
    "find helpers\"). This session, in this order:\n"
    "1) HELP-HUNT (most of the session): the people below ASKED for something I do. Answer the question itself first, usefully, "
    "in their language; then one plain sentence that this is the kind of thing I take care of (no link in a first word - they "
    "ask for more). skeet/toot with url = their post. If the list is thin, search for more people asking (xsearch, search). "
    "After each: market_note kind=answer channel=<where>.\n"
    "2) SHOW: ONE post about real work I did for someone this week (no private names or details - 'a man in Essonne with a "
    "noisy washing machine'), before/after, what it took, in a warm human voice. On every LIVE channel (skeet, toot, and "
    "social_post who=kinoverse for the networks Zernio has). market_note kind=post.\n"
    "3) MY PEOPLE (Matsy 13/11: operators and community managers, properly): first handle ANSWERS TO HANDLE below (answer "
    "them by email, bench_status interested with their rate and hours). Then RECRUIT 2-3 OPERATORS - people who will work for "
    "me on small paid tasks - ONLY for what I cannot do myself (Matsy 13/11: a human only when it truly needs a human): "
    "PHONE operators (call a shop or a craftsman for a client - I have no phone line), on-the-ground COMMUNITY helpers "
    "(film or photograph at a client's shop, cover a live event - the posting and answering I do myself), ERRAND runners "
    "in Paris / Île-de-France: freelancers with a public "
    "profile and a public professional email (Malt, ComeUp, Fiverr, their own site, LinkedIn 'disponible'), students on job "
    "boards, virtual assistants. bench_add kind operator with their email, then recruit (one warm short email each). "
    "No public email but a contact form on THEIR OWN site (not a marketplace that forbids it)? Send the same short "
    "message through that form (allow_site, then the browser), say you are Kino, an AI of Kinoverse, give your email "
    "kino@kinoverseai.com for the answer, then bench_status contacted - one message per person, never twice. Also "
    "1-2 PROVIDERS for an empty skill below (a business I can book for a client: bench_add kind provider). Only public "
    "professional contacts, never private data. A first small paid test (help_task) when a mission needs them; after a "
    "good test bench_status ok.\n"
    "4) done: what I did and what I learned about which channel answers.\n"
    "Never spam: never the same text twice, never more than one answer per person, never in politics, religion, grief or "
    "health. Channels marked WAITING are not mine yet - do not try them.")
