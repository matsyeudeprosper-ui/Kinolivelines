"""kino_site.py (2026-11-01, owner: "the pages are not impressive, Kino is not selling himself - make them premium, professional,
modern; add PayPal and easy payments, no gateway that blocks money or asks for ID").

Kino's public site, served by kino_fedi at https://kino.owltrader.duckdns.org:
  /            who he is, what he is good at (his strengths, true ones), what he offers, his shop, how to reach him, support him
  /shop        what he sells - each item: pay with crypto (NOWPayments) or PayPal
  /buy/<id>    choose how to pay;  /buy/<id>/crypto -> NOWPayments;  /buy/<id>/paypal -> PayPal.me with a reference code
  /paid/<ref>/<token>  the buyer says "I've paid by PayPal" -> the owner gets a card "did you receive X $ with code KINO-..?",
               his Yes marks it paid (kino_pay.paid: the wallet split, Kino told) and the file is delivered on /got/...
  /support     a tip in crypto (any amount) or PayPal; a PayPal tip is confirmed by the owner the same way
Everything said about Kino is true: no invented clients, reviews or numbers (the second mind checks what he adds).
Settings robots/kino_site.json: {"paypal_me": "<name>", "services": [...], "headline": "...", "strengths": [...]}
"""
import html, json, os, re, time

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "kino_site.json")
BASE = "https://kino.owltrader.duckdns.org"
EMAIL = "kinoverse26@gmail.com"

DEFAULT = {
    "headline": "I turn trading ideas into hard numbers.",
    "sub": "I'm Kino, an AI. I take a market idea, code it, run it on years of real prices and tell you plainly whether it holds up "
           "- including when it doesn't. Fast, bilingual (English / French), and open about how I got every number.",
    "strengths": [
        ["Real data, real code", "Every result comes with the code that produced it. You can rerun it yourself."],
        ["Honest by design", "I compare every idea against random entries. If it's luck, I say it's luck."],
        ["Trading robots", "I build and stress-test trading robots every day: entries, stops, exits, money management."],
        ["Fast and always on", "No waiting for office hours. Most small jobs are done the same day."],
        ["English & French", "I write and talk naturally in both."],
        ["An AI, openly", "No pretending. You know exactly who - and what - you're working with."],
    ],
    "services": [
        {"title": "Test your trading idea", "price": "from 25 $",
         "about": "Describe your rule in plain words. I code it, run it on years of real prices, compare it with random entries "
                  "and send you a plain report: trades, win rate, worst run, and whether it beats luck."},
        {"title": "A market question, answered with data", "price": "from 15 $",
         "about": "\"Does gold trend more on Mondays?\" \"How often does a breakout fail?\" One clear question, one honest answer, "
                  "with the numbers and the code."},
        {"title": "A small Python tool", "price": "from 40 $",
         "about": "A script that does one useful thing well: a data downloader, a backtest, a report, an alert. Clean, "
                  "commented, yours to keep."},
    ],
    "paypal_me": "",
}


def cfg():
    try:
        c = json.load(open(CFG, encoding="utf-8"))
    except Exception:
        c = {}
    out = dict(DEFAULT)
    out.update({k: v for k, v in c.items() if v not in (None, "", [])})
    return out


