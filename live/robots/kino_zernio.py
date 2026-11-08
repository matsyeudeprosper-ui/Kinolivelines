"""
kino_zernio.py - Kino's two client services on Zernio (2026-11-07, owner: "social media manager + marketer"; "letting the
client post themselves defeats the purpose" -> option A: Kino posts for them through Zernio's API).

  SOCIAL  - Kino writes the client's posts, the client approves the week on one page (first weeks), Kino posts them on
            every network the client connected, answers comments and Google reviews, monthly report.
  ADS     - the client connects their ad account; Kino proposes a boost/campaign WITH A BUDGET; it runs only after the
            client confirmed that budget on their page. The client's ad money is never spent without their written yes.

The client never gives Kino a password: they open their own link (/c/<token>), press "Connect Instagram" etc., and sign in
on the network itself (Zernio OAuth, branded "Kinoverse"). Links on our side never expire; each click asks Zernio for a
fresh 30-minute connect URL.

Key: C:\\ProgramData\\kino_secret\\zernio.json (never printed, never logged).
"""
import html
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_zernio.json")
LOG = os.path.join(HERE, "kino_zernio.log")
API = "https://zernio.com/api/v1"
BASE = "https://owltrader.duckdns.org/c/"
NETWORKS = ("facebook", "instagram", "googlebusiness", "linkedin", "tiktok", "threads", "pinterest", "youtube", "twitter",
            "bluesky")
ADS = ("metaads", "googleads", "tiktokads", "linkedinads")
NICE = {"facebook": "Facebook", "instagram": "Instagram", "googlebusiness": "Google (fiche Google / Maps)",
        "linkedin": "LinkedIn", "tiktok": "TikTok", "threads": "Threads", "pinterest": "Pinterest", "youtube": "YouTube",
        "twitter": "X", "bluesky": "Bluesky", "metaads": "Publicités Facebook + Instagram", "googleads": "Google Ads",
        "tiktokads": "Publicités TikTok", "linkedinads": "Publicités LinkedIn"}
# connect path per name (ads go through the network's /ads connect)
_CONNECT = {"metaads": "facebook/ads", "googleads": "googleads", "tiktokads": "tiktok/ads", "linkedinads": "linkedin/ads"}


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(t).replace("\n", " ")[:600] + "\n")
    except Exception:
        pass


def _key():
    return json.load(open(r"C:\ProgramData\kino_secret\zernio.json", encoding="utf-8"))["api_key"]


def _api(method, path, body=None, q=None, idem=None):
    url = API + path + (("?" + urllib.parse.urlencode({k: v for k, v in q.items() if v is not None})) if q else "")
    h = {"Authorization": "Bearer " + _key(), "User-Agent": "kinoverse/1", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    if idem:
        h["Idempotency-Key"] = idem
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=40) as f:
            t = f.read().decode("utf-8", "replace")
            return {"ok": True, "status": f.status, "data": json.loads(t) if t.strip() else {}}
    except urllib.error.HTTPError as e:
        t = e.read().decode("utf-8", "replace")[:800]
        _log("API %s %s -> %s %s" % (method, path, e.code, t[:300]))
        try:
            d = json.loads(t)
        except Exception:
            d = {"raw": t}
        return {"ok": False, "status": e.code, "data": d}
    except Exception as e:
        _log("API %s %s -> %s" % (method, path, e))
        return {"ok": False, "status": 0, "data": {"error": str(e)}}


def _err(r):
    d = r.get("data") or {}
    return str(d.get("message") or d.get("error") or d.get("raw") or r.get("status"))[:200]


