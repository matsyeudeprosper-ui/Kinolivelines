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


def download(url, path, cap=20_000_000):
    """a public file saved as it is (bytes) - reading only; path already checked by the caller"""
    url = str(url or "").strip()
    if not _public(url):
        raise ValueError("not a public web address")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with _OPENER.open(req, timeout=60) as r:
        data = r.read(cap + 1)
    if len(data) > cap:
        raise ValueError("file larger than %d MB" % (cap // 1_000_000))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)
    _log("DOWNLOAD %s -> %s (%d bytes)" % (url[:150], path, len(data)))
    return len(data)


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
    if not out:
        # 2026-11-13 (watch: 33 searches came back empty - the TV for Pekos, the helper bench): DuckDuckGo now answers this
        # server with a bot check page, and Bing serves scripts junk (hotels for "plombier Paris"). Claude's own web search
        # (claude.exe, WebSearch tool, haiku) returns real results - it is the fallback.
        try:
            out = _claude_search(q, n)
            _log("SEARCH(claude) %s -> %d" % (q[:120], len(out)))
            return out
        except Exception as e:
            _log("SEARCH(claude) failed %s" % str(e)[:120])
    _log("SEARCH %s -> %d" % (q[:120], len(out)))
    return out


def _claude_search(q, n=8):
    import json as _j, os as _o, subprocess as _sp
    exe = _o.path.join(_o.environ.get("USERPROFILE", r"C:\Users\Administrator"), ".local", "bin", "claude.exe")
    prompt = ("Search the web for: %s\nReply ONLY with a JSON array of up to %d objects {\"title\", \"url\", \"snippet\"} taken "
              "from real search results (no invented links), most useful first." % (q, n))
    r = _sp.run([exe, "-p", prompt, "--allowedTools", "WebSearch", "--model", "haiku", "--output-format", "text",
                 "--no-session-persistence"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                creationflags=0x08000000)
    txt = r.stdout or ""
    i = txt.find("[")
    if i < 0:
        return []
    try:                                        # 14/11: a greedy [.*] swallowed text after the list -> "Extra data" -> 0 results
        arr, _end = _j.JSONDecoder().raw_decode(txt[i:])
    except Exception:
        return []
    out = []
    for x in (arr if isinstance(arr, list) else []):
        if not isinstance(x, dict):
            continue
        u = str(x.get("url") or "")
        if u.startswith("http"):
            out.append({"title": str(x.get("title") or "")[:160], "url": u, "snippet": str(x.get("snippet") or "")[:300]})
    return out[:n]


def _bing(q, n=8):
    import base64
    h, _ = _get("https://www.bing.com/search?q=" + urllib.parse.quote(q))
    out = []
    for blk in re.findall(r'(?is)<li class="b_algo"(.*?)</li>', h):
        m = re.search(r'(?is)<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', blk)
        if not m:
            continue
        url = html.unescape(m.group(1))
        if "bing.com/ck/a" in url:                     # Bing's click redirect: u=a1<base64url of the real address>
            u = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("u", [""])[0]
            if u.startswith("a1"):
                try:
                    b = u[2:]
                    url = base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode("utf-8", "replace")
                except Exception:
                    pass
        if not url.startswith("http") or "bing.com" in url:
            continue
        sn = re.search(r'(?is)<p[^>]*>(.*?)</p>', blk)
        out.append({"title": _text(m.group(2))[:160], "url": url, "snippet": _text(sn.group(1) if sn else "")[:300]})
        if len(out) >= n:
            break
    return out


def fetch(url, max_chars=7000, start=0):
    """-> the page as plain text, a part of it (start = where to continue a long page)"""
    h, ct = _get(str(url or "").strip())
    t = _text(h) if "html" in ct or "<html" in h[:500].lower() else h
    start = max(0, min(int(start or 0), len(t)))
    _log("FETCH %s (%d chars, from %d)" % (str(url)[:150], len(t), start))
    part = t[start:start + max_chars]
    more = len(t) - (start + len(part))
    return ("[characters %d-%d of %d]\n" % (start, start + len(part), len(t))) + part + (
        ("\n[... %d more characters - fetch again with start=%d to continue]" % (more, start + len(part))) if more > 0 else "")