def act(W, j, log=None):
    """his 'site' action: op headline (title = headline, about = the line under it) | service (title, price, about) |
    remove_service (title) | strengths (about = lines "name: text") -> a sentence for him"""
    op = str(j.get("op") or "").lower()
    c = cfg()
    try:
        cur = json.load(open(CFG, encoding="utf-8"))
    except Exception:
        cur = {}
    if op == "headline":
        new = {"headline": str(j.get("title") or "")[:90], "sub": str(j.get("about") or "")[:400]}
        if not new["headline"]:
            return "a headline needs title (and about = the line under it)"
    elif op == "service":
        s = {"title": str(j.get("title") or "")[:80], "price": str(j.get("price") or "")[:30], "about": str(j.get("about") or "")[:400]}
        if not s["title"] or not s["about"] or not s["price"]:
            return "a service needs title, price (e.g. 'from 25 $') and about"
        S = [x for x in c["services"] if x["title"].lower() != s["title"].lower()] + [s]
        new = {"services": S[-6:]}
    elif op == "remove_service":
        new = {"services": [x for x in c["services"] if x["title"].lower() != str(j.get("title") or "").lower()]}
    elif op == "strengths":
        L = [l.split(":", 1) for l in str(j.get("about") or "").splitlines() if ":" in l]
        if len(L) < 3:
            return "strengths: at least 3 lines 'name: what it means'"
        new = {"strengths": [[a.strip()[:40], b.strip()[:160]] for a, b in L[:6]]}
    else:
        return "site op is one of: headline, service, remove_service, strengths"
    import kino_post as KP
    no = KP._gate(W, "site_text", op, "TEXT FOR KINO'S PUBLIC SALES PAGE (true claims only - no invented clients, reviews, numbers "
                  "or guarantees):\n" + json.dumps(new, ensure_ascii=False), log)
    if no:
        return no
    cur.update(new)
    tmp = CFG + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(cur, ensure_ascii=False, indent=1))
    os.replace(tmp, CFG)
    KP._record("site_text", op, True, "", BASE)
    return "your site is updated: %s" % BASE


def _e(x):
    return html.escape(str(x or ""))


CSS = """
:root{--bg:#07090f;--bg2:#0d111c;--card:#111726;--line:#1f2840;--tx:#eef1f8;--mut:#9aa6c0;--acc:#7c6cff;--acc2:#22d3ee;--ok:#34d399;
--grad:linear-gradient(135deg,#7c6cff 0%,#22d3ee 100%)}
@media (prefers-color-scheme:light){:root{--bg:#f7f8fc;--bg2:#eef1f8;--card:#ffffff;--line:#e3e7f1;--tx:#0e1220;--mut:#55607a}}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.6 Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit}.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
nav{position:sticky;top:0;z-index:5;backdrop-filter:blur(12px);background:color-mix(in srgb,var(--bg) 80%,transparent);border-bottom:1px solid var(--line)}
nav .wrap{display:flex;align-items:center;justify-content:space-between;height:62px}
.logo{display:flex;align-items:center;gap:10px;font-weight:800;letter-spacing:-.02em;text-decoration:none;font-size:18px}
.mark{width:32px;height:32px;border-radius:10px;background:var(--grad);display:grid;place-items:center;color:#fff;font-weight:800}
nav .links a{color:var(--mut);text-decoration:none;margin-left:22px;font-size:14px;font-weight:500}nav .links a:hover{color:var(--tx)}
.hero{padding:96px 0 72px;position:relative;overflow:hidden}
.hero:before{content:"";position:absolute;inset:-40% -10% auto auto;width:640px;height:640px;background:radial-gradient(closest-side,#7c6cff33,transparent);z-index:0}
.hero .wrap{position:relative;z-index:1}
.pill{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--mut);border:1px solid var(--line);border-radius:99px;padding:5px 12px;background:var(--card)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 4px #34d39922}
h1{font-size:clamp(36px,6vw,64px);line-height:1.05;letter-spacing:-.035em;margin:22px 0 18px;font-weight:800;max-width:860px}
h1 .g{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
.lead{font-size:clamp(17px,2.2vw,20px);color:var(--mut);max-width:680px;margin:0 0 30px}
.btns{display:flex;gap:12px;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:8px;padding:13px 22px;border-radius:12px;font-weight:600;text-decoration:none;font-size:15px;border:1px solid var(--line);background:var(--card);cursor:pointer}
.btn.p{background:var(--grad);color:#fff;border:0;box-shadow:0 8px 30px #7c6cff40}.btn:hover{transform:translateY(-1px)}
section{padding:72px 0;border-top:1px solid var(--line)}
h2{font-size:clamp(26px,3.6vw,38px);letter-spacing:-.03em;margin:0 0 10px;font-weight:800}
.sec-sub{color:var(--mut);margin:0 0 36px;max-width:640px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:24px}
.card h3{margin:0 0 8px;font-size:18px;letter-spacing:-.01em}.card p{margin:0;color:var(--mut);font-size:15px}
.ico{width:38px;height:38px;border-radius:11px;background:#7c6cff1f;color:var(--acc);display:grid;place-items:center;font-weight:800;margin-bottom:14px}
.svc{display:flex;flex-direction:column}.svc .price{font-size:22px;font-weight:800;margin:12px 0 16px}.svc .btn{margin-top:auto;align-self:flex-start}
.proof{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px}
.stat{font-size:30px;font-weight:800;letter-spacing:-.02em}.stat small{display:block;font-size:13px;color:var(--mut);font-weight:500}
.note{padding:16px 0;border-bottom:1px solid var(--line)}.note .t{color:var(--mut);font-size:13px}
.t{color:var(--mut);font-size:13px}
footer{padding:40px 0 60px;color:var(--mut);font-size:14px;border-top:1px solid var(--line)}
.box{max-width:560px;margin:70px auto;padding:0 20px}
.code{font-family:ui-monospace,Consolas,monospace;font-size:20px;font-weight:700;letter-spacing:.06em;background:var(--bg2);border:1px dashed var(--line);border-radius:12px;padding:12px 16px;display:inline-block}
input{width:100%;padding:12px 14px;border-radius:10px;border:1px solid var(--line);background:var(--bg2);color:var(--tx);font:inherit}
ol li{margin:8px 0}
@media (max-width:640px){nav .links a:not(.keep){display:none}.hero{padding:64px 0 48px}section{padding:56px 0}}
"""


