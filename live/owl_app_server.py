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
LOGIN = 223985697          # 2026-09-07: the Pro master account
                           # (was 134499778 - stale after the account
                           # move; master gates were keying on the
                           # wrong login)
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
    "self.addEventListener('fetch',e=>{"
    "if(e.request.mode==='navigate'){"
    "e.respondWith(fetch(e.request).then(r=>{"
    "const cp=r.clone();"
    "caches.open('owl1').then(c=>c.put(e.request,cp));"
    "return r;}).catch(()=>caches.match(e.request)));}});"
    "self.addEventListener('push',e=>{let d={};"
    "try{d=e.data.json()}catch(x){}"
    "e.waitUntil(self.registration.showNotification("
    "d.title||'OwlNest',{body:d.body||'',icon:'icon192.png',"
    "badge:'icon192.png',tag:d.tag||'owl',renotify:true,"
    "vibrate:[80,40,80]}));});"
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


PUSH_PREFS_FILE = os.path.join(DIR, "owl_push_prefs.json")


def _load_subs():
    try:
        return json.load(open(PUSH_SUBS_FILE))
    except Exception:
        return {}


def _save_subs(s):
    json.dump(s, open(PUSH_SUBS_FILE, "w"))


_rl = {}   # brute-force limiter: key -> [fail timestamps]


def rate_limited(key, limit=5, window=600):
    now = time.time()
    _rl[key] = [t for t in _rl.get(key, []) if now - t < window]
    return len(_rl[key]) >= limit


def rate_fail(key):
    _rl.setdefault(key, []).append(time.time())


def is_admin(u):
    """Both of the owner's pages (Pro master + manual Standard)."""
    return u is not None and (u.get("id") in ("kino", "std")
                              or str(u.get("login")) == str(LOGIN))


def master_pwd_ok(pw):
    """Master actions always validate against the KINO record's
    broker password, whichever admin page they come from."""
    k = next((x for x in users() if x.get("id") == "kino"), None)
    return k is not None and pwd_ok(k, pw)


def pwd_ok(u, pw):
    """Broker-password check with 5-fails-per-10-min lockout."""
    key = ("pwd", u.get("id"))
    if rate_limited(key):
        return False
    if pw and (u.get("mt5_password") or "") == pw:
        return True
    rate_fail(key)
    return False

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
.tab.on{display:block;animation:tfade .25s ease}
@keyframes tfade{0%{opacity:0;transform:translateY(6px)}
 100%{opacity:1;transform:none}}
.card,.panel,.status{animation:cin .5s ease backwards}
.grid .card:nth-child(2){animation-delay:.06s}
.grid .card:nth-child(3){animation-delay:.12s}
.grid .card:nth-child(4){animation-delay:.18s}
@keyframes cin{0%{opacity:0;transform:translateY(10px)}
 100%{opacity:1;transform:none}}
.tabbar{position:fixed;left:0;right:0;bottom:0;z-index:30;
 display:flex;max-width:480px;margin:0 auto;
 background:rgba(15,22,32,.94);backdrop-filter:blur(12px);
 border-top:1px solid #1e2937;border-radius:18px 18px 0 0;
 padding:6px 8px calc(8px + env(safe-area-inset-bottom,0px))}
.tb{flex:1;background:none;border:0;color:#5f7185;font-size:.68rem;
 font-weight:600;display:flex;flex-direction:column;
 align-items:center;gap:3px;padding:6px 0;border-radius:12px}
