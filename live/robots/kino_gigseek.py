"""
Kino's hunt for helpers - people who SAY they want work (owner plan 2026-11-14, step 4 of mt5_kino_world_helpers_plan).

Where: Bluesky search and Mastodon hashtags (#getfedihired, #hireme, #opentowork...), in many languages - both reachable
from the VPS (Reddit blocks it). A cheap brain keeps only real people looking for work, and notes what they can do,
where they live, their languages, whether they can work remotely.

How Kino reaches them: an ordinary reply to their post with skeet/toot url=... - the friends gate applies (spacing, daily
allowance of people who ASKED, no link in a first word). They asked for work, so mentioning small paid tasks is answering
them; the link (https://chat.kinoverse ai.com/?gigs=1 - opens the sign-up sheet) only once they answer.

Demand first: kino_reach.priorities() places (people waiting, nobody there) get searched by name first.
Store: kino_gigseek.json {"seen": {post_url: t}, "cands": [...], "scans": [t...]}
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_gigseek.json")
LOG = os.path.join(HERE, "kino_gigseek.log")
_LK = threading.Lock()
LINK = "https://chat.kinoverseai.com/?gigs=1"
SCAN_EVERY_H = 6
FRESH_DAYS = 4

BSKY_Q = ['"looking for work"', '"looking for gigs"', '"open to work"', '"available for hire"', '"hire me"',
          '"cherche du travail"', '"cherche un job"', '"cherche des missions"', '"recherche emploi"', '"petits boulots"',
          '"busco trabajo"', '"procuro emprego"', '"virtual assistant" available', '"freelance" "available"']
MASTO_TAGS = ["getfedihired", "hireme", "opentowork", "fedihire", "lookingforwork", "jobsearch"]


def _log(line):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _j():
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seen": {}, "cands": [], "scans": []}


def _mut(fn):
    with _LK:
        d = _j()
        r = fn(d)
        tmp = STORE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
        return r


def _get(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Kinoverse helper search)"}),
                               timeout=20)
    return json.loads(r.read().decode("utf-8", "replace"))


def _iso_t(s):
    try:
        return time.mktime(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except Exception:
        return 0


def _strip_html(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(h or ""))).strip()


def _bsky_posts(queries):
    import kino_post as KP
    tok, _, me = KP._bsky_session()
    out = []
    for q in queries:
        try:
            r = KP._bsky("app.bsky.feed.searchPosts?q=%s&limit=25&sort=latest" % urllib.parse.quote(q), None, tok)
        except Exception as e:
            _log("bsky %s: %s" % (q, str(e)[:80]))
            continue
        for p in r.get("posts") or []:
            h = (p.get("author") or {}).get("handle") or ""
            if h == me:
                continue
            rk = str(p.get("uri") or "").rsplit("/", 1)[-1]
            out.append({"where": "bluesky", "who": "@" + h, "name": (p.get("author") or {}).get("displayName") or h,
                        "url": "https://bsky.app/profile/%s/post/%s" % (h, rk), "text": (p.get("record") or {}).get("text") or "",
                        "t": _iso_t((p.get("record") or {}).get("createdAt")), "q": q})
    return out


def _masto_posts(tags):
    out = []
    for tg in tags:
        try:
            r = _get("https://mastodon.social/api/v1/timelines/tag/%s?limit=30" % tg)
        except Exception as e:
            _log("masto %s: %s" % (tg, str(e)[:80]))
            continue
        for p in r or []:
            a = p.get("account") or {}
            out.append({"where": "mastodon", "who": "@" + (a.get("acct") or ""), "name": a.get("display_name") or a.get("acct"),
                        "url": p.get("url") or p.get("uri") or "", "text": _strip_html(p.get("content")),
                        "t": _iso_t(p.get("created_at")), "q": "#" + tg})
    return out


_SYS = ("You sort social posts. For each numbered post decide if its AUTHOR is a real person (not a company, recruiter, bot, "
        "news or job board) who is looking for paid work for THEMSELVES. Reply ONLY a JSON list, one object per post that is: "
        "{\"n\": number, \"skills\": \"short\", \"city\": \"or empty\", \"country\": \"or empty\", \"langs\": \"languages the "
        "post shows or says, comma separated\", \"remote\": true|false (can work remotely), \"fit\": 1-5 (how well they "
        "could do small paid tasks: phone calls, online research, forms, errands, posting ads)}. Posts that are not "
        "people seeking work are simply left out. Also leave out anyone who says they dislike, refuse or lost work to AI "
        "(an AI offering them tasks would hurt). Never invent a place.")


def _qualify(posts):
    import robot_warm as RW
    keep = []
    for i in range(0, len(posts), 15):
        chunk = posts[i:i + 15]
        user = "\n\n".join("%d. %s (%s): %s" % (k, p["name"], p["where"], p["text"][:500]) for k, p in enumerate(chunk))
        try:
            raw = RW.ask_text(_SYS, user, model="haiku", timeout=120)
            a = str(raw or "").find("[")
            L = json.JSONDecoder().raw_decode(raw[a:])[0] if a >= 0 else []
        except Exception as e:
            _log("qualify: %s" % str(e)[:120])
            continue
        for x in L:
            try:
                p = dict(chunk[int(x["n"])])
            except Exception:
                continue
            p.update(skills=str(x.get("skills") or "")[:120], city=str(x.get("city") or "")[:60],
                     country=str(x.get("country") or "")[:60], langs=str(x.get("langs") or "")[:60],
                     remote=bool(x.get("remote")), fit=int(x.get("fit") or 0))
            keep.append(p)
    return keep


def scan(force=False):
    """search, qualify, store new gig seekers -> a sentence"""
    d = _j()
    if not force and d.get("scans") and time.time() - d["scans"][-1] < SCAN_EVERY_H * 3600:
        return "searched %.1f h ago - nothing new to search yet" % ((time.time() - d["scans"][-1]) / 3600.0)
    qs = list(BSKY_Q)
    try:
        import kino_reach as KR                 # demand first: where people wait and nobody is there
        for n, _, country, city, _w in KR.priorities(4):
            place = city or country
            qs = ['"%s" "cherche du travail"' % place, '"%s" "looking for work"' % place] + qs
    except Exception:
        pass
    posts = _bsky_posts(qs) + _masto_posts(MASTO_TAGS)
    now = time.time()
    seen = d.get("seen") or {}
    known = {c["who"] for c in d.get("cands") or []}
    fresh, uniq = [], set()
    for p in posts:
        if not p["url"] or p["url"] in seen or p["who"] in known or p["who"] in uniq or now - p["t"] > FRESH_DAYS * 86400:
            continue
        uniq.add(p["who"])
        fresh.append(p)
    keep = [p for p in _qualify(fresh[:90]) if p.get("fit", 0) >= 3]
    for p in keep:
        p.update(status="found", found_t=now)

    def f(dd):
        S = dd.setdefault("seen", {})
        for p in fresh:
            S[p["url"]] = now
        if len(S) > 5000:
            for k in sorted(S, key=S.get)[:len(S) - 5000]:
                S.pop(k, None)
        dd.setdefault("cands", []).extend(keep)
        dd["cands"] = dd["cands"][-400:]
        dd.setdefault("scans", []).append(now)
        dd["scans"] = dd["scans"][-50:]
    _mut(f)
    _log("SCAN %d posts, %d new, %d kept" % (len(posts), len(fresh), len(keep)))
    return "searched %d posts: %d new, %d people looking for work kept" % (len(posts), len(fresh), len(keep))


def mark(who, status, note=""):
    """found -> invited -> answered -> joined | no"""
    def f(d):
        for c in d.get("cands") or []:
            if c["who"].lower() == str(who).lower():
                c["status"] = status
                c[status + "_t"] = time.time()
                if note:
                    c["note"] = str(note)[:200]
                return True
    ok = _mut(f)
    _log("MARK %s %s" % (who, status))
    return "%s is now %s" % (who, status) if ok else "nobody called %s in the helper hunt" % who


def block(limit=6):
    d = _j()
    C = d.get("cands") or []
    if not C and not d.get("scans"):
        return "HELPER HUNT: no search yet - gig_scan searches Bluesky and Mastodon for people looking for work"
    st = {}
    for c in C:
        st[c.get("status")] = st.get(c.get("status"), 0) + 1
    last = d["scans"][-1] if d.get("scans") else 0
    todo = sorted([c for c in C if c.get("status") == "found"], key=lambda c: (c.get("fit", 0), c.get("t", 0)), reverse=True)
    lines = ["HELPER HUNT (people who said they want work; last search %s): %s" % (
        ("%.0f h ago" % ((time.time() - last) / 3600.0)) if last else "never",
        ", ".join("%s %d" % kv for kv in st.items()) or "nobody yet")]
    for c in todo[:limit]:
        lines.append("- %s on %s (%s%s%s, %s) said: \"%s\" - %s" % (
            c["who"], c["where"], c.get("skills") or "?", (", " + (c.get("city") or c.get("country"))) if (c.get("city") or c.get("country")) else "",
            ", remote ok" if c.get("remote") else "", c.get("langs") or "?", c["text"][:140].replace("\n", " "), c["url"]))
    if todo:
        lines.append("Reach them as a person: reply to THEIR post (skeet/toot url=...) in THEIR language, about what they "
                     "said, then that you sometimes have small paid tasks (calls, online research, errands), paid per task, "
                     "and ask if they would like you to send them some. No link in that first word; once they say yes, "
                     "give %s (it opens the sign-up) and gig_mark who invited/answered/joined/no." % LINK)
    return "\n".join(lines)


if __name__ == "__main__":
    print(scan(force=True))
    print(block())
