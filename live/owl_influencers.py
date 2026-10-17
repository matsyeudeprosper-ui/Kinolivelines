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


def apply(uid, channel, video, note=""):
    """a member asks to join: channel + the video that mentions the app. A refused member may apply again."""
    ch, vd = _clean_url(channel), _clean_url(video)
    if not ch:
        return {"ok": False, "err": "channel"}
    if not vd:
        return {"ok": False, "err": "video"}
    with _LOCK:
        d = _load()
        cur = d.get(uid) or {}
        if cur.get("status") == "approved":
            return {"ok": False, "err": "already"}
        d[uid] = {"channel": ch, "video": vd, "note": str(note or "").strip()[:240], "status": "pending",
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
