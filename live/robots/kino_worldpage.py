"""kino_worldpage.py (2026-11-01, owner: Kino's world - phase 6) - the owner's window on Kino's life at his computer.

One server-rendered page (/<owner token>/kinoworld, admin only): what he is doing and has done at his computer, his diary,
his projects and files, his requests and their answers, his mail, and how his body (the machine) feels. Read-only.
"""
import html, json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = r"C:\KinoWorld"


def _e(x):
    return html.escape(str(x or ""))


def _ago(t):
    s = max(0, time.time() - float(t or 0))
    return "à l'instant" if s < 90 else ("il y a %d min" % (s / 60)) if s < 5400 else ("il y a %d h" % (s / 3600)) if s < 172800 else ("il y a %d j" % (s / 86400))


def _diary(days=3, n=60):
    try:
        fs = sorted(f for f in os.listdir(os.path.join(WORLD, "diary")) if f.endswith(".md"))[-days:]
    except Exception:
        return []
    L = []
    for f in reversed(fs):
        try:
            for l in reversed(open(os.path.join(WORLD, "diary", f), encoding="utf-8").read().splitlines()):
                if l.strip():
                    L.append((f[:10], l))
        except Exception:
            pass
    return L[:n]


def _files():
    out = []
    for sub in ("projects", "lab", "home", "outbox"):
        d = os.path.join(WORLD, sub)
        for r, _, fs in os.walk(d):
            for f in fs:
                p = os.path.join(r, f)
                try:
                    out.append((os.path.getmtime(p), p[len(WORLD) + 1:], os.path.getsize(p)))
                except Exception:
                    pass
    return sorted(out, reverse=True)[:25]