.tb span{font-size:1.3rem;line-height:1}
.tb.on{color:#8fc6ff;background:rgba(127,179,224,.12)}
.srow{display:flex;align-items:center;gap:13px;padding:13px 2px;
 border-bottom:1px solid #1e2937;cursor:pointer;color:#e8eef4}
.srow:last-child{border-bottom:0}
.srow b{font-weight:600;font-size:.97rem}
.sic{width:38px;height:38px;border-radius:11px;background:#0f2740;
 display:flex;align-items:center;justify-content:center;
 font-size:1.15rem;flex:none}
.chv{color:#3d4c5c;font-size:1.3rem;line-height:1}
.ssub{font-size:.76rem;color:#5f7185;margin-top:2px}
.hero{background:linear-gradient(165deg,#0f2740 0%,#14406b 100%);
 color:#fff;padding:22px 22px 38px;border-radius:0 0 30px 30px;
 text-align:center;box-shadow:0 8px 24px rgba(0,0,0,.35);
 position:relative;overflow:hidden}
#spark{position:absolute;left:0;right:0;bottom:0;width:100%;
 height:64px;opacity:.3;pointer-events:none}
.hero>*{position:relative}
#daychip{display:none;margin-top:8px;font-size:.74rem;
 font-weight:700;padding:4px 12px;border-radius:99px;
 font-variant-numeric:tabular-nums}
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
.status{background:linear-gradient(160deg,#131e2e,#101927);
 border:1px solid #1f3145;border-radius:18px;padding:16px;
 text-align:center;font-size:1.04rem;color:#c6d3df;
 box-shadow:0 6px 18px rgba(0,0,0,.3)}
.panel{background:linear-gradient(160deg,#131e2e,#101927);
 border:1px solid #1f3145;border-radius:18px;padding:16px;
 box-shadow:0 6px 18px rgba(0,0,0,.3)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
.card{background:linear-gradient(160deg,#131e2e,#101927);
 border:1px solid #1f3145;border-radius:18px;padding:18px 10px 15px;
 text-align:center;box-shadow:0 6px 18px rgba(0,0,0,.3)}
.empty{text-align:center;padding:26px 10px;color:#4d5f73}
.empty i{font-style:normal;font-size:1.7rem;display:block}
.empty p{font-size:.85rem;margin-top:7px}
.lbl{font-size:.74rem;color:#8fa1b3;text-transform:uppercase;
 letter-spacing:.06em;font-weight:600}
.val{font-size:1.45rem;font-weight:800;margin-top:8px;
 white-space:nowrap}
.sub{font-size:.72rem;color:#5f7185;margin-top:6px}
.pos{color:#2ecc71}.neg{color:#ff5c5c}.neu{color:#e8eef4}
.sec{margin:26px 8px 10px;color:#5f7185;font-weight:700;
 font-size:.68rem;text-transform:uppercase;letter-spacing:.09em;
 text-align:left}
.sec .hint{opacity:.65;letter-spacing:.02em;text-transform:none;
 font-weight:500}
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
@keyframes ipulse{0%{box-shadow:0 0 0 0 rgba(127,179,224,.45)}
 70%{box-shadow:0 0 0 8px rgba(127,179,224,0)}
 100%{box-shadow:0 0 0 0 rgba(127,179,224,0)}}
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
#tourbg{position:fixed;inset:0;background:rgba(4,8,14,.72);
 display:none;z-index:51}
#tourbx{position:fixed;left:16px;right:16px;z-index:53;display:none;
 background:#16202e;border:1px solid #2a5a80;border-radius:18px;
 padding:18px;box-shadow:0 14px 40px rgba(0,0,0,.6);
 max-width:420px;margin:0 auto}
#tourbx p{color:#dbe7f3;font-size:1rem;line-height:1.6;margin:0}
#tourdots{margin-top:12px;color:#5f7185;letter-spacing:.35em;
 font-size:.8rem}
.tourhl{position:relative;z-index:52;border-radius:16px;
 box-shadow:0 0 0 3px #7fb0ff,0 0 28px rgba(37,99,235,.65)!important}
</style></head><body>
<div class="hero">
<div class="topline"><span class="brand">&#129417; OwlNest</span>
<span style="display:flex;align-items:center;gap:10px">
<a id="chartlink" href="#" title="Graphique en direct"
 style="text-decoration:none;font-size:.95rem;line-height:1;
 background:rgba(232,197,90,.1);border:1px solid rgba(232,197,90,.35);
 border-radius:99px;padding:4px 9px">&#128200;</a>
<span class="live" id="lv"><span class="dot" id="lvd"></span><span
 id="lvt">EN DIRECT</span></span>
<a href="../" style="color:#9fc2de;text-decoration:none;font-size:1.25rem;
 line-height:1" title="Sortir">&#10162;</a></span></div>
<div class="hello" id="hello">Bonjour %%NAME%% &#128075;</div>
<canvas id="spark"></canvas>
<div class="money skel" id="eq">&#8226;&#8226;&#8226;</div>
<div class="eur" id="eqe">&nbsp;</div>
<span id="daychip"></span>
<div class="bankline" id="bank">&nbsp;</div>
<div id="acctline" style="margin-top:8px;font-size:.72rem;
 color:#5f7185">&nbsp;</div>
<div id="palier" style="display:none;margin-top:14px;text-align:left">
 <div style="font-size:.78rem;color:#9fc2de" id="palier-lbl"></div>
 <div style="background:rgba(255,255,255,.15);border-radius:99px;
  height:8px;margin-top:6px"><div id="palier-bar" style="
  transition:width .9s cubic-bezier(.2,.8,.2,1);background:
  #2ecc71;height:8px;border-radius:99px;width:0%"></div></div>
</div>
</div>
<div class="wrap">
<div class="tab on" id="tab-home">
<div id="meteo" class="status" style="margin-top:26px;
 text-align:center;background:#101c2b;border:1px solid #23405e;
 border-radius:16px;padding:14px;color:#cfe3f5;font-size:.95rem;
 line-height:1.5">
 <div style="font-size:.7rem;color:#6f93b5;text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:6px">&Eacute;tat du robot</div>
 <div id="meteo-txt">&#9925; ...</div>
 <div id="st" style="margin-top:9px;border-top:1px solid #1c2a3d;
  padding-top:9px;font-size:.97rem;color:#c6d3df">Connexion...</div>
</div>
<div id="trial" style="display:none;margin-top:10px;text-align:center;
 background:#251d07;border:1px solid #4a3c12;border-radius:14px;
 padding:10px;color:#e8c55a;font-size:.9rem"></div>
<div id="ftcard" style="display:none;margin-top:12px;
 background:linear-gradient(150deg,#132036,#101c2b);
 border:1px solid #2a5a80;border-radius:16px;padding:14px;
 color:#cfe3f5;font-size:.9rem;line-height:1.5">
 <div style="font-size:.7rem;color:#7fb3e0;text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:6px">&#129514; Le grand test
  de la strat&eacute;gie</div>
 <div id="ft-txt"></div>
 <div style="background:rgba(255,255,255,.15);border-radius:99px;
  height:8px;margin-top:8px"><div id="ft-bar" style="height:8px;
  border-radius:99px;width:0%;background:#7fb0ff"></div></div>
 <div id="ft-sub" style="font-size:.76rem;color:#6f93b5;
  margin-top:6px"></div>
</div>
<div id="ledcard" style="display:none;position:relative;margin-top:12px;
 background:#101c2b;border:1px solid #23405e;border-radius:16px;
 padding:14px;color:#cfe3f5;font-size:.92rem;line-height:1.5">
 <button onclick="ledInfo()" aria-label="explications" style="
  position:absolute;right:9px;bottom:9px;width:26px;height:26px;
  border-radius:50%;border:1px solid rgba(127,179,224,.4);
  background:rgba(127,179,224,.12);color:#7fb3e0;font-size:.8rem;
  font-weight:700;font-style:italic;font-family:Georgia,serif;
  cursor:pointer;animation:ipulse 2.6s ease-out infinite">i</button>
 <div id="led-hd" style="font-size:.7rem;color:#6f93b5;
  text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">
  Le rattrapage</div>
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
 <a id="batchart" href="#" style="display:flex;align-items:center;
  justify-content:center;gap:7px;margin-top:10px;padding:9px;
  border-radius:12px;text-decoration:none;color:#9fd4ff;
  font-size:.8rem;font-weight:700;
  background:rgba(127,179,224,.1);
  border:1px solid rgba(127,179,224,.3)">&#128200; Suivre sur le
  graphique en direct</a>
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
<div class="sec" style="display:flex;justify-content:space-between;
 align-items:center">Progression
 <span><button class="cvc" data-c="7" style="border:1px solid #2a5a80;
  background:#1d3350;color:#cfe3f5;border-radius:99px;padding:4px 12px;
  font-size:.72rem;font-weight:700">7 j</button>
 <button class="cvc" data-c="30" style="border:1px solid #263341;
  background:#0f1620;color:#8fa1b3;border-radius:99px;padding:4px 12px;
  font-size:.72rem;font-weight:700;margin-left:6px">30 j</button></span>
</div>
<div class="panel"><svg id="spark" viewBox="0 0 300 70"
 style="width:100%;height:70px"></svg></div>
</div>
<div class="tab" id="tab-hist">
<div class="sec" style="margin-top:26px">Jour par jour
 <span class="hint">&middot; touchez un jour</span></div>
<div class="panel" id="days" style="display:none"></div>
<div class="sec" id="msum-sec" style="display:none">R&eacute;sum&eacute;
 du mois</div>
<div class="grid" id="msum" style="display:none;margin-top:2px"></div>
<div class="sec" id="cal-sec" style="display:none">Calendrier du mois
</div>
<div class="panel" id="cal" style="display:none"></div>
<div class="sec" id="statx-sec" style="display:none">Statistiques
 &middot; 30 derniers trades</div>
<div class="panel" id="statx" style="display:none"></div>
<div class="sec" id="fights-sec" style="display:none">&#9876;&#65039;
 Combats des soldats</div>
<div class="panel" id="fights" style="display:none"></div>
<div class="sec">Derniers trades</div>
<div class="panel" id="hist">
<div class="row"><span class="skel" style="width:42%">&nbsp;</span>
<span class="skel" style="width:18%">&nbsp;</span></div>
<div class="row"><span class="skel" style="width:36%">&nbsp;</span>
<span class="skel" style="width:22%">&nbsp;</span></div>
<div class="row"><span class="skel" style="width:46%">&nbsp;</span>
<span class="skel" style="width:16%">&nbsp;</span></div></div>
<button id="sharebtn" onclick="shareWeek()" style="width:100%;
 margin-top:18px;background:linear-gradient(135deg,#2563eb,#5b3fd4);
 color:#fff;border:0;border-radius:14px;padding:15px;font-size:1rem;
 font-weight:700">&#128228; Partager ma semaine</button>
</div>
<div class="tab" id="tab-set">
<div class="sec" style="margin-top:26px">Notifications</div>
<div class="panel" style="padding:4px 14px">
 <div class="srow" id="notifbtn" style="display:none">
  <div class="sic">&#128276;</div>
  <div style="flex:1"><b id="notif-lbl">Notifications</b>
   <div class="ssub">Gains, orages et soldats sur votre
    t&eacute;l&eacute;phone</div></div>
  <span class="chv">&#8250;</span>
 </div>
 <div id="nprefs" style="display:none;padding:2px 0 14px 51px">
  <div style="display:flex;gap:8px">
   <button class="npc" data-l="all" style="flex:1;border:1px solid
    #2a5a80;background:#1d3350;color:#cfe3f5;border-radius:10px;
    padding:9px;font-size:.82rem;font-weight:700">Tout</button>
   <button class="npc" data-l="important" style="flex:1;border:1px
    solid #263341;background:#0f1620;color:#8fa1b3;
    border-radius:10px;padding:9px;font-size:.82rem;
    font-weight:700">Important seulement</button>
  </div>
 </div>
</div>
<div class="sec">Application</div>
<div class="panel" style="padding:4px 14px">
 <div class="srow" onclick="inst()">
  <div class="sic">&#128241;</div>
  <div style="flex:1"><b>Installer l&#39;application</b>
   <div class="ssub">Une ic&ocirc;ne sur votre &eacute;cran
    d&#39;accueil</div></div>
  <span class="chv">&#8250;</span>
 </div>
 <div class="srow" id="infobtn">
  <div class="sic">&#8505;&#65039;</div>
  <div style="flex:1"><b>Ce qu&#39;il faut savoir</b></div>
  <span class="chv">&#8250;</span>
 </div>
 <div class="srow" id="tourbtn">
  <div class="sic">&#127891;</div>
  <div style="flex:1"><b>Revoir le guide</b></div>
  <span class="chv">&#8250;</span>
 </div>
</div>
<div id="howto" style="margin-top:10px">&#128241;
 <b>Pour installer :</b><br>
1. Touchez le menu <b>&#8942;</b> en haut &agrave; droite de Chrome<br>
2. Choisissez <b>&laquo; Ajouter &agrave; l&#8217;&eacute;cran
 d&#8217;accueil &raquo;</b> (ou &laquo; Installer
 l&#8217;application &raquo;)<br>
3. L&#8217;ic&ocirc;ne &#129417; appara&icirc;t sur votre
 t&eacute;l&eacute;phone !</div>
<div class="sec" id="adm-sec" style="display:none">Administration</div>
<div class="panel" id="adm-card" style="display:none;padding:4px 14px">
 <div class="srow" id="goalbtn">
  <div class="sic">&#127919;</div>
  <div style="flex:1"><b>D&eacute;finir l&#39;objectif</b></div>
  <span class="chv">&#8250;</span>
 </div>
 <div class="srow" id="codebtn">
  <div class="sic">&#128273;</div>
  <div style="flex:1"><b>Code d&#39;activation</b>
   <div class="ssub">Pour activer le robot d&#39;un membre</div></div>
  <span class="chv">&#8250;</span>
 </div>
 <div class="srow" id="pausebtn" style="display:none">
  <div class="sic">&#9208;&#65039;</div>
  <div style="flex:1"><b id="pause-lbl">Mettre le robot en
   pause</b></div>
  <span class="chv">&#8250;</span>
 </div>
 <a class="srow" id="chartbtn" href="#"
  style="display:none;text-decoration:none;color:inherit">
  <div class="sic">&#128200;</div>
  <div style="flex:1"><b>Graphique custom (BTC)</b>
   <div class="ssub">M1 filtr&eacute; &mdash; labo du
    ma&icirc;tre</div></div>
  <span class="chv">&#8250;</span>
 </a>
</div>
<div class="sec">Compte</div>
<div class="panel" style="padding:4px 14px">
 <a class="srow" href="../" style="text-decoration:none">
  <div class="sic">&#8618;</div>
  <div style="flex:1"><b>Changer de compte</b>
   <div class="ssub">Ou cr&eacute;er un nouveau nid</div></div>
  <span class="chv">&#8250;</span>
 </a>
 <div class="srow" id="delbtn">
  <div class="sic" style="background:#2a1518">&#128465;</div>
  <div style="flex:1"><b style="color:#ff9c9c">Retirer mon compte
   du robot</b></div>
  <span class="chv">&#8250;</span>
 </div>
</div>
<div class="foot" id="upd">chargement...</div>
</div>
<div class="tab" id="tab-nid">
<div class="sec" style="margin-top:26px">Le Nid &middot; tous les
 comptes</div>
<div id="acctsw" style="display:none;margin-bottom:12px;
 background:#151d29;border:1px solid #263341;border-radius:14px;
 padding:12px">
 <div style="font-size:.78rem;color:#8fa1b3;margin-bottom:8px">
  Changer de vue (admin)</div>
 <div id="acctsw-b" style="display:flex;gap:8px;flex-wrap:wrap"></div>
</div>
<div class="panel" id="nest">...</div>
<button id="invbtn" style="width:100%;margin-top:14px;
 background:#1d3350;color:#cfe3f5;border:1px solid #2a5a80;
 border-radius:14px;padding:15px;font-size:1rem;font-weight:700">
 &#127915; Code d&#39;invitation (compte r&eacute;el)</button>
</div>
</div>
<div class="tabbar">
<button class="tb on" onclick="tab('home',this)"><span>&#127968;
</span>Accueil</button>
<button class="tb" onclick="tab('hist',this)"><span>&#128197;
</span>Historique</button>
<button class="tb" id="tb-nid" style="display:none"
 onclick="tab('nid',this)"><span>&#129417;</span>Le Nid</button>
<button class="tb" onclick="tab('set',this)"><span>&#9881;&#65039;
</span>R&eacute;glages</button>
</div>
<div id="sheetbg"></div>
<div id="sheet"><div class="grab"></div><div id="sheet-c"></div></div>
<div id="tourbg"></div>
<div id="tourbx"><p id="tourtxt"></p>
 <div style="display:flex;justify-content:space-between;
  align-items:center;margin-top:14px">
  <a href="#" id="tourskip" style="color:#5f7185;font-size:.85rem;
   text-decoration:none">Passer</a>
  <span id="tourdots"></span>
  <button id="tournext" class="shbtn shmain" style="width:auto;
   margin:0;padding:10px 22px">Suivant</button>
 </div>
</div>
<script>
const B=location.pathname.endsWith('/')?location.pathname:location.pathname+'/';
(function(){
 const m=document.createElement('link');m.rel='manifest';
 m.href=B+'manifest.json';document.head.appendChild(m);
 const i=document.createElement('link');i.rel='icon';
 i.href=B+'icon192.png';document.head.appendChild(i);
 const a=document.createElement('link');a.rel='apple-touch-icon';
 a.href=B+'icon192.png';document.head.appendChild(a);
})();
let lastOk=0;
let isPaused=false;
function setH(el,h){if(el._h!==h){el._h=h;el.innerHTML=h;}}
function fdur(m){
 if(m==null)return '';
 m=Math.round(m);
 if(m<60)return m+' min';
 const h=Math.floor(m/60),r=m%60;
 if(h<24)return h+' h'+(r?' '+String(r).padStart(2,'0'):'');
 const j=Math.floor(h/24);
 return j+' j '+(h%24)+' h';}
function sheet(html){return new Promise(res=>{
 const bg=document.getElementById('sheetbg'),
  sh=document.getElementById('sheet');
 document.getElementById('sheet-c').innerHTML=html;
 bg.style.display='block';
 requestAnimationFrame(()=>{bg.style.opacity='1';
  sh.style.transform='translateY(0)'});
 window._shOpen=true;
 try{history.pushState({sh:1},'')}catch(e){}
 window._shDone=(v)=>{
  if(!window._shOpen)return;
  window._shOpen=false;
  bg.style.opacity='0';
  sh.style.transform='translateY(105%)';
  setTimeout(()=>{bg.style.display='none'},250);
  try{if(history.state&&history.state.sh)history.back()}catch(e){}
  res(v)};
 bg.onclick=()=>window._shDone(null);
 const inp=document.getElementById('shpw');
 if(inp){setTimeout(()=>inp.focus(),280);
  inp.onkeydown=(ev)=>{if(ev.key==='Enter'){
   const m=sh.querySelector('.shmain');if(m)m.click();}};}
});}
window.addEventListener('popstate',()=>{
 if(window._shOpen)window._shDone(null);});
let _pty=null;
document.addEventListener('touchstart',e=>{
 _pty=(window.scrollY===0)?e.touches[0].clientY:null;},
 {passive:true});
document.addEventListener('touchmove',e=>{
 if(_pty!=null&&!window._shOpen
    &&e.touches[0].clientY-_pty>80){
  _pty=null;
  document.getElementById('upd').textContent='actualisation...';
  window._lastS=null;load();
  try{navigator.vibrate&&navigator.vibrate(8)}catch(x){}}},
 {passive:true});
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
function ledInfo(){
 const row=(ic,t,s)=>'<div style="display:flex;gap:12px;'+
  'align-items:flex-start;margin:13px 0">'+
  '<div style="flex:0 0 38px;height:38px;border-radius:12px;'+
   'background:rgba(127,179,224,.1);border:1px solid '+
   'rgba(127,179,224,.18);display:flex;align-items:center;'+
   'justify-content:center;font-size:1.05rem">'+ic+'</div>'+
  '<div style="min-width:0"><b style="font-size:.86rem">'+t+
   '</b><div style="font-size:.79rem;color:#8fa1b3;'+
   'line-height:1.45">'+s+'</div></div></div>';
 const man=isPaused;
 sheet('<h3 style="margin:0 0 2px">Le rattrapage</h3>'+
  '<p style="font-size:.78rem;color:#6f93b5;margin:0 0 6px">'+
  (man?'Votre plan de r&eacute;cup&eacute;ration, comme celui '+
    'du robot':'Comment le robot r&eacute;cup&egrave;re une '+
    'perte, sans jamais creuser le compte')+'</p>'+
  row('&#128546;','&Agrave; rattraper',
   'Les pertes pas encore r&eacute;cup&eacute;r&eacute;es. '+
   'Chaque gain fait baisser ce chiffre.')+
  row('&#128176;','Gains de c&ocirc;t&eacute;',
   (man?'Vos gains':'Les gains du robot')+' sont mis dans une '+
   'r&eacute;serve au lieu d&#39;&ecirc;tre risqu&eacute;s '+
   '&agrave; nouveau.')+
  row('&#127919;',man?'Le grand chiffre vert'
    :'Prochain soldat',
   (man?'Le plus gros trade que la r&eacute;serve peut payer '+
     'enti&egrave;rement. Vous pouvez prendre moins &mdash; '+
     'jamais plus.'
    :'Le trade un peu plus gros que le robot pr&eacute;pare '+
     'pour rattraper la perte, pay&eacute; par la '+
     'r&eacute;serve.'))+
  row('&#128299;','Les balles',
   (man?'1 balle = un trade de 0.01 d&eacute;j&agrave; '+
     'pay&eacute;. Magasin plein = carte dor&eacute;e : votre '+
     'grand coup est pr&ecirc;t.'
    :'Le soldat se remplit gain apr&egrave;s gain. Magasin '+
     'plein = carte dor&eacute;e : il attaque au prochain '+
     'signal.'))+
  '<div style="background:rgba(46,204,113,.08);border:1px solid '+
   'rgba(46,204,113,.2);border-radius:12px;padding:10px 12px;'+
   'font-size:.8rem;color:#9fd4b5;line-height:1.45;margin:4px 0 '+
   '10px">&#128737;&#65039; Si le coup rate, seule la '+
   'r&eacute;serve paie &mdash; le compte ne descend pas plus '+
   'bas. S&#39;il gagne, la dette fond.</div>'+
  '<button class="shbtn shmain" onclick="_shDone(1)">'+
  'Compris&nbsp;!</button>');
}
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
 const gb=document.getElementById('goalbtn');
 if(gb)gb.onclick=async(e)=>{e.preventDefault();
  const b0=(window._d&&window._d.balance)?window._d.balance:0;
  const chips=[25,50,100,250].map(a=>
   '<button class="shbtn shghost" style="flex:1;margin:0;'+
   'padding:11px 0;font-size:.9rem" '+
   'onclick="document.getElementById(\\'goalamt\\').value=\\''+
   Math.ceil(b0+a)+'\\'">+'+a+'&nbsp;$</button>').join('');
  const v=await sheet('<h3>&#127919; Objectif</h3>'+
   '<div style="display:flex;justify-content:space-between;'+
   'align-items:center;background:#0b1420;border-radius:12px;'+
   'padding:12px 14px;margin-bottom:12px">'+
   '<span style="color:#8fa1b3;font-size:.85rem">Solde actuel'+
   '</span><b style="font-size:1.1rem">'+b0.toFixed(2)+
   '&nbsp;$</b></div>'+
   '<div style="font-size:.78rem;color:#8fa1b3;margin-bottom:8px">'+
   'Choix rapide &mdash; ou entrez votre montant :</div>'+
   '<div style="display:flex;gap:8px;margin-bottom:10px">'+chips+
   '</div>'+
   '<input id="goalamt" type="number" inputmode="decimal" '+
   'placeholder="Montant vis&eacute; (ex : '+
   Math.ceil(b0+50)+')">'+
   '<input id="shpw" type="password" '+
   'placeholder="Mot de passe du compte (broker)">'+
   '<button class="shbtn shmain" onclick="_shDone('+
   '[document.getElementById(\\'goalamt\\').value,'+
   'document.getElementById(\\'shpw\\').value])">'+
   '&#127919; Enregistrer l&#39;objectif</button>'+
   '<button class="shbtn shghost" style="color:#ff9c9c" '+
   'onclick="_shDone([\\'0\\','+
   'document.getElementById(\\'shpw\\').value])">D&eacute;sactiver '+
   'la barre</button>'+
   '<button class="shbtn shghost" onclick="_shDone(null)">Annuler'+
   '</button>');
  if(!v||!v[1])return;
  if(v[0]!=='0'&&parseFloat(v[0]||'0')<=b0){
   await info('&#9888;&#65039; <h3>Visez plus haut !</h3>'+
    '<p>L&#39;objectif doit &ecirc;tre au-dessus du solde actuel ('+
    b0.toFixed(2)+'&nbsp;$).</p>');
   return;}
  const r=await fetch(B+'set_goal',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'amount='+encodeURIComponent(v[0]||'0')+'&pwd='+
    encodeURIComponent(v[1])}).catch(()=>null);
  try{const j=await r.json();
   if(j.ok){await info('&#127919; <h3>Objectif enregistr&eacute; !'+
    '</h3>');load();}
   else{await info('&#10060; <h3>Mot de passe incorrect.</h3>');}}
  catch(e2){await info('<h3>Petit souci, r&eacute;essayez.</h3>');}};
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
 nb.style.display='flex';
 const cur=await reg.pushManager.getSubscription().catch(()=>null);
 nb.dataset.on=cur?'1':'0';
 document.getElementById('notif-lbl').innerHTML=cur
  ?'Notifications activ&eacute;es &mdash; toucher pour couper'
  :'Activer les notifications';
 document.getElementById('nprefs').style.display=cur?'block':'none';
 document.querySelectorAll('.npc').forEach(b=>{b.onclick=async()=>{
  await fetch(B+'push_pref',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'level='+b.dataset.l}).catch(()=>null);
  window._plvl=b.dataset.l;npcPaint();};});
 function npcPaint(){document.querySelectorAll('.npc').forEach(b=>{
  const on=b.dataset.l===(window._plvl||'all');
  b.style.background=on?'#1d3350':'#0f1620';
  b.style.borderColor=on?'#2a5a80':'#263341';
  b.style.color=on?'#cfe3f5':'#8fa1b3';});}
 window.npcPaint=npcPaint;npcPaint();
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
const TOUR=[
 ['eq','&#128176; &Ccedil;a, c&#39;est votre argent. Il se met '+
  '&agrave; jour tout seul, toutes les 5 secondes.'],
 ['meteo','&#127782;&#65039; La m&eacute;t&eacute;o du robot : '+
  'soleil = il travaille tranquillement, orage = il se met &agrave; '+
  'l&#39;abri et attend.'],
 ['ledcard','&#9876;&#65039; Quand le robot perd un peu, il '+
  '&eacute;conomise ses petits gains, puis envoie un soldat '+
  'rattraper la perte. Tout se suit ici.'],
 [null,'&#128197; En bas : l&#39;Accueil, l&#39;Historique jour par '+
  'jour, et les R&eacute;glages &mdash; pensez &agrave; activer '+
  'les notifications !']];
let _ti=-1;
function tourStep(i){
 document.querySelectorAll('.tourhl').forEach(x=>
  x.classList.remove('tourhl'));
 if(i>=TOUR.length){
  document.getElementById('tourbg').style.display='none';
  document.getElementById('tourbx').style.display='none';
  try{localStorage.setItem('owlTourDone','1')}catch(e){}
  _ti=-1;return;
 }
 _ti=i;
 const [tid,txt]=TOUR[i];
 const el=tid?document.getElementById(tid)
  :document.querySelector('.tabbar');
 document.getElementById('tourbg').style.display='block';
 const bx=document.getElementById('tourbx');
 bx.style.display='block';
 document.getElementById('tourtxt').innerHTML=txt;
 document.getElementById('tourdots').innerHTML=
  TOUR.map((_,k)=>k===i?'&#9679;':'&#9675;').join('');
 document.getElementById('tournext').textContent=
  i===TOUR.length-1?'C’est parti !':'Suivant';
 if(el){
  el.classList.add('tourhl');
  try{el.scrollIntoView({block:'center',behavior:'smooth'})}
  catch(e){}
  setTimeout(()=>{
   const r=el.getBoundingClientRect();
   const below=r.bottom<window.innerHeight*0.55;
   bx.style.top=below?(r.bottom+14)+'px':'';
   bx.style.bottom=below?'':(window.innerHeight-r.top+14)+'px';
   if(!below)bx.style.top='auto';
  },350);
 }
}
window.addEventListener('load',()=>{
 document.getElementById('tournext').onclick=()=>tourStep(_ti+1);
 document.getElementById('tourskip').onclick=(e)=>{
  e.preventDefault();tourStep(TOUR.length);};
 const ib2=document.getElementById('infobtn');
 if(ib2)ib2.onclick=(e)=>{e.preventDefault();
  info('<h3>&#8505;&#65039; Ce qu&#39;il faut savoir</h3>'+
   '<div style="text-align:left;font-size:.92rem;color:#c6d3df;'+
   'line-height:1.7">'+
   '&#128176; Le robot travaille avec de l&#39;argent '+
   'r&eacute;el. Il peut gagner <b>et</b> perdre.<br>'+
   '&#128737;&#65039; Chaque trade ne risque qu&#39;une toute '+
   'petite part du compte &mdash; jamais tout d&#39;un coup.<br>'+
   '&#9928;&#65039; Quand le march&eacute; devient m&eacute;chant, '+
   'le robot s&#39;abrite tout seul et attend.<br>'+
   '&#128184; Ne confiez que de l&#39;argent que vous pouvez '+
   'laisser travailler longtemps, sans en avoir besoin.<br>'+
   '&#9208;&#65039; Vous pouvez mettre en pause ou retirer votre '+
   'compte &agrave; tout moment, ici dans les R&eacute;glages.<br>'+
   '&#128200; Les r&eacute;sultats pass&eacute;s ne promettent '+
   'jamais l&#39;avenir.</div>');};
 const tb=document.getElementById('tourbtn');
 if(tb)tb.onclick=(e)=>{e.preventDefault();
  tab('home',document.querySelector('.tb'));tourStep(0);};
 setTimeout(()=>{try{
  if(!localStorage.getItem('owlTourDone'))tourStep(0);
 }catch(e){}},1500);
});
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
 const g=(h>=5&&h<12)?'Bonjour'
  :((h>=12&&h<18)?'Bon apr&egrave;s-midi':'Bonsoir');
 const he=document.getElementById('hello');
 he.innerHTML=he.innerHTML.replace('Bonjour',g)
  .replace('&#128075;',(h>=20||h<5)?'&#127769;':'&#128075;')
  .replace('👋',(h>=20||h<5)?'🌙'
   :'👋');
})();
function confetti(em){
 for(let i=0;i<44;i++){
  const s=document.createElement('div');
  s.textContent=(em||['🎉','✨','💚',
   '🏆'])[i%4];
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
window._cvz='7';
function drawSpark(){
 const c=(window._cvz==='30'&&window._c30&&window._c30.length>1)
  ?window._c30:(window._c7||[]);
 if(c.length<2)return;
 const mn=Math.min(...c,0),mx=Math.max(...c,0),sp=(mx-mn)||1;
 const P=(v,i)=>((i/(c.length-1))*300).toFixed(1)+','+
   (62-((v-mn)/sp*54)).toFixed(1);
 const pts=c.map((v,i)=>P(v,i)).join(' ');
 const col=c[c.length-1]>=0?'#2ecc71':'#ff5c5c';
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
document.querySelectorAll('.cvc').forEach(b=>{b.onclick=()=>{
 window._cvz=b.dataset.c;
 document.querySelectorAll('.cvc').forEach(x=>{
  const on=x.dataset.c===window._cvz;
  x.style.background=on?'#1d3350':'#0f1620';
  x.style.borderColor=on?'#2a5a80':'#263341';
  x.style.color=on?'#cfe3f5':'#8fa1b3';});
 drawSpark();};});
function tradeSheet(i){
 const x=(window._tr||[])[i];
 if(!x)return;
 const L=(a,b)=>'<div style="display:flex;justify-content:'+
  'space-between;padding:9px 2px;border-bottom:1px solid #1e2937;'+
  'font-size:.95rem"><span style="color:#8fa1b3">'+a+
  '</span><b>'+b+'</b></div>';
 sheet('<h3>'+(x.dir==='A'?'&#128200; Achat':'&#128201; Vente')+
  (x.k?' &middot; '+(x.k==='page'?'normal':x.k):'')+'</h3>'+
  L('R&eacute;sultat','<span class="'+(x.p>=0?'pos':'neg')+'">'+
   (x.p>=0?'+':'-')+Math.abs(x.p).toFixed(2)+' $</span>')+
  (x.lot?L('Taille',x.lot.toFixed(2)+' lot'):'')+
  (x.ep!=null?L('Entr&eacute;e',x.ep.toFixed(2)):'')+
  (x.xp!=null?L('Sortie',x.xp.toFixed(2)):'')+
  (x.dur!=null?L('Dur&eacute;e',fdur(x.dur)):'')+
  L('Quand',x.w)+
  '<button class="shbtn shmain" onclick="_shDone(1)">Fermer</button>');
}
window.addEventListener('load',()=>{
 const ib=document.getElementById('invbtn');
 if(ib)ib.onclick=async()=>{
  const pw=await askPwd('Code d&#39;invitation (compte r&eacute;el)',
   'Pour un membre de la famille qui veut connecter son VRAI compte. '+
   'Usage unique.','&#127915; G&eacute;n&eacute;rer',false);
  if(!pw)return;
  const r=await fetch(B+'nest_invite',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'pwd='+encodeURIComponent(pw)}).catch(()=>null);
  try{const j=await r.json();
   if(j.ok){await sheet('<h3>Code d&#39;invitation</h3>'+
    '<div style="font-size:2rem;font-weight:800;letter-spacing:.3em;'+
    'text-align:center;background:#0b1420;border-radius:14px;'+
    'padding:18px 6px;margin:6px 0 10px;color:#7fb0ff">'+j.code+
    '</div><p>Usage unique &middot; &agrave; entrer &agrave; '+
    'l&#39;inscription avec un compte r&eacute;el</p>'+
    '<button class="shbtn shmain" onclick="navigator.clipboard&&'+
    'navigator.clipboard.writeText(\\''+j.code+'\\');_shDone(1)">'+
    '&#128203; Copier et fermer</button>');}
   else{await info('&#10060; <h3>Mot de passe incorrect.</h3>');}}
  catch(e2){await info('<h3>Petit souci, r&eacute;essayez.</h3>');}};
});
function shareWeek(){
 const d=window._d;
 if(!d)return;
 const c=document.createElement('canvas');
 c.width=720;c.height=940;
 const g=c.getContext('2d');
 const gr=g.createLinearGradient(0,0,0,940);
 gr.addColorStop(0,'#0f2740');gr.addColorStop(1,'#0b0f14');
 g.fillStyle=gr;g.fillRect(0,0,720,940);
 g.textAlign='center';
 g.fillStyle='#cfe3f5';g.font='bold 46px sans-serif';
 g.fillText('🦉 OwlNest',360,92);
 g.fillStyle='#7d9cb8';g.font='26px sans-serif';
 g.fillText('Ma semaine · '+(d.name||''),360,138);
 const wk=d.week||0;
 g.fillStyle=wk>=0?'#2ecc71':'#ff5c5c';
 g.font='bold 92px sans-serif';
 g.fillText((wk>=0?'+':'-')+Math.abs(wk).toFixed(2)+' $',360,252);
 const cv=d.curve||[];
 if(cv.length>1){
  const mn=Math.min(...cv,0),mx=Math.max(...cv,0),sp=(mx-mn)||1;
  g.beginPath();
  cv.forEach((v,i)=>{
   const x=80+(i/(cv.length-1))*560;
   const y=470-((v-mn)/sp)*150;
   i?g.lineTo(x,y):g.moveTo(x,y);});
  g.strokeStyle=cv[cv.length-1]>=0?'#2ecc71':'#ff5c5c';
  g.lineWidth=5;g.lineJoin='round';g.stroke();
 }
 let y=560;
 (d.days||[]).slice(0,7).forEach(x=>{
  g.textAlign='left';g.fillStyle='#8fa1b3';
  g.font='26px sans-serif';
  g.fillText(x.d,110,y);
  g.textAlign='right';
  g.fillStyle=x.p>=0?'#2ecc71':'#ff5c5c';
  g.font='bold 26px sans-serif';
  g.fillText((x.p>=0?'+':'-')+Math.abs(x.p).toFixed(2)+' $',610,y);
  y+=44;});
 g.textAlign='center';g.fillStyle='#5f7185';
 g.font='22px sans-serif';
 g.fillText('Le robot Owl trade pour vous, jour et nuit.',360,898);
 c.toBlob(async b=>{
  const f=new File([b],'owlnest-semaine.png',{type:'image/png'});
  if(navigator.canShare&&navigator.canShare({files:[f]})){
   try{await navigator.share({files:[f],
    title:'Ma semaine OwlNest'});}catch(e){}
  }else{
   try{window.open(URL.createObjectURL(b),'_blank');}catch(e){}
  }
 },'image/png');
}
async function nestPause(uid,on){
 const pw=await askPwd(
  on=='1'?'Mettre ce membre en pause ?':'Reprendre ce membre ?',
  'Le robot '+(on=='1'?'ne prendra plus':'reprendra')+
  ' de nouveaux trades sur ce compte.',
  on=='1'?'&#9208;&#65039; Mettre en pause':'&#9654;&#65039; Reprendre',
  on=='1');
 if(!pw)return;
 const r=await fetch(B+'nest_pause',{method:'POST',
  headers:{'Content-Type':'application/x-www-form-urlencoded'},
  body:'uid='+encodeURIComponent(uid)+'&on='+on+'&pwd='+
   encodeURIComponent(pw)}).catch(()=>null);
 try{const j=await r.json();
  if(!j.ok){await info('&#10060; <h3>Mot de passe incorrect.</h3>');
   return;}}catch(e){}
 load();
}
function ago(){
 if(!lastOk){return}
 const s=Math.max(0,Math.round((Date.now()-lastOk)/1000));
 document.getElementById('upd').innerHTML='Mis &agrave; jour il y a '+s+' s';
}
function render(d){
  window._d=d;
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
  if(d.ftest){
   const ft=d.ftest;
   const fc=document.getElementById('ftcard');
   fc.style.display='block';
   const wr=ft.n?ft.w/Math.max(1,ft.w+ft.l):0;
   const col=(ft.w+ft.l)<5?'#7fb0ff'
    :(wr>=ft.wr_pass?'#2ecc71':(wr>=0.60?'#e8c55a':'#ff5c5c'));
   document.getElementById('ft-txt').innerHTML=
    'Trade <b>'+ft.n+'</b> sur '+ft.target+' &middot; '+
    '<span style="color:#8df0bb">'+ft.w+' gagn&eacute;s</span> / '+
    '<span style="color:#ff9c9c">'+ft.l+' perdus</span>'+
    ((ft.w+ft.l)?' (<b style="color:'+col+'">'+
     Math.round(wr*100)+'&nbsp;%</b>)':'')+
    ' &middot; <b class="'+(ft.net>=0?'pos':'neg')+'">'+
    (ft.net>=0?'+':'-')+Math.abs(ft.net).toFixed(2)+'&nbsp;$</b>';
   const pb=document.getElementById('ft-bar');
   pb.style.width=Math.min(100,ft.n/ft.target*100)+'%';
   pb.style.background=col;
   document.getElementById('ft-sub').innerHTML=
    'Objectif : '+Math.round(ft.wr_pass*100)+'&nbsp;% de '+
    'r&eacute;ussite sur '+ft.target+' trades &mdash; si le robot '+
    'y arrive, la strat&eacute;gie est prouv&eacute;e.';
  }
  if(d.ledger){
   const lc=document.getElementById('ledcard');lc.style.display='block';
   const lt2=document.getElementById('led-txt'),
    lb=document.getElementById('led-bar'),
    lw=document.getElementById('led-barwrap'),
    ls2=document.getElementById('led-sub');
   lc.style.padding=d.ledger.debt>0.5?'14px':'8px 14px';
   lc.style.fontSize=d.ledger.debt>0.5?'.92rem':'.8rem';
   lc.style.boxShadow='';lc.style.borderColor='#23405e';
   document.getElementById('led-hd').style.display=
    d.ledger.debt>0.5?'block':'none';
   if(d.ledger.debt>0.5){
    if(d.trading_paused){
     const am=d.ledger.chest;
     let rk=50,rn=0,rs=0;
     (d.trades||[]).forEach(x=>{
      if(x.p<-0.005&&x.lot>0){rs+=Math.abs(x.p)/x.lot;rn++;}});
     if(rn>=3)rk=rs/rn;
     const bc=rk*0.01;
     const nb=Math.floor(am/bc+1e-9);
     const fr=(am-nb*bc)/bc;
     const ml=nb*0.01;
     const SL=Math.max(4,Math.min(10,
      Math.floor((d.ledger.cap||5)/bc+1e-9)));
     let pills='';
     for(let i=0;i<SL;i++){
      const on=i<nb;
      const g=(!on&&i===nb&&fr>0.02)
       ?'background:linear-gradient(90deg,#e8c55a '+
        (fr*100).toFixed(0)+'%,rgba(255,255,255,.07) '+
        (fr*100).toFixed(0)+'%);'
       :'background:'+(on?'#e8c55a':'rgba(255,255,255,.07)')+';';
      pills+='<span data-bp="'+i+'" style="display:inline-block;'+
       'width:13px;height:22px;border-radius:4px;margin:0 2px;'+g+
       (on?'box-shadow:0 0 6px rgba(232,197,90,.45);':'')+
       'transition:transform .3s"></span>';
     }
     lt2.innerHTML=
      '<div style="display:grid;grid-template-columns:1fr 1fr;'+
       'gap:8px">'+
       '<div style="background:rgba(255,92,92,.08);border:1px '+
        'solid rgba(255,92,92,.22);border-radius:12px;'+
        'padding:8px 10px;text-align:center">'+
        '<div style="font-size:.62rem;color:#ff9c9c;'+
         'text-transform:uppercase;letter-spacing:.08em">'+
         '&Agrave; rattraper</div>'+
        '<b style="color:#ffb3b3;font-size:1.05rem;'+
         'font-variant-numeric:tabular-nums"><span id="rz-debt">'+
         d.ledger.debt.toFixed(2)+'</span>&nbsp;$</b></div>'+
       '<div style="background:rgba(232,197,90,.07);border:1px '+
        'solid rgba(232,197,90,.22);border-radius:12px;'+
        'padding:8px 10px;text-align:center">'+
        '<div style="font-size:.62rem;color:#e8c55a;'+
         'text-transform:uppercase;letter-spacing:.08em">'+
         'Gains de c&ocirc;t&eacute;</div>'+
        '<b style="color:#f0d788;font-size:1.05rem;'+
         'font-variant-numeric:tabular-nums"><span id="rz-ammo">'+
         am.toFixed(2)+'</span>&nbsp;$</b></div>'+
      '</div>'+
      '<div style="text-align:center;margin:12px 0 4px">'+
       '<div style="font-size:.62rem;color:#7fb3e0;'+
        'text-transform:uppercase;letter-spacing:.08em">'+
        'Vous pouvez trader jusqu&#39;&agrave;</div>'+
       '<b style="color:#7fd4a0;font-size:2.1rem;'+
        'font-variant-numeric:tabular-nums"><span id="rz-lot">'+
        (ml>=0.01?ml.toFixed(2):'0.00')+'</span></b>'+
       '<span style="color:#8fa1b3;font-size:.85rem"> lot</span>'+
      '</div>'+
      '<div style="text-align:center;margin-top:4px">'+pills+
       (nb>SL?'<span style="color:#e8c55a;font-size:.78rem"> '+
        '&times;'+nb+'</span>':'')+'</div>'+
      '<div style="text-align:center;font-size:.68rem;'+
       'color:#5f7185;margin-top:4px">'+
       (nb>0
        ?nb+' tir'+(nb>1?'s':'')+' pr&ecirc;t'+(nb>1?'s':'')+
         ' &middot; 1 tir = 0.01 lot'
        :'Aucun tir pr&ecirc;t &mdash; chaque gain remplit la '+
         'r&eacute;serve')+'</div>';
     lw.style.display='none';ls2.innerHTML='';
     const full=nb>=SL;
     lc.style.transition='box-shadow .8s,border-color .8s';
     lc.style.boxShadow=full?'0 0 24px rgba(232,197,90,.3)':'';
     lc.style.borderColor=full?'rgba(232,197,90,.55)':'#23405e';
     const rz=window._rz||{};
     const roll=(id,a,b)=>{
      if(a===undefined||Math.abs(a-b)<0.005)return;
      const el=lc.querySelector('#'+id);if(!el)return;
      const t0=performance.now();
      const st=t=>{const k=Math.min(1,(t-t0)/600);
       el.textContent=(a+(b-a)*k).toFixed(2);
       if(k<1)requestAnimationFrame(st);};
      requestAnimationFrame(st);};
     const fl=(id,a,b,good)=>{
      if(a===undefined||Math.abs(a-b)<0.005)return;
      const el=lc.querySelector('#'+id);if(!el)return;
      el.style.transition='color .25s';
      el.style.color=good?'#2ecc71':'#ff5c5c';
      setTimeout(()=>{el.style.color='';},1100);};
     roll('rz-debt',rz.d,d.ledger.debt);
     fl('rz-debt',rz.d,d.ledger.debt,d.ledger.debt<rz.d);
     roll('rz-ammo',rz.a,am);
     fl('rz-ammo',rz.a,am,am>rz.a);
     roll('rz-lot',rz.m,ml);
     fl('rz-lot',rz.m,ml,ml>rz.m);
     window._rz={d:d.ledger.debt,a:am,m:ml};
     if(window._ammoB!==undefined&&nb>window._ammoB&&nb<=SL){
      setTimeout(()=>{
       const el=lc.querySelector('[data-bp="'+(nb-1)+'"]');
       if(el){el.style.transform='scale(1.6)';
        setTimeout(()=>{el.style.transform='';},450);}},60);
     }
     window._ammoB=nb;
    }else{
     const am=d.ledger.chest;
     const need=Math.max(d.ledger.need_min||0.01,0.01);
     const nl=Math.max(d.ledger.next_lot||0.02,0.01);
     const SL=Math.max(2,Math.min(10,Math.round(nl/0.01)));
     const prog=Math.max(0,Math.min(SL,am/need*SL));
     const fillN=Math.floor(prog+1e-9);
     const fr=prog-fillN;
     const ok=am>=need-0.005;
     let pills='';
     for(let i=0;i<SL;i++){
      const on=i<fillN;
      const g=(!on&&i===fillN&&fr>0.02)
       ?'background:linear-gradient(90deg,#e8c55a '+
        (fr*100).toFixed(0)+'%,rgba(255,255,255,.07) '+
        (fr*100).toFixed(0)+'%);'
       :'background:'+(on?'#e8c55a':'rgba(255,255,255,.07)')+';';
      pills+='<span style="display:inline-block;width:13px;'+
       'height:22px;border-radius:4px;margin:0 2px;'+g+
       (on?'box-shadow:0 0 6px rgba(232,197,90,.45);':'')+
       '"></span>';
     }
     lt2.innerHTML=
      '<div style="display:grid;grid-template-columns:1fr 1fr;'+
       'gap:8px">'+
       '<div style="background:rgba(255,92,92,.08);border:1px '+
        'solid rgba(255,92,92,.22);border-radius:12px;'+
        'padding:8px 10px;text-align:center">'+
        '<div style="font-size:.62rem;color:#ff9c9c;'+
         'text-transform:uppercase;letter-spacing:.08em">'+
         '&Agrave; rattraper</div>'+
        '<b style="color:#ffb3b3;font-size:1.05rem;'+
         'font-variant-numeric:tabular-nums"><span id="rz-debt">'+
         d.ledger.debt.toFixed(2)+'</span>&nbsp;$</b></div>'+
       '<div style="background:rgba(232,197,90,.07);border:1px '+
        'solid rgba(232,197,90,.22);border-radius:12px;'+
        'padding:8px 10px;text-align:center">'+
        '<div style="font-size:.62rem;color:#e8c55a;'+
         'text-transform:uppercase;letter-spacing:.08em">'+
         'Gains de c&ocirc;t&eacute;</div>'+
        '<b style="color:#f0d788;font-size:1.05rem;'+
         'font-variant-numeric:tabular-nums"><span id="rz-ammo">'+
         am.toFixed(2)+'</span>&nbsp;$</b></div>'+
      '</div>'+
      '<div style="text-align:center;margin:12px 0 4px">'+
       '<div style="font-size:.62rem;color:#7fb3e0;'+
        'text-transform:uppercase;letter-spacing:.08em">'+
        'Prochain soldat du robot</div>'+
       '<b style="color:#7fd4a0;font-size:2.1rem;'+
        'font-variant-numeric:tabular-nums"><span id="rz-lot">'+
        nl.toFixed(2)+'</span></b>'+
       '<span style="color:#8fa1b3;font-size:.85rem"> lot</span>'+
      '</div>'+
      '<div style="text-align:center;margin-top:4px">'+pills+
      '</div>'+
      '<div style="text-align:center;font-size:.68rem;'+
       'color:#5f7185;margin-top:4px">'+
       (ok
        ?'Soldat financ&eacute; &mdash; il attaque au prochain '+
         'signal'
        :'Encore '+(need-am).toFixed(2)+'&nbsp;$ de gains avant '+
         'l&#39;attaque')+'</div>';
     lw.style.display='none';ls2.innerHTML='';
     lc.style.transition='box-shadow .8s,border-color .8s';
     lc.style.boxShadow=ok?'0 0 24px rgba(232,197,90,.3)':'';
     lc.style.borderColor=ok?'rgba(232,197,90,.55)':'#23405e';
     const rz=window._rz||{};
     const roll=(id,a,b)=>{
      if(a===undefined||Math.abs(a-b)<0.005)return;
      const el=lc.querySelector('#'+id);if(!el)return;
      const t0=performance.now();
      const st=t=>{const k=Math.min(1,(t-t0)/600);
       el.textContent=(a+(b-a)*k).toFixed(2);
       if(k<1)requestAnimationFrame(st);};
      requestAnimationFrame(st);};
     const fl=(id,a,b,good)=>{
      if(a===undefined||Math.abs(a-b)<0.005)return;
      const el=lc.querySelector('#'+id);if(!el)return;
      el.style.transition='color .25s';
      el.style.color=good?'#2ecc71':'#ff5c5c';
      setTimeout(()=>{el.style.color='';},1100);};
     roll('rz-debt',rz.d,d.ledger.debt);
     fl('rz-debt',rz.d,d.ledger.debt,d.ledger.debt<rz.d);
     roll('rz-ammo',rz.a,am);
     fl('rz-ammo',rz.a,am,am>rz.a);
     roll('rz-lot',rz.m,nl);
     fl('rz-lot',rz.m,nl,nl>rz.m);
     window._rz={d:d.ledger.debt,a:am,m:nl};
    }
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
  if(d.push_level&&window._plvl===undefined){
   window._plvl=d.push_level;
   if(window.npcPaint)window.npcPaint();
  }
  if(d.eurusd){document.getElementById('eqe').innerHTML=
   '&asymp; '+(d.equity/d.eurusd).toFixed(0)+' &euro;';}
  const bk=document.getElementById('bank');
  if(Math.abs(d.equity-d.balance)<0.005){bk.style.display='none';}
  else{bk.style.display='block';
   bk.innerHTML='Solde des trades termin&eacute;s : '+
    d.balance.toFixed(2)+' $';}
  const dc=document.getElementById('daychip');
  if(typeof d.today==='number'){
   dc.style.display='inline-block';
   const up=d.today>=0;
   dc.textContent=(up?'+':'')+d.today.toFixed(2)+
    ' $ aujourd\\u2019hui';
   dc.style.background=up?'rgba(46,204,113,.16)'
    :'rgba(255,92,92,.16)';
   dc.style.color=up?'#8df0bb':'#ffb3b3';
  }
  try{
   const sc2=document.getElementById('spark');
   const cv30=d.curve30&&d.curve30.length>2?d.curve30
    :(d.curve&&d.curve.length>2?d.curve:null);
   if(cv30){
    const dpr=window.devicePixelRatio||1;
    const w=sc2.clientWidth,h=sc2.clientHeight;
    sc2.width=w*dpr;sc2.height=h*dpr;
    const g=sc2.getContext('2d');
    g.setTransform(dpr,0,0,dpr,0,0);
    g.clearRect(0,0,w,h);
    let mn=Math.min(...cv30),mx=Math.max(...cv30);
    if(mx-mn<0.01){mx+=0.5;mn-=0.5;}
    g.strokeStyle='rgba(255,255,255,.85)';
    g.lineWidth=1.6;g.lineJoin='round';
    g.beginPath();
    cv30.forEach((v,i)=>{
     const x=i/(cv30.length-1)*w;
     const y=h-6-((v-mn)/(mx-mn))*(h-14);
     i?g.lineTo(x,y):g.moveTo(x,y);});
    g.stroke();
   }
  }catch(e){}
  const lvE=document.getElementById('lv'),
   lvtE=document.getElementById('lvt');
  if(lvE&&lvtE){
   if(d.stale){lvtE.textContent='EN ATTENTE \\u23f3';
    lvE.style.background='rgba(230,160,40,.16)';
    lvE.style.color='#ffd27a';}
   else{lvtE.textContent='EN DIRECT';
    lvE.style.background='';lvE.style.color='';}
  }
  if(d.acct){
   document.getElementById('acctline').innerHTML=
    '<span style="background:'+
    (d.real?'rgba(46,204,113,.13)':'rgba(230,160,40,.13)')+
    ';color:'+(d.real?'#8df0bb':'#ffd27a')+
    ';padding:3px 10px;border-radius:99px;font-weight:700;'+
    'font-size:.64rem;letter-spacing:.05em">'+
    (d.real?'R&Eacute;EL':'D&Eacute;MO')+' &middot; '+d.acct+'</span>';
  }
  if(d.palier&&d.equity){
   const pb0=(d.palier_base&&d.palier_base<d.palier)
    ?d.palier_base:0;
   const pc=Math.max(0,Math.min(100,
    (d.equity-pb0)/(d.palier-pb0)*100));
   document.getElementById('palier').style.display='block';
   document.getElementById('palier-lbl').innerHTML=
    (d.palier_def
     ?'Objectif de la semaine : +50&nbsp;$'
     :'Objectif : '+d.palier.toFixed(0)+'&nbsp;$')+
    ' &middot; '+pc.toFixed(0)+'&nbsp;%';
   document.getElementById('palier-bar').style.width=pc+'%';
   if(pc>=100&&!window._conf){window._conf=1;confetti();}
  }
  const n=d.open_positions;
  if(d.trading_paused!==undefined){
   isPaused=d.trading_paused;
   const pb=document.getElementById('pausebtn');
   pb.style.display='flex';
   document.getElementById('adm-sec').style.display='block';
   document.getElementById('adm-card').style.display='block';
   document.getElementById('pause-lbl').innerHTML=isPaused
    ?'&#9654;&#65039; Reprendre le trading'
    :'Mettre le robot en pause';
  }
  document.getElementById('actcard').style.display=
   d.activation_needed?'block':'none';
  if(d.is_master){
   document.getElementById('adm-sec').style.display='block';
   document.getElementById('adm-card').style.display='block';
   document.getElementById('codebtn').style.display='flex';
   document.getElementById('goalbtn').style.display='flex';
   const cb=document.getElementById('chartbtn');
   cb.style.display='flex';
   cb.href=location.pathname.replace(/\\/+$/,'')+'/chart';}
  document.getElementById('chartlink').href=
   location.pathname.replace(/\\/+$/,'')+'/chart';
  document.getElementById('batchart').href=
   location.pathname.replace(/\\/+$/,'')+'/chart';
  document.getElementById('st').innerHTML =
   (d.trading_paused)
   ? '&#9208;&#65039; <b>Robot en pause</b> (par vous) &mdash; aucun '+
     'nouveau trade'
   : (n>0
   ? '&#129302; Le robot travaille &mdash; <b>'+n+' trade'+(n>1?'s':'')+
     ' en cours</b>'
   : '&#127747; March&eacute; sous surveillance &mdash; aucun trade ouvert');
  const bs=document.getElementById('battles-sec');
  const met=document.getElementById('meteo');
  const lc0=document.getElementById('ledcard');
  if(d.open_list&&d.open_list.length){
   met.style.display='none';
   if(lc0)lc0.style.marginTop='0px';
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
    ' lot</span>'+(x.k=='s'?' <span style="background:'+
    'rgba(232,197,90,.15);color:#e8c55a;padding:2px 8px;'+
    'border-radius:99px;font-size:.68rem;font-weight:700">'+
    '&#9876;&#65039; soldat</span>':'')+
    '</span><b style="font-size:1.12rem" class="'+
    (x.pl>=0?'pos':'neg')+'">'+
    (x.pl>=0?'+':'-')+Math.abs(x.pl).toFixed(2)+' $</b></div>'+bar;
   }).join('');
  }else{bs.style.display='none';met.style.display='block';
   if(lc0)lc0.style.marginTop='12px';}
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
  window._c7=d.curve||[];window._c30=d.curve30||[];
  drawSpark();
  if(d.is_master&&d.nest){
   document.getElementById('tb-nid').style.display='flex';
   const asw=document.getElementById('acctsw');
   asw.style.display='block';
   document.getElementById('acctsw-b').innerHTML=d.nest
    .filter(x=>x.tok)
    .map(x=>{
     const cur=(x.login&&d.acct&&String(x.login)===String(d.acct));
     return '<a href="/'+x.tok+'/" style="text-decoration:none;'+
      'padding:9px 14px;border-radius:10px;font-size:.85rem;'+
      'font-weight:700;border:1px solid '+
      (cur?'#2a5a80':'#263341')+';background:'+
      (cur?'#1d3350':'#0f1620')+';color:'+
      (cur?'#cfe3f5':'#8fa1b3')+'">'+x.name+
      (cur?' &#10004;':'')+'</a>';
    }).join('');
  }
  if(d.is_master&&d.nest){
   const tb=d.nest.reduce((a,x)=>a+(x.bal||0),0);
   const tt=d.nest.reduce((a,x)=>a+(x.today||0),0);
   const hdr='<div class="row" style="border-bottom:2px solid '+
    '#24344a"><span><b>&#127968; Total famille</b> <span style="'+
    'color:#5f7185;font-size:.75rem">'+d.nest.length+
    ' compte'+(d.nest.length>1?'s':'')+'</span></span>'+
    '<span style="text-align:right"><b>'+tb.toFixed(2)+' $</b>'+
    '<span style="display:block;font-size:.78rem" class="'+
    (tt>=0?'pos':'neg')+'">auj. '+(tt>=0?'+':'-')+
    Math.abs(tt).toFixed(2)+' $</span></span></div>';
   document.getElementById('nest').innerHTML=hdr+d.nest.map(x=>{
    const dot=x.err||x.stale?'#e6a028':(x.paused?'#8fa1b3':'#2ecc71');
    const st=x.err?'probl&egrave;me':(x.stale?'hors ligne'
     :(x.paused?'en pause':'actif'));
    return '<div class="row"><span style="display:flex;'+
    'flex-direction:column;gap:3px"><span><span style="display:'+
    'inline-block;width:9px;height:9px;border-radius:50%;background:'+
    dot+';margin-right:8px"></span><b>'+x.name+'</b> '+
    '<span style="color:#5f7185;font-size:.75rem">'+st+
    (x.plan?' &middot; '+x.plan:'')+
    (x.login?' &middot; '+x.login:'')+'</span></span>'+
    '<span style="font-size:.8rem;color:#8fa1b3">'+
    (x.bal!=null?x.bal.toFixed(2)+' $':'--')+
    (x.today!=null?' &middot; auj. <span class="'+
     (x.today>=0?'pos':'neg')+'">'+(x.today>=0?'+':'-')+
     Math.abs(x.today).toFixed(2)+' $</span>':'')+'</span></span>'+
    '<span style="display:flex;gap:6px">'+
    (x.tok?'<a href="/'+x.tok+'/" target="_blank" '+
    'style="border:1px solid #263341;background:#0f1620;'+
    'color:#c6d3df;border-radius:10px;padding:8px 11px;'+
    'font-size:.85rem;text-decoration:none">&#128065;&#65039;'+
    '</a>':'')+
    (x.trade?'<button data-u="'+x.id+'" data-o="'+(x.paused?0:1)+
    '" onclick="nestPause(this.dataset.u,this.dataset.o)" '+
    'style="border:1px solid #263341;background:#0f1620;'+
    'color:#c6d3df;border-radius:10px;padding:8px 13px;'+
    'font-size:.85rem">'+
    (x.paused?'&#9654;&#65039;':'&#9208;&#65039;')+'</button>':'')+
    '</span></div>';
   }).join('');
  }
  if(d.days&&!d.days.length){
   const de=document.getElementById('days');de.style.display='block';
   de.innerHTML='<div class="empty"><i>&#129417;</i>'+
    '<p>Vos journ&eacute;es appara&icirc;tront ici</p></div>';
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
   setH(ms,
    cell('Net du mois',f(net),net>=0?'pos':'neg','depuis le 1er')+
    cell('Jours','<span class="pos">'+g+'</span> / <span class="neg">'+
     rr+'</span>','neu','verts / rouges')+
    cell('Meilleur jour',f(best),'pos','le plus gagnant')+
    cell('Pire jour',f(worst),worst>=0?'pos':'neg','le plus dur'));
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
   ce.style.display='block';setH(ce,h);
  }
  if(d.trades&&d.trades.length>4){
   const ps=d.trades.map(x=>x.p);
   const W=ps.filter(p=>p>0.005),Lo=ps.filter(p=>p<-0.005);
   const sw=W.reduce((a,b)=>a+b,0),
    slo=Math.abs(Lo.reduce((a,b)=>a+b,0));
   let bs=0,cur=0;
   ps.slice().reverse().forEach(p=>{
    if(p>0.005){cur++;if(cur>bs)bs=cur;}
    else if(p<-0.005)cur=0;});
   const SR=(a,b,c)=>'<div class="row"><span class="rowt">'+a+
    '</span><b class="'+(c||'neu')+'">'+b+'</b></div>';
   document.getElementById('statx-sec').style.display='block';
   const sx=document.getElementById('statx');
   sx.style.display='block';
   setH(sx,
    SR('Trades gagnants',W.length+' sur '+ps.length+' ('+
     Math.round(W.length/ps.length*100)+'&nbsp;%)','pos')+
    SR('Gain moyen','+'+(sw/Math.max(1,W.length)).toFixed(2)+
     '&nbsp;$','pos')+
    SR('Perte moyenne','-'+(slo/Math.max(1,Lo.length)).toFixed(2)+
     '&nbsp;$','neg')+
    SR('Gains / pertes',slo>0?(sw/slo).toFixed(2):'&#8734;',
     sw>=slo?'pos':'neg')+
    SR('Meilleure s&eacute;rie',bs+' gains de suite','pos'));
  }
  if(d.fights&&d.fights.length){
   const f0=d.fights[0];
   if(window._lf===undefined){window._lf=f0.t;}
   else if(f0.t>window._lf){window._lf=f0.t;
    if(f0.res==='gagne'){
     confetti(['⚔️','🏆','✨',
      '🪙']);}}
   document.getElementById('fights-sec').style.display='block';
   const fe=document.getElementById('fights');
   fe.style.display='block';
   fe.innerHTML=d.fights.map(x=>{
    const dt=new Date(x.t*1000);
    const when=String(dt.getDate()).padStart(2,'0')+'/'+
     String(dt.getMonth()+1).padStart(2,'0')+' '+
     String(dt.getHours()).padStart(2,'0')+':'+
     String(dt.getMinutes()).padStart(2,'0');
    const badge=x.res==='gagne'
     ?'<span style="background:rgba(46,204,113,.18);color:#8df0bb;'+
      'padding:2px 9px;border-radius:99px;font-size:.72rem;'+
      'font-weight:700">GAGN&Eacute;</span>'
     :(x.res==='perdu'
      ?'<span style="background:rgba(255,92,92,.16);color:#ff9c9c;'+
       'padding:2px 9px;border-radius:99px;font-size:.72rem;'+
       'font-weight:700">PERDU</span>'
      :'<span style="background:rgba(255,255,255,.1);color:#9fb2c4;'+
       'padding:2px 9px;border-radius:99px;font-size:.72rem;'+
       'font-weight:700">NUL</span>');
    const after=x.book<=0.5
     ?'<span style="color:#8df0bb">livre sold&eacute; &#10024;</span>'
     :'reste '+x.book.toFixed(2)+'&nbsp;$ &agrave; rattraper';
    return '<div class="row"><span style="display:flex;'+
     'flex-direction:column;gap:3px"><span>'+badge+
     ' <span style="color:#6f93b5;font-size:.82rem">'+
     x.lot.toFixed(2)+' lot &middot; '+when+'</span></span>'+
     '<span style="font-size:.75rem;color:#5f7185">'+after+
     '</span></span><b class="'+(x.pnl>=0?'pos':'neg')+'">'+
     (x.pnl>=0?'+':'-')+Math.abs(x.pnl).toFixed(2)+' $</b></div>';
   }).join('');
  }
  if(d.trades&&!d.trades.length){
   document.getElementById('hist').innerHTML=
    '<div class="empty"><i>&#129417;</i>'+
    '<p>Aucun trade encore &mdash; le robot chasse</p></div>';
  }
  if(d.trades&&d.trades.length){
   window._tr=d.trades;
   const N=window._trN||10;
   setH(document.getElementById('hist'),
    d.trades.slice(0,N).map((x,i)=>
    '<div class="row" style="cursor:pointer" data-i="'+i+
    '" onclick="tradeSheet(this.dataset.i)"><span class="rowt">'+x.w+
    (x.k?' &middot; '+(x.k==='soldat'?'&#9876;&#65039; soldat'
     :(x.k==='page'?'normal':x.k)):'')+
    (x.dur!=null?' &middot; '+fdur(x.dur):'')+
    '</span><b class="'+
    (x.p>=0?'pos':'neg')+'">'+(x.p>=0?'+':'-')+Math.abs(x.p).toFixed(2)+
    ' $</b></div>').join('')+
    (d.trades.length>N
    ?'<div class="row" style="cursor:pointer;justify-content:center;'+
     'color:#7fb0ff;font-size:.9rem" onclick="window._trN=99;load()">'+
     'Voir plus ('+d.trades.length+')</div>':''));
  }
}
async function load(){
 try{
  const r=await fetch(B+'api?t='+Date.now(),{cache:'no-store'});
  const d=await r.json();
  const s=JSON.stringify(d);
  if(s!==window._lastS){
   window._lastS=s;
   render(d);
   try{localStorage.setItem('owlLast:'+B,s)}catch(e){}
  }
  lastOk=Date.now();ago();
 }catch(e){
  document.getElementById('upd').textContent=
   'hors ligne - nouvel essai...';
  if(!window._offR){window._offR=1;
   try{const c=JSON.parse(
    localStorage.getItem('owlLast:'+B)||'null');
    if(c){render(c);
     document.getElementById('st').innerHTML='&#128244; '+
      '<b>Hors ligne</b> &mdash; derni&egrave;res donn&eacute;es '+
      'connues';}}catch(e2){}}
 }
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
                _ga = json.load(open(os.path.join(
                    DIR, "owl_goal_app.json")))
                if _ga.get("enabled") and _ga.get("milestone"):
                    d["palier"] = float(_ga["milestone"])
                    d["palier_base"] = float(_ga.get("base") or 0)
                elif _ga.get("disabled"):
                    d["palier_off"] = True
            except Exception:
                pass
            try:
                d["trading_paused"] = bool(json.load(open(
                    os.path.join(DIR, "owl_trading_pause.json")))
                    .get("paused"))
            except Exception:
                d["trading_paused"] = False
        # per-account books (2026-09-07): std has its own ledger/
        # fights; family mirrors follow the master's
        _sfx = "_std" if u.get("id") == "std" else ""
        try:
            # war-chest books exist only on the kino/std accounts;
            # the fresh demo (harvest engine) has no ledger card
            if u.get("id") in ("kino", "std") or str(
                    u.get("login")) == str(LOGIN):
                d["ledger"] = json.load(open(os.path.join(
                    DIR, f"owl_ledger{_sfx}.json")))
                d["ledger"]["cap"] = 5.0  # CHEST_FUND_MAX in the bots
            elif u.get("id") == "bos":
                # the Structure Bot keeps its own debt/bullet books
                _bs = json.load(open(os.path.join(
                    DIR, "bos_state.json")))
                d["ledger"] = {
                    "debt": float(_bs.get("debt") or 0.0),
                    "chest": float(_bs.get("chest") or 0.0),
                    "cap": 5.0,
                    "next_lot": 0.03,
                    "need_min": 3.0}  # ~one bullet at typical stop
        except Exception:
            pass
        try:
            # the preregistered forward test - MASTER ONLY (2026-09-07
            # user: the family sees the product, not the lab)
            if not (u.get("id") == "kino"
                    or str(u.get("login")) == str(LOGIN)):
                raise ValueError("not master")
            _ft = json.load(open(os.path.join(
                DIR, "owl_forward_test.json")))
            _fps = []
            with open(os.path.join(DIR, "owl_manual_journal.csv"),
                      encoding="utf-8", errors="replace") as _jf:
                import csv as _csv
                for _r in _csv.DictReader(_jf):
                    if ((_r.get("exit_time_utc") or "")
                            >= _ft["start"]):
                        try:
                            _fps.append(float(
                                _r.get("profit_usd") or 0))
                        except Exception:
                            pass
            _w = sum(1 for x in _fps if x > 0.005)
            _l = sum(1 for x in _fps if x < -0.005)
            d["ftest"] = {
                "n": len(_fps), "target": _ft.get("target", 50),
                "w": _w, "l": _l,
                "net": round(sum(_fps), 2),
                "wr_pass": _ft.get("wr_pass", 0.66)}
        except Exception:
            pass
        try:
            # war-chest fight history belongs to kino/std only -
            # other accounts (fresh, bos, family) have their own
            # systems and must not inherit the master's fights
            if u.get("id") in ("kino", "std") or str(
                    u.get("login")) == str(LOGIN):
                d["fights"] = json.load(open(os.path.join(
                    DIR, f"owl_fight_history{_sfx}.json")))[-12:][::-1]
        except Exception:
            pass
        if u.get("id") == "std":
            try:
                d["trading_paused"] = bool(json.load(open(
                    os.path.join(DIR, "owl_trading_pause_std.json")))
                    .get("paused"))
            except Exception:
                d["trading_paused"] = False
            try:
                _ms2 = json.load(open(os.path.join(
                    DIR, "owl_milestone_std.json")))
                if _ms2.get("enabled") and _ms2.get("milestone"):
                    d["palier"] = float(_ms2["milestone"])
            except Exception:
                pass
            try:
                _ga2 = json.load(open(os.path.join(
                    DIR, "owl_goal_app_std.json")))
                if _ga2.get("enabled") and _ga2.get("milestone"):
                    d["palier"] = float(_ga2["milestone"])
                    d["palier_base"] = float(_ga2.get("base") or 0)
                elif _ga2.get("disabled"):
                    d["palier_off"] = True
            except Exception:
                pass
        try:
            d["push_level"] = json.load(open(PUSH_PREFS_FILE)).get(
                u["id"], "all")
        except Exception:
            d["push_level"] = "all"
        # default weekly objective (+$50 from Monday's balance) so the
        # bar is always alive unless explicitly disabled (2026-09-08)
        try:
            if (not d.get("palier") and not d.get("palier_off")
                    and d.get("balance") is not None):
                _wb = float(d["balance"]) - float(d.get("week") or 0)
                d["palier"] = round(_wb + 50.0, 2)
                d["palier_base"] = round(_wb, 2)
                d["palier_def"] = True
        except Exception:
            pass
        if (u.get("id") in ("kino", "std")
                or str(u.get("login")) == str(LOGIN)):
            d["is_master"] = True
            # v2 Le Nid: one row per member for the master console
            try:
                _rows = []
                for x in json.load(open(USERS_FILE, encoding="utf-8")):
                    _ndp = os.path.join(NEST_DATA, x["id"] + ".json")
                    try:
                        nd = json.load(open(_ndp))
                    except Exception:
                        nd = {}
                    _ppf = ("owl_trading_pause.json"
                            if x.get("id") == "kino"
                            else f"owl_trading_pause_{x['id']}.json")
                    try:
                        _pz = bool(json.load(open(os.path.join(
                            DIR, _ppf))).get("paused"))
                    except Exception:
                        _pz = False
                    try:
                        _age = time.time() - os.path.getmtime(_ndp)
                    except Exception:
                        _age = 9e9
                    _rows.append({
                        "id": x["id"],
                        "name": x.get("name", x["id"]),
                        "login": x.get("login"),
                        "tok": x.get("token"),
                        "bal": nd.get("balance"),
                        "today": nd.get("today"),
                        "err": bool(nd.get("error")),
                        "stale": _age > 60, "paused": _pz,
                        "trade": bool(x.get("trade")
                                      or x.get("id") == "kino"),
                        "plan": x.get("plan")})
                d["nest"] = _rows
            except Exception:
                pass
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

CHART_PAGE = """<!doctype html><html lang="fr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,
maximum-scale=1,user-scalable=no">
<title>Graphique custom</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0b1420;color:#cfe3f5;font-family:system-ui,
-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}
#hd{display:flex;align-items:baseline;gap:10px;padding:12px 14px 8px}
#hd h1{font-size:1.02rem;font-weight:700}
#hd .badge{font-size:.62rem;color:#7fb3e0;background:rgba(127,179,
224,.12);border:1px solid rgba(127,179,224,.3);border-radius:99px;
padding:2px 9px;text-transform:uppercase;letter-spacing:.06em}
#sub{font-size:.7rem;color:#5f7185;padding:0 14px 8px}
#cv{display:block;width:100vw;height:calc(100vh - 64px)}
#px{position:fixed;top:12px;right:14px;font-size:.95rem;
font-variant-numeric:tabular-nums;color:#e8c55a;font-weight:700}
</style></head><body>
<div id="hd">
<a id="back" href="#" style="text-decoration:none;color:#9fc2de;
 font-size:1.35rem;line-height:1;padding:2px 8px 2px 0">&#8592;</a>
<h1>BTCUSD &middot; M1</h1>
<span class="badge">filtre silence</span>
<span class="badge" id="trbadge" style="display:none"></span></div>
<div id="sub">chargement...</div>
<span id="px"></span>
<div id="livedot"></div>
<canvas id="cv"></canvas>
<style>
#livedot{position:fixed;width:10px;height:10px;border-radius:50%;
background:#e8c55a;display:none;pointer-events:none;
animation:ldp 1.2s ease-out infinite}
@keyframes ldp{0%{box-shadow:0 0 0 0 rgba(232,197,90,.55)}
100%{box-shadow:0 0 0 12px rgba(232,197,90,0)}}
</style>
<script>
const tok=location.pathname.split('/').filter(x=>x)[0];
document.getElementById('back').onclick=(e)=>{e.preventDefault();
 if(history.length>1)history.back();else location.href='/'+tok;};
const cv=document.getElementById('cv');
const ctx=cv.getContext('2d');
let D=null,lastPx=null;
function draw(){
 if(!D||!D.candles||!D.candles.length)return;
 const dpr=window.devicePixelRatio||1;
 const W=cv.clientWidth,Hh=cv.clientHeight;
 cv.width=W*dpr;cv.height=Hh*dpr;
 ctx.setTransform(dpr,0,0,dpr,0,0);
 ctx.clearRect(0,0,W,Hh);
 const N=Math.min(D.candles.length,Math.max(60,Math.floor(W/7)));
 const cs=D.candles.slice(-N);
 let lo=Infinity,hi=-Infinity;
 for(const c of cs){if(c[2]>hi)hi=c[2];if(c[3]<lo)lo=c[3];}
 if(D.live){hi=Math.max(hi,D.live[2]);lo=Math.min(lo,D.live[3]);}
 (D.trades||[]).forEach(t=>{
  [t[2],t[3],t[4]].forEach(v=>{
   if(v>0){hi=Math.max(hi,v);lo=Math.min(lo,v);}});});
 const pad=(hi-lo)*0.06||1;hi+=pad;lo-=pad;
 const px=v=>(hi-v)/(hi-lo)*(Hh-26)+8;
 const cw=W/(N+9);   // ~7 empty slots of forward space
 const bw=Math.max(2,Math.min(9,cw*0.62));
 ctx.strokeStyle='rgba(255,255,255,.05)';
 ctx.lineWidth=1;
 for(let g=0;g<5;g++){const y=px(lo+pad+(hi-lo-2*pad)*g/4);
  ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();
  ctx.fillStyle='#3d4f63';ctx.font='10px system-ui';
  ctx.fillText((lo+pad+(hi-lo-2*pad)*g/4).toFixed(0),4,y-3);}
 const xoft={};
 cs.forEach((c,i)=>{
  const x=cw*(i+1);
  xoft[c[0]]=x;
  const up=c[5]===1;
  ctx.strokeStyle=up?'#2ecc71':'#ff5c5c';
  ctx.fillStyle=up?'#2ecc71':'#ff5c5c';
  ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(x,px(c[2]));ctx.lineTo(x,px(c[3]));
  ctx.stroke();
  const y1=px(Math.max(c[1],c[4])),y2=px(Math.min(c[1],c[4]));
  ctx.fillRect(x-bw/2,y1,bw,Math.max(1,y2-y1));
 });
 (D.marks||[]).forEach(m=>{
  const x=xoft[m[0]];
  if(x===undefined)return;
  const up=m[3]===1;
  const col=up?'#2ecc71':'#ff5c5c';
  const y=px(m[1]);
  const isC=m[2]==='choch';
  ctx.strokeStyle=col;
  ctx.lineWidth=isC?1:2;
  if(isC)ctx.setLineDash([3,3]);
  ctx.beginPath();ctx.moveTo(x-20,y);ctx.lineTo(x+20,y);ctx.stroke();
  ctx.setLineDash([]);
  ctx.lineWidth=1;
  if(isC){
   // CHoCH: small open circle on the dashed break line
   ctx.beginPath();ctx.arc(x,y,3.5,0,6.3);ctx.stroke();
  }else{
   // BOS: filled arrow at the break, pointing the new direction
   const s=5,dy2=up?-7:7;
   ctx.fillStyle=col;
   ctx.beginPath();
   ctx.moveTo(x,y+dy2+(up?-s:s));
   ctx.lineTo(x-s,y+dy2+(up?s*0.6:-s*0.6));
   ctx.lineTo(x+s,y+dy2+(up?s*0.6:-s*0.6));
   ctx.closePath();ctx.fill();
  }
 });
 (D.dots||[]).forEach(d=>{
  const x=xoft[d[0]];
  if(x===undefined)return;
  const isLow=d[2]===1;
  const y=px(d[1])+(isLow?9:-9);
  const col=isLow?'#4fd8c8':'#ffb86b';
  const g=ctx.createRadialGradient(x,y,0,x,y,11);
  g.addColorStop(0,col);
  g.addColorStop(0.35,col+'88');
  g.addColorStop(1,col+'00');
  ctx.fillStyle=g;
  ctx.beginPath();ctx.arc(x,y,11,0,6.3);ctx.fill();
  ctx.fillStyle=col;
  ctx.beginPath();ctx.arc(x,y,3,0,6.3);ctx.fill();
  ctx.fillStyle='#ffffff';
  ctx.globalAlpha=0.9;
  ctx.beginPath();ctx.arc(x,y,1.2,0,6.3);ctx.fill();
  ctx.globalAlpha=1;
 });
 const dot=document.getElementById('livedot');
 if(D.live){
  const x=cw*(cs.length+1);
  const c=D.live;
  const up=c[4]>=c[1];
  const col=up?'#2ecc71':'#ff5c5c';
  ctx.strokeStyle=col;ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(x,px(c[2]));ctx.lineTo(x,px(c[3]));
  ctx.stroke();
  const y1=px(Math.max(c[1],c[4])),y2=px(Math.min(c[1],c[4]));
  ctx.globalAlpha=0.35;
  ctx.fillStyle=col;
  ctx.fillRect(x-bw/2,y1,bw,Math.max(1,y2-y1));
  ctx.globalAlpha=1;
  ctx.strokeStyle='#e8c55a';
  ctx.strokeRect(x-bw/2,y1,bw,Math.max(1,y2-y1));
  const yc=px(c[4]);
  const r=cv.getBoundingClientRect();
  dot.style.display='block';
  dot.style.left=(r.left+x-5)+'px';
  dot.style.top=(r.top+yc-5)+'px';
 }else{dot.style.display='none';}
 const tag=(y,txt,col,bg)=>{
  ctx.font='bold 9px system-ui';
  const w=ctx.measureText(txt).width+10;
  ctx.fillStyle=bg;
  ctx.beginPath();
  ctx.roundRect(W-w-4,y-8,w,16,8);ctx.fill();
  ctx.fillStyle=col;
  ctx.fillText(txt,W-w+1,y+3.5);};
 (D.trades||[]).forEach(t=>{
  const man=t[6]==='m';
  const yE=px(t[2]);
  ctx.strokeStyle=man?'rgba(232,197,90,.85)':'rgba(127,179,224,.8)';
  ctx.setLineDash([7,4]);
  ctx.beginPath();ctx.moveTo(0,yE);ctx.lineTo(W,yE);ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle=t[0]===1?'#2ecc71':'#ff5c5c';
  const s=5;
  ctx.beginPath();
  if(t[0]===1){ctx.moveTo(8,yE-2-s);ctx.lineTo(8-s,yE-2+s*0.6);
   ctx.lineTo(8+s,yE-2+s*0.6);}
  else{ctx.moveTo(8,yE+2+s);ctx.lineTo(8-s,yE+2-s*0.6);
   ctx.lineTo(8+s,yE+2-s*0.6);}
  ctx.closePath();ctx.fill();
  tag(yE,(man?'\\u270B ':'\\u{1F916} ')+
   (t[0]===1?'\\u25b2 ':'\\u25bc ')+t[1].toFixed(2)+
   (t[5]>=0?'  +':'  ')+t[5].toFixed(2)+' $',
   '#cfe3f5',man?'rgba(232,197,90,.28)':'rgba(127,179,224,.25)');
  if(t[3]>0){const y=px(t[3]);
   ctx.strokeStyle='rgba(255,92,92,.75)';
   ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();
   tag(y,'SL '+t[3].toFixed(0),'#ffd7d7','rgba(255,92,92,.3)');}
  if(t[4]>0){const y=px(t[4]);
   ctx.strokeStyle='rgba(46,204,113,.75)';
   ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();
   tag(y,'TP '+t[4].toFixed(0),'#d2f5e0','rgba(46,204,113,.3)');}
 });
 if(D.px){const y=px(D.px);
  if(y>0&&y<Hh){ctx.strokeStyle='rgba(232,197,90,.55)';
   ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(0,y);
   ctx.lineTo(W,y);ctx.stroke();ctx.setLineDash([]);}}
 document.getElementById('sub').textContent=
  cs.length+' bougies affich\\u00e9es \\u00b7 '+
  (D.raw-D.kept)+' silenc\\u00e9es sur '+D.raw+' (M1)';
 const tb=document.getElementById('trbadge');
 tb.style.display='inline-block';
 const wound=D.choch?' \\u00b7 choc!':'';
 if(D.trend===1){tb.textContent='\\u25b2 haussier'+wound;
  tb.style.color='#2ecc71';
  tb.style.borderColor='rgba(46,204,113,.45)';
  tb.style.background='rgba(46,204,113,.1)';}
 else if(D.trend===-1){tb.textContent='\\u25bc baissier'+wound;
  tb.style.color='#ff5c5c';
  tb.style.borderColor='rgba(255,92,92,.45)';
  tb.style.background='rgba(255,92,92,.1)';}
 else{tb.textContent='\\u2012 neutre';
  tb.style.color='#8fa1b3';
  tb.style.borderColor='rgba(143,161,179,.35)';
  tb.style.background='rgba(143,161,179,.08)';}
 const pe=document.getElementById('px');
 if(D.px){
  pe.textContent=D.px.toFixed(0)+' $';
  if(lastPx!==null&&D.px!==lastPx){
   pe.style.color=D.px>lastPx?'#2ecc71':'#ff5c5c';
   setTimeout(()=>{pe.style.color='#e8c55a'},600);}
  lastPx=D.px;}
}
async function load(){
 try{
  const r=await fetch('/'+tok+'/chart_data',{cache:'no-store'});
  if(r.ok){D=await r.json();draw();}
 }catch(e){}
}
window.addEventListener('resize',draw);
load();setInterval(load,3000);
</script></body></html>"""

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
    if rate_limited(("login", login)):
        return ("page", _join_result(
            "&#9203; Trop d&#8217;essais",
            "<p>Attendez 10 minutes puis r&eacute;essayez.</p>"))
    u = next((x for x in users()
              if str(x.get("login")) == login
              or str(x.get("mt5_login") or "") == login), None)
    if u is not None:
        if (u.get("mt5_password") or "") == pwd:
            return ("redirect", f"https://owltrader.duckdns.org/"
                                f"{u['token']}/")
        rate_fail(("login", login))
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
        if len(_parts) == 2 and _parts[1] == "set_goal":
            # master sets the Objectif bar target (pwd gated)
            u = user_by_token(_parts[0])
            if not is_admin(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _up5
                _f5 = _up5.parse_qs(self.rfile.read(ln)
                                    .decode("utf-8", "replace"))
                _pw = (_f5.get("pwd", [""])[0] or "").strip()
                if not master_pwd_ok(_pw):
                    self._send(json.dumps({"ok": False,
                                           "err": "bad password"}),
                               "application/json")
                    return
                try:
                    _amt = float(_f5.get("amount", ["0"])[0] or 0)
                except Exception:
                    _amt = 0.0
                _gs = "_std" if u.get("id") == "std" else ""
                # the app's own goal store - the bot's auto milestone
                # manager can't overwrite this one (2026-09-07).
                # base = balance at set time, so the bar measures the
                # JOURNEY from here to the goal, not absolute level
                _base = 0.0
                try:
                    _base = float(json.load(open(os.path.join(
                        NEST_DATA, u["id"] + ".json")))
                        .get("balance") or 0.0)
                except Exception:
                    pass
                json.dump({"enabled": _amt > 0,
                           "disabled": _amt <= 0,
                           "milestone": round(_amt, 2),
                           "base": round(_base, 2)},
                          open(os.path.join(
                              DIR, f"owl_goal_app{_gs}.json"), "w"))
                self._send(json.dumps({"ok": True, "goal": _amt}),
                           "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "nest_invite":
            # master creates a real-account invite code (pwd gated)
            u = user_by_token(_parts[0])
            if not is_admin(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _up4
                _pw = (_up4.parse_qs(self.rfile.read(ln)
                                     .decode("utf-8", "replace"))
                       .get("pwd", [""])[0] or "").strip()
                if not master_pwd_ok(_pw):
                    self._send(json.dumps({"ok": False,
                                           "err": "bad password"}),
                               "application/json")
                    return
                import secrets as _sec4
                _alph = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
                _code = "".join(_sec4.choice(_alph) for _ in range(6))
                _ipath = os.path.join(DIR, "owl_invites.json")
                try:
                    _iv = json.load(open(_ipath, encoding="utf-8"))
                except Exception:
                    _iv = {"codes": {}}
                _iv.setdefault("codes", {})[_code] = {
                    "used": False, "t": time.time(), "by": "app"}
                json.dump(_iv, open(_ipath, "w", encoding="utf-8"))
                self._send(json.dumps({"ok": True, "code": _code}),
                           "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "nest_pause":
            # master pauses/resumes any member (master pwd gated)
            u = user_by_token(_parts[0])
            if not is_admin(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _up3
                _f3 = _up3.parse_qs(self.rfile.read(ln)
                                    .decode("utf-8", "replace"))
                _pw = (_f3.get("pwd", [""])[0] or "").strip()
                _uid = (_f3.get("uid", [""])[0] or "").strip()
                _on = (_f3.get("on", ["1"])[0] == "1")
                if not master_pwd_ok(_pw):
                    self._send(json.dumps({"ok": False,
                                           "err": "bad password"}),
                               "application/json")
                    return
                us = json.load(open(USERS_FILE, encoding="utf-8"))
                if not any(x.get("id") == _uid for x in us):
                    self._send(json.dumps({"ok": False,
                                           "err": "no such user"}),
                               "application/json")
                    return
                _ppf = ("owl_trading_pause.json" if _uid == "kino"
                        else f"owl_trading_pause_{_uid}.json")
                json.dump({"paused": _on, "by": "master",
                           "t": time.time()},
                          open(os.path.join(DIR, _ppf), "w"))
                self._send(json.dumps({"ok": True, "paused": _on}),
                           "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "push_pref":
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _up2
                lvl = _up2.parse_qs(
                    self.rfile.read(ln).decode("utf-8", "replace")
                ).get("level", ["all"])[0]
                if lvl not in ("all", "important"):
                    lvl = "all"
                try:
                    prefs = json.load(open(PUSH_PREFS_FILE))
                except Exception:
                    prefs = {}
                prefs[u["id"]] = lvl
                json.dump(prefs, open(PUSH_PREFS_FILE, "w"))
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
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
            if not is_admin(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(ln).decode("utf-8", "replace")
                import urllib.parse as _up
                _pw = (_up.parse_qs(body).get("pwd", [""])[0] or "").strip()
                if not master_pwd_ok(_pw):
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
            if not pwd_ok(u, _pwd):
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
        elif sub == "chart":
            # aura redesign 2026-09-08 lives in its own file; the
            # inline constant is only the fallback
            try:
                self._send(open(os.path.join(
                    DIR, "owl_chart_page.html"),
                    encoding="utf-8").read(),
                    "text/html; charset=utf-8")
            except Exception:
                self._send(CHART_PAGE, "text/html; charset=utf-8")
        elif sub == "chart_data":
            try:
                self._send(open(os.path.join(
                    DIR, "owl_chart_btc.json")).read(),
                    "application/json")
            except Exception:
                self._send("{}", "application/json")
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
