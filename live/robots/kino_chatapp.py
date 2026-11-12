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
import json
import os
import re
import secrets
import threading
import time

# 2026-11-08 (owner: "if he is a known friend, the conversation just continues from where they stopped - Telegram, social
# media, trading app or email"): Kino gives a person he knows a personal Kino Chat link; whoever signs up / signs in through
# it IS that person - their Kino Chat account is linked to that channel, and Kino Chat reads what was said there.
HERE = os.path.dirname(os.path.abspath(__file__))
LINKS = os.path.join(HERE, "kino_chatlinks.json")           # {"tok": {tok: channel key}, "uid": {uid: [channel keys]}}
BASE = "https://chat.owltrader.duckdns.org"   # 2026-11-08: its own address, owltrader links belong to the OwlNest app
_LK = threading.Lock()


def _ld():
    try:
        d = json.load(open(LINKS, encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("tok", {}); d.setdefault("uid", {})
    return d


def _sv(d):
    json.dump(d, open(LINKS + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(LINKS + ".tmp", LINKS)


def invite_link(key):
    """this person's own Kino Chat link (telegram:<id>, whatsapp:<phone>, mailto:<email>, bluesky:@handle ...) - same link each time"""
    key = str(key or "").strip()
    if not key:
        return BASE + "/kinochat"
    with _LK:
        d = _ld()
        tok = next((t for t, k in d["tok"].items() if k == key), None)
        if tok is None:
            tok = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")
            d["tok"][tok] = key
            _sv(d)
    return BASE + "/kinochat?k=" + tok


def claim(tok, uid):
    """someone came in through a personal link: their Kino Chat account is that person -> the channel key, or None"""
    tok = re.sub(r"[^A-Za-z0-9]", "", str(tok or ""))[:40]
    if not tok or not uid:
        return None
    with _LK:
        d = _ld()
        key = d["tok"].get(tok)
        if not key:
            return None
        L = d["uid"].setdefault(str(uid), [])
        if key not in L:
            L.append(key)
            _sv(d)
    try:                                   # one person, one memory: the friend he met on Bluesky/Telegram is this account too
        import kino_online as KO
        who = next((w for w, p in KO._load()["people"].items() if key in (p.get("also") or []) or w == key.split(":", 1)[-1]), None)
        if who:
            import kino_friends as KF
            KF.link(who, "kinochat:%s" % uid)
    except Exception:
        pass
    return key


def keys_of(uid):
    return list(_ld()["uid"].get(str(uid), []))


def elsewhere(uid, n=14):
    """for Kino's prompt in Kino Chat: who this person is on his other channels and the last words said there"""
    out = []
    try:
        import kino_friends as KF
        fo = KF.friend_of("kinochat:%s" % uid)
        if fo:
            out.append(fo)
    except Exception:
        pass
    for key in keys_of(uid):
        try:
            if key.startswith(("telegram:", "whatsapp:")):
                import kino_clients as KC
                tg = key.split(":", 1)[1] if key.startswith("telegram:") else "wa:" + key.split(":", 1)[1]
                M = (KC._load(tg).get("msgs") or [])[-n:]
                if M:
                    out.append("YOUR CONVERSATION WITH THEM ON %s (UTC, newest last):\n" % key.split(":")[0].upper() + "\n".join(
                        "[%s] %s: %s" % (time.strftime("%d/%m %H:%M", time.gmtime(m["t"])), "them" if m["who"] == "them" else "you",
                                         str(m["text"])[:300]) for m in M))
            if key.startswith("mailto:"):         # the emails between them (kept in his people book)
                import kino_online as KO
                p = KO._load()["people"].get(key.split(":", 1)[1]) or {}
                S = (p.get("said") or [])[-n:]
                if S:
                    out.append("YOUR EMAILS WITH THEM (newest last):\n" + "\n".join(
                        ("they: " if s.get("dir") == "in" else "you: ") + str(s.get("text"))[:300] for s in S))
            if not out or key not in " ".join(out):
                try:
                    import kino_friends as KF
                    fo = KF.friend_of(key)
                    if fo and fo not in out:
                        out.append(fo)
                except Exception:
                    pass
        except Exception:
            pass
    return "\n\n".join(out)

_KC_HEAD = """<script>window.KC=1;
/* 2026-11-08 owner: "find a professional way to introduce all the things Kino can do - friend, but also an excellent coworker" */
function kcTourGo(){var en=typeof EN!=='undefined'&&EN,T=function(f,e){return en?e:f};var S=[
['👋',T('Kino, ton compagnon et assistant IA','Kino, your AI companion and assistant'),T('Parle-lui de tout, à toute heure. Il se souvient de ce que tu lui dis : tu ne repars jamais de zéro.','Talk to him about anything, any time. He remembers what you tell him, so you never start from zero.')],
['💼',T('Un collègue toujours disponible','A coworker on call'),T('Un e-mail, une lettre, un CV, un post à écrire ; un plan à préparer ; une recherche sur le web ; un document ou une photo à lire (bouton +).','An email, a letter, a CV or a post to write; a plan to prepare; a web search; a document or a photo to read (the + button).')],
['🏪',T('Pour ton activité','For your business'),T('Avec l’équipe Kinoverse, Kino crée des sites web et gère réseaux sociaux et publicités. Demande-lui simplement.','With the Kinoverse team, Kino builds websites and runs social media and ads. Just ask him.')],
['📞',T('Écris, parle ou appelle','Write, talk or call'),T('Écris, envoie un message vocal avec 🎤, ou appelle-le avec 📞 (5 minutes offertes chaque mois).','Write, send a voice message with 🎤, or call him with 📞 (5 free minutes every month).')],
['📈',T('Et si tu trades','And if you trade'),T('Il construit et teste des robots de trading avec toi, sur le même compte que l’app OwlNest.','He builds and tests trading robots with you, on the same account as the OwlNest app.')]];
var k=0,paint=function(){shOpen('<div class="tour"><div class="ti">'+S[k][0]+'</div><h4>'+S[k][1]+'</h4><p>'+S[k][2]+'</p><div class="tdots">'+S.map(function(_,i){return '<i class="'+(i===k?'on':'')+'"></i>'}).join('')+'</div><button class="btn pri" id="tnext">'+(k<S.length-1?T('Suivant','Next'):T('C’est parti','Let’s go'))+'</button></div>');
var b=document.getElementById('tnext');if(b)b.onclick=function(){k++;if(k<S.length)paint();else shClose()}};paint();}try{localStorage.setItem('kcLink',location.pathname.replace(/\\/+$/,''))}catch(e){}
document.addEventListener('DOMContentLoaded',function(){document.body.classList.add('kcm');var t=document.getElementById('tx');
if(t)t.placeholder=(document.documentElement.lang||'fr').indexOf('en')===0?'Write to Kino…':'Écris à Kino…';
/* 2026-11-08 owner: "not all users will be traders" - no robot / money items in Kino Chat's menu; a sign-out instead */
if(typeof moreSh==='function'){var _m=moreSh;window.moreSh=function(b){_m(b);var d=document.getElementById('rxbar');if(!d)return;
d.querySelectorAll('[data-a="n"],[data-a="r"]').forEach(function(x){x.remove()});var w=document.createElement('button');w.className='it';
w.innerHTML='✨&nbsp; '+((typeof EN!=='undefined'&&EN)?'What Kino can do':'Ce que Kino sait faire');w.onclick=function(){d.remove();kcTourGo()};d.insertBefore(w,d.firstChild);
var o=document.createElement('button');o.className='it';
var en=typeof EN!=='undefined'&&EN;o.innerHTML='🚪&nbsp; '+(en?'Sign out':'Me déconnecter');o.onclick=function(){try{localStorage.removeItem('kcLink')}catch(e){}location.href='/kinochat?out=1'};d.appendChild(o);}}});</script>
<link rel="manifest" href="/kinochat.webmanifest"><meta name="theme-color" content="#0B0F14">
<style>body.kcm #chartb,body.kcm .ring,body.kcm #bp,body.kcm #bk,body.kcm #hint,body.kcm #tlb,body.kcm #strip,body.kcm #todayln,body.kcm .start,
body.kcm button[onclick="rpOpen()"]{display:none!important}body.kcm .app{grid-template-columns:1fr!important}body.kcm .chat{background-image:radial-gradient(120% 50% at 50% 0%,rgba(109,92,246,.09),transparent 65%)!important}</style>"""


def inject(page_html):
    """the trading app's chat page, in Kino Chat mode"""
    page_html = page_html.replace("post('chat_start',{lang:", "post('chat_start',{app:'kinochat',lang:")   # Kino meets a person, not a trader
    page_html = page_html.replace("function tourMaybe(){if(C&&C.tour_done)",   # Kino Chat's own tour, once per phone, members too
                                  "function tourMaybe(){if(window.KC){try{if(localStorage.getItem('kcTour'))return;localStorage.setItem('kcTour','1')}"
                                  "catch(e){return}return kcTourGo();}if(C&&C.tour_done)")
    i = page_html.find("</head>")
    return page_html[:i] + _KC_HEAD + page_html[i:] if i > 0 else _KC_HEAD + page_html


MANIFEST = {
    "name": "Kino Chat", "short_name": "Kino Chat", "start_url": "/kinochat", "scope": "/", "display": "standalone",
    "background_color": "#0B0F14", "theme_color": "#0B0F14", "description": "Talk with Kino, anytime.",
    "icons": [{"src": "/kinochat_round.png", "sizes": "1000x1000", "type": "image/png", "purpose": "any"},
              {"src": "/kinochat.png", "sizes": "1000x1000", "type": "image/png", "purpose": "maskable"}]}


# 2026-11-12 (owner: a translate banner at start; a shared group link showed the OwlNest logo): no translation offer, and the
# link preview (WhatsApp, Telegram, SMS) shows Kino Chat's own card
def start_page(msg="", en=False):
    T = (lambda f, e: e) if en else (lambda f, e: f)
    return """<!doctype html><html lang="%s" translate="no" class="notranslate"><head><meta charset="utf-8"><meta name="google" content="notranslate"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kino Chat</title><link rel="manifest" href="/kinochat.webmanifest"><meta name="theme-color" content="#0B0F14">
<link rel="icon" type="image/png" href="/kinochat_round.png"><link rel="apple-touch-icon" href="/kinochat.png">
<meta property="og:site_name" content="Kino Chat"><meta property="og:title" content="Kino Chat">
<meta property="og:description" content="L'assistant IA qui s'occupe de tout - rejoins la conversation."><meta property="og:type" content="website">
<meta property="og:image" content="https://chat.owltrader.duckdns.org/kinochat_og.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="https://chat.owltrader.duckdns.org/kinochat_og.png">
<script>var KQ=(location.search.match(/[?&]k=([A-Za-z0-9]+)/)||[])[1]||'',GQ=(location.search.match(/[?&]g=([A-Za-z0-9]+)/)||[])[1]||'';
try{var L=localStorage.getItem('kcLink');if(L&&/^\\/[A-Za-z0-9_-]+\\/kinochat$/.test(L)&&location.search.indexOf('out=1')<0)location.replace(L+(KQ||GQ?'?'+(KQ?'k='+KQ:'')+(KQ&&GQ?'&':'')+(GQ?'g='+GQ:''):''))}catch(e){}
document.addEventListener('DOMContentLoaded',function(){document.querySelectorAll('form').forEach(function(f){[['k',KQ],['g',GQ]].forEach(function(x){if(!x[1])return;var i=document.createElement('input');i.type='hidden';i.name=x[0];i.value=x[1];f.appendChild(i)})});
if(GQ){var s=document.querySelector('p.s');if(s)s.textContent=(document.documentElement.lang==='en'?'You are invited to a group with Kino. Create your free account, or sign in:':'Tu es invité dans un groupe avec Kino. Crée ton compte gratuit, ou connecte-toi :')}});</script>
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
<p class="f" id="apk" style="display:none"><a href="https://kinoverse26-byte.github.io/app/KinoChat.apk" style="color:var(--acc);font-weight:600">&#128241; KINOAPK</a></p>
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