# ---------------------------------------------------------------- store
def _load():
    try:
        d = json.load(open(STORE, encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("clients", {})
    d.setdefault("posts", {})
    return d


def _save(d):
    tmp = STORE + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def _slug(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")
    return s[:40] or "client"


def _find(d, ref):
    ref = str(ref or "").strip().lower()
    if ref in d["clients"]:
        return ref
    for k, c in d["clients"].items():
        if ref and (ref == (c.get("email") or "").lower() or ref == c.get("name", "").lower() or ref == c.get("token")):
            return k
    return None


def by_token(tok):
    d = _load()
    for k, c in d["clients"].items():
        if tok and secrets.compare_digest(str(c.get("token") or ""), str(tok)):
            return k, c, d
    return None, None, d


# ---------------------------------------------------------------- clients
def client(name, email, service="social", lang="fr", tz="Europe/Paris", price="", notes=""):
    """a client who said yes (a won job): their own Zernio profile + their private page. Nothing costs money until they
    connect accounts (first 2 free, then about 6 USD per account a month - Matsy pays, it goes in the price)."""
    name = str(name or "").strip()
    email = str(email or "").strip().lower()
    if not name or "@" not in email:
        return "client needs a business name and their email"
    service = service if service in ("social", "ads", "both") else "social"
    d = _load()
    k = _find(d, email) or _find(d, name)
    if k:
        return "already a client: %s - their page %s%s" % (k, BASE, d["clients"][k]["token"])
    k = _slug(name)
    while k in d["clients"]:
        k += "-2"
    r = _api("POST", "/profiles", {"name": name[:80], "externalId": k})
    if not r["ok"]:
        return "could not open their space at Zernio: " + _err(r)
    pid = ((r["data"] or {}).get("profile") or {}).get("_id")
    tok = secrets.token_urlsafe(12)
    d["clients"][k] = {"name": name, "email": email, "service": service, "lang": "en" if str(lang).lower().startswith("en") else "fr",
                       "tz": tz or "Europe/Paris", "price": str(price or ""), "notes": str(notes or "")[:400],
                       "profile_id": pid, "token": tok, "accounts": [], "auto": False, "ads_cap_eur": 0,
                       "since": time.strftime("%Y-%m-%d"), "replied": []}
    _save(d)
    _log("client %s (%s) profile %s" % (k, service, pid))
    return ("client %s ready. Send them THEIR page (it never expires): %s%s - there they connect their networks with one "
            "click each (they sign in on the network itself, no password to you), approve your posts, and see the results."
            % (k, BASE, tok))


def page_link(ref):
    d = _load()
    k = _find(d, ref)
    return (BASE + d["clients"][k]["token"]) if k else None


def connect_url(tok, net):
    """our never-expiring button -> a fresh Zernio connect URL (30 min), branded Kinoverse, landing back on their page"""
    k, c, d = by_token(tok)
    if not k or net not in NETWORKS + ADS:
        return None
    if net in ADS and c.get("service") == "social":
        return None
    path = _CONNECT.get(net, net)
    r = _api("GET", "/connect/" + path, q={"profileId": c["profile_id"], "redirect_url": BASE + tok + "?connected=" + net})
    if not r["ok"]:
        return None
    return (r["data"] or {}).get("authUrl") or (r["data"] or {}).get("url")


def sync(ref):
    d = _load()
    k = _find(d, ref)
    if not k:
        return []
    c = d["clients"][k]
    r = _api("GET", "/accounts", q={"profileId": c["profile_id"]})
    if r["ok"]:
        acc = [{"id": a.get("_id"), "platform": a.get("platform"), "user": a.get("username") or a.get("displayName") or "",
                "active": a.get("isActive", True)} for a in (r["data"] or {}).get("accounts") or []
               if a.get("profileId") in (None, c["profile_id"]) or (isinstance(a.get("profileId"), dict)
                                                                 and a["profileId"].get("_id") == c["profile_id"])]
        if [a["id"] for a in acc] != [a["id"] for a in c.get("accounts") or []]:
            _log("accounts %s: %s" % (k, ", ".join(a["platform"] for a in acc)))
        c["accounts"] = acc
        _save(d)
    return c.get("accounts") or []


# ---------------------------------------------------------------- posts
def draft(ref, text, when="", image="", nets=None, why=""):
    """one post Kino wrote for the client. when = 'YYYY-MM-DD HH:MM' in the client's time (empty = as soon as approved).
    While the client has not chosen 'post without asking me' it waits for their yes on their page."""
    d = _load()
    k = _find(d, ref)
    if not k:
        return "no such client - add them first (social_client)"
    text = str(text or "").strip()
    if len(text) < 10:
        return "post text is empty"
    c = d["clients"][k]
    when = str(when or "").strip()
    if when and not re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}$", when):
        return "when must be 'YYYY-MM-DD HH:MM' (the client's local time) or empty"
    if image and not (str(image).startswith("https://") or os.path.isfile(str(image))):
        return "image must be a file in your world or an https link"
    nets = [n for n in (nets or []) if n in NETWORKS] or None
    pid = "s%d" % (int(time.time() * 1000) % 10 ** 11)
    d["posts"][pid] = {"client": k, "text": text[:3000], "when": when.replace(" ", "T"), "image": str(image or ""),
                       "nets": nets, "why": str(why or "")[:300], "state": "approved" if c.get("auto") else "waiting",
                       "made": time.strftime("%Y-%m-%d %H:%M")}
    _save(d)
    return ("post %s %s" % (pid, "will go out on time (client lets you post alone)" if c.get("auto") else
                            "waits for the client's yes on their page %s%s - tell them a new post is waiting (once a "
                            "week for the whole batch, not for each post)" % (BASE, c["token"])))


def _upload(path):
    ext = os.path.splitext(path)[1].lower()
    ct = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
          ".mp4": "video/mp4"}.get(ext)
    if not ct:
        return None
    r = _api("POST", "/media/presign", {"filename": os.path.basename(path), "contentType": ct, "size": os.path.getsize(path)})
    if not r["ok"]:
        return None
    up = urllib.request.Request(r["data"]["uploadUrl"], data=open(path, "rb").read(), method="PUT",
                                headers={"Content-Type": ct})
    try:
        urllib.request.urlopen(up, timeout=120).read()
    except Exception as e:
        _log("upload failed %s" % e)
        return None
    return {"url": r["data"]["publicUrl"], "type": "video" if ct.startswith("video") else "image"}


def send_due():
    """approved posts -> Zernio (scheduled at their time, or now). Runs from the online tick."""
    d = _load()
    out = []
    for pid, p in list(d["posts"].items()):
        if p.get("state") != "approved":
            continue
        c = d["clients"].get(p["client"])
        if not c:
            continue
        acc = [a for a in (c.get("accounts") or []) if a.get("active", True) and a.get("platform") in NETWORKS
               and (not p.get("nets") or a["platform"] in p["nets"])]
        if not acc:
            acc = [a for a in sync(p["client"]) if a.get("platform") in NETWORKS and (not p.get("nets") or a["platform"] in p["nets"])]
            d = _load()
            p = d["posts"][pid]
            if not acc:
                if p.get("state_note") != "no accounts":
                    p["state_note"] = "no accounts"
                    _save(d)
                continue
        body = {"content": p["text"], "platforms": [{"platform": a["platform"], "accountId": a["id"]} for a in acc]}
        if p.get("image"):
            m = {"url": p["image"], "type": "image"} if p["image"].startswith("https://") else _upload(p["image"])
            if not m:
                p["state"] = "failed"
                p["state_note"] = "image upload failed"
                _save(d)
                continue
            body["mediaItems"] = [m]
        if p.get("when") and p["when"] > time.strftime("%Y-%m-%dT%H:%M"):
            body["scheduledFor"] = p["when"]
            body["timezone"] = c.get("tz") or "Europe/Paris"
        else:
            body["publishNow"] = True
        r = _api("POST", "/posts", body, idem="kino-" + pid)
        if r["ok"]:
            post = (r["data"] or {}).get("post") or {}
            p["state"] = "sent"
            p["zid"] = post.get("_id")
            p["sent"] = time.strftime("%Y-%m-%d %H:%M")
            p["state_note"] = post.get("status") or ""
            out.append("%s %s -> %s" % (p["client"], pid, post.get("status")))
        else:
            p["tries"] = p.get("tries", 0) + 1
            p["state_note"] = _err(r)
            if p["tries"] >= 3 or r.get("status") in (400, 403, 422):
                p["state"] = "failed"
        _save(d)
    if out:
        _log("sent: " + "; ".join(out))
    return out


# ---------------------------------------------------------------- replies (comments + Google reviews)
def inbox(ref, n=15):
    """what people wrote to the client that has no answer yet: Google reviews and comments under their posts"""
    d = _load()
    k = _find(d, ref)
    if not k:
        return "no such client"
    c = d["clients"][k]
    lines = []
    done = set(c.get("replied") or [])
    for a in c.get("accounts") or []:
        if a["platform"] == "googlebusiness":
            r = _api("GET", "/inbox/reviews", q={"platform": "googlebusiness", "accountId": a["id"], "hasReply": "false"})
            for rv in ((r.get("data") or {}).get("data") or [])[:n]:
                if rv.get("id") in done:
                    continue
                lines.append("REVIEW %s stars by %s: %s  [reply: social_reply kind=review id=%s account=%s]" % (
                    rv.get("rating"), (rv.get("reviewer") or {}).get("name") or "?", (rv.get("text") or "(no text)")[:300],
                    rv.get("id"), a["id"]))
    r = _api("GET", "/inbox/comments", q={"profileId": c["profile_id"], "limit": 20})
    posts = (r.get("data") or {}).get("data") or (r.get("data") or {}).get("posts") or []
    for po in posts[:10]:
        post_id = po.get("id") or po.get("_id") or po.get("postId")
        acc = po.get("accountId") or ((po.get("account") or {}).get("id"))
        if not post_id:
            continue
        r2 = _api("GET", "/inbox/comments/%s" % urllib.parse.quote(str(post_id), safe=""), q={"accountId": acc})
        for cm in ((r2.get("data") or {}).get("comments") or (r2.get("data") or {}).get("data") or [])[:n]:
            cid = cm.get("id") or cm.get("commentId")
            if not cid or cid in done or cm.get("isOwner") or cm.get("fromOwner"):
                continue
            who = (cm.get("from") or {}).get("name") or (cm.get("author") or {}).get("name") or cm.get("username") or "?"
            lines.append("COMMENT on %s by %s: %s  [reply: social_reply kind=comment post=%s id=%s account=%s]" % (
                po.get("platform") or "", who, (cm.get("message") or cm.get("text") or "")[:300], post_id, cid, acc))
    return "\n".join(lines[:n]) or "nothing waiting for an answer"


def reply(ref, kind, rid, text, account, post=""):
    d = _load()
    k = _find(d, ref)
    if not k:
        return "no such client"
    text = str(text or "").strip()
    if len(text) < 2:
        return "empty reply"
    if kind == "review":
        r = _api("POST", "/inbox/reviews/%s/reply" % urllib.parse.quote(str(rid), safe=""),
                 {"accountId": account, "message": text[:4000]}, idem="kr-" + str(rid)[-40:])
    else:
        r = _api("POST", "/inbox/comments/%s" % urllib.parse.quote(str(post), safe=""),
                 {"accountId": account, "commentId": rid, "message": text[:2000]}, idem="kc-" + str(rid)[-40:])
    if not r["ok"]:
        return "reply failed: " + _err(r)
    d = _load()
    d["clients"][k].setdefault("replied", []).append(str(rid))
    d["clients"][k]["replied"] = d["clients"][k]["replied"][-500:]
    _save(d)
    _log("reply %s %s %s" % (k, kind, rid))
    return "answered (%s)" % kind


# ---------------------------------------------------------------- report
def report(ref, days=30):
    d = _load()
    k = _find(d, ref)
    if not k:
        return "no such client"
    c = d["clients"][k]
    frm = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400 * int(days or 30)))
    r = _api("GET", "/analytics", q={"profileId": c["profile_id"], "fromDate": frm, "limit": 50})
    sent = [p for p in d["posts"].values() if p["client"] == k and p.get("state") == "sent" and (p.get("sent") or "") >= frm]
    if not r["ok"]:
        return "%d posts sent since %s; numbers not available (%s)" % (len(sent), frm, _err(r))
    items = (r["data"] or {}).get("posts") or (r["data"] or {}).get("data") or []
    tot = {}
    for it in items:
        an = it.get("analytics") or it
        for f in ("impressions", "reach", "likes", "comments", "shares", "clicks", "views"):
            v = an.get(f)
            if isinstance(v, (int, float)):
                tot[f] = tot.get(f, 0) + v
    return "since %s: %d posts by you; %s" % (frm, len(sent), ", ".join("%s %d" % (f, v) for f, v in tot.items()) or
                                                "no numbers yet")


