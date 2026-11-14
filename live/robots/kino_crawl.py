"""
Kino's eyes inside social media and booking sites, without an account (owner 2026-11-14: SocialCrawl API, tested).

One API, ~75 sites, read only, any country: Reddit, X, TikTok, Instagram, Facebook (public pages and PUBLIC groups),
YouTube, LinkedIn, Threads, Telegram, Bluesky, Airbnb, Booking, Google, Yelp, Tripadvisor, Trustpilot, eBay, jobs...
Tested 14/11: Airbnb listings real (title/place checked on airbnb.fr), dated prices returned (USD), Brazzaville OK,
Reddit [For Hire] posts real (Reddit's own url slug = the title). Not tested: whether prices match the checkout to the
cent - a booking's price is always re-read by the person who places it.

Key: C:\\ProgramData\\kino_secret\\socialcrawl.json (never in code, never in a URL). Every call is GET, capped per day
(credits cost money), counted from the API's own X-Credits-Used header. Docs per site: https://www.socialcrawl.dev/llms-<site>.txt
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_crawl.json")
LOG = os.path.join(HERE, "kino_crawl.log")
SECRET = r"C:\ProgramData\kino_secret\socialcrawl.json"
DAY_CAP = 60                          # credits a day (free test pack: 100 in all; raise once the owner buys a pack)
_LK = threading.Lock()


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
        return {"days": {}, "left": None, "fx": {}}


def _mut(fn):
    with _LK:
        d = _j()
        r = fn(d)
        tmp = STORE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
        return r


def used_today():
    return int((_j().get("days") or {}).get(time.strftime("%Y-%m-%d"), 0))


def get(path, **q):
    """-> (data dict, None) or (None, why). Only GET, only /v1 paths, within the day's credits."""
    path = "/" + str(path or "").strip().lstrip("/")
    if path.startswith("/v1/"):
        path = path[3:]
    if not re.match(r"^/[a-z0-9_/\-]+$", path):
        return None, "a path like /airbnb/search or /reddit/search"
    if used_today() >= DAY_CAP:
        return None, "the day's look-around budget is used (%d credits); tomorrow" % DAY_CAP
    try:
        c = json.load(open(SECRET, encoding="utf-8"))
    except Exception:
        return None, "no SocialCrawl key"
    q = {k: v for k, v in q.items() if v not in (None, "")}
    # 14/11: NOT max_credits by default - sent alone it makes a search walk up to 50 pages (a 1-credit search cost 21)
    q.setdefault("max_pages", 1)
    u = c.get("base", "https://www.socialcrawl.dev/v1") + path + "?" + urllib.parse.urlencode(q)
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={"x-api-key": c["api_key"], "User-Agent": "kinoverse"}),
                                   timeout=120)
        d = json.loads(r.read().decode("utf-8", "replace"))
        n, left = int(r.headers.get("X-Credits-Used") or 0), r.headers.get("X-Credits-Remaining")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        _log("ERR %s %s %s" % (path, e.code, body[:160]))
        return None, "the site answered %s: %s" % (e.code, body[:200])
    except Exception as e:
        _log("ERR %s %s" % (path, str(e)[:160]))
        return None, "could not reach it (%s)" % str(e)[:120]

    def f(dd):
        day = time.strftime("%Y-%m-%d")
        dd.setdefault("days", {})[day] = int(dd["days"].get(day, 0)) + n
        if left is not None:
            dd["left"] = int(left)
    _mut(f)
    _log("GET %s %s credits=%d left=%s" % (path, json.dumps(q, ensure_ascii=False)[:160], n, left))
    return d, None


_DROP = re.compile(r"image|thumbnail|avatar|cover|cursor|request_id|_ids|muscache|embed|html|video_url|audio", re.I)


def _slim(x, depth=0):
    """what a reader needs: no images, ids lists, cursors, empty fields"""
    if isinstance(x, dict):
        return {k: _slim(v, depth + 1) for k, v in x.items() if v not in (None, "", [], {}) and not _DROP.search(k)}
    if isinstance(x, list):
        return [_slim(v, depth + 1) for v in x[:25]]
    if isinstance(x, str):
        return x[:600]
    return x


_OUT = {"t": 0}                       # credits out / service down: plain web search for an hour, owner told once a day


