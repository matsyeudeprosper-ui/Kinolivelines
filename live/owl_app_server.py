"""OwlNest v3 - MULTI-USER French PWA (2026-09-01).

Users live in owl_nest_users.json; per-user stats are computed by
owl_nest_worker.py processes (kept alive by owl_nest_manager.py) into
nest_data/<id>.json. This server only displays: it maps /<token>/ to the
user and serves their JSON. Old single-user docstring follows.

Read-only. Canonical URL (behind Caddy): https://mobali.duckdns.org/owlnest/kino/
Caddy strips /owlnest, so this server sees:
  GET /<TOKEN>/               -> one-page mobile HTML app (installable PWA)
  GET /<TOKEN>/api            -> JSON stats (incl. eurusd rate)
  GET /<TOKEN>/manifest.json  -> PWA manifest
  GET /<TOKEN>/sw.js          -> minimal service worker
  GET /<TOKEN>/icon192.png /icon512.png -> generated owl icons

Token = first line of owl_app_token.txt. Stats from MT5 deal history
(trade deals only). Max DD = deepest peak-to-trough over the last 7 days,
INCLUDING open-trade floating pain (sightings kept in _ddhist).
"""
import json, os, time, secrets, struct, threading, zlib
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np
import MetaTrader5 as mt5

DIR = r"C:\Projects\KinoliveLines\live"
TERMINAL = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
LOGIN = 134499778
PORT = 8787
TOKEN_FILE = os.path.join(DIR, "owl_app_token.txt")

if os.path.exists(TOKEN_FILE):
    TOKEN = open(TOKEN_FILE).read().strip()
else:
    TOKEN = secrets.token_urlsafe(18)
    open(TOKEN_FILE, "w").write(TOKEN)

_lock = threading.Lock()
_cache = {"t": 0.0, "data": None}
_ddhist = []   # (epoch, dd) sightings incl. floating pain, 7d window


ERA_START = datetime(2026, 8, 31, 3, 30, tzinfo=timezone.utc)
# 2026-09-01 user: stats show ONLY the machine's era - bot trades
# (OWL-kino pages + OWL-recov chains) since the clean restart; the
# user's hand trades and the pre-era mess are excluded.


def bot_out_deals(frm, to):
    """Closing deals of BOT-opened positions within [frm, to], era-clamped."""
    frm = max(frm, ERA_START)
    alld = mt5.history_deals_get(ERA_START, to) or []
    botpos = {d.position_id for d in alld
              if d.entry == mt5.DEAL_ENTRY_IN
              and (d.comment or "").startswith("OWL-")}
    return [d for d in alld
            if d.entry == mt5.DEAL_ENTRY_OUT
            and d.position_id in botpos
            and datetime.fromtimestamp(d.time, tz=timezone.utc) >= frm]


def stats():
    now = time.time()
    if _cache["data"] is not None and now - _cache["t"] < 5:
        return _cache["data"]
    with _lock:
        if _cache["data"] is not None and time.time() - _cache["t"] < 5:
            return _cache["data"]
        if not mt5.initialize(path=TERMINAL):
            return {"error": "mt5 init failed"}
        ai = mt5.account_info()
        if ai is None or ai.login != LOGIN:
            return {"error": "wrong account"}
        utcnow = datetime.now(timezone.utc)
        midnight = utcnow.replace(hour=0, minute=0, second=0, microsecond=0)
        monday = midnight - timedelta(days=midnight.weekday())
        week_ago = utcnow - timedelta(days=7)
        pnl = lambda ds: sum(d.profit + d.commission + d.swap for d in ds)
        today = pnl(bot_out_deals(midnight, utcnow + timedelta(minutes=5)))
        week = pnl(bot_out_deals(monday, utcnow + timedelta(minutes=5)))
        month = pnl(bot_out_deals(midnight.replace(day=1),
                                  utcnow + timedelta(minutes=5)))
        d7 = sorted(bot_out_deals(week_ago, utcnow + timedelta(minutes=5)),
                    key=lambda d: d.time)
        cum = 0.0
        peak = 0.0
        dd = 0.0
        for d in d7:
            cum += d.profit + d.commission + d.swap
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        # include OPEN-trade pain (user 2026-09-01): the floating curve
        # point counts against the 7d peak; worst sighting remembered.
        # Bot positions only (user hand trades excluded from stats).
        _open = mt5.positions_get(symbol="BTCUSDm") or []
        floating = sum(p.profit + p.swap for p in _open
                       if (p.comment or "").startswith("OWL-"))
        dd = max(dd, peak - (cum + floating))
        _ddhist.append((time.time(), dd))
        while _ddhist and time.time() - _ddhist[0][0] > 7 * 86400:
            _ddhist.pop(0)
        dd = max(x[1] for x in _ddhist)
        _te = mt5.symbol_info_tick("EURUSDm")
        _eur = round(_te.bid, 5) if _te and _te.bid > 0 else None
        trades = [{"w": datetime.fromtimestamp(d.time, tz=timezone.utc)
                        .strftime("%d/%m %H:%M"),
                   "p": round(d.profit + d.commission + d.swap, 2)}
                  for d in d7[-10:]][::-1]
        cum2 = 0.0
        curve = []
        for d in d7:
            cum2 += d.profit + d.commission + d.swap
            curve.append(round(cum2, 2))
        curve = curve[-120:]
        data = {
            "trades": trades,
            "curve": curve,
            "eurusd": _eur,
            "balance": round(ai.balance, 2),
            "equity": round(ai.equity, 2),
            "today": round(today, 2),
            "week": round(week, 2),
            "month": round(month, 2),
            "max_dd_7d": round(dd, 2),
            "open_positions": len(mt5.positions_get(symbol="BTCUSDm") or []),
            "updated_utc": utcnow.isoformat(timespec="seconds"),
        }
        _cache["data"] = data
        _cache["t"] = time.time()
        return data


def _png(arr):
    h, w, _ = arr.shape
    raw = b"".join(b"\x00" + arr[i].tobytes() for i in range(h))

    def chunk(t, d):
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def owl_icon(n):
    a = np.zeros((n, n, 3), np.uint8)
    a[:, :] = (13, 17, 23)
    yy, xx = np.mgrid[0:n, 0:n]
    for cx in (0.32, 0.68):
        d2 = (xx - n * cx) ** 2 + (yy - n * 0.40) ** 2
        a[d2 < (n * 0.17) ** 2] = (240, 180, 60)
        a[d2 < (n * 0.075) ** 2] = (18, 18, 18)
    beak = ((abs(xx - n * 0.5) < (yy - n * 0.50) * 0.38)
            & (yy > n * 0.50) & (yy < n * 0.70))
    a[beak] = (200, 120, 40)
    return _png(np.ascontiguousarray(a))


ICON192 = owl_icon(192)
ICON512 = owl_icon(512)

