"""owl_influencers.py - creators / YouTubers who talk about OwlNest to their audience (owner 2026-10-17).

A member applies with their channel and the video that mentions the app; the owner checks the video and approves
with a button; from then on every month their referred users pay credits the creator INF_PCT (owl_wallet), as long
as those users keep paying. One code, one rule: an approved creator's code pays 30 % every month instead of the
standard 50 % once. Creators may promote Signal and Strategie, never Automatique (on invitation only).

File: live/owl_influencers.json {uid: {"channel", "video", "note", "status": pending|approved|refused,
                                       "applied_t", "reviewed_t", "review_note"}}
"""
import json, os, time, threading, re

DIR = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(DIR, "owl_influencers.json")
_LOCK = threading.Lock()


def _load():
    try:
        return json.load(open(FILE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = FILE + ".%d.tmp" % os.getpid()
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, FILE)


def _clean_url(u, maxlen=200):
    u = str(u or "").strip()[:maxlen]
    if u and not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u if re.match(r"^https?://[\w\-]+(\.[\w\-]+)+(/[^\s]*)?$", u, re.I) else ""      # a real host, with a dot


def status(uid):
    """the creator record for this member, or None"""
    return _load().get(uid)


def is_approved(uid):
    r = _load().get(uid) or {}
    return r.get("status") == "approved"


PLATFORMS = ("youtube", "tiktok", "instagram", "facebook", "telegram", "blog", "podcast", "other")
PRIVATE = ("telegram", "facebook")     # may be a closed group: the proof is the invite link + a screenshot sent to the Owl


def apply(uid, channel, video, note="", platform="youtube"):
    """a member asks to join (owner 2026-10-17: any platform, not only YouTube): where they publish (optional profile
    or page link), the PUBLICATION that mentions the app - a video, a post, an article, a pinned message - which must
    show their link or code, and a note. A refused member may apply again."""
    platform = str(platform or "youtube").lower()
    if platform not in PLATFORMS:
        platform = "other"
    ch, vd = _clean_url(channel), _clean_url(video)
    if not vd:
        return {"ok": False, "err": "video"}
    with _LOCK:
        d = _load()
        cur = d.get(uid) or {}
        if cur.get("status") == "approved":
            return {"ok": False, "err": "already"}
        d[uid] = {"platform": platform, "channel": ch, "video": vd, "note": str(note or "").strip()[:240], "status": "pending",
                  "applied_t": int(time.time()), "reviewed_t": None, "review_note": ""}
        _save(d)
    return {"ok": True}


def review(uid, approve, note=""):
    """the owner's button"""
    with _LOCK:
        d = _load()
        r = d.get(uid)
        if not r:
            return {"ok": False, "err": "unknown"}
        r["status"] = "approved" if approve else "refused"
        r["reviewed_t"] = int(time.time()); r["review_note"] = str(note or "").strip()[:240]
        _save(d)
    return {"ok": True, "status": r["status"]}


def pending():
    """[{uid, channel, video, note, applied_t}] waiting for the owner"""
    return sorted([dict(v, uid=k) for k, v in _load().items() if v.get("status") == "pending"], key=lambda x: x.get("applied_t") or 0)


def approved_uids():
    return {k for k, v in _load().items() if v.get("status") == "approved"}


# ---- automatic check (owner 2026-10-17: "approve without asking, all automated") ----
AUTO_APPROVE = True
FETCH_TIMEOUT = 12
FETCH_MAX = 2 * 1024 * 1024


def _public_host(url):
    """SSRF guard: only http(s) to a public address - never our own server, a LAN box or a cloud metadata address"""
    import socket, ipaddress
    from urllib.parse import urlparse
    try:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False
        if u.hostname.lower().endswith(("owltrader.duckdns.org", "duckdns.org")):
            return False                     # our own pages always show the code: never a proof
        if u.hostname.lower() in ("localhost",) or u.hostname.replace(".", "").isdigit():
            return False                     # names only; a bare IP is never a publication
        for info in socket.getaddrinfo(u.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                return False
        return True
    except Exception:
        return False


def fetch_text(url):
    """the publication's page, as text (HTML, best effort), or None"""
    import urllib.request
    if not _public_host(url):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 13) OwlNest-check/1.0", "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
            if not _public_host(r.geturl()):
                return None
            return r.read(FETCH_MAX).decode("utf-8", "replace")
    except Exception:
        return None


def verify(uid, code, link=""):
    """fetch the publication and look for the member's code or link. Records the result on the application:
    auto_check = {"t", "found", "reason"}. Returns the record. Approves when found and AUTO_APPROVE is on."""
    r = _load().get(uid)
    if not r:
        return None
    url = r.get("video") or ""
    txt = fetch_text(url)
    found = False; reason = ""
    if txt is None:
        reason = "page illisible (site fermé ou privé)"
    else:
        hay = txt.upper()
        if code and code.upper() in hay:
            found = True; reason = "code trouvé sur la page"
        elif link and link.lower() in txt.lower():
            found = True; reason = "lien trouvé sur la page"
        else:
            reason = "code absent de la page"
    with _LOCK:
        d = _load()
        r = d.get(uid)
        if not r:
            return None
        r["auto_check"] = {"t": int(time.time()), "found": found, "reason": reason}
        if found and AUTO_APPROVE and r.get("status") == "pending":
            r["status"] = "approved"; r["reviewed_t"] = int(time.time()); r["review_note"] = "auto : " + reason
        _save(d)
    return r