# ---------------------------------------------------------------- ads (client money: only inside the cap they confirmed)
def ads_accounts(ref):
    d = _load()
    k = _find(d, ref)
    if not k:
        return "no such client"
    c = d["clients"][k]
    out = []
    for a in sync(k):
        if a["platform"] in ("facebook", "instagram", "linkedin", "tiktok", "googleads", "metaads"):
            plat = {"instagram": "facebook", "metaads": "facebook"}.get(a["platform"], a["platform"])
            r = _api("GET", "/connect/%s/ads" % plat, q={"profileId": c["profile_id"], "accountId": a["id"]})
            if r["ok"]:
                for x in (r["data"] or {}).get("adAccounts") or (r["data"] or {}).get("data") or []:
                    out.append("%s ad account %s (%s) via account %s" % (a["platform"], x.get("id"), x.get("name") or "",
                                                                         a["id"]))
    return "\n".join(out) or "no ad account reachable - the client connects one on their page (Publicités ...)"


def boost(ref, post, account, ad_account, budget_eur, days, goal="engagement"):
    """promote one of the client's posts. Refused above the monthly cap the CLIENT typed and confirmed on their page."""
    d = _load()
    k = _find(d, ref)
    if not k:
        return "no such client"
    c = d["clients"][k]
    if c.get("service") == "social":
        return "this client bought social only - ads are a separate service they must ask for"
    try:
        b = float(budget_eur)
        n = max(1, min(31, int(days)))
    except Exception:
        return "budget_eur and days must be numbers"
    cap = float(c.get("ads_cap_eur") or 0)
    month = time.strftime("%Y-%m")
    spent = sum(x.get("total", 0) for x in c.get("ads", []) if x.get("month") == month)
    if cap <= 0:
        return "REFUSED: the client has not confirmed a monthly ad budget on their page yet - ask them to"
    if spent + b * n > cap + 1e-6:
        return "REFUSED: %.0f EUR planned this month + %.0f would pass the client's own cap of %.0f EUR" % (spent, b * n, cap)
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 600))
    end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 600 + 86400 * n))
    r = _api("POST", "/ads/boost", {"postId": post, "accountId": account, "adAccountId": str(ad_account),
                                    "name": "Kinoverse %s %s" % (k, time.strftime("%m-%d")), "goal": goal,
                                    "budget": {"amount": round(b, 2), "type": "daily"},
                                    "schedule": {"startDate": start, "endDate": end}}, idem="kb-%s-%s" % (k, post))
    if not r["ok"]:
        return "boost failed: " + _err(r)
    ad = (r["data"] or {}).get("ad") or {}
    d = _load()
    d["clients"][k].setdefault("ads", []).append({"month": month, "ad": ad.get("_id"), "daily": b, "days": n, "total": b * n,
                                                  "post": post, "at": time.strftime("%Y-%m-%d %H:%M")})
    _save(d)
    _log("boost %s %s %.2f x %d" % (k, ad.get("_id"), b, n))
    return "boost submitted (%s, %.2f EUR/day x %d days, status %s) - tell the client" % (ad.get("_id"), b, n, ad.get("status"))