def _down(why):
    """the API cannot serve (cap, no credits, error) -> remember it, tell the owner once a day"""
    # only a truly empty pack alerts the owner - the daily cap ("budget is used") is ours, not the pack's
    out = bool(re.search(r"\b402\b|insufficient|out of credits|no credits|credit balance|not enough credits", str(why), re.I))
    _OUT["t"] = time.time()
    if out:
        d = _j()
        if time.time() - float(d.get("told_t") or 0) > 20 * 3600:
            _mut(lambda dd: dd.__setitem__("told_t", time.time()))
            try:
                import kino_work as KW
                if KW.NOTIFY:
                    KW.NOTIFY("SocialCrawl: plus de crédits (%s). Kino passe à la recherche web normale en attendant - "
                              "un pack sur socialcrawl.dev le remet en route." % str(why)[:80])
            except Exception:
                pass


def _web(q, why):
    """the fallback: his ordinary web search (DuckDuckGo -> Bing -> Claude WebSearch)"""
    try:
        import kino_web as KWB
        R = KWB.search(q, 8)
    except Exception as e:
        return "NOT READ - %s, and the web search failed too (%s)" % (why, str(e)[:80])
    if not R:
        return "NOT READ - %s; the web search found nothing for: %s" % (why, q)
    return ("(inside-sites reader unavailable: %s - ordinary web search instead, less precise; open a result with fetch)\n" % why +
            "\n".join("- %s | %s | %s" % (r.get("title", "")[:90], r.get("url"), (r.get("snippet") or "")[:160]) for r in R))


def _query_of(path, params):
    p = params or {}
    site = str(path).strip("/").split("/")[0].replace("_", " ")
    q = p.get("query") or p.get("q") or p.get("keywords") or p.get("location") or p.get("subreddit") or p.get("url") or p.get("handle") or ""
    return ("%s %s" % (q, site)).strip()


def look(path, params=None, limit_chars=6000):
    """the desk's general eye: any read endpoint -> slim JSON text; plain web search when it cannot serve"""
    if time.time() - _OUT["t"] < 3600 and used_today() >= DAY_CAP:
        return _web(_query_of(path, params), "today's budget is used")
    d, why = get(path, **(params or {}))
    if why:
        if "a path like" in why:
            return "NOT READ - " + why
        _down(why)
        return _web(_query_of(path, params), why)
    s = json.dumps(_slim(d.get("data", d)), ensure_ascii=False)
    return s[:limit_chars] + (" …(cut)" if len(s) > limit_chars else "")


def fx(cur_from="USD", cur_to="EUR"):
    """ECB rate (frankfurter.dev), refreshed daily; None when unknown"""
    key = "%s%s" % (cur_from.upper(), cur_to.upper())
    d = _j()
    e = (d.get("fx") or {}).get(key)
    if e and time.time() - e["t"] < 86400:
        return e["r"]
    try:
        r = json.loads(urllib.request.urlopen("https://api.frankfurter.dev/v1/latest?base=%s&symbols=%s" % (
            cur_from.upper(), cur_to.upper()), timeout=20).read())["rates"][cur_to.upper()]
    except Exception:
        return e["r"] if e else None
    _mut(lambda dd: dd.setdefault("fx", {}).__setitem__(key, {"r": r, "t": time.time()}))
    return r


def money(amount, cur, to="EUR"):
    if str(cur).upper() == to.upper():
        return "%.0f %s" % (float(amount), to)
    r = fx(cur, to)
    return ("about %.0f %s (%s %s)" % (float(amount) * r, to, amount, cur)) if r else "%s %s" % (amount, cur)


def stays(location, check_in="", check_out="", adults=2, site="airbnb", children=0):
    """places to stay (Airbnb or Booking) for a place and dates -> lines; give the postcode or 'city, country' for precision"""
    d, why = get("/%s/search" % ("booking" if site == "booking" else "airbnb"), location=location, check_in=check_in,
                 check_out=check_out, adults=adults, children=children or None)
    if why:
        _down(why)
        return _web("%s %s %s %s" % (site, location, check_in, check_out), why)
    out = []
    for it in ((d.get("data") or {}).get("items") or [])[:12]:
        p = it.get("place") or it
        out.append("- %s | %s | rating %s (%s reviews)%s" % (
            p.get("name"), p.get("url"), (p.get("rating") or {}).get("value"), p.get("reviews_count"),
            (" | " + str((p.get("ext") or {}).get("subtitle")))[:120] if (p.get("ext") or {}).get("subtitle") else ""))
    return ("%d places (no price in a search - stay_price one listing for the real price for the dates):\n" % len(out) +
            "\n".join(out)) if out else "no place found there - try 'city postcode' or 'city, country'"


