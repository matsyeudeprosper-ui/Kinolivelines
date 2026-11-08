"""kino_chatapp.py (2026-11-07, owner: "our own app called Kino Chat where the only contact is Kino, the same style as the chat
in the trading app"; "make sure the history is the same in the chat app and in the trading app chat when it's the same person").

Kino Chat = the trading app's own chat page (owl_atelier_page.html) in a chat-only mode, on the SAME OwlNest account:
  /kinochat              the start page the Android app opens: remembered account -> straight to the chat; else sign in
                         (same identifiant + password as the trading app) or create a free account in one step.
  /<token>/kinochat      the chat itself: the very conversations of the trading app (same account = same history), with the
                         trading buttons (chart, robot plan, replay, tools) hidden; calls (📞) stay.
The APK (live/apk_kinochat, package org.duckdns.owltrader.kinochat) is a Trusted Web Activity on /kinochat.
"""
import html as _h

_KC_HEAD = """<script>window.KC=1;try{localStorage.setItem('kcLink',location.pathname.replace(/\\/+$/,''))}catch(e){}
document.addEventListener('DOMContentLoaded',function(){document.body.classList.add('kcm');var t=document.getElementById('tx');
if(t)t.placeholder=(document.documentElement.lang||'fr').indexOf('en')===0?'Write to Kino…':'Écris à Kino…';});</script>
<link rel="manifest" href="/kinochat.webmanifest"><meta name="theme-color" content="#0B0F14">
<style>body.kcm #chartb,body.kcm .ring,body.kcm #bp,body.kcm #bk,body.kcm #hint,body.kcm #tlb,body.kcm #strip,
body.kcm button[onclick="rpOpen()"]{display:none!important}body.kcm .app{grid-template-columns:1fr!important}body.kcm .chat{background-image:radial-gradient(120% 50% at 50% 0%,rgba(109,92,246,.09),transparent 65%)!important}</style>"""


def inject(page_html):
    """the trading app's chat page, in Kino Chat mode"""
    i = page_html.find("</head>")
    return page_html[:i] + _KC_HEAD + page_html[i:] if i > 0 else _KC_HEAD + page_html


MANIFEST = {
    "name": "Kino Chat", "short_name": "Kino Chat", "start_url": "/kinochat", "scope": "/", "display": "standalone",
    "background_color": "#0B0F14", "theme_color": "#0B0F14", "description": "Talk with Kino, anytime.",
    "icons": [{"src": "/kinochat.png", "sizes": "1000x1000", "type": "image/png", "purpose": "any"},
              {"src": "/kinochat.png", "sizes": "1000x1000", "type": "image/png", "purpose": "maskable"}]}


def start_page(msg="", en=False):
    T = (lambda f, e: e) if en else (lambda f, e: f)
    return """<!doctype html><html lang="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kino Chat</title><link rel="manifest" href="/kinochat.webmanifest"><meta name="theme-color" content="#0B0F14">
<script>try{var L=localStorage.getItem('kcLink');if(L&&/^\\/[A-Za-z0-9_-]+\\/kinochat$/.test(L)&&location.search.indexOf('out=1')<0)location.replace(L)}catch(e){}</script>
<style>:root{--bg:#0B0F14;--card:#141a22;--ink:#e9eef4;--mut:#93a1b1;--acc:#8b85ff;--line:#222c38}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:420px;margin:0 auto;padding:36px 16px 50px}.av{width:96px;height:96px;border-radius:50%%;margin:0 auto 14px;background:url(/kinochat.png) center/cover}
h1{text-align:center;margin:0;font-size:28px}p.s{text-align:center;color:var(--mut);margin:6px 0 26px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;margin:14px 0}.card h2{font-size:17px;margin:0 0 4px}
.card small{color:var(--mut);display:block;margin-bottom:10px}input{width:100%%;padding:12px;margin:5px 0;border-radius:11px;border:1px solid var(--line);background:var(--bg);color:var(--ink);font:16px system-ui}
button{width:100%%;margin-top:8px;padding:13px;border:0;border-radius:12px;background:var(--acc);color:#fff;font:600 16px system-ui;cursor:pointer}
button.g{background:transparent;border:1px solid var(--acc);color:var(--acc)}.msg{background:#dc262622;border-radius:10px;padding:10px 12px;margin-bottom:8px}
.f{color:var(--mut);font-size:13px;text-align:center;margin-top:26px}</style></head><body><main>
<div class="av"></div><h1>Kino Chat</h1><p class="s">%s</p>%s
<div class="card"><h2>%s</h2><small>%s</small><form method="post" action="/kinochat/join">
<input name="name" placeholder="%s" required maxlength="40" autocomplete="given-name">
<input name="ident" placeholder="%s" required maxlength="24" autocomplete="username" autocapitalize="none">
<input name="password" type="password" placeholder="%s" required minlength="4" maxlength="64" autocomplete="new-password">
<button>%s</button></form></div>
<div class="card"><h2>%s</h2><small>%s</small><form method="post" action="/kinochat/login">
<input name="login" placeholder="%s" required maxlength="40" autocomplete="username" autocapitalize="none">
<input name="password" type="password" placeholder="%s" required maxlength="64" autocomplete="current-password">
<button class="g">%s</button></form></div>
<p class="f" id="apk" style="display:none"><a href="/kinochat.apk" style="color:var(--acc);font-weight:600">&#128241; KINOAPK</a></p>
<script>if(/Android/i.test(navigator.userAgent)&&!matchMedia('(display-mode: standalone)').matches&&document.referrer.indexOf('android-app://')<0)document.getElementById('apk').style.display='block'</script>
<p class="f">%s</p></main></body></html>""".replace("KINOAPK", "Installer l'app Kino Chat (Android)" if not en else "Install the Kino Chat app (Android)") % (
        "en" if en else "fr",
        T("Kino, une IA, toujours là pour parler : une idée, une question, ou juste discuter.",
          "Kino, an AI, always there to talk: an idea, a question, or just a chat."),
        ('<p class="msg">%s</p>' % _h.escape(msg)) if msg else "",
        T("Nouveau ici", "New here"), T("Gratuit. Votre prénom, un identifiant et un mot de passe.",
                                         "Free. Your first name, a username and a password."),
        T("Votre prénom", "Your first name"), T("Identifiant (lettres et chiffres)", "Username (letters and digits)"),
        T("Mot de passe (4 caractères au moins)", "Password (at least 4 characters)"), T("Commencer à parler avec Kino", "Start talking with Kino"),
        T("J'ai déjà un compte", "I already have an account"),
        T("Le même que l'app de trading OwlNest : vous retrouvez toutes vos conversations avec Kino.",
          "The same as the OwlNest trading app: you find all your conversations with Kino."),
        T("Identifiant", "Username"), T("Mot de passe", "Password"), T("Me connecter", "Sign in"),
        T("Kino est une intelligence artificielle de Kinoverse.", "Kino is an artificial intelligence by Kinoverse."))