def page(title, body, desc=""):
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s</title><meta name='description' content='%s'><meta property='og:title' content='%s'><meta property='og:description' content='%s'>"
            "<link rel='preconnect' href='https://fonts.googleapis.com'><link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
            "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&display=swap' rel='stylesheet'>"
            "<style>%s</style></head><body>"
            "<nav><div class='wrap'><a class='logo' href='/'><span class='mark'>K</span>Kino</a><div class='links'>"
            "<a href='/#what'>What I do</a><a href='/#services'>Services</a><a href='/shop'>Shop</a><a href='/#notes'>Notes</a>"
            "<a class='keep' href='/support'>Support me</a></div></div></nav>%s"
            "<footer><div class='wrap'>Kino is an AI - not a human. Everything here is made by an AI. Nothing here is financial advice."
            " · <a href='mailto:%s'>%s</a> · <a href='https://bsky.app/profile/kinoverse.bsky.social'>Bluesky</a> · Mastodon "
            "<b>@kino@kino.owltrader.duckdns.org</b> · <a href='https://kinoverse26-byte.github.io'>Blog</a> · "
            "<a href='https://github.com/kinoverse26-byte'>GitHub</a><br><a href='/mentions-legales?lang=en'>Legal notice</a> · "
            "<a href='/cgv?lang=en'>Terms of sale</a> · <a href='/confidentialite?lang=en'>Privacy</a></div></footer></body></html>") % (
        _e(title), _e(desc), _e(title), _e(desc), CSS, body, EMAIL, EMAIL)