def stay_price(listing, check_in, check_out, adults=2, site="airbnb"):
    """the real price of one listing for the dates, converted to EUR"""
    k = {"url": listing} if str(listing).startswith("http") else {"id": listing}
    d, why = get("/%s/%s" % ("booking" if site == "booking" else "airbnb", "hotel" if site == "booking" else "listing"),
                 check_in=check_in, check_out=check_out, adults=adults, **k)
    if why:
        _down(why)
        try:                                   # fallback: the page itself (the price may be hidden to a robot)
            import kino_web as KWB
            t = KWB.fetch(listing if str(listing).startswith("http") else "https://www.airbnb.fr/rooms/%s" % listing, 4000)
            pr = re.findall(r"[^\n]{0,40}\d[\d  ]*\s?(?:€|EUR|\$)[^\n]{0,40}", str(t))
            return ("(price reader unavailable: %s) %s" % (why, ("; ".join(pr[:4]) if pr else
                    "the page does not show the price to a robot - give the listing link, the person who books reads it at checkout")))
        except Exception:
            return "NOT READ - %s; the person who books reads the price at checkout" % why
    s = json.dumps(d, ensure_ascii=False)
    P = re.findall(r'\{"title": "([^"]+)", "price": ([0-9.]+), "currency": "([A-Z]{3})"', s)
    if not P:
        return "no price for these dates (maybe not available): " + look_slim(d)[:600]
    return "; ".join("%s: %s" % (t, money(p, c)) for t, p, c in P) + \
        " - a shown price; the person who books re-reads it at checkout"


def look_slim(d):
    return json.dumps(_slim(d.get("data", d) if isinstance(d, dict) else d), ensure_ascii=False)


_ROUTE = ("You choose where to look for a question, like a person choosing the right site. TODAY is %s. Reply ONLY JSON:\n"
          "{\"use\": \"stays\", \"location\": \"town + its postcode when you know it (Viry-Chatillon 91170), never 'town, country' for a small town\", \"check_in\": \"YYYY-MM-DD\", \"check_out\": "
          "\"YYYY-MM-DD\", \"adults\": n, \"site\": \"airbnb|booking\", \"cheapest\": true|false} - a place to stay with dates "
          "(tomorrow = one night unless said; no dates -> use 'web');\n"
          "{\"use\": \"look\", \"path\": \"/site/endpoint\", \"params\": {...}} - something inside a site: posts or people on "
          "Reddit (/reddit/search {query}), TikTok (/tiktok/search {query}), Instagram (/instagram/search/reels {query}), X "
          "(/twitter/ai-search {query}), YouTube (/youtube/search {query}), product prices (/google_shopping/product-search "
          "{query, country}, /amazon/product-search {query}, /ebay/search {query}, /aliexpress/search {query}), reviews "
          "(/yelp/search, /tripadvisor/search {query, location});\n"
          "{\"use\": \"web\"} - anything else (facts, news, how-to, opening hours, a company, a law).")