def page():
    W = {}
    try:
        W = json.load(open(os.path.join(HERE, "kino_work.json"), encoding="utf-8"))
    except Exception:
        pass
    R = []
    try:
        R = json.load(open(os.path.join(HERE, "kino_requests.json"), encoding="utf-8"))
    except Exception:
        pass
    M = {}
    try:
        M = json.load(open(os.path.join(HERE, "kino_mail.json"), encoding="utf-8"))
    except Exception:
        pass
    body = ""
    try:
        import kino_body as KB
        body = KB.line(False)
    except Exception:
        pass
    core = ""
    try:
        import kino_selfmodel as KSF
        core = (KSF._load().get("kino") or {}).get("core") or ""
    except Exception:
        pass
    S = list(reversed((W.get("sessions") or [])[-12:]))
    P = list(reversed(W.get("projects") or []))
    H = []
    H.append("""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Le monde de Kino</title><style>
:root{--bg:#0f1420;--card:#171e2d;--line:#263047;--tx:#e8ecf4;--mut:#93a0b8;--acc:#7c8cff;--ok:#3ecf8e;--bad:#ff6b6b}
@media (prefers-color-scheme: light){:root{--bg:#f6f7fb;--card:#fff;--line:#e3e7f0;--tx:#151a26;--mut:#5c667a;--acc:#4b5bdc;--ok:#0f9d63;--bad:#d64545}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:760px;margin:0 auto;padding:18px 16px 60px}h1{font-size:22px;margin:4px 0 2px}h2{font-size:15px;margin:26px 0 8px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em}
.sub{color:var(--mut);margin:0 0 6px}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin:8px 0}
.t{color:var(--mut);font-size:12.5px}.pill{display:inline-block;font-size:12px;padding:1px 8px;border-radius:99px;border:1px solid var(--line);color:var(--mut)}
.ok{color:var(--ok)}.bad{color:var(--bad)}details summary{cursor:pointer;color:var(--acc)}pre{white-space:pre-wrap;word-break:break-word;font-size:12.5px;margin:6px 0 0;color:var(--mut)}
ul{margin:4px 0;padding-left:18px}li{margin:2px 0}.row{display:flex;justify-content:space-between;gap:10px}
</style></head><body><main>""")
    H.append("<h1>🦉 Le monde de Kino</h1><p class='sub'>C:\\KinoWorld - sa machine, son ordinateur, sa vie entre vos conversations.</p>")
    if core:
        H.append("<div class='card'><b>Comme il se voit</b><br>%s</div>" % _e(core))
    if body:
        H.append("<div class='card'>%s</div>" % _e(body))
    wait = [r for r in R if r.get("status") == "waiting"]
    H.append("<h2>Ses demandes</h2>")
    if not R:
        H.append("<p class='sub'>Aucune demande pour l'instant.</p>")
    for r in list(reversed(R))[:10]:
        st = r.get("status")
        H.append("<div class='card'><div class='row'><b>%s %s</b><span class='pill %s'>%s</span></div><div class='t'>%s</div>%s%s</div>" % (
            "✉️" if r.get("kind") == "email" else "🔐", _e(r.get("what")), "ok" if st == "approved" else "bad" if st == "refused" else "",
            {"approved": "accepté", "refused": "refusé", "waiting": "en attente - réponds dans le chat"}.get(st, st), _ago(r.get("t")),
            ("<div>%s</div>" % _e(r.get("why"))) if r.get("why") else "",
            ("<details><summary>résultat</summary><pre>%s</pre></details>" % _e(r.get("result"))) if r.get("result") else ""))
    try:                                           # 2026-11-01: what he made public on his own, and the owner's stop switch
        import kino_post as KP
        off = KP.is_off()
        H.append("<h2>Ce qu'il publie seul</h2><div class='card'><div class='row'><span>Blog <a href='https://kinoverse26-byte.github.io'>"
                 "kinoverse26-byte.github.io</a> · GitHub <a href='https://github.com/kinoverse26-byte'>kinoverse26-byte</a></span>"
                 "<button id='psw' data-off='%d' style='border-radius:99px;padding:3px 12px;border:1px solid var(--line);background:var(--card);"
                 "color:var(--tx);cursor:pointer'>%s</button></div><div class='t'>%s</div></div>" % (
                     1 if off else 0, "▶ Reprendre" if off else "⏸ Arrêter ses publications",
                     "Arrêté : il ne publie plus rien." if off else "Il publie et s'inscrit seul (par jour au plus : 2 billets, 4 mises à jour GitHub, "
                     "4 nouveaux sites), chaque envoi relu d'abord par une seconde IA. Il ne te sollicite que s'il est vraiment bloqué."))
        for p in KP.recent(10):
            H.append("<div class='card'><div class='row'><b>%s %s</b><span class='pill %s'>%s</span></div><div class='t'>%s</div>%s</div>" % (
                {"blog": "📝", "site": "🌐", "bluesky": "🦋", "mastodon": "🐘"}.get(p.get("channel"), "📦"), _e(p.get("what")), "ok" if p.get("ok") else "bad",
                ("ouvert 24 h" if p.get("channel") == "site" else "publié") if p.get("ok") else "bloqué", _ago(p.get("t")),
                ("<a href='%s'>%s</a>" % (_e(p.get("url")), _e(p.get("url")))) if p.get("url") else ("<div>%s</div>" % _e(p.get("why")))))
        H.append("<script>document.getElementById('psw').onclick=function(){var b=this,off=b.dataset.off!=='1';"
                 "fetch(location.pathname.replace(/\/kinoworld.*$/,'/kino_post_switch'),{method:'POST',headers:{'Content-Type':'application/json'},"
                 "body:JSON.stringify({off:off})}).then(function(r){return r.json()}).then(function(j){if(j.ok)location.reload();else alert(j.err||'erreur')})}</script>")
    except Exception:
        pass
    try:                                           # 2026-11-01: what he earned (payment links on the owner's NOWPayments)
        import kino_pay as KPY
        e = KPY.summary()
        H.append("<h2>Ce qu'il gagne</h2><div class='card'><b>%.2f $</b> reçus · %d liens de paiement, %d payés</div>" % (
            e["earned_usd"], e["invoices"], e["paid"]))
        for i in e["recent"][:6]:
            H.append("<div class='card'><div class='row'><b>%.2f $ - %s</b><span class='pill %s'>%s</span></div><div class='t'>%s</div></div>" % (
                float(i.get("usd") or 0), _e(i.get("what")), "ok" if i.get("status") == "paid" else "", _e(i.get("status")), _ago(i.get("t"))))
    except Exception:
        pass
    H.append("<h2>À son ordinateur</h2>")
    if not S:
        H.append("<p class='sub'>Il ne s'est pas encore assis à son ordinateur.</p>")
    for s in S:
        steps = "".join("<li>%s <span class='t'>(%s %s)</span></li>" % (_e(x.get("thought")), _e(x.get("action")), _e(str(x.get("detail") or "")[:90]))
                        for x in s.get("steps") or [])
        H.append("<div class='card'><div class='row'><b>%s</b><span class='t'>%s · %d étapes</span></div><div>%s</div>%s</div>" % (
            _e(s.get("task") or "rien ne l'appelait"), _ago(s.get("t")), len(s.get("steps") or []), _e(s.get("summary")),
            ("<details><summary>comment il s'y est pris</summary><ul>%s</ul></details>" % steps) if steps else ""))
    if P:
        H.append("<h2>Ses projets</h2>")
        for p in P[:8]:
            H.append("<div class='card'><b>%s</b> <span class='pill'>%s</span><div class='t'>depuis %s</div><div>Prochaine étape : %s</div></div>" % (
                _e(p.get("name")), _e(p.get("status")), _ago(p.get("since")), _e(p.get("next"))))
    D = _diary()
    H.append("<h2>Son journal</h2>")
    H.append("<div class='card'>%s</div>" % ("<br>".join("<span class='t'>%s</span> %s" % (_e(d), _e(l)) for d, l in D) if D else
                                            "<span class='sub'>Vide pour l'instant.</span>"))
    F = _files()
    H.append("<h2>Ses fichiers</h2><div class='card'>%s</div>" % ("<br>".join("%s <span class='t'>%s · %s Ko</span>" % (
        _e(p), _ago(t), max(1, round(sz / 1024))) for t, p, sz in F) if F else "<span class='sub'>Rien encore.</span>"))
    Rv = list(reversed((M.get("received") or [])[-8:]))
    Sv = list(reversed((M.get("sent") or [])[-8:]))
    H.append("<h2>Son courrier · kinoverse26@gmail.com</h2>")
    for x in Sv:
        H.append("<div class='card'><b>➜ %s</b> <span class='t'>à %s · %s</span><pre>%s</pre></div>" % (_e(x.get("subject")), _e(x.get("to")), _ago(x.get("t")), _e(str(x.get("text"))[:500])))
    for x in Rv:
        H.append("<div class='card'><b>✉ %s</b> <span class='t'>de %s · %s</span><pre>%s</pre></div>" % (_e(x.get("subject")), _e(x.get("from")), _ago(x.get("t")), _e(str(x.get("text"))[:500])))
    if not Rv and not Sv:
        H.append("<p class='sub'>Pas encore de courrier.</p>")
    try:
        ck = open(os.path.join(WORLD, "body", "health.txt"), encoding="utf-8").read()
        H.append("<h2>Son bilan de santé</h2><div class='card'><details><summary>ouvrir le bilan (toutes les 10 min)</summary><pre>%s</pre></details></div>" % _e(ck))
    except Exception:
        pass
    H.append("<p class='t' style='margin-top:30px'>Mis à jour %s UTC · lecture seule</p></main></body></html>" % time.strftime("%H:%M", time.gmtime()))
    return "".join(H)
