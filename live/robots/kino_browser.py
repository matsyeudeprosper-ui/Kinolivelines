"""kino_browser.py (2026-11-01, owner: "everything a human can do in front of a computer he should do... under my control").

A real browser (Chromium, headless) that Kino drives during a work session: open a page, click, type, scroll, read, follow
links, take a screenshot - like a person. It runs inside the app (not as his user), so the gate below cannot be bypassed:

  THE GATE  every request the page makes goes through a filter. Reading (GET/HEAD/OPTIONS) to public addresses passes.
            Anything that SENDS (POST/PUT/PATCH/DELETE: forms, sign-ups, posts, uploads, payments) is blocked - unless the
            owner granted a PERMIT for that site (a request card of kind "site"; a permit lasts PERMIT_H hours).
            Private and local addresses are always refused.

His own Windows user has no direct internet at all (firewall rule "Kino - no direct internet"), so the app's tools - kino_web
(search/read) and this browser - are his only way out. The browser files and its profile live in C:\\ProgramData\\kino_browser
(administrators only), never in his world. Log robots/kino_browser.log (git-ignored).
"""
import json, os, re, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = r"C:\ProgramData\kino_browser"
WORLD = r"C:\KinoWorld"
LOG = os.path.join(HERE, "kino_browser.log")
PERMITS = os.path.join(HERE, "kino_permits.json")
PERMIT_H = 24
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.join(BASE, "browsers"))


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def permits():
    try:
        P = json.load(open(PERMITS, encoding="utf-8"))
    except Exception:
        P = {}
    return {d: t for d, t in P.items() if float(t) > time.time()}


def grant(domain, hours=PERMIT_H):
    d = _dom(domain)
    if not d:
        return None
    P = permits()
    P[d] = time.time() + hours * 3600
    tmp = PERMITS + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(P))
    os.replace(tmp, PERMITS)
    _log("PERMIT %s for %d h" % (d, hours))
    return d


def _dom(x):
    x = str(x or "").strip().lower()
    h = urllib.parse.urlparse(x if "//" in x else "https://" + x).hostname or ""
    return h[4:] if h.startswith("www.") else h


def _permitted(host):
    h = (host or "").lower()
    return any(h == d or h.endswith("." + d) for d in permits())


class Browser:
    """one browser for one work session (same thread from open to close)"""

    def __init__(self):
        from playwright.sync_api import sync_playwright
        import kino_web as KW
        self._KW = KW
        self._pw = sync_playwright().start()
        prof = os.path.join(BASE, "profile")
        os.makedirs(prof, exist_ok=True)
        self.ctx = self._pw.chromium.launch_persistent_context(prof, headless=True, viewport={"width": 1280, "height": 900},
                                                               user_agent=KW.UA, accept_downloads=False)
        self.ctx.set_default_timeout(20000)
        self._pub = {}
        self.blocked = []
        self.ctx.route("**/*", self._gate)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def _public_host(self, url):
        h = urllib.parse.urlparse(url).hostname or ""
        if h not in self._pub:
            self._pub[h] = self._KW._public(url)
        return self._pub[h]

    def _gate(self, route, request):
        url, m = request.url, request.method.upper()
        if url.startswith(("data:", "blob:", "about:")):
            return route.continue_()
        if not url.startswith(("http://", "https://")) or not self._public_host(url):
            return route.abort()
        if m in ("GET", "HEAD", "OPTIONS"):
            return route.continue_()
        host = urllib.parse.urlparse(url).hostname or ""
        if _permitted(host):
            _log("SEND allowed (permit) %s %s" % (m, url[:200]))
            return route.continue_()
        self.blocked.append("%s %s" % (m, host))
        _log("SEND blocked %s %s" % (m, url[:200]))
        return route.abort()

    def _view(self, n=5000):
        p = self.page
        try:
            t = p.inner_text("body")
        except Exception:
            t = ""
        t = re.sub(r"\n\s*\n+", "\n", t).strip()
        out = "PAGE: %s\nURL: %s\n%s" % (p.title()[:150], p.url[:300], t[:n] + ("\n[... more below - scroll or read]" if len(t) > n else ""))
        if self.blocked:
            out += "\n[the gate blocked %d sending request(s) on this page: %s - sending needs the owner's permit for the site]" % (
                len(self.blocked), ", ".join(sorted(set(self.blocked))[:4]))
            self.blocked = []
        return out

    def act(self, j):
        """one browser action from his step -> what he sees"""
        a = str(j.get("do") or j.get("browse") or "").lower()
        p = self.page
        try:
            if a == "open":
                p.goto(str(j.get("url") or ""), wait_until="domcontentloaded")
                p.wait_for_timeout(1500)
                return self._view()
            if a == "click":
                tgt = str(j.get("target") or "")
                loc = p.get_by_text(tgt, exact=False).first if not tgt.startswith(("#", ".", "[", "//")) else p.locator(tgt).first
                loc.click()
                p.wait_for_timeout(1500)
                return self._view()
            if a == "type":
                p.locator(str(j.get("target") or "input")).first.fill(str(j.get("text") or ""))
                return "typed into %s (nothing is sent until a form is submitted - and sending needs a permit)" % j.get("target")
            if a == "scroll":
                p.mouse.wheel(0, 1800)
                p.wait_for_timeout(800)
                t = p.inner_text("body")
                return t[-5000:]
            if a == "read":
                return self._view(12000)
            if a == "links":
                L = p.eval_on_selector_all("a[href]", "els => els.slice(0, 80).map(e => (e.innerText || '').trim().slice(0, 70) + ' -> ' + e.href)")
                return "\n".join(x for x in L if x.strip(" ->"))[:6000]
            if a == "back":
                p.go_back()
                return self._view()
            if a == "shot":
                fn = os.path.join(WORLD, "lab", "screens", time.strftime("%Y%m%d_%H%M%S") + ".png")
                os.makedirs(os.path.dirname(fn), exist_ok=True)
                p.screenshot(path=fn)
                return "screenshot saved: %s" % fn
            return "unknown browser action (open, click, type, scroll, read, links, back, shot)"
        except Exception as e:
            return "browser: %s" % str(e).split("\n")[0][:300]

    def close(self):
        for f in (lambda: self.ctx.close(), lambda: self._pw.stop()):
            try:
                f()
            except Exception:
                pass