def _near(P, location):
    """keep the places around the asked town: its centre = the places whose name says the town; others within 15 km"""
    import math
    town = re.sub(r"[^a-z ]", " ", __import__("unicodedata").normalize("NFKD", str(location).split(",")[0]).encode("ascii", "ignore").decode().lower())
    town = " ".join(w for w in town.split() if len(w) > 2)

    def nm(p):
        return re.sub(r"[^a-z ]", " ", __import__("unicodedata").normalize("NFKD", str(p.get("name") or "")).encode("ascii", "ignore").decode().lower())
    core = [p for p in P if town and town.split()[0] in nm(p) and p.get("latitude")]
    if not core:
        return []                                  # nothing says the town: do not present far places as that town
    la = sorted(float(p["latitude"]) for p in core)[len(core) // 2]
    lo = sorted(float(p["longitude"]) for p in core)[len(core) // 2]

    def km(p):
        try:
            return 111 * math.hypot(float(p["latitude"]) - la, (float(p["longitude"]) - lo) * math.cos(math.radians(la)))
        except Exception:
            return 999
    return [p for p in P if km(p) <= 15]


def smart(q):
    """2026-11-14 (owner: 'je n'ai pas trouvé de vrai prix pour demain à Viry' then 'mets Viry sur Airbnb et trie'):
    his quick #cherche goes INSIDE the right site when that is where the answer lives -> text, or None (plain web)"""
    if time.time() - _OUT["t"] < 3600 and used_today() >= DAY_CAP:
        return None
    try:
        import robot_warm as RW
        raw = RW.ask_text(_ROUTE % time.strftime("%A %Y-%m-%d"), str(q)[:400], model="haiku", timeout=40)
        i = str(raw or "").find("{")
        R = json.JSONDecoder().raw_decode(raw[i:])[0] if i >= 0 else {}
    except Exception as e:
        _log("route: %s" % str(e)[:100])
        return None
    use = R.get("use")
    if use == "stays" and R.get("location") and R.get("check_in"):
        ci, co = R["check_in"], R.get("check_out") or R["check_in"]
        if co <= ci:
            co = time.strftime("%Y-%m-%d", time.gmtime(time.mktime(time.strptime(ci, "%Y-%m-%d")) + 86400 + 7200))
        site = "booking" if R.get("site") == "booking" else "airbnb"
        d, why = get("/%s/search" % site, location=R["location"], check_in=ci, check_out=co, adults=R.get("adults") or 1)
        if why:
            _down(why)
            return None
        P = [(it.get("place") or it) for it in ((d.get("data") or {}).get("items") or [])]
        P = _near(P, R["location"])[:6]          # 14/11: 'Viry-Chatillon, France' came back with Thionville, Carcassonne...
        if not P:
            return None
        rows = []
        for p in P:                                  # the real price for the dates: one look per place (1 credit each)
            pr = stay_price(p.get("url") or p.get("id"), ci, co, R.get("adults") or 1, site)
            m = re.search(r"total[^:]*:\s*about (\d+) EUR", pr) or re.search(r"about (\d+) EUR", pr)
            rows.append((int(m.group(1)) if m else 10 ** 6, "%s | %s | rating %s | %s" % (
                p.get("name"), p.get("url"), (p.get("rating") or {}).get("value"), pr[:160])))
        rows.sort()
        return ("INSIDE %s, %s, %s -> %s, %s adult(s) - real places, real prices for these dates%s:\n" % (
            site.upper(), R["location"], ci, co, R.get("adults") or 1, ", cheapest first" if R.get("cheapest") else "") +
            "\n".join("- " + r for _, r in rows)) if rows else None
    if use == "look" and R.get("path"):
        s = look(R["path"], R.get("params") if isinstance(R.get("params"), dict) else {}, 4000)
        return None if s.startswith("NOT READ") else "INSIDE %s:\n%s" % (R["path"], s)
    return None


def block():
    d = _j()
    return ("EYES INSIDE SITES (no account, any country, read only): stays (\"location\" 'city postcode' or 'city, country', "
            "\"check_in\", \"check_out\" YYYY-MM-DD, \"adults\", \"site\" airbnb|booking) lists places; stay_price (\"listing\" "
            "url or id, dates, adults) gives the real price converted to euros; look (\"path\", \"params\" {}) reads any of "
            "~75 sites - e.g. /reddit/search {query}, /reddit/subreddit/search {subreddit, query, sort:new}, /tiktok/search "
            "{query}, /instagram/search/reels {query}, /twitter/ai-search {query}, /facebook/group/posts {url}, "
            "/youtube/search {query}, /google/search {query}, /yelp/search, /tripadvisor/search, /trustpilot/..., "
            "/jobs/linkedin/search; PRICES TO BUY (cheapest, to resell): /google_shopping/product-search {query, country}, "
            "/google_shopping/sellers, /amazon/product-search {query}, /ebay/search {query}, /aliexpress/search {query}, "
            "/walmart/..., /gumtree/... - docs https://www.socialcrawl.dev/llms-<site>.txt (fetch). Credits today %d of %d%s." % (
                used_today(), DAY_CAP, (", %s left in the pack" % d["left"]) if d.get("left") is not None else ""))


if __name__ == "__main__":
    print(block())
    print(money(220, "USD"))
