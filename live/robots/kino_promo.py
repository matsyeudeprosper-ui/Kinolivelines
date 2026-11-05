"""kino_promo.py (2026-11-05, owner: "make him as independent as a real human... he should figure out the best strategies, follow
up, update... He is a master promoter of himself").

A promoter who cannot see what his work brings is guessing. This gives Kino, in every session at his computer, what came back
from what he did - the same anonymous counters the owner sees:
  - the app's funnel per day (owl_funnel.json): visits to the landing, the demo opened, messages people wrote him in the demo,
    free sign-ups, payments started / paid
  - where visits came from (owl_usage.json "src_*": links tagged ?src=bsky, ?src=blog... - his own tags show up here)
  - what he posted, where (kino_posts.json)
  - his reach on Bluesky (public profile and his recent posts' likes / reposts / replies, public API, cached 1 h)
and where his strategy lives (C:\\KinoWorld\\projects\\promotion\\strategy.md - his to write and revise).
No person is identified anywhere: counts only.
"""
import json, os, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
STRATEGY = r"C:\KinoWorld\projects\promotion\strategy.md"
CASES = r"C:\KinoWorld\projects\promotion\case_studies"
BSKY_HANDLE = "kinoverse.bsky.social"
DEMO = "https://owltrader.duckdns.org/demo"
_BS = {"t": 0.0, "v": None}


def _j(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _days(n):
    t = time.time()
    return [time.strftime("%Y-%m-%d", time.gmtime(t - i * 86400)) for i in range(n - 1, -1, -1)]


def bsky(now=None):
    """followers, posts, and likes/reposts/replies on his last 20 posts (public API, no login) - cached 1 h"""
    now = now or time.time()
    if _BS["v"] is not None and now - _BS["t"] < 3600:
        return _BS["v"]
    v = None
    try:
        base = "https://public.api.bsky.app/xrpc/"
        pr = json.load(urllib.request.urlopen(base + "app.bsky.actor.getProfile?actor=" + BSKY_HANDLE, timeout=10))
        fd = json.load(urllib.request.urlopen(base + "app.bsky.feed.getAuthorFeed?limit=20&actor=" + BSKY_HANDLE, timeout=10))
        F = [x.get("post") or {} for x in fd.get("feed") or []]
        v = {"followers": pr.get("followersCount"), "following": pr.get("followsCount"), "posts": pr.get("postsCount"),
             "likes": sum(int(p.get("likeCount") or 0) for p in F), "reposts": sum(int(p.get("repostCount") or 0) for p in F),
             "replies": sum(int(p.get("replyCount") or 0) for p in F), "recent": len(F)}
    except Exception:
        v = None
    _BS.update(t=now, v=v)
    return v


def results(days=7):
    """one plain block for his work session"""
    D = _days(days)
    fun = _j(os.path.join(LIVE, "owl_funnel.json"), {}) or {}
    us = (_j(os.path.join(LIVE, "owl_usage.json"), {}) or {}).get("day") or {}
    keys = (("landing", "visits to the app's page"), ("meet_open", "demo opened"), ("meet_msg", "messages people wrote you in the demo"),
            ("free_signup", "free sign-ups"), ("pay_created", "payments started"), ("paid", "paid"))
    L = ["YOUR PROMOTION RESULTS (anonymous counts, last %d days, UTC; today last):" % days]
    for k, lab in keys:
        L.append("- %s: %s" % (lab, " ".join(str(int((fun.get(d) or {}).get(k, 0))) for d in D)))
    src = {}
    for d in D:
        for k, v in (us.get(d) or {}).items():
            if k.startswith("src_"):
                src[k[4:]] = src.get(k[4:], 0) + int(v)
    L.append("- visits by source (your ?src= tags): " + (", ".join("%s %d" % kv for kv in sorted(src.items(), key=lambda z: -z[1])) or
                                                        "none yet - tag every link you share, e.g. %s?src=bsky, ?src=blog, ?src=masto" % DEMO))
    P = _j(os.path.join(HERE, "kino_posts.json"), []) or []
    P = P if isinstance(P, list) else (list(P.values())[0] if P else [])
    t0 = time.time() - days * 86400
    by = {}
    for x in P:
        if float(x.get("t") or 0) >= t0 and x.get("ok"):
            by[x.get("channel") or "?"] = by.get(x.get("channel") or "?", 0) + 1
    L.append("- what you posted: " + (", ".join("%s %d" % kv for kv in sorted(by.items())) or "nothing in %d days" % days))
    b = bsky()
    if b:
        L.append("- Bluesky now: %s followers, %s posts; on your last %s posts %s likes, %s reposts, %s replies" % (
            b["followers"], b["posts"], b["recent"], b["likes"], b["reposts"], b["replies"]))
    try:                                      # 2026-11-05 (owner "yes"): his portfolio for the future promotion service
        cs = [f for f in os.listdir(CASES) if f.endswith(".md")]
        L.append("- your case studies (portfolio for the promotion service you will offer): %d written%s" % (
            len(cs), (", latest " + sorted(cs)[-1]) if cs else " - write one when a campaign or a week of trying ends"))
    except Exception:
        L.append("- your case studies: none yet (%s) - write one when a campaign or a week of trying ends" % CASES)
    try:
        st = os.path.getmtime(STRATEGY)
        L.append("- your strategy (%s, last revised %s UTC): read it first, act on it, and revise it when the numbers teach you "
                 "something" % (STRATEGY, time.strftime("%d/%m %H:%M", time.gmtime(st))))
    except Exception:
        L.append("- you have no written strategy yet: write %s first - who you want to reach, where they are, what you offer them, "
                 "how you will know it works - then act on it" % STRATEGY)
    return "\n".join(L)


if __name__ == "__main__":
    print(results())
