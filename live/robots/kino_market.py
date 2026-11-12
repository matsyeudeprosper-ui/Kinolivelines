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
          "accounting", "tutoring", "errands", "other")


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
def bench_add(name, skill, city="", contact="", price="", source="", ok=False, about=""):
    name = " ".join(str(name or "").split())[:80]
    skill = str(skill or "other").lower().strip()
    if not name or not (contact or source):
        return "a bench entry needs a name and how to reach them (contact) or where you found them (source)"
    if skill not in SKILLS:
        skill = "other"

    def f(d):
        for b in d["bench"]:
            if b["name"].lower() == name.lower() and (b.get("city") or "").lower() == str(city or "").lower():
                b.update({k: v for k, v in (("contact", contact), ("price", price), ("source", source), ("about", about)) if v})
                if ok:
                    b["ok"] = True
                return "updated %s on your bench" % name
        d["bench"].append({"name": name, "skill": skill, "city": str(city or "")[:60], "contact": str(contact or "")[:160],
                           "price": str(price or "")[:60], "source": str(source or "")[:200], "about": str(about or "")[:200],
                           "ok": bool(ok), "t": int(time.time()), "tried": 0})
        d["bench"] = d["bench"][-800:]
        return "%s is on your bench (%s%s)" % (name, skill, (", " + city) if city else "")
    return _mut(f)


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
    return "%s | bench: %d people (+%d this week, %d tested OK) | ads %s" % (
        ", ".join("%s %d" % kv for kv in sorted(kinds.items())) or "no marketing actions recorded",
        len(d["bench"]), newb, sum(1 for b in d["bench"] if b.get("ok")),
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
    "3) BENCH: fill 2-3 of the empty skills below near where my people live (France first, then the countries I work in): "
    "freelancers (ComeUp, Malt, Fiverr profiles), student job sites (StudentPop, StaffMe), task sites (Yoojo, AlloVoisins), "
    "local trades (directories, Google Maps), and friends I met who said what they do. bench_add name, skill, city, contact "
    "(public email / form / profile link / phone), price if shown, source. Only public business contacts, never private "
    "data. A first small paid test (help_task) only when a mission needs them.\n"
    "4) done: what I did and what I learned about which channel answers.\n"
    "Never spam: never the same text twice, never more than one answer per person, never in politics, religion, grief or "
    "health. Channels marked WAITING are not mine yet - do not try them.")