# ---------------------------------------------------------------- Kino's view
def block():
    d = _load()
    if not d["clients"]:
        return ""
    L = ["MY SOCIAL/ADS CLIENTS (social_client / social_post / social_inbox / social_reply / social_report / ads_boost):"]
    for k, c in d["clients"].items():
        ps = [p for p in d["posts"].values() if p["client"] == k]
        cnt = {s: sum(1 for p in ps if p.get("state") == s) for s in ("waiting", "approved", "sent", "failed")}
        nets = ", ".join(sorted(set(a["platform"] for a in c.get("accounts") or []))) or "NOTHING CONNECTED YET"
        L.append("- %s (%s, %s): %s | posts waiting for their yes %d, approved %d, sent %d, failed %d%s | page %s%s" % (
            k, c.get("service"), "posts alone" if c.get("auto") else "asks first", nets, cnt["waiting"], cnt["approved"],
            cnt["sent"], cnt["failed"], (" | ad cap %.0f EUR/month" % c["ads_cap_eur"]) if c.get("ads_cap_eur") else "",
            BASE, c["token"]))
    return "\n".join(L)


# ---------------------------------------------------------------- the client's page (/c/<token>)
_T = {
    "fr": {"hi": "Bonjour", "intro": "Votre espace Kinoverse. Ici, vous connectez vos réseaux, vous validez les publications que "
           "Kino a préparées, et vous voyez les résultats.", "nets": "Vos réseaux", "connect": "Connecter",
           "ok": "connecté", "how": "Vous vous connectez sur le réseau lui-même : Kino ne voit jamais votre mot de passe. "
           "Vous pouvez retirer l'accès à tout moment.", "wait": "Publications à valider", "none": "Rien à valider pour l'instant.",
           "yes": "Oui, publier", "change": "Demander un changement", "note": "Ce que vous voulez changer",
           "sent": "Déjà publié ou programmé", "auto": "Laisser Kino publier sans me demander",
           "autoon": "Kino publie sans vous demander. Vous pouvez revenir en arrière ici.", "autooff": "Revenir à : me demander avant",
           "ads": "Publicité", "cap": "Budget pub maximum par mois (EUR) - Kino ne dépensera jamais plus",
           "capok": "Confirmer ce budget", "capnow": "Budget confirmé : %s EUR / mois maximum.",
           "foot": "Kino est un assistant IA de Kinoverse. Une question : répondez simplement à son e-mail.",
           "when": "prévu le", "asap": "dès validation", "thanks": "Merci, c'est noté.",
           "s1": "Connectez vos réseaux", "s1d": "Une fois, un clic par réseau.",
           "s2": "Validez les publications", "s2d": "Kino les écrit, vous dites oui ou demandez un changement.",
           "s3": "Kino s'occupe du reste", "s3d": "Il publie, répond aux commentaires et aux avis, et vous envoie un bilan chaque mois.",
           "conn": "%s est connecté. Merci !", "nwait": "%d publication(s) attendent votre oui."},
    "en": {"hi": "Hello", "intro": "Your Kinoverse space. Connect your networks, approve the posts Kino prepared, see the results.",
           "nets": "Your networks", "connect": "Connect", "ok": "connected",
           "how": "You sign in on the network itself: Kino never sees your password. You can remove access at any time.",
           "wait": "Posts to approve", "none": "Nothing to approve right now.", "yes": "Yes, post it",
           "change": "Ask for a change", "note": "What you want changed", "sent": "Already posted or scheduled",
           "auto": "Let Kino post without asking me", "autoon": "Kino posts without asking you. You can switch back here.",
           "autooff": "Switch back: ask me first", "ads": "Advertising",
           "cap": "Maximum ad budget per month (EUR) - Kino will never spend more", "capok": "Confirm this budget",
           "capnow": "Budget confirmed: %s EUR / month maximum.",
           "foot": "Kino is an AI assistant by Kinoverse. A question? Just reply to his email.", "when": "planned for",
           "asap": "as soon as approved", "thanks": "Thank you, noted.",
           "s1": "Connect your networks", "s1d": "Once, one click per network.",
           "s2": "Approve the posts", "s2d": "Kino writes them, you say yes or ask for a change.",
           "s3": "Kino does the rest", "s3d": "He posts, answers comments and reviews, and sends you a report every month.",
           "conn": "%s is connected. Thank you!", "nwait": "%d post(s) waiting for your yes."}}