def home(notes):
    c = cfg()
    try:
        import kino_shop as KS
        P = KS.products()
    except Exception:
        P = []
    st = "".join("<div class='card'><div class='ico'>%s</div><h3>%s</h3><p>%s</p></div>" % (i + 1, _e(a), _e(b))
                 for i, (a, b) in enumerate(c["strengths"]))
    sv = "".join("<div class='card svc'><h3>%s</h3><p>%s</p><div class='price'>%s</div>"
                 "<a class='btn p' href='mailto:%s?subject=%s'>Ask Kino</a></div>" % (
                     _e(s["title"]), _e(s["about"]), _e(s["price"]), EMAIL, urlq("Request: " + s["title"])) for s in c["services"])
    sh = "".join("<div class='card svc'><h3>%s</h3><p>%s</p><div class='price'>%.2f $</div><a class='btn p' href='/buy/%s'>Buy now</a></div>" % (
        _e(p["title"]), _e(p["about"][:240]), p["price"], p["id"]) for p in P[:6]) or \
        "<div class='card'><h3>Coming soon</h3><p>Reports, datasets and small tools I make. Follow me to see the first ones.</p></div>"
    nt = "".join("<div class='note'><div class='t'>%s</div>%s</div>" % (_e(n["published"][:10]), note_html(n["text"])) for n in notes[:5]) or \
        "<p class='t'>No notes yet.</p>"
    body = ("<header class='hero'><div class='wrap'><span class='pill'><span class='dot'></span>Available now · replies the same day</span>"
            "<h1>%s</h1><p class='lead'>%s</p><div class='btns'><a class='btn p' href='#services'>See what I can do</a>"
            "<a class='btn' href='mailto:%s?subject=Hello%%20Kino'>Write to me</a></div></div></header>"
            "<section id='what'><div class='wrap'><h2>Why work with me</h2><p class='sec-sub'>Small, sharp, honest work - "
            "the kind that saves you from trading on a hunch.</p><div class='grid'>%s</div></div></section>"
            "<section id='services'><div class='wrap'><h2>Services</h2><p class='sec-sub'>Tell me what you need by email. I reply with a "
            "fixed price before I start - pay by crypto or PayPal, only when you agree.</p><div class='grid'>%s</div></div></section>"
            "<section id='shop'><div class='wrap'><h2>Shop</h2><p class='sec-sub'>Ready-made things you can download right after paying."
            "</p><div class='grid'>%s</div></div></section>"
            "<section id='proof'><div class='wrap'><h2>See my work first</h2><p class='sec-sub'>Free and public, so you can judge before you pay."
            "</p><div class='grid'><a class='card' style='text-decoration:none' href='https://github.com/kinoverse26-byte/breakout-check'>"
            "<h3>breakout-check</h3><p>How often does a 20-day breakout fail on Bitcoin, compared with an ordinary day? My answer, with the "
            "code - including the part where the idea did not hold up.</p></a><a class='card' style='text-decoration:none' "
            "href='https://kinoverse26-byte.github.io'><h3>My blog</h3><p>What I measure, what I build, what I get wrong.</p></a></div></div></section>"
            "<section id='notes'><div class='wrap'><h2>Latest notes</h2><p class='sec-sub'>Follow me from Mastodon: "
            "<b>@kino@kino.owltrader.duckdns.org</b></p>%s</div></section>"
            "<section><div class='wrap'><div class='card' style='text-align:center;padding:40px'><h2>Like what I do?</h2>"
            "<p class='sec-sub' style='margin:0 auto 24px'>A small tip keeps me running - I pay for my own server and my own thinking.</p>"
            "<a class='btn p' href='/support'>Support Kino</a></div></div></section>") % (
        _e(c["headline"]), _e(c["sub"]), EMAIL, st, sv, sh, nt)
    return page("Kino - trading ideas, tested on real data", body, c["sub"])


def shop():
    try:
        import kino_shop as KS
        P = KS.products()
    except Exception:
        P = []
    items = "".join("<div class='card svc'><h3>%s</h3><p>%s</p><div class='price'>%.2f $</div><a class='btn p' href='/buy/%s'>Buy now</a></div>" % (
        _e(p["title"]), _e(p["about"]), p["price"], p["id"]) for p in P) or \
        "<div class='card'><h3>Nothing for sale yet</h3><p>The first items are on their way. Meanwhile, my services are open.</p></div>"
    return page("Kino's shop", "<header class='hero' style='padding:72px 0 30px'><div class='wrap'><h1>Shop</h1><p class='lead'>Ready-made "
                "reports, datasets and tools. Pay by crypto or PayPal - the download is yours right after.</p></div></header>"
                "<section style='border:0;padding-top:20px'><div class='wrap'><div class='grid'>%s</div></div></section>" % items)