MANIFEST = json.dumps({
    "name": "OwlNest",
    "short_name": "OwlNest",
    "description": "Suivi du trading en direct",
    "start_url": "./",
    "scope": "/",
    "display": "standalone",
    "background_color": "#0b0f14",
    "theme_color": "#0f2740",
    "icons": [
        {"src": "icon192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "icon512.png", "sizes": "512x512", "type": "image/png"},
    ],
})

SW = (
    "self.addEventListener('install',e=>self.skipWaiting());"
    "self.addEventListener('activate',e=>e.waitUntil("
    "clients.claim()));"
    "self.addEventListener('fetch',()=>{});"
    "self.addEventListener('push',e=>{let d={};"
    "try{d=e.data.json()}catch(x){}"
    "e.waitUntil(self.registration.showNotification("
    "d.title||'OwlNest',{body:d.body||'',icon:'icon192.png',"
    "badge:'icon192.png',tag:d.tag||'owl'}));});"
    "self.addEventListener('notificationclick',e=>{"
    "e.notification.close();"
    "e.waitUntil(clients.matchAll({type:'window',"
    "includeUncontrolled:true}).then(cs=>{"
    "for(const c of cs){if('focus' in c)return c.focus();}"
    "return clients.openWindow('.');}));});")

VAPID_FILE = os.path.join(DIR, "owl_push_vapid.json")
PUSH_SUBS_FILE = os.path.join(DIR, "owl_push_subs.json")
try:
    _VAPID = json.load(open(VAPID_FILE))
except Exception:
    _VAPID = None


def _load_subs():
    try:
        return json.load(open(PUSH_SUBS_FILE))
    except Exception:
        return {}


def _save_subs(s):
    json.dump(s, open(PUSH_SUBS_FILE, "w"))

PAGE = """<!doctype html><html lang="fr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="google" content="notranslate">
<meta name="theme-color" content="#0f2740">
<title>OwlNest</title>
<style>
*{box-sizing:border-box;margin:0}
body{background:#0b0f14;color:#e8eef4;padding:0 0 96px;
 font-family:-apple-system,'Segoe UI',Roboto,sans-serif}
.tab{display:none}
.tab.on{display:block}
.tabbar{position:fixed;left:0;right:0;bottom:0;z-index:30;
 display:flex;max-width:480px;margin:0 auto;
 background:rgba(15,22,32,.94);backdrop-filter:blur(12px);
 border-top:1px solid #1e2937;border-radius:18px 18px 0 0;
 padding:6px 8px calc(8px + env(safe-area-inset-bottom,0px))}
.tb{flex:1;background:none;border:0;color:#5f7185;font-size:.68rem;
 font-weight:600;display:flex;flex-direction:column;
 align-items:center;gap:3px;padding:6px 0;border-radius:12px}
.tb span{font-size:1.3rem;line-height:1}
.tb.on{color:#8fc6ff}
.hero{background:linear-gradient(165deg,#0f2740 0%,#14406b 100%);
 color:#fff;padding:22px 22px 38px;border-radius:0 0 30px 30px;
 text-align:center;box-shadow:0 8px 24px rgba(0,0,0,.35)}
.topline{display:flex;justify-content:space-between;align-items:center}
.brand{font-weight:700;color:#cfe3f5;font-size:1.02rem}
.live{display:inline-flex;align-items:center;gap:6px;
 background:rgba(46,204,113,.16);color:#8df0bb;font-size:.7rem;
 font-weight:700;padding:4px 11px;border-radius:999px;
 letter-spacing:.06em}
.dot{width:8px;height:8px;border-radius:50%;background:#2ecc71;
 animation:p 1.8s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.25}}
.hello{color:#9fc2de;font-size:.95rem;margin-top:16px}
.money{font-size:3.5rem;font-weight:800;margin-top:6px;
 letter-spacing:-1px}
.eur{color:#9fc2de;font-size:1.2rem;margin-top:2px}
.bankline{color:#7d9cb8;font-size:.85rem;margin-top:9px}
.wrap{max-width:440px;margin:-20px auto 0;padding:0 16px}
.status{background:#151d29;border-radius:18px;padding:16px;
 text-align:center;font-size:1.04rem;color:#c6d3df;
 box-shadow:0 6px 18px rgba(0,0,0,.35)}
.panel{background:#151d29;border-radius:18px;padding:16px;
 box-shadow:0 6px 18px rgba(0,0,0,.35)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
.card{background:#151d29;border-radius:18px;padding:18px 10px 15px;
 text-align:center;box-shadow:0 6px 18px rgba(0,0,0,.35)}
.lbl{font-size:.74rem;color:#8fa1b3;text-transform:uppercase;
 letter-spacing:.06em;font-weight:600}
.val{font-size:1.45rem;font-weight:800;margin-top:8px;
 white-space:nowrap}
.sub{font-size:.72rem;color:#5f7185;margin-top:6px}
.pos{color:#2ecc71}.neg{color:#ff5c5c}.neu{color:#e8eef4}
.sec{margin:24px 6px 10px;color:#b9c7d4;font-weight:700;font-size:.96rem;
 text-align:left}
.row{display:flex;justify-content:space-between;align-items:center;
 padding:11px 4px;border-bottom:1px solid #1e2937;font-size:1rem}
.row:last-child{border-bottom:0}
@keyframes livepulse{0%{opacity:1;transform:scale(1)}
 50%{opacity:.35;transform:scale(.75)}100%{opacity:1;transform:scale(1)}}
.livedot{display:inline-block;width:8px;height:8px;border-radius:50%;
 background:#2ecc71;margin-right:6px;vertical-align:middle;
 animation:livepulse 1.6s infinite}
.rowt{color:#8fa1b3;font-size:.92rem}
.bd{display:inline-block;width:8px;height:8px;border-radius:50%;
 margin-right:8px;animation:p 1.8s infinite}
#inst{width:100%;margin-top:24px;background:#2563eb;
 color:#fff;border:0;border-radius:14px;padding:16px;font-size:1.06rem;
 font-weight:700}
#howto{display:none;margin-top:12px;background:#151d29;border:1px solid
 #263341;border-radius:14px;padding:14px;font-size:.9rem;color:#c6d3df;
 line-height:1.6;text-align:left}
.foot{margin-top:20px;text-align:center;font-size:.8rem;color:#5f7185}
.exit{display:block;margin-top:14px;text-align:center;color:#5f7185;
 font-size:.82rem;text-decoration:none}
.money,.val{font-variant-numeric:tabular-nums}
@supports(padding:env(safe-area-inset-top)){
 .hero{padding-top:calc(22px + env(safe-area-inset-top))}}
@keyframes fup{0%{text-shadow:0 0 20px rgba(46,204,113,.95)}
 100%{text-shadow:none}}
@keyframes fdn{0%{text-shadow:0 0 20px rgba(255,92,92,.95)}
 100%{text-shadow:none}}
.flash-up{animation:fup .9s ease}
.flash-dn{animation:fdn .9s ease}
.skel{position:relative;overflow:hidden;color:transparent!important;
 background:#1a2432!important;border-radius:8px}
.skel::after{content:'';position:absolute;inset:0;
 background:linear-gradient(90deg,transparent,
 rgba(255,255,255,.08),transparent);animation:shim 1.2s infinite}
@keyframes shim{0%{transform:translateX(-100%)}
 100%{transform:translateX(100%)}}
#sheetbg{position:fixed;inset:0;background:rgba(0,0,0,.55);
 display:none;z-index:40;opacity:0;transition:opacity .2s}
#sheet{position:fixed;left:0;right:0;bottom:0;z-index:41;
 background:#151d29;border-radius:22px 22px 0 0;
 padding:20px 20px calc(24px + env(safe-area-inset-bottom,0px));
 transform:translateY(105%);transition:transform .25s ease;
 box-shadow:0 -10px 40px rgba(0,0,0,.5);max-width:480px;margin:0 auto}
#sheet h3{font-size:1.08rem;margin-bottom:8px;color:#e8eef4}
#sheet p{color:#9fc2de;font-size:.9rem;line-height:1.55;
 margin-bottom:14px}
#sheet input{width:100%;padding:13px;border-radius:12px;
 border:1px solid #2a3a4e;background:#0b1420;color:#fff;
 font-size:1rem;margin-bottom:6px}
.shbtn{width:100%;border:0;border-radius:13px;padding:14px;
 font-size:1rem;font-weight:700;margin-top:8px}
.shmain{background:#2563eb;color:#fff}
.shdanger{background:#a03030;color:#fff}
.shghost{background:#1e2937;color:#c6d3df}
.grab{width:38px;height:4px;border-radius:99px;background:#2a3a4e;
 margin:0 auto 14px}
</style></head><body>
<div class="hero">
<div class="topline"><span class="brand">&#129417; OwlNest</span>
<span style="display:flex;align-items:center;gap:10px">
<span class="live" id="lv"><span class="dot" id="lvd"></span><span
 id="lvt">EN DIRECT</span></span>
<a href="../" style="color:#9fc2de;text-decoration:none;font-size:1.25rem;
 line-height:1" title="Sortir">&#10162;</a></span></div>
<div class="hello" id="hello">Bonjour %%NAME%% &#128075;</div>
<div class="money skel" id="eq">&#8226;&#8226;&#8226;</div>
<div class="eur" id="eqe">&nbsp;</div>
<div class="bankline" id="bank">&nbsp;</div>
<div id="palier" style="display:none;margin-top:14px;text-align:left">
 <div style="font-size:.78rem;color:#9fc2de" id="palier-lbl"></div>
 <div style="background:rgba(255,255,255,.15);border-radius:99px;
  height:8px;margin-top:6px"><div id="palier-bar" style="background:
  #2ecc71;height:8px;border-radius:99px;width:0%"></div></div>
</div>
</div>
<div class="wrap">
<div class="tab on" id="tab-home">
<div class="status" id="st" style="margin-top:26px">Connexion...</div>
<div id="trial" style="display:none;margin-top:10px;text-align:center;
 background:#251d07;border:1px solid #4a3c12;border-radius:14px;
 padding:10px;color:#e8c55a;font-size:.9rem"></div>
<div id="meteo" style="margin-top:12px;text-align:center;
 background:#101c2b;border:1px solid #23405e;border-radius:16px;
 padding:14px;color:#cfe3f5;font-size:.95rem;line-height:1.5">
 <div style="font-size:.7rem;color:#6f93b5;text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:6px">&Eacute;tat du robot</div>
 <div id="meteo-txt">&#9925; ...</div></div>
<div id="ledcard" style="display:none;margin-top:12px;background:#101c2b;
 border:1px solid #23405e;border-radius:16px;
 padding:14px;color:#cfe3f5;font-size:.92rem;line-height:1.5">
 <div style="font-size:.7rem;color:#6f93b5;text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:6px">Le rattrapage</div>
 <div id="led-txt"></div>
 <div id="led-barwrap" style="display:none;
  background:rgba(255,255,255,.15);border-radius:99px;height:8px;
  margin-top:8px"><div id="led-bar" style="background:#e8c55a;
  height:8px;border-radius:99px;width:0%"></div></div>
 <div id="led-sub" style="font-size:.78rem;color:#6f93b5;margin-top:6px">
 </div>
</div>
<div id="actcard" style="display:none;margin-top:12px;background:#0f2740;
 border:1px solid #2a5a80;border-radius:16px;
 padding:16px;text-align:center">
 <div style="font-size:1rem;color:#cfe3f5">&#128273; <b>Activer le
  robot</b></div>
 <div style="font-size:.86rem;color:#9fc2de;margin-top:6px;line-height:1.5">
  Demandez votre code d&#8217;activation &agrave; <b>Kino sur
  Telegram</b>, puis entrez-le ici.</div>
 <input id="actcode" inputmode="text" autocapitalize="characters"
  maxlength="6" placeholder="CODE"
  style="margin-top:10px;width:60%;padding:12px;font-size:1.3rem;
  text-align:center;letter-spacing:.3em;border-radius:12px;border:1px
  solid #2a5a80;background:#0b1826;color:#fff;text-transform:uppercase">
 <br><button id="actbtn" style="margin-top:10px;background:#2563eb;
  color:#fff;border:0;border-radius:12px;padding:12px 26px;
  font-size:1rem;font-weight:700">Activer</button>
 <div id="actmsg" style="margin-top:8px;font-size:.85rem;color:#ff9c9c">
 </div>
</div>
<div id="battles-sec" style="display:none">
<div class="panel" style="margin-top:24px;
 background:linear-gradient(135deg,#0f2740,#151d29);
 border:1px solid #2a5a80;box-shadow:0 6px 22px rgba(37,99,235,.28)">
 <div style="display:flex;justify-content:space-between;
  align-items:center;margin-bottom:6px">
  <span style="font-size:.7rem;color:#7fb3e0;text-transform:uppercase;
   letter-spacing:.08em;font-weight:700">&#9876;&#65039; En plein
   combat</span>
  <span style="font-size:.66rem;color:#8df0bb;font-weight:800;
   letter-spacing:.06em"><span class="livedot"></span>EN DIRECT</span>
 </div>
 <div id="battles"></div>
</div>
</div>
<div class="grid">
<div class="card"><div class="lbl">Aujourd&#8217;hui</div>
<div class="val skel" id="today">--</div>
<div class="sub">gains du jour</div></div>
<div class="card"><div class="lbl">Cette semaine</div>
<div class="val skel" id="week">--</div>
<div class="sub">depuis lundi</div></div>
<div class="card"><div class="lbl">Pire creux</div>
<div class="val neg skel" id="dd">--</div>
<div class="sub">7 derniers jours</div></div>
<div class="card"><div class="lbl">Ce mois</div>
<div class="val skel" id="month">--</div>
<div class="sub">depuis le 1er</div></div>
</div>
<div class="sec">Progression &middot; 7 jours</div>
<div class="panel"><svg id="spark" viewBox="0 0 300 70"
 style="width:100%;height:70px"></svg></div>
</div>
<div class="tab" id="tab-hist">
<div class="sec" style="margin-top:26px">Jour par jour &middot;
 touchez un jour</div>
<div class="panel" id="days" style="display:none"></div>
<div class="sec" id="msum-sec" style="display:none">R&eacute;sum&eacute;
 du mois</div>
<div class="grid" id="msum" style="display:none;margin-top:2px"></div>
<div class="sec" id="cal-sec" style="display:none">Calendrier du mois
</div>
<div class="panel" id="cal" style="display:none"></div>
<div class="sec">Derniers trades</div>
<div class="panel" id="hist">
<div class="row"><span class="skel" style="width:42%">&nbsp;</span>
<span class="skel" style="width:18%">&nbsp;</span></div>
<div class="row"><span class="skel" style="width:36%">&nbsp;</span>
<span class="skel" style="width:22%">&nbsp;</span></div>
<div class="row"><span class="skel" style="width:46%">&nbsp;</span>
<span class="skel" style="width:16%">&nbsp;</span></div></div>
</div>
<div class="tab" id="tab-set">
<div class="sec" style="margin-top:26px">R&eacute;glages</div>
<button id="notifbtn" style="width:100%;margin-top:4px;
 background:#1d3350;color:#cfe3f5;border:1px solid #2a5a80;
 border-radius:14px;padding:15px;font-size:1rem;font-weight:700;
 display:none">&#128276; Activer les notifications</button>
<button id="inst" onclick="inst()">Installer l&#8217;application</button>
<div id="howto">&#128241; <b>Pour installer :</b><br>
1. Touchez le menu <b>&#8942;</b> en haut &agrave; droite de Chrome<br>
2. Choisissez <b>&laquo; Ajouter &agrave; l&#8217;&eacute;cran
 d&#8217;accueil &raquo;</b> (ou &laquo; Installer
 l&#8217;application &raquo;)<br>
3. L&#8217;ic&ocirc;ne &#129417; appara&icirc;t sur votre
 t&eacute;l&eacute;phone !</div>
<div class="foot" id="upd">chargement...</div>
<div style="margin-top:24px;text-align:center">
<a href="#" id="codebtn" style="display:none;color:#8fa1b3;
 font-size:.86rem;text-decoration:none">&#128273; G&eacute;n&eacute;rer
 un code d&#8217;activation</a>
<br><a href="#" id="pausebtn" style="display:none;color:#8fa1b3;
 font-size:.86rem;text-decoration:none;margin-top:10px;
 display:none">&#9208;&#65039; Mettre le robot
 en pause</a>
<br><a href="#" id="delbtn" style="color:#8a5a5a;font-size:.78rem;
 text-decoration:none;display:inline-block;margin-top:12px">&#128465;
 Retirer mon compte du robot</a>
</div>
<a class="exit" href="../">&#8618; Changer de compte &middot;
 cr&eacute;er un nouveau nid</a>
</div>
</div>
<div class="tabbar">
<button class="tb on" onclick="tab('home',this)"><span>&#127968;
</span>Accueil</button>
<button class="tb" onclick="tab('hist',this)"><span>&#128197;
</span>Historique</button>
<button class="tb" onclick="tab('set',this)"><span>&#9881;&#65039;
</span>R&eacute;glages</button>
</div>
<div id="sheetbg"></div>
<div id="sheet"><div class="grab"></div><div id="sheet-c"></div></div>
<script>
const B=location.pathname.endsWith('/')?location.pathname:location.pathname+'/';
(function(){
 const m=document.createElement('link');m.rel='manifest';
 m.href=B+'manifest.json';document.head.appendChild(m);
 const i=document.createElement('link');i.rel='icon';
 i.href=B+'icon192.png';document.head.appendChild(i);
})();
let lastOk=0;
let isPaused=false;
function sheet(html){return new Promise(res=>{
 const bg=document.getElementById('sheetbg'),
  sh=document.getElementById('sheet');
 document.getElementById('sheet-c').innerHTML=html;
 bg.style.display='block';
 requestAnimationFrame(()=>{bg.style.opacity='1';
  sh.style.transform='translateY(0)'});
 window._shDone=(v)=>{bg.style.opacity='0';
  sh.style.transform='translateY(105%)';
  setTimeout(()=>{bg.style.display='none'},250);res(v)};
 bg.onclick=()=>window._shDone(null);
});}
function askPwd(title,desc,btn,danger){return sheet(
 '<h3>'+title+'</h3><p>'+desc+'</p>'+
 '<input id="shpw" type="password" autocomplete="current-password" '+
 'placeholder="Mot de passe du compte (broker)">'+
 '<button class="shbtn '+(danger?'shdanger':'shmain')+'" '+
 'onclick="_shDone(document.getElementById(\\'shpw\\').value)">'+
 btn+'</button>'+
 '<button class="shbtn shghost" onclick="_shDone(null)">Annuler'+
 '</button>').then(v=>{
  if(v){try{navigator.vibrate&&navigator.vibrate(12)}catch(e){}}
  return v;});}
function info(html){return sheet(html+
 '<button class="shbtn shmain" onclick="_shDone(1)">OK</button>');}
window.addEventListener('load',()=>{
 const pb=document.getElementById('pausebtn');
 if(pb)pb.onclick=async(e)=>{e.preventDefault();
  const pw=await askPwd(
   isPaused?'Reprendre le trading ?':'Mettre le robot en pause ?',
   isPaused
    ?'Le robot reprendra les nouveaux trades sur ce compte.'
    :'Le robot ne prendra plus de nouveaux trades sur ce compte. '+
     'Les trades ouverts gardent leur protection (SL/TP).',
   isPaused?'&#9654;&#65039; Reprendre':'&#9208;&#65039; Mettre en pause',
   !isPaused);
  if(!pw)return;
  const r=await fetch(B+'pause',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'on='+(isPaused?'0':'1')+'&pwd='+encodeURIComponent(pw)}
   ).catch(()=>null);
  try{const j=await r.json();
   if(!j.ok){await info('&#10060; <h3>Mot de passe incorrect.</h3>');
    return;}}catch(e2){}
  load();};
 const ab=document.getElementById('actbtn');
 if(ab)ab.onclick=async(e)=>{e.preventDefault();
  const code=(document.getElementById('actcode').value||'').trim();
  const msg=document.getElementById('actmsg');
  if(code.length<6){msg.textContent='Entrez le code complet.';return;}
  ab.disabled=true;ab.textContent='...';
  const r=await fetch(B+'activate',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'code='+encodeURIComponent(code)}).catch(()=>null);
  ab.disabled=false;ab.textContent='Activer';
  try{const j=await r.json();
   if(j.ok){document.getElementById('actcard').innerHTML=
    '<div style="font-size:1.05rem;color:#8df0bb">&#127881; '+
    '<b>Robot activ&eacute; !</b><br><span style="font-size:.85rem;'+
    'color:#9fc2de">Le robot copie maintenant les trades sur votre '+
    'compte.</span></div>';setTimeout(load,1500);}
   else{msg.textContent='Code invalide ou expir&eacute;. Demandez un '+
    'nouveau code &agrave; Kino.';}}
  catch(e2){msg.textContent='Petit souci, r&eacute;essayez.';}};
 const cb=document.getElementById('codebtn');
 if(cb)cb.onclick=async(e)=>{e.preventDefault();
  const pw=await askPwd('G&eacute;n&eacute;rer un code d&#39;activation',
   'Le code est valable 24 h, usage unique. Envoyez-le au membre '+
   'sur Telegram.','&#128273; G&eacute;n&eacute;rer',false);
  if(!pw)return;
  const r=await fetch(B+'actcode',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'pwd='+encodeURIComponent(pw)}).catch(()=>null);
  try{const j=await r.json();
   if(j.ok){await sheet('<h3>Code d&#39;activation</h3>'+
    '<div style="font-size:2rem;font-weight:800;letter-spacing:.3em;'+
    'text-align:center;background:#0b1420;border-radius:14px;'+
    'padding:18px 6px;margin:6px 0 10px;color:#8df0bb">'+j.code+
    '</div><p>Valable 24 h &middot; usage unique</p>'+
    '<button class="shbtn shmain" onclick="navigator.clipboard&&'+
    'navigator.clipboard.writeText(\\''+j.code+'\\');_shDone(1)">'+
    '&#128203; Copier et fermer</button>');}
   else{await info('&#10060; <h3>Mot de passe incorrect.</h3>');}}
  catch(e2){await info('<h3>Petit souci, r&eacute;essayez.</h3>');}};
 const db=document.getElementById('delbtn');
 if(db)db.onclick=async(e)=>{e.preventDefault();
  const pw=await askPwd('Retirer mon compte du robot ?',
   '&#9888;&#65039; Le robot arr&ecirc;te de trader ce compte et '+
   'cette page ne fonctionnera plus. Pour revenir il faudra vous '+
   'inscrire &agrave; nouveau.',
   '&#128465; Retirer d&eacute;finitivement',true);
  if(!pw)return;
  const r=await fetch(B+'delete',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'pwd='+encodeURIComponent(pw)}).catch(()=>null);
  try{const j=await r.clone().json();
   if(!j.ok){await info('&#10060; <h3>Mot de passe incorrect.</h3>');
    return;}}catch(e2){}
  if(r&&r.ok){document.body.innerHTML=
   '<div style="padding:48px 24px;text-align:center;color:#c6d3df;'+
   'font-family:sans-serif;line-height:1.7">&#128075; <b>Compte '+
   'retir&eacute;.</b><br>Le robot ne trade plus ce compte.<br>Pour '+
   'revenir : inscrivez-vous &agrave; nouveau.<br><br>'+
   '<a href="../" style="color:#2563eb">Accueil</a></div>';}};
});
async function notifSetup(){
 const nb=document.getElementById('notifbtn');
 if(!nb||!('serviceWorker' in navigator)||!('PushManager' in window)
    ||!window.Notification){return;}
 const reg=await navigator.serviceWorker.ready.catch(()=>null);
 if(!reg||!reg.pushManager){return;}
 nb.style.display='block';
 const cur=await reg.pushManager.getSubscription().catch(()=>null);
 nb.dataset.on=cur?'1':'0';
 nb.innerHTML=cur?'&#128277; D&eacute;sactiver les notifications'
  :'&#128276; Activer les notifications';
 nb.onclick=async()=>{
  if(nb.dataset.on==='1'){
   const s=await reg.pushManager.getSubscription().catch(()=>null);
   if(s){await fetch(B+'push_unsub',{method:'POST',
    body:JSON.stringify(s)}).catch(()=>null);
    await s.unsubscribe().catch(()=>null);}
   notifSetup();return;
  }
  const perm=await Notification.requestPermission();
  if(perm!=='granted'){await info('<h3>Le t&eacute;l&eacute;phone a '+
   'refus&eacute; les notifications.</h3><p>Autorisez-les dans les '+
   'r&eacute;glages du navigateur.</p>');return;}
  const kr=await fetch(B+'push_key').then(r=>r.json())
   .catch(()=>null);
  if(!kr||!kr.key){await info('<h3>Service indisponible.</h3>');
   return;}
  const conv=(s)=>{const p='='.repeat((4-s.length%4)%4);
   const b=atob((s+p).replace(/-/g,'+').replace(/_/g,'/'));
   return Uint8Array.from([...b].map(c=>c.charCodeAt(0)));};
  const s=await reg.pushManager.subscribe({userVisibleOnly:true,
   applicationServerKey:conv(kr.key)}).catch(()=>null);
  if(!s){await info('<h3>Abonnement impossible sur cet '+
   'appareil.</h3>');return;}
  await fetch(B+'push_sub',{method:'POST',body:JSON.stringify(s)})
   .catch(()=>null);
  await info('&#128276; <h3>Notifications activ&eacute;es !</h3>'+
   '<p>Vous recevrez les gains, les orages et les victoires des '+
   'soldats &mdash; m&ecirc;me app ferm&eacute;e.</p>');
  notifSetup();
 };
}
window.addEventListener('load',notifSetup);
function tab(n,el){
 document.querySelectorAll('.tab').forEach(x=>
  x.classList.toggle('on',x.id==='tab-'+n));
 document.querySelectorAll('.tb').forEach(x=>
  x.classList.toggle('on',x===el));
 try{navigator.vibrate&&navigator.vibrate(6)}catch(e){}
 window.scrollTo({top:0});
}
(function(){
 const h=new Date().getHours();
 const g=(h>=5&&h<12)?'Bonjour':(h<18?'Bon apr&egrave;s-midi'
  :'Bonsoir');
 const he=document.getElementById('hello');
 he.innerHTML=he.innerHTML.replace('Bonjour',g)
  .replace('&#128075;',(h>=20||h<5)?'&#127769;':'&#128075;')
  .replace('👋',(h>=20||h<5)?'🌙'
   :'👋');
})();
function confetti(){
 for(let i=0;i<44;i++){
  const s=document.createElement('div');
  s.textContent=['🎉','✨','💚',
   '🏆'][i%4];
  s.style.cssText='position:fixed;z-index:60;top:-30px;left:'+
   (Math.random()*100)+'vw;font-size:'+(14+Math.random()*16)+
   'px;transition:transform 2.8s ease-in,opacity 2.8s;'+
   'pointer-events:none';
  document.body.appendChild(s);
  requestAnimationFrame(()=>{s.style.transform='translateY('+
   (window.innerHeight+80)+'px) rotate('+
   (Math.random()*720-360)+'deg)';s.style.opacity='0';});
  setTimeout(()=>s.remove(),3000);
 }
 try{navigator.vibrate&&navigator.vibrate([40,60,40])}catch(e){}
}
window.openDay=null;
function dayx(l){
 window.openDay=(window.openDay===l?null:l);
 load();
}
function ago(){
 if(!lastOk){return}
 const s=Math.max(0,Math.round((Date.now()-lastOk)/1000));
 document.getElementById('upd').innerHTML='Mis &agrave; jour il y a '+s+' s';
}
async function load(){
 try{
  const r=await fetch(B+'api?t='+Date.now(),{cache:'no-store'});
  const d=await r.json();
  if(d.expired){document.getElementById('st').innerHTML=
   '&#9203; <b>Essai termin&eacute;.</b> Contactez Kino pour passer au '+
   'Premium et continuer.';return}
  if(d.error){document.getElementById('st').innerHTML=
   '&#9203; '+(d.error.includes('patientez')?d.error:
   'Petit souci technique, r&eacute;essai automatique...');return}
  const lv=document.getElementById('lv'),lvd=document.getElementById('lvd'),
   lvt=document.getElementById('lvt');
  if(d.stale){lv.style.background='rgba(230,160,40,.16)';
   lv.style.color='#ffd27a';lvd.style.background='#e6a028';
   lvt.textContent='RECONNEXION';}
  else{lv.style.background='rgba(46,204,113,.16)';lv.style.color='#8df0bb';
   lvd.style.background='#2ecc71';lvt.textContent='EN DIRECT';}
  const mt=document.getElementById('meteo-txt');
  if(d.meteo==='storm'||d.meteo==='shelter'){
   mt.innerHTML='&#9928;&#65039; <b>Gros orage</b><br>Le march&eacute; '+
    's&#8217;agite trop : le robot se met en pause et attend.';}
  else if(d.meteo==='floor'){
   mt.innerHTML='&#127783;&#65039; <b>Temps couvert</b><br>March&eacute; '+
    'nerveux : le robot ne fait que de petits trades, prudemment.';}
  else if(d.meteo==='clear'){
   mt.innerHTML='&#127781;&#65039; <b>&Eacute;claircie</b><br>Le calme '+
    'revient : le robot se remet &agrave; trader normalement.';}
  else{
   mt.innerHTML='&#9728;&#65039; <b>Grand beau temps</b><br>March&eacute; '+
    'tranquille : le robot travaille normalement.';}
  if((d.meteo==='storm'||d.meteo==='shelter'||d.meteo==='floor')
     &&d.meteo_since){
   const s=Math.max(0,Math.round(Date.now()/1000-d.meteo_since));
   const hh=Math.floor(s/3600),mm=Math.floor((s%3600)/60);
   const lt=new Date(d.meteo_since*1000).toLocaleTimeString([],
    {hour:'2-digit',minute:'2-digit'});
   mt.innerHTML+='<br><span style="color:#6f93b5;font-size:.85rem">'+
    'En pause depuis '+lt+' ('+(hh>0?hh+' h ':'')+mm+' min)</span>';}
  if(d.ledger){
   const lc=document.getElementById('ledcard');lc.style.display='block';
   const lt2=document.getElementById('led-txt'),
    lb=document.getElementById('led-bar'),
    lw=document.getElementById('led-barwrap'),
    ls2=document.getElementById('led-sub');
   if(d.ledger.debt>0.5){
    const need=Math.max(d.ledger.need_min||0,0.01);
    const pc2=Math.max(0,Math.min(100,d.ledger.chest/need*100));
    lt2.innerHTML='&#128546; Le robot a perdu : '+
     '<b style="color:#ff9c9c">'+d.ledger.debt.toFixed(2)+
     '&nbsp;$</b><br>&#128176; Argent mis de c&ocirc;t&eacute; : '+
     '<b style="color:#e8c55a">'+d.ledger.chest.toFixed(2)+'&nbsp;$</b>'+
     '<br><span style="font-size:.84rem;color:#9fc2de">Il fait de '+
     'tout petits trades et garde chaque petit gain de '+
     'c&ocirc;t&eacute;.</span>';
    lw.style.display='block';lb.style.width=pc2+'%';
    ls2.innerHTML='Quand il a mis assez de c&ocirc;t&eacute; ('+
     pc2.toFixed(0)+'&nbsp;%), il tente un coup un peu plus gros '+
     'pour rattraper la perte. Ce coup est d&eacute;j&agrave; '+
     'pay&eacute; d&#8217;avance : m&ecirc;me si &ccedil;a rate, '+
     'votre compte ne descend pas plus bas.';
   }else{
    lt2.innerHTML='&#128522; Tout va bien &mdash; rien &agrave; '+
     'rattraper.'+(d.ledger.chest>0
     ?'<br>&#128176; Gard&eacute; pour les jours difficiles : '+
      '<b style="color:#e8c55a">'+d.ledger.chest.toFixed(2)+
      '&nbsp;$</b>':'');
    lw.style.display='none';ls2.innerHTML='';
   }
  }
  if(d.trial_days_left!==undefined){
   const tb=document.getElementById('trial');tb.style.display='block';
   tb.innerHTML='&#127873; Essai gratuit &mdash; <b>'+d.trial_days_left+
    ' jour'+(d.trial_days_left>1?'s':'')+' restant'+
    (d.trial_days_left>1?'s':'')+'</b>';}
  const f=(x)=>(x>=0?'+':'-')+Math.abs(x).toFixed(2)+'&nbsp;$';
  document.querySelectorAll('.skel').forEach(el=>
   el.classList.remove('skel'));
  const eqEl=document.getElementById('eq');
  const prevEq=parseFloat(eqEl.dataset.v||'NaN');
  if(isNaN(prevEq)||Math.abs(prevEq-d.equity)<0.005){
   eqEl.textContent=d.equity.toFixed(2)+' $';}
  else{
   const from=prevEq,to=d.equity,t0=performance.now();
   eqEl.classList.remove('flash-up','flash-dn');void eqEl.offsetWidth;
   eqEl.classList.add(to>=from?'flash-up':'flash-dn');
   (function stepA(ts){const k=Math.min(1,(ts-t0)/500);
    eqEl.textContent=(from+(to-from)*(1-Math.pow(1-k,3)))
     .toFixed(2)+' $';
    if(k<1)requestAnimationFrame(stepA);})(t0);
  }
  eqEl.dataset.v=d.equity;
  if(d.eurusd){document.getElementById('eqe').innerHTML=
   '&asymp; '+(d.equity/d.eurusd).toFixed(0)+' &euro;';}
  document.getElementById('bank').innerHTML=
   'Solde des trades termin&eacute;s : '+d.balance.toFixed(2)+' $';
  if(d.palier&&d.equity){
   const pc=Math.max(0,Math.min(100,d.equity/d.palier*100));
   document.getElementById('palier').style.display='block';
   document.getElementById('palier-lbl').innerHTML=
    'Objectif : '+d.palier.toFixed(0)+'&nbsp;$ &middot; '+
    pc.toFixed(0)+'&nbsp;%';
   document.getElementById('palier-bar').style.width=pc+'%';
   if(pc>=100&&!window._conf){window._conf=1;confetti();}
  }
  const n=d.open_positions;
  if(d.trading_paused!==undefined){
   isPaused=d.trading_paused;
   const pb=document.getElementById('pausebtn');
   pb.style.display='inline';
   pb.innerHTML=isPaused
    ?'&#9654;&#65039; Reprendre le trading'
    :'&#9208;&#65039; Mettre le robot en pause';
  }
  document.getElementById('actcard').style.display=
   d.activation_needed?'block':'none';
  if(d.is_master){document.getElementById('codebtn')
   .style.display='inline';}
  document.getElementById('st').innerHTML =
   (d.trading_paused)
   ? '&#9208;&#65039; <b>Robot en pause</b> (par vous) &mdash; aucun '+
     'nouveau trade'
   : (n>0
   ? '&#129302; Le robot travaille &mdash; <b>'+n+' trade'+(n>1?'s':'')+
     ' en cours</b>'
   : '&#127747; March&eacute; sous surveillance &mdash; aucun trade ouvert');
  const bs=document.getElementById('battles-sec');
  if(d.open_list&&d.open_list.length){
   bs.style.display='block';
   document.getElementById('battles').innerHTML=d.open_list.map(x=>{
    let bar='';
    if(x.e&&x.sl&&x.tp&&x.cur){
     const P=(v)=>x.d=='A'
      ?(v-x.sl)/((x.tp-x.sl)||1)*100
      :(x.sl-v)/((x.sl-x.tp)||1)*100;
     const cp=Math.max(2,Math.min(98,P(x.cur))),
      ep=Math.max(2,Math.min(98,P(x.e)));
     const col=x.pl>=0?'#2ecc71':'#ff5c5c';
     bar='<div style="position:relative;height:6px;border-radius:99px;'+
      'background:linear-gradient(90deg,rgba(255,92,92,.4),'+
      'rgba(255,255,255,.08) 50%,rgba(46,204,113,.4));'+
      'margin:2px 4px 12px">'+
      '<div style="position:absolute;top:-2px;left:calc('+
      ep.toFixed(1)+'% - 1px);width:2px;height:10px;'+
      'background:#8fa1b3"></div>'+
      '<div style="position:absolute;top:-3px;left:calc('+
      cp.toFixed(1)+'% - 6px);width:12px;height:12px;'+
      'border-radius:50%;background:'+col+';box-shadow:0 0 8px '+col+
      '"></div></div>'+
      '<div style="display:flex;justify-content:space-between;'+
      'margin:-8px 4px 8px;font-size:.6rem;color:#5f7185">'+
      '<span>mur</span><span>cible</span></div>';
    }
    return '<div class="row" style="border-bottom-color:#1d3350;'+
    'border-bottom:0">'+
    '<span style="display:flex;align-items:center;gap:8px">'+
    (x.d=='A'?'&#128200; <b>Achat</b>':'&#128201; <b>Vente</b>')+
    ' <span style="color:#6f93b5;font-size:.85rem">'+x.lot.toFixed(2)+
    ' lot</span></span><b style="font-size:1.12rem" class="'+
    (x.pl>=0?'pos':'neg')+'">'+
    (x.pl>=0?'+':'-')+Math.abs(x.pl).toFixed(2)+' $</b></div>'+bar;
   }).join('');
  }else{bs.style.display='none'}
  const t=document.getElementById('today');
  t.innerHTML=(d.today>=0?'&#9650; ':'&#9660; ')+f(d.today);
  t.className='val '+(d.today>=0?'pos':'neg');
  const w=document.getElementById('week');
  w.innerHTML=(d.week>=0?'&#9650; ':'&#9660; ')+f(d.week);
  w.className='val '+(d.week>=0?'pos':'neg');
  const dv=d.max_dd_7d.toFixed(0);
  document.getElementById('dd').textContent=(dv==0?'0':'-'+dv)+' $';
  if(d.month!==undefined){
   const mo=document.getElementById('month');
   mo.innerHTML=(d.month>=0?'&#9650; ':'&#9660; ')+f(d.month);
   mo.className='val '+(d.month>=0?'pos':'neg');
  }
  if(d.curve&&d.curve.length>1){
   const c=d.curve,mn=Math.min(...c,0),mx=Math.max(...c,0),sp=(mx-mn)||1;
   const P=(v,i)=>((i/(c.length-1))*300).toFixed(1)+','+
     (62-((v-mn)/sp*54)).toFixed(1);
   const pts=c.map((v,i)=>P(v,i)).join(' ');
   const up=c[c.length-1]>=0;
   const col=up?'#2ecc71':'#ff5c5c';
   const y0=(62-((0-mn)/sp*54)).toFixed(1);
   document.getElementById('spark').innerHTML=
    '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'+
    '<stop offset="0%" stop-color="'+col+'" stop-opacity=".35"/>'+
    '<stop offset="100%" stop-color="'+col+'" stop-opacity="0"/>'+
    '</linearGradient></defs>'+
    '<line x1="0" y1="'+y0+'" x2="300" y2="'+y0+'" stroke="#3a4a5c"'+
    ' stroke-width="1" stroke-dasharray="4 4"/>'+
    '<polygon points="0,70 '+pts+' 300,70" fill="url(#g)"/>'+
    '<polyline points="'+pts+'" fill="none" stroke="'+col+
    '" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>';
  }
  if(d.days&&d.days.length){
   const de=document.getElementById('days');de.style.display='block';
   window._dtr=d.day_trades||{};
   de.innerHTML=d.days.map(x=>{
    const tr=window._dtr[x.d]||[];
    const open=window.openDay===x.d&&tr.length;
    return '<div class="row" style="cursor:pointer" data-l="'+x.d+
    '" onclick="dayx(this.dataset.l)"><span class="rowt">'+
    (tr.length?(open?'&#9662; ':'&#9656; '):'&nbsp;&nbsp;')+x.d+
    '</span><b class="'+(x.p>=0?'pos':'neg')+'">'+
    (x.p>=0?'+':'-')+Math.abs(x.p).toFixed(2)+'&nbsp;$</b></div>'+
    (open?'<div style="padding:0 0 6px 18px;border-bottom:1px solid '+
    '#1e2937">'+tr.map(t=>'<div class="row" style="font-size:.85rem;'+
    'padding:6px 4px;border-bottom:0"><span class="rowt">'+t.t+
    '</span><span class="'+(t.p>=0?'pos':'neg')+'">'+
    (t.p>=0?'+':'-')+Math.abs(t.p).toFixed(2)+'&nbsp;$</span></div>')
    .join('')+'</div>':'');
   }).join('');
  }
  if(d.month_days&&d.month_days.length){
   const vals=d.month_days.map(x=>x.p);
   const net=vals.reduce((a,b)=>a+b,0);
   const g=vals.filter(v=>v>0.005).length,
    rr=vals.filter(v=>v<-0.005).length;
   const best=Math.max(...vals),worst=Math.min(...vals);
   const cell=(l,v,c,s)=>'<div class="card"><div class="lbl">'+l+
    '</div><div class="val '+c+'" style="font-size:1.15rem">'+v+
    '</div><div class="sub">'+s+'</div></div>';
   document.getElementById('msum-sec').style.display='block';
   const ms=document.getElementById('msum');
   ms.style.display='grid';
   ms.innerHTML=
    cell('Net du mois',f(net),net>=0?'pos':'neg','depuis le 1er')+
    cell('Jours','<span class="pos">'+g+'</span> / <span class="neg">'+
     rr+'</span>','neu','verts / rouges')+
    cell('Meilleur jour',f(best),'pos','le plus gagnant')+
    cell('Pire jour',f(worst),worst>=0?'pos':'neg','le plus dur');
   const md={};d.month_days.forEach(x=>md[x.d]=x.p);
   const now=new Date();
   const y=now.getUTCFullYear(),m=now.getUTCMonth();
   const nd=new Date(Date.UTC(y,m+1,0)).getUTCDate();
   const off=(new Date(Date.UTC(y,m,1)).getUTCDay()+6)%7;
   let h='<div style="display:grid;'+
    'grid-template-columns:repeat(7,1fr);gap:6px">';
   ['L','M','M','J','V','S','D'].forEach(w=>h+=
    '<div style="text-align:center;font-size:.62rem;'+
    'color:#5f7185">'+w+'</div>');
   for(let i=0;i<off;i++)h+='<div></div>';
   for(let dd2=1;dd2<=nd;dd2++){
    const k=y+'-'+String(m+1).padStart(2,'0')+'-'+
     String(dd2).padStart(2,'0');
    const p=md[k];let bg='#141c28',fg='#4c5c6f';
    if(p!==undefined){
     if(p>0.005){bg='rgba(46,204,113,'+
      Math.min(.85,.28+p/4).toFixed(2)+')';fg='#eafff3';}
     else if(p<-0.005){bg='rgba(255,92,92,'+
      Math.min(.85,.28-p/4).toFixed(2)+')';fg='#ffecec';}
     else{bg='#22303f';fg='#9fb2c4';}
    }
    h+='<div style="aspect-ratio:1;border-radius:9px;background:'+bg+
     ';display:flex;align-items:center;justify-content:center;'+
     'font-size:.7rem;font-weight:600;color:'+fg+'" title="'+
     (p===undefined?'':((p>=0?'+':'-')+Math.abs(p).toFixed(2)+' $'))+
     '">'+dd2+'</div>';
   }
   h+='</div>';
   document.getElementById('cal-sec').style.display='block';
   const ce=document.getElementById('cal');
   ce.style.display='block';ce.innerHTML=h;
  }
  if(d.trades&&d.trades.length){
   document.getElementById('hist').innerHTML=d.trades.map(x=>
    '<div class="row"><span class="rowt">'+x.w+'</span><b class="'+
    (x.p>=0?'pos':'neg')+'">'+(x.p>=0?'+':'-')+Math.abs(x.p).toFixed(2)+
    ' $</b></div>').join('');
  }
  lastOk=Date.now();ago();
 }catch(e){document.getElementById('upd').textContent=
  'hors ligne - nouvel essai...'}
}
load();
let pollT=setInterval(load,5000);
setInterval(ago,1000);
document.addEventListener('visibilitychange',()=>{
 clearInterval(pollT);
 if(document.hidden){pollT=setInterval(load,30000);}
 else{load();pollT=setInterval(load,5000);}
});
if('serviceWorker' in navigator){
 navigator.serviceWorker.register(B+'sw.js',{scope:B}).catch(()=>{});}
let dp=null;
if(/iPad|iPhone|iPod/.test(navigator.userAgent)){
 document.getElementById('howto').innerHTML=
  '&#128241; <b>Pour installer sur iPhone :</b><br>'+
  '1. Ouvrez cette page dans <b>Safari</b><br>'+
  '2. Touchez le bouton <b>Partager</b> &#11014;&#65039; en bas<br>'+
  '3. Choisissez <b>&laquo; Sur l&#8217;&eacute;cran d&#8217;accueil'+
  ' &raquo;</b><br>4. L&#8217;ic&ocirc;ne &#129417; appara&icirc;t !';}
if(window.matchMedia('(display-mode: standalone)').matches){
 document.getElementById('inst').style.display='none';}
window.addEventListener('beforeinstallprompt',(e)=>{
 e.preventDefault();dp=e;});
function inst(){
 if(dp){dp.prompt();dp=null;}
 else{const h=document.getElementById('howto');
  h.style.display=(h.style.display==='block')?'none':'block';}}
window.addEventListener('appinstalled',()=>{
 document.getElementById('inst').style.display='none';
 document.getElementById('howto').style.display='none';});
</script></body></html>"""


USERS_FILE = os.path.join(DIR, "owl_nest_users.json")
NEST_DATA = os.path.join(DIR, "nest_data")
CODES_FILE = os.path.join(DIR, "owl_activation_codes.json")
_users_cache = {"t": 0.0, "users": []}


def _load_codes():
    try:
        return json.load(open(CODES_FILE, encoding="utf-8"))
    except Exception:
        return {"codes": []}


def _save_codes(c):
    json.dump(c, open(CODES_FILE, "w", encoding="utf-8"), indent=2)


def new_activation_code():
    """One-time activation code (2026-09-05 user): the master generates
    it in HIS app, sends it to the family member on Telegram; entering
    it activates copying - no operator in the loop. Single use, 24h."""
    import random
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no O/0/I/1
    code = "".join(random.choice(alphabet) for _ in range(6))
    c = _load_codes()
    c["codes"].append({"code": code, "t": time.time(), "used_by": None})
    c["codes"] = c["codes"][-200:]
    _save_codes(c)
    return code


def redeem_activation_code(code, uid):
    c = _load_codes()
    for e in c["codes"]:
        if (e["code"] == code.strip().upper() and not e.get("used_by")
                and time.time() - float(e["t"]) < 86400):
            e["used_by"] = uid
            e["used_t"] = time.time()
            _save_codes(c)
            return True
    return False


def start_copier(uid):
    import subprocess
    pyw = (r"C:\Users\Administrator\AppData\Local\Programs\Python"
           r"\Python311\pythonw.exe")
    subprocess.Popen([pyw, os.path.join(DIR, "owl_copier.py"), uid],
                     cwd=DIR)


def users():
    if time.time() - _users_cache["t"] > 10:
        try:
            _users_cache["users"] = json.load(
                open(USERS_FILE, encoding="utf-8"))
        except Exception:
            pass
        _users_cache["t"] = time.time()
    return _users_cache["users"]


def user_by_token(tok):
    for u in users():
        if u.get("token") == tok:
            return u
    return None


def user_stats(u):
    plan = u.get("plan", "premium")
    if plan == "trial":
        try:
            te = datetime.fromisoformat(u.get("trial_end"))
        except Exception:
            te = datetime.now(timezone.utc)
        left = (te - datetime.now(timezone.utc)).total_seconds()
        if left <= 0:
            return {"expired": True,
                    "updated_utc": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds")}
    fp = os.path.join(NEST_DATA, u["id"] + ".json")
    try:
        d = json.load(open(fp))
        age = os.path.getmtime(fp)
        if time.time() - age > 60:
            d["stale"] = True
        if plan == "trial":
            d["trial_days_left"] = max(0, int(left // 86400) + 1)
        if u.get("id") == "kino":
            try:
                _wx = json.load(open(os.path.join(
                    DIR, "owl_weather.json")))
                d["meteo"] = _wx.get("mode")
                d["meteo_since"] = _wx.get("since")
            except Exception:
                pass
            try:
                _ms = json.load(open(os.path.join(
                    DIR, "owl_milestone.json")))
                if _ms.get("enabled") and _ms.get("milestone"):
                    d["palier"] = float(_ms["milestone"])
            except Exception:
                pass
            try:
                d["trading_paused"] = bool(json.load(open(
                    os.path.join(DIR, "owl_trading_pause.json")))
                    .get("paused"))
            except Exception:
                d["trading_paused"] = False
        try:
            # war-chest ledger (version C): shared strategy state, shown
            # to every user - copiers mirror the same trades
            d["ledger"] = json.load(open(os.path.join(
                DIR, "owl_ledger.json")))
        except Exception:
            pass
        if u.get("id") == "kino" or str(u.get("login")) == str(LOGIN):
            d["is_master"] = True
        elif not u.get("trade"):
            d["activation_needed"] = True
        if u.get("id") != "kino" and u.get("trade"):
            # family member whose real account the bot trades: their
            # own pause switch (2026-09-05)
            try:
                d["trading_paused"] = bool(json.load(open(os.path.join(
                    DIR, f"owl_trading_pause_{u['id']}.json")))
                    .get("paused"))
            except Exception:
                d["trading_paused"] = False
        return d
    except Exception:
        # fall back to the built-in kino stats while the worker warms up
        if u.get("id") == "kino":
            return stats()
        return {"error": "patientez, connexion en cours..."}


FAMILY_CODE = "kino"

JOIN_PAGE = """<!doctype html><html lang="fr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="google" content="notranslate">
<meta name="theme-color" content="#0b0f14">
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/icon192.png">
<title>OwlNest</title>
<style>
*{box-sizing:border-box;margin:0}
body{background:#0b0f14;color:#e8eef4;padding:0 0 44px;overflow-x:hidden;
 font-family:-apple-system,'Segoe UI',Roboto,sans-serif}
.bg{position:fixed;inset:0;z-index:-1;overflow:hidden}
.blob{position:absolute;width:420px;height:420px;border-radius:50%;
 filter:blur(90px);opacity:.35}
.bl1{background:#1d4ed8;top:-140px;left:-120px;
 animation:dr 14s ease-in-out infinite alternate}
.bl2{background:#0e7a5f;bottom:-160px;right:-140px;
 animation:dr 17s ease-in-out infinite alternate-reverse}
@keyframes dr{0%{transform:translate(0,0)}100%{transform:translate(60px,40px)}}
.wrap{max-width:440px;margin:0 auto;padding:0 18px}
.hero{text-align:center;padding:44px 0 8px}
.ring{width:96px;height:96px;margin:0 auto;border-radius:50%;
 display:flex;align-items:center;justify-content:center;font-size:2.9rem;
 background:radial-gradient(circle at 35% 30%,#1b3a5f,#0f2740);
 box-shadow:0 0 40px rgba(37,99,235,.45),inset 0 0 18px rgba(0,0,0,.4);
 animation:fl 3.4s ease-in-out infinite}
@keyframes fl{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
h1{font-size:2rem;font-weight:800;margin-top:16px;letter-spacing:.5px}
.tag{color:#9fc2de;font-size:1rem;margin-top:8px;line-height:1.6}
.preview{margin:30px auto 0;background:linear-gradient(150deg,
 #16202e 0%,#121a26 100%);border:1px solid #24344a;border-radius:22px;
 padding:20px 18px;box-shadow:0 18px 44px rgba(0,0,0,.5);
 transform:rotate(-1.6deg);max-width:340px;text-align:center}
.pv-lbl{font-size:.68rem;color:#6f93b5;text-transform:uppercase;
 letter-spacing:.1em}
.pv-money{font-size:2.2rem;font-weight:800;margin-top:5px}
.pv-eur{color:#9fc2de;font-size:.95rem}
.pv-row{display:flex;justify-content:space-around;margin-top:12px;
 font-size:.85rem}
.pv-chip{background:rgba(46,204,113,.12);color:#2ecc71;font-weight:700;
 border-radius:999px;padding:5px 12px}
.pv-chip2{background:rgba(37,99,235,.14);color:#7fb0ff;font-weight:700;
 border-radius:999px;padding:5px 12px}
.pv-bot{margin-top:13px;font-size:.82rem;color:#c6d3df}
.feats{margin-top:34px}
.fr{display:flex;align-items:center;gap:14px;background:#141c28;
 border:1px solid #1f2c3d;border-radius:16px;padding:14px 16px;
 margin-top:12px}
.fi{width:42px;height:42px;border-radius:12px;display:flex;flex:none;
 align-items:center;justify-content:center;font-size:1.3rem;
 background:#0f2740}
.ft b{display:block;font-size:.98rem}
.ft span{font-size:.8rem;color:#8fa1b3;line-height:1.45}
.bigbtn{display:block;width:100%;margin-top:16px;border:0;
 border-radius:16px;padding:19px;font-size:1.12rem;font-weight:700;
 text-align:center;cursor:pointer}
.bigbtn:active{transform:scale(.98)}
.b1{background:linear-gradient(135deg,#2563eb,#5b3fd4);color:#fff;
 box-shadow:0 10px 26px rgba(37,99,235,.35);margin-top:32px}
.b2{background:#151d29;color:#c6d3df;border:1.5px solid #263341}
.view{display:none}
.view.on{display:block}
.card{background:#151d29;border-radius:20px;padding:22px 18px;
 box-shadow:0 6px 18px rgba(0,0,0,.35);margin-top:22px}
.back{color:#5f7185;text-decoration:none;font-size:.95rem;
 display:inline-block;margin:18px 0 0 4px;cursor:pointer}
h2{font-size:1.25rem;margin-bottom:4px}
label{display:block;margin:16px 0 7px;color:#9db0c2;font-size:.92rem;
 font-weight:600}
input{width:100%;padding:15px;border-radius:12px;border:1.5px solid
 #263341;background:#0f1620;color:#e8eef4;font-size:1.05rem}
input:focus{outline:none;border-color:#2563eb}
button.go{width:100%;margin-top:24px;background:#2563eb;color:#fff;
 border:0;border-radius:14px;padding:17px;font-size:1.1rem;
 font-weight:700}
.note{background:#0d2417;border:1px solid #1d4a2f;border-radius:14px;
 padding:14px;font-size:.88rem;color:#7fd6a0;margin-top:18px;
 line-height:1.5}
.pfoot{margin-top:34px;text-align:center;font-size:.75rem;color:#3d4c5c}
</style></head><body>
<div class="bg"><div class="blob bl1"></div><div class="blob bl2"></div></div>
<div class="wrap">

<div class="view on" id="v-home">
<div class="hero">
<div class="ring">&#129417;</div>
<h1>OwlNest</h1>
<div class="tag">Le robot Owl trade pour vous,<br>
jour et nuit. Vous, vous regardez.</div>
</div>
<div class="preview">
<div class="pv-lbl">Aper&ccedil;u en direct</div>
<div class="pv-money">1 234,56 $</div>
<div class="pv-eur">&asymp; 1 062 &euro;</div>
<svg viewBox="0 0 260 44" style="width:100%;height:44px;margin-top:10px">
<defs><linearGradient id="pg" x1="0" y1="0" x2="0" y2="1">
<stop offset="0%" stop-color="#2ecc71" stop-opacity=".35"/>
<stop offset="100%" stop-color="#2ecc71" stop-opacity="0"/>
</linearGradient></defs>
<polygon fill="url(#pg)" points="0,44 0,34 30,30 60,33 90,24 120,27
 150,18 180,21 210,12 240,15 260,7 260,44"/>
<polyline fill="none" stroke="#2ecc71" stroke-width="2.5"
 stroke-linecap="round" stroke-linejoin="round"
 points="0,34 30,30 60,33 90,24 120,27 150,18 180,21 210,12 240,15 260,7"/>
</svg>
<div class="pv-row"><span class="pv-chip">&#9650; +23,40 $
 aujourd&#8217;hui</span>
<span class="pv-chip2">2 trades</span></div>
<div class="pv-bot">&#129302; L&#8217;Owl vient de gagner un trade
 pour vous</div>
</div>
<div class="feats">
<div class="fr"><div class="fi">&#129302;</div>
<div class="ft"><b>L&#8217;Owl trade pour vous</b>
<span>Vous connectez votre compte, le robot fait tout : entr&eacute;es,
 sorties, protections. Z&eacute;ro effort.</span></div></div>
<div class="fr"><div class="fi">&#128200;</div>
<div class="ft"><b>Vous regardez tout en direct</b>
<span>Solde, gains du jour, combats du robot &mdash; mis &agrave; jour
 toutes les 5 secondes.</span></div></div>
<div class="fr"><div class="fi">&#127873;</div>
<div class="ft"><b>7 jours d&#8217;essai, z&eacute;ro risque</b>
<span>L&#8217;essai se fait sur un compte d&eacute;mo : argent fictif,
 vraies performances.</span></div></div>
</div>
<button class="bigbtn b1" onclick="show('v-login')">
Se connecter</button>
<button class="bigbtn b2" id="inst2" onclick="inst2()"
 style="margin-top:12px">&#128241; Installer l&#8217;application</button>
<div id="howto2" style="display:none;margin-top:12px;background:#141c28;
 border:1px solid #1f2c3d;border-radius:14px;padding:14px;
 font-size:.9rem;color:#c6d3df;line-height:1.6;text-align:left">
&#128241; <b>Pour installer :</b><br>
1. Touchez le menu <b>&#8942;</b> en haut &agrave; droite de Chrome<br>
2. Choisissez <b>&laquo; Ajouter &agrave; l&#8217;&eacute;cran
 d&#8217;accueil &raquo;</b><br>
3. L&#8217;ic&ocirc;ne &#129417; appara&icirc;t !</div>
<div class="pfoot">&#129417; OwlNest &middot; fait avec amour
 par la famille Kino</div>
</div>

<div class="view" id="v-login">
<a class="back" onclick="show('v-home')">&#8592; Retour</a>
<form class="card" method="POST" action="login">
<h2>Se connecter</h2>
<div style="color:#9aa7b4;font-size:.85rem">Compte connu : vous entrez
 directement. Nouveau compte : on vous demande juste une info de plus.
</div>
<label>Num&eacute;ro de compte MT5</label>
<input name="login" required inputmode="numeric" placeholder="12345678">
<label>Mot de passe du compte</label>
<input name="password" required placeholder="votre mot de passe">
<button class="go">Continuer &#10142;</button>
</form>
</div>

</div><script>
function show(id){
 document.querySelectorAll('.view').forEach(v=>v.classList.remove('on'));
 document.getElementById(id).classList.add('on');
 window.scrollTo(0,0);
}
let dp2=null;
if('serviceWorker' in navigator){
 navigator.serviceWorker.register('/sw.js',{scope:'/'}).catch(()=>{});}
if(window.matchMedia('(display-mode: standalone)').matches){
 document.getElementById('inst2').style.display='none';}
window.addEventListener('beforeinstallprompt',(e)=>{
 e.preventDefault();dp2=e;});
function inst2(){
 if(dp2){dp2.prompt();dp2=null;}
 else{const h=document.getElementById('howto2');
  h.style.display=(h.style.display==='block')?'none':'block';}}
window.addEventListener('appinstalled',()=>{
 document.getElementById('inst2').style.display='none';});
</script></body></html>"""


def _join_result(title, body_html):
    return ("<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,"
            "initial-scale=1\"><title>OwlNest</title>"
            "<style>body{background:#0b0f14;color:#e8eef4;margin:0;"
            "padding:40px 20px;font-family:-apple-system,'Segoe UI',Roboto,"
            "sans-serif;text-align:center}a{color:#2563eb;font-size:1.15rem;"
            "word-break:break-all}.k{background:#151d29;border-radius:20px;"
            "box-shadow:0 6px 18px rgba(0,0,0,.35);padding:26px 20px;"
            "max-width:420px;margin:0 auto;line-height:1.6}"
            "</style></head><body><div class=\"k\">"
            f"<h2>{title}</h2>{body_html}</div></body></html>")


def _step2_page(login, pwd):
    """Smart login step 2 (2026-09-06 user): the account is new - ask
    ONLY the missing pieces (first name + server)."""
    import html as _h
    return ("<!doctype html><html lang=\"fr\"><head>"
            "<meta charset=\"utf-8\"><meta name=\"viewport\" "
            "content=\"width=device-width,initial-scale=1\">"
            "<title>OwlNest</title><style>body{background:#0b0f14;"
            "color:#e8eef4;margin:0;padding:34px 20px;font-family:"
            "-apple-system,'Segoe UI',Roboto,sans-serif}.k{background:"
            "#151d29;border-radius:20px;padding:24px 20px;max-width:"
            "420px;margin:0 auto;box-shadow:0 6px 18px rgba(0,0,0,.35)}"
            "label{display:block;margin:16px 0 7px;color:#9db0c2;"
            "font-size:.92rem;font-weight:600}input{width:100%;"
            "box-sizing:border-box;padding:15px;border-radius:12px;"
            "border:1.5px solid #263341;background:#0f1620;color:"
            "#e8eef4;font-size:1.05rem}button{width:100%;margin-top:"
            "22px;background:#2563eb;color:#fff;border:0;border-radius:"
            "14px;padding:17px;font-size:1.1rem;font-weight:700}"
            "</style></head><body><div class=\"k\">"
            "<h2>&#129417; Nouveau compte !</h2>"
            "<p style=\"color:#9aa7b4;font-size:.9rem;line-height:1.5\">"
            f"Le compte <b>{_h.escape(login)}</b> n&#8217;est pas encore "
            "dans le nid. Deux petites infos et c&#8217;est fait :</p>"
            "<form method=\"POST\" action=\"/register\">"
            f"<input type=\"hidden\" name=\"login\" "
            f"value=\"{_h.escape(login)}\">"
            f"<input type=\"hidden\" name=\"password\" "
            f"value=\"{_h.escape(pwd)}\">"
            "<label>Votre pr&eacute;nom</label>"
            "<input name=\"name\" required maxlength=\"30\" "
            "placeholder=\"Marie\">"
            "<label>Serveur MT5 (visible dans votre app Exness)</label>"
            "<input name=\"server\" required list=\"srv\" "
            "placeholder=\"Exness-MT5Real9\">"
            "<datalist id=\"srv\">"
            "<option value=\"Exness-MT5Real9\">"
            "<option value=\"Exness-MT5Real14\">"
            "<option value=\"Exness-MT5Trial9\">"
            "<option value=\"Exness-MT5Trial10\"></datalist>"
            "<button>Cr&eacute;er mon nid &#10142;</button></form>"
            "</div></body></html>")


def handle_login(form):
    """Smart login (2026-09-06 user): one page for everyone.
    Known account+password -> straight in. Known account, wrong
    password -> error. Unknown account -> step 2 (auto-register)."""
    import re as _re
    login = _re.sub(r"\D", "", form.get("login", [""])[0] or "")[:12]
    pwd = (form.get("password", [""])[0] or "").strip()[:64]
    if not (login and pwd):
        return ("page", _join_result("&#10060; Il manque une info",
                                     "<p>Compte et mot de passe.</p>"))
    u = next((x for x in users()
              if str(x.get("login")) == login
              or str(x.get("mt5_login") or "") == login), None)
    if u is not None:
        if (u.get("mt5_password") or "") == pwd:
            return ("redirect", f"https://owltrader.duckdns.org/"
                                f"{u['token']}/")
        return ("page", _join_result(
            "&#128274; Mot de passe incorrect",
            "<p>Ce compte existe d&eacute;j&agrave; dans le nid, mais "
            "le mot de passe ne correspond pas.</p>"
            "<p><a href=\"/\">R&eacute;essayer</a></p>"))
    return ("page", _step2_page(login, pwd))


def handle_register(form):
    """Auto-registration from the smart login. Credentials are
    validated by the worker actually logging in; failures are cleaned
    up by the nest manager (user + terminal removed)."""
    import re as _re
    import secrets as _sec
    login = _re.sub(r"\D", "", form.get("login", [""])[0] or "")[:12]
    pwd = (form.get("password", [""])[0] or "").strip()[:64]
    name = (form.get("name", [""])[0] or "").strip()[:30]
    server = (form.get("server", [""])[0] or "").strip()[:48]
    if not (login and pwd and name and server):
        return _join_result("&#10060; Il manque une info",
                            "<p>Toutes les cases sont requises.</p>")
    us = json.load(open(USERS_FILE, encoding="utf-8"))
    if len(us) >= 12:
        return _join_result("&#128679; Nid complet",
                            "<p>Contactez Kino pour une place.</p>")
    if any(str(x.get("login")) == login
           or str(x.get("mt5_login") or "") == login for x in us):
        return _join_result("&#9888;&#65039; D&eacute;j&agrave; inscrit",
                            "<p>Ce compte existe. <a href=\"/\">"
                            "Connectez-vous</a>.</p>")
    uid = "u" + login
    _is_demo = "trial" in server.lower() or "demo" in server.lower()
    rec = {
        "id": uid, "name": name,
        "token": _sec.token_urlsafe(9),
        "login": int(login), "mt5_login": int(login),
        "mt5_password": pwd, "mt5_server": server,
        "era_start": datetime.now(timezone.utc)
        .isoformat(timespec="seconds"),
        "symbol": "BTCUSDm",
        "plan": "trial" if _is_demo else "premium",
        "pending_since": time.time(),
    }
    if _is_demo:
        rec["trial_end"] = (datetime.now(timezone.utc)
                            + timedelta(days=7)) \
            .isoformat(timespec="seconds")
    us.append(rec)
    json.dump(us, open(USERS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    _users_cache["t"] = 0.0
    link = f"https://owltrader.duckdns.org/{rec['token']}/"
    return _join_result(
        "&#129417; Nid en pr&eacute;paration !",
        f"<p>Bienvenue {name} ! Votre espace se construit "
        "(environ 2 minutes).</p>"
        f"<p><a href=\"{link}\">Ouvrir mon OwlNest</a></p>"
        "<p style=\"color:#8fa1b3;font-size:.85rem\">Si les "
        "identifiants sont incorrects, la page vous le dira et "
        "l&#8217;essai sera nettoy&eacute; automatiquement.</p>")


def handle_join(form):
    import re as _re
    code = (form.get("code", [""])[0] or "").strip().lower()
    if code != FAMILY_CODE:
        return _join_result("&#10060; Code famille incorrect",
                           "<p>Demandez le mot secret &agrave; Kino.</p>")
    name = (form.get("name", [""])[0] or "").strip()[:30]
    login = _re.sub(r"\D", "", form.get("login", [""])[0] or "")[:12]
    pwd = (form.get("password", [""])[0] or "").strip()[:64]
    server = (form.get("server", [""])[0] or "").strip()[:48]
    if not (name and login and pwd and server):
        return _join_result("&#10060; Il manque une information",
                           "<p>Revenez en arri&egrave;re et remplissez "
                           "toutes les cases.</p>")
    _srv = server.lower()
    _is_demo = ("trial" in _srv) or ("demo" in _srv)
    _plan = "trial"
    if not _is_demo:
        _invite = (form.get("invite", [""])[0] or "").strip().upper()
        _ipath = os.path.join(DIR, "owl_invites.json")
        try:
            _iv = json.load(open(_ipath, encoding="utf-8"))
        except Exception:
            _iv = {"codes": {}}
        _c0 = _iv.get("codes", {}).get(_invite)
        if not _invite or _c0 is None or _c0.get("used"):
            return _join_result(
                "&#11088; Compte r&eacute;el = famille ou Premium",
                "<p>Commencez avec un <b>compte d&eacute;mo</b> (7 jours "
                "d&#8217;essai gratuit) &mdash; ou demandez un <b>code "
                "d&#8217;invitation</b> &agrave; Kino si vous &ecirc;tes "
                "de la famille.</p>")
        _c0["used"] = True
        _c0["used_by"] = login
        json.dump(_iv, open(_ipath, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        _plan = "family"
    base = _re.sub(r"[^a-z0-9]", "", name.lower()) or "membre"
    try:
        us = json.load(open(USERS_FILE, encoding="utf-8"))
    except Exception:
        us = []
    uid = base
    n = 1
    while any(u.get("id") == uid for u in us):
        n += 1
        uid = f"{base}{n}"
    token = uid + secrets.token_hex(2)
    us.append({
        "id": uid, "name": name, "token": token,
        "terminal": "",
        "login": int(login),
        "mt5_login": int(login), "mt5_password": pwd, "mt5_server": server,
        "era_start": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbol": "BTCUSDm", "bot_only": False,
        "plan": _plan,
        "trading": True,
        "trial_end": (None if _plan == "family" else
                      (datetime.now(timezone.utc)
                       + timedelta(days=7)).isoformat(timespec="seconds")),
    })
    json.dump(us, open(USERS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    _users_cache["t"] = 0.0
    link = f"https://owltrader.duckdns.org/{token}/"
    return _join_result(
        "&#127881; Bienvenue dans le nid, " + name + " !",
        "<p>Votre OwlNest se pr&eacute;pare (2-3 minutes).</p>"
        "<p>&#127873; Essai gratuit : <b>7 jours</b>.</p>"
        f"<p>Votre lien personnel :</p><p><a href=\"{link}\">{link}</a></p>"
        "<p style=\"color:#9aa7b4;font-size:.85rem\">Gardez-le "
        "pr&eacute;cieusement et ajoutez-le &agrave; votre &eacute;cran "
        "d&#8217;accueil.</p>")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        p = self.path.split("?")[0].rstrip("/")
        _parts = [x for x in p.split("/") if x]
        # token-gated user actions (2026-09-05 user): pause the robot's
        # trading on THIS account / delete the account from the bot.
        if len(_parts) == 2 and _parts[1] in ("push_sub", "push_unsub"):
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                sub = json.loads(self.rfile.read(ln)
                                 .decode("utf-8", "replace"))
                ep = (sub or {}).get("endpoint")
                subs = _load_subs()
                lst = [s for s in subs.get(u["id"], [])
                       if s.get("endpoint") != ep]
                if _parts[1] == "push_sub" and ep:
                    lst.append(sub)
                subs[u["id"]] = lst
                _save_subs(subs)
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "activate":
            # family member enters the one-time code from Kino
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(ln).decode("utf-8", "replace")
                import urllib.parse as _up
                code = (_up.parse_qs(body).get("code", [""])[0] or "")
                if not redeem_activation_code(code, u["id"]):
                    self._send(json.dumps({"ok": False,
                                           "err": "bad code"}),
                               "application/json")
                    return
                us = json.load(open(USERS_FILE, encoding="utf-8"))
                for x in us:
                    if x.get("id") == u["id"]:
                        x["trade"] = True
                json.dump(us, open(USERS_FILE, "w", encoding="utf-8"),
                          indent=2)
                _users_cache["t"] = 0.0
                start_copier(u["id"])
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "actcode":
            # the master generates a fresh one-time code (password-gated)
            u = user_by_token(_parts[0])
            if u is None or str(u.get("login")) != str(LOGIN):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(ln).decode("utf-8", "replace")
                import urllib.parse as _up
                _pw = (_up.parse_qs(body).get("pwd", [""])[0] or "").strip()
                if not u.get("mt5_password") or _pw != u["mt5_password"]:
                    self._send(json.dumps({"ok": False,
                                           "err": "bad password"}),
                               "application/json")
                    return
                self._send(json.dumps({"ok": True,
                                       "code": new_activation_code()}),
                           "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 2 and _parts[1] in ("pause", "delete"):
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            # both actions need the account's broker password (2026-09-05)
            ln = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(ln).decode("utf-8", "replace")
            import urllib.parse as _up
            _form = _up.parse_qs(body)
            _pwd = (_form.get("pwd", [""])[0] or "").strip()
            _real = (u.get("mt5_password") or "").strip()
            if not _real or _pwd != _real:
                self._send(json.dumps({"ok": False,
                                       "err": "bad password"}),
                           "application/json")
                return
            # per-user pause file: the main account keeps the global
            # name (the live bot reads it); family bots read
            # owl_trading_pause_<uid>.json (2026-09-05, family real)
            _pp = ("owl_trading_pause.json"
                   if str(u.get("login")) == str(LOGIN)
                   else f"owl_trading_pause_{u['id']}.json")
            if _parts[1] == "pause":
                try:
                    on = (_form.get("on", ["1"])[0] == "1")
                    if (str(u.get("login")) == str(LOGIN)
                            or u.get("trade")):
                        json.dump({"paused": on, "by": u["id"],
                                   "t": time.time()},
                                  open(os.path.join(DIR, _pp), "w"))
                    self._send(json.dumps({"ok": True, "paused": on}),
                               "application/json")
                except Exception as e:
                    self._send(json.dumps({"ok": False, "err": str(e)}),
                               "application/json")
                return
            try:                                   # delete
                us = json.load(open(USERS_FILE, encoding="utf-8"))
                us = [x for x in us
                      if x.get("token") != u.get("token")]
                json.dump(us, open(USERS_FILE, "w", encoding="utf-8"),
                          indent=2)
                _users_cache["t"] = 0.0
                if str(u.get("login")) == str(LOGIN) or u.get("trade"):
                    json.dump({"paused": True, "by": u["id"],
                               "t": time.time()},
                              open(os.path.join(DIR, _pp), "w"))
                try:
                    os.remove(os.path.join(NEST_DATA,
                                           u["id"] + ".json"))
                except Exception:
                    pass
                self._send(json.dumps({"ok": True}),
                           "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if p.endswith("/login") or p.endswith("/register"):
            try:
                ln = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(ln).decode("utf-8", "replace")
                import urllib.parse as _up
                form = _up.parse_qs(body)
                if p.endswith("/login"):
                    kind, val = handle_login(form)
                    if kind == "redirect":
                        self.send_response(302)
                        self.send_header("Location", val)
                        self.end_headers()
                    else:
                        self._send(val, "text/html; charset=utf-8")
                else:
                    self._send(handle_register(form),
                               "text/html; charset=utf-8")
            except Exception as e:
                self._send(_join_result("&#9888;&#65039; Petit souci",
                                        f"<p>{e}</p>"),
                           "text/html; charset=utf-8")
            return
        if p.endswith("/find"):
            try:
                ln = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(ln).decode("utf-8", "replace")
                import urllib.parse as _up
                import re as _re
                form = _up.parse_qs(body)
                pwd = (form.get("password", [""])[0] or "").strip()
                login = _re.sub(r"\D", "", form.get("login", [""])[0] or "")
                u = None
                if login and pwd:
                    u = next((x for x in users()
                              if str(x.get("login")) == login
                              and x.get("mt5_password")
                              and x.get("mt5_password") == pwd), None)
                if u is None:
                    self._send(_join_result(
                        "&#128269; Introuvable",
                        "<p>Compte inconnu ou code incorrect. "
                        "V&eacute;rifiez, ou inscrivez-vous "
                        "ci-dessous.</p>"), "text/html; charset=utf-8")
                else:
                    link = (f"https://owltrader.duckdns.org/"
                            f"{u['token']}/")
                    self.send_response(302)
                    self.send_header("Location", link)
                    self.end_headers()
            except Exception as e:
                self._send(_join_result("&#9888;&#65039; Petit souci",
                                        f"<p>{e}</p>"),
                           "text/html; charset=utf-8")
            return
        if not p.endswith("/join"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            ln = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(ln).decode("utf-8", "replace")
            import urllib.parse as _up
            form = _up.parse_qs(body)
            self._send(handle_join(form), "text/html; charset=utf-8")
        except Exception as e:
            self._send(_join_result("&#9888;&#65039; Petit souci",
                                    f"<p>{e}</p>"),
                       "text/html; charset=utf-8")

    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/")
        parts = [x for x in p.split("/") if x]
        if parts and parts[0] == "manifest.json":
            self._send(MANIFEST, "application/manifest+json")
            return
        if parts and parts[0] == "sw.js":
            self._send(SW, "text/javascript")
            return
        if parts and parts[0] == "icon192.png":
            self._send(ICON192, "image/png")
            return
        if parts and parts[0] == "icon512.png":
            self._send(ICON512, "image/png")
            return
        if not parts or parts[0] == "join":
            # front door: no token -> the welcome/sign-up screen
            self._send(JOIN_PAGE, "text/html; charset=utf-8")
            return
        user = user_by_token(parts[0])
        if user is None:
            self.send_response(404)
            self.end_headers()
            return
        sub = parts[1] if len(parts) > 1 else ""
        if sub == "":
            page = PAGE.replace("%%NAME%%", user.get("name", ""))
            self._send(page, "text/html; charset=utf-8")
        elif sub == "api":
            self._send(json.dumps(user_stats(user)), "application/json")
        elif sub == "push_key":
            self._send(json.dumps(
                {"key": (_VAPID or {}).get("public_key")}),
                "application/json")
        elif sub == "manifest.json":
            self._send(MANIFEST, "application/manifest+json")
        elif sub == "sw.js":
            self._send(SW, "text/javascript")
        elif sub == "icon192.png":
            self._send(ICON192, "image/png")
        elif sub == "icon512.png":
            self._send(ICON512, "image/png")
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    print(f"OwlNest v2 serving on port {PORT}, token {TOKEN}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