def page(tok, method="GET", form=None, query=""):
    """the client's own page. Returns (html) or None for an unknown token."""
    k, c, d = by_token(tok)
    if not k:
        return None
    t = _T.get(c.get("lang"), _T["fr"])
    msg = ""
    form = form or {}
    if method == "POST":
        act = (form.get("do") or [""])[0]
        pid = (form.get("post") or [""])[0]
        p = d["posts"].get(pid)
        if act == "yes" and p and p["client"] == k and p["state"] == "waiting":
            p["state"] = "approved"
            p["approved"] = time.strftime("%Y-%m-%d %H:%M")
            msg = t["thanks"]
        elif act == "change" and p and p["client"] == k and p["state"] == "waiting":
            p["state"] = "change"
            p["client_note"] = (form.get("note") or [""])[0][:800]
            msg = t["thanks"]
        elif act == "auto":
            c["auto"] = (form.get("v") or ["0"])[0] == "1"
            msg = t["thanks"]
        elif act == "cap" and c.get("service") in ("ads", "both"):
            try:
                c["ads_cap_eur"] = max(0.0, min(100000.0, float((form.get("cap") or ["0"])[0].replace(",", "."))))
                c["ads_cap_at"] = time.strftime("%Y-%m-%d %H:%M")
                msg = t["thanks"]
            except Exception:
                pass
        _save(d)
        _log("client page %s: %s %s" % (k, act, pid))
    if "connected=" in (query or ""):
        sync(k)
        k, c, d = by_token(tok)
        _cn = re.search(r"connected=([a-z]+)", query or "")
        if _cn and _cn.group(1) in NICE:
            msg = t["conn"] % NICE[_cn.group(1)]
    e = html.escape
    have = set(a["platform"] for a in c.get("accounts") or [])
    nets = list(NETWORKS[:6]) + ([n for n in ADS[:2]] if c.get("service") in ("ads", "both") else [])
    rows = "".join(
        '<div class="net"><span>%s</span>%s</div>' % (
            e(NICE[n]), '<b class="ok">&#10003; %s</b>' % t["ok"] if n in have else
            '<a class="btn" href="/c/%s/connect/%s">%s</a>' % (e(tok), n, t["connect"])) for n in nets)
    wait = [(i, p) for i, p in d["posts"].items() if p["client"] == k and p["state"] == "waiting"]
    sent = sorted([(i, p) for i, p in d["posts"].items() if p["client"] == k and p["state"] == "sent"],
                  key=lambda x: x[1].get("sent") or "", reverse=True)[:8]

    def card(i, p, buttons):
        img = ""
        if p.get("image", "").startswith("https://"):
            img = '<img src="%s" alt="">' % e(p["image"])
        when = (t["when"] + " " + p["when"].replace("T", " ")) if p.get("when") else t["asap"]
        b = ""
        if buttons:
            b = ('<form method="post"><input type="hidden" name="post" value="%s"><button name="do" value="yes" class="btn">%s'
                 '</button></form><details><summary>%s</summary><form method="post"><input type="hidden" name="post" '
                 'value="%s"><textarea name="note" placeholder="%s"></textarea><button name="do" value="change" '
                 'class="btn ghost">%s</button></form></details>') % (e(i), t["yes"], t["change"], e(i), t["note"], t["change"])
        return '<div class="post">%s<p>%s</p><small>%s</small>%s</div>' % (img, e(p["text"]).replace("\n", "<br>"), e(when), b)
    w = "".join(card(i, p, True) for i, p in wait) or '<p class="muted">%s</p>' % t["none"]
    s = "".join(card(i, p, False) for i, p in sent)
    auto = ('<form method="post"><input type="hidden" name="v" value="%s"><button name="do" value="auto" class="btn ghost">%s'
            '</button></form>%s') % ("0" if c.get("auto") else "1", t["autooff"] if c.get("auto") else t["auto"],
                                     '<p class="muted">%s</p>' % t["autoon"] if c.get("auto") else "")
    done1 = bool(have)
    done2 = not wait and bool(sent)
    steps = "".join('<div class="st%s"><b>%s</b><div><strong>%s</strong><small>%s</small></div></div>' % (
        " done" if dn else "", "&#10003;" if dn else n, t["s%s" % n], t["s%sd" % n])
        for n, dn in (("1", done1), ("2", done2), ("3", False)))
    if wait and not msg:
        msg = t["nwait"] % len(wait)
    ads = ""
    if c.get("service") in ("ads", "both"):
        ads = ('<h2>%s</h2><form method="post" class="cap"><label>%s<input name="cap" inputmode="decimal" value="%s"></label>'
               '<button name="do" value="cap" class="btn">%s</button></form>%s') % (
            t["ads"], t["cap"], ("%.0f" % c["ads_cap_eur"]) if c.get("ads_cap_eur") else "", t["capok"],
            ('<p class="muted">%s</p>' % (t["capnow"] % ("%.0f" % c["ads_cap_eur"]))) if c.get("ads_cap_eur") else "")
    return """<!doctype html><html lang="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Kinoverse - %s</title><style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--mut:#6b6b70;--acc:#4f46e5;--line:#e6e4df}
@media (prefers-color-scheme:dark){:root{--bg:#131316;--card:#1d1d22;--ink:#f2f2f4;--mut:#a0a0a8;--acc:#8b85ff;--line:#2c2c33}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:640px;margin:0 auto;padding:28px 16px 60px}h1{font-size:26px;margin:0 0 6px}h2{font-size:18px;margin:32px 0 10px}
.muted,small{color:var(--mut)}.net,.post{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:8px 0}
.net{display:flex;justify-content:space-between;align-items:center;gap:10px}.ok{color:#16a34a;font-weight:600}
.btn{display:inline-block;background:var(--acc);color:#fff;border:0;border-radius:10px;padding:9px 16px;font:600 15px system-ui;text-decoration:none;cursor:pointer}
.btn.ghost{background:transparent;color:var(--acc);border:1px solid var(--acc)}.post img{width:100%%;border-radius:10px}
.post form{display:inline-block;margin:10px 8px 0 0}details{margin-top:8px}textarea,input{width:100%%;margin:6px 0;padding:10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);font:15px system-ui}
.steps{display:grid;gap:8px;margin:18px 0 6px}.steps>div{display:flex;gap:12px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.steps b{flex:0 0 30px;height:30px;border-radius:50%%;background:var(--acc);color:#fff;display:grid;place-items:center;font-size:15px}
.steps .done b{background:#16a34a}.steps strong{display:block}.steps small{display:block;line-height:1.35}
.msg{background:#16a34a22;border-radius:10px;padding:10px 14px}.brand{font-weight:700;letter-spacing:.3px;color:var(--acc)}
</style></head><body><main><div class="brand">Kinoverse</div><h1>%s, %s</h1><p class="muted">%s</p>%s
<div class="steps">%s</div>
<h2>1. %s</h2>%s<p class="muted">%s</p><h2>2. %s</h2>%s%s%s%s<p class="muted" style="margin-top:40px">%s</p></main></body></html>""" % (
        c.get("lang"), e(c["name"]), t["hi"], e(c["name"]), t["intro"], ('<p class="msg">%s</p>' % e(msg)) if msg else "",
        steps, t["nets"], rows, t["how"], t["wait"], w, auto, ads, ("<h2>%s</h2>%s" % (t["sent"], s)) if s else "", t["foot"])


def tick():
    """from the online tick: send approved posts; quiet otherwise"""
    try:
        if _load()["posts"]:
            return send_due()
    except Exception as e:
        _log("tick error %s" % e)
    return []