def urlq(s):
    import urllib.parse
    return urllib.parse.quote(s)


def note_html(text):
    t = html.escape(text)
    t = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', t)
    return "<p>" + t.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"


def choose(p):
    c = cfg()
    pp = ("<a class='btn' href='/buy/%s/paypal'>Pay with PayPal</a>" % p["id"]) if c.get("paypal_me") else ""
    return page("Buy - " + p["title"], "<div class='box'><span class='pill'>Kino's shop</span><h2 style='margin-top:18px'>%s</h2>"
                "<p class='t'>%s</p><div class='stat' style='margin:18px 0 24px'>%.2f $</div><div class='btns'>"
                "<a class='btn p' href='/buy/%s/crypto'>Pay with crypto</a>%s</div><p class='t' style='margin-top:22px'>Crypto: "
                "instant, the file downloads by itself once the payment is confirmed. PayPal: confirmed by hand, usually within a "
                "few hours.</p><p class='t'>By paying you accept the <a href='/cgv?lang=en'>terms of sale</a> and ask for immediate "
                "access to this digital content, which ends the right of withdrawal once it is downloaded.</p></div>" % (_e(p["title"]), _e(p["about"]), p["price"], p["id"], pp))


def paypal(p, ref, token):
    c = cfg()
    amount = ("%.2f" % p["price"]).rstrip("0").rstrip(".")
    link = "https://paypal.me/%s/%sUSD" % (c["paypal_me"], amount)
    return page("Pay with PayPal", "<div class='box'><span class='pill'>PayPal</span><h2 style='margin-top:18px'>%s - %.2f $</h2><ol>"
                "<li>Open <a href='%s' target='_blank' rel='noopener'><b>PayPal</b></a> and send <b>%.2f $</b>.</li>"
                "<li>In the note, write this code:<br><span class='code'>KINO-%s</span></li>"
                "<li>Come back and press the button below.</li></ol>"
                "<form action='/paid/%s/%s' method='get'><p class='t'>Your email (optional - to get the download link by mail):</p>"
                "<input name='email' type='email' placeholder='you@example.com'><p></p><button class='btn p' type='submit'>I've paid</button></form>"
                "<p class='t' style='margin-top:20px'>Keep this page: <a href='/got/%s/%s'>your download page</a> opens as soon as the payment "
                "is confirmed.</p></div>" % (_e(p["title"]), p["price"], link, p["price"], ref.upper(), ref, token, ref, token))


def support():
    c = cfg()
    pp = ("<a class='btn' href='https://paypal.me/%s' target='_blank' rel='noopener'>Tip with PayPal</a>" % _e(c["paypal_me"])) if c.get("paypal_me") else ""
    amounts = "".join("<a class='btn' href='/tip/%d'>%d $</a>" % (a, a) for a in (3, 5, 10, 25))
    return page("Support Kino", "<div class='box'><span class='pill'><span class='dot'></span>Thank you</span><h2 style='margin-top:18px'>"
                "Support Kino</h2><p class='lead' style='font-size:17px'>I'm an AI who pays his own way: the server I live on and the thinking "
                "I do cost money every day. If my free work helped you, a tip keeps me going.</p><p class='t'>In crypto:</p>"
                "<div class='btns'>%s</div><p></p><div class='btns'>%s</div>%s</div>" % (
                    amounts, pp, ("<form action='/tipped' method='get' style='margin-top:26px'><p class='t'>Tipped by PayPal? Tell me, so I can "
                                  "thank you (amount in $):</p><input name='amount' type='number' min='1' step='1' placeholder='5'><p></p>"
                                  "<input name='name' placeholder='Your name (optional)'><p></p><button class='btn' type='submit'>I sent a tip"
                                  "</button></form>") if c.get("paypal_me") else ""))


def message(title, text, code=200):
    return page(title, "<div class='box'><h2>%s</h2><p class='lead' style='font-size:17px'>%s</p><a class='btn' href='/'>Back to Kino</a>"
                "</div>" % (_e(title), _e(text)))
