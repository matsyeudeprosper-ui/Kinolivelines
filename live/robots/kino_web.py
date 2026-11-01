"""kino_web.py (2026-11-01, owner: "everything a human can do in front of a computer he should do... research how to earn")

Kino's web: search and read pages, like a person with a browser. Read-only (GET), from the app, with limits:
  - only http/https, and only PUBLIC addresses - the machine itself, its network and private ranges are refused (resolved
    before the request), so he cannot reach the app or anything inside
  - pages come back as plain text, cut to a size a person reads in a sitting
Search uses DuckDuckGo's HTML page (no key). Log robots/kino_web.log (git-ignored).
"""
import html, ipaddress, json, os, re, socket, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "kino_web.log")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _public(url):
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        for fam, _, _, _, sa in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80)):
            ip = ipaddress.ip_address(sa[0])
            if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
            if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):        # tailnet / carrier-grade NAT
                return False
    except Exception:
        return False
    return True


class _NoPrivateRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _public(newurl):
            raise urllib.error.URLError("redirect to a non-public address refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_NoPrivateRedirect)


def _get(url, timeout=25, cap=1_500_000):
    if not _public(url):
        raise ValueError("not a public web address")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,fr;q=0.8"})
    with _OPENER.open(req, timeout=timeout) as r:
        ct = r.headers.get("Content-Type") or ""
        raw = r.read(cap)
    cs = (re.search(r"charset=([\w-]+)", ct) or [None, "utf-8"])[1]
    return raw.decode(cs, "replace"), ct


def _text(h):
    h = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</tr>|</div>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def search(q, n=8):
    """-> list of {title, url, snippet}"""
    q = str(q or "").strip()[:300]
    if not q:
        return []
    h, _ = _get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q))
    out = []
    for m in re.finditer(r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?(?:class="result__snippet"[^>]*>(.*?)</a>)?', h):
        url = html.unescape(m.group(1))
        uq = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("uddg")
        if uq:
            url = uq[0]
        if "duckduckgo.com/y.js" in url:
            continue                                   # ads
        out.append({"title": _text(m.group(2))[:160], "url": url, "snippet": _text(m.group(3) or "")[:300]})
        if len(out) >= n:
            break
    _log("SEARCH %s -> %d" % (q[:120], len(out)))
    return out


def fetch(url, max_chars=7000):
    """-> the page as plain text (cut)"""
    h, ct = _get(str(url or "").strip())
    t = _text(h) if "html" in ct or "<html" in h[:500].lower() else h
    _log("FETCH %s (%d chars)" % (str(url)[:150], len(t)))
    return t[:max_chars] + ("\n[... page cut ...]" if len(t) > max_chars else "")
