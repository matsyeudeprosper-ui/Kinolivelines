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
import json, math, os, sys, time, secrets, struct, threading, zlib
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np
import MetaTrader5 as mt5
import owl_package as PKG
import owl_share as SHARE   # 2026-10-03 (owner): the profit share
import re

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


def owl_icon(n, maskable=False):
    if maskable:
        # maskable icons must keep their subject inside the inner 80%
        # "safe zone"; draw the owl at 68% and centre it on the background
        m = int(n * 0.68)
        inner = _owl_arr(m)
        a = np.zeros((n, n, 3), np.uint8)
        a[:, :] = (13, 17, 23)
        o = (n - m) // 2
        a[o:o + m, o:o + m] = inner
        return _png(np.ascontiguousarray(a))
    return _png(_owl_arr(n))


def _owl_arr(n):
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
    return np.ascontiguousarray(a)


ICON192 = owl_icon(192)
ICON512 = owl_icon(512)
ICON512M = owl_icon(512, maskable=True)

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
        {"src": "icon512m.png", "sizes": "512x512", "type": "image/png",
         "purpose": "maskable"},
    ],
    # 2026-09-28 (owner): Graphique / Signal / Historique from the launcher
    "shortcuts": [
        {"name": "Graphique", "url": "./chart",
         "icons": [{"src": "icon192.png", "sizes": "192x192"}]},
        {"name": "Signal", "url": "./chart?sig=1",
         "icons": [{"src": "icon192.png", "sizes": "192x192"}]},
        {"name": "Historique", "url": "./#hist",
         "icons": [{"src": "icon192.png", "sizes": "192x192"}]},
    ],
    # 2026-09-27: OwlNest can be a share destination (a screenshot, a note)
    "share_target": {"action": "share", "method": "POST",
                     "enctype": "multipart/form-data",
                     "params": {"title": "title", "text": "text", "url": "url",
                                "files": [{"name": "media",
                                           "accept": ["image/*"]}]}},
})

SW = (
    "const OFF='<!doctype html><html lang=fr><head><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\"><title>OwlNest</title><style>body{margin:0;background:#0b0f14;color:#e8eef4;font-family:Inter,-apple-system,Segoe UI,Roboto,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;text-align:center;padding:24px}b{display:block;font-size:1.2rem;margin-bottom:8px}p{color:#8a9bb0;font-size:.95rem;line-height:1.5;margin:0 0 18px}a{display:inline-block;background:#3b82f6;color:#fff;text-decoration:none;padding:12px 22px;border-radius:12px;font-weight:700}</style></head><body><div><b>Pas de connexion</b><p>Le hibou n\\'arrive pas &agrave; joindre le serveur. V&eacute;rifiez votre r&eacute;seau, puis r&eacute;essayez.</p><a href=\"javascript:location.reload()\">R&eacute;essayer</a></div></body></html>';"
    "self.addEventListener('install',e=>{self.skipWaiting();"
    "e.waitUntil(caches.open('owl1').then(c=>Promise.allSettled(['./','chart','manifest.json','icon192.png','/fonts/inter.woff2']"
    ".map(u=>fetch(u).then(r=>{if(r&&r.ok)return c.put(u,r);}).catch(()=>{})))));});"
    "self.addEventListener('activate',e=>e.waitUntil("
    "clients.claim()));"
    "self.addEventListener('fetch',e=>{"
    "if(e.request.method==='GET'&&(/\\/fonts\\//.test(e.request.url)||/icon\\d+m?\\.png$/.test(e.request.url))){"
    "e.respondWith(caches.match(e.request).then(m=>m||fetch(e.request).then(r=>{if(r&&r.ok){const cp=r.clone();caches.open('owl1').then(c=>c.put(e.request,cp));}return r;})));return;}"
    "if(e.request.mode==='navigate'&&!/owlnest\\.apk|apk\\.json/.test(e.request.url)){"
    "e.respondWith(caches.match(e.request).then(m=>{"
    "const net=fetch(e.request).then(r=>{if(r&&r.ok){const cp=r.clone();"
    "caches.open('owl1').then(c=>c.put(e.request,cp));}return r;}).catch(()=>null);"
    "if(m){net.catch(()=>{});return m;}"
    "return net.then(r=>r||new Response(OFF,{headers:{'Content-Type':'text/html;charset=utf-8'}}));}));}});"
    "self.addEventListener('message',e=>{if(e.data&&e.data.type==='refresh'){"
    "e.waitUntil(fetch(e.data.url,{cache:'no-store'}).then(r=>{if(r&&r.ok){"
    "return caches.open('owl1').then(c=>c.put(e.data.url,r.clone()));}}).catch(()=>{})"
    ".then(()=>{if(e.source)e.source.postMessage({type:'refreshed'});}));}});"
    "self.addEventListener('push',e=>{let d={};"
    "try{d=e.data.json()}catch(x){}"
    "e.waitUntil(self.registration.showNotification("
    "d.title||'OwlNest',{body:d.body||'',icon:'icon192.png',"
    "badge:'icon192.png',tag:d.tag||'owl',renotify:true,"
    "data:{url:d.url||''},image:d.image||undefined,"
    "vibrate:[80,40,80]}));});"
    "self.addEventListener('notificationclick',e=>{"
    "e.notification.close();"
    "const u=(e.notification.data&&e.notification.data.url)||'';"
    "e.waitUntil(clients.matchAll({type:'window',"
    "includeUncontrolled:true}).then(cs=>{"
    "for(const c of cs){if('focus' in c){if(u&&c.navigate){return c.navigate(u).then(w=>w&&w.focus()).catch(()=>c.focus());}return c.focus();}}"
    "return clients.openWindow(u||'.');}));});")

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


MANUAL_MODES = ("manual", "semi")

# ---- 2026-09-27: the commercial model (owner, decisions delegated) ----
# family    : the owner's circle - everything, no payment (activation code)
# manual    : the signal service + the trade tool, 30 days (NOWPayments)
# strategy  : manual + the full chart view + the method in words, 30 days
# auto      : copy of the owner's account on MQL5 Signals (link only)
ENT_FILE = os.path.join(DIR, "owl_entitlements.json")
PAY_FILE = os.path.join(DIR, "owl_payments.json")
PACKAGES = {"manual": {"usd": 15, "days": 30, "label": "Signal"},   # 2026-10-03 (owner): Manuel -> Signal   *** TEMPORARY $3 for the real-money test (2026-10-04) - put back 29 ***
            "strategy": {"usd": 49, "days": 30, "label": "Strat\u00e9gie"}}   # separate packages, they combine
MANUAL_CAP = 100000      # 2026-10-04: Signal is app-only now - no terminal, no cap
FAMILY_CAP = 50          # 2026-10-03 (owner): at most 50 family (Automatique) accounts on this VPS


def _ents():
    try:
        e = json.load(open(ENT_FILE, encoding="utf-8"))
        return e if isinstance(e, dict) else {}
    except Exception:
        return {}


def ent(uid):
    return _ents().get(uid) or {}


FAMILY_DAYS = 30
OWNER_UIDS = ("kino", "std", "expenses")


def family_active(e, now=None):
    """2026-09-27 (owner): family = the Automatique package settled with the
    owner directly, 30 days at a time, renewed with a code. An old boolean
    'family' record still counts (grandfathered until it is dated)."""
    now = now or time.time()
    # 2026-10-03 (owner): with the profit share on, the package has no
    # end date - it runs while the monthly statements are settled
    if SHARE.on() and (e.get("family") or e.get("family_until")):
        return not e.get("share_blocked")
    if e.get("family_until"):
        return float(e["family_until"]) > now
    return bool(e.get("family"))


def has(uid, key):
    """2026-09-28 (owner): three separate keys.
    family   = the Automatique package (robot on the account) -> also manual
    manual   = signals + trade tool
    strategy = the full chart + the method - its own package, never
               included in family or manual, and not including them."""
    if uid in OWNER_UIDS:
        return True
    e = ent(uid)
    now = time.time()
    if key == "family":
        return family_active(e, now)
    if key == "manual":
        return family_active(e, now) or float(e.get("manual_until") or 0) > now
    if key == "strategy":
        return float(e.get("strategy_until") or 0) > now
    return False


def ent_grant(uid, pkg, days, src):
    """Extend from the later of now / the current end (a renewal adds)."""
    e = _ents()
    r = e.get(uid) or {}
    k = pkg + "_until"
    base = max(time.time(), float(r.get(k) or 0))
    r[k] = int(base + days * 86400)
    if pkg == "family":
        r["family"] = True           # legacy flag, kept in step with the date
    r["updated"] = int(time.time())
    r["src"] = src
    e[uid] = r
    json.dump(e, open(ENT_FILE + ".tmp", "w", encoding="utf-8"), indent=1)
    os.replace(ENT_FILE + ".tmp", ENT_FILE)
    return r


def ent_family(uid, on=True):
    """Revoke (on=False) or grant a family period (on=True -> +FAMILY_DAYS)."""
    if on:
        return ent_grant(uid, "family", FAMILY_DAYS, "code")
    e = _ents()
    r = e.get(uid) or {}
    r["family"] = False
    r["family_until"] = 0
    r["updated"] = int(time.time())
    e[uid] = r
    json.dump(e, open(ENT_FILE + ".tmp", "w", encoding="utf-8"), indent=1)
    os.replace(ENT_FILE + ".tmp", ENT_FILE)


def manual_seats():
    """Accounts running (or entitled to run) a desk right now."""
    try:
        us = json.load(open(USERS_FILE, encoding="utf-8"))
    except Exception:
        us = []
    return sum(1 for u in us if u.get("mode") in MANUAL_MODES)


SIGMARK_FILE = lambda uid: os.path.join(DIR, f"owl_sigmarks_{uid}.json")
WAIT_FILE = os.path.join(DIR, "owl_waitlist.json")


def sig_marks(uid):
    try:
        m = json.load(open(SIGMARK_FILE(uid), encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def sig_merge(uid, lst):
    """2026-09-28: apply the member's own marks (J'ai pris / Pas pris /
    result) - kept in a separate file so the desk never overwrites them.
    Members trading on another broker have no MT5 account here, so the
    desk cannot detect their trades: this is the only way their signals
    get a result."""
    m = sig_marks(uid)
    for x in lst:
        mk = m.get(str(x.get("t")))
        if not isinstance(mk, dict):
            continue
        if mk.get("taken"):
            x["taken"] = x.get("taken") or "manual"
            x["taken_manual"] = True
        elif mk.get("taken") is False:
            x["skipped"] = True
        if mk.get("result") is not None and "result" not in x:
            x["result"] = mk["result"]
    return lst


def sig_score(uid, era=0):
    """This month's signal numbers for one manual member (UTC month)."""
    try:
        import calendar as _cal
        lst = json.load(open(os.path.join(DIR, f"owl_signals_{uid}.json"), encoding="utf-8"))
        lst = sig_merge(uid, [x for x in lst if isinstance(x, dict) and (not era or x.get("t", 0) >= era)])
        _g = time.gmtime()
        m0 = _cal.timegm((_g.tm_year, _g.tm_mon, 1, 0, 0, 0, 0, 0, 0))
        sc = {"sent": 0, "taken": 0, "wins": 0, "losses": 0, "net": 0.0}
        for x in lst:
            if not x.get("ok") or x.get("t", 0) < m0:
                continue
            sc["sent"] += 1
            if x.get("taken"):
                sc["taken"] += 1
                r = x.get("result")
                if isinstance(r, (int, float)):
                    sc["net"] += float(r)
                    if r >= 0:
                        sc["wins"] += 1
                    else:
                        sc["losses"] += 1
        sc["net"] = round(sc["net"], 2)
        return sc
    except Exception:
        return None


def waitlist():
    try:
        w = json.load(open(WAIT_FILE, encoding="utf-8"))
        return w if isinstance(w, dict) else {}
    except Exception:
        return {}


def member_lang(uid):
    """The phone's language (push_pref lang=), default fr."""
    try:
        return (json.load(open(os.path.join(DIR, "owl_push_prefs.json"), encoding="utf-8"))
                .get("_lang") or {}).get(uid, "fr")
    except Exception:
        return "fr"


def _push_subs():
    try:
        m = json.load(open(PUSH_SUBS_FILE, encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def can_switch(u):
    """May this account switch auto <-> manual (and use the trade tool)?
    2026-10-03 (owner): the admin only - members no longer trade by hand
    from the app; the Signal package is the signals on their phone."""
    return u is not None and is_admin(u)


def plan_of(u):
    e = ent(u.get("id"))
    cfg = nest_config()
    return {"family": family_active(e) or u.get("id") in OWNER_UIDS,
            "family_until": int(e.get("family_until") or 0),
            "family_expired": bool(e.get("family_until")) and float(e["family_until"]) <= time.time(),
            "manual": has(u.get("id"), "manual"),
            "strategy": has(u.get("id"), "strategy"),
            "manual_until": int(e.get("manual_until") or 0),
            "strategy_until": int(e.get("strategy_until") or 0),
            "packages": PACKAGES,
            "seats_left": max(0, MANUAL_CAP - manual_seats()),
            "waitlisted": u.get("id") in waitlist(),
            "pay_ready": bool(cfg.get("np_api_key")),
            "mql5_url": cfg.get("mql5_url") or "",
            "contact_url": cfg.get("contact_url") or "",     # the Owl on Telegram
            "pending_pay": bool(u.get("pending_pay")),
            # 2026-10-04 (owner): recovery through the Telegram bot
            "tg_linked": bool(u.get("telegram_chat")),
            "tg_bot": nest_config().get("tg_bot") or "Kino_owl_bot",
            "app_account": bool(u.get("app_only") or u.get("app_login") or u.get("app_pwd")),
            # 2026-10-03 (owner): the member's share statement (robot accounts only)
            "share": (SHARE.statement(u.get("id")) if (SHARE.on() and u.get("id") in SHARE.eligible()) else None),
            # 2026-10-03 (owner): the one-time opening fee, every account type
            "setup": (SHARE.setup_info(u.get("id")) if (u.get("id") not in OWNER_UIDS and not u.get("public")) else None)}
# who may actually switch the bot off (owner 2026-09-16). Everyone else
# sees the row, locked.
# Owner 2026-09-17: the accounts whose owner may switch auto <-> manual.
# "bos" = the live half-manual account. "kino" = the live Pro master,
# added on the owner's request the same day.
# 2026-09-27: "std" = Kino 778, the owner's hand-traded account.
PAUSE_ALLOWED = ("bos", "kino", "std")
# 2026-09-23: the ONLY account that has ever supported manual
# (hand-placed) trading - the other four are pure-auto by design
# with no desk process to swap to. See owl_mode_switch.py.
# 2026-09-27 (owner): "accounts in manual trading mode always have the
# trade tool" - the swap is generic in owl_mode_switch.py now (a desk per
# account; an account without a bot simply runs nothing in auto), so every
# account whose owner may pause it may also switch it.
MODE_SWITCH_ALLOWED = PAUSE_ALLOWED
# 2026-09-24: every account running its own structure_bos_bot.py
# instance - the only ones with a lot/day-cap to scale in the first
# place. The public demo is separately refused ALL actions above
# (view-only), so this only ever matters for the other four in practice.
SCALE_TOGGLE_ALLOWED = ("bos", "kino", "u224016179", "demo", "infinity")


def pause_file(uid):
    """The switch for ONE account.

    Owner 2026-09-17: kino used to write owl_trading_pause.json - the file
    EVERY bot reads as the master kill-all - so unlocking its switch would
    have handed the owner a stop-everything button labelled "manual mode",
    and pausing kino would silently have stopped Valere's real account.
    Kino now has its own per-account file like everyone else; the master
    file keeps its kill-all meaning and no card writes it.
    """
    return f"owl_trading_pause_{uid}.json"


def acct_auto(u):
    """Is this account trading by itself right now?

    Owner 2026-09-17: the chart badge used to read manual_state, which only
    exists for the half-manual desk - so Valere's account (mode=auto, driven
    by structure_bos_bot) showed no robot badge even though it WAS in auto.
    The pause file is the real switch for every account, so read that.
    Same defaults as the settings section: no file means auto, except on the
    accounts allowed to switch, where manual is the safe default.
    """
    if u is None:
        return False
    uid = u.get("id")
    # the Pro master account trades through owl_manual_bot; its record has
    # no "trade" flag because it is not a nest member
    if not u.get("trade") and str(u.get("login")) != str(LOGIN):
        return False
    try:
        paused = bool(json.load(open(os.path.join(DIR, pause_file(uid)),
                                     encoding="utf-8"))
                      .get("paused", uid in PAUSE_ALLOWED))
    except Exception:
        paused = uid in PAUSE_ALLOWED
    if paused:
        return False
    # the master file still stops everyone, whoever set it
    try:
        if json.load(open(os.path.join(DIR, "owl_trading_pause.json"),
                          encoding="utf-8")).get("paused"):
            return False
    except Exception:
        pass
    return True


# account -> (robot's name, the file it keeps fresh, its log)
# The 4th field is how long this robot may stay silent before it counts as
# stopped. They do not all breathe at the same rate: the structure bots
# write every minute, Harvest works on H1 logic and can go ~7 min between
# writes - a single 5-minute rule declared it dead while it was fine
# (owner 2026-09-18).
# 2026-09-27: build id = this file's mtime; the page compares it with the
# one /api reports and offers a reload when they differ.
APP_BUILD = time.strftime("%m%d.%H%M", time.localtime(os.path.getmtime(__file__)))

BOT_OF = {
    # 2026-09-22: this pointed at the RETIRED KINO bot (owl_manual.log,
    # last written 09-18), so the nest list showed Kino as bot KINO / not
    # live while its structure bot was trading all night. Kino has run
    # structure_bos_bot.py kino since 09-18.
    "kino":       ("Structure", "bos_state_kino.json",
                   "bos_bot_kino.log", 300),
    "luc":        ("CROC", "owl_pro_alive.json", "owl_pro.log", 300),
    # 2026-10-01: this one is an HOURLY bot. Its loop polls every 30 s but
    # only writes state when a new H1 bar closes, so a perfectly healthy
    # Harvest H1 looked "robot arrete" for up to half of every hour and the
    # header counted 6 robots instead of 7. 70 minutes is just over its
    # natural cadence. The cost is honest: without a heartbeat you cannot
    # detect an hourly bot dying any faster than it normally speaks.
    "fresh":      ("Harvest H1", "harvest_fresh_state.json",
                   "harvest_fresh.log", 4200),
    # 2026-09-23 (owner): "make 441 behave exactly like the rest, only
    # its daily target differs". It now runs structure_bos_bot.py like
    # Valere and Infinity, so it reads the bot's files, not the desk's.
    "bos":        ("Structure", "bos_state.json", "bos_bot.log", 300),
    "u224016179": ("Structure", "bos_state_valere.json",
                   "bos_bot_valere.log", 300),
    "demo":       ("Structure · démo publique", "bos_state_demo.json",
                   "bos_bot_demo.log", 300),
    "infinity":   ("Structure", "bos_state_infinity.json",
                   "bos_bot_infinity.log", 300),
    # 2026-09-30 (owner): the Expenses account - the profit from this one is
    # the money he takes out to spend, so it is kept apart from the accounts
    # that compound. Same bot, same Valere package.
    "expenses":   ("Structure", "bos_state_expenses.json",
                   "bos_bot_expenses.log", 300),
}
# the broker refusals that mean "alive but cannot trade"
BLOCKED = {"10027": "AutoTrading &eacute;teint", "10019": "solde insuffisant"}


def bot_blocked(log):
    """A robot can be running and still be unable to place a single order.
    CROC looked 'actif' for 7 days while the terminal refused all 1295 of
    its entries (owner 2026-09-18). Read the tail of its log and say so."""
    try:
        p = os.path.join(DIR, log)
        if time.time() - os.path.getmtime(p) > 3600:
            return None                     # not even trying lately
        with open(p, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 2048))
            tail = f.read().decode("utf-8", "replace")
        for code, why in BLOCKED.items():
            if f"retcode={code}" in tail or f"code {code}" in tail:
                return why
    except Exception:
        pass
    return None


def recap_yesterday(uid, days, trades):
    """What the robot did on the UTC day that just closed.

    Owner 2026-10-01: a recap on the first open of a new day. Every number
    here already existed, scattered over three tabs - the day's money in
    the Nid, the trades in the history, and the refusals only in a log
    file nobody reads.
    """
    y = datetime.now(timezone.utc) - timedelta(days=1)
    key = y.strftime("%Y-%m-%d")
    short = y.strftime("%d/%m")
    net = None
    for row in (days or []):
        # the worker writes "jeu 01/10", so match the date part only
        if isinstance(row, dict) and str(row.get("d", "")).endswith(short):
            net = row.get("p")
            break
    if net is None:
        return None
    n = sum(1 for t in (trades or [])
            if str(t.get("w", "")).startswith(short))
    return {"day": short, "net": round(float(net), 2), "n": n,
            "why": why_idle(uid, key)}


# 2026-10-01 (owner): the multi-timeframe payoff. He picked it knowing it
# is not measurable yet, so it is GATED rather than guessed - a verdict
# only once the sample can carry one, a countdown before that. Two cells of
# four trades would make a headline that means nothing, and this desk has
# been wrong twice this week by believing a first half.
HTF_MIN_N = 20        # trades carrying a snapshot
HTF_MIN_CELL = 8      # ... and at least this many on each side of the split


def htf_payoff(uid):
    """Did the trades the big timeframes agreed with actually do better?"""
    m = BOT_OF.get(uid)
    if not m or not m[1].startswith("bos_state"):
        return None
    import csv as _csv
    sfx = m[1][len("bos_state"):-len(".json")]
    f = os.path.join(DIR, "bos_journal" + sfx + ".csv")
    cells = {"all": [], "some": []}
    try:
        with open(f, newline="", encoding="utf-8", errors="replace") as fh:
            for r in _csv.DictReader(fh):
                try:
                    v = json.loads(r.get("htf_entry") or "")
                    pnl = float(r.get("profit_usd"))
                except Exception:
                    continue
                if not isinstance(v, dict):
                    continue
                d = 1 if (r.get("direction") == "BUY") else -1
                ts = [(v.get(k) or {}).get("t") for k in ("m15", "h1", "h4")]
                ts = [t for t in ts if t is not None]
                if len(ts) < 3:
                    continue
                with_me = sum(1 for t in ts if t == d)
                cells["all" if with_me == 3 else "some"].append(pnl)
    except Exception:
        return None
    n = len(cells["all"]) + len(cells["some"])
    if (n < HTF_MIN_N
            or min(len(cells["all"]), len(cells["some"])) < HTF_MIN_CELL):
        return {"ready": False, "n": n, "need": HTF_MIN_N,
                "all_n": len(cells["all"]), "some_n": len(cells["some"]),
                "need_cell": HTF_MIN_CELL}

    def side(v):
        return {"n": len(v),
                "win": round(sum(1 for p in v if p > 0) / len(v) * 100, 1),
                "avg": round(sum(v) / len(v), 2)}
    return {"ready": True, "n": n,
            "all": side(cells["all"]), "some": side(cells["some"])}


def htf_of(uid):
    """The multi-timeframe snapshot per trade, keyed by position id.

    Recorded since 2026-10-01 for pattern work and never shown; the owner
    asked for it on the history row. Only the three higher timeframes and
    the agreement count are kept - the app does not need the levels.
    """
    m = BOT_OF.get(uid)
    if not m or not m[1].startswith("bos_state"):
        return {}
    import csv as _csv          # csv is not imported at module level here
    sfx = m[1][len("bos_state"):-len(".json")]
    f = os.path.join(DIR, "bos_journal" + sfx + ".csv")
    out = {}
    try:
        with open(f, newline="", encoding="utf-8", errors="replace") as fh:
            for r in _csv.DictReader(fh):
                tk = (r.get("ticket") or "").strip()
                if not tk:
                    continue
                row = {}
                for side, col in (("e", "htf_entry"), ("x", "htf_exit")):
                    try:
                        v = json.loads(r.get(col) or "")
                    except Exception:
                        continue
                    if not isinstance(v, dict):
                        continue
                    row[side] = {
                        "m15": (v.get("m15") or {}).get("t"),
                        "h1": (v.get("h1") or {}).get("t"),
                        "h4": (v.get("h4") or {}).get("t"),
                        "agree": v.get("agree"),
                    }
                if row:
                    out[tk] = row
    except Exception:
        return {}
    return out


def day_state(uid):
    """Has this account finished its day, and where is it against its own
    target? (owner 2026-10-01: "all accounts done for the day?")

    day_capped is the bot's own sticky flag, set the first time the daily
    limit refuses an entry and cleared at the UTC day roll. cap_today is
    the ADAPTIVE cap the bot computed for today, which is not the package
    number: it scales with the balance and widens while the account is
    catching up. Both come straight from the bot's state file, so this
    cannot drift from what the bot actually did.
    """
    m = BOT_OF.get(uid)
    if not m or not m[1].startswith("bos_state"):
        return None
    try:
        st = json.load(open(os.path.join(DIR, m[1]), encoding="utf-8"))
    except Exception:
        return None
    cap = st.get("cap_today")
    cap = float(cap) if isinstance(cap, (int, float)) else None
    pnl = float(st.get("day_pnl") or 0.0)
    return {"pnl": round(pnl, 2), "cap": cap, "n": st.get("day_n") or 0,
            "done": bool(st.get("day_capped")
                         or (cap is not None and cap > 0 and pnl >= cap)),
            "killed": bool(st.get("killed")),
            "debt": round(float(st.get("debt") or 0.0), 2)}


# Every one of these strings is copied from structure_bos_bot.py, not
# guessed. Order matters: the first match wins, so the specific ones come
# before the general. `kind` is the bucket shown to a member; two patterns
# can share a bucket.
IDLE_WHY = (
    ("market asleep", "asleep"),
    ("LIMITE DU JOUR", "daycap"),
    ("tres rapide", "storm"),
    ("trop nerveux", "nervous"),
    ("even 0.01 lot risks", "toobig"),
    ("SKIPPED: risk", "toobig"),
    ("structure interne en pause", "recovery"),
    ("demi-lot impossible", "toobig"),
)
IDLE_TXT = {
    "asleep": ("le march\u00e9 dormait \u2014 pas de nouveau mouvement",
               "the market was asleep \u2014 no new move"),
    "daycap": ("l\u2019objectif du jour \u00e9tait atteint",
               "the day\u2019s target was already reached"),
    "storm": ("le march\u00e9 \u00e9tait trop rapide",
              "the market was moving too fast"),
    "nervous": ("le march\u00e9 \u00e9tait nerveux",
                "the market was nervous"),
    "toobig": ("le risque d\u00e9passait le plafond du compte",
               "the risk was over the account ceiling"),
    "recovery": ("la petite structure est en pause pendant la reprise",
                 "the small structure pauses during catch-up"),
}


def why_idle(uid, day=None):
    """What stopped the robot today, counted from its own log.

    Owner 2026-10-01: "Pourquoi rien aujourd'hui". The bot has always
    written the reason and the app has never shown it, so a quiet day and
    a broken day looked identical from the phone.
    """
    m = BOT_OF.get(uid)
    if not m:
        return None
    day = day or time.strftime("%Y-%m-%d", time.gmtime())
    counts, inner, took = {}, 0, 0
    try:
        with open(os.path.join(DIR, m[2]), encoding="utf-8",
                  errors="replace") as f:
            for ln in f:
                if not ln.startswith(day):
                    continue
                if "ENTRY:" in ln:
                    took += 1
                    continue
                if "INT note, pas pris" in ln:
                    inner += 1
                    continue
                for pat, kind in IDLE_WHY:
                    if pat in ln:
                        counts[kind] = counts.get(kind, 0) + 1
                        break
    except Exception:
        return None
    top = sorted(counts.items(), key=lambda kv: -kv[1])
    return {"took": took, "inner": inner,
            "why": [{"k": k, "n": n} for k, n in top[:3]],
            "total": sum(counts.values())}


def bot_on(uid):
    """Which robot runs this account, is it alive, and can it trade?

    Owner 2026-09-18: the nest list showed people's names, so "Luc" was
    really the CROC bot and "Kino (manuel)" had no robot at all - the list
    could not tell you what was left after the cleanup. Liveness is read
    from the file each bot publishes, never from a hardcoded table, so a
    bot that dies shows as dead instead of quietly looking fine.
    """
    m = BOT_OF.get(uid)
    if not m:
        return None, False, None
    label, f, log, max_age = m
    try:
        live = (time.time() - os.path.getmtime(
            os.path.join(DIR, f))) < max_age
    except Exception:
        live = False
    # 2026-09-27: a robot at its kill line is alive but will never trade
    # again - say so instead of "actif" (the demo sat like that for hours)
    try:
        if json.load(open(os.path.join(DIR, f))).get("killed"):
            return label, live, "limite de s\u00e9curit\u00e9"
    except Exception:
        pass
    return label, live, (bot_blocked(log) if live else None)


def public_user():
    """The showcase account (owner 2026-09-19): opened from the front door
    without a password, so everyone can watch the bot work. None if no
    record carries public=True."""
    try:
        for x in json.load(open(USERS_FILE, encoding="utf-8")):
            if x.get("public") and x.get("token"):
                return x
    except Exception:
        pass
    return None


def manual_ok(u):
    """2026-09-15 (owner): the trade tool belongs to the ACCOUNT's mode.
    An account running full automation never gets it; one switched to
    manual or semi-manual drives itself from its own page."""
    return (u is not None and u.get("mode") in MANUAL_MODES
            and is_admin(u))          # 2026-10-03 (owner): admin only


def master_pwd_ok(pw):
    """Master actions always validate against the KINO record's
    broker password, whichever admin page they come from."""
    k = next((x for x in users() if x.get("id") == "kino"), None)
    return k is not None and pwd_ok(k, pw)


# 2026-09-23 (owner): "the nid menu must not exist for all but me."
# is_master was tied to WHICH ACCOUNT's page is open (the Owl's own token),
# not to WHO is looking - so viewing any other member's page hid Le Nid
# even for the owner. This is a real access control on other people's
# balances (Valere, Infinity, ... are not the owner), so unlocking it is
# a SERVER-VERIFIED secret, not a client-side flag anyone could set on
# their own account's page.
ADMIN_TOKENS_FILE = os.path.join(DIR, "owl_admin_tokens.json")
ADMIN_COOKIE = "owl_admin"
ADMIN_MAX_AGE = 180 * 86400        # 180 days


def _admin_tokens():
    try:
        return json.load(open(ADMIN_TOKENS_FILE, encoding="utf-8"))
    except Exception:
        return {}


def issue_admin_cookie():
    toks = _admin_tokens()
    secret = secrets.token_urlsafe(24)
    toks[secret] = time.time()
    # prune anything already expired so this file cannot grow forever
    toks = {k: v for k, v in toks.items() if time.time() - v < ADMIN_MAX_AGE}
    toks[secret] = time.time()
    tmp = ADMIN_TOKENS_FILE + ".tmp"
    json.dump(toks, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, ADMIN_TOKENS_FILE)
    return secret


def admin_cookie_ok(headers):
    raw = headers.get("Cookie") or ""
    secret = None
    for part in raw.split(";"):
        part = part.strip()
        if part.startswith(ADMIN_COOKIE + "="):
            secret = part[len(ADMIN_COOKIE) + 1:]
            break
    if not secret:
        return False
    toks = _admin_tokens()
    issued = toks.get(secret)
    return issued is not None and (time.time() - issued) < ADMIN_MAX_AGE


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
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="OwlNest">
<title>OwlNest</title>
<style>
@font-face{font-family:'Inter';src:url('/fonts/inter.woff2') format('woff2');
 font-weight:100 900;font-style:normal;font-display:swap}
:root{--bg:#0b0f14;--surface:#121a25;--surface2:#172130;--surface3:#1d2a3b;
 --border:#1f2a38;--border2:#2b3a4d;--hl:inset 0 1px 0 rgba(255,255,255,.04);
 --text:#e8eef4;--text2:#c6d3df;--text3:#9fc2de;--muted:#8a9bb0;--muted2:#a9b8c8;
 --accent:#3b82f6;--accent-soft:#8fc6ff;--accent-bg:rgba(59,130,246,.14);
 --up:#2ecc71;--up-soft:#8df0bb;--down:#ff5c5c;--down-soft:#ff9a9a;
 --warn:#e8c55a;--r:16px;--r-lg:24px;--hero1:#0f2740;--hero2:#123a63}
:root{--tile-bg:rgba(255,255,255,.035);--tile-bd:rgba(255,255,255,.07);
 --tabbar:rgba(14,20,29,.92)}
:root[data-theme=light]{--bg:#eef2f7;--surface:#ffffff;--surface2:#f6f8fb;
 --surface3:#e6ecf4;--border:#dde4ed;--border2:#c7d2df;
 --hl:inset 0 1px 0 rgba(255,255,255,.7);--text:#0f172a;--text2:#33415a;
 --text3:#46556b;--muted:#5f6f85;--muted2:#4c5b70;--accent:#2563eb;
 --accent-soft:#1d4ed8;--accent-bg:rgba(37,99,235,.10);--up:#15803d;
 --up-soft:#166534;--down:#dc2626;--down-soft:#b91c1c;--warn:#a16207;
 --tile-bg:rgba(15,23,42,.035);--tile-bd:rgba(15,23,42,.08);
 --tabbar:rgba(255,255,255,.9)}
:root[data-theme=light] .hero{--text:#e8eef4;--text2:#c6d3df;--text3:#9fc2de;
 --muted:#8a9bb0;--muted2:#a9b8c8;--up:#2ecc71;--up-soft:#8df0bb;
 --down-soft:#ff9a9a;--warn:#e8c55a;--accent-soft:#8fc6ff}
:root[data-theme=light] .skel{background:#dfe6ef!important}
:root[data-theme=light] #sheetbg,:root[data-theme=light] #tourbg{
 background:rgba(15,23,42,.45)}
*{box-sizing:border-box;margin:0}
/* 2026-10-01: the tab bar measures 65px and adds its own
   env(safe-area-inset-bottom). A fixed 96px was 31px too much on a
   flat screen and ~3px too LITTLE on a phone with a home indicator,
   where the bar grows to ~99px and clips the last card. Track it. */
body{background:var(--bg);color:var(--text);
 padding:0 0 calc(78px + env(safe-area-inset-bottom,0px));
 font-family:'Inter',-apple-system,'Segoe UI',Roboto,sans-serif;
 font-feature-settings:'tnum' 1,'cv11' 1;
 -webkit-font-smoothing:antialiased}
.ic{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:1.9;
 stroke-linecap:round;stroke-linejoin:round;flex:none;vertical-align:-4px}
.ic-s{width:16px;height:16px}
.brandmk{width:22px;height:22px;border-radius:6px;vertical-align:-5px;
 margin-right:6px}
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
@media(prefers-reduced-motion:reduce){*{animation:none!important;
 transition:none!important}}
.tabbar{position:fixed;left:0;right:0;bottom:0;z-index:30;
 display:flex;max-width:480px;margin:0 auto;
 background:var(--tabbar);backdrop-filter:blur(14px);
 -webkit-backdrop-filter:blur(14px);
 border-top:1px solid var(--border);border-radius:20px 20px 0 0;
 padding:6px 8px calc(8px + env(safe-area-inset-bottom,0px))}
.tb{flex:1;background:none;border:0;color:var(--muted);font-size:.76rem;
 font-weight:600;display:flex;flex-direction:column;min-height:48px;
 align-items:center;justify-content:center;gap:4px;padding:6px 0;
 border-radius:12px;cursor:pointer;transition:color .15s,background .15s}
.tb .ic{width:22px;height:22px}
.tb.on{color:var(--accent-soft);background:var(--accent-bg)}
.srow{display:flex;align-items:center;gap:13px;padding:14px 2px;
 min-height:56px;border-bottom:1px solid var(--border);cursor:pointer;
 color:var(--text)}
.srow:last-child{border-bottom:0}
.srow b{font-weight:600;font-size:.97rem}
.sic{width:38px;height:38px;border-radius:10px;background:var(--surface3);
 color:var(--accent-soft);display:flex;align-items:center;
 justify-content:center;font-size:1.15rem;flex:none}
.chv{color:var(--muted);width:18px;height:18px}
.ssub{font-size:.82rem;color:var(--muted);margin-top:2px}
.hero{background:linear-gradient(165deg,var(--hero1) 0%,var(--hero2) 100%);
 color:#fff;padding:20px 22px 40px;border-radius:0 0 28px 28px;
 text-align:center;position:relative;overflow:hidden;
 box-shadow:inset 0 -1px 0 rgba(255,255,255,.05)}
.hero>*{position:relative}
.chips{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;
 margin-top:12px}
.chips:empty{display:none}
.glass{position:relative;overflow:hidden;border-radius:var(--r-lg);
 background:linear-gradient(135deg,rgba(255,255,255,.10),rgba(255,255,255,.03));
 backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
 border:1px solid rgba(255,255,255,.14);
 box-shadow:0 12px 34px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.14);
 transition:transform .12s ease}
.glass:active{transform:scale(.99)}
.glass .sheen{position:absolute;left:-20%;top:-60%;width:140%;height:120%;
 background:radial-gradient(ellipse at 30% 0,rgba(143,198,255,.20),transparent 55%);
 pointer-events:none}
.orbsm{width:44px;height:44px;border-radius:50%;flex:none;display:flex;
 align-items:center;justify-content:center;
 background:radial-gradient(circle at 35% 30%,rgba(255,255,255,.16),rgba(255,255,255,.04));
 border:1px solid rgba(255,255,255,.12)}
:root[data-theme=light] .glass{background:linear-gradient(135deg,rgba(255,255,255,.85),rgba(255,255,255,.55));
 border-color:rgba(15,23,42,.08);box-shadow:0 12px 30px rgba(15,23,42,.10),inset 0 1px 0 #fff}
:root[data-theme=light] .orbsm{background:rgba(15,23,42,.05);border-color:rgba(15,23,42,.1)}
.jsteps{position:relative;display:flex;justify-content:space-between;
 margin-top:14px;padding:0 6px}
.jsteps .jl{position:absolute;left:28px;right:28px;top:19px;height:2px;
 background:var(--border2);border-radius:2px}
.js{position:relative;display:flex;flex-direction:column;align-items:center;
 gap:7px;width:60px;font-size:.7rem;font-weight:600;color:var(--muted)}
.js .jc{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;
 justify-content:center;background:var(--surface3);border:1px solid var(--border2);
 color:var(--muted2);transition:all .25s}
.js.on{color:var(--accent-soft)}
.js.on .jc{background:var(--accent);border-color:var(--accent);color:#fff;
 box-shadow:0 0 0 0 rgba(59,130,246,.5);animation:jp 2.2s ease-out infinite}
@keyframes jp{0%{box-shadow:0 0 0 0 rgba(59,130,246,.45)}
 70%{box-shadow:0 0 0 10px rgba(59,130,246,0)}100%{box-shadow:0 0 0 0 rgba(59,130,246,0)}}
.js.done .jc{color:var(--up)}
#ib-list .srow-ev>button{opacity:.5;font-size:.9rem}
#ib-list .evi{background:var(--tile-bg);border:1px solid var(--tile-bd)}
#tfilt .tfc,#ib-list ~ * .ibf{border-color:transparent}
.srow-ev{display:flex;align-items:flex-start;gap:11px;padding:10px 2px;
 border-bottom:1px solid var(--border);font-size:.92rem;line-height:1.4}
.srow-ev:last-child{border-bottom:0}
.srow-ev .evi{width:30px;height:30px;border-radius:9px;flex:none;display:flex;
 align-items:center;justify-content:center;background:var(--tile-bg);
 border:1px solid var(--tile-bd)}
.srow-ev .evt{flex:none;font-size:.74rem;color:var(--muted);margin-top:3px;
 font-variant-numeric:tabular-nums}
#toast{position:fixed;left:16px;right:16px;z-index:45;max-width:448px;
 margin:0 auto;bottom:calc(88px + env(safe-area-inset-bottom,0px));
 background:var(--surface2);border:1px solid var(--border2);border-radius:16px;
 padding:12px 14px;display:flex;align-items:center;gap:11px;font-size:.92rem;
 color:var(--text);box-shadow:0 12px 34px rgba(0,0,0,.4);
 transform:translateY(16px);opacity:0;pointer-events:none;
 transition:transform .25s ease,opacity .25s ease}
#toast.on{transform:none;opacity:1;pointer-events:auto}
#offline{position:fixed;left:16px;right:16px;top:calc(10px + env(safe-area-inset-top,0px));
 z-index:46;max-width:448px;margin:0 auto;display:none;align-items:center;gap:9px;
 background:rgba(232,197,90,.14);border:1px solid rgba(232,197,90,.4);
 color:var(--warn);border-radius:14px;padding:10px 13px;font-size:.84rem;font-weight:600;
 backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
#offline.on{display:flex}
#lock{position:fixed;inset:0;z-index:70;background:var(--bg);display:none;
 flex-direction:column;align-items:center;justify-content:center;padding:24px}
html.locked #lock{display:flex}
html.locked .wrap,html.locked .hero,html.locked .tabbar{visibility:hidden}
#lock .kp{display:grid;grid-template-columns:repeat(3,72px);gap:12px}
#lock .kp button{height:64px;border-radius:50%;border:1px solid var(--border2);
 background:var(--surface2);color:var(--text);font-size:1.4rem;font-weight:600}
#lock .kp button:active{background:var(--surface3)}
#lock .ld{width:14px;height:14px;border-radius:50%;border:2px solid var(--muted)}
#lock .ld.on{background:var(--accent-soft);border-color:var(--accent-soft)}
#lock.shake #lock-dots{animation:shk .4s}
@keyframes shk{0%,100%{transform:none}25%{transform:translateX(-8px)}75%{transform:translateX(8px)}}
.hchip{display:inline-flex;align-items:center;gap:6px;font-size:.72rem;
 font-weight:700;padding:4px 11px;border-radius:99px;
 background:rgba(255,255,255,.1);color:#dbe9f7}
.topline{display:flex;justify-content:space-between;align-items:center;gap:8px}
.topline>span:last-child{flex:none}
.brand{font-weight:700;color:#dbe9f7;font-size:1.02rem;display:inline-flex;
 align-items:center}
.live{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;flex:none;
 background:rgba(46,204,113,.14);color:var(--up-soft);font-size:.6rem;
 font-weight:700;padding:3px 8px;border-radius:999px;
 letter-spacing:.06em}
.dot{width:8px;height:8px;border-radius:50%;background:var(--up);
 animation:p 1.8s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.25}}
/* 2026-10-01 (owner): a whole hero-sized row that tells the member
   nothing they do not know. Kept - it is the only warm line on the
   screen - but it stops costing 22px of the first fold. */
/* back to its old size - the tighter margin stays, the text does
   not need to be smaller to save that space */
/* 2026-10-01: a compact hero away from Home was tried and REVERTED the
   same hour - the owner: "the hero is not supposed to be affected, just
   the content below". It is the app's anchor and it reads the same on
   every tab by design. Do not shrink it again. */
.hello{color:rgba(219,233,247,.6);font-size:.86rem;margin-top:16px;
 letter-spacing:.01em}
.money{font-size:3.7rem;font-weight:800;margin-top:6px;
 letter-spacing:-2px;line-height:1.05}
.dayline{margin-top:10px;font-size:.92rem;color:rgba(219,233,247,.72);font-weight:600;
 font-variant-numeric:tabular-nums;min-height:1.3em}
.dayline b{font-weight:700}
.dayline .sep{opacity:.45;margin:0 6px}
#acctline{display:inline-flex;align-items:center;gap:6px;
 font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
 font-size:.62rem;letter-spacing:.06em;color:rgba(255,255,255,.5);line-height:1;white-space:nowrap}
#acctline i{width:6px;height:6px;border-radius:50%;display:inline-block}
#tradepill{cursor:pointer;padding:6px 13px;font-size:.76rem}
.eur{color:var(--text3);font-size:1.2rem;margin-top:2px}
.bankline{color:#8fb0cc;font-size:.85rem;margin-top:9px}
.wrap{max-width:440px;margin:-20px auto 0;padding:0 16px}
.status,.panel,.card{background:var(--surface);border:1px solid var(--border);
 border-radius:var(--r);box-shadow:var(--hl)}
.status{padding:16px;text-align:center;font-size:1.04rem;color:var(--text2)}
.panel{padding:16px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
.card{padding:18px 10px 15px;text-align:center}
/* 2026-10-01 (owner): "professional, premium, modern". Restraint, not
   more colour - one accent, one glow, hairlines, and alignment that
   holds. The orb stops pulsing: a permanent animation next to a live
   graph competes with the thing that is actually moving. */
#mx-orb{width:44px;height:44px;border-radius:50%;flex:none;
 display:flex;align-items:center;justify-content:center;
 font-size:1.35rem;background:radial-gradient(circle at 35% 30%,
 rgba(255,255,255,.14),rgba(255,255,255,.03));
 border:1px solid rgba(255,255,255,.1)}
#meteo{background:linear-gradient(180deg,
 rgba(255,255,255,.045),rgba(255,255,255,0) 42%),var(--surface)}
#meteo::before{content:"";position:absolute;left:14px;right:14px;top:0;
 height:1px;background:linear-gradient(90deg,transparent,
 rgba(255,255,255,.22),transparent);pointer-events:none}
/* the reading the whole card is about */
#mx-now{text-align:right;flex:none;line-height:1}
#mx-now b{display:block;font-size:1.7rem;font-weight:800;
 font-variant-numeric:tabular-nums;letter-spacing:-.5px}
#mx-now span{display:block;font-size:.66rem;color:var(--muted);
 text-transform:uppercase;letter-spacing:.09em;margin-top:3px}
/* 2026-10-01: this grid has NEVER laid out in two columns. The layout
   was declared inline as display:grid, and the show/hide pass does
   `el.style.display=''` to reveal it - which deletes the inline display
   and drops the element back to block. So the rule has to live here,
   where clearing an inline style cannot reach it. minmax(0,1fr) on top:
   a track will not shrink below its content, and the labels are nowrap. */
#mx-chips{display:grid;
 grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
@keyframes orbp{0%,100%{box-shadow:0 0 0 0 var(--mxg)}
 50%{box-shadow:0 0 22px 3px var(--mxg)}}
/* 2026-10-01 (owner): this ran a 7s infinite gradient the whole time the
   tab was open - a permanent repaint on a phone for a decorative sheen.
   It animates only while the Marche tab is actually showing, and not at
   all for a reader who has asked for less motion. */
#mx-wave{position:absolute;inset:0;pointer-events:none;
 background:linear-gradient(115deg,transparent 30%,var(--mxg) 50%,
 transparent 70%);background-size:280% 100%;opacity:.5}
#tab-marche.on #mx-wave{animation:wv 7s linear infinite}
@media (prefers-reduced-motion:reduce){
 #tab-marche.on #mx-wave{animation:none}}
@keyframes wv{0%{background-position:120% 0}
 100%{background-position:-60% 0}}
.mx-sun{--mxg:rgba(232,197,90,.12)}
.mx-fish{--mxg:rgba(79,216,200,.16)}
.mx-sleep{--mxg:rgba(109,125,160,.12)}
.mx-sleep #mx-wave{animation-duration:16s;opacity:.3}
.mx-storm{--mxg:rgba(255,92,92,.16)}
.mx-cloud{--mxg:rgba(230,160,40,.14)}
.mxc{font-size:.68rem;font-weight:700;padding:3px 10px;
 border-radius:99px;border:1px solid rgba(255,255,255,.12);
 background:var(--tile-bg);color:var(--muted2);
 letter-spacing:.03em}
.empty{text-align:center;padding:26px 10px;color:var(--muted)}
.empty i{font-style:normal;font-size:1.7rem;display:block}
.empty p{font-size:.85rem;margin-top:7px}
.lbl{font-size:.78rem;color:var(--muted2);text-transform:uppercase;
 letter-spacing:.07em;font-weight:600}
.val{font-size:1.45rem;font-weight:800;margin-top:8px;
 white-space:nowrap;letter-spacing:-.3px}
.sub{font-size:.8rem;color:var(--muted);margin-top:6px}
.pos{color:var(--up)}.neg{color:var(--down)}.neu{color:var(--text)}
/* 2026-10-01 (owner): "the text is so little". These were already
   under a sane floor - .sec 10.9px, .lbl 11.5px, .sub 11.8px, .tb
   11.5px - and once the changelog and two tiles came off the home
   screen, three times as much of that smallest text landed in one
   screenful. Nothing had shrunk; a lot more of it became visible.
   ~12.2px is the floor now. */
.sec{margin:26px 8px 10px;color:var(--muted);font-weight:700;
 font-size:.76rem;text-transform:uppercase;letter-spacing:.09em;
 text-align:left}
.sec .hint{opacity:.7;letter-spacing:.02em;text-transform:none;
 font-weight:500}
.row{display:flex;justify-content:space-between;align-items:center;
 padding:12px 4px;min-height:44px;border-bottom:1px solid var(--border);
 font-size:1rem}
.row:last-child{border-bottom:0}
/* 2026-10-01 (owner): Le Nid rows. The old row was one flex with the text
   on the left and four buttons on the right, centred - so the buttons sat
   in the MIDDLE of a five-line block and squeezed the text until it
   truncated mid-word on a phone. These lay the row out in three bands
   instead, with the money right-aligned so it reads as a column. */
.nrow{padding:13px 4px;border-bottom:1px solid var(--border)}
.nrow:last-child{border-bottom:0}
.nr-l{display:flex;align-items:baseline;gap:10px}
.nr-nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap;font-weight:700;font-size:.98rem}
.nr-bal{white-space:nowrap;font-weight:700;font-size:.98rem;
 color:var(--text2)}
.nr-mt{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap;font-size:.78rem;color:var(--muted)}
.nr-td{white-space:nowrap;font-size:.8rem;font-weight:700}
.nr-b{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:9px}
.nchip{font-size:.74rem;padding:4px 10px;border-radius:99px;
 background:var(--surface3);color:var(--muted2);
 border:1px solid var(--border);white-space:nowrap}
.nchip-ok{background:rgba(46,204,113,.12);color:var(--up-soft);
 border-color:rgba(46,204,113,.3)}
.nchip-w{background:rgba(232,197,90,.1);color:var(--warn);
 border-color:rgba(232,197,90,.3)}
.nchip-b{background:rgba(255,92,92,.1);color:#ff8c8c;
 border-color:rgba(255,92,92,.32)}
.nr-a{display:flex;gap:5px;margin-left:auto}
/* 2026-10-01 (owner): 44px is the accepted minimum for a thumb, and one
   of these four closes every position on an account. It asks for a
   password and shows a dry run first, so a mis-tap is not a disaster -
   but it should not be easy to hit by accident either. */
.nact{border:1px solid var(--border);background:transparent;
 color:var(--muted);border-radius:10px;padding:0 10px;
 text-decoration:none;display:inline-flex;align-items:center;
 justify-content:center;min-width:44px;min-height:44px}
.nact .ic{vertical-align:0}
.nact:active{background:var(--surface3)}
.nact-b{border-color:rgba(255,92,92,.38);color:#ff8c8c}
@keyframes livepulse{0%{opacity:1;transform:scale(1)}
 50%{opacity:.35;transform:scale(.75)}100%{opacity:1;transform:scale(1)}}
.livedot{display:inline-block;width:8px;height:8px;border-radius:50%;
 background:var(--up);margin-right:6px;vertical-align:middle;
 animation:livepulse 1.6s infinite}
.rowt{color:var(--muted2);font-size:.92rem}
.bd{display:inline-block;width:8px;height:8px;border-radius:50%;
 margin-right:8px;animation:p 1.8s infinite}
#inst{width:100%;margin-top:24px;background:var(--accent);
 color:#fff;border:0;border-radius:14px;padding:16px;font-size:1.06rem;
 font-weight:700}
#howto{display:none;margin-top:12px;background:var(--surface2);
 border:1px solid var(--border2);border-radius:14px;padding:14px;
 font-size:.9rem;color:var(--text2);line-height:1.6;text-align:left}
.foot{margin-top:20px;text-align:center;font-size:.8rem;color:var(--muted)}
.exit{display:block;margin-top:14px;text-align:center;color:var(--muted);
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
 background:var(--surface3)!important;border-radius:8px}
.skel::after{content:'';position:absolute;inset:0;
 background:linear-gradient(90deg,transparent,
 rgba(255,255,255,.08),transparent);animation:shim 1.2s infinite}
@keyframes shim{0%{transform:translateX(-100%)}
 100%{transform:translateX(100%)}}
@keyframes ipulse{0%{box-shadow:0 0 0 0 rgba(127,179,224,.45)}
 70%{box-shadow:0 0 0 8px rgba(127,179,224,0)}
 100%{box-shadow:0 0 0 0 rgba(127,179,224,0)}}
#sheetbg{position:fixed;inset:0;background:rgba(0,0,0,.6);
 display:none;z-index:40;opacity:0;transition:opacity .2s}
#sheet{position:fixed;left:0;right:0;bottom:0;z-index:41;
 background:var(--surface2);border:1px solid var(--border);border-bottom:0;
 border-radius:var(--r-lg) var(--r-lg) 0 0;
 padding:20px 20px calc(24px + env(safe-area-inset-bottom,0px));
 transform:translateY(105%);transition:transform .25s ease;
 box-shadow:0 -10px 40px rgba(0,0,0,.5);max-width:480px;margin:0 auto;
 max-height:calc(100vh - 28px - env(safe-area-inset-top,0px));overflow-y:auto;
 -webkit-overflow-scrolling:touch;overscroll-behavior:contain}
#sheet .grab{position:sticky;top:0;z-index:1}
#sheet h3{font-size:1.08rem;margin-bottom:8px;color:var(--text)}
#sheet p{color:var(--text3);font-size:.9rem;line-height:1.55;
 margin-bottom:14px}
#sheet input{width:100%;padding:13px;border-radius:12px;
 border:1px solid var(--border2);background:var(--bg);color:var(--text);
 font-size:1rem;margin-bottom:6px}
#sheet input:focus{outline:none;border-color:var(--accent)}
.shbtn{width:100%;border:0;border-radius:13px;padding:14px;
 font-size:1rem;font-weight:700;margin-top:8px;min-height:48px}
.shmain{background:var(--accent);color:#fff}
.shdanger{background:#a03030;color:#fff}
.shghost{background:var(--surface3);color:var(--text2)}
.grab{width:38px;height:4px;border-radius:99px;background:var(--border2);
 margin:0 auto 14px}
#tourbg{position:fixed;inset:0;background:rgba(4,8,14,.72);
 display:none;z-index:51}
#tourbx{position:fixed;left:16px;right:16px;z-index:53;display:none;
 background:var(--surface2);border:1px solid rgba(143,198,255,.35);
 border-radius:18px;padding:18px;box-shadow:0 14px 40px rgba(0,0,0,.6);
 max-width:420px;margin:0 auto}
#tourbx p{color:var(--text);font-size:1rem;line-height:1.6;margin:0}
#tourdots{margin-top:12px;display:flex;align-items:center}
.tourhl{position:relative;z-index:52;border-radius:16px;
 box-shadow:0 0 0 3px #7fb0ff,0 0 28px rgba(59,130,246,.65)!important}
/* 2026-10-01: these were a 24px pill with a transparent 44px overlay.
   The overlay did not hit-test reliably - a press 8px above the pill
   still missed - and a target the eye cannot find is worse than one that
   is honestly the right size. They grow instead. */
.cvc{position:relative;min-height:40px;font-size:.78rem!important;
 padding:9px 14px!important}
.tb,.srow,.shbtn,#sharebtn,#inst,.cvc,#actbtn,#invbtn{transition:transform .12s ease,
 background .15s,color .15s,border-color .15s}
.tb:active,.srow:active,.shbtn:active,#sharebtn:active,#inst:active,.cvc:active,
#actbtn:active,#invbtn:active{transform:scale(.97)}
.srow:active{background:var(--tile-bg)}
.sw{width:44px;height:26px;border-radius:99px;background:var(--surface3);
 border:1px solid var(--border2);position:relative;flex:none;transition:background .2s}
.sw .swk{position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;
 background:#fff;transition:left .2s;box-shadow:0 1px 3px rgba(0,0,0,.4)}
.sw.on{background:var(--up);border-color:var(--up)}
.sw.on .swk{left:21px}
:focus-visible{outline:2px solid var(--accent-soft);outline-offset:2px}
button,a,.srow{-webkit-tap-highlight-color:transparent}
.pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:.66rem;
 font-weight:700;letter-spacing:.03em;background:rgba(255,255,255,.07);
 color:var(--muted2);vertical-align:1px}
.pill-w{background:rgba(232,197,90,.14);color:var(--warn)}
.mxseg{display:flex;gap:4px;background:var(--surface2);border:1px solid var(--border);border-radius:14px;padding:4px;margin:16px 0 0}
/* 2026-10-01 (owner): 33px, under the floor set on the other tabs. */
.mxs{flex:1;display:inline-flex;align-items:center;justify-content:center;gap:7px;border:0;background:transparent;color:var(--muted2);
 border-radius:11px;padding:13px 8px;min-height:44px;font-size:.86rem;font-weight:700;letter-spacing:.01em;transition:background .18s,color .18s}
.mxs.on{background:var(--surface);color:var(--text);box-shadow:0 2px 10px rgba(0,0,0,.28),var(--hl,none)}
.mxs .ic-s{width:16px;height:16px}
/* 2026-09-28 polish (owner): the switch never wraps, the lab reads like a
   magazine - one card grammar (.lc), one row grammar (.kv), one chip (.pchip) */
.mxs{font-size:.8rem;padding:9px 6px;white-space:nowrap;gap:6px}
.mxs .ic-s{width:15px;height:15px}
.labstat{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;margin-top:10px;padding-bottom:2px}
.labstat::-webkit-scrollbar{display:none}
.labstat .ls{flex:none;display:inline-flex;align-items:center;gap:6px;background:var(--surface2);border:1px solid var(--border);border-radius:99px;padding:6px 11px 6px 9px;font-size:.7rem;color:var(--muted2);font-weight:600;white-space:nowrap;text-transform:uppercase;letter-spacing:.05em;cursor:pointer}
.labstat .ls.on{background:var(--surface3);border-color:var(--border2);color:var(--text)}
.labintro{margin-top:10px;padding:14px;border-color:rgba(59,130,246,.3)}
.labintro .st{display:flex;gap:8px;margin-top:10px}
.labintro .st div{flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:9px 8px;text-align:center;font-size:.72rem;color:var(--text2);line-height:1.35}
.labintro .st b{display:block;font-size:.95rem;color:var(--accent-soft);margin-bottom:2px}
.labstat .ls b{font-size:.95rem;font-variant-numeric:tabular-nums;letter-spacing:0}
.pv{position:relative}
.pv-top{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.pv-k{font-size:.58rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--accent-soft)}
.pv-n{margin-left:auto;font-size:.66rem;color:var(--muted);font-variant-numeric:tabular-nums}
.pv-body{min-height:58vh}
.pv-h{font-size:1.32rem;font-weight:800;line-height:1.24;letter-spacing:-.01em;margin:2px 0 6px;color:var(--text)}
.pv-p{font-size:.86rem;color:var(--text2);line-height:1.5}
.pv-big{display:flex;align-items:baseline;gap:8px;margin:14px 0 2px}
.pv-big b{font-size:2.6rem;font-weight:900;letter-spacing:-.03em;line-height:1}
.pv-big span{font-size:.8rem;color:var(--muted2)}
.pv-g{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}
.pv-c{background:var(--surface2);border:1px solid var(--border);border-radius:16px;padding:12px 13px}
.pv-c b{display:block;font-size:1.32rem;font-weight:900;letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.pv-c span{display:block;font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:3px}
.pv-c small{display:block;font-size:.68rem;color:var(--muted2);margin-top:5px;line-height:1.35}
.pv-chart{background:var(--surface2);border:1px solid var(--border);border-radius:16px;padding:12px 10px 8px;margin-top:12px}
.pv-chart svg{width:100%;display:block}
.pv-row{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid var(--border)}
.pv-row .t{flex:1;min-width:0;font-size:.84rem;color:var(--text)}
.pv-row .t small{display:block;color:var(--muted2);font-size:.7rem;margin-top:1px}
.pv-row .v{font-weight:800;font-variant-numeric:tabular-nums;font-size:.9rem}
.pv-note{font-size:.7rem;color:var(--muted);line-height:1.5;margin-top:12px}
.pv-dots{display:flex;gap:5px;justify-content:center;margin:14px 0 10px}
.pv-dots i{height:6px;border-radius:99px;background:var(--border2);transition:width .22s,background .22s}
.pv-nav{display:flex;gap:8px}
.pv-pill{display:inline-flex;align-items:center;gap:6px;background:var(--surface2);border:1px solid var(--border);border-radius:99px;padding:5px 11px;font-size:.7rem;color:var(--text2);font-weight:700}
.pf{--pfc:var(--warn)}
.pf-hero{display:flex;gap:14px;align-items:center}
.pf-ring{flex:none;width:74px;height:74px;position:relative}
.pf-ring svg{width:74px;height:74px;display:block}
.pf-ring b{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:1.25rem;font-weight:900;color:var(--text)}
.pf-verdict{font-size:1.05rem;font-weight:800;line-height:1.25;color:var(--pfc)}
.pf-sub{font-size:.74rem;color:var(--muted2);line-height:1.4;margin-top:3px}
.pf-rows{margin-top:12px;border-top:1px solid var(--border)}
.pf-row{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid var(--border)}
.pf-row .t{flex:1;min-width:0}
.pf-row .t b{display:block;font-size:.84rem;color:var(--text)}
.pf-row .t span{display:block;font-size:.7rem;color:var(--muted2);margin-top:1px}
.pf-row .v{font-size:.86rem;font-weight:800;font-variant-numeric:tabular-nums;white-space:nowrap}
.pf-row svg{width:56px;height:22px;flex:none}
.pf-sec{margin-top:20px}
.pf-k{font-size:.6rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--accent-soft)}
.pf-h{font-size:1.02rem;font-weight:800;margin:3px 0 4px;color:var(--text)}
.pf-p{font-size:.82rem;color:var(--text2);line-height:1.5}
.pf-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}
.pf-kpi{background:var(--surface2);border:1px solid var(--border);border-radius:14px;padding:11px 12px}
.pf-kpi b{display:block;font-size:1.25rem;font-weight:900;letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.pf-kpi span{display:block;font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:2px}
.pf-kpi small{display:block;font-size:.7rem;color:var(--muted2);margin-top:4px;text-transform:none;letter-spacing:0}
.pf-chart{margin-top:12px;background:var(--surface2);border:1px solid var(--border);border-radius:16px;padding:12px 10px 8px}
.pf-chart svg{width:100%;display:block}
.pf-cap{font-size:.68rem;color:var(--muted);line-height:1.5;margin-top:8px}
.pf-leg{display:flex;flex-wrap:wrap;gap:10px;font-size:.66rem;color:var(--muted2);margin-top:6px}
.pf-leg i{display:inline-block;width:10px;height:3px;border-radius:2px;vertical-align:middle;margin-right:5px}
.pf-bar{display:flex;align-items:center;gap:10px;font-size:.8rem;margin-top:8px}
.pf-bar .l{flex:none;width:118px;color:var(--text2)}
.pf-bar .b{flex:1;height:10px;border-radius:99px;background:var(--surface3);overflow:hidden;position:relative}
.pf-bar .b i{position:absolute;top:0;bottom:0;border-radius:99px}
.pf-bar .v{flex:none;width:52px;text-align:right;font-weight:800;font-variant-numeric:tabular-nums}
.pf-prog{margin-top:12px;background:var(--surface2);border:1px solid var(--border);border-radius:14px;padding:11px 12px}
.pf-prog .b{height:8px;border-radius:99px;background:var(--surface3);overflow:hidden;margin-top:8px}
.pf-prog .b i{display:block;height:100%;background:var(--accent-soft);border-radius:99px}
.pf-ans{display:flex;gap:12px;align-items:flex-start;background:var(--surface2);border:1px solid var(--border);border-radius:14px;padding:12px;margin-top:8px}
.pf-ans .d{flex:none;width:30px;height:30px;border-radius:99px;display:flex;align-items:center;justify-content:center;font-weight:900;color:#0b1020}
.pf-ans b{display:block;font-size:.86rem;color:var(--text)}
.pf-ans p{margin:3px 0 0;font-size:.8rem;color:var(--text2);line-height:1.5}
.pf-final{margin-top:12px;border-radius:16px;padding:14px;border:1px solid var(--pfc);background:linear-gradient(180deg,rgba(255,255,255,.05),transparent)}
.pf-final b{font-size:1.15rem;color:var(--pfc)}
.pf-final p{margin:4px 0 0;font-size:.78rem;color:var(--text2);line-height:1.5}
.pf-steps{display:flex;gap:6px;margin-top:10px}
.pf-steps div{flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:8px 6px;font-size:.66rem;color:var(--text2);line-height:1.3;text-align:center}
.pf-steps b{display:block;font-size:.9rem;color:var(--accent-soft);margin-bottom:2px}
.pf-ring b{font-size:.72rem;letter-spacing:.02em;text-transform:uppercase;text-align:center;line-height:1.1;padding:0 8px}
.pf-ring.big{width:116px;height:116px}.pf-ring.big svg{width:116px;height:116px}.pf-ring.big b{font-size:.9rem}
/* 2026-10-02 (owner): the proof deck's verdict slide left 40% empty; the
   dots become their sentence, the checks get room, the ring grows. */
#sheet .pf-dots i{display:none}
#sheet .pf-dots span{margin-left:0!important;font-size:.76rem;color:var(--muted2)}
#sheet .pv-row{padding:15px 0;gap:12px}
#sheet .pv-row .t{font-size:.95rem;font-weight:600}
#sheet .pv-note{font-size:.78rem;margin-top:16px}
.pf-nav{position:sticky;top:-2px;z-index:3;display:flex;gap:6px;padding:8px 0 10px;background:var(--surface);border-bottom:1px solid var(--border);margin-bottom:6px}
.pf-nav button{flex:1;border:1px solid var(--border);background:var(--surface2);color:var(--text2);border-radius:99px;padding:7px 4px;font:inherit;font-size:.72rem;font-weight:700;cursor:pointer}
.pf-nav button b{color:var(--accent-soft);margin-right:3px}
.pf-kpi{cursor:pointer;position:relative}
.pf-kpi .x{display:none;font-size:.74rem;color:var(--text);line-height:1.45;margin-top:8px;padding-top:8px;border-top:1px solid var(--border);text-transform:none;letter-spacing:0}
.pf-kpi.open .x{display:block}
.pf-st b{font-size:1.15rem;margin-top:2px}
.pf-st span{margin-top:0}
.pf-st small{color:var(--muted2)}
.pf-sech{font-size:.7rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--muted2);margin:18px 2px 0}
.pf-kpi::after{content:"?";position:absolute;top:8px;right:10px;width:16px;height:16px;border-radius:99px;background:var(--surface3);color:var(--muted2);font-size:.62rem;font-weight:800;display:flex;align-items:center;justify-content:center}
.pf-dots{display:flex;gap:5px;align-items:center;margin-top:8px;flex-wrap:wrap}
.pf-lot{display:flex;align-items:center;gap:6px;margin-top:10px;flex-wrap:wrap;font-size:.74rem;color:var(--muted2)}
.pf-lot button{border:1px solid var(--border);background:var(--surface2);color:var(--text2);border-radius:99px;padding:5px 10px;font:inherit;font-size:.72rem;font-weight:700;cursor:pointer}
.pf-lot button.on{background:var(--accent-soft);border-color:var(--accent-soft);color:#0b1020}
.pf-tbl{width:100%;border-collapse:collapse;font-size:.8rem;margin-top:8px}
.pf-tbl td{padding:8px 0;border-top:1px solid var(--border);vertical-align:top}
.pf-tbl td:first-child{color:var(--text);font-weight:700;width:46%}
.pf-tbl td:first-child small{display:block;font-weight:400;color:var(--muted);font-size:.68rem;line-height:1.35;margin-top:1px}
.pf-tbl td:nth-child(2),.pf-tbl td:nth-child(3){text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;padding-left:12px}
.pf-tbl th{font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;text-align:right;padding-bottom:4px;font-weight:700}
.pf-tbl th:first-child{text-align:left}

.pf-dots i{width:14px;height:14px;border-radius:99px;display:inline-block;border:2px solid transparent}
.pf-dots i.today{border-color:var(--text)}
.pf-tip{min-height:18px;font-size:.74rem;color:var(--text);margin-top:6px;font-variant-numeric:tabular-nums}
.pf-mine{margin-top:12px;border-radius:16px;padding:12px 14px;border:1px solid var(--accent-soft);background:linear-gradient(180deg,rgba(59,130,246,.10),transparent)}
/* 2026-10-02 (owner): Marche > Robot, premium pass - scoped to #mx-robot */
#mx-robot .panel>.lbl{display:flex;align-items:center;gap:8px;font-size:.68rem;
 font-weight:700;letter-spacing:.12em;color:var(--muted2);margin-bottom:10px}
#mx-robot .panel>.lbl::after{content:"";flex:1;height:1px;background:var(--border);margin-left:4px}
#mx-robot .panel>.lbl>span:first-child,#mx-robot .panel>.lbl{white-space:nowrap}
#mx-robot .panel .lbl .hint{font-weight:600;letter-spacing:.04em;text-transform:none;
 color:var(--muted);white-space:normal;flex:0 1 auto;min-width:0;line-height:1.3}
#mx-robot #rb-next{background:transparent!important;border:0!important;
 border-top:1px solid var(--border)!important;border-radius:0!important;padding:11px 0 0!important}
#mx-robot #rb-next>span{color:var(--muted2)!important;font-weight:700;
 letter-spacing:.12em!important;font-size:.62rem!important;margin-bottom:4px!important}
#mx-robot #st{border-top:1px solid var(--border)!important}
#mx-robot #proofcard{border-color:var(--border)!important}
#mx-robot .pf-verdict{font-weight:700;letter-spacing:-.01em}
#mx-robot .pf-dots{margin-top:6px}
#mx-robot .pf-dots i{display:none}
#mx-robot .pf-dots span{margin-left:0!important;font-size:.72rem;color:var(--muted)}
#mx-robot .pf-row .t b{font-weight:600}
#mx-robot #proofcard .shbtn.shmain{margin:12px 0 0;padding:12px 0 2px;background:transparent;
 border:0;border-top:1px solid var(--border);border-radius:0;color:var(--accent-soft);
 font-weight:700;font-size:.9rem;text-align:left;box-shadow:none}
#mx-robot #rjcard .lbl{margin-bottom:0;font-size:.62rem}
#mx-robot #rjcard .lbl::after{display:none}
#mx-robot .sic{background:var(--tile-bg);border:1px solid var(--tile-bd)}
/* 2026-10-02 (owner): Accueil, premium pass - scoped to #tab-home */
#tab-home .grid .card{background:var(--tile-bg);border:1px solid var(--tile-bd);
 border-radius:14px;padding:14px 10px 12px;box-shadow:none}
#tab-home .grid .card .lbl{font-size:.64rem;letter-spacing:.1em;color:var(--muted);font-weight:700}
#tab-home .grid .card .val{font-size:1.5rem;font-weight:700;letter-spacing:-.02em;margin-top:6px}
#tab-home .grid .card .sub{font-size:.7rem;margin-top:5px}
#tab-home .panel>.lbl{display:flex;align-items:center;gap:8px;font-size:.68rem;font-weight:700;
 letter-spacing:.12em;color:var(--muted2);white-space:nowrap}
#tab-home .panel>.lbl::after{content:"";flex:1;height:1px;background:var(--border);margin-left:4px}
#tab-home .panel .lbl .hint{font-weight:600;letter-spacing:.04em;text-transform:none;color:var(--muted);
 white-space:normal;flex:0 1 auto;min-width:0;line-height:1.3}
#tab-home #apkcard,#tab-home #newscard,#tab-home #recap{border-color:var(--border)!important;margin-top:26px!important}
#tab-home #expcard{margin-top:26px!important}
#expcard .shbtn{width:auto!important;margin:0!important;padding:10px 14px!important}
.hq{display:none!important}
html.apponly #rob-sec,html.apponly #rob-card,html.apponly #healthrow{display:none!important}
#apkcard .shbtn{width:auto!important;margin:0!important;padding:10px 14px!important}
#apkcard #apk-go{flex:1 1 auto;min-width:0}
#apkcard #apk-no{flex:0 0 auto}
#tab-home #newscard .shbtn{display:inline-flex;width:auto;margin:10px 8px 0 0;padding:7px 12px;
 font-size:.78rem;font-weight:600;background:transparent;border:1px solid var(--border);
 color:var(--text2);border-radius:99px;box-shadow:none}
#tab-home #newscard .shbtn.shmain{color:var(--accent-soft);border-color:rgba(59,130,246,.35)}
#tab-home #newscard .shbtn,#tab-home #newscard button{flex:0 0 auto!important;width:auto!important}
#tab-home .sic{background:var(--tile-bg)!important;border:1px solid var(--tile-bd)}
#tab-home .cvc{border-color:transparent!important;padding:6px 11px!important;border-radius:9px!important}
#tab-home .sec{font-size:.68rem;letter-spacing:.12em;font-weight:700;color:var(--muted2)}
/* 2026-10-02 (owner): Le Nid, premium pass - scoped to #tab-nid */
#tab-nid .sec{font-size:.68rem;letter-spacing:.12em;font-weight:700;color:var(--muted2)}
#tab-nid #acctsw{background:transparent!important;border:0!important;padding:0!important;margin-bottom:10px!important}
#tab-nid #acctsw>div:first-child{font-size:.62rem;letter-spacing:.12em;text-transform:uppercase;font-weight:700;color:var(--muted)}
#tab-nid #acctsw-b{flex-wrap:nowrap!important;overflow-x:auto;scrollbar-width:none;padding-bottom:4px;margin:0 -2px}
#tab-nid #acctsw-b::-webkit-scrollbar{display:none}
#tab-nid #acctsw-b>*{flex:none;white-space:nowrap;border-color:transparent!important;background:var(--tile-bg)!important;
 font-size:.84rem!important;padding:8px 12px!important;border-radius:99px!important}
#tab-nid .panel>.lbl{display:flex;align-items:center;gap:8px;font-size:.68rem;font-weight:700;letter-spacing:.12em;color:var(--muted2)}
#tab-nid .panel>.lbl::after{content:"";flex:1;height:1px;background:var(--border);margin-left:4px}
#tab-nid #rev-g>div{background:var(--tile-bg)!important;border:1px solid var(--tile-bd)!important;border-radius:14px!important;padding:12px 6px!important}
#tab-nid #rev-g>div b{font-size:1.3rem!important;font-weight:700!important;letter-spacing:-.02em}
#tab-nid #rev-g>div span{font-size:.62rem!important;color:var(--muted)!important}
#tab-nid .nrow{padding:14px 2px}
#tab-nid .nr-nm{font-weight:600}
#tab-nid .nr-bal{font-weight:600;color:var(--text)}
#tab-nid .nchip{font-size:.7rem;padding:3px 9px;background:var(--tile-bg);border-color:var(--tile-bd)}
#tab-nid .nr-a{gap:4px}
#tab-nid .nact{border-color:transparent;background:var(--tile-bg);color:var(--muted);min-width:40px;min-height:40px;border-radius:10px}
#tab-nid .nact-b{background:rgba(255,92,92,.08);color:#ff8c8c}
#tab-nid #invbtn{background:transparent!important;border:1px dashed var(--border2)!important;color:var(--text2)!important;
 font-weight:600!important;font-size:.9rem!important;padding:13px!important}
/* 2026-10-02 (owner): Historique, premium pass - scoped to #tab-hist */
#tab-hist .sec{font-size:.68rem;letter-spacing:.12em;font-weight:700;color:var(--muted2)}
#tab-hist .panel>.lbl{display:flex;align-items:center;gap:8px;font-size:.68rem;font-weight:700;letter-spacing:.12em;color:var(--muted2)}
#tab-hist .panel>.lbl::after{content:"";flex:1;height:1px;background:var(--border);margin-left:4px}
#tab-hist .sincegrid>div,#tab-hist #mvm-g>div{background:var(--tile-bg)!important;border:1px solid var(--tile-bd)!important;border-radius:14px!important}
#tab-hist .sincegrid b{font-size:1.3rem;font-weight:700;letter-spacing:-.02em}
#tab-hist .sincegrid span{font-size:.62rem;letter-spacing:.08em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}
#tab-hist .grid .card{background:var(--tile-bg);border:1px solid var(--tile-bd);border-radius:14px;padding:14px 10px 12px;box-shadow:none}
#tab-hist .grid .card .lbl{font-size:.64rem;letter-spacing:.1em;color:var(--muted);font-weight:700}
#tab-hist .grid .card .val{font-size:1.4rem;font-weight:700;letter-spacing:-.02em;margin-top:6px}
#tab-hist .grid .card .sub{font-size:.7rem;margin-top:5px}
#tab-hist #sharebtn{background:transparent!important;box-shadow:none!important;border:0!important;
 border-top:1px solid var(--border)!important;border-radius:0!important;color:var(--accent-soft)!important;
 justify-content:flex-start!important;padding:12px 0 2px!important;font-size:.9rem!important}
#tab-hist #days .row{justify-content:flex-start;gap:10px}
#tab-hist #days .row .rowt svg,#tab-hist #days .row .rowt>span{display:none}
#tab-hist #days .row>b{margin-left:auto}
#tab-hist #days .row::after{content:"›";color:var(--muted);font-size:1.1rem;line-height:1;margin-left:2px}
#tab-hist #siglist .empty{padding:14px 10px}
#tab-hist #siglist:has(.empty){background:transparent;border:1px dashed var(--border2);box-shadow:none}
#tab-hist #msum-sec button{background:transparent!important;border-color:var(--border)!important;color:var(--muted2)!important}
#tab-hist #tgo button,#tab-hist #tgo input{border-color:var(--border)!important;background:var(--tile-bg)!important}
#tab-hist #cal-sec>span:last-child{margin-left:14px}
/* 2026-10-02 (owner): Marche > Marche, premium pass - scoped to #mx-market */
#mx-market .sec{font-size:.68rem;letter-spacing:.12em;font-weight:700;color:var(--muted2)}
#mx-jump{gap:2px!important;border-bottom:1px solid var(--border);padding:2px 0 6px!important;margin-top:6px!important}
#mx-jump button{border:0!important;background:transparent!important;color:var(--muted2)!important;
 border-radius:9px!important;padding:8px 10px!important;min-height:36px!important;font-weight:600!important;font-size:.8rem!important}
#mx-jump button:active{background:var(--surface2)!important}
#mx-market .panel>.lbl{display:flex;align-items:center;gap:8px;font-size:.68rem;font-weight:700;letter-spacing:.12em;color:var(--muted2);white-space:nowrap}
#mx-market .panel>.lbl::after{content:"";flex:1;height:1px;background:var(--border);margin-left:4px}
#mx-market .panel .lbl .hint{font-weight:600;letter-spacing:.04em;text-transform:none;color:var(--muted);white-space:normal;flex:0 1 auto;min-width:0;line-height:1.3}
#mx-chips>div{border-color:var(--tile-bd)!important;border-radius:14px!important}
#mx-chips>div b{font-weight:600!important}
#mx-market #tf-foot{font-size:.76rem;color:var(--muted);line-height:1.5}
#mx-market #mh-leg{justify-content:flex-end}

.jboard{padding:14px 12px 12px;margin-top:12px}
.jrail{display:flex;align-items:flex-start;position:relative;margin:2px 0 6px}
.jrail .jn{flex:1;text-align:center;position:relative;cursor:pointer;-webkit-tap-highlight-color:transparent}
.jrail .jn:not(:last-child)::after{content:"";position:absolute;top:15px;left:50%;width:100%;height:2px;background:var(--border2);z-index:0}
.jrail .jn.past:not(:last-child)::after{background:var(--jc);opacity:.55}
.jrail .jn i{position:relative;z-index:1;display:flex;align-items:center;justify-content:center;width:32px;height:32px;margin:0 auto;border-radius:99px;background:var(--surface2);border:2px solid var(--border2);font-style:normal;font-weight:800;font-size:.8rem;color:var(--muted2);transition:transform .2s,background .2s,color .2s,border-color .2s}
.jrail .jn.past i{border-color:var(--jc);color:var(--jc)}
.jrail .jn.on i{background:var(--jc);border-color:var(--jc);color:#0b1020;transform:scale(1.18);box-shadow:0 0 0 5px rgba(255,255,255,.08)}
.jrail .jn span{display:block;margin-top:7px;font-size:.56rem;line-height:1.2;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);padding:0 2px}
.jrail .jn.on span{color:var(--text);font-weight:800}
.jhead{display:flex;align-items:center;gap:10px;margin:14px 2px 2px}
.jht{font-size:.7rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase}
.jht b{color:var(--text);margin-left:4px}
.jhs{font-size:.78rem;color:var(--muted2);line-height:1.4;margin-top:2px}
.jcards .lc{margin-top:10px}
.jcards .lc:first-child{margin-top:12px}
.jfoot{display:flex;justify-content:space-between;align-items:center;margin-top:14px}
.jfoot .tfc{max-width:48%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* 2026-10-02 (owner): "more professional, modern and premium". Fewer boxes,
   one accent per block, numbers that read at a glance, and air. */
.jboard{padding:18px 14px 14px;margin-top:12px;border-radius:var(--r-lg)}
.jrail{margin:0 0 4px}
.jrail .jn i{width:36px;height:36px;font-size:.84rem;border-width:2px}
.jrail .jn:not(:last-child)::after{top:17px}
.jrail .jn span{font-size:.6rem;margin-top:8px;letter-spacing:.06em;line-height:1.25}
.jrail .jn.on i{box-shadow:0 0 0 5px rgba(255,255,255,.07),0 6px 18px rgba(0,0,0,.35)}
.jhead{margin:18px 2px 0}
.jhs{margin-top:3px}
.jempty{padding:26px 14px;text-align:center;color:var(--muted);font-size:.86rem;
 border:1px dashed var(--border2);border-radius:16px;margin-top:12px}
.jfoldbtn{width:100%;margin-top:12px;padding:11px;justify-content:center}
.lc{border-radius:18px;padding:14px 14px 12px;
 background:linear-gradient(180deg,rgba(255,255,255,.028),rgba(255,255,255,0)),var(--surface);
 box-shadow:var(--hl)}
.lc .lcb{width:34px;height:34px;border-radius:10px;font-size:.95rem}
.lc h4{font-size:.96rem;letter-spacing:-.01em}
.lc .lcc{margin-top:8px}
.lc .lcm{border-top:1px solid var(--border);padding-top:9px;margin-top:11px;font-size:.68rem}
.pchip{font-size:.58rem;padding:3px 7px;letter-spacing:.04em}
.labhero{display:block;width:100%;text-align:left;margin-top:12px;padding:16px 16px 14px;
 border-radius:var(--r-lg);border:1px solid rgba(185,140,255,.26);color:var(--text);
 cursor:pointer;font:inherit;position:relative;overflow:hidden;
 background:radial-gradient(120% 95% at 100% 0%,rgba(185,140,255,.24),transparent 58%),
  linear-gradient(160deg,var(--hero1),var(--hero2));
 box-shadow:0 12px 32px rgba(0,0,0,.28),var(--hl)}
:root[data-theme=light] .labhero{--text:#e8eef4;--text2:#c6d3df;--muted:#8a9bb0;--up-soft:#8df0bb}
.labhero:active{filter:brightness(1.06)}
.lh-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.lh-eye{font-size:.62rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:#d2b8ff}
.lh-read{font-size:.76rem;font-weight:700;color:var(--text2)}
.lh-head{margin-top:9px;font-size:1.04rem;font-weight:700;line-height:1.38;letter-spacing:-.012em;
 display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.lh-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px}
.lh-stats div{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.09);
 border-radius:14px;padding:11px 6px 9px;text-align:center}
.lh-stats b{display:block;font-size:1.35rem;font-weight:800;line-height:1;letter-spacing:-.02em;
 font-variant-numeric:tabular-nums}
.lh-stats span{display:block;font-size:.6rem;color:var(--text2);margin-top:6px;line-height:1.2}
.lh-ok{margin-top:11px;font-size:.7rem;color:var(--up-soft);display:flex;align-items:center;gap:6px}
.lh-live{display:flex;align-items:flex-start;gap:9px;margin-top:11px;padding:10px 11px;
 background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);border-radius:14px;font-size:.8rem;line-height:1.4}
.lh-live b{color:var(--text)}
.lh-ago{color:var(--muted)}
.lh-say{display:block;color:var(--text2);margin-top:3px}
.lh-dot{flex:none;width:8px;height:8px;border-radius:99px;background:var(--up);margin-top:6px;
 box-shadow:0 0 0 0 rgba(46,204,113,.6);animation:lhdot 2.2s ease-out infinite}
@keyframes lhdot{0%{box-shadow:0 0 0 0 rgba(46,204,113,.55)}100%{box-shadow:0 0 0 9px rgba(46,204,113,0)}}
.lablabo{margin-top:10px;padding:14px 14px 12px}
.lablabo.paused{border-color:rgba(232,197,90,.35)}
.lablabo-reh{display:flex;align-items:center;gap:7px;margin-top:12px;font-size:.78rem;color:var(--up-soft)}
.lablabo-reh.bad{color:var(--down-soft)}
.lablabo-reh span{color:var(--muted)}
.lablabo-brake{margin:12px 0 0;padding:11px;width:100%}
.labweek{margin-top:10px;padding:0}
.labweek>summary{list-style:none;cursor:pointer;padding:14px 14px 12px;display:flex;flex-direction:column;gap:6px;position:relative}
.labweek>summary::-webkit-details-marker{display:none}
.labweek>summary .lbl{display:flex;align-items:center;gap:8px;font-size:.68rem;font-weight:700;letter-spacing:.12em;color:var(--muted2)}
.labweek>summary .lbl .hint{font-weight:600;letter-spacing:.04em;text-transform:none;color:var(--muted)}
.labweek>summary b{font-size:.92rem;line-height:1.45;font-weight:600;padding-right:26px}
.labweek>summary .chv{position:absolute;right:14px;top:16px;transition:transform .2s}
.labweek[open]>summary .chv{transform:rotate(180deg)}
.labweek ul{margin:0;padding:0 14px 14px 30px;color:var(--text2);font-size:.86rem;line-height:1.5}
.labweek li{margin-top:6px}
.lablabo>.lbl{display:flex;align-items:center;gap:8px;font-size:.68rem;font-weight:700;letter-spacing:.12em;color:var(--muted2);white-space:nowrap}
.lablabo>.lbl::after{content:"";flex:1;height:1px;background:var(--border);margin-left:4px}
.lablabo>.lbl .hint{font-weight:600;letter-spacing:.04em;text-transform:none;color:var(--muted)}
.lab-dot{width:8px;height:8px;border-radius:99px;flex:none}
.lablabo-what{font-size:.9rem;line-height:1.5;color:var(--text);margin-top:10px}
.lablabo-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px}
.lablabo-tiles>div{background:var(--tile-bg);border:1px solid var(--tile-bd);border-radius:14px;padding:12px 6px 10px;text-align:center}
.lablabo-tiles b{display:block;font-size:1.3rem;font-weight:700;letter-spacing:-.02em;line-height:1;font-variant-numeric:tabular-nums}
.lablabo-tiles span{display:block;font-size:.64rem;color:var(--muted);margin-top:6px}
.labseedrow{display:flex;align-items:center;gap:12px;width:100%;margin-top:10px;
 background:transparent;border:1px dashed var(--border2);border-radius:16px;
 padding:12px 14px;min-height:52px;text-align:left;color:var(--text2);font:inherit;cursor:pointer}
.labseedrow:active{background:var(--surface2)}
.labseedrow .lsr-n{font-size:1.2rem;font-weight:800;color:var(--warn);min-width:28px;
 text-align:center;font-variant-numeric:tabular-nums}
.labseedrow b{display:block;font-size:.88rem;color:var(--text)}
.labseedrow .lsr-s{display:block;font-size:.74rem;color:var(--muted);margin-top:2px}
.labseedrow .chv{flex:none;color:var(--muted);width:16px;height:16px}
.jb{display:flex;gap:10px;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none;padding:2px 0 10px;margin-top:10px}
.jb::-webkit-scrollbar{display:none}
.jcol{flex:0 0 84%;scroll-snap-align:start;background:var(--surface2);border:1px solid var(--border);border-radius:16px;padding:10px 10px 6px;min-height:120px}
.jch{display:flex;align-items:center;gap:8px;font-size:.66rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--muted2);padding:2px 4px 8px}
.jch i{width:8px;height:8px;border-radius:99px;display:inline-block}
.jch b{margin-left:auto;font-size:.8rem;color:var(--text)}
.jcard{background:var(--surface);border:1px solid var(--border);border-radius:13px;padding:10px 12px;margin-bottom:8px;cursor:pointer}
.jcard h5{margin:0;font-size:.86rem;line-height:1.3;font-weight:700;color:var(--text)}
.jcard .jl{font-size:.72rem;color:var(--muted2);margin-top:5px;line-height:1.4}
.jcard .jl b{font-weight:800}
.jnav{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;margin-top:10px}
.jst{display:flex;align-items:flex-start;margin:12px 0 4px;position:relative}
.jst>div{flex:1;text-align:center;position:relative;font-size:.58rem;color:var(--muted);line-height:1.25;text-transform:uppercase;letter-spacing:.04em;padding:0 3px}
.jst>div:not(:last-child)::after{content:"";position:absolute;top:11px;left:50%;width:100%;height:2px;background:var(--border2)}
.jst>div.done:not(:last-child)::after{background:var(--accent-soft)}
.jst>div.no:not(:last-child)::after{background:var(--border2)}
.jst i{display:flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:99px;margin:0 auto 6px;background:var(--surface3);border:2px solid var(--border2);font-style:normal;font-weight:800;font-size:.66rem;color:var(--muted);position:relative;z-index:1}
.jst>div.done i{background:var(--accent-soft);border-color:var(--accent-soft);color:#fff}
.jst>div.now i{box-shadow:0 0 0 4px rgba(59,130,246,.22)}
.jst>div.no i{background:var(--down-soft);border-color:var(--down-soft);color:#fff}
.jst>div.done,.jst>div.now{color:var(--text2)}
.jst small{display:block;font-size:.56rem;color:var(--muted);text-transform:none;letter-spacing:0;margin-top:2px}
.jev{border-top:1px solid var(--border);padding:8px 0;display:flex;gap:10px;font-size:.8rem;line-height:1.45}
.jev span{flex:none;width:44px;color:var(--muted);font-variant-numeric:tabular-nums;font-size:.7rem;padding-top:2px}
.lc{padding:14px 40px 12px 14px;margin-top:10px;position:relative;cursor:pointer}
.lc .lct{display:flex;align-items:flex-start;gap:11px}
.lc .lcb{flex:none;width:36px;height:36px;border-radius:11px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:1rem}
.lc h4{margin:0;font-size:.95rem;font-weight:700;line-height:1.3;color:var(--text);letter-spacing:-.005em}
.lc .lcc{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}
.lc .lcn{font-size:.8rem;color:var(--muted2);line-height:1.5;margin-top:9px}
.lc .lcm{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:.66rem;color:var(--muted);margin-top:9px;font-variant-numeric:tabular-nums}
.lc .chv{position:absolute;right:12px;top:16px;color:var(--muted)}
.kv{display:flex;align-items:center;gap:8px;padding:10px 0;border-top:1px solid var(--border);font-size:.8rem}
.kv:first-child{border-top:0}
.kv .kvt{flex:1;min-width:0}.kv .kvt b{display:block;font-size:.86rem;color:var(--text);line-height:1.3}.kv .kvt span{display:block;color:var(--muted2);font-size:.74rem;font-variant-numeric:tabular-nums;margin-top:2px}
.pchip{display:inline-flex;align-items:center;font-size:.6rem;font-weight:800;letter-spacing:.05em;text-transform:uppercase;border-radius:99px;padding:3px 8px;white-space:nowrap}
.prow{display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-top:1px solid var(--border);font-size:.8rem;color:var(--text2);line-height:1.5}
.prow .pk{flex:none;width:66px;font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;padding-top:4px}
.pman{margin-top:10px;padding:10px 12px;border-radius:12px;background:var(--accent-bg,rgba(59,130,246,.10));border:1px solid rgba(59,130,246,.28);font-size:.84rem;color:var(--text);line-height:1.5}
.pman .pk{display:block;color:var(--accent-soft);font-size:.58rem;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}
.tfc{border:1px solid var(--border);background:transparent;color:var(--muted2);border-radius:99px;
 padding:6px 13px;font-size:.74rem;font-weight:700;white-space:nowrap;flex:none}
.tfc.on{background:var(--surface3);border-color:var(--border2);color:var(--text2)}
#tfilt{display:flex;gap:8px;overflow-x:auto;padding:2px 0 10px;scrollbar-width:none}
#tfilt::-webkit-scrollbar{display:none}
#ptr{position:fixed;left:50%;transform:translate(-50%,-90px);top:calc(58px + env(safe-area-inset-top,0px));
 z-index:44;background:var(--surface3);border:1px solid var(--border2);color:var(--text2);
 border-radius:99px;padding:7px 14px;font-size:.78rem;font-weight:700;transition:transform .25s;
 display:flex;align-items:center;gap:8px;box-shadow:0 8px 24px rgba(0,0,0,.25)}
#ptr.on{transform:translate(-50%,0)}
.gbar{height:8px;border-radius:99px;background:var(--surface3);overflow:hidden;margin-top:12px}
.gbar>i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--accent),var(--up));transition:width .6s}
/* 2026-10-01 (owner): eight controls on the home screen measured under
   44px - the header pills at 28, the chart range chips at 24, the ledger
   info at 26. The Nid buttons were raised this morning; these are the
   same standard. What grows is the HIT AREA, through a transparent
   overlay, because a 44px-tall "7 j" chip would look absurd. The pills
   keep their size and the thumb gets its target. */
.tap44{position:relative}
.tap44::after{content:"";position:absolute;left:50%;top:50%;
 transform:translate(-50%,-50%);width:100%;height:44px;min-width:44px}
/* 2026-10-02 (owner): the Labo landing - three doors answering the only
   three questions anyone has, before the pipeline rail drops them into
   the middle of it. Restraint, as on the weather card: a number that
   leads, a hairline, one accent each, and a real 44px target. */
/* 2026-10-02: the chercheur's night, as one row under the doors. */
@keyframes jland{0%{box-shadow:0 0 0 0 rgba(127,179,224,.55)}
 100%{box-shadow:0 0 0 12px rgba(127,179,224,0)}}
.jland{animation:jland .9s ease-out 1;border-radius:var(--r-lg)}
/* 2026-10-02 (owner): the night report - one page read top to bottom. */
.nt-eye{font-size:.62rem;font-weight:700;letter-spacing:.12em;
 text-transform:uppercase;color:#b98cff}
#sheet h3.nt-h{font-size:1.2rem;line-height:1.36;font-weight:650;
 letter-spacing:-.015em;margin:8px 0 12px;color:var(--text);
 display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;
 overflow:hidden;cursor:pointer}
#sheet h3.nt-h.open{display:block;-webkit-line-clamp:unset}
.nt-pill em{font-style:normal;color:var(--muted);margin-left:1px;
 font-variant-numeric:tabular-nums}
.nt-cast{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}
.nt-pill{display:inline-flex;align-items:center;gap:7px;padding:6px 11px 6px 9px;
 border-radius:99px;background:var(--surface2);border:1px solid var(--border);
 font-size:.74rem;font-weight:600;color:var(--text2);font:inherit;cursor:pointer}
.nt-pill i{width:7px;height:7px;border-radius:99px;flex:none}
.nt-nav{position:sticky;top:0;z-index:2;display:flex;gap:2px;overflow-x:auto;
 margin:0 -20px 4px;padding:8px 16px;scrollbar-width:none;
 background:rgba(18,26,37,.86);backdrop-filter:blur(12px);
 -webkit-backdrop-filter:blur(12px);border-bottom:1px solid var(--border)}
:root[data-theme=light] .nt-nav{background:rgba(255,255,255,.86)}
.nt-nav::-webkit-scrollbar{display:none}
.nt-nav button{flex:none;min-height:36px;padding:0 10px;border:0;border-radius:9px;
 background:transparent;color:var(--muted);font-size:.78rem;font-weight:600;
 white-space:nowrap;font:inherit;cursor:pointer}
.nt-nav button i{font-style:normal;font-size:.66rem;opacity:.7;margin-right:5px;
 font-variant-numeric:tabular-nums}
.nt-nav button.on{color:var(--text);background:var(--surface2)}
.nt-sec{scroll-margin-top:56px;padding-top:24px}
.nt-sh{display:flex;align-items:baseline;gap:8px;margin-bottom:6px}
.nt-sh i{font-style:normal;font-size:.64rem;font-weight:700;letter-spacing:.1em;
 color:#b98cff;font-variant-numeric:tabular-nums}
.nt-sh b{font-size:.68rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
 color:var(--muted2)}
.nt-sh::after{content:"";flex:1;height:1px;background:var(--border);margin-left:4px}
.nt-sub{font-size:.84rem;color:var(--muted2);line-height:1.5;margin:4px 0 12px}
.nt-cap{font-size:.72rem;color:var(--muted);margin:10px 2px 0;text-align:right}
.nt-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.nt-tile{background:var(--tile-bg);border:1px solid var(--tile-bd);
 border-radius:14px;padding:14px 8px 12px;text-align:center}
.nt-tile b{display:block;font-size:1.7rem;line-height:1;font-weight:700;
 letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.nt-tile span{display:block;margin-top:7px;font-size:.68rem;line-height:1.3;
 color:var(--muted2)}
.nt-fold{background:transparent;border:0;border-top:1px solid var(--border);
 border-radius:0;margin:0;overflow:hidden}
.nt-fold:last-of-type{border-bottom:1px solid var(--border)}
.nt-fold summary{list-style:none;display:flex;align-items:center;gap:10px;
 min-height:46px;padding:12px 2px;font-weight:600;font-size:.92rem;
 color:var(--text);cursor:pointer}
.nt-fold summary::-webkit-details-marker{display:none}
.nt-fold summary .chv{margin-left:auto;flex:none;width:16px;height:16px;
 color:var(--muted);transition:transform .2s}
.nt-fold[open] summary .chv{transform:rotate(90deg)}
.nt-fold .nt-b{padding:0 2px 14px;font-size:.92rem;line-height:1.6;color:var(--text2)}
.nt-fold .nt-b p{margin:0 0 9px;font-size:.92rem;color:var(--text2)}
.nt-fold .nt-b p:last-child{margin-bottom:0}
.nt-card{background:var(--tile-bg);border:1px solid var(--tile-bd);
 border-radius:14px;padding:13px 14px;margin-bottom:8px}
.nt-card b{display:block;font-size:.93rem;font-weight:600;line-height:1.4;
 letter-spacing:-.005em;color:var(--text)}
.nt-card span.nt-w{display:block;margin-top:6px;font-size:.82rem;line-height:1.55;
 color:var(--text2)}
.nt-chip{display:inline-flex;align-items:center;gap:6px;margin-bottom:8px;padding:0;
 border-radius:0;font-size:.62rem;font-weight:700;letter-spacing:.1em;
 text-transform:uppercase;background:transparent!important}
.nt-chip::before{content:"";width:6px;height:6px;border-radius:99px;background:currentColor}
.nt-go{margin-top:12px;min-height:40px;width:auto;padding:0 14px;font-size:.78rem}
.nt-day{position:relative;padding-left:18px;margin:4px 0 0}
.nt-day::before{content:"";position:absolute;left:5px;top:8px;bottom:10px;width:1px;
 background:var(--border2)}
.nt-ev{position:relative;padding:0 0 16px}
.nt-ev:last-child{padding-bottom:4px}
.nt-dot{position:absolute;left:-18px;top:5px;width:11px;height:11px;border-radius:99px;
 background:var(--surface);border:2px solid var(--accent-soft)}
.nt-ev time{display:block;font-size:.66rem;color:var(--muted);letter-spacing:.06em;
 margin-bottom:3px;font-variant-numeric:tabular-nums}
.nt-ev p{margin:0;font-size:.9rem;line-height:1.55;color:var(--text)}
.nt-none{font-size:.84rem;color:var(--muted);padding:4px 0}
/* no media query hiding anything: the column stacks on its own, and a
   door without its sentence is a door nobody can read. */
.ibdot{width:8px;height:8px;border-radius:99px;background:var(--accent);display:inline-block;margin-left:6px;vertical-align:middle}
.hl{animation:hlp 1.6s ease-in-out 2}
@keyframes hlp{0%,100%{box-shadow:var(--hl)}50%{box-shadow:0 0 0 2px var(--accent),0 0 28px rgba(59,130,246,.45)}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
.bdg{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:6px 0 4px}
.stpi{display:flex;align-items:center;gap:10px;background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:11px 12px}
.stpi .stpc{width:34px;height:34px;border-radius:10px;flex:none;display:flex;align-items:center;justify-content:center;background:var(--accent-soft-bg,rgba(59,130,246,.14));color:var(--accent-soft)}
.stpi b{display:block;font-size:.84rem;line-height:1.25}
.stpi span{font-size:.7rem;color:var(--muted2)}
.stpi.off{opacity:.45}.stpi.off .stpc{background:var(--surface3);color:var(--muted)}
.sincegrid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}
.sincegrid>div{background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:10px 8px;text-align:center}
.sincegrid b{display:block;font-size:1rem}.sincegrid span{font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
</style></head><body>
<script>try{if(localStorage.getItem('owlTheme')==='light')document.documentElement.dataset.theme='light';if(localStorage.getItem('owlPin:'+location.pathname))document.documentElement.classList.add('locked');if(localStorage.getItem('owlBig')==='1')document.documentElement.style.fontSize='112.5%'}catch(e){}</script>

<div class="hero">
<div class="topline"><span style="display:flex;flex-direction:column;align-items:flex-start;gap:3px">
<span class="brand"><img class="brandmk" src="icon192.png" alt="">OwlNest</span>
<span style="display:flex;align-items:center;gap:8px"><span id="acctline"></span><span class="live" id="lv"><span class="dot" id="lvd"></span><span id="lvt">EN DIRECT</span></span></span></span>
<span style="display:flex;align-items:center;gap:8px;flex:none">
<button id="acctchip" onclick="acctSheet()" aria-label="Changer de compte" style="display:none;align-items:center;gap:5px;
 color:#dbe9f7;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);
 border-radius:99px;padding:5px 8px;font-size:.7rem;font-weight:700;line-height:1"><svg class="ic ic-s"><use href="#i-users"/></svg><span id="acctchip-n"></span></button>
<button id="hbell" class="tap44" onclick="inboxSheet()" title="Messages" aria-label="Messages" style="position:relative;line-height:1;display:inline-flex;
 color:#dbe9f7;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);border-radius:99px;padding:5px 9px"><svg class="ic ic-s"><use href="#i-bell"/></svg><span id="hbell-n" style="display:none;position:absolute;top:-7px;right:-7px;min-width:17px;height:17px;border-radius:99px;background:var(--down);color:#fff;font-size:.6rem;font-weight:800;align-items:center;justify-content:center;padding:0 4px;border:2px solid #0e1a2b"></span></button>
<a id="chartlink" class="tap44" href="#" title="Graphique en direct" aria-label="Graphique en direct"
 style="text-decoration:none;line-height:1;display:inline-flex;
 color:#dbe9f7;background:rgba(255,255,255,.08);
 border:1px solid rgba(255,255,255,.14);
 border-radius:99px;padding:5px 9px"><svg class="ic ic-s"><use href="#i-chart"/></svg></a>
</span></div>
<!-- 2026-10-01 (owner): the wave was the last emoji in the hero. -->
<div class="hello" id="hello">Bonjour %%NAME%%</div>
<div class="money skel" id="eq">&#8226;&#8226;&#8226;</div>
<div class="eur" id="eqe" style="display:none"></div>
<!-- 2026-09-27 (owner: "the hero looks busy"): one line under the number
     - today's result and the trade count - then at most one pill for the
     running trade (plus the day-objective ring when a daily cap is on).
     Account identity lives under the brand; "en rattrapage" moved to the
     rattrapage card; the closed balance is one tap on the trade pill. -->
<div class="dayline" id="dayline" role="button" tabindex="0" aria-label="Partager ma journ&eacute;e" style="cursor:pointer" onclick="shareDay()">&nbsp;</div>
<div class="chips" id="chips"><span id="daytargetchip" style="display:none;padding:5px 12px;
 border-radius:99px;font-size:.72rem;font-weight:700;
 background:rgba(127,179,224,.13);color:var(--text3)"></span>
<span id="tradepill" class="hchip" role="button" tabindex="0" style="display:none" onclick="tradePillTap()"></span></div>
</div>
<div class="wrap">
<div class="tab on" id="tab-home">
<div id="ptr"><svg class="ic ic-s"><use href="#i-activity"/></svg>Actualisation...</div>
<div class="panel" id="firstfail" style="display:none;margin-top:26px;text-align:center">
 <div style="color:var(--muted2);margin:6px auto 0;width:44px;height:44px;border-radius:13px;
  background:var(--surface3);display:flex;align-items:center;justify-content:center"><svg class="ic"><use href="#i-cloud"/></svg></div>
 <b style="display:block;margin-top:10px;font-size:1rem">Impossible de joindre le robot</b>
 <div style="font-size:.86rem;color:var(--muted2);margin-top:4px;line-height:1.45">V&eacute;rifiez votre
  connexion. Le robot, lui, continue de travailler.</div>
 <button class="shbtn shmain" style="margin-top:14px" onclick="retryLoad()">R&eacute;essayer</button>
</div>
<div class="panel" id="welcome" style="display:none;margin-top:26px">
 <div class="lbl">Bienvenue</div>
 <div style="font-size:.95rem;color:var(--text);line-height:1.5;margin-top:8px">
  Le robot commence &agrave; surveiller le march&eacute; pour vous. Voici ce
  qui va appara&icirc;tre ici :</div>
 <div style="margin-top:6px">
  <div class="srow-ev"><div class="evi" style="color:var(--accent-soft)"><svg class="ic ic-s"><use href="#i-eye"/></svg></div>
   <div style="flex:1"><b>Le march&eacute;</b><div style="font-size:.84rem;color:var(--muted2)">Ce que le robot voit, et ce qu&#39;il fait aujourd&#39;hui.</div></div></div>
  <div class="srow-ev"><div class="evi" style="color:var(--up)"><svg class="ic ic-s"><use href="#i-chart"/></svg></div>
   <div style="flex:1"><b>Votre premier trade</b><div style="font-size:.84rem;color:var(--muted2)">D&egrave;s que le robot agit, il s&#39;affiche ici et dans l&#39;Historique.</div></div></div>
  <div class="srow-ev"><div class="evi" style="color:var(--warn)"><svg class="ic ic-s"><use href="#i-bell"/></svg></div>
   <div style="flex:1"><b>Les notifications</b><div style="font-size:.84rem;color:var(--muted2)">Activez-les dans les R&eacute;glages pour &ecirc;tre pr&eacute;venu.</div></div></div>
 </div>
</div>
<div class="panel" id="renewcard" style="display:none;margin-top:26px;border-color:rgba(232,197,90,.4)">
 <div style="display:flex;align-items:center;gap:12px">
  <div class="sic" style="color:var(--warn);background:rgba(232,197,90,.12)"><svg class="ic"><use href="#i-key"/></svg></div>
  <div style="flex:1;min-width:0"><b id="renew-t" style="font-size:.98rem"></b>
   <div id="renew-s" style="font-size:.82rem;color:var(--muted2);line-height:1.4;margin-top:2px"></div></div>
  <button id="renew-b" class="shbtn shmain" style="width:auto;margin:0;padding:9px 12px;font-size:.82rem;min-height:0"></button>
 </div>
</div>
<div class="panel" id="missedcard" style="display:none;margin-top:12px">
 <div style="display:flex;align-items:center;gap:12px">
  <div class="sic" style="color:var(--accent-soft);background:rgba(59,130,246,.12)"><svg class="ic"><use href="#i-calendar"/></svg></div>
  <div style="flex:1;min-width:0"><b id="missed-t" style="font-size:.98rem"></b>
   <div id="missed-s" style="font-size:.78rem;color:var(--muted2);margin-top:2px"></div></div>
  <button onclick="window._missedDone=true;document.getElementById('missedcard').style.display='none'" aria-label="Fermer" style="border:1px solid var(--border2);background:var(--surface3);color:var(--muted);border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center"><svg class="ic ic-s"><use href="#i-x"/></svg></button>
 </div>
 <div id="missed-g" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:10px"></div>
 <div id="missed-sig" style="font-size:.8rem;color:var(--muted2);margin-top:8px"></div>
</div>
<div class="panel" id="expcard" style="display:none;margin-top:12px;border-color:rgba(232,197,90,.45)">
 <div style="display:flex;align-items:center;gap:12px"><div style="flex:1;min-width:0"><b id="exp-t"></b><div id="exp-b" style="font-size:.84rem;color:var(--text2);margin-top:4px;line-height:1.45"></div></div></div>
 <div style="display:flex;gap:8px;margin-top:10px"><button class="shbtn shmain" id="exp-go" style="flex:1;margin:0;padding:10px"></button></div>
</div>
<div class="panel" id="apkcard" style="display:none;margin-top:12px;border-color:rgba(46,204,113,.35)">
 <div style="display:flex;align-items:center;gap:12px"><div style="flex:1;min-width:0"><b id="apk-t"></b><div id="apk-b" style="font-size:.84rem;color:var(--text2);margin-top:4px;line-height:1.45"></div></div></div>
 <div style="display:flex;gap:8px;margin-top:10px"><a class="shbtn shmain" id="apk-go" href="/owlnest.apk" style="flex:1;margin:0;padding:10px;text-align:center;text-decoration:none"></a><button class="shbtn shghost" id="apk-no" style="flex:0 0 auto;margin:0;padding:10px 14px" onclick="apkDismiss()"></button></div>
</div>
<div class="panel" id="newscard" style="display:none;margin-top:12px;border-color:rgba(59,130,246,.35)">
 <div style="display:flex;align-items:center;gap:12px">
  <div class="sic" style="color:var(--accent-soft);background:rgba(59,130,246,.12)"><svg class="ic"><use href="#i-gift"/></svg></div>
  <div style="flex:1;min-width:0"><b id="news-t" style="font-size:.98rem"></b>
   <div id="news-s" style="font-size:.78rem;color:var(--muted2);margin-top:2px"></div></div>
 </div>
 <!-- 2026-10-01 (owner): this list was 1121px of a 2541px page - 44%,
      above the member's own day. It opens in a sheet now; the card keeps
      one line. -->
 <div id="news-list" style="display:none"></div>
 <div style="display:flex;gap:8px;margin-top:10px">
  <button id="news-open" class="shbtn shghost" style="flex:1;margin:0;padding:10px;font-size:.86rem"></button>
  <button id="news-b" class="shbtn shghost" style="flex:1;margin:0;padding:10px;font-size:.86rem"></button>
 </div>
</div>
<div class="panel" id="nopushcard" style="display:none;margin-top:12px;border-color:rgba(255,92,92,.45)">
 <div style="display:flex;align-items:center;gap:12px">
  <div class="sic" style="color:var(--down-soft);background:rgba(255,92,92,.12)"><svg class="ic"><use href="#i-bell"/></svg></div>
  <div style="flex:1;min-width:0"><b id="nopush-t" style="font-size:.98rem"></b>
   <div id="nopush-s" style="font-size:.82rem;color:var(--muted2);line-height:1.4;margin-top:2px"></div></div>
  <button id="nopush-b" class="shbtn shmain" style="width:auto;margin:0;padding:9px 12px;font-size:.82rem;min-height:0"></button>
 </div>
</div>
<div class="panel" id="sigcard" style="display:none;margin-top:12px;border-width:1.5px">
 <div style="display:flex;justify-content:space-between;align-items:center">
  <div class="lbl" id="sig-lbl">Signal</div><span id="sig-when" style="font-size:.72rem;color:var(--muted)"></span></div>
 <div style="display:flex;align-items:center;gap:12px;margin-top:8px">
  <div id="sig-dir" style="font-size:1.35rem;font-weight:800;letter-spacing:-.01em"></div>
  <div id="sig-sym" style="font-size:.8rem;color:var(--muted2)">BTCUSD</div></div>
 <div id="sig-g" style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px"></div>
 <div id="sig-mylot" style="display:none;font-size:.78rem;color:var(--muted2);margin-top:8px;line-height:1.45"></div>
 <div id="sig-note" style="font-size:.8rem;color:var(--muted2);line-height:1.45;margin-top:8px"></div>
 <div id="sig-mark" style="display:none;margin-top:10px"></div>
 <div style="display:flex;gap:8px;margin-top:12px">
  <a id="sig-chart" href="#" class="shbtn shmain" style="flex:1 1 46%;margin:0;padding:11px;text-align:center;text-decoration:none;font-size:.88rem">Prendre sur le graphique</a>
  <button id="sig-copy" class="shbtn shghost" style="flex:none;margin:0;padding:11px 14px;font-size:.88rem" onclick="sigCopy()">Copier</button>
 </div>
</div>
<div class="panel" id="kinocard" style="display:none;margin-top:12px">
 <div class="lbl">Le robot du Owl &middot; r&eacute;sultats</div>
 <div id="kino-g" style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px"></div>
 <svg id="kino-spark" viewBox="0 0 300 44" style="width:100%;height:44px;display:none;margin-top:10px"></svg>
 <div id="kino-s" style="font-size:.78rem;color:var(--muted2);margin-top:8px"></div>
 <div style="display:flex;gap:8px;margin-top:12px">
  <a id="kino-link" href="/demo" class="shbtn shghost" style="flex:1;margin:0;padding:10px;text-align:center;text-decoration:none;font-size:.86rem">Voir en direct</a>
  <button class="shbtn shmain" style="flex:1;margin:0;padding:10px;font-size:.86rem" onclick="offersSheet()">Les offres</button>
 </div>
</div>
<div class="glass" id="offercard" role="button" tabindex="0" style="display:none;margin-top:26px;padding:14px 16px;cursor:pointer" onclick="offersSheet()">
 <div class="sheen"></div>
 <div style="position:relative;display:flex;align-items:center;gap:12px">
  <div class="sic" style="color:var(--warn);background:rgba(232,197,90,.14)"><svg class="ic"><use href="#i-key"/></svg></div>
  <div style="flex:1;min-width:0"><b id="offercard-t" style="font-size:.98rem"></b>
   <div id="offercard-s" style="font-size:.8rem;color:var(--muted2);line-height:1.4;margin-top:2px"></div></div>
  <button onclick="event.stopPropagation();try{localStorage.setItem('owlOfferHide:'+B,String(Date.now()))}catch(e){};this.closest('#offercard').style.display='none'" aria-label="Fermer" style="border:0;background:transparent;color:var(--muted);font-size:1.1rem;padding:4px">&times;</button>
 </div>
</div>
<!-- 2026-10-01 (owner): "Pourquoi rien aujourd'hui". The robot has
     always written the reason in its log and the app never showed it, so a
     quiet day and a broken day looked the same from the phone. -->
<!-- 2026-10-01 (owner): the day that just closed, once per day. It sits
     BELOW the day-done card on purpose - this one is yesterday, and
     yesterday must not lead today. -->
<div class="panel" id="recap" style="display:none;margin-top:26px;
 border-color:rgba(59,130,246,.3)">
 <div style="display:flex;align-items:flex-start;gap:12px">
  <div class="sic" style="color:var(--accent-soft)"><svg class="ic"><use href="#i-moon"/></svg></div>
  <div style="flex:1;min-width:0"><b id="recap-t" style="font-size:1rem"></b>
   <div id="recap-s" style="font-size:.84rem;color:var(--muted2);line-height:1.45;margin-top:3px"></div></div>
  <button id="recap-x" onclick="recapHide()" aria-label="Fermer"
   style="flex:none;border:0;background:transparent;color:var(--muted);
   min-width:40px;min-height:40px;font-size:1rem">&times;</button>
 </div>
</div>
<div class="panel" id="whyidle" style="display:none;margin-top:26px">
 <div style="display:flex;align-items:center;gap:12px">
  <div class="sic"><svg class="ic"><use href="#i-info"/></svg></div>
  <div style="flex:1;min-width:0"><b id="whyidle-t" style="font-size:1rem"></b>
   <div id="whyidle-s" style="font-size:.84rem;color:var(--muted2);line-height:1.45;margin-top:2px"></div></div>
 </div>
</div>
<div class="panel" id="daydone" style="display:none;margin-top:26px;border-color:rgba(46,204,113,.35)">
 <div style="display:flex;align-items:center;gap:12px">
  <div class="sic" style="color:var(--up);background:rgba(46,204,113,.12)"><svg class="ic"><use href="#i-check"/></svg></div>
  <div style="flex:1;min-width:0"><b id="daydone-t" style="font-size:1rem"></b>
   <div id="daydone-s" style="font-size:.84rem;color:var(--muted2);line-height:1.45;margin-top:2px"></div></div>
 </div>
</div>
<div class="panel" id="nudge" style="display:none;margin-top:26px">
 <div style="display:flex;align-items:flex-start;gap:12px">
  <div class="sic" style="color:var(--warn)"><svg class="ic"><use href="#i-bell"/></svg></div>
  <div style="flex:1;min-width:0"><b>Les notifications</b>
   <div style="font-size:.86rem;color:var(--muted2);line-height:1.45;margin-top:2px">Vous n&#39;avez rien manqu&eacute; pour l&#39;instant. Activez-les pour &ecirc;tre pr&eacute;venu des trades et du bilan du soir.</div>
   <div style="display:flex;gap:8px;margin-top:10px">
    <button class="shbtn shmain" style="margin:0;padding:10px 14px;width:auto;font-size:.86rem" onclick="nudgeGo()">Activer</button>
    <button class="shbtn shghost" style="margin:0;padding:10px 14px;width:auto;font-size:.86rem" onclick="nudgeDone()">Plus tard</button>
   </div></div>
 </div>
</div>
<div class="glass" id="mxsum" role="button" tabindex="0" aria-label="Voir le march&eacute;"
 style="margin-top:26px;padding:16px 16px 14px;cursor:pointer"
 onclick="tab('marche',document.getElementById('tb-marche'));mxView('market',true)">
 <div class="sheen"></div>
 <div style="position:relative;display:flex;align-items:center;gap:12px">
  <div id="mxs-orb" class="orbsm"></div>
  <div style="flex:1;min-width:0">
   <div style="font-size:.66rem;color:var(--muted);text-transform:uppercase;
    letter-spacing:.08em">Le march&eacute;</div>
   <b id="mxs-title" style="font-size:1.02rem;display:block;margin-top:2px">
    ...</b>
   <div id="mxs-sub" style="font-size:.78rem;color:var(--muted2);margin-top:2px;
    line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;
    -webkit-box-orient:vertical;overflow:hidden"></div>
  </div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <svg id="mxs-spark" viewBox="0 0 300 40" style="position:relative;width:100%;
  height:40px;display:none;margin-top:10px"></svg>
 <div id="mxs-day" style="position:relative;font-size:.76rem;color:var(--muted);
  margin-top:8px"></div>
</div>
<div class="panel" id="palier" style="display:none;margin-top:12px">
 <div class="lbl">Croissance</div>
 <div style="font-size:.92rem;color:var(--text2);margin-top:8px"
  id="palier-lbl"></div>
 <div style="background:var(--surface3);border-radius:99px;height:6px;
  margin-top:8px"><div id="palier-bar" style="
  transition:width .9s cubic-bezier(.2,.8,.2,1);background:
  var(--up);height:6px;border-radius:99px;width:0%"></div></div>
 <div class="sub" id="grow-lot"></div>
</div>
<div id="trial" style="display:none;margin-top:10px;text-align:center;
 background:rgba(232,197,90,.12);border:1px solid rgba(232,197,90,.35);border-radius:14px;
 padding:10px;color:var(--warn);font-size:.9rem"></div>
<div id="ftcard" style="display:none;margin-top:12px;
 background:linear-gradient(150deg,var(--surface3),var(--surface2));
 border:1px solid var(--border2);border-radius:16px;padding:14px;
 color:var(--text2);font-size:.9rem;line-height:1.5">
 <div style="font-size:.7rem;color:var(--accent-soft);text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:6px">&#129514; Le grand test
  de la strat&eacute;gie</div>
 <div id="ft-txt"></div>
 <div style="background:rgba(255,255,255,.15);border-radius:99px;
  height:8px;margin-top:8px"><div id="ft-bar" style="height:8px;
  border-radius:99px;width:0%;background:var(--accent-soft)"></div></div>
 <div id="ft-sub" style="font-size:.76rem;color:var(--muted);
  margin-top:6px"></div>
</div>
<div id="ledcard" style="display:none;position:relative;margin-top:12px;
 background:var(--surface2);border:1px solid var(--border2);border-radius:16px;
 padding:14px;color:var(--text2);font-size:.92rem;line-height:1.5">
 <button onclick="ledInfo()" aria-label="explications" class="tap44" style="
  position:absolute;right:10px;top:10px;width:26px;height:26px;
  border-radius:50%;border:1px solid rgba(127,179,224,.4);
  background:rgba(127,179,224,.12);color:var(--accent-soft);font-size:.8rem;
  font-weight:700;font-style:italic;font-family:Georgia,serif;
  cursor:pointer;animation:ipulse 2.6s ease-out infinite">i</button>
 <div id="led-hd" style="font-size:.7rem;color:var(--muted);
  text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">
  Le rattrapage</div>
 <div id="led-txt"></div>
 <div id="led-barwrap" style="display:none;
  background:rgba(255,255,255,.15);border-radius:99px;height:8px;
  margin-top:8px"><div id="led-bar" style="background:var(--warn);
  height:8px;border-radius:99px;width:0%"></div></div>
 <div id="led-sub" style="font-size:.78rem;color:var(--muted);margin-top:6px">
 </div>
</div>
<div id="actcard" class="panel" style="display:none;margin-top:12px">
 <div class="lbl">Activer le robot</div>
 <div class="jsteps" style="margin-top:12px"><div class="jl"></div>
  <div class="js done" data-i="1"><div class="jc"><svg class="ic ic-s"><use href="#i-check"/></svg></div><span>Compte</span></div>
  <div class="js on" data-i="2"><div class="jc"><svg class="ic ic-s"><use href="#i-key"/></svg></div><span>Code</span></div>
  <div class="js" data-i="3"><div class="jc"><svg class="ic ic-s"><use href="#i-bot"/></svg></div><span>Pr&ecirc;t</span></div>
 </div>
 <div style="font-size:.95rem;color:var(--text);line-height:1.5;margin-top:12px">
  Votre compte est connect&eacute;. Il reste un code &agrave; entrer :
  demandez-le &agrave; <b>le Owl sur Telegram</b>.</div>
 <div style="display:flex;gap:8px;margin-top:12px">
  <input id="actcode" inputmode="text" autocapitalize="characters"
   maxlength="6" placeholder="CODE" aria-label="Code d&#39;activation"
   style="flex:1;min-width:0;padding:12px;font-size:1.25rem;text-align:center;
   letter-spacing:.3em;border-radius:12px;border:1px solid var(--border2);
   background:var(--bg);color:var(--text);text-transform:uppercase">
  <button id="actbtn" style="background:var(--accent);color:#fff;border:0;
   border-radius:12px;padding:12px 20px;font-size:1rem;font-weight:700;
   flex:none">Activer</button>
 </div>
 <div id="actmsg" style="margin-top:8px;font-size:.85rem;color:var(--down-soft)"></div>
</div>
<div id="battles-sec" style="display:none">
<div class="panel" style="margin-top:24px;
 background:linear-gradient(135deg,var(--surface3),var(--surface2));
 border:1px solid var(--border2);box-shadow:0 6px 22px rgba(37,99,235,.28)">
 <div style="display:flex;justify-content:space-between;
  align-items:center;margin-bottom:6px">
  <span style="font-size:.7rem;color:var(--accent-soft);text-transform:uppercase;
   letter-spacing:.08em;font-weight:700;display:inline-flex;
   align-items:center;gap:6px"><svg class="ic ic-s"><use href="#i-wave"/></svg>En plein
   combat</span>
  <span style="font-size:.66rem;color:var(--up-soft);font-weight:800;
   letter-spacing:.06em"><span class="livedot"></span>EN DIRECT</span>
 </div>
 <div id="battles"></div>
 <a id="batchart" href="#" style="display:flex;align-items:center;
  justify-content:center;gap:7px;margin-top:10px;padding:9px;
  border-radius:12px;text-decoration:none;color:var(--accent-soft);
  font-size:.8rem;font-weight:700;
  background:rgba(127,179,224,.1);
  border:1px solid rgba(127,179,224,.3)"><svg class="ic ic-s"><use href="#i-chart"/></svg> Suivre sur le
  graphique en direct</a>
</div>
</div>
<!-- 2026-10-01 (owner): this was a 2x2. "Aujourd'hui" repeated the hero
     figure word for word, and "Pire creux" was the only red tile among
     greens - the eye landed on it first - while the same number was
     already labelled on the chart below. Today is the hero; the worst dip
     belongs to the chart. What is left is the pair that says something
     the hero does not. #today and #dd stay in the DOM, hidden, because
     render() writes to them every tick. -->
<div class="grid">
<div class="card"><div class="lbl">Cette semaine</div>
<div class="val skel" id="week">--</div>
<div class="sub">depuis lundi</div></div>
<div class="card"><div class="lbl">Ce mois</div>
<div class="val skel" id="month">--</div>
<!-- 2026-10-01 (owner): on the 1st this tile sits beside a full week and
     reads as a collapse, in either direction. It says which day it is
     while that still explains the gap. -->
<div class="sub" id="monthsub">depuis le 1er</div></div>
</div>
<div id="today" style="display:none"></div>
<div id="dd" style="display:none"></div>
<div class="panel" id="pgoal" style="display:none;margin-top:12px;cursor:pointer" role="button"
 tabindex="0" onclick="myGoal()" aria-label="Mon objectif">
 <div style="display:flex;align-items:center;gap:12px">
  <div class="sic" style="color:var(--accent-soft)"><svg class="ic"><use href="#i-target"/></svg></div>
  <div style="flex:1;min-width:0"><div class="lbl">Mon objectif</div>
   <b id="pgoal-t" style="font-size:1rem;display:block;margin-top:2px"></b></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="gbar"><i id="pgoal-bar" style="width:0%"></i></div>
 <div id="pgoal-s" style="font-size:.8rem;color:var(--muted2);margin-top:8px"></div>
</div>
<div class="sec" style="display:flex;justify-content:space-between;
 align-items:center">Progression
 <span><button class="cvc" data-c="7" style="border:1px solid var(--border2);
  background:var(--surface3);color:var(--text2);border-radius:99px;padding:5px 12px;
  font-size:.72rem;font-weight:700">7 j</button>
 <button class="cvc" data-c="30" style="border:1px solid var(--border);
  background:transparent;color:var(--muted2);border-radius:99px;padding:5px 12px;
  font-size:.72rem;font-weight:700;margin-left:6px">30 j</button>
 <button class="cvc" data-c="90" style="border:1px solid var(--border);
  background:transparent;color:var(--muted2);border-radius:99px;padding:5px 12px;
  font-size:.72rem;font-weight:700;margin-left:6px">3 mois</button></span>
</div>
<div class="panel"><svg id="spark" viewBox="0 0 300 80"
 style="width:100%;height:80px;display:block"></svg>
 <!-- 2026-10-01 (owner): the worst dip, next to the line that shows it,
      and only on the 7-day view it actually measures. -->
 <!-- 2026-10-01 (owner): the curve said how much and never WHEN. -->
 <div id="spkdates" style="display:none;justify-content:space-between;
  font-size:.74rem;color:var(--muted);margin-top:4px"></div>
 <div id="ddcap" style="display:none;font-size:.78rem;color:var(--muted2);
  margin-top:8px"></div></div>
</div>
<div class="tab" id="tab-marche">
<!-- 2026-09-28 (owner): two spaces, one switch - the MARKET (what the
     feed sees, to grow into a real analysis space) and the ROBOT (what
     it does on this account, to grow with AI). No extra tab. -->
<div class="mxseg" id="mxseg" role="tablist">
 <button class="mxs on" id="mxs-market" role="tab" aria-selected="true" onclick="mxView('market')"><svg class="ic ic-s"><use href="#i-wave"/></svg><span>March&eacute;</span></button>
 <button class="mxs" id="mxs-robot" role="tab" aria-selected="false" onclick="mxView('robot')"><svg class="ic ic-s"><use href="#i-bot"/></svg><span>Robot</span></button>
 <button class="mxs" id="mxs-lab" role="tab" aria-selected="false" onclick="mxView('lab')" style="display:none"><svg class="ic ic-s"><use href="#i-target"/></svg><span>Labo</span></button>
</div>
<div id="mx-market">
<!-- 2026-10-01 (owner UX): the Marche tab is four stacked sections and
     the one you want is often the last. A jump row costs one line. -->
<div id="mx-jump" style="display:flex;gap:6px;margin-top:12px;overflow-x:auto;
 scrollbar-width:none;padding-bottom:2px"></div>
<div class="sec" style="margin-top:14px">Le march&eacute; <span class="hint" id="mx-hint">&middot; ce que le robot voit</span></div>
<div id="meteo" class="status mx-sun" style="margin-top:12px;
 position:relative;overflow:hidden;text-align:left;padding:0;
 border-radius:18px">
 <div id="mx-wave"></div>
 <div style="position:relative;padding:15px 16px 13px">
  <div style="display:flex;align-items:center;gap:13px">
   <div id="mx-orb">&#9925;</div>
   <div style="flex:1;min-width:0">
    <b id="mx-title" style="font-size:1.02rem;letter-spacing:.01em">
     ...</b>
    <div id="mx-line" style="font-size:.78rem;color:var(--muted2);
     line-height:1.4;margin-top:2px"></div>
   </div>
   <!-- 2026-10-01 (owner): the card's headline figure was buried in the
        third tile. It belongs where the eye lands first. -->
   <div id="mx-now" style="display:none"><b></b><span></span></div>
  </div>
  <svg id="mx-nerv" viewBox="0 0 300 132" style="width:100%;height:132px;
   display:none;margin-top:14px"></svg>
  <!-- 2026-10-01 (owner): minmax(0,1fr), not 1fr - a grid track will not
       shrink below its content, so the nowrap labels forced each track
       full width and this silently rendered as ONE column. -->
  <div id="mx-chips" style="gap:8px;margin-top:14px"></div>
 </div>
</div>
<div class="panel" id="tfcard" style="display:none;margin-top:12px">
 <div class="lbl">Les temps du march&eacute; <span class="hint" id="tf-hint"></span></div>
 <div id="tf-head" style="margin-top:11px"></div>
 <div id="tf-rows" style="margin-top:13px"></div>
 <div id="tf-foot" style="margin-top:12px"></div>
</div>
<!-- 2026-10-01 (owner): the main Marche page is the market's STATE, in
     time order - the weather now, the timeframes, then the hours. The
     lessons are a reference, not state, so they live behind a card. -->
<div class="panel" id="mhcard" style="display:none;margin-top:12px">
 <div class="lbl">Les heures du march&eacute; <span class="hint" id="mh-hint"></span></div>
 <div id="mh-grid" style="margin-top:10px"></div>
 <div id="mh-leg" style="font-size:.68rem;color:var(--muted);margin-top:8px;display:flex;gap:10px;flex-wrap:wrap;align-items:center"></div>
</div>
<div class="panel" id="lrn-card" style="display:none;margin-top:12px;cursor:pointer"
 role="button" tabindex="0" onclick="lrnOpen()">
 <div style="display:flex;align-items:center;gap:12px">
  <div class="sic"><svg class="ic"><use href="#i-book"/></svg></div>
  <div style="flex:1;min-width:0">
   <b id="lrn-card-t">Ce que le march&eacute; nous apprend</b>
   <div class="ssub" id="lrn-card-s"></div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
</div>
<!-- the lesson block keeps its ids and its renderer; it is MOVED into the
     sheet on open and moved back on close, so nothing is ever duplicated -->
<div id="lrn-wrap" style="display:none">
<div class="sec" id="lrn-sec" style="display:none">Ce que le march&eacute; nous apprend <span class="hint" id="lrn-hint"></span></div>
<div id="lrn-list" style="display:none"></div>
<div class="panel" id="lrn-next" style="display:none;margin-top:12px;border-color:rgba(59,130,246,.35)"></div>
</div>
</div>
<div id="mx-lab" style="display:none">
<div class="sec" style="margin-top:14px">Le labo <span class="hint" id="lab-hint">&middot; id&eacute;es, tests, observations, d&eacute;cisions</span></div>
<div id="lab-stats" style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:10px"></div>
<div id="lab-stale" style="display:none;margin-top:10px;padding:8px 11px;
 background:var(--surface2);border-radius:10px;font-size:.76rem;line-height:1.45"></div>
<div id="lab-parity" style="display:none;margin-top:10px;padding:8px 11px;
 background:var(--surface2);border-radius:10px;font-size:.76rem;line-height:1.45"></div>
<div id="lab-tabs" style="display:flex;gap:6px;margin-top:12px;overflow-x:auto;scrollbar-width:none;padding-bottom:2px"></div>
<div id="lab-body" style="margin-top:4px"></div>
</div>
<div id="mx-robot" style="display:none">
<div class="sec" style="margin-top:14px">Le robot <span class="hint" id="rb-hint">&middot; sur ce compte</span></div>
<div class="panel" id="jcard" style="margin-top:12px">
 <div class="lbl" id="jcard-lbl">Le robot en ce moment</div>
 <div class="jsteps" id="jsteps">
  <div class="jl"></div>
  <div class="js" data-i="1"><div class="jc"><svg class="ic ic-s"><use href="#i-eye"/></svg></div><span>Observe</span></div>
  <div class="js" data-i="2"><div class="jc"><svg class="ic ic-s"><use href="#i-target"/></svg></div><span>Occasion</span></div>
  <div class="js" data-i="3"><div class="jc"><svg class="ic ic-s"><use href="#i-chart"/></svg></div><span>Trade</span></div>
  <div class="js" data-i="4"><div class="jc"><svg class="ic ic-s"><use href="#i-check"/></svg></div><span>Bilan</span></div>
 </div>
 <div id="jmsg" style="font-size:.95rem;color:var(--text);line-height:1.5;margin-top:12px"></div>
 <div id="jprog" style="display:none;margin-top:10px"></div>
 <div id="rb-next" style="display:none;margin-top:12px;padding:10px 12px;border-radius:12px;background:var(--tile-bg);border:1px solid var(--tile-bd);font-size:.88rem;color:var(--text);line-height:1.45"></div>
 <div id="st" style="position:relative;margin:12px 0 0;
  border-top:1px solid rgba(255,255,255,.06);padding:10px 0 2px;
  font-size:.8rem;color:var(--muted)">Connexion...</div>
</div>
<div class="panel pf" id="proofcard" style="display:none;margin-top:12px">
 <div class="lbl" id="proof-lbl">La preuve <span class="hint">&middot; en direct</span></div>
 <div id="proof-lights" style="margin-top:10px"></div>
 <button class="shbtn shmain" style="margin:12px 0 0;padding:11px;font-size:.9rem" onclick="proofPage()">Voir la preuve &rsaquo;</button>
</div>
<div class="panel" id="whycard" style="display:none;margin-top:12px">
 <div class="lbl">Le robot explique <span class="hint">&middot; les occasions laiss&eacute;es passer</span></div>
 <div id="why-sum" style="font-size:.92rem;color:var(--text);line-height:1.5;margin-top:8px"></div>
 <div id="why-bars" style="margin-top:10px"></div>
</div>
<div class="panel" id="daycard" style="display:none;margin-top:12px">
 <div class="lbl" id="day-lbl">La journ&eacute;e du robot</div>
 <div id="day-sum" style="font-size:.95rem;color:var(--text);line-height:1.5;
  margin-top:8px"></div>
 <svg id="daybar" viewBox="0 0 300 34" style="width:100%;height:34px;
  display:block;margin-top:12px"></svg>
 <div id="day-list" style="margin-top:6px"></div>
</div>
<!-- 2026-10-01 (owner): this list rendered 1050px inline, 42% of the
     Robot view - the same thing the changelog was doing on Home. The card
     stays, the list opens in a sheet. The block is MOVED and moved back,
     never cloned: two elements with one id and a renderer that writes by
     id is how the copy on screen goes stale. -->
<div class="panel" id="rjcard" style="display:none;margin-top:12px;
 cursor:pointer" role="button" tabindex="0" onclick="rjOpen()">
 <div style="display:flex;align-items:center;gap:12px">
  <div class="sic"><svg class="ic"><use href="#i-calendar"/></svg></div>
  <div style="flex:1;min-width:0">
   <div class="lbl">Journal du robot</div>
   <b id="rj-sub" style="font-size:.95rem;display:block;margin-top:2px"></b></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
</div>
<div id="rj-wrap" style="display:none">
 <div id="rj-list" style="margin-top:6px"></div>
</div>
</div>
</div>
<div class="tab" id="tab-hist">
<div class="panel" id="since" style="display:none;margin-top:26px">
 <div class="lbl">Depuis le d&eacute;but</div>
 <div id="since-t" style="font-size:.95rem;color:var(--text);line-height:1.5;margin-top:8px"></div>
 <div class="sincegrid" id="since-g"></div>
</div>
<div class="panel" id="tl" style="display:none;margin-top:12px">
 <div class="lbl" id="tl-lbl">Votre parcours</div>
 <div id="tl-list" style="margin-top:8px;position:relative"></div>
</div>
<div class="panel" id="weekcard" style="display:none;margin-top:12px">
 <div class="lbl">Ma semaine</div>
 <div id="week-sum" style="font-size:.95rem;color:var(--text);line-height:1.5;
  margin-top:8px"></div>
 <button id="sharebtn" onclick="shareWeek()" style="width:100%;margin-top:12px;
  background:var(--accent);box-shadow:0 8px 22px rgba(59,130,246,.3);color:#fff;
  border:0;border-radius:14px;padding:13px;font-size:.95rem;font-weight:700;
  display:flex;align-items:center;justify-content:center;gap:8px">
  <svg class="ic"><use href="#i-share"/></svg> Partager ma semaine</button>
</div>
<div class="sec" style="margin-top:20px">Jour par jour
 <span class="hint">&middot; touchez un jour</span></div>
<div class="panel" id="days" style="display:none"></div>
<div class="sec" id="sig-sec" style="display:none">Signaux <span class="hint">&middot; ce que le service vous a envoy&eacute;</span></div>
<div class="panel" id="sigscore" style="display:none"></div>
<div class="panel" id="siglist" style="display:none"></div>
<div class="sec" id="cmp-sec" style="display:none">Vous et le robot <span class="hint">&middot; m&ecirc;me p&eacute;riode</span></div>
<div class="panel" id="cmpcard" style="display:none"></div>
<div class="sec" id="msum-sec" style="display:none;display:flex;justify-content:space-between;
 align-items:center"><span>R&eacute;sum&eacute; du mois</span>
 <button onclick="monthReport()" style="border:1px solid var(--border2);background:var(--surface3);
  color:var(--text2);border-radius:99px;padding:5px 12px;font-size:.72rem;font-weight:700;
  text-transform:none;letter-spacing:0;display:inline-flex;align-items:center;gap:6px">
  <svg class="ic ic-s"><use href="#i-book"/></svg>Rapport</button></div>
<div class="panel" id="msum-verdict" style="display:none;margin-bottom:10px;
 font-size:.95rem;line-height:1.5;color:var(--text)"></div>
<div class="grid" id="msum" style="display:none;margin-top:2px"></div>
<div class="panel" id="mvm" style="display:none;margin-top:10px">
 <div class="lbl" id="mvm-lbl">Ce mois vs le mois dernier</div>
 <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px" id="mvm-g"></div>
 <div id="mvm-t" style="font-size:.92rem;color:var(--text);line-height:1.5;margin-top:10px"></div>
</div>
<div class="sec" id="cal-sec" style="display:none;display:flex;justify-content:space-between;align-items:center"><span>Calendrier</span><span style="display:inline-flex;align-items:center;gap:6px;text-transform:none;letter-spacing:0"><button id="cal-prev" onclick="calNav(1)" aria-label="Mois pr&eacute;c&eacute;dent" style="border:1px solid var(--border2);background:var(--surface3);color:var(--text2);border-radius:99px;width:30px;height:30px;font-size:1rem">&#8249;</button><span id="cal-ym" style="font-size:.78rem;font-weight:700;color:var(--text2);min-width:110px;text-align:center"></span><button id="cal-next" onclick="calNav(-1)" aria-label="Mois suivant" style="border:1px solid var(--border2);background:var(--surface3);color:var(--text2);border-radius:99px;width:30px;height:30px;font-size:1rem">&#8250;</button></span>
</div>
<div class="panel" id="cal" style="display:none"></div>
<div class="sec" id="statx-sec" style="display:none">Statistiques
 &middot; 30 derniers trades</div>
<div class="panel" id="statx" style="display:none"></div>
<div class="sec">Derniers trades</div>
<div id="tfilt"><button class="tfc on" data-f="all">Tous</button><button class="tfc" data-f="won">Gagn&eacute;s</button><button class="tfc" data-f="lost">Perdus</button><button class="tfc" data-f="week">Cette semaine</button></div>
<div id="tgo" style="display:flex;gap:8px;align-items:center;margin:0 0 10px">
 <input type="date" id="tdate" aria-label="Aller &agrave; un jour" style="flex:1;min-width:0;border:1px solid var(--border2);
  background:var(--surface2);color:var(--text);border-radius:12px;padding:9px 12px;font-size:.88rem;font-family:inherit">
 <button onclick="goDay()" style="border:1px solid var(--border2);background:var(--surface3);color:var(--text2);
  border-radius:12px;padding:9px 14px;font-size:.82rem;font-weight:700;white-space:nowrap">Voir ce jour</button>
</div>
<!-- 2026-10-01 (owner): did the big timeframes agreeing actually pay?
     Recording began today, so this shows a countdown until the sample can
     answer, and the answer the moment it can. -->
<div class="panel" id="tfpay" style="display:none;margin-bottom:12px"></div>
<div class="panel" id="hist">
<div class="row"><span class="skel" style="width:42%">&nbsp;</span>
<span class="skel" style="width:18%">&nbsp;</span></div>
<div class="row"><span class="skel" style="width:36%">&nbsp;</span>
<span class="skel" style="width:22%">&nbsp;</span></div>
<div class="row"><span class="skel" style="width:46%">&nbsp;</span>
<span class="skel" style="width:16%">&nbsp;</span></div></div>

</div>
<div class="tab" id="tab-set">
<!-- 2026-10-01 (owner): accounts really differ now - a 3% per-trade
     ceiling here, none there - and the only way to see which was to read
     owl_packages.json. A member should be able to see their own worst
     case without asking anybody. -->
<div class="sec" id="arules-sec"
 style="margin-top:26px;display:none">Vos r&egrave;gles</div>
<div class="panel" id="arules" style="display:none;padding:4px 14px"></div>
<div class="sec" style="margin-top:26px">Notifications</div>
<div class="panel" style="padding:4px 14px">
 <div class="srow" id="notifbtn" style="display:none">
  <div class="sic"><svg class="ic"><use href="#i-bell"/></svg></div>
  <div style="flex:1"><b id="notif-lbl">Notifications</b>
   <div class="ssub">Gains, orages et soldats sur votre
    t&eacute;l&eacute;phone</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div id="nprefs" style="display:none;padding:2px 0 14px 51px">
  <div style="display:flex;gap:8px">
   <button class="npc" data-l="all" style="flex:1;border:1px solid
    var(--border2);background:var(--surface3);color:var(--text2);border-radius:10px;
    padding:9px;font-size:.82rem;font-weight:700">Tout</button>
   <button class="npc" data-l="important" style="flex:1;border:1px
    solid var(--border);background:transparent;color:var(--muted2);
    border-radius:10px;padding:9px;font-size:.82rem;
    font-weight:700">Important seulement</button>
  </div>
  <button id="quietbtn" style="margin-top:8px;width:100%;display:flex;
   align-items:center;justify-content:space-between;border:1px solid
   var(--border);background:transparent;color:var(--muted2);
   border-radius:10px;padding:9px 12px;font-size:.82rem;font-weight:700">
   <span style="display:inline-flex;align-items:center;gap:6px"><svg
    class="ic ic-s"><use href="#i-moon"/></svg>Silence la nuit
    (22 h &ndash; 7 h)</span><span id="quiet-st">Non</span></button>
  <button id="chimebtn" style="margin-top:8px;width:100%;display:flex;
   align-items:center;justify-content:space-between;border:1px solid
   var(--border);background:transparent;color:var(--muted2);
   border-radius:10px;padding:9px 12px;font-size:.82rem;font-weight:700">
   <span style="display:inline-flex;align-items:center;gap:6px"><svg
    class="ic ic-s"><use href="#i-bolt"/></svg>Son et vibration &agrave; chaque signal</span><span id="chime-st">Non</span></button>
  <div style="margin-top:12px;font-size:.68rem;color:var(--muted);
   text-transform:uppercase;letter-spacing:.08em">Exemple</div>
  <div style="margin-top:6px;display:flex;gap:10px;align-items:flex-start;
   background:var(--surface2);border:1px solid var(--border);
   border-radius:14px;padding:10px 12px"><img src="icon192.png" alt=""
   style="width:28px;height:28px;border-radius:8px;flex:none">
   <div style="min-width:0;flex:1"><div style="font-size:.7rem;
    color:var(--muted);display:flex;justify-content:space-between">
    <span>OwlNest</span><span>maintenant</span></div>
    <b style="font-size:.86rem">Objectif du jour atteint : +$3.20</b>
    <div style="font-size:.78rem;color:var(--muted2)">Le robot a
     termin&eacute; sa journ&eacute;e. &Agrave; demain.</div></div></div>
 </div>
</div>
<div class="sec">Application</div>
<div class="panel" style="padding:4px 14px">
 <div class="srow" onclick="inst()">
  <div class="sic"><svg class="ic"><use href="#i-phone"/></svg></div>
  <div style="flex:1"><b>Installer l&#39;application</b>
   <div class="ssub">Une ic&ocirc;ne sur votre &eacute;cran
    d&#39;accueil</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <!-- 2026-10-03 (owner): Sortir lives here now; it locks the page without leaving it -->
 <div class="srow" onclick="appExit()">
  <div class="sic"><svg class="ic"><use href="#i-lock"/></svg></div>
  <div style="flex:1"><b>Verrouiller l&#39;&eacute;cran</b>
   <div class="ssub">Cache l&#39;application sans quitter le compte</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <!-- 2026-10-03 (owner): the admin's way back from a member's page -->
 <a class="srow" id="admback" href="#" style="display:none;text-decoration:none;color:inherit">
  <div class="sic"><svg class="ic"><use href="#i-users"/></svg></div>
  <div style="flex:1"><b>Revenir &agrave; mon compte</b>
   <div class="ssub" id="admback-s">Vous regardez le compte d&#39;un membre</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </a>
 <!-- 2026-10-03 (owner): the Android app (an APK that wraps this site) -->
 <a class="srow" id="apkrow" href="/owlnest.apk" style="text-decoration:none;color:inherit">
  <div class="sic"><svg class="ic"><use href="#i-download"/></svg></div>
  <div style="flex:1"><b id="apkrow-t">Application Android</b>
   <div class="ssub" id="apkrow-s">T&eacute;l&eacute;charger le fichier APK</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </a>
 <!-- 2026-09-30 (owner): the robot stopped trading the inner
      structure today, but the chart still draws it. Somebody reading the
      chart would reasonably assume the robot acts on it. This switch lets
      the marks be turned off; it is a DISPLAY setting, stored in this
      browser, and changes nothing the robot does. -->
 <div class="srow" id="intmkrow">
  <div class="sic"><svg class="ic"><use href="#i-chart"/></svg></div>
  <div style="flex:1"><b id="intmk-lbl">Petite structure sur le graphique</b>
   <div class="ssub" id="intmk-sub">Le robot ne la trade plus &mdash;
    affichage seulement</div></div>
  <span class="sw" id="intmk-sw" aria-hidden="true"><span class="swk"></span></span>
 </div>
 <div class="srow" id="themerow" style="cursor:default">
  <div class="sic"><svg class="ic"><use href="#i-sun"/></svg></div>
  <div style="flex:1"><b>Apparence</b>
   <div style="display:flex;gap:8px;margin-top:8px">
    <button class="thc" data-t="dark" style="flex:1;border:1px solid var(--border2);
     background:var(--surface3);color:var(--text2);border-radius:10px;
     padding:9px;font-size:.82rem;font-weight:700">Sombre</button>
    <button class="thc" data-t="light" style="flex:1;border:1px solid var(--border);
     background:transparent;color:var(--muted2);border-radius:10px;
     padding:9px;font-size:.82rem;font-weight:700">Clair</button>
   </div></div>
 </div>
 <div class="srow" id="langrow" style="cursor:default">
  <div class="sic"><svg class="ic"><use href="#i-book"/></svg></div>
  <div style="flex:1"><b>Langue</b>
   <div style="display:flex;gap:8px;margin-top:8px">
    <button class="lgc" data-l="fr" onclick="setLang('fr')" style="flex:1;border:1px solid var(--border2);
     background:var(--surface3);color:var(--text2);border-radius:10px;
     padding:9px;font-size:.82rem;font-weight:700">Fran&ccedil;ais</button>
    <button class="lgc" data-l="en" onclick="setLang('en')" style="flex:1;border:1px solid var(--border);
     background:transparent;color:var(--muted2);border-radius:10px;
     padding:9px;font-size:.82rem;font-weight:700">English</button>
   </div></div>
 </div>
 <div class="srow" id="textrow" style="cursor:default">
  <div class="sic"><svg class="ic"><use href="#i-info"/></svg></div>
  <div style="flex:1"><b>Taille du texte</b>
   <div style="display:flex;gap:8px;margin-top:8px">
    <button class="tsc" data-b="0" style="flex:1;border:1px solid var(--border2);
     background:var(--surface3);color:var(--text2);border-radius:10px;
     padding:9px;font-size:.82rem;font-weight:700">Normal</button>
    <button class="tsc" data-b="1" style="flex:1;border:1px solid var(--border);
     background:transparent;color:var(--muted2);border-radius:10px;
     padding:9px;font-size:.82rem;font-weight:700">Plus grand</button>
   </div></div>
 </div>
 <div class="srow" id="pinbtn" onclick="pinSetup()">
  <div class="sic"><svg class="ic"><use href="#i-lock"/></svg></div>
  <div style="flex:1"><b>Code d&#39;acc&egrave;s</b>
   <div class="ssub" id="pin-sub">Prot&eacute;ger cette page avec 4 chiffres</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <a class="srow" href="export.csv" download="owlnest-trades.csv" style="text-decoration:none;color:inherit">
  <div class="sic"><svg class="ic"><use href="#i-download"/></svg></div>
  <div style="flex:1"><b>T&eacute;l&eacute;charger mes trades</b>
   <div class="ssub">Fichier CSV &middot; date, sens, lot, entr&eacute;e, sortie, r&eacute;sultat</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </a>
 <a class="srow" id="contactrow" href="#" target="_blank" rel="noopener" style="display:none;text-decoration:none;color:inherit">
  <div class="sic"><svg class="ic"><use href="#i-users"/></svg></div>
  <div style="flex:1"><b id="contact-lbl">Contacter le Owl</b>
   <div class="ssub">Une question, un souci : un message suffit</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </a>
 <div class="srow" id="inboxbtn" onclick="inboxSheet()">
  <div class="sic"><svg class="ic"><use href="#i-bell"/></svg></div>
  <div style="flex:1"><b>Messages<span class="ibdot" id="inbox-dot" style="display:none"></span></b>
   <div class="ssub" id="inbox-sub">Les derni&egrave;res notifications re&ccedil;ues</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="srow" id="mygoalbtn" onclick="myGoal()">
  <div class="sic"><svg class="ic"><use href="#i-target"/></svg></div>
  <div style="flex:1"><b>Mon objectif</b>
   <div class="ssub" id="mygoal-sub">Choisir un solde &agrave; atteindre</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="srow" id="stepsbtn" onclick="stepsSheet()">
  <div class="sic"><svg class="ic"><use href="#i-check"/></svg></div>
  <div style="flex:1"><b>Mon parcours</b>
   <div class="ssub" id="steps-sub">&Eacute;tapes et moments avec OwlNest</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="srow" id="healthrow" onclick="healthSheet()" style="display:none">
  <div class="sic"><svg class="ic"><use href="#i-activity"/></svg></div>
  <div style="flex:1"><b>Le service</b>
   <div class="ssub" id="health-sub">Flux, robots, notifications</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="srow" id="infobtn">
  <div class="sic"><svg class="ic"><use href="#i-info"/></svg></div>
  <div style="flex:1"><b>Ce qu&#39;il faut savoir</b></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="srow" id="tourbtn">
  <div class="sic"><svg class="ic"><use href="#i-book"/></svg></div>
  <div style="flex:1"><b>Revoir le guide</b></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
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
<div class="sec" id="plan-sec">Abonnement</div>
<div class="panel" id="plan-card" style="padding:14px">
 <div style="display:flex;align-items:center;gap:12px">
  <div class="sic" id="plan-ic" style="color:var(--accent-soft)"><svg class="ic"><use href="#i-key"/></svg></div>
  <div style="flex:1;min-width:0"><b id="plan-t" style="font-size:1rem">Abonnement</b>
   <div id="plan-s" style="font-size:.84rem;color:var(--muted2);line-height:1.45;margin-top:2px"></div></div>
 </div>
 <div id="plan-btns" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px"></div>
 <div id="plan-note" style="font-size:.74rem;color:var(--muted);margin-top:8px;line-height:1.45"></div>
</div>
<div class="srow" id="payrow" onclick="paySheet()" style="display:none;margin-top:10px">
 <div class="sic"><svg class="ic"><use href="#i-ticket"/></svg></div>
 <div style="flex:1"><b>Mes paiements</b>
  <div class="ssub">Vos re&ccedil;us et vos dates de fin</div></div>
 <svg class="ic chv"><use href="#i-chev"/></svg>
</div>
<div class="srow" id="stratrow" onclick="stratSheet()" style="display:none;margin-top:10px">
 <div class="sic" style="color:var(--warn)"><svg class="ic"><use href="#i-eye"/></svg></div>
 <div style="flex:1"><b>La strat&eacute;gie</b>
  <div class="ssub">La m&eacute;thode en mots simples &middot; le graphique complet</div></div>
 <svg class="ic chv"><use href="#i-chev"/></svg>
</div>
<div class="sec" id="rob-sec" style="display:none">Le robot</div>
<div class="panel" id="rob-card" style="display:none;padding:4px 14px">
 <div class="srow" id="pausebtn">
  <div class="sic" id="pause-ic">&#9208;&#65039;</div>
  <div style="flex:1"><b id="pause-lbl">Mode manuel</b>
   <div class="ssub" id="pause-sub"></div></div>
  <span class="sw" id="pause-sw" aria-hidden="true"><span class="swk"></span></span>
 </div>
 <div class="srow" id="scalebtn" style="display:none">
  <div class="sic" id="scale-ic"><svg class="ic"><use href="#i-chart"/></svg></div>
  <div style="flex:1"><b id="scale-lbl">Mise &agrave; l&#39;&eacute;chelle
   du solde</b>
   <div class="ssub" id="scale-sub"></div></div>
  <span class="sw" id="scale-sw" aria-hidden="true"><span class="swk"></span></span>
 </div>
</div>
<!-- Owner 2026-09-23: "the nid menu must not exist for all but me" - this
     is how the owner unlocks it from whichever account's page is open,
     without going back to the Owl. Password-verified server-side
     (admin_unlock), never a client-side flag; hidden the moment this
     browser is already recognised as admin. -->
<div class="sec" id="adminlock-sec">Acc&egrave;s</div>
<div class="panel" id="adminlock-card" style="padding:4px 14px">
 <div class="srow" id="adminlockbtn">
  <div class="sic"><svg class="ic"><use href="#i-lock"/></svg></div>
  <div style="flex:1"><b>D&eacute;verrouiller Le Nid</b>
   <div class="ssub">R&eacute;serv&eacute; &agrave;
    l&#39;administrateur</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
</div>
<div class="sec" id="adm-sec" style="display:none">Administration</div>
<div class="panel" id="adm-card" style="display:none;padding:4px 14px">
 <div class="srow" id="goalbtn">
  <div class="sic"><svg class="ic"><use href="#i-target"/></svg></div>
  <div style="flex:1"><b>D&eacute;finir l&#39;objectif</b></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="srow" id="paycfg" onclick="payCfg()">
  <div class="sic"><svg class="ic"><use href="#i-key"/></svg></div>
  <div style="flex:1"><b>Paiements</b>
   <div class="ssub" id="paycfg-sub">Cl&eacute; NOWPayments, secret IPN, prix Automatique</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="srow" id="contactcfg" onclick="contactCfg()">
  <div class="sic"><svg class="ic"><use href="#i-users"/></svg></div>
  <div style="flex:1"><b>Lien de contact</b>
   <div class="ssub" id="contactcfg-sub">WhatsApp, Telegram ou e-mail, montr&eacute; &agrave; chaque membre</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="srow" id="codebtn">
  <div class="sic"><svg class="ic"><use href="#i-key"/></svg></div>
  <div style="flex:1"><b>Code d&#39;activation</b>
   <div class="ssub">Pour activer le robot d&#39;un membre</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>

 <a class="srow" id="chartbtn" href="#"
  style="display:none;text-decoration:none;color:inherit">
  <div class="sic"><svg class="ic"><use href="#i-chart"/></svg></div>
  <div style="flex:1"><b>Graphique custom (BTC)</b>
   <div class="ssub">M1 filtr&eacute; &mdash; labo du
    ma&icirc;tre</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </a>
</div>
<div class="sec">Compte</div>
<div class="panel" style="padding:4px 14px">
 <div class="srow" id="tgrow" onclick="tgLink()">
  <div class="sic"><svg class="ic"><use href="#i-bell"/></svg></div>
  <div style="flex:1"><b id="tgrow-t">Relier Telegram</b>
   <div class="ssub" id="tgrow-s">Pour retrouver votre acc&egrave;s un jour, sans e-mail</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="srow" id="pwdrow" onclick="pwdChange()" style="display:none">
  <div class="sic"><svg class="ic"><use href="#i-key"/></svg></div>
  <div style="flex:1"><b>Changer mon mot de passe</b>
   <div class="ssub">Celui de l&#39;app, pour vous connecter</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="srow" onclick="appLogout()">
  <div class="sic"><svg class="ic"><use href="#i-exit"/></svg></div>
  <div style="flex:1"><b>Se d&eacute;connecter</b>
   <div class="ssub">Ce t&eacute;l&eacute;phone oublie ce compte ; vous pourrez en ouvrir un autre</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
 <div class="srow" id="delbtn">
  <div class="sic" style="background:rgba(255,92,92,.14);color:var(--down-soft)"><svg class="ic"><use href="#i-trash"/></svg></div>
  <div style="flex:1"><b style="color:var(--down-soft)">Retirer mon compte
   du robot</b></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </div>
</div>
<div class="foot" id="upd">chargement...</div>
</div>
<div class="tab" id="tab-nid">
<div class="sec" style="margin-top:26px">Le Nid &middot; tous les
 comptes</div>
<div id="acctsw" style="display:none;margin-bottom:12px;
 background:var(--surface2);border:1px solid var(--border);border-radius:14px;
 padding:12px">
 <div style="font-size:.78rem;color:var(--muted2);margin-bottom:8px">
  Changer de vue (admin)</div>
 <div id="acctsw-b" style="display:flex;gap:8px;flex-wrap:wrap"></div>
</div>
<div class="panel" id="revcard" style="display:none;margin-bottom:12px">
 <div class="lbl">Revenus</div>
 <div id="rev-g" style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px"></div>
 <div id="rev-due" style="font-size:.82rem;color:var(--muted2);line-height:1.5;margin-top:10px"></div>
 <div id="rev-pay" style="margin-top:8px"></div>
</div>
<div class="panel" id="nest">...</div>
<button id="invbtn" style="width:100%;margin-top:14px;
 background:var(--surface3);color:var(--text2);border:1px solid var(--border2);
 border-radius:14px;padding:15px;font-size:1rem;font-weight:700">
 <svg class="ic"><use href="#i-key"/></svg> G&eacute;n&eacute;rer un code</button>
</div>
</div>
<div class="tabbar">
<button class="tb on" onclick="tab('home',this)"><svg class="ic"><use href="#i-home"/></svg>Accueil</button>
<button class="tb" id="tb-marche" onclick="tab('marche',this)"><svg class="ic"><use href="#i-activity"/></svg>March&eacute;</button>
<button class="tb" onclick="tab('hist',this)"><svg class="ic"><use href="#i-calendar"/></svg>Historique</button>
<button class="tb" id="tb-nid" style="display:none"
 onclick="tab('nid',this)"><svg class="ic"><use href="#i-users"/></svg>Le Nid</button>
<button class="tb" onclick="tab('set',this)"><svg class="ic"><use href="#i-settings"/></svg>R&eacute;glages</button>
</div>
<div id="lock" aria-label="Code d&#39;acc&egrave;s">
 <img src="icon192.png" alt="" style="width:56px;height:56px;border-radius:16px">
 <div style="font-weight:700;font-size:1.05rem;margin-top:14px">Code d&#39;acc&egrave;s</div>
 <div id="lock-dots" style="display:flex;gap:12px;margin:16px 0 22px"></div>
 <div class="kp" id="lock-kp"></div>
 <button id="lock-back" class="shbtn shmain" style="display:none;width:auto;margin-top:18px;padding:11px 26px" onclick="appBack()">Revenir</button>
 <a id="lock-forgot" href="../" style="margin-top:22px;color:var(--muted);font-size:.85rem;text-decoration:none">Code oubli&eacute; ? Changer de compte</a>
</div>
<div id="offline" role="status"><svg class="ic ic-s"><use href="#i-cloud"/></svg><span id="offline-t">Connexion perdue</span></div>
<div id="toast" role="status" aria-live="polite"></div>
<div id="sheetbg"></div>
<div id="sheet"><div class="grab"></div><div id="sheet-c"></div></div>
<div id="tourbg"></div>
<div id="tourbx"><p id="tourtxt"></p>
 <div style="display:flex;justify-content:space-between;
  align-items:center;margin-top:14px">
  <a href="#" id="tourskip" style="color:var(--muted);font-size:.85rem;
   text-decoration:none">Passer</a>
  <span id="tourdots"></span>
  <button id="tournext" class="shbtn shmain" style="width:auto;
   margin:0;padding:10px 22px">Suivant</button>
 </div>
</div>
<script>
const B=location.pathname.endsWith('/')?location.pathname:location.pathname+'/';
const APP_BUILD='%%BUILD%%';
function sgn(v){return v>0?'pos':(v<0?'neg':'neu')}
function SVGI(n){return '<svg class="ic"><use href="#'+n+'"/></svg>'}
function arw(v){return v>0?'&#9650; ':(v<0?'&#9660; ':'')}
async function sha(t){const b=new TextEncoder().encode(t);
 const h=await crypto.subtle.digest('SHA-256',b);
 return [...new Uint8Array(h)].map(x=>x.toString(16).padStart(2,'0')).join('');}
function pinKey(){return 'owlPin:'+location.pathname;}
// 2026-10-03 (owner): "Sortir" never leaves the page - the trip to the
// landing page showed the address in the browser bar for a moment. With
// a code set it locks; without one it shows the same screen with a
// "Revenir" button. Nothing is loaded, so nothing can flash.
function appExit(){const en=LANG()==='en';let pin=null;try{pin=localStorage.getItem(pinKey());}catch(e){}
 const t=document.querySelector('#lock > div[style*="font-weight:700"]');
 const kp=document.getElementById('lock-kp'),dots=document.getElementById('lock-dots'),back=document.getElementById('lock-back'),fg=document.getElementById('lock-forgot');
 if(pin){if(t)t.textContent=en?'Access code':'Code d\u2019acc\u00e8s';if(kp)kp.style.display='';if(dots)dots.style.display='flex';if(back)back.style.display='none';if(fg)fg.style.display='';}
 else{if(t)t.textContent=en?'See you soon':'\u00c0 bient\u00f4t';if(kp)kp.style.display='none';if(dots)dots.style.display='none';if(back){back.style.display='inline-flex';back.textContent=en?'Come back':'Revenir';}if(fg)fg.style.display='none';}
 window._shDone&&window._shDone(1);window.scrollTo(0,0);
 document.documentElement.classList.add('locked');}
// 2026-10-04 (owner): a real logout - this phone forgets the account
// (remembered link, admin memory if it is this account, the app session)
// and goes back to the landing, where another account can log in
async function appLogout(){const en=LANG()==='en';
 const ok=await sheet('<h3>'+(en?'Log out?':'Se d\u00e9connecter ?')+'</h3><p style="color:var(--text2)">'+(en?'This phone forgets this account. To come back you will need your identifiant and password (or your personal link).':'Ce t\u00e9l\u00e9phone oublie ce compte. Pour revenir il faudra votre identifiant et votre mot de passe (ou votre lien personnel).')+'</p>'+
  '<button class="shbtn shmain" onclick="_shDone(1)">'+(en?'Log out':'Se d\u00e9connecter')+'</button><button class="shbtn shghost" onclick="_shDone(null)">'+(en?'Cancel':'Annuler')+'</button>');
 if(!ok)return;
 try{localStorage.removeItem('owlLink');sessionStorage.removeItem('owlTwa');if(localStorage.getItem('owl_adm')===B)localStorage.removeItem('owl_adm');}catch(e){}
 location.replace('/');}
function appBack(){document.documentElement.classList.remove('locked');
 const kp=document.getElementById('lock-kp'),dots=document.getElementById('lock-dots'),back=document.getElementById('lock-back'),fg=document.getElementById('lock-forgot');
 if(kp)kp.style.display='';if(dots)dots.style.display='flex';if(back)back.style.display='none';if(fg)fg.style.display='';}
// 2026-10-03 (owner): the home shows ONE card at a time, in order of
// importance: notifications, last night, the Android app, what's new.
// Each card keeps its own logic (it sets display:block when it has
// something to say, none when dismissed); this only decides which of the
// willing cards is the one on screen. The next appears when one goes.
const HOME_Q=['expcard','nudge','recap','apkcard','newscard'];
function homeCards(){let shown=false;
 HOME_Q.forEach(id=>{const el=document.getElementById(id);if(!el)return;
  const wants=el.style.display==='block';
  if(wants&&!shown){el.classList.remove('hq');shown=true;}
  else el.classList.toggle('hq',wants);});}
setInterval(homeCards,600);
function pinInit(){
 const kp=document.getElementById('lock-kp'),dots=document.getElementById('lock-dots');
 if(!kp||kp.children.length)return;
 let buf='';
 const paint=()=>{dots.innerHTML=[0,1,2,3].map(i=>'<span class="ld'+(i<buf.length?' on':'')+'"></span>').join('');};
 paint();
 [1,2,3,4,5,6,7,8,9,'',0,'\u232b'].forEach(k=>{const b=document.createElement('button');
  b.textContent=k;if(k==='')b.style.visibility='hidden';
  b.onclick=async()=>{if(k==='\u232b'){buf=buf.slice(0,-1);paint();return;}
   if(buf.length>=4)return;buf+=k;paint();
   if(buf.length===4){const ok=(await sha(buf))===localStorage.getItem(pinKey());
    if(ok){document.documentElement.classList.remove('locked');buf='';paint();
     try{navigator.vibrate&&navigator.vibrate(10)}catch(e){}}
    else{const L=document.getElementById('lock');L.classList.add('shake');
     setTimeout(()=>L.classList.remove('shake'),450);buf='';paint();
     try{navigator.vibrate&&navigator.vibrate([40,30,40])}catch(e){}}}};
  kp.appendChild(b);});
}
async function pinSetup(){
 const has=!!localStorage.getItem(pinKey());
 const v=await sheet('<h3>Code d&#39;acc&egrave;s</h3>'+
  '<p>'+(has?'Un code prot&egrave;ge d&eacute;j&agrave; cette page. Entrez un nouveau code &agrave; 4 chiffres, ou retirez-le.'
   :'4 chiffres demand&eacute;s &agrave; chaque ouverture de l&#39;application, sur ce t&eacute;l&eacute;phone seulement.')+'</p>'+
  '<input id="shpw" type="password" inputmode="numeric" maxlength="4" pattern="[0-9]*" placeholder="4 chiffres" '+
  'style="text-align:center;letter-spacing:.4em;font-size:1.3rem">'+
  '<button class="shbtn shmain" onclick="_shDone(document.getElementById(\\'shpw\\').value)">Enregistrer</button>'+
  (has?'<button class="shbtn shdanger" onclick="_shDone(\\'__off__\\')">Retirer le code</button>':'')+
  '<button class="shbtn shghost" onclick="_shDone(null)">Annuler</button>');
 if(v==null)return;
 if(v==='__off__'){try{localStorage.removeItem(pinKey())}catch(e){}
  toast('<div class="evi" style="color:var(--muted2)"><svg class="ic ic-s"><use href="#i-lock"/></svg></div><div style="flex:1">Code d\u2019acc\u00e8s retir\u00e9.</div>');pinRow();return;}
 if(!/^\d{4}$/.test(v)){await info('<h3>4 chiffres, s&#39;il vous pla&icirc;t.</h3>');return;}
 try{localStorage.setItem(pinKey(),await sha(v))}catch(e){}
 toast('<div class="evi" style="color:var(--up)"><svg class="ic ic-s"><use href="#i-lock"/></svg></div><div style="flex:1">Code d\u2019acc\u00e8s enregistr\u00e9.</div>');
 pinRow();
}
function pinRow(){const e=document.getElementById('pin-sub');if(e)e.textContent=
 localStorage.getItem(pinKey())?'Activ\u00e9 \u2014 demand\u00e9 \u00e0 l\u2019ouverture':'Prot\u00e9ger cette page avec 4 chiffres';}
function appRefresh(){
 let done=false;const go=()=>{if(done)return;done=true;location.reload();};
 const c=navigator.serviceWorker&&navigator.serviceWorker.controller;
 if(!c){go();return;}
 navigator.serviceWorker.addEventListener('message',ev=>{if(ev.data&&ev.data.type==='refreshed')go();});
 c.postMessage({type:'refresh',url:location.href.split('#')[0]});
 setTimeout(go,4000);
}
function toast(html,ms){const t=document.getElementById('toast');if(!t)return;
 t.innerHTML=html;t.classList.add('on');clearTimeout(window._toastT);
 window._toastT=setTimeout(()=>t.classList.remove('on'),ms||4500);}
function setTheme(t,save){const L=(t==='light');
 document.documentElement.dataset.theme=L?'light':'';
 if(save){try{localStorage.setItem('owlTheme',L?'light':'dark')}catch(e){}}
 document.querySelectorAll('.thc').forEach(b=>{const on=b.dataset.t===(L?'light':'dark');
  b.style.background=on?'var(--surface3)':'transparent';
  b.style.borderColor=on?'var(--border2)':'var(--border)';
  b.style.color=on?'var(--text2)':'var(--muted2)';});}
window.addEventListener('load',()=>{let t='dark';
 try{t=localStorage.getItem('owlTheme')||'dark'}catch(e){}
 setTheme(t,false);pinRow();
 document.querySelectorAll('.thc').forEach(b=>b.onclick=()=>setTheme(b.dataset.t,true));
 const _big=(()=>{try{return localStorage.getItem('owlBig')==='1'}catch(e){return false}})();
 const _tsp=on=>{document.documentElement.style.fontSize=on?'112.5%':'';
  document.querySelectorAll('.tsc').forEach(b=>{const a=(b.dataset.b==='1')===on;
   b.style.background=a?'var(--surface3)':'transparent';b.style.borderColor=a?'var(--border2)':'var(--border)';
   b.style.color=a?'var(--text2)':'var(--muted2)';});};
 _tsp(_big);document.querySelectorAll('.tsc').forEach(b=>b.onclick=()=>{const on=b.dataset.b==='1';
  try{localStorage.setItem('owlBig',on?'1':'0')}catch(e){}_tsp(on);});
 loadDay();setInterval(loadDay,60000);
 try{const _h=(location.hash||'').slice(1);
  if(_h==='marche'||_h==='robot'||_h==='hist'||_h==='set'||_h==='resume'){
   const _hh=(_h==='robot')?'marche':_h;
   const _b=[...document.querySelectorAll('.tb')].find(x=>(x.getAttribute('onclick')||'').indexOf("'"+_hh+"'")>=0);
   if(_b)tab(_hh,_b);
   if(_h==='robot')setTimeout(()=>mxView('robot',true),50);if(_h==='marche')setTimeout(()=>mxView('market',true),50);
   if(_h==='resume')setTimeout(resumeShare,2500);
   if(_h==='hist')setTimeout(()=>{const w=document.getElementById('weekcard');if(w&&w.style.display!=='none'){
    w.classList.add('hl');w.scrollIntoView({block:'start',behavior:'smooth'});setTimeout(()=>w.classList.remove('hl'),3200);}},900);}}catch(e){}
 pinInit();
 // a11y: clickable rows behave like buttons for keyboards/screen readers
 document.querySelectorAll('.srow').forEach(el=>{if(el.tagName==='A'||el.id==='themerow')return;
  if(!el.getAttribute('onclick')&&!el.id)return;
  el.setAttribute('role','button');el.tabIndex=0;
  el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();el.click();}});});
});
const ORB=(()=>{const o=(n,c)=>'<svg class="ic" style="width:26px;height:26px;color:'+c+'"><use href="#'+n+'"/></svg>';
 return {'mx-sun':o('i-sun','#e8c55a'),'mx-fish':o('i-wave','var(--up-soft)'),
  'mx-sleep':o('i-moon','#9fb0d0'),'mx-storm':o('i-bolt','var(--down-soft)'),
  'mx-cloud':o('i-cloud','#ffd27a')};})();
(function(){
 const m=document.createElement('link');m.rel='manifest';
 m.href=B+'manifest.json';document.head.appendChild(m);
 const i=document.createElement('link');i.rel='icon';
 i.href=B+'icon192.png';document.head.appendChild(i);
 const a=document.createElement('link');a.rel='apple-touch-icon';
 a.href=B+'icon192.png';document.head.appendChild(a);
})();
let lastOk=0;
let isPaused=false,pauseLocked=false;
function setH(el,h){if(el._h!==h){el._h=h;el.innerHTML=h;}}
// 2026-09-27 (owner): two voices. AUTO = the robot is in charge and says
// what it does / will do. MANUAL = the app is a signal service: it says what
// the signal is and leaves the decision to the member. Every sentence that
// names an actor goes through MAN().
function MAN(){return !!(window._d&&window._d.trading_paused);}
// 2026-09-27: every sentence that carries a voice lives HERE, once per voice.
// T(key) picks the current voice; a missing manual key falls back to auto.
// This is also the i18n seam: a language is one more table.
const VOICE={
 auto:{
  wx:{ready:['✅','Feu vert','#8df0bb','Les conditions sont réunies. Le robot entrera dès que le signal se confirme.'],
      flip:['⚖️','Ça peut tourner','#e8c55a','Le sens change peut-être. Le robot attend la confirmation avant d’agir.'],
      forming:['⏳','Ça se prépare','#8fa1b3','Trop tôt. Le robot laisse le marché se dessiner.'],
      none:['💤','Rien à faire','#6f8299','Le marché est calme. Le robot attend une occasion.'],
      brisk:['🍃','Marché soutenu','#e8c55a','Les bougies sont un peu plus grandes que d’habitude. Le robot laisse passer celui-là.'],
      nervous:['🌀','Marché rapide','#ff9678','Les mouvements sont beaucoup plus grands que d’habitude. Le robot préfère s’écarter.'],
      nogate:['⚡','Aucun frein','#b98cff','Ce compte prend tous les signaux, marché calme ou rapide.']},
  mx_hint:'&middot; ce que le robot voit',
  jcard:'Le robot en ce moment',jsteps:['Observe','Occasion','Trade','Bilan'],
  j_open:'Un trade est en cours{pl}. Le robot le surveille jusqu\u2019au bout.',
  j_won:'Dernier trade termin\u00e9 : <b class="pos">gagn\u00e9 +${p}</b>. Le robot repart en observation.',
  j_lost:'Dernier trade termin\u00e9 : <b class="neg">perdu ${p}</b>. \u00c7a arrive \u2014 le robot repart en observation.',
  j_forming:'Quelque chose se dessine sur le march\u00e9. Le robot attend une confirmation avant d\u2019agir.',
  j_flip:'Le march\u00e9 h\u00e9site sur sa direction. Le robot attend que ce soit clair.',
  j_ready:'Les conditions sont r\u00e9unies. Le robot entrera d\u00e8s que le signal se confirme.',
  j_storm:'Le march\u00e9 est tr\u00e8s agit\u00e9. Le robot reste \u00e0 l\u2019abri et attend que \u00e7a se calme.',
  j_nervous:'Le march\u00e9 bouge beaucoup. Le robot pr\u00e9f\u00e8re attendre.',
  j_none:'Le march\u00e9 est calme. Le robot observe et attend une occasion.',
  j_debt:' Apr\u00e8s une perte, il est un peu plus prudent.',
  day_lbl:'La journ\u00e9e du robot',
  day_empty:'Depuis ce matin, le robot surveille le march\u00e9 et n\u2019a rien trouv\u00e9 \u00e0 faire. C\u2019est normal : il n\u2019agit que quand tout est r\u00e9uni.',
  day_ign:['occasion laiss\u00e9e passer','occasions laiss\u00e9es passer'],
  day_cont:' Le robot continue de surveiller.',
  who:'Le robot a ',won_v:'a gagn\u00e9',lost_v:'a perdu',lost_tail:' \u2014 il continue.',
  ev_meteo:'Le march\u00e9 bougeait trop. Le robot a pr\u00e9f\u00e9r\u00e9 laisser passer.',
  ev_eye:'Le robot a vu une occasion, mais tout n\u2019\u00e9tait pas r\u00e9uni. Il a attendu.',
  wk_up:'Le robot avance.',wk_debt:'Le robot se rattrape.',wk_down:'Semaine difficile ; le robot continue.',
  mo_n:', le robot a pris <b>',mo_up:'Le robot avance.',mo_debt:'Le robot est en train de se rattraper \u2014 il avance prudemment.',mo_down:'Un mois difficile ; le robot continue.',
  since:'Avec le robot depuis le <b>',
  toast_lost:' \u2014 \u00e7a arrive, il continue.',toast_debt_done:'le robot repasse en mode normal.',
  st_manual:'<b>Mode manuel</b> &mdash; vous d&eacute;cidez',st_killed:'Robot arr\u00eat\u00e9 \u2014 limite de s\u00e9curit\u00e9 atteinte',
  cmp_pick:'Jour choisi : {d} \u2014 appuyez longuement sur un autre jour pour comparer.',cmp_title:'Deux jours c\u00f4te \u00e0 c\u00f4te',cmp_best:'meilleur',cmp_worst:'pire',cmp_even:'Les deux jours se valent.',cmp_better:'{a} a fait mieux, de {x}.',
  mvm_lbl:'Ce mois vs le mois dernier',mvm_same:'\u00e0 la m\u00eame date',mvm_better:'Mieux que le mois dernier \u00e0 la m\u00eame date.',mvm_worse:'Un peu en dessous du mois dernier \u00e0 la m\u00eame date.',mvm_even:'Au m\u00eame niveau que le mois dernier.',mvm_none:'Pas encore de mois pr\u00e9c\u00e9dent \u00e0 comparer.',
  dayx_empty:'Ce jour-l\u00e0, le robot a surveill\u00e9 le march\u00e9 sans trader.',dayx_who:'Le robot a ',
  ts_who:'Le robot a ',ts_buy:'achet\u00e9',ts_sell:'vendu',ts_on:' le ',ts_at:' \u00e0 ',ts_in:', dans un march\u00e9 ',ts_in2:'',ts_risk:' Il a risqu\u00e9 au plus <b>$',
  ts_dur:' Le trade a dur\u00e9 ',ts_end:' et s\u2019est termin\u00e9 par ',ts_gain:'un <b class="pos">gain de ',ts_gain_tail:'</b>. Bien jou\u00e9.',ts_loss:'une <b class="neg">perte de $',ts_loss_tail:'</b>. \u00c7a arrive',
  ts_kept:' et gard\u00e9 le trade ',ts_ended:', termin\u00e9 par ',
  day_since:'Depuis ce matin : ',day_of:' (dont ',day_won:' gagn\u00e9',day_1won:' (gagn\u00e9)',day_1lost:' (perdu)',day_and:' et ',day_total:' Total du jour : '},
 manual:{
  wx:{ready:['✅','Feu vert','#8df0bb','Les conditions sont réunies : le prochain signal est jouable. À vous de décider.'],
      flip:['⚖️','Ça peut tourner','#e8c55a','Le sens change peut-être. Attendez la confirmation avant d’entrer.'],
      forming:['⏳','Ça se prépare','#8fa1b3','Trop tôt pour entrer. Laissez le marché se dessiner.'],
      none:['💤','Pas de signal','#6f8299','Le marché est calme. Mieux vaut attendre le prochain signal.'],
      brisk:['🍃','Marché soutenu','#e8c55a','Les bougies sont un peu plus grandes que d’habitude. Signal à prendre avec prudence.'],
      nervous:['🌀','Marché rapide','#ff9678','Les mouvements sont beaucoup plus grands que d’habitude. Mieux vaut s’écarter.'],
      nogate:['⚡','Aucun frein','#b98cff','Tous les signaux sont affichés, marché calme ou rapide.']},
  mx_hint:'&middot; ce que le signal dit',
  jcard:'Le signal en ce moment',jsteps:['Veille','Signal','Trade','Bilan'],
  j_open:'Votre trade est en cours{pl}. G\u00e9rez-le depuis le graphique.',
  j_won:'Dernier trade termin\u00e9 : <b class="pos">gagn\u00e9 +${p}</b>. Bien jou\u00e9 \u2014 l\u2019app veille pour le prochain signal.',
  j_lost:'Dernier trade termin\u00e9 : <b class="neg">perdu ${p}</b>. \u00c7a arrive \u2014 l\u2019app veille pour le prochain signal.',
  j_forming:'Un signal se pr\u00e9pare. Trop t\u00f4t pour entrer \u2014 l\u2019app vous pr\u00e9vient.',
  j_flip:'Le march\u00e9 h\u00e9site sur sa direction. Attendez la confirmation avant d\u2019entrer.',
  j_ready:'<b>Signal jouable</b> : les conditions sont r\u00e9unies. Ouvrez le graphique pour d\u00e9cider.',
  j_storm:'March\u00e9 tr\u00e8s agit\u00e9 : pas de signal fiable. Mieux vaut s\u2019\u00e9carter.',
  j_nervous:'Le march\u00e9 bouge beaucoup. Un signal ici serait \u00e0 prendre avec prudence.',
  j_none:'Aucun signal pour l\u2019instant. L\u2019app veille et vous pr\u00e9vient.',
  j_debt:' Apr\u00e8s une perte, la r\u00e9serve conseille un lot plus petit.',
  day_lbl:'Votre journ\u00e9e',
  day_empty:'Depuis ce matin, aucun signal confirm\u00e9. L\u2019app veille et vous pr\u00e9vient d\u00e8s qu\u2019il y en a un.',
  day_ign:['signal \u00e9cart\u00e9','signaux \u00e9cart\u00e9s'],
  day_cont:' L\u2019app continue de veiller.',
  who:'Vous avez ',won_v:'gagn\u00e9',lost_v:'perdu',lost_tail:'.',
  ev_meteo:'Le march\u00e9 bougeait trop. Signal \u00e9cart\u00e9.',
  ev_eye:'Un signal est apparu, mais tout n\u2019\u00e9tait pas r\u00e9uni. \u00c9cart\u00e9.',
  wk_up:'Le compte avance.',wk_debt:'Vous vous rattrapez \u2014 restez prudent.',wk_down:'Semaine difficile ; on continue.',
  mo_n:', vous avez pris <b>',mo_up:'Le compte avance.',mo_debt:'Vous \u00eates en train de vous rattraper \u2014 restez prudent.',mo_down:'Un mois difficile ; on continue.',
  since:'Avec OwlNest depuis le <b>',
  toast_lost:' \u2014 \u00e7a arrive.',toast_debt_done:'lot normal \u00e0 nouveau.',
  st_manual:'<b>Mode manuel</b> &mdash; vous d&eacute;cidez',
  dayx_empty:'Ce jour-l\u00e0, aucun trade.',dayx_who:'Vous avez ',ts_who:'Vous avez ',ts_risk:' Risque maximum : <b>$'}};
// 2026-09-27: English - the same keys, the same two voices.
const VOICE_EN={
 auto:{
  wx:{ready:['✅','Green light','#8df0bb','Conditions are met. The robot will enter as soon as the signal confirms.'],
      flip:['⚖️','It may turn','#e8c55a','The direction may be changing. The robot waits for confirmation before acting.'],
      forming:['⏳','Setting up','#8fa1b3','Too early. The robot lets the market take shape.'],
      none:['💤','Nothing to do','#6f8299','The market is calm. The robot waits for an opportunity.'],
      brisk:['🍃','Lively market','#e8c55a','Candles are a bit larger than usual. The robot lets this one go.'],
      nervous:['🌀','Fast market','#ff9678','Moves are much larger than usual. The robot prefers to step aside.'],
      nogate:['⚡','No brakes','#b98cff','This account takes every signal, calm or fast market.']},
  mx_hint:'&middot; what the robot sees',
  jcard:'The robot right now',jsteps:['Watching','Opportunity','Trade','Review'],
  j_open:'A trade is running{pl}. The robot watches it to the end.',
  j_won:'Last trade closed: <b class="pos">won +${p}</b>. The robot is back to watching.',
  j_lost:'Last trade closed: <b class="neg">lost ${p}</b>. It happens \u2014 the robot is back to watching.',
  j_forming:'Something is taking shape. The robot waits for confirmation before acting.',
  j_flip:'The market is hesitating on its direction. The robot waits until it is clear.',
  j_ready:'Conditions are met. The robot will enter as soon as the signal confirms.',
  j_storm:'The market is very agitated. The robot stays sheltered until it calms down.',
  j_nervous:'The market is moving a lot. The robot prefers to wait.',
  j_none:'The market is calm. The robot watches and waits for an opportunity.',
  j_debt:' After a loss, it is a little more careful.',
  day_lbl:'The robot\u2019s day',
  day_empty:'Since this morning the robot has watched the market and found nothing to do. That is normal: it only acts when everything lines up.',
  day_ign:['opportunity let go','opportunities let go'],
  day_cont:' The robot keeps watching.',
  who:'The robot ',won_v:'won',lost_v:'lost',lost_tail:' \u2014 it carries on.',
  ev_meteo:'The market was moving too much. The robot preferred to let it go.',
  ev_eye:'The robot saw an opportunity, but not everything lined up. It waited.',
  wk_up:'The robot is moving forward.',wk_debt:'The robot is catching up.',wk_down:'A hard week; the robot carries on.',
  mo_n:', the robot took <b>',mo_up:'The robot is moving forward.',mo_debt:'The robot is catching up \u2014 carefully.',mo_down:'A hard month; the robot carries on.',
  since:'With the robot since <b>',
  toast_lost:' \u2014 it happens, it carries on.',toast_debt_done:'the robot is back to normal mode.',
  st_manual:'<b>Manual mode</b> &mdash; you decide',st_killed:'Robot stopped \u2014 safety limit reached',
  cmp_pick:'Day picked: {d} \u2014 long-press another day to compare.',cmp_title:'Two days side by side',cmp_best:'best',cmp_worst:'worst',cmp_even:'The two days are level.',cmp_better:'{a} did better, by {x}.',
  mvm_lbl:'This month vs last month',mvm_same:'same date',mvm_better:'Better than last month at the same date.',mvm_worse:'A little below last month at the same date.',mvm_even:'Level with last month.',mvm_none:'No previous month to compare yet.',
  dayx_empty:'That day, the robot watched the market without trading.',dayx_who:'The robot ',
  ts_who:'The robot ',ts_buy:'bought',ts_sell:'sold',ts_on:' on ',ts_at:' at ',ts_in:', in a ',ts_in2:' market',ts_risk:' It risked at most <b>$',
  ts_dur:' The trade lasted ',ts_end:' and ended with ',ts_gain:'a <b class="pos">gain of ',ts_gain_tail:'</b>. Well played.',ts_loss:'a <b class="neg">loss of $',ts_loss_tail:'</b>. It happens',
  ts_kept:' and kept the trade ',ts_ended:', ended with ',
  day_since:'Since this morning: ',day_of:' (',day_won:' won',day_1won:' (won)',day_1lost:' (lost)',day_and:' and ',day_total:' Total for the day: '},
 manual:{
  wx:{ready:['✅','Green light','#8df0bb','Conditions are met: the next signal is playable. Your call.'],
      flip:['⚖️','It may turn','#e8c55a','The direction may be changing. Wait for confirmation before entering.'],
      forming:['⏳','Setting up','#8fa1b3','Too early to enter. Let the market take shape.'],
      none:['💤','No signal','#6f8299','The market is calm. Better to wait for the next signal.'],
      brisk:['🍃','Lively market','#e8c55a','Candles are a bit larger than usual. Take any signal with care.'],
      nervous:['🌀','Fast market','#ff9678','Moves are much larger than usual. Better to step aside.'],
      nogate:['⚡','No brakes','#b98cff','Every signal is shown, calm or fast market.']},
  mx_hint:'&middot; what the signal says',
  jcard:'The signal right now',jsteps:['Watch','Signal','Trade','Review'],
  j_open:'Your trade is running{pl}. Manage it from the chart.',
  j_won:'Last trade closed: <b class="pos">won +${p}</b>. Well played \u2014 the app watches for the next signal.',
  j_lost:'Last trade closed: <b class="neg">lost ${p}</b>. It happens \u2014 the app watches for the next signal.',
  j_forming:'A signal is setting up. Too early to enter \u2014 the app will tell you.',
  j_flip:'The market is hesitating on its direction. Wait for confirmation before entering.',
  j_ready:'<b>Playable signal</b>: conditions are met. Open the chart to decide.',
  j_storm:'Very agitated market: no reliable signal. Better to step aside.',
  j_nervous:'The market is moving a lot. A signal here would need care.',
  j_none:'No signal for now. The app watches and will tell you.',
  j_debt:' After a loss, the reserve suggests a smaller lot.',
  day_lbl:'Your day',
  day_empty:'No confirmed signal since this morning. The app watches and will tell you as soon as there is one.',
  day_ign:['signal set aside','signals set aside'],
  day_cont:' The app keeps watching.',
  who:'You ',won_v:'won',lost_v:'lost',lost_tail:'.',
  ev_meteo:'The market was moving too much. Signal set aside.',
  ev_eye:'A signal appeared, but not everything lined up. Set aside.',
  wk_up:'The account is moving forward.',wk_debt:'You are catching up \u2014 stay careful.',wk_down:'A hard week; we carry on.',
  mo_n:', you took <b>',mo_up:'The account is moving forward.',mo_debt:'You are catching up \u2014 stay careful.',mo_down:'A hard month; we carry on.',
  since:'With OwlNest since <b>',
  toast_lost:' \u2014 it happens.',toast_debt_done:'normal lot again.',
  st_manual:'<b>Manual mode</b> &mdash; you decide',
  dayx_empty:'That day, no trade.',dayx_who:'You ',ts_who:'You ',ts_risk:' Maximum risk: <b>$'}};
function LANG(){try{return localStorage.getItem('owlLang')==='en'?'en':'fr';}catch(e){return 'fr';}}
// 2026-09-27: the member's tier decides what is shown
function TIER(){const d=window._d||{},P=d.plan||{};if(d.public)return 'demo';if(P.family)return 'family';if(P.strategy)return 'strategy';if(P.manual)return 'manual';return 'observer';}
function OBS(){const t=TIER();return t==='observer'||t==='strategy';}   // no robot on the account
function HIDEGAUGES(){return TIER()==='observer';}
// observers watch the Owl's robot: the market card speaks about HIS robot
VOICE.observer={
 wx:{ready:['✅','Feu vert','#8df0bb','Les conditions sont réunies. Le robot du Owl entrera dès que le signal se confirme.'],
     flip:['⚖️','Ça peut tourner','#e8c55a','Le sens change peut-être. Le robot du Owl attend la confirmation.'],
     forming:['⏳','Ça se prépare','#8fa1b3','Trop tôt. Le robot du Owl laisse le marché se dessiner.'],
     none:['💤','Rien à faire','#6f8299','Le marché est calme. Le robot du Owl attend une occasion.'],
     brisk:['🍃','Marché soutenu','#e8c55a','Les bougies sont un peu plus grandes que d’habitude. Le robot du Owl laisse passer.'],
     nervous:['🌀','Marché rapide','#ff9678','Les mouvements sont beaucoup plus grands que d’habitude. Le robot du Owl s’écarte.'],
     nogate:['⚡','Marché rapide','#b98cff','Le robot du Owl travaille quand même — à ses risques.']},
 mx_hint:'&middot; ce que voit le robot du Owl',day_lbl:'Votre journ\u00e9e',
 day_empty:'Aucun trade sur votre compte aujourd\u2019hui. Le robot du Owl, lui, travaille : ses r\u00e9sultats sont plus bas.',
 since:'Avec OwlNest depuis le <b>'};
VOICE_EN.observer={
 wx:{ready:['✅','Green light','#8df0bb','Conditions are met. the Owl\u2019s robot will enter as soon as the signal confirms.'],
     flip:['⚖️','It may turn','#e8c55a','The direction may be changing. the Owl\u2019s robot waits for confirmation.'],
     forming:['⏳','Setting up','#8fa1b3','Too early. the Owl\u2019s robot lets the market take shape.'],
     none:['💤','Nothing to do','#6f8299','The market is calm. the Owl\u2019s robot waits for an opportunity.'],
     brisk:['🍃','Lively market','#e8c55a','Candles are a bit larger than usual. the Owl\u2019s robot lets it go.'],
     nervous:['🌀','Fast market','#ff9678','Moves are much larger than usual. the Owl\u2019s robot steps aside.'],
     nogate:['⚡','Fast market','#b98cff','the Owl\u2019s robot works anyway \u2014 at its own risk.']},
 mx_hint:'&middot; what the Owl\u2019s robot sees',day_lbl:'Your day',
 day_empty:'No trade on your account today. the Owl\u2019s robot is working: its results are below.',
 since:'With OwlNest since <b>'};
function T(k){const Lb=LANG()==='en'?VOICE_EN:VOICE;const _vo=MAN()?'manual':(OBS()?'observer':'auto');const v=Lb[_vo]||Lb.auto;
 if(v[k]!==undefined)return v[k];if(Lb.auto[k]!==undefined)return Lb.auto[k];
 const f=VOICE[MAN()?'manual':'auto'];return f[k]!==undefined?f[k]:VOICE.auto[k];}
// Static chrome: a French -> English dictionary applied to text nodes and a
// few attributes; the original French is kept on the node so switching
// back is exact. Regex entries handle counted words.
const I18N_EN=new Map(Object.entries({
 'Accueil':'Home','Marché':'Market','Historique':'History','Réglages':'Settings','Le Nid':'The Nest',
 'Le marché':'The market','Croissance':'Growth','Le rattrapage':'Catching up','À rattraper':'to catch up','Réserve':'Reserve',
 'Prochain trade':'Next trade','Ma semaine':'My week','Jour par jour':'Day by day','· touchez un jour':'· tap a day',
 'Résumé du mois':'Month summary','Calendrier':'Calendar','Statistiques · 30 derniers trades':'Statistics · last 30 trades',
 'Derniers trades':'Latest trades','Tous':'All','Gagnés':'Won','Perdus':'Lost','Cette semaine':'This week','Voir ce jour':'Open that day',
 'Depuis le début':'Since the start','Rapport':'Report','Partager ma semaine':'Share my week','Partager ce rapport':'Share this report',
 'Notifications':'Notifications','Son et vibration à chaque signal':'Sound and vibration on every signal','Activer les notifications':'Enable notifications','Tout':'All','Important seulement':'Important only',
 'Application':'App','Installer l\u2019application':'Install the app','Installer l\\'application':'Install the app',
 'Une icône sur votre écran d\\'accueil':'An icon on your home screen','Une icône sur votre écran d\u2019accueil':'An icon on your home screen',
 'Apparence':'Appearance','Sombre':'Dark','Clair':'Light','Taille du texte':'Text size','Normal':'Normal','Plus grand':'Larger',
 'Langue':'Language','Code d\\'accès':'Passcode','Code d\u2019accès':'Passcode','Protéger cette page avec 4 chiffres':'Protect this page with 4 digits',
 'Télécharger mes trades':'Download my trades','Fichier CSV · date, sens, lot, entrée, sortie, résultat':'CSV file · date, side, lot, entry, exit, result',
 'Messages':'Messages','Les dernières notifications reçues':'Latest notifications received','Mon objectif':'My goal','Choisir un solde à atteindre':'Pick a balance to reach',
 'Mes étapes':'My milestones','Mon parcours':'My journey','Étapes et moments avec OwlNest':'Milestones and moments with OwlNest','Vos premiers pas avec le robot':'Your first steps with the robot','Ce qu\\'il faut savoir':'Good to know','Ce qu\u2019il faut savoir':'Good to know',
 'Revoir le guide':'See the guide again','Le robot':'The robot','Le service':'Service health','Accès':'Access','Déverrouiller Le Nid':'Unlock The Nest',
 'Réservé à l\\'administrateur':'Admin only','Réservé à l\u2019administrateur':'Admin only',
 'Fermer':'Close','Annuler':'Cancel','Enregistrer':'Save','Voir sur le graphique':'View on the chart','Résultat':'Result','Taille':'Size','Entrée':'Entry','Sortie':'Exit','Durée':'Duration','Quand':'When',
 'Achat':'Buy','Vente':'Sell','Rapport du mois':'Month report','Vos comptes':'Your accounts','Le labo':'The lab','Marché':'Market','Robot':'Robot','Labo':'Lab','· idées, tests, observations, décisions':'· ideas, tests, observations, decisions','Ce que le marché nous apprend':'What we learn from the market','Les heures du marché':'Market hours','Le robot explique':'The robot explains','· les occasions laissées passer':'· the opportunities let go','Journal du robot':'Robot journal','· les 20 derniers trades':'· the last 20 trades','Le marché':'The market','· sur ce compte':'· on this account','Vous et le robot':'You and the robot','même période':'same period','Mes paiements':'My payments','Vos re\u00e7us et vos dates de fin':'Your receipts and end dates','Retour à mon compte':'Back to my account','Ouvrir Le Nid':'Open The Nest',
 'Trades':'Trades','Jours verts / rouges':'Green / red days','Meilleur jour':'Best day','Jour le plus dur':'Hardest day','Plus longue série':'Longest streak',
 'Trades gagnants':'Winning trades','Gain moyen':'Average win','Perte moyenne':'Average loss','Gains / pertes':'Wins / losses','Meilleure série':'Best streak',
 'Le robot en ce moment':'The robot right now','Le signal en ce moment':'The signal right now','La journée du robot':'The robot\u2019s day','Votre journée':'Your day',
 'Grands mouvements':'Big moves','Nervosité vs 24 h':'Nervousness vs 24 h','Petits mouvements':'Small moves',
 'Mode manuel':'Manual mode','Mode automatique':'Automatic mode','Mise à l\\'échelle du solde':'Scale with balance','Mise à l\u2019échelle du solde':'Scale with balance',
 'Bienvenue':'Welcome','Votre premier trade':'Your first trade','Les notifications':'Notifications','Aujourd\\'hui':'Today','Aujourd\u2019hui':'Today',
 'gains du jour':'today\u2019s result','depuis lundi':'since Monday','7 derniers jours':'last 7 days','depuis le 1er':'since the 1st','Pire creux':'Worst dip','Ce mois':'This month',
 'Progression':'Progress','3 mois':'3 months','Impossible de joindre le robot':'Cannot reach the robot','Réessayer':'Retry',
 'Vérifiez votre connexion. Le robot, lui, continue de travailler.':'Check your connection. The robot keeps working.',
 'Passer':'Skip','Suivant':'Next','Compris !':'Got it!','Compris\u00a0!':'Got it!','Terminer':'Finish','Plus tard':'Later',
 'Un instant…':'One moment…','Un instant\u2026':'One moment…','Aucun message pour l\u2019instant':'No message yet','dernier :':'last:',
 'aujourd\u2019hui':'today','Marché sous surveillance — aucun trade ouvert':'Market under watch — no open trade','Le robot travaille — ':'The robot is working — ',
 'à rattraper':'to catch up','Solde des trades terminés :':'Closed-trades balance:','Trade en cours':'Running trade','En rattrapage':'Catching up',
 'Le robot travaille avec de l\\'argent réel. Il peut gagner':'The robot works with real money. It can win','et':'and','perdre.':'lose.',
 'Vous tradez avec de l\\'argent réel, sur vos propres décisions. On peut gagner':'You trade with real money, on your own decisions. One can win',
 'La dette':'The debt','La réserve':'The reserve','Quand c\u2019est fini':'When it is over','Quand c\\'est fini':'When it is over',
 'Ce sont les pertes pas encore récupérées. Chaque trade gagné en efface une partie':'These are the losses not yet recovered. Each winning trade erases part of them',
 'Une partie de chaque gain est mise de côté ici, en plus de votre solde. C\\'est elle qui permet au robot de rattraper un peu plus vite.':'Part of every win is set aside here, on top of your balance. It lets the robot catch up a little faster.',
 'Une fois la dette à zéro, le robot repasse en mode normal. Rien à faire de votre côté.':'Once the debt is at zero, the robot is back to normal mode. Nothing to do on your side.',
 'Six choses simples, à garder en tête.':'Six simple things to keep in mind.',
 'Chaque trade ne risque qu\\'une petite part du compte — jamais tout d\\'un coup.':'Each trade risks only a small part of the account — never all at once.',
 'Ne confiez que de l\\'argent que vous pouvez laisser travailler longtemps, sans en avoir besoin.':'Only entrust money you can leave working for a long time without needing it.',
 'Vous pouvez mettre en pause ou retirer votre compte à tout moment, ici dans les Réglages.':'You can pause or withdraw your account at any time, here in Settings.',
 'Les résultats passés ne promettent jamais l\\'avenir.':'Past results never promise the future.',
 'Premier trade':'First trade','10 trades':'10 trades','50 trades':'50 trades','100 trades':'100 trades','Semaine verte':'Green week','Objectif atteint':'Goal reached','30 jours':'30 days','100 jours':'100 days',
 'Le robot a agi pour vous':'The robot acted for you','Le rythme est pris':'The rhythm is set','Une vraie habitude':'A real habit','Un cap':'A milestone','Une semaine terminée dans le vert':'A week closed in the green',
 'Votre objectif personnel':'Your personal goal','Un mois avec le robot':'A month with the robot','Une saison avec le robot':'A season with the robot',
 'Un solde que vous aimeriez atteindre. Il reste sur ce téléphone ; personne d’autre ne le voit.':'A balance you would like to reach. It stays on this phone; nobody else sees it.',
 'Retirer l’objectif':'Remove the goal','Objectif atteint :':'Goal reached:','du chemin vers':'of the way to','il reste':'left',
 'Ouvrir Le Nid':'Open The Nest','Graphique':'Chart','Pause':'Pause','Reprendre':'Resume','Urgence':'Emergency','Réinitialiser':'Reset',
 'Vert = frais, orange = en retard, rouge = figé ou arrêté.':'Green = fresh, amber = late, red = stale or stopped.',
 'Lot de base actuel :':'Current base lot:','mise à l\u2019échelle active':'scaling on','Aucun trade pour l\u2019instant':'No trade yet','Rien à raconter pour l\u2019instant.':'Nothing to tell yet.'
}));
const I18N_RX=[[/^(\d+) trades?$/,'$1 trades'],[/^(\d+) trades? en cours$/,'$1 running'],[/^Prochain palier \$(\d+)\s*→\s*\$(\d+)\/jour\s*·\s*(\d+)\s*%$/,'Next step $$$1 → $$$2/day · $3 %'],[/^Objectif : \$(\d+)\s*·\s*(\d+)\s*%$/,'Goal: $$$1 · $2 %'],
 [/^Lot de base actuel : ([\d.]+) lot · mise à l\u2019échelle active$/,'Current base lot: $1 lot · scaling on'],[/^Trade en cours · (.+)$/,'Running trade · $1'],
 [/^(\d+) trades? · (\d+) (occasions? laissées? passer|signa(?:l|ux) écartés?)$/,'$1 trades · $2 set aside'],[/^ aujourd\u2019hui$/,' today'],[/^(\d+) sur (\d+) étapes$/,'$1 of $2 milestones'],
 [/^(\d+) comptes? · total$/,'$1 accounts · total'],[/^Bonjour (.+)$/,'Good morning $1'],[/^Bon après-midi (.+)$/,'Good afternoon $1'],[/^Bonsoir (.+)$/,'Good evening $1']];
function _i18nText(fr){const k=fr.trim();if(!k)return null;
 if(I18N_EN.has(k))return fr.replace(k,I18N_EN.get(k));
 for(const [rx,to] of I18N_RX){if(rx.test(k))return fr.replace(k,k.replace(rx,to));}
 return null;}
function applyLang(root){
 const en=LANG()==='en';root=root||document.body;if(!root)return;
 try{document.documentElement.lang=en?'en':'fr';}catch(e){}
 const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode:n=>{const p=n.parentNode;
  if(!p||/^(SCRIPT|STYLE|SVG|INPUT|TEXTAREA)$/i.test(p.nodeName))return NodeFilter.FILTER_REJECT;
  return NodeFilter.FILTER_ACCEPT;}});
 const nodes=[];while(w.nextNode())nodes.push(w.currentNode);
 nodes.forEach(n=>{
  if(en){const fr=(n.__fr!==undefined)?n.__fr:n.nodeValue;const t=_i18nText(fr);
   if(t!==null&&n.nodeValue!==t){if(n.__fr===undefined)n.__fr=fr;n.nodeValue=t;}}
  else if(n.__fr!==undefined&&n.nodeValue!==n.__fr){n.nodeValue=n.__fr;}});
 root.querySelectorAll('[aria-label],[title],[placeholder]').forEach(el=>['aria-label','title','placeholder'].forEach(a=>{
  const v=el.getAttribute(a);if(!v)return;const key='__fr_'+a;
  if(en){const fr=el[key]!==undefined?el[key]:v;const t=_i18nText(fr);if(t!==null&&v!==t){if(el[key]===undefined)el[key]=fr;el.setAttribute(a,t);}}
  else if(el[key]!==undefined&&v!==el[key])el.setAttribute(a,el[key]);}));
}
let _i18nT=null;
function i18nWatch(){if(!window.MutationObserver||window._i18nMO)return;
 window._i18nMO=new MutationObserver(()=>{clearTimeout(_i18nT);_i18nT=setTimeout(()=>applyLang(),60);});
 window._i18nMO.observe(document.body,{childList:true,subtree:true,characterData:true});}
function setLang(l){try{localStorage.setItem('owlLang',l);}catch(e){}
 document.querySelectorAll('.lgc').forEach(b=>{const on=b.dataset.l===l;
  b.style.background=on?'var(--surface3)':'transparent';b.style.borderColor=on?'var(--border2)':'var(--border)';b.style.color=on?'var(--text2)':'var(--muted2)';});
 applyLang();if(window._d){window._lastS=null;render(window._d);loadDay();}
 fetch(B+'push_pref',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'lang='+l}).catch(()=>null);}
// 2026-10-01 (owner): the multi-timeframe snapshot taken at entry, as
// three dots - M15, H1, H4. Green when that timeframe pointed the way the
// trade went, red when it pointed against, grey when it had no trend yet.
// Nothing is drawn for trades older than the recording - which is most of
// them today - rather than three grey dots that mean "no data" but read
// as "no trend".
function tfSide(t,dir){
 if(t==null||t===0)return '#4a5a6b';
 return (t===dir)?'var(--up)':'var(--down)';
}
function tfDots(x){
 const s=(x.tf||{}).e;if(!s)return '';
 const dir=(x.dir==='A')?1:-1;
 // 2026-10-02 (owner: "why 3 red dots, not green?"). The dots were right
 // and the CHANNEL was wrong. They used the same red/green palette as the
 // money, on the same row, for a completely different meaning - so a
 // winning sell against three rising timeframes showed red dots beside a
 // green +$2.90 and read as a fault. Colour cannot carry two unrelated
 // scales on one line.
 //
 // Shape carries it instead: filled = that timeframe was WITH the trade,
 // hollow = against. Monochrome accent, so it cannot be mistaken for P&L,
 // and the number of filled dots reads as a little 0-to-3 gauge.
 const d=['m15','h1','h4'].map(k=>{
  const t=s[k],on=(t!=null&&t!==0&&t===dir);
  return '<span style="display:inline-block;width:7px;height:7px;'+
   'border-radius:50%;box-sizing:border-box;'+
   (on?'background:var(--accent-soft)'
     :'border:1.5px solid var(--muted);opacity:.75')+'"></span>';}).join('');
 const n=['m15','h1','h4'].filter(k=>s[k]===dir).length;
 return ' <span title="M15 H1 H4 \u00e0 l\u2019entr\u00e9e \u00b7 '+n+' sur 3 allaient dans le '+
  'sens du trade (plein = avec, creux = contre)" '+
  'style="display:inline-flex;gap:3px;align-items:center;'+
  'margin-left:6px;vertical-align:middle">'+d+'</span>';
}
function fdur(m){
 if(m==null)return '';
 m=Math.round(m);
 if(m<60)return m+' min';
 const h=Math.floor(m/60),r=m%60;
 if(h<24)return h+' h'+(r?' '+String(r).padStart(2,'0'):'');
 const j=Math.floor(h/24);
 return j+' j '+(h%24)+' h';}
function sheet(html){return new Promise(res=>{
 // 2026-09-27: wait for a just-closed sheet's history.back() to land before
 // opening the next one (the form -> password chain used to lose the
 // password sheet), and cancel its pending hide timer
 const _w=Math.max(0,(window._shClosedAt||0)+450-Date.now());
 setTimeout(()=>{
 const bg=document.getElementById('sheetbg'),
  sh=document.getElementById('sheet');
 clearTimeout(window._shHideT);
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
  window._shClosedAt=Date.now();
  window._shHideT=setTimeout(()=>{bg.style.display='none'},250);
  try{if(history.state&&history.state.sh)history.back()}catch(e){}
  res(v)};
 bg.onclick=()=>window._shDone(null);
 const inp=document.getElementById('shpw');
 if(inp){setTimeout(()=>inp.focus(),280);
  inp.onkeydown=(ev)=>{if(ev.key==='Enter'){
   const m=sh.querySelector('.shmain');if(m)m.click();}};}
 },_w);
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
  ptrShow();loadDay();loadInbox();
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
 const L=window._ledD||{mode:'bot',debt:0,chest:0,nl:0.02,fill:0};
 const F=x=>'$'+(x||0).toFixed(2);
 const fm=v=>v<10?v.toFixed(1):v.toFixed(0);
 const ico=(n,c)=>'<div class="evi" style="color:'+c+'"><svg class="ic ic-s">'+
  '<use href="#'+n+'"/></svg></div>';
 const row=(i,t,x)=>'<div class="srow-ev">'+i+'<div style="flex:1;min-width:0">'+
  '<b style="font-size:.92rem">'+t+'</b><div style="font-size:.84rem;'+
  'color:var(--muted2);line-height:1.45;margin-top:2px">'+x+'</div></div></div>';
 const cap=L.cap||0,pct=cap?Math.max(0,Math.min(100,100*(L.chest||0)/cap)):0;
 const manual=MAN();   // 2026-09-27: _ledD never carried 'man' - the manual branch was dead
 const intro=manual
  ?'Il reste <b>'+F(L.debt)+'</b> &agrave; rattraper. Une partie de chaque gain '+
   'est mise de c&ocirc;t&eacute; pour y arriver, sans jamais risquer plus que pr&eacute;vu.'
  :'Il reste <b>'+F(L.debt)+'</b> &agrave; rattraper. Le robot met une partie de '+
   'chaque gain de c&ocirc;t&eacute; pour y arriver, sans jamais risquer plus de '+
   '<b>$'+fm(L.stake||0)+'</b> sur un trade.';
 const cell=(l,v,c,sub)=>'<div class="card" style="flex:1;padding:12px 8px 10px">'+
  '<div class="lbl">'+l+'</div><div class="val" style="font-size:1.35rem;color:'+c+'">'+
  v+'</div><div class="sub">'+sub+'</div></div>';
 sheet('<h3 style="margin:0 0 4px">Le rattrapage</h3>'+
  '<p style="color:var(--text);font-size:.95rem;line-height:1.5;margin:0 0 12px">'+
  intro+'</p>'+
  '<div style="display:flex;gap:10px;margin-bottom:10px">'+
   cell('&Agrave; rattraper',F(L.debt),'var(--down-soft)','baisse &agrave; chaque gain')+
   cell('R&eacute;serve',F(L.chest),'var(--warn)',cap?'sur $'+fm(cap)+' max':'mise de c&ocirc;t&eacute;')+
  '</div>'+
  (cap?'<div style="background:var(--surface3);border-radius:99px;height:6px;'+
   'overflow:hidden;margin-bottom:12px"><div style="height:6px;border-radius:99px;'+
   'width:'+pct.toFixed(0)+'%;background:linear-gradient(90deg,#b8963f,#e8c55a)">'+
   '</div></div>':'')+
  row(ico('i-target','var(--down-soft)'),'La dette',
   'Ce sont les pertes pas encore r&eacute;cup&eacute;r&eacute;es. Chaque trade '+
   'gagn&eacute; en efface une partie'+(L.clears>0.005?' &mdash; le prochain gain en '+
   'enl&egrave;verait environ <b>$'+fm(L.clears)+'</b>':'')+'.')+
  row(ico('i-lock','var(--warn)'),'La r&eacute;serve',
   'Une partie de chaque gain est mise de c&ocirc;t&eacute; ici, en plus de votre '+
   'solde. C&#39;est elle qui permet au robot de rattraper un peu plus vite.')+
  row(ico('i-chart','var(--accent-soft)'),
   manual?'Votre plafond : '+L.nl.toFixed(2)+' lot':'Le prochain trade : '+L.nl.toFixed(2)+' lot',
   manual?'Le plus gros trade que votre r&eacute;serve paie enti&egrave;rement '+
    'aujourd&#39;hui. Prenez moins si vous voulez &mdash; jamais plus.'
   :'Le robot adapte la taille de son prochain trade &agrave; ce qu&#39;il a en '+
    'r&eacute;serve'+(L.fill>0?', sans d&eacute;passer <b>$'+fm(L.stake||0)+
    '</b> de risque':'. Pour l&#39;instant, il garde la taille normale')+'.')+
  row(ico('i-check','var(--up)'),'Quand c&#39;est fini',
   manual?'Une fois la dette &agrave; z&eacute;ro, le lot conseill&eacute; redevient le lot normal.'
   :'Une fois la dette &agrave; z&eacute;ro, le robot repasse en mode normal. '+
   'Rien &agrave; faire de votre c&ocirc;t&eacute;.')+
  '<div style="background:rgba(232,197,90,.08);border:1px solid rgba(232,197,90,.25);'+
   'border-radius:12px;padding:10px 12px;font-size:.82rem;color:var(--warn);'+
   'line-height:1.45;margin:12px 0 10px">&Agrave; savoir : un trade de rattrapage '+
   'est un peu plus gros, donc il gagne plus <b>et il perd plus</b>. Garde-fou : '+
   'jamais plus de 10&nbsp;% du solde sur un seul trade.</div>'+
  '<button class="shbtn shmain" onclick="_shDone(1)">Compris&nbsp;!</button>');
}
window.addEventListener('load',()=>{
 const alb=document.getElementById('adminlockbtn');
 if(alb)alb.onclick=async(e)=>{e.preventDefault();
  const pw=await askPwd('D&eacute;verrouiller Le Nid ?',
   'Mot de passe administrateur. Une fois entr&eacute;, Le Nid reste '+
   'visible sur cet appareil, quel que soit le compte affich&eacute;.',
   '&#128274; D&eacute;verrouiller',false);
  if(!pw)return;
  const r=await fetch(B+'admin_unlock',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'pwd='+encodeURIComponent(pw)}).catch(()=>null);
  let j=null;try{j=await r.json();}catch(e2){}
  if(!j||!j.ok){await info('&#10060; <h3>Mot de passe incorrect.'+
   '</h3>');return;}
  location.reload();};
 const pb=document.getElementById('pausebtn');
 if(pb)pb.onclick=async(e)=>{e.preventDefault();
  if(pauseLocked){await info('&#128274; <h3>R&eacute;serv&eacute; '+
   '&agrave; l&#39;administrateur</h3><p>Ce compte peut voir '+
   'l&#39;interrupteur mais pas s&#39;en servir. Seul le compte '+
   'concern&eacute; peut basculer entre manuel et automatique.</p>');
   return;}
  // Owner 2026-09-17: do not spell the strategy out in the app. Say what
  // changes for the user, nothing about which conditions are watched.
  // 2026-09-28 (owner): a Manuel-only member has NO robot on their account -
  // "launching the automatic" would just stop the desk and run nothing.
  // Automatic trading is the Automatique package (settled with the Owl) or the
  // copy of the Owl's account on MQL5: say so and point at the offers.
  const _P=(window._d&&window._d.plan)||{};
  if(isPaused&&!_P.family&&!(window._d&&window._d.is_master)){
   const en=LANG()==='en';
   const v=await sheet('<h3>'+(en?'Automatic trading':'Trading automatique')+'</h3><p>'+(en
    ?'The robot does not run on your account with the Signal plan. Automatic trading is the <b>Automatic</b> package, for the family, by invitation - ask the Owl for a code on Telegram.'
    :'Le robot ne tourne pas sur votre compte avec le paquet Signal. Le trading automatique, c\u2019est le paquet <b>Automatique</b>, r\u00e9serv\u00e9 \u00e0 la famille, sur invitation \u2014 demandez un code au Owl sur Telegram.')+'</p>'+
    '<button class="shbtn shmain" onclick="_shDone({o:1})">'+(en?'See the plans':'Voir les offres')+'</button>'+
    '<button class="shbtn shghost" onclick="_shDone(null)">'+(en?'Close':'Fermer')+'</button>');
   if(v&&v.o)setTimeout(offersSheet,500);
   return;}
  const pw=await askPwd(
   isPaused?'Lancer le trading automatique ?':'Repasser en manuel ?',
   isPaused
    ?'Le robot prendra les trades tout seul, et seulement quand les '+
     'conditions du march\u00e9 sont favorables. Aucune performance '+
     'garantie. Vous pouvez repasser en manuel \u00e0 tout moment.'
    :'Le robot n\u2019entrera plus seul. Vous gardez la main depuis le '+
     'graphique. Les trades ouverts gardent leur SL et leur TP.',
   isPaused?'&#129302; Lancer l\u2019automatique':'&#9995; Repasser en manuel',
   isPaused);
  if(!pw)return;
  const r=await fetch(B+'pause',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'on='+(isPaused?'0':'1')+'&pwd='+encodeURIComponent(pw)}
   ).catch(()=>null);
  try{const j=await r.json();
   if(!j.ok){await info('&#10060; <h3>Mot de passe incorrect.</h3>');
    return;}}catch(e2){}
  load();};
(function(){const r=document.getElementById('intmkrow');if(!r)return;
  const sw=document.getElementById('intmk-sw');
  const rd=()=>{try{return localStorage.getItem('owlIntMarks')!=='0';}catch(e){return true;}};
  const paint=()=>{const on=rd();sw.classList.toggle('on',on);
   const en=LANG()==='en';
   document.getElementById('intmk-lbl').textContent=en?'Inner structure on the chart':'Petite structure sur le graphique';
   document.getElementById('intmk-sub').textContent=on
    ?(en?'The robot no longer trades it - shown for reading only':'Le robot ne la trade plus \u2014 affichage seulement')
    :(en?'Hidden on the chart':'Masqu\u00e9e sur le graphique');};
  r.onclick=()=>{try{localStorage.setItem('owlIntMarks',rd()?'0':'1');}catch(e){}paint();};
  paint();})();
 const scb=document.getElementById('scalebtn');
 if(scb)scb.onclick=async(e)=>{e.preventDefault();
  const on=!!window._scaleOn;
  const pw=await askPwd(
   on?'D&eacute;sactiver la mise &agrave; l&#39;&eacute;chelle ?'
     :'Activer la mise &agrave; l&#39;&eacute;chelle ?',
   on?'Le lot et la cible du jour redeviendront fixes, quel que soit '+
      'le solde du compte.'
     :'Le lot et la cible du jour du compte suivront d&eacute;sormais '+
      'le solde (m&ecirc;me formule que Val&egrave;re). Le changement '+
      'prend effet au prochain reset quotidien (00:00 UTC).',
   on?'D&eacute;sactiver':'&#9889; Activer',on);
  if(!pw)return;
  const r=await fetch(B+'scale_pref',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'on='+(on?'0':'1')+'&pwd='+encodeURIComponent(pw)}
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
  const send=async(extra)=>{const r=await fetch(B+'activate',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'code='+encodeURIComponent(code)+(extra||'')}).catch(()=>null);
   try{return await r.json();}catch(e){return null;}};
  let j=await send('');
  // 2026-10-04 (owner): a Signal member switching to Automatique - the
  // robot needs the MT5 account it will trade; asked once, here
  if(j&&!j.ok&&j.need==='mt5'){
   const en=LANG()==='en';
   const inp=(id,ph,t)=>'<input id="'+id+'" type="'+(t||'text')+'" placeholder="'+ph+'" style="width:100%;box-sizing:border-box;background:var(--surface2);border:1px solid var(--border);border-radius:12px;color:var(--text);padding:12px;font-size:1rem;margin-top:8px">';
   const v=await sheet('<h3>'+(en?'Your MT5 account':'Votre compte MT5')+'</h3><p style="color:var(--text2)">'+(en?'This code puts the robot on your own account. Tell it which one - once.':'Ce code met le robot sur votre propre compte. Dites-lui lequel \u2014 une seule fois.')+'</p>'+
    inp('am-l',en?'MT5 account number':'Num\u00e9ro de compte MT5')+inp('am-s','Exness-MT5Real30')+inp('am-p',en?'account password (main)':'mot de passe du compte (principal)','password')+
    '<div style="font-size:.78rem;color:var(--muted);margin-top:8px">'+(en?'The main password: the robot must be able to trade. Your app login does not change.':'Le mot de passe principal : le robot doit pouvoir trader. Votre connexion \u00e0 l\u2019app ne change pas.')+'</div>'+
    '<button class="shbtn shmain" style="margin-top:14px" onclick="_shDone({l:document.getElementById(&#39;am-l&#39;).value,s:document.getElementById(&#39;am-s&#39;).value,p:document.getElementById(&#39;am-p&#39;).value})">'+(en?'Put the robot on it':'Mettre le robot dessus')+'</button>'+
    '<button class="shbtn shghost" onclick="_shDone(null)">'+(en?'Cancel':'Annuler')+'</button>');
   if(!v||!v.l||!v.s||!v.p){ab.disabled=false;ab.textContent='Activer';msg.textContent='';return;}
   j=await send('&mt5_login='+encodeURIComponent(v.l)+'&mt5_server='+encodeURIComponent(v.s)+'&mt5_password='+encodeURIComponent(v.p));}
  ab.disabled=false;ab.textContent='Activer';
  try{
   if(j&&j.ok&&j.pkg&&j.pkg!=='family'){document.getElementById('actcard').innerHTML='<div class="lbl">Code</div><div style="font-size:.95rem;color:var(--text);line-height:1.5;margin-top:10px"><b>'+(j.pkg==='manual'?'Signal':'Strat\u00e9gie')+' activ\u00e9 !</b> '+(j.days||30)+' jours de plus.</div>';try{confetti();}catch(e2){}setTimeout(load,1500);return;}
   if(j.ok){document.getElementById('actcard').innerHTML=
    '<div class="lbl">Activer le robot</div>'+
    '<div class="jsteps" style="margin-top:12px"><div class="jl"></div>'+
    '<div class="js done"><div class="jc"><svg class="ic ic-s"><use href="#i-check"/></svg></div><span>Compte</span></div>'+
    '<div class="js done"><div class="jc"><svg class="ic ic-s"><use href="#i-check"/></svg></div><span>Code</span></div>'+
    '<div class="js on"><div class="jc"><svg class="ic ic-s"><use href="#i-bot"/></svg></div><span>Pr&ecirc;t</span></div></div>'+
    '<div style="font-size:.95rem;color:var(--text);line-height:1.5;margin-top:12px">'+
    '<b>Robot activ&eacute; !</b> Il surveille maintenant le march&eacute; pour vous.</div>';
    try{confetti();}catch(e2){}setTimeout(load,1500);}
   else{msg.textContent='Code invalide ou expir&eacute;. Demandez un '+
    'nouveau code au Owl.';}}
  catch(e2){msg.textContent='Petit souci, r&eacute;essayez.';}};
 const gb=document.getElementById('goalbtn');
 if(gb)gb.onclick=async(e)=>{e.preventDefault();
  const b0=(window._d&&window._d.balance)?window._d.balance:0;
  const chips=[25,50,100,250].map(a=>
   '<button class="shbtn shghost" style="flex:1;margin:0;'+
   'padding:11px 0;font-size:.9rem" '+
   'onclick="document.getElementById(\\'goalamt\\').value=\\''+
   Math.ceil(b0+a)+'\\'">+$'+a+'</button>').join('');
  const v=await sheet('<h3>&#127919; Objectif</h3>'+
   '<div style="display:flex;justify-content:space-between;'+
   'align-items:center;background:var(--bg);border-radius:12px;'+
   'padding:12px 14px;margin-bottom:12px">'+
   '<span style="color:var(--muted2);font-size:.85rem">Solde actuel'+
   '</span><b style="font-size:1.1rem">$'+b0.toFixed(2)+
   '</b></div>'+
   '<div style="font-size:.78rem;color:var(--muted2);margin-bottom:8px">'+
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
   '<button class="shbtn shghost" style="color:var(--down-soft)" '+
   'onclick="_shDone([\\'0\\','+
   'document.getElementById(\\'shpw\\').value])">D&eacute;sactiver '+
   'la barre</button>'+
   '<button class="shbtn shghost" onclick="_shDone(null)">Annuler'+
   '</button>');
  if(!v||!v[1])return;
  if(v[0]!=='0'&&parseFloat(v[0]||'0')<=b0){
   await info('&#9888;&#65039; <h3>Visez plus haut !</h3>'+
    '<p>L&#39;objectif doit &ecirc;tre au-dessus du solde actuel ('+
    '$'+b0.toFixed(2)+').</p>');
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
    'text-align:center;background:var(--bg);border-radius:14px;'+
    'padding:18px 6px;margin:6px 0 10px;color:var(--up-soft)">'+j.code+
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
   '<div style="padding:48px 24px;text-align:center;color:var(--text2);'+
   'font-family:sans-serif;line-height:1.7">&#128075; <b>Compte '+
   'retir&eacute;.</b><br>Le robot ne trade plus ce compte.<br>Pour '+
   'revenir : inscrivez-vous &agrave; nouveau.<br><br>'+
   '<a href="../" style="color:var(--accent)">Accueil</a></div>';}};
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
  b.style.background=on?'var(--surface3)':'transparent';
  b.style.borderColor=on?'var(--border2)':'var(--border)';
  b.style.color=on?'var(--text2)':'var(--muted2)';});}
 window.npcPaint=npcPaint;npcPaint();
 const qb=document.getElementById('quietbtn');
 function qPaint(){if(!qb)return;const on=!!window._pquiet;
  document.getElementById('quiet-st').textContent=on?'Oui':'Non';
  qb.style.borderColor=on?'var(--border2)':'var(--border)';
  qb.style.background=on?'var(--surface3)':'transparent';
  qb.style.color=on?'var(--text2)':'var(--muted2)';}
 window.qPaint=qPaint;qPaint();
 // 2026-09-28: opt-in chime + vibration when a NEW signal shows while the app is open
 const cb=document.getElementById('chimebtn');
 function cPaint(){if(!cb)return;let on=false;try{on=localStorage.getItem('owlChime')==='1';}catch(e){}
  document.getElementById('chime-st').textContent=on?(LANG()==='en'?'Yes':'Oui'):(LANG()==='en'?'No':'Non');
  cb.style.borderColor=on?'var(--border2)':'var(--border)';cb.style.background=on?'var(--surface3)':'transparent';cb.style.color=on?'var(--text2)':'var(--muted2)';}
 cPaint();
 if(cb)cb.onclick=()=>{let on=false;try{on=localStorage.getItem('owlChime')==='1';localStorage.setItem('owlChime',on?'0':'1');}catch(e){}cPaint();if(!on){try{window._ac=window._ac||new (window.AudioContext||window.webkitAudioContext)();}catch(e){}chime(true);}};
 if(qb)qb.onclick=async()=>{window._pquiet=!window._pquiet;qPaint();
  await fetch(B+'push_pref',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'quiet='+(window._pquiet?'1':'0')+'&tz='+
    new Date().getTimezoneOffset()}).catch(()=>null);};
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
  window._pushLocal=true;const _np=document.getElementById('nopushcard');if(_np)_np.style.display='none';
  await info('&#128276; <h3>Notifications activ&eacute;es !</h3>'+
   '<p>Vous recevrez les gains, les orages et les victoires des '+
   'soldats &mdash; m&ecirc;me app ferm&eacute;e.</p>');
  notifSetup();
 };
}
window.addEventListener('load',notifSetup);
function tourList(){const M=MAN();return [
 ['eq','&#128176; &Ccedil;a, c&#39;est votre argent. Il se met '+
  '&agrave; jour tout seul, toutes les 5 secondes.'],
 ['mxsum',M?'&#127782;&#65039; Ici, l&#39;app vous dit ce que fait le march&eacute; '+
  'et si un signal est jouable. Touchez la carte pour la page March&eacute;.'
  :'&#127782;&#65039; Ici, le robot vous dit ce qu&#39;il voit : '+
  'march&eacute; calme ou agit&eacute;, et ce qu&#39;il a fait aujourd&#39;hui. '+
  'Touchez la carte pour la page March&eacute;.'],
 ['ledcard',M?'&#128737;&#65039; Apr&egrave;s une perte, une partie de chaque gain '+
  'est mise de c&ocirc;t&eacute; et l&#39;app vous conseille le lot. Tout se suit ici.'
  :'&#128737;&#65039; Quand le robot perd un peu, il met une '+
  'partie de chaque gain de c&ocirc;t&eacute; pour se rattraper, sans '+
  'risquer plus. Tout se suit ici.'],
 [null,'&#128197; En bas : l&#39;Accueil, le March&eacute;, l&#39;Historique '+
  'jour par jour (touchez un jour pour son histoire), et les '+
  'R&eacute;glages &mdash; pensez &agrave; activer les notifications !']];}
let TOUR=tourList();
let _ti=-1;
function tourStep(i){
 if(i===0)TOUR=tourList();
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
  TOUR.map((_,k)=>'<span style="display:inline-block;width:'+(k===i?'18px':'6px')+
   ';height:6px;border-radius:99px;margin:0 3px;background:'+
   (k===i?'var(--accent-soft)':'rgba(255,255,255,.25)')+
   ';transition:width .25s"></span>').join('');
 document.getElementById('tournext').textContent=
  i===TOUR.length-1?'C\\u2019est parti !':'Suivant';
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
  {const ico=(n,c)=>'<div class="evi" style="color:'+c+'"><svg class="ic ic-s">'+
    '<use href="#'+n+'"/></svg></div>';
   const row=(i,t)=>'<div class="srow-ev">'+i+'<div style="flex:1;min-width:0;'+
    'font-size:.92rem;line-height:1.45">'+t+'</div></div>';
   sheet('<h3 style="margin:0 0 4px">Ce qu&#39;il faut savoir</h3>'+
    '<p style="color:var(--text);font-size:.95rem;line-height:1.5;margin:0 0 10px">'+
    'Six choses simples, &agrave; garder en t&ecirc;te.</p>'+
    row(ico('i-chart','var(--accent-soft)'),MAN()?'Vous tradez avec de l&#39;argent '+
     'r&eacute;el, sur vos propres d&eacute;cisions. On peut gagner <b>et</b> perdre.'
     :'Le robot travaille avec de '+
     'l&#39;argent r&eacute;el. Il peut gagner <b>et</b> perdre.')+
    row(ico('i-lock','var(--warn)'),'Chaque trade ne risque qu&#39;une petite '+
     'part du compte &mdash; jamais tout d&#39;un coup.')+
    row(ico('i-cloud','var(--muted2)'),MAN()?'Quand le march&eacute; devient '+
     'm&eacute;chant, l&#39;app vous le dit : mieux vaut s&#39;abriter.'
     :'Quand le march&eacute; devient '+
     'm&eacute;chant, le robot s&#39;abrite tout seul et attend.')+
    row(ico('i-target','var(--down-soft)'),'Ne confiez que de l&#39;argent que '+
     'vous pouvez laisser travailler longtemps, sans en avoir besoin.')+
    row(ico('i-switch','var(--text3)'),'Vous pouvez mettre en pause ou retirer '+
     'votre compte &agrave; tout moment, ici dans les R&eacute;glages.')+
    row(ico('i-activity','var(--up)'),'Les r&eacute;sultats pass&eacute;s ne '+
     'promettent jamais l&#39;avenir.')+
    '<button class="shbtn shmain" style="margin-top:14px" onclick="_shDone(1)">'+
    'Compris&nbsp;!</button>');}};
 const tb=document.getElementById('tourbtn');
 if(tb)tb.onclick=(e)=>{e.preventDefault();
  tab('home',document.querySelector('.tb'));onboard(0);};
 setTimeout(()=>{try{
  if(!localStorage.getItem('owlTourDone'))onboard(0);
  if(!localStorage.getItem('owlFirstSeen'))localStorage.setItem('owlFirstSeen',String(Date.now()));
 }catch(e){}},1500);
});
function labAllowed(){const d=window._d||{};let adm=false;try{adm=!!localStorage.getItem('owl_adm');}catch(e){}return !!(d.is_master||adm||TIER()==='strategy');}
function labVisible(){const d=window._d||{};return !d.public;}
function mxView(v,quiet){v=(v==='robot')?'robot':(v==='lab'&&labVisible()?'lab':'market');
 const m=document.getElementById('mx-market'),r=document.getElementById('mx-robot'),l=document.getElementById('mx-lab');if(!m||!r)return;
 m.style.display=v==='market'?'':'none';r.style.display=v==='robot'?'':'none';if(l)l.style.display=v==='lab'?'':'none';
 if(v==='lab'){window._labT=0;loadLab(window._d||{});}
 [['mxs-market','market'],['mxs-robot','robot'],['mxs-lab','lab']].forEach(([id,k])=>{const b=document.getElementById(id);if(b){b.classList.toggle('on',v===k);b.setAttribute('aria-selected',v===k?'true':'false');}});
 try{localStorage.setItem('owlMxView:'+B,v);}catch(e){}
 if(!quiet){try{navigator.vibrate&&navigator.vibrate(6)}catch(e){}window.scrollTo({top:0});}}
(function(){let v='market';try{v=localStorage.getItem('owlMxView:'+B)||'market';}catch(e){}window.addEventListener('load',()=>mxView(v,true));})();
function tab(n,el){
 document.querySelectorAll('.tab').forEach(x=>
  x.classList.toggle('on',x.id==='tab-'+n));
 document.querySelectorAll('.tb').forEach(x=>{
  x.classList.toggle('on',x===el);
  x.setAttribute('aria-current',x===el?'page':'false');});
 try{navigator.vibrate&&navigator.vibrate(6)}catch(e){}
 window.scrollTo({top:0});
}
(function(){
 const h=new Date().getHours();
 const g=(h>=5&&h<12)?'Bonjour'
  :((h>=12&&h<18)?'Bon apr&egrave;s-midi':'Bonsoir');
 const he=document.getElementById('hello');
 // 2026-10-01: the wave is gone, so only the greeting word changes
 he.innerHTML=he.innerHTML.replace('Bonjour',g);
})();
function confetti(em){
 for(let i=0;i<44;i++){
  const s=document.createElement('div');
  s.textContent=(em||['\\u{1F389}','\\u2728','\\u{1F49A}','\\u{1F3C6}'])[i%4];
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
function calNav(k){window._calOff=Math.max(0,Math.min(2,(window._calOff||0)+k));window._lastS=null;load();}
function dayx(l){
 if(window._lpFired){window._lpFired=0;return;}
 const tr=((window._dtr||{})[l]||[]).slice();
 const row=(window._days||[]).find(x=>x.d===l);
 const p=row?row.p:tr.reduce((a,t)=>a+t.p,0);
 const won=tr.filter(t=>t.p>0.005).length,lost=tr.filter(t=>t.p<-0.005).length;
 const money=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 const ico=(n,c)=>'<div class="evi" style="color:'+c+'"><svg class="ic ic-s"><use href="#'+n+'"/></svg></div>';
 let sum;
 if(!tr.length)sum=T('dayx_empty');
 else sum='Ce jour-l\u00e0 : '+tr.length+' trade'+(tr.length>1?'s':'')+
  (tr.length>1?' \u2014 '+won+' gagn\u00e9'+(won>1?'s':'')+', '+lost+' perdu'+(lost>1?'s':''):'')+
  '. R\u00e9sultat : <b class="'+sgn(p)+'">'+money(p)+'</b>.';
 const who=T('dayx_who');
 const rows=tr.map(t=>'<div class="srow-ev">'+(t.p>=0?ico('i-check','var(--up)'):ico('i-x','var(--down)'))+
  '<div style="flex:1">'+(t.p>=0?who+'<b class="pos">gagn\u00e9 '+money(t.p)+'</b>.'
   :who+'<b class="neg">perdu $'+Math.abs(t.p).toFixed(2)+'</b>.')+'</div>'+
  '<span class="evt">'+t.t+'</span></div>').join('');
 sheet('<h3>'+l+'</h3><p style="color:var(--text)">'+sum+'</p>'+daySpark(tr)+rows+
  '<button class="shbtn shmain" onclick="_shDone(1)">Fermer</button>');
}
window._cvz='7';
function drawNerv(){
 const D=window._day,el=document.getElementById('mx-nerv'),
  ms=document.getElementById('mxs-spark');
 if(!D)return;const pts=(D.nerv||[]).slice(-1440);
 if(pts.length<5){if(el)el.style.display='none';if(ms)ms.style.display='none';return;}
 const t0=pts[0][0],t1=pts[pts.length-1][0],sp=Math.max(1,t1-t0);
 const mx=Math.max(2.2,...pts.map(p=>p[1]));
 const X=t=>(6+(t-t0)/sp*288);
 const bands=(Y,top,hgt)=>{let o='',st=null;
  pts.forEach((p,i)=>{if(p[1]>=1.85&&st===null)st=p[0];
   if((p[1]<1.85||i===pts.length-1)&&st!==null){
    o+='<rect x="'+X(st).toFixed(1)+'" y="'+top+'" width="'+
     Math.max(1.5,X(p[0])-X(st)).toFixed(1)+'" height="'+hgt+'" style="fill:var(--down);'+
     'opacity:.14"/>';st=null;}});return o;};
 const path=Y=>{let d='';pts.forEach((p,i)=>{d+=(i?' L':'M')+X(p[0]).toFixed(1)+','+
  Y(p[1]).toFixed(1);});return d;};
 const last=pts[pts.length-1][1];
 if(el){
  // 2026-10-01: written for the taller viewBox - baseline 112, 96px of
  // drawing above it, the tick labels on the 20 below.
  const Y=v=>(112-(v/mx)*96);
  // 2026-10-01 (owner): the two captions used to sit ON the data at the
  // left edge, where the curve usually is. The reference line stays - a
  // reader needs to know where calm is - but its label moves to the right
  // margin, out of the way of the line it describes.
  const band=(v,c,l)=>'<line x1="6" y1="'+Y(v).toFixed(1)+'" x2="294" y2="'+
   Y(v).toFixed(1)+'" style="stroke:'+c+';opacity:.4" stroke-width="1" '+
   'stroke-dasharray="2 5"/><text x="294" y="'+(Y(v)-4).toFixed(1)+
   '" text-anchor="end" font-size="7.5" style="fill:'+c+';opacity:.85">'+
   l+'</text>';
  let ticks='';for(let k=0;k<=4;k++){const t=t0+sp*k/4,x=X(t).toFixed(1);
   const h=new Date(t*1000).getHours();
   ticks+='<line x1="'+x+'" y1="112" x2="'+x+'" y2="116" style="stroke:var(--border2)"/>'+
    '<text x="'+x+'" y="128" text-anchor="'+(k===0?'start':(k===4?'end':'middle'))+
    '" font-size="8" style="fill:var(--muted)">'+(k===4?'maintenant':h+'h')+'</text>';}
  const dp=path(Y);
  el.style.display='block';
  el.innerHTML='<defs><linearGradient id="ng" x1="0" y1="0" x2="0" y2="1">'+
   '<stop offset="0" stop-color="#8fc6ff" stop-opacity=".28"/>'+
   '<stop offset="1" stop-color="#8fc6ff" stop-opacity="0"/></linearGradient></defs>'+
   '<rect x="6" y="'+Y(mx).toFixed(1)+'" width="288" height="'+(Y(1.85)-Y(mx)).toFixed(1)+
   '" style="fill:var(--down);opacity:.05"/>'+
   bands(Y,6,106)+band(1.0,'var(--muted)','1,0\\u00d7 calme')+
   band(1.85,'var(--down)','1,85\\u00d7 tr\\u00e8s rapide')+
   '<line x1="6" y1="112" x2="294" y2="112" style="stroke:var(--border2)"/>'+ticks+
   '<path d="'+dp+' L'+X(t1).toFixed(1)+',112 L6,112 Z" fill="url(#ng)"/>'+
   '<path d="'+dp+'" fill="none" style="stroke:var(--accent-soft)" stroke-width="1.9" '+
   'stroke-linejoin="round"/>'+
   '<circle cx="'+X(t1).toFixed(1)+'" cy="'+Y(last).toFixed(1)+'" r="6" style="fill:var(--accent-soft);opacity:.25"/>'+
   // 2026-10-01: the dot marks WHERE, the header readout says WHAT.
   // Printing the same figure twice inside 80px is noise, not emphasis.
   '<circle cx="'+X(t1).toFixed(1)+'" cy="'+Y(last).toFixed(1)+
   '" r="3" style="fill:var(--accent-soft)" stroke="var(--surface)" '+
   'stroke-width="1.5"/>';
 }
 if(ms){
  const Ym=v=>(36-(v/mx)*30),dm=path(Ym);
  ms.style.display='block';
  ms.innerHTML=bands(Ym,2,36)+'<line x1="6" y1="'+Ym(1).toFixed(1)+'" x2="294" y2="'+
   Ym(1).toFixed(1)+'" style="stroke:var(--muted);opacity:.4" stroke-dasharray="3 4"/>'+
   '<path d="'+dm+' L'+X(t1).toFixed(1)+',40 L6,40 Z" style="fill:var(--accent-soft);opacity:.12"/>'+
   '<path d="'+dm+'" fill="none" style="stroke:var(--accent-soft)" stroke-width="1.6" '+
   'stroke-linejoin="round"/>'+
   '<circle cx="'+X(t1).toFixed(1)+'" cy="'+Ym(last).toFixed(1)+'" r="2.6" style="fill:var(--accent-soft)"/>';
 }
}
function drawDay(){
 const D=window._day,card=document.getElementById('daycard');
 if(!card||!D)return;
 const now=new Date();
 const d0=new Date(now.getFullYear(),now.getMonth(),now.getDate()).getTime()/1000,
  d1=d0+86400;
 const hm=t=>{const d=new Date(t*1000);return String(d.getHours()).padStart(2,'0')+':'+
  String(d.getMinutes()).padStart(2,'0');};
 const money=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 const ev=[];
 (D.ignored||[]).forEach(g=>{if(g[0]>=d0&&g[0]<=d1)ev.push({t:g[0],k:'ign',m:g[1]});});
 (D.trades||[]).forEach(t=>{if(t.t&&t.t>=d0&&t.t<=d1)ev.push({t:t.x||t.t,k:'tr',p:t.p,d:t.d});});
 const tr=ev.filter(e=>e.k==='tr'),ig=ev.filter(e=>e.k==='ign');
 const won=tr.filter(e=>e.p>0.005).length,tot=tr.reduce((a,e)=>a+e.p,0);
 // --- the summary, in plain words ---
 let sum;
 const M=MAN();
 (function(){const lb=document.getElementById('day-lbl');if(lb)lb.textContent=T('day_lbl');})();
 if(!tr.length&&!ig.length){
  sum=T('day_empty');
 }else{
  const parts=[],EN=LANG()==='en';
  if(tr.length)parts.push(tr.length+' trade'+(tr.length>1?'s':'')+
   (tr.length>1?T('day_of')+won+T('day_won')+(won>1&&!EN?'s':'')+')':(won?T('day_1won'):T('day_1lost'))));
  if(ig.length)parts.push(ig.length+' '+T('day_ign')[ig.length>1?1:0]);
  sum=T('day_since')+parts.join(T('day_and'))+'.'+
   (tr.length?T('day_total')+'<b class="'+sgn(tot)+'">'+money(tot)+'</b>.':'')+
   (!tr.length?T('day_cont'):'');
 }
 setH(document.getElementById('day-sum'),sum);
 // --- the day bar: morning / noon / evening, sun at "now" ---
 const X=t=>(10+Math.max(0,Math.min(1,(t-d0)/86400))*280);
 const xn=X(now.getTime()/1000);
 let bar='<defs><linearGradient id="dg" x1="0" y1="0" x2="1" y2="0">'+
  '<stop offset="0" stop-color="#5b6b8a" stop-opacity=".35"/>'+
  '<stop offset=".3" stop-color="#e8c55a" stop-opacity=".45"/>'+
  '<stop offset=".7" stop-color="#e8c55a" stop-opacity=".45"/>'+
  '<stop offset="1" stop-color="#5b6b8a" stop-opacity=".35"/></linearGradient></defs>'+
  '<rect x="10" y="14" width="280" height="6" rx="3" fill="url(#dg)"/>'+
  '<rect x="10" y="14" width="'+(xn-10).toFixed(1)+'" height="6" rx="3" style="fill:var(--accent-soft);opacity:.55"/>';
 ev.forEach(e=>{bar+='<circle cx="'+X(e.t).toFixed(1)+'" cy="17" r="3.2" style="fill:'+
  (e.k==='tr'?(e.p>=0?'var(--up)':'var(--down)'):'var(--muted)')+'"/>';});
 bar+='<circle cx="'+xn.toFixed(1)+'" cy="17" r="7" style="fill:var(--surface);stroke:var(--warn);stroke-width:2"/>'+
  '<circle cx="'+xn.toFixed(1)+'" cy="17" r="2.5" style="fill:var(--warn)"/>';
 [['matin',7],['midi',13],['soir',20]].forEach(([l,h])=>{bar+='<text x="'+X(d0+h*3600).toFixed(1)+
  '" y="32" text-anchor="middle" font-size="8" style="fill:var(--muted)">'+l+'</text>';});
 document.getElementById('daybar').innerHTML=bar;
 // --- the story, newest first ---
 const ico=(n,c)=>'<div class="evi" style="color:'+c+'"><svg class="ic ic-s"><use href="#'+n+'"/></svg></div>';
 ev.sort((a,b)=>b.t-a.t);
 setH(document.getElementById('day-list'),ev.slice(0,12).map(e=>{
  let i,txt;
  const who=T('who');
  if(e.k==='tr'){const buy=e.d==='BUY';
   if(e.p>=0){i=ico('i-check','var(--up)');
    txt=who+(buy?'achet\u00e9':'vendu')+' et '+T('won_v')+' <b class="pos">'+money(e.p)+'</b>.';}
   else{i=ico('i-x','var(--down)');
    txt=who+(buy?'achet\u00e9':'vendu')+' et '+T('lost_v')+' <b class="neg">$'+Math.abs(e.p).toFixed(2)+
     '</b>. \u00c7a arrive'+T('lost_tail');}}
  else if(e.m==='meteo'){i=ico('i-cloud','var(--warn)');txt=T('ev_meteo');}
  else{i=ico('i-eye','var(--muted2)');txt=T('ev_eye');}
  return '<div class="srow-ev">'+i+'<div style="flex:1;min-width:0">'+txt+'</div>'+
   '<span class="evt">'+hm(e.t)+'</span></div>';}).join('')||
  '<div class="sub" style="margin-top:4px">Rien \u00e0 raconter pour l\u2019instant.</div>');
 card.style.display='block';
 const md=document.getElementById('mxs-day');
 if(md)md.textContent=(tr.length?tr.length+' trade'+(tr.length>1?'s':''):(LANG()==='en'?'No trade yet':'Aucun trade pour l\u2019instant'))+
  (ig.length?' \u00b7 '+ig.length+' '+T('day_ign')[ig.length>1?1:0]:'');
 drawJourney(window._lastd);
}
function drawJourney(d){
 const el=document.getElementById('jsteps'),msg=document.getElementById('jmsg');
 if(!el||!msg||!d)return;
 const k=window._mxk||'none',D=window._day||{},now=Date.now()/1000;
 const open=d.open_list||[];
 const recent=(D.trades||[]).filter(t=>t.x&&now-t.x<1800).sort((a,b)=>b.x-a.x)[0];
 let step=1,txt='';
 const M=MAN();
 (function(){const lb=document.getElementById('jcard-lbl');if(lb)lb.textContent=T('jcard');
  const names=T('jsteps');
  el.querySelectorAll('.js span').forEach((sp,i)=>{if(names[i]&&sp.textContent!==names[i])sp.textContent=names[i];});})();
 const fmtP=v=>Math.abs(v).toFixed(2);
 if(open.length){step=3;const pl=open.reduce((a,p)=>a+(parseFloat(p.pl)||0),0);
  txt=T('j_open').replace('{pl}',Math.abs(pl)>0.005?' \u00b7 pour l\u2019instant <b class="'+sgn(pl)+'">'+(pl>=0?'+$':'-$')+fmtP(pl)+'</b>':'');}
 else if(recent){step=4;txt=(recent.p>=0?T('j_won'):T('j_lost')).replace('{p}',fmtP(recent.p));}
 else if(k==='ready'||k==='flip'||k==='forming'||k==='nogate'){step=2;
  txt=k==='forming'?T('j_forming'):(k==='flip'?T('j_flip'):T('j_ready'));}
 else{step=1;txt=k==='storm'?T('j_storm'):((k==='nervous'||k==='brisk')?T('j_nervous'):T('j_none'));}
 if(((d.ledger||{}).debt||0)>0.5&&step<3)txt+=T('j_debt');
 const jp=document.getElementById('jprog');
 if(jp){if(step===3&&open.length){const p=open[0];
   const e=parseFloat(p.e)||0,tp=parseFloat(p.tp)||0,lot=parseFloat(p.lot)||0,pl=parseFloat(p.pl)||0;
   let pct=null;if(e&&tp&&lot&&tp!==e){const px=e+(pl/lot)*(p.d==='A'?1:-1);
    pct=Math.max(0,Math.min(100,100*(px-e)/(tp-e)));}
   jp.style.display='block';
   jp.innerHTML='<div style="display:flex;justify-content:space-between;font-size:.72rem;'+
    'color:var(--muted2);margin-bottom:5px"><span>Chemin vers l\u2019objectif</span><span>'+
    (pct===null?'\u2014':pct.toFixed(0)+' %')+'</span></div>'+
    '<div style="background:var(--surface3);border-radius:99px;height:7px;overflow:hidden">'+
    '<div style="height:7px;border-radius:99px;width:'+(pct===null?0:pct.toFixed(0))+'%;'+
    'background:linear-gradient(90deg,var(--accent),var(--up));transition:width .8s"></div></div>';}
  else jp.style.display='none';}
 el.querySelectorAll('.js').forEach(x=>{const i=parseInt(x.dataset.i);
  x.classList.toggle('on',i===step);x.classList.toggle('done',false);});
 setH(msg,txt);
}
async function loadDay(){try{const r=await fetch(B+'day');if(!r.ok)return;
 window._day=await r.json();drawDay();drawNerv();}catch(e){}}
function drawSpark(){
 const c=(window._cvz==='90'&&window._c90&&window._c90.length>1)?window._c90
  :(window._cvz==='30'&&window._c30&&window._c30.length>1)?window._c30:(window._c7||[]);
 const el=document.getElementById('spark');
 if(c.length<2){
  // no curve, so no dates to put under it
  {const sd=document.getElementById('spkdates');if(sd)sd.style.display='none';}
  el.innerHTML='<text x="150" y="44" text-anchor="middle" style="fill:var(--muted)" '+
   'font-size="11">La courbe se dessinera apr\\u00e8s quelques trades</text>';
  return;}
 const mn=Math.min(...c,0),mx=Math.max(...c,0),sp=(mx-mn)||1;
 const X=i=>(12+(i/(c.length-1))*276),Y=v=>(66-((v-mn)/sp*50));
 const pts=c.map((v,i)=>[X(i),Y(v)]);
 let dp='M'+pts[0][0].toFixed(1)+','+pts[0][1].toFixed(1);
 for(let i=0;i<pts.length-1;i++){const p0=pts[Math.max(0,i-1)],p1=pts[i],
  p2=pts[i+1],p3=pts[Math.min(pts.length-1,i+2)];
  const c1x=p1[0]+(p2[0]-p0[0])/6,c1y=p1[1]+(p2[1]-p0[1])/6,
   c2x=p2[0]-(p3[0]-p1[0])/6,c2y=p2[1]-(p3[1]-p1[1])/6;
  dp+=' C'+c1x.toFixed(1)+','+c1y.toFixed(1)+' '+c2x.toFixed(1)+','+
   c2y.toFixed(1)+' '+p2[0].toFixed(1)+','+p2[1].toFixed(1);}
 // 2026-10-01 (owner): the dates the curve actually covers. Derived
 // from its own length - one point per day - so an account younger than
 // the selected range still gets true dates instead of a flattering one.
 {const sd=document.getElementById('spkdates');
  if(sd){const f=n=>{const x=new Date();x.setDate(x.getDate()-n);
    return String(x.getDate()).padStart(2,'0')+'/'+
      String(x.getMonth()+1).padStart(2,'0');};
   sd.innerHTML='<span>'+f(c.length-1)+'</span><span>'+f(0)+'</span>';
   sd.style.display='flex';}}
 const last=c[c.length-1],col=last>=0?'#2ecc71':'#ff5c5c';
 const y0=Y(0).toFixed(1),ex=pts[pts.length-1][0].toFixed(1),
  ey=pts[pts.length-1][1].toFixed(1);
 const fm=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(0);
 const iMx=c.indexOf(mx),iMn=c.indexOf(mn);
 const lab=(i,v,above,mk)=>'<text x="'+Math.min(280,Math.max(20,X(i))).toFixed(1)+
  '" y="'+(Y(v)+(above?-6:12)).toFixed(1)+'" text-anchor="middle" '+
  'style="fill:var(--muted)" font-size="9" font-weight="600">'+
  (mk||'')+fm(v)+'</text>';
 el.innerHTML=
  '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'+
  '<stop offset="0%" stop-color="'+col+'" stop-opacity=".32"/>'+
  '<stop offset="100%" stop-color="'+col+'" stop-opacity="0"/>'+
  '</linearGradient><filter id="gl" x="-50%" y="-50%" width="200%" '+
  'height="200%"><feGaussianBlur stdDeviation="2.4"/></filter></defs>'+
  '<line x1="12" y1="'+y0+'" x2="288" y2="'+y0+'" '+
  'stroke="rgba(255,255,255,.14)" stroke-width="1" stroke-dasharray="3 5"/>'+
  '<path d="'+dp+' L'+ex+',80 L12,80 Z" fill="url(#g)"/>'+
  '<path d="'+dp+'" fill="none" stroke="'+col+'" stroke-width="2.4" '+
  'stroke-linejoin="round" stroke-linecap="round"/>'+
  '<circle cx="'+ex+'" cy="'+ey+'" r="6" fill="'+col+'" opacity=".4" '+
  'filter="url(#gl)"/>'+
  '<circle cx="'+ex+'" cy="'+ey+'" r="3.2" fill="'+col+'" stroke="#121a25" '+
  'stroke-width="1.5"/>'+
  // 2026-10-01 (owner): the two labels were the PEAK and the TROUGH,
  // while the colour came from the END - so a red curve could shout
  // "+$13" (its high) at a member who is down, and the one number they
  // wanted, where they stand now, was the one not written. The end value
  // is labelled at the dot in the line's colour; the extremes are marked
  // with arrows so they read as extremes, and are dropped when they are
  // the end point anyway.
  (mx>0.005&&iMx<c.length-1?lab(iMx,mx,true,'\u2191'):'')+
  (mn<-0.005&&iMn<c.length-1?lab(iMn,mn,false,'\u2193'):'')+
  '<text x="'+Math.min(286,Math.max(24,+ex)).toFixed(1)+'" y="'+
  (+ey-9).toFixed(1)+'" text-anchor="middle" style="fill:'+col+
  '" font-size="11" font-weight="800">'+fm(last)+'</text>';
}
document.querySelectorAll('.cvc').forEach(b=>{b.onclick=()=>{
 window._cvz=b.dataset.c;
 document.querySelectorAll('.cvc').forEach(x=>{
  const on=x.dataset.c===window._cvz;
  x.style.background=on?'var(--surface3)':'transparent';
  x.style.borderColor=on?'var(--border2)':'var(--border)';
  x.style.color=on?'var(--text2)':'var(--muted2)';});
 drawSpark();ddCap(window._d);};});
document.querySelectorAll('.tfc').forEach(b=>{b.onclick=()=>{window._trF=b.dataset.f;window._trN=10;
 document.querySelectorAll('.tfc').forEach(x=>x.classList.toggle('on',x===b));
 if(window._d)render(window._d);};});
// 2026-09-27: pull-to-refresh indicator, honest first-load failure, a
// personal goal (this phone only) and the Messages inbox.
function ptrShow(){const p=document.getElementById('ptr');if(!p)return;p.classList.add('on');
 clearTimeout(window._ptrT);window._ptrT=setTimeout(()=>p.classList.remove('on'),1100);}
function retryLoad(){const b=document.querySelector('#firstfail button');
 if(b){b.textContent='Connexion...';b.disabled=true;}
 window._offFail=0;load().then(()=>{if(b){b.textContent='R\u00e9essayer';b.disabled=false;}});}
function goalKey(){return 'owlGoal:'+B;}
function drawGoal(d){
 let g=0;try{g=parseFloat(localStorage.getItem(goalKey())||'0')||0;}catch(e){}
 const el=document.getElementById('pgoal'),sub=document.getElementById('mygoal-sub');
 if(!el)return;
 if(!(g>0)){el.style.display='none';if(sub)sub.textContent='Choisir un solde \u00e0 atteindre';return;}
 const eq=d.equity||0,pc=Math.max(0,Math.min(100,eq/g*100));
 el.style.display='block';
 document.getElementById('pgoal-bar').style.width=pc.toFixed(1)+'%';
 if(eq>=g){document.getElementById('pgoal-t').textContent='Objectif atteint : $'+g.toFixed(0)+' \U0001f389';
  document.getElementById('pgoal-s').textContent='Bravo. Touchez pour en choisir un nouveau.';}
 else{document.getElementById('pgoal-t').textContent=Math.round(pc)+' % du chemin vers $'+g.toFixed(0);
  document.getElementById('pgoal-s').textContent='$'+eq.toFixed(2)+' aujourd\u2019hui \u00b7 il reste $'+(g-eq).toFixed(2);}
 if(sub)sub.textContent='$'+g.toFixed(0)+' \u00b7 '+Math.round(pc)+' % atteint';
}
async function myGoal(){
 let g=0;try{g=parseFloat(localStorage.getItem(goalKey())||'0')||0;}catch(e){}
 const v=await sheet('<h3>Mon objectif</h3><p>Un solde que vous aimeriez atteindre. Il reste sur ce t\u00e9l\u00e9phone ; personne d\u2019autre ne le voit.</p>'+
  '<input id="shgoal" type="number" inputmode="decimal" min="1" step="1" placeholder="Par exemple 500" value="'+(g>0?g:'')+'" '+
  'style="width:100%;box-sizing:border-box;border:1px solid var(--border2);background:var(--surface2);color:var(--text);border-radius:12px;padding:12px 14px;font-size:1.05rem;margin-bottom:10px">'+
  '<button class="shbtn shmain" onclick="_shDone(document.getElementById(&#39;shgoal&#39;).value)">Enregistrer</button>'+
  (g>0?'<button class="shbtn shghost" onclick="_shDone(&#39;0&#39;)">Retirer l\u2019objectif</button>':'')+
  '<button class="shbtn shghost" onclick="_shDone(null)">Annuler</button>');
 if(v===null)return;
 const n=parseFloat(v)||0;
 try{if(n>0)localStorage.setItem(goalKey(),String(n));else localStorage.removeItem(goalKey());}catch(e){}
 if(window._d)drawGoal(window._d);
 toast(n>0?'Objectif enregistr\u00e9 : $'+n.toFixed(0):'Objectif retir\u00e9',2200);
}
function inboxKey(){return 'owlInboxSeen:'+B;}
function inboxWhen(t){const d=new Date(t*1000),n=new Date();
 const hm=String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
 const dd=Math.round((new Date(n.getFullYear(),n.getMonth(),n.getDate())-new Date(d.getFullYear(),d.getMonth(),d.getDate()))/86400000);
 return (dd===0?'aujourd\u2019hui':dd===1?'hier':String(d.getDate()).padStart(2,'0')+'/'+String(d.getMonth()+1).padStart(2,'0'))+' '+hm;}
async function loadInbox(){
 try{const r=await fetch(B+'inbox');if(!r.ok)return;const j=await r.json();window._inbox=j.items||[];}catch(e){return;}
 let seen=0;try{seen=parseInt(localStorage.getItem(inboxKey())||'0',10)||0;}catch(e){}
 const it=window._inbox,nw=it.filter(x=>x.t>seen).length;
 const sub=document.getElementById('inbox-sub'),dot=document.getElementById('inbox-dot');
 if(!sub)return;
 if(!it.length)sub.textContent='Aucun message pour l\u2019instant';
 else sub.textContent=(nw?nw+' nouveau'+(nw>1?'x':'')+' \u00b7 ':'')+'dernier : '+inboxWhen(it[0].t);
 if(dot)dot.style.display=nw?'inline-block':'none';
 const hb=document.getElementById('hbell-n');if(hb){hb.textContent=nw>9?'9+':String(nw);hb.style.display=nw?'flex':'none';}
 try{if(navigator.setAppBadge){if(nw)navigator.setAppBadge(nw);else if(navigator.clearAppBadge)navigator.clearAppBadge();}}catch(e){}
}
function inboxKind(x){const t=(x.title||'')+' '+(x.body||'');
 if(/signal/i.test(t))return 'sig';if(/trade (termin|closed)/i.test(t))return 'tr';if(/bilan|semaine|your week|daily review/i.test(t))return 'bil';return 'oth';}
function inboxList(){
 const it=window._inbox||[],f=window._ibF||'all',q=(window._ibQ||'').toLowerCase();
 const en=LANG()==='en';
 const ic=k=>k==='bil'?['i-calendar','var(--accent-soft)']:k==='sig'?['i-activity','var(--up)']:k==='tr'?['i-chart','var(--text3)']:['i-bell','var(--warn)'];
 const esc=x=>String(x||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
 // 2026-10-02 (owner): the icon square carries the picture; a title that
 // starts with an emoji wrapped to three lines for nothing
 const stripEmo=t=>String(t||'').replace(/^[\s\p{Extended_Pictographic}\uFE0F\u200D]+/u,'');
 const L=it.filter(x=>(f==='all'||inboxKind(x)===f)&&(!q||((x.title||'')+' '+(x.body||'')).toLowerCase().indexOf(q)>=0));
 const el=document.getElementById('ib-list');if(!el)return;
 el.innerHTML=L.length?L.map(x=>{const [n,c]=ic(inboxKind(x));
  return '<div class="srow-ev" style="align-items:flex-start"><div class="evi" style="color:'+c+'"><svg class="ic ic-s"><use href="#'+n+'"/></svg></div>'+
  '<div style="flex:1;min-width:0"><div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline">'+
  '<b style="font-size:.9rem;font-weight:600">'+esc(stripEmo(x.title))+'</b><span style="font-size:.7rem;color:var(--muted);white-space:nowrap">'+inboxWhen(x.t)+'</span></div>'+
  '<div style="font-size:.84rem;color:var(--muted2);line-height:1.4;margin-top:2px">'+esc(x.body)+'</div></div>'+
  '<button onclick="inboxDel('+x.t+')" aria-label="'+(en?'Delete':'Supprimer')+'" style="flex:none;border:0;background:transparent;color:var(--muted);padding:2px 4px;font-size:1rem;line-height:1">\u00d7</button></div>';}).join('')
  :'<div class="empty"><p>'+(en?'Nothing here.':'Rien ici.')+'</p></div>';
 document.querySelectorAll('.ibf').forEach(b=>b.classList.toggle('on',b.dataset.f===f));
}
async function inboxDel(t){
 try{await fetch(B+'inbox_del',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'t='+t});}catch(e){}
 window._inbox=(window._inbox||[]).filter(x=>x.t!==t);inboxList();
}
function inboxSheet(){
 const it=window._inbox||[],en=LANG()==='en';
 const F=[['all',en?'All':'Tous'],['tr','Trades'],['bil',en?'Reviews':'Bilans'],['sig',en?'Signals':'Signaux']];
 let h='<h3>Messages</h3>';
 if(!it.length)h+='<div class="empty"><p>'+(en?'No message yet. Enable notifications to receive the daily review.':'Aucun message pour l\u2019instant. Activez les notifications pour recevoir le bilan du jour.')+'</p></div>';
 else h+='<div style="display:flex;gap:6px;overflow-x:auto;padding:2px 0 8px;scrollbar-width:none">'+F.map(([k,l])=>'<button class="tfc ibf'+(k===(window._ibF||'all')?' on':'')+'" data-f="'+k+'" onclick="window._ibF=this.dataset.f;inboxList()">'+l+'</button>').join('')+'</div>'+
  '<input id="ib-q" type="search" placeholder="'+(en?'Search\u2026':'Rechercher\u2026')+'" oninput="window._ibQ=this.value;inboxList()" style="width:100%;box-sizing:border-box;border:1px solid var(--border2);background:var(--surface2);color:var(--text);border-radius:12px;padding:9px 12px;font-size:.9rem;margin-bottom:6px">'+
  '<div id="ib-list" style="max-height:52vh;overflow-y:auto;margin:0 -2px"></div>';
 h+='<button class="shbtn shghost" onclick="_shDone(1)">Fermer</button>';
 try{if(it.length)localStorage.setItem(inboxKey(),String(it[0].t));}catch(e){}
 window._ibF='all';window._ibQ='';
 sheet(h);
 // 2026-09-28 (owner): "Tous is selected but no data" - sheet() renders
 // asynchronously (it waits after a previous close), so the list must be
 // filled once #ib-list exists, not right away
 (function tryList(n){if(document.getElementById('ib-list'))inboxList();else if(n>0)setTimeout(()=>tryList(n-1),120);})(15);
 const dot=document.getElementById('inbox-dot');if(dot)dot.style.display='none';const hb2=document.getElementById('hbell-n');if(hb2)hb2.style.display='none';
 const sub=document.getElementById('inbox-sub');if(sub&&it.length)sub.textContent=(en?'last: ':'dernier : ')+inboxWhen(it[0].t);
 try{if(navigator.clearAppBadge)navigator.clearAppBadge();}catch(e){}
}
// 2026-09-27: "Depuis le debut" (worker since_start) and the gentle badges.
const MON=['janv.','f\u00e9vr.','mars','avr.','mai','juin','juil.','ao\u00fbt','sept.','oct.','nov.','d\u00e9c.'];
function renderSince(d){
 const S=d.since_start,el=document.getElementById('since');if(!el)return;
 if(!S||!S.n){el.style.display='none';return;}
 el.style.display='block';
 const money=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 const fd=k=>{const m=/(\d{4})-(\d\d)-(\d\d)/.exec(k||'');return m?parseInt(m[3],10)+' '+MON[parseInt(m[2],10)-1]+' '+m[1]:k;};
 const bm=S.best_month;
 setH(document.getElementById('since-t'),T('since')+fd(S.first||S.era)+'</b>'+(S.days>1?' \u2014 '+S.days+' jours':'')+
  '. R\u00e9sultat depuis le d\u00e9but : <b class="'+sgn(S.net)+'">'+money(S.net)+'</b>.');
 setH(document.getElementById('since-g'),
  '<div><b>'+S.n+'</b><span>trade'+(S.n>1?'s':'')+'</span></div>'+
  '<div><b>'+Math.round(S.won/Math.max(1,S.n)*100)+'\u202f%</b><span>gagn\u00e9s</span></div>'+
  '<div><b class="'+(bm?sgn(bm.p):'neu')+'">'+(bm?money(bm.p):'\u2014')+'</b><span>'+(bm?'meilleur mois \u00b7 '+MON[parseInt(bm.ym.slice(5,7),10)-1]:'meilleur mois')+'</span></div>');
}
const BADGES=[
 ['first','Premier trade','Le robot a agi pour vous','i-chart'],
 ['t10','10 trades','Le rythme est pris','i-activity'],
 ['t50','50 trades','Une vraie habitude','i-activity'],
 ['t100','100 trades','Un cap','i-activity'],
 ['gweek','Semaine verte','Une semaine termin\u00e9e dans le vert','i-check'],
 ['goal','Objectif atteint','Votre objectif personnel','i-target'],
 ['d30','30 jours','Un mois avec le robot','i-calendar'],
 ['d100','100 jours','Une saison avec le robot','i-calendar']];
function badgeKey(){return 'owlBadges:'+B;}
function unlockedNow(d){
 const S=d.since_start||{},n=S.n||0,u={};
 if(n>=1)u.first=1;if(n>=10)u.t10=1;if(n>=50)u.t50=1;if(n>=100)u.t100=1;
 if((S.days||0)>=30)u.d30=1;if((S.days||0)>=100)u.d100=1;
 let g=0;try{g=parseFloat(localStorage.getItem(goalKey())||'0')||0;}catch(e){}
 if(g>0&&(d.equity||0)>=g)u.goal=1;
 const M=d.months||{},wk={};
 Object.keys(M).forEach(k=>(M[k]||[]).forEach(x=>{const m=/(\d{4})-(\d\d)-(\d\d)/.exec(x.d||'');if(!m)return;
  const t=new Date(Date.UTC(+m[1],+m[2]-1,+m[3]));t.setUTCDate(t.getUTCDate()-((t.getUTCDay()+6)%7));
  const key=t.toISOString().slice(0,10);wk[key]=(wk[key]||0)+(x.p||0);}));
 const now=new Date(),cw=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),now.getUTCDate()));cw.setUTCDate(cw.getUTCDate()-((cw.getUTCDay()+6)%7));
 if(Object.keys(wk).some(k=>k<cw.toISOString().slice(0,10)&&wk[k]>0.005))u.gweek=1;
 return u;
}
function checkBadges(d){
 const u=unlockedNow(d);let st=null;
 try{st=JSON.parse(localStorage.getItem(badgeKey())||'null');}catch(e){}
 const first=!st;st=st||{};let fresh=[];
 Object.keys(u).forEach(k=>{if(!st[k]){st[k]=Math.floor(Date.now()/1000);if(!first)fresh.push(k);}});
 try{localStorage.setItem(badgeKey(),JSON.stringify(st));}catch(e){}
 window._badges=st;
 const sub=document.getElementById('steps-sub');
 if(sub)sub.textContent=Object.keys(st).length+' sur '+BADGES.length+' \u00e9tapes';
 if(fresh.length){const b=BADGES.find(x=>x[0]===fresh[0]);
  if(b)toast('Nouvelle \u00e9tape : <b>'+b[1]+'</b> \U0001f389',3200);
  try{navigator.vibrate&&navigator.vibrate([10,40,10]);}catch(e){}}
}
function stepsSheet(){
 const st=window._badges||{};
 const fd=t=>{const d=new Date(t*1000);return String(d.getDate()).padStart(2,'0')+'/'+String(d.getMonth()+1).padStart(2,'0');};
 const n=Object.keys(st).length;
 const en=LANG()==='en';
 let h='<h3>'+(en?'My journey':'Mon parcours')+'</h3><p>'+(n?n+' \u00e9tape'+(n>1?'s':'')+' sur '+BADGES.length+'. Les autres viendront avec le temps.':'Vos premi\u00e8res \u00e9tapes appara\u00eetront ici d\u00e8s que le robot aura agi pour vous.')+'</p>';
 h+='<div class="bdg">'+BADGES.map(([k,l,dsc,ic])=>'<div class="stpi'+(st[k]?'':' off')+'"><div class="stpc"><svg class="ic ic-s"><use href="#'+ic+'"/></svg></div><div style="min-width:0"><b>'+l+'</b><span>'+(st[k]?'le '+fd(st[k]):dsc)+'</span></div></div>').join('')+'</div>';
 if(window._tlHtml)h+='<div class="lbl" style="margin:16px 0 6px">'+(en?'Moments':'Les moments')+'</div>'+window._tlHtml;
 h+='<button class="shbtn shghost" onclick="_shDone(1)">Fermer</button>';
 sheet(h);
}
// swipe down on a sheet closes it (only when its content is not scrolled)
(function(){const sh=document.getElementById('sheet');if(!sh)return;let y0=null,dy=0;
 sh.addEventListener('touchstart',e=>{y0=e.touches[0].clientY;dy=0;
  if(sh.scrollTop>0){y0=null;return;}   // 2026-09-27: the sheet scrolls itself now
  let el=e.target;while(el&&el!==sh){if(el.scrollTop>0){y0=null;break;}el=el.parentElement;}},{passive:true});
 sh.addEventListener('touchmove',e=>{if(y0==null)return;dy=e.touches[0].clientY-y0;
  if(dy>0){sh.style.transition='none';sh.style.transform='translateY('+dy+'px)';}},{passive:true});
 sh.addEventListener('touchend',()=>{if(y0==null)return;sh.style.transition='';
  if(dy>90&&window._shOpen)window._shDone(null);else sh.style.transform='translateY(0)';y0=null;dy=0;});})();
function tradeSheet(i){
 if(window._lpFired){window._lpFired=0;return;}   // a long-press copied the row, no sheet
 const x=(window._tr||[])[i];
 if(!x)return;
 const L=(a,b)=>'<div style="display:flex;justify-content:'+
  'space-between;padding:10px 2px;border-bottom:1px solid var(--border);'+
  'font-size:.95rem"><span style="color:var(--muted2)">'+a+
  '</span><b>'+b+'</b></div>';
 const _m2=/^(\d\d)\/(\d\d) (\d\d):(\d\d)$/.exec(x.w||'');let _tx=0;
 if(_m2){const n=new Date();let y=n.getUTCFullYear();if(parseInt(_m2[2])>n.getUTCMonth()+1)y--;
  _tx=Math.round(Date.UTC(y,parseInt(_m2[2])-1,parseInt(_m2[1]),parseInt(_m2[3]),parseInt(_m2[4]))/1000);}
 sheet('<h3 style="display:flex;align-items:center;gap:8px">'+
  (x.dir==='A'?'<span style="color:var(--up)">&#9650;</span> Achat'
   :'<span style="color:var(--down)">&#9660;</span> Vente')+
  (x.k&&x.k!=='page'?'<span class="pill'+(x.k==='soldat'?' pill-w':'')+
   '">'+x.k+'</span>':'')+'</h3>'+
  '<div id="tstory" style="font-size:.92rem;line-height:1.5;color:var(--text);margin:6px 0 12px">'+
  '<span style="color:var(--muted)">Un instant\u2026</span></div>'+
  '<svg id="tspark" viewBox="0 0 300 80" style="width:100%;height:80px;display:none;margin:-4px 0 10px"></svg>'+
  L('R&eacute;sultat','<span class="'+(sgn(x.p))+'">'+
   (x.p>=0?'+$':'-$')+Math.abs(x.p).toFixed(2)+'</span>')+
  (x.lot?L('Taille',x.lot.toFixed(2)+' lot'):'')+
  (x.ep!=null?L('Entr&eacute;e',x.ep.toFixed(2)):'')+
  (x.xp!=null?L('Sortie',x.xp.toFixed(2)):'')+
  (x.dur!=null?L('Dur&eacute;e',fdur(x.dur)):'')+
  L('Quand',x.w)+
  (function(){
   // 2026-10-01: the big picture at entry AND at exit. The interesting
   // case is when they differ - the trade outlived the context it was
   // taken in - so both lines show rather than only the entry.
   const tf=x.tf;if(!tf)return '';
   const dir=(x.dir==='A')?1:-1;
   // 2026-10-02 (owner: "why are they all red???"). The colour was right
   // and the WORD was wrong. On a sell with all three timeframes up this
   // printed "M15 haut" in RED - because red here means "against this
   // trade", while red everywhere else in the app means "down". One token
   // carrying two opposite meanings reads as a bug even when the data is
   // correct. The arrow is the DIRECTION and stays neutral; the word is
   // the RELATIONSHIP to this trade and carries the colour. Nothing is
   // lost and nothing contradicts itself.
   const en2=LANG()==='en';
   const arw=t=>t===1?'\u25b2':(t===-1?'\u25bc':'\u2014');
   const rel=t=>(t==null||t===0)?(en2?'no trend':'sans tendance')
    :((t===dir)?(en2?'with':'avec'):(en2?'against':'contre'));
   const line=s=>['m15','h1','h4'].map(k=>k.toUpperCase()+
    ' <span style="color:var(--muted)">'+arw(s[k])+'</span> '+
    '<span style="color:'+tfSide(s[k],dir)+'">'+rel(s[k])+'</span>')
    .join('&nbsp;&nbsp; ');
   let h=tf.e?L('Grandes unit\u00e9s \u00e0 l\u2019entr\u00e9e',line(tf.e)):'';
   if(tf.x)h+=L('\u2026 \u00e0 la sortie',line(tf.x));
   return h;})()+
  (function(){const m=/^(\d\d)\/(\d\d) (\d\d):(\d\d)$/.exec(x.w||'');
   if(!m)return '';const n=new Date();let y=n.getUTCFullYear();
   if(parseInt(m[2])>n.getUTCMonth()+1)y--;
   // x.w is the CLOSE time of the deal; the entry is dur minutes earlier
   const tx=Math.round(Date.UTC(y,parseInt(m[2])-1,parseInt(m[1]),
    parseInt(m[3]),parseInt(m[4]))/1000);
   const t=(x.dur!=null)?tx-Math.round(x.dur*60):tx;
   const q=B+'chart?t='+t+'&x='+tx+
    (x.ep!=null?'&ep='+x.ep:'')+(x.xp!=null?'&xp='+x.xp:'')+
    '&d='+encodeURIComponent(x.dir||'')+'&p='+x.p;
   return '<a class="shbtn shghost" style="display:flex;align-items:center;'+
    'justify-content:center;gap:8px;text-decoration:none" href="'+q+'">'+
    '<svg class="ic ic-s"><use href="#i-chart"/></svg>Voir sur le graphique</a>';})()+
  '<button class="shbtn shmain" onclick="_shDone(1)">Fermer</button>');
 tradeStory(_tx,x);
 tradeSpark(_tx,x);
}
// ---- batch 18 (2026-09-27) ----
// long-press on a trade row copies its one-line summary
function lpStart(ev,el){lpEnd();window._lpT=setTimeout(()=>{
 const x=(window._tr||[])[el.dataset.i];if(!x)return;
 const txt=(x.dir==='A'?'Achat':'Vente')+(x.lot?' '+x.lot.toFixed(2)+' lot':'')+' \u00b7 '+
  (x.p>=0?'+$':'-$')+Math.abs(x.p).toFixed(2)+' \u00b7 '+x.w+' UTC';
 window._lpFired=1;
 try{navigator.vibrate&&navigator.vibrate(14);}catch(e){}
 (navigator.clipboard?navigator.clipboard.writeText(txt):Promise.reject()).then(
  ()=>toast('<div class="evi" style="color:var(--accent-soft)"><svg class="ic ic-s"><use href="#i-check"/></svg></div><div style="flex:1">Copi\u00e9 : '+txt+'</div>',2600),
  ()=>toast(txt,3200));},550);}
function lpEnd(){if(window._lpT){clearTimeout(window._lpT);window._lpT=null;}}
// 2026-09-27: long-press two days to compare them side by side
function lpDayStart(ev,lab){lpEnd();window._lpT=setTimeout(()=>{window._lpFired=1;
 try{navigator.vibrate&&navigator.vibrate(14);}catch(e){}daySelect(lab);},550);}
function daySelect(lab){
 if(!window._cmpA||window._cmpA===lab){window._cmpA=lab;
  toast('<div class="evi" style="color:var(--accent-soft)"><svg class="ic ic-s"><use href="#i-calendar"/></svg></div><div style="flex:1">'+T('cmp_pick').replace('{d}','<b>'+lab+'</b>')+'</div>',4200);return;}
 const a=window._cmpA;window._cmpA=null;compareDays(a,lab);
}
function compareDays(a,b){
 const S=l=>{const tr=((window._dtr||{})[l]||[]);const row=(window._days||[]).find(x=>x.d===l);
  const p=row?row.p:tr.reduce((s,t)=>s+t.p,0);const won=tr.filter(t=>t.p>0.005).length;
  const best=tr.length?Math.max(...tr.map(t=>t.p)):null,worst=tr.length?Math.min(...tr.map(t=>t.p)):null;
  return {l,p,n:tr.length,won,best,worst};};
 const A=S(a),Bq=S(b),money=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 const col=(x)=>'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:14px;padding:12px 10px;text-align:center">'+
  '<div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">'+x.l+'</div>'+
  '<b style="display:block;font-size:1.35rem;margin:4px 0" class="'+sgn(x.p)+'">'+money(x.p)+'</b>'+
  '<div style="font-size:.8rem;color:var(--muted2);line-height:1.5">'+x.n+' trade'+(x.n>1?'s':'')+(x.n?' \u00b7 '+x.won+' \u2713':'')+
  (x.best!=null?'<br>'+T('cmp_best')+' <span class="'+sgn(x.best)+'">'+money(x.best)+'</span>':'')+
  (x.worst!=null&&x.n>1?'<br>'+T('cmp_worst')+' <span class="'+sgn(x.worst)+'">'+money(x.worst)+'</span>':'')+'</div></div>';
 const diff=A.p-Bq.p;
 const verdict=Math.abs(diff)<0.5?T('cmp_even'):(diff>0?T('cmp_better'):T('cmp_better')).replace('{a}','<b>'+(diff>0?A.l:Bq.l)+'</b>').replace('{x}','<b>$'+Math.abs(diff).toFixed(2)+'</b>');
 sheet('<h3>'+T('cmp_title')+'</h3><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:6px 0 12px">'+col(A)+col(Bq)+'</div>'+
  '<p style="color:var(--text)">'+verdict+'</p><button class="shbtn shghost" onclick="_shDone(1)">Fermer</button>');
}
// "Resume du jour" shortcut: today's line as text, shared or copied
function resumeShare(){
 const d=window._d;if(!d)return;const en=LANG()==='en';
 const lab=dayLabel(new Date()),tr=((window._dtr||{})[lab]||[]);
 const t=(typeof d.today==='number')?d.today:0;
 const txt='OwlNest \u00b7 '+lab+' \u00b7 '+(t>=0?'+$':'-$')+Math.abs(t).toFixed(2)+(en?' today':' aujourd\u2019hui')+' \u00b7 '+tr.length+' trade'+(tr.length>1?'s':'')+' \u00b7 $'+(d.equity||0).toFixed(2);
 const go=async()=>{try{if(navigator.share){await navigator.share({text:txt});return;}}catch(e){}
  try{await navigator.clipboard.writeText(txt);toast((en?'Copied: ':'Copi\u00e9 : ')+txt,3000);}catch(e){toast(txt,5000);}};
 toast('<div style="flex:1">'+txt+'</div><button class="shbtn shmain" style="width:auto;margin:0;padding:8px 12px;font-size:.82rem;min-height:0" onclick="(window._rsGo||function(){})()">'+(en?'Share':'Partager')+'</button>',12000);
 window._rsGo=go;
}
const FRD=['dim','lun','mar','mer','jeu','ven','sam'];
function dayLabel(dt){return FRD[dt.getUTCDay()]+' '+String(dt.getUTCDate()).padStart(2,'0')+'/'+String(dt.getUTCMonth()+1).padStart(2,'0');}
function goDay(){
 const v=(document.getElementById('tdate')||{}).value;if(!v){toast('Choisissez une date',1800);return;}
 const m=/^(\d{4})-(\d\d)-(\d\d)$/.exec(v);if(!m)return;
 const lab=dayLabel(new Date(Date.UTC(+m[1],+m[2]-1,+m[3])));
 const has=((window._dtr||{})[lab]||[]).length||(window._days||[]).some(x=>x.d===lab);
 if(has)dayx(lab);else toast('Aucun trade le '+m[3]+'/'+m[2]+'.',2200);
}
// tiny cumulative curve of one day's trades (day sheet)
function daySpark(tr){
 if(!tr||tr.length<2)return '';
 let c=0;const pts=tr.map(t=>{c+=t.p;return c;});
 const mn=Math.min(0,...pts),mx=Math.max(0,...pts),sp=(mx-mn)||1;
 const X=i=>10+(i/(pts.length-1))*280,Y=v=>52-((v-mn)/sp)*40;
 const col=c>=0?'var(--up)':'var(--down)';
 let d='M10,'+Y(0).toFixed(1);pts.forEach((v,i)=>{d+=' L'+X(i).toFixed(1)+','+Y(v).toFixed(1);});
 return '<svg viewBox="0 0 300 64" style="width:100%;height:64px;display:block;margin:0 0 6px">'+
  '<line x1="10" y1="'+Y(0).toFixed(1)+'" x2="290" y2="'+Y(0).toFixed(1)+'" style="stroke:var(--border2)" stroke-dasharray="3 4"/>'+
  '<path d="'+d+'" fill="none" style="stroke:'+col+'" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>'+
  pts.map((v,i)=>'<circle cx="'+X(i).toFixed(1)+'" cy="'+Y(v).toFixed(1)+'" r="3" style="fill:'+(tr[i].p>=0?'var(--up)':'var(--down)')+'"/>').join('')+
  '<text x="10" y="62" font-size="8" style="fill:var(--muted)">'+tr[0].t+'</text>'+
  '<text x="290" y="62" font-size="8" text-anchor="end" style="fill:var(--muted)">'+tr[tr.length-1].t+'</text></svg>';
}
// price path of one trade (trade sheet), from the chart feed's kept candles
async function tradeSpark(tx,x){
 // 2026-09-27: 30 min around the trade as real candles, entry/exit marked
 const el=document.getElementById('tspark');if(!el||!tx)return;
 const t0=((x.dur!=null)?tx-Math.round(x.dur*60):tx-600)-900,t1=tx+900;
 let D=null;try{const r=await fetch(B+'chart_data');if(r.ok)D=await r.json();}catch(e){return;}
 const C=((D&&D.candles)||[]).filter(k=>k[0]>=t0&&k[0]<=t1);
 if(C.length<4)return;
 const te=(x.dur!=null)?tx-Math.round(x.dur*60):tx;
 const lo=Math.min(...C.map(k=>k[3]),x.ep||Infinity,x.xp||Infinity),hi=Math.max(...C.map(k=>k[2]),x.ep||-Infinity,x.xp||-Infinity),sp=(hi-lo)||1;
 const X=t=>10+((t-C[0][0])/Math.max(1,C[C.length-1][0]-C[0][0]))*280,Y=v=>68-((v-lo)/sp)*56;
 const w=Math.max(1.6,Math.min(6,280/C.length*0.62));
 const up=x.p>=0,col=up?'var(--up)':'var(--down)';
 let h='';
 C.forEach(k=>{const cx=X(k[0]),o=k[1],c=k[4],g=c>=o;
  h+='<line x1="'+cx.toFixed(1)+'" y1="'+Y(k[2]).toFixed(1)+'" x2="'+cx.toFixed(1)+'" y2="'+Y(k[3]).toFixed(1)+'" style="stroke:'+(g?'var(--up)':'var(--down)')+';opacity:.7" stroke-width="1"/>'+
   '<rect x="'+(cx-w/2).toFixed(1)+'" y="'+Y(Math.max(o,c)).toFixed(1)+'" width="'+w.toFixed(1)+'" height="'+Math.max(1,Y(Math.min(o,c))-Y(Math.max(o,c))).toFixed(1)+'" rx="1" style="fill:'+(g?'var(--up)':'var(--down)')+';opacity:.85"/>';});
 const hl=(v,lab,c)=>(v==null?'':'<line x1="10" y1="'+Y(v).toFixed(1)+'" x2="290" y2="'+Y(v).toFixed(1)+'" style="stroke:'+c+';opacity:.5" stroke-dasharray="3 4"/>'+
  '<text x="290" y="'+(Y(v)-3).toFixed(1)+'" font-size="8" text-anchor="end" style="fill:'+c+'">'+lab+'</text>');
 const xe=X(Math.max(C[0][0],te)),xx=X(Math.min(C[C.length-1][0],tx));
 h+=hl(x.ep,LANG()==='en'?'entry':'entr\u00e9e','var(--muted2)')+hl(x.xp,LANG()==='en'?'exit':'sortie',col);
 if(x.ep!=null&&x.xp!=null){h+='<line x1="'+xe.toFixed(1)+'" y1="'+Y(x.ep).toFixed(1)+'" x2="'+xx.toFixed(1)+'" y2="'+Y(x.xp).toFixed(1)+'" style="stroke:'+col+'" stroke-width="1.6" stroke-dasharray="4 4"/>'+
  '<circle cx="'+xe.toFixed(1)+'" cy="'+Y(x.ep).toFixed(1)+'" r="3.2" style="fill:var(--text)"/><circle cx="'+xx.toFixed(1)+'" cy="'+Y(x.xp).toFixed(1)+'" r="3.6" style="fill:'+col+'"/>';}
 const ft=t=>{const d=new Date(t*1000);return String(d.getUTCHours()).padStart(2,'0')+':'+String(d.getUTCMinutes()).padStart(2,'0');};
 h+='<text x="10" y="79" font-size="8" style="fill:var(--muted)">'+ft(C[0][0])+'</text><text x="290" y="79" font-size="8" text-anchor="end" style="fill:var(--muted)">'+ft(C[C.length-1][0])+' UTC</text>';
 el.innerHTML=h;el.style.display='block';
}
// "Ma journee" share image
function shareDay(){
 const d=window._d;if(!d)return;
 const lab=dayLabel(new Date());const tr=((window._dtr||{})[lab]||[]).slice(-12);
 const today=(typeof d.today==='number')?d.today:0,up=today>=0;
 const W=720,H=900,c=document.createElement('canvas');c.width=W;c.height=H;
 const g=c.getContext('2d');
 const rr=(x,y,w,h,r)=>{g.beginPath();g.roundRect(x,y,w,h,r);};
 const bg=g.createLinearGradient(0,0,0,H);bg.addColorStop(0,'#0f2740');bg.addColorStop(.45,'#0b0f14');bg.addColorStop(1,'#0b0f14');
 g.fillStyle=bg;g.fillRect(0,0,W,H);
 rr(56,52,60,60,16);g.fillStyle='#0d1117';g.fill();
 [76,96].forEach(cx=>{g.beginPath();g.arc(cx,76,9.5,0,Math.PI*2);g.fillStyle='#f0b43c';g.fill();
  g.beginPath();g.arc(cx,76,4,0,Math.PI*2);g.fillStyle='#121212';g.fill();});
 g.beginPath();g.moveTo(86,84);g.lineTo(80,98);g.lineTo(92,98);g.closePath();g.fillStyle='#c87828';g.fill();
 g.textAlign='left';g.fillStyle='#e8eef4';g.font='bold 34px Inter, system-ui, sans-serif';g.fillText('OwlNest',132,84);
 g.fillStyle='#8a9bb0';g.font='22px Inter, system-ui, sans-serif';g.fillText('Ma journ\u00e9e \u00b7 '+lab+' \u00b7 '+(d.name||''),132,112);
 g.textAlign='center';g.fillStyle=Math.abs(today)<0.005?'#c6d3df':(up?'#2ecc71':'#ff5c5c');
 g.font='bold 104px Inter, system-ui, sans-serif';g.fillText((up?'+$':'-$')+Math.abs(today).toFixed(2),W/2,246);
 g.fillStyle='#8a9bb0';g.font='20px Inter, system-ui, sans-serif';
 g.fillText(tr.length?(tr.length+' trade'+(tr.length>1?'s':'')+' aujourd\u2019hui'):'aucun trade aujourd\u2019hui',W/2,280);
 // curve card
 rr(48,318,W-96,200,26);g.fillStyle='#121a25';g.fill();g.strokeStyle='#1f2a38';g.lineWidth=1.5;g.stroke();
 if(tr.length>=2){let cum=0;const pts=tr.map(t=>{cum+=t.p;return cum;});
  const mn=Math.min(0,...pts),mx=Math.max(0,...pts),sp=(mx-mn)||1;
  const X=i=>84+(i/(pts.length-1))*(W-168),Y=v=>488-((v-mn)/sp)*130;
  g.beginPath();g.moveTo(84,Y(0));pts.forEach((v,i)=>g.lineTo(X(i),Y(v)));
  g.strokeStyle=up?'#2ecc71':'#ff5c5c';g.lineWidth=5;g.lineJoin='round';g.lineCap='round';g.stroke();
  g.setLineDash([6,8]);g.strokeStyle='rgba(255,255,255,.18)';g.lineWidth=1.5;g.beginPath();g.moveTo(84,Y(0));g.lineTo(W-84,Y(0));g.stroke();g.setLineDash([]);
  pts.forEach((v,i)=>{g.beginPath();g.arc(X(i),Y(v),7,0,Math.PI*2);g.fillStyle=tr[i].p>=0?'#2ecc71':'#ff5c5c';g.fill();});}
 else{g.textAlign='center';g.fillStyle='#5f7185';g.font='20px Inter, system-ui, sans-serif';g.fillText(tr.length?'Un seul trade aujourd\u2019hui':'La courbe se dessine avec les trades',W/2,425);}
 // trades card
 const top=550,dh=44,n=Math.min(tr.length,6);
 rr(48,top,W-96,40+Math.max(1,n)*dh+18,26);g.fillStyle='#121a25';g.fill();g.strokeStyle='#1f2a38';g.stroke();
 g.textAlign='left';g.fillStyle='#8a9bb0';g.font='bold 16px Inter, system-ui, sans-serif';g.fillText('LES TRADES DU JOUR',80,top+34);
 if(!n){g.fillStyle='#5f7185';g.font='20px Inter, system-ui, sans-serif';g.fillText('Rien pour l\u2019instant.',80,top+74);}
 tr.slice(-6).forEach((t,i)=>{const y=top+58+i*dh;
  g.textAlign='left';g.fillStyle='#c6d3df';g.font='22px Inter, system-ui, sans-serif';g.fillText(t.t+' UTC',80,y+14);
  g.textAlign='right';g.fillStyle=t.p>=0?'#2ecc71':'#ff5c5c';g.font='bold 22px Inter, system-ui, sans-serif';
  g.fillText((t.p>=0?'+$':'-$')+Math.abs(t.p).toFixed(2),W-80,y+14);});
 g.textAlign='center';g.fillStyle='#8a9bb0';g.font='20px Inter, system-ui, sans-serif';
 g.fillText(MAN()?'OwlNest \u2014 vos signaux, vos d\u00e9cisions.':'Le robot Owl trade pour vous, jour et nuit.',W/2,H-56);
 c.toBlob(async b=>{const f=new File([b],'owlnest-journee.png',{type:'image/png'});
  if(navigator.canShare&&navigator.canShare({files:[f]})){try{await navigator.share({files:[f],title:'Ma journ\u00e9e OwlNest'});}catch(e){}}
  else{try{window.open(URL.createObjectURL(b),'_blank');}catch(e){}}},'image/png');
}
// owner: account switcher sheet (the header chip); Le Nid stays the console
// Owner 2026-09-27: "once you have switched there is no way to go back" -
// another member's page is not master, so it has no nest list. The owner's
// browser remembers the owner's own page (owl_adm, set on the master page);
// that page's /api still answers with the list, so any page can show the chip.
async function nestFromAdmin(){
 if(window._nest&&window._nest.length)return window._nest;
 let adm=null;try{adm=localStorage.getItem('owl_adm');}catch(e){}
 if(!adm)return null;
 try{const r=await fetch(adm+'api?t='+Date.now(),{cache:'no-store'});if(!r.ok)return null;
  const j=await r.json();if(j&&j.is_master&&j.nest){window._nest=j.nest;window._admName=j.name||'';return j.nest;}}catch(e){}
 return null;
}
async function acctChipInit(){
 if(window._d&&window._d.is_master)return;
 // 2026-10-03 (owner): on a member's page the hero shows no switcher,
 // even on the admin's own phone - the way back is a row in Reglages
 const N=await nestFromAdmin();let adm=null;try{adm=localStorage.getItem('owl_adm');}catch(e){}
 const row=document.getElementById('admback');
 if(N&&N.length&&adm&&row){row.href=adm;row.style.display='flex';
  const s=document.getElementById('admback-s');if(s)s.textContent=(LANG()==='en'?'You are viewing a member\u2019s account':'Vous regardez le compte d\u2019un membre')+(window._admName?' \u00b7 '+window._admName:'');}
}
async function acctSheet(){
 const N=(await nestFromAdmin())||[],d=window._d||{};if(!N.length)return;
 // 2026-10-01 (owner): real money only here too - the same figure
 // shown in a second place must not disagree with the first
 const _R=N.filter(x=>x.real===true);
 const tb=_R.reduce((a,x)=>a+(x.bal||0),0),tt=_R.reduce((a,x)=>a+(x.today||0),0);
 const money=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 const st=x=>{const noBot=!x.bot;
  if(noBot)return[x.paused?'manuel':'sans robot','var(--muted)','#4a5a6b'];
  if(x.observer&&!x.botlive)return['observateur','var(--muted)','#4a5a6b'];
  if(x.err)return['probl\u00e8me','var(--down-soft)','var(--down)'];
  if(x.stale)return['hors ligne','var(--warn)','var(--warn)'];
  if(!x.botlive)return['robot arr\u00eat\u00e9','var(--down-soft)','var(--down)'];
  if(x.blocked)return[x.blocked,'var(--warn)','var(--warn)'];
  return x.paused?['manuel','var(--text3)','#8fa1b3']:['auto','var(--up-soft)','var(--up)'];};
 const fu=x=>{if(!x.family_until)return '';const dl=Math.ceil((x.family_until-Date.now()/1000)/86400);const dt=new Date(x.family_until*1000);
  const ds=String(dt.getDate()).padStart(2,'0')+'/'+String(dt.getMonth()+1).padStart(2,'0');
  return ' \u00b7 <span style="color:'+(dl<=0?'var(--down-soft)':dl<=5?'var(--warn)':'var(--muted)')+'">'+(dl<=0?'expir\u00e9 le '+ds:'jusqu\u2019au '+ds+(dl<=5?' ('+dl+' j)':''))+'</span>';};
 const rows=N.filter(x=>x.tok).map(x=>{const cur=(x.login&&d.acct&&String(x.login)===String(d.acct));const S=st(x);
  const ini=(x.name||'?').trim().split(/\s+/).map(w=>w[0]).join('').slice(0,2).toUpperCase();
  return '<div class="srow" role="button" tabindex="0" onclick="location.href=\\'/'+x.tok+'/\\'" style="'+(cur?'background:rgba(59,130,246,.08);border-radius:12px;':'')+'">'+
   '<div class="sic" style="font-weight:800;font-size:.8rem;color:var(--text2);position:relative">'+ini+
    '<i style="position:absolute;right:-2px;bottom:-2px;width:9px;height:9px;border-radius:50%;background:'+S[2]+';border:2px solid var(--surface)"></i></div>'+
   '<div style="flex:1;min-width:0"><b style="display:flex;align-items:center;gap:6px">'+x.name+(cur?'<svg class="ic ic-s" style="color:var(--accent-soft)"><use href="#i-check"/></svg>':'')+'</b>'+
    (x.note?'<div style="font-size:.74rem;color:var(--warn);line-height:1.35;margin-top:2px">\u270e '+String(x.note).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))+'</div>':'')+
    '<div class="ssub"><span style="color:'+S[1]+';font-weight:700">'+S[0]+'</span>'+(x.login?' \u00b7 '+x.login:'')+(x.pos?' \u00b7 '+x.pos+' en cours':'')+fu(x)+(x.sigs&&x.sigs.sent?' \u00b7 <span style="color:var(--accent-soft)">'+x.sigs.taken+'/'+x.sigs.sent+' signaux '+money(x.sigs.net)+'</span>':'')+(x.push===false&&x.paused?' \u00b7 <span style="color:var(--down-soft)">pas de notif</span>':'')+' \u00b7 <span style="color:var(--muted)">'+agoTxt(x.seen)+'</span></div></div>'+
   '<div style="text-align:right;flex:none"><b style="font-variant-numeric:tabular-nums">'+(typeof x.bal==='number'?'$'+x.bal.toFixed(2):'\u2014')+'</b>'+
    '<div style="font-size:.74rem" class="'+sgn(x.today||0)+'">'+(typeof x.today==='number'?money(x.today):'')+'</div></div></div>'+
   '<div style="display:flex;gap:6px;padding:0 0 10px 44px;margin-top:-4px">'+
    '<a href="/'+x.tok+'/chart" onclick="event.stopPropagation()" aria-label="Graphique" style="text-decoration:none;color:var(--text2);border:1px solid var(--border2);background:var(--surface3);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700;display:inline-flex;align-items:center;gap:5px"><svg class="ic ic-s"><use href="#i-chart"/></svg>Graphique</a>'+
    (x.family_until?'<button onclick="event.stopPropagation();_shDone(1);nestCodeFor(&#39;'+String(x.name||'').replace(/[&#39;"<>]/g,'')+'&#39;)" style="border:1px solid var(--border2);background:var(--surface3);color:var(--warn);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700;display:inline-flex;align-items:center;gap:5px"><svg class="ic ic-s"><use href="#i-key"/></svg>Code</button>':'')+
    (x.setup&&!x.setup.paid&&x.setup.usd?'<button onclick="event.stopPropagation();_shDone(1);nestSharePaid(&#39;'+x.id+'&#39;,&#39;'+String(x.name||'').replace(/[&#39;"<>]/g,'')+'&#39;,&#39;setup&#39;,'+Number(x.setup.usd).toFixed(2)+')" style="border:1px solid rgba(232,197,90,.5);background:rgba(232,197,90,.1);color:var(--warn);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700;display:inline-flex;align-items:center;gap:5px">Ouverture $'+Number(x.setup.usd).toFixed(0)+'</button>':'')+
    (x.app&&!x.trade?'<button onclick="event.stopPropagation();_shDone(1);nestActivate(&#39;'+x.id+'&#39;,&#39;'+String(x.name||'').replace(/[&#39;"<>]/g,'')+'&#39;,&#39;'+({manual:'Signal',strategy:'Strat\u00e9gie'}[x.pkg]||'Signal')+'&#39;)" style="border:1px solid rgba(46,204,113,.45);background:rgba(46,204,113,.1);color:var(--up-soft);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700">Renouveler</button>':'')+
    (x.app?'<button onclick="event.stopPropagation();_shDone(1);nestResetPwd(&#39;'+x.id+'&#39;,&#39;'+String(x.name||'').replace(/[&#39;"<>]/g,'')+'&#39;)" style="border:1px solid var(--border2);background:var(--surface3);color:var(--text2);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700">Mot de passe</button>':'')+
    (x.share&&x.share.last&&(x.share.last.status==='open'||x.share.last.status==='overdue')?'<button onclick="event.stopPropagation();_shDone(1);nestSharePaid(&#39;'+x.id+'&#39;,&#39;'+String(x.name||'').replace(/[&#39;"<>]/g,'')+'&#39;,&#39;'+x.share.last.ym+'&#39;,'+Number(x.share.last.due).toFixed(2)+')" style="border:1px solid rgba(46,204,113,.45);background:rgba(46,204,113,.1);color:var(--up-soft);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700;display:inline-flex;align-items:center;gap:5px">Pay\u00e9 $'+Number(x.share.last.due).toFixed(2)+(x.share.last.status==='overdue'?' \u00b7 retard':'')+'</button>':'')+
    (x.trade?'<button onclick="event.stopPropagation();_shDone(1);nestPause(&#39;'+x.id+'&#39;,&#39;'+(x.paused?'0':'1')+'&#39;)" style="border:1px solid var(--border2);background:var(--surface3);color:var(--text2);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700;display:inline-flex;align-items:center;gap:5px"><svg class="ic ic-s"><use href="#'+(x.paused?'i-bot':'i-pause')+'"/></svg>'+(x.paused?'Reprendre':'Pause')+'</button>':'')+
    '<button onclick="event.stopPropagation();_shDone(1);nestNote(&#39;'+x.id+'&#39;,&#39;'+String(x.name||'').replace(/[&#39;"<>]/g,'')+'&#39;)" aria-label="Note" style="border:1px solid var(--border2);background:var(--surface3);color:var(--text2);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700">\u270e</button>'+
    (x.app?'':'<button onclick="event.stopPropagation();_shDone(1);nestPanic(&#39;'+x.id+'&#39;,&#39;'+String(x.name||'').replace(/[&#39;"<>]/g,'')+'&#39;)" style="border:1px solid rgba(255,92,92,.45);background:rgba(255,92,92,.12);color:#ff8c8c;border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700;display:inline-flex;align-items:center;gap:5px"><svg class="ic ic-s"><use href="#i-stop"/></svg>Urgence'+(x.pos?' \u00b7 '+x.pos:'')+'</button>')+
   '</div>';}).join('');
 const PEND=((window._d||{}).pending)||[];
 const pendHtml=PEND.length?'<div class="lbl" style="margin:4px 0 6px;color:var(--warn)">En attente d\u2019un code \u00b7 '+PEND.length+'</div>'+PEND.map(p=>{const L={family:'Automatique',manual:'Signal',strategy:'Strat\u00e9gie'}[p.pkg]||p.pkg;const ago=p.asked?Math.max(0,Math.round((Date.now()/1000-p.asked)/3600)):null;
   return '<div class="srow" style="background:rgba(232,197,90,.06);border-radius:12px"><div class="sic" style="font-weight:800;font-size:.8rem;color:var(--warn)">'+String(p.name||p.id||'?').slice(0,2).toUpperCase()+'</div>'+
    '<div style="flex:1;min-width:0"><b>'+_escS(p.name||p.id)+'</b><div class="ssub">'+L+(p.mt5?' \u00b7 compte \u2022\u2022\u2022\u2022'+p.mt5:'')+(p.pkg==='family'&&!p.has_mt5?' \u00b7 <span style="color:var(--down-soft)">compte MT5 manquant</span>':'')+(p.telegram?' \u00b7 '+_escS(p.telegram):'')+(ago!=null?' \u00b7 il y a '+ago+' h':'')+'</div></div>'+
    '<div style="display:flex;gap:6px;flex:none"><button onclick="event.stopPropagation();_shDone(1);nestActivate(&#39;'+p.id+'&#39;,&#39;'+_escS(p.name||p.id)+'&#39;,&#39;'+L+'&#39;)" style="border:1px solid rgba(46,204,113,.45);background:rgba(46,204,113,.12);color:var(--up-soft);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700">Activer</button>'+
    '<button onclick="event.stopPropagation();_shDone(1);nestPendingDel(&#39;'+p.id+'&#39;,&#39;'+_escS(p.name||p.id)+'&#39;)" style="border:1px solid var(--border2);background:var(--surface3);color:var(--muted2);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700">\u2715</button></div></div>';}).join('')+'<div style="height:10px"></div>':'';
 sheet('<h3>Vos comptes</h3>'+pendHtml+
  '<div style="display:flex;justify-content:space-between;align-items:baseline;padding:4px 2px 10px;border-bottom:1px solid var(--border);margin-bottom:4px">'+
   '<span style="color:var(--muted2);font-size:.84rem">'+N.length+' compte'+(N.length>1?'s':'')+' \u00b7 total</span>'+
   '<span style="text-align:right"><b style="font-size:1.05rem">$'+tb.toFixed(2)+'</b> <span class="'+sgn(tt)+'" style="font-size:.8rem;margin-left:6px">'+money(tt)+' auj.</span></span></div>'+
  '<div style="max-height:56vh;overflow-y:auto;margin:0 -6px;padding:0 6px">'+rows+'</div>'+
  ((function(){let adm=null;try{adm=localStorage.getItem('owl_adm');}catch(e){}
    return (adm&&adm!==B)?'<a class="shbtn shmain" style="display:block;text-align:center;text-decoration:none" href="'+adm+'">Retour \\u00e0 mon compte</a>':'';})())+
  (d.is_master?'<button class="shbtn shmain" onclick="_shDone(1);nestCodeAny()">\U0001f511 G\u00e9n\u00e9rer un code</button>':'')+
  (d.is_master?'<button class="shbtn shghost" onclick="_shDone(1);tab(\\'nid\\',document.getElementById(\\'tb-nid\\'))">Ouvrir Le Nid</button>':'')+
  '<button class="shbtn shghost" onclick="_shDone(1)">Fermer</button>');
}
// ---- batch 20: onboarding cards + notification nudge ----
function onboard(i){
 const M=MAN();
 const C=[
  ['i-eye','var(--accent-soft)','Bienvenue sur OwlNest',M?'Votre compte est en mode manuel : l\u2019app lit le march\u00e9 pour vous et vous dit quand un signal est jouable. Vous d\u00e9cidez, l\u2019app veille.'
    :'Le robot Owl trade pour vous, jour et nuit. Vous, vous regardez : solde, trades et march\u00e9, mis \u00e0 jour toutes les 5 secondes.'],
  ['i-activity','var(--up)',M?'Le signal':'Le robot',M?'La carte March\u00e9 dit ce que fait le march\u00e9 et si un signal est jouable. Le graphique montre o\u00f9, et l\u2019outil Trader vous laisse d\u00e9cider.'
    :'Il n\u2019agit que quand tout est r\u00e9uni, il s\u2019abrite quand le march\u00e9 devient m\u00e9chant, et apr\u00e8s une perte il se rattrape prudemment. Tout se lit sur l\u2019Accueil.'],
  ['i-calendar','var(--warn)','Ce que vous recevrez','Chaque trade termin\u00e9, le bilan du soir et votre semaine le dimanche. L\u2019Historique garde tout, jour par jour.'],
  ['i-bell','var(--accent-soft)','Les notifications','Pour \u00eatre pr\u00e9venu sur votre t\u00e9l\u00e9phone, m\u00eame l\u2019app ferm\u00e9e. Vous pourrez couper la nuit dans les R\u00e9glages.']];
 if(OBS())C.push(['i-key','var(--warn)','Choisissez votre offre','Regarder est gratuit. Pour trader la strat\u00e9gie vous-m\u00eame avec les signaux et l\u2019outil du graphique, ou tout comprendre, une offre \u00e0 30 jours suffit.']);
 const n=C.length;i=Math.max(0,Math.min(n-1,i||0));const c=C[i];
 const dots=C.map((_,k)=>'<i style="display:inline-block;width:'+(k===i?18:6)+'px;height:6px;border-radius:99px;margin:0 2px;background:'+(k===i?'var(--accent)':'var(--border2)')+';transition:width .2s"></i>').join('');
 const last=i===n-1;
 const nb=document.getElementById('notifbtn');const canNotif=!!(nb&&nb.style.display!=='none'&&nb.dataset.on!=='1');
 sheet('<div style="text-align:center;padding:6px 0 2px"><div class="sic" style="margin:0 auto;width:56px;height:56px;border-radius:18px;color:'+c[1]+'"><svg class="ic" style="width:26px;height:26px"><use href="#'+c[0]+'"/></svg></div>'+
  '<h3 style="margin:14px 0 6px">'+c[2]+'</h3><p style="color:var(--text);font-size:.95rem;line-height:1.55">'+c[3]+'</p><div style="margin:6px 0 14px">'+dots+'</div></div>'+
  (last?(OBS()?'<button class="shbtn shmain" onclick="_shDone(1);try{localStorage.setItem(&#39;owlTourDone&#39;,&#39;1&#39;)}catch(e){};offersSheet()">Voir les offres</button>'
      :canNotif?'<button class="shbtn shmain" onclick="_shDone(1);document.getElementById(&#39;notifbtn&#39;).click();try{localStorage.setItem(&#39;owlTourDone&#39;,&#39;1&#39;)}catch(e){}">Activer les notifications</button>'
      :'<button class="shbtn shmain" onclick="_shDone(1);try{localStorage.setItem(&#39;owlTourDone&#39;,&#39;1&#39;)}catch(e){}">Terminer</button>')
      +'<button class="shbtn shghost" onclick="_shDone(1);try{localStorage.setItem(&#39;owlTourDone&#39;,&#39;1&#39;)}catch(e){}">Plus tard</button>'
   :'<button class="shbtn shmain" onclick="_shDone(1);onboard('+(i+1)+')">Suivant</button>'+
    '<button class="shbtn shghost" onclick="_shDone(1);try{localStorage.setItem(&#39;owlTourDone&#39;,&#39;1&#39;)}catch(e){}">Passer</button>'));
}
function nudgeCheck(){
 const el=document.getElementById('nudge');if(!el)return;
 let fs=0,done=0;try{fs=parseInt(localStorage.getItem('owlFirstSeen')||'0',10);done=localStorage.getItem('owlNudgeDone')?1:0;}catch(e){}
 const nb=document.getElementById('notifbtn');
 const need=nb&&nb.style.display!=='none'&&nb.dataset.on!=='1'&&window.Notification&&Notification.permission!=='granted';
 el.style.display=(need&&!done&&fs&&Date.now()-fs>3*86400000)?'block':'none';
}
function nudgeGo(){nudgeDone();const nb=document.getElementById('notifbtn');if(nb)nb.click();}
function nudgeDone(){try{localStorage.setItem('owlNudgeDone','1');}catch(e){}const el=document.getElementById('nudge');if(el)el.style.display='none';}
setInterval(nudgeCheck,15000);setTimeout(nudgeCheck,4000);
// ---- batch 20: Nid actions reachable from any page (owner) ----
function AB(){try{return localStorage.getItem('owl_adm')||B;}catch(e){return B;}}
// 2026-09-27: the member's journey - start, first trade, milestones, fresh starts
function renderTimeline(d){
 const el=document.getElementById('tl');if(!el)return;const en=LANG()==='en';
 const ev=[];const S=d.since_start||{};
 const fd=k=>{const m=/(\d{4})-(\d\d)-(\d\d)/.exec(k||'');return m?(m[3]+'/'+m[2]+'/'+m[1]):null;};
 const ts=k=>{const m=/(\d{4})-(\d\d)-(\d\d)/.exec(k||'');return m?Date.UTC(+m[1],+m[2]-1,+m[3])/1000:0;};
 if(d.era_start){ev.push({t:ts(d.era_start),ic:'i-home',c:'var(--accent-soft)',l:en?'Start with OwlNest':'D\u00e9but avec OwlNest',s:fd(d.era_start)});}
 (d.era_prev||[]).forEach(st=>{const m=/^(\d{4})(\d\d)(\d\d)/.exec(st);if(m){const k=m[1]+'-'+m[2]+'-'+m[3];
  ev.push({t:ts(k),ic:'i-activity',c:'var(--warn)',l:en?'Fresh start':'Nouveau d\u00e9part',s:fd(k)});}});
 if(S.first){ev.push({t:ts(S.first)+1,ic:'i-chart',c:'var(--up)',l:en?'First trade':'Premier trade',s:fd(S.first)});}
 const bd=window._badges||{};const BN={t10:['10 trades','10 trades'],t50:['50 trades','50 trades'],t100:['100 trades','100 trades'],gweek:['Semaine verte','Green week'],goal:['Objectif atteint','Goal reached'],d30:['30 jours','30 days'],d100:['100 jours','100 days']};
 Object.keys(bd).forEach(k=>{if(!BN[k])return;const dt=new Date(bd[k]*1000);
  ev.push({t:bd[k],ic:'i-check',c:'var(--up)',l:BN[k][en?1:0],s:String(dt.getDate()).padStart(2,'0')+'/'+String(dt.getMonth()+1).padStart(2,'0')+'/'+dt.getFullYear()});});
 el.style.display='none';   // 2026-09-28 (owner): the journey lives in Reglages > Mon parcours, not in Historique
 if(ev.length<2){window._tlHtml='';return;}
 ev.sort((a,b)=>b.t-a.t);
 window._tlHtml='<div style="position:relative"><div style="position:absolute;left:14px;top:12px;bottom:12px;width:2px;background:var(--border2)"></div>'+
  ev.map(e=>'<div style="display:flex;align-items:center;gap:12px;padding:7px 0;position:relative"><div class="evi" style="color:'+e.c+';background:var(--surface);border:1px solid var(--border2);z-index:1"><svg class="ic ic-s"><use href="#'+e.ic+'"/></svg></div>'+
   '<div style="flex:1"><b style="font-size:.9rem">'+e.l+'</b><div style="font-size:.74rem;color:var(--muted)">'+(e.s||'')+'</div></div></div>').join('')+'</div>';
}
// 2026-09-27: after a reset or for a new member, cards say what comes next
function renderEmpty(d){
 const en=LANG()==='en',M=MAN();
 const S=d.since_start||{},sc=document.getElementById('since'),st=document.getElementById('since-t'),sg=document.getElementById('since-g');
 if(sc&&(!S.n)&&d.era_start){sc.style.display='block';
  setH(st,en?'Your story starts here. The first trade will appear on this page.':'Votre histoire commence ici. Le premier trade appara\u00eetra sur cette page.');
  setH(sg,'');}
 const wk=document.getElementById('weekcard'),ws=document.getElementById('week-sum'),sb=document.getElementById('sharebtn');
 if(wk&&!(d.days||[]).length){wk.style.display='block';
  setH(ws,en?'This week is just starting \u2014 '+(M?'your first signal':'the robot\u2019s first trade')+' will show up here.':'Cette semaine commence \u2014 '+(M?'votre premier signal':'le premier trade du robot')+' appara\u00eetra ici.');
  if(sb)sb.style.display='none';}
 else if(sb)sb.style.display='';
 const mv=document.getElementById('msum-verdict');
 if(mv&&!(d.month_days||[]).length&&!(d.days||[]).length){mv.style.display='block';document.getElementById('msum-sec').style.display='flex';
  setH(mv,en?'This month is just starting.':'Ce mois commence.');}
}
// 2026-09-27: this month so far against last month up to the same day
function renderMvM(d){
 const el=document.getElementById('mvm');if(!el)return;
 const M=d.months||{};const n=new Date();const dom=n.getUTCDate();
 const ym=n.getUTCFullYear()+'-'+String(n.getUTCMonth()+1).padStart(2,'0');
 const pv=new Date(Date.UTC(n.getUTCFullYear(),n.getUTCMonth()-1,1));
 const pym=pv.getUTCFullYear()+'-'+String(pv.getUTCMonth()+1).padStart(2,'0');
 const cut=a=>(a||[]).filter(x=>parseInt((x.d||'').slice(8,10),10)<=dom);
 const cur=cut(M[ym]),prev=cut(M[pym]);
 if(!prev.length&&!cur.length){el.style.display='none';return;}
 const sum=a=>a.reduce((s,x)=>s+(x.p||0),0),g=a=>a.filter(x=>x.p>0.005).length;
 const cs=sum(cur),ps=sum(prev);
 const money=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 document.getElementById('mvm-lbl').textContent=T('mvm_lbl');
 const cell=(l,v,c,sub)=>'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:10px 12px">'+
  '<div style="font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">'+l+'</div>'+
  '<b style="display:block;font-size:1.15rem;margin-top:2px" class="'+c+'">'+v+'</b><span style="font-size:.72rem;color:var(--muted2)">'+sub+'</span></div>';
 const MON=LANG()==='en'?['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']:['janv.','f\u00e9vr.','mars','avr.','mai','juin','juil.','ao\u00fbt','sept.','oct.','nov.','d\u00e9c.'];
 setH(document.getElementById('mvm-g'),
  cell(MON[n.getUTCMonth()]+' 1\u2013'+dom,money(cs),sgn(cs),cur.length+' j \u00b7 '+g(cur)+' \u2713')+
  cell(MON[pv.getUTCMonth()]+' 1\u2013'+dom,prev.length?money(ps):'\u2014',prev.length?sgn(ps):'neu',prev.length?(prev.length+' j \u00b7 '+g(prev)+' \u2713'):''));
 setH(document.getElementById('mvm-t'),!prev.length?T('mvm_none'):(cs-ps>0.5?T('mvm_better'):(ps-cs>0.5?T('mvm_worse'):T('mvm_even'))));
 el.style.display='block';
}
async function healthSheet(){
 let h=null;try{const r=await fetch(AB()+'health?t='+Date.now(),{cache:'no-store'});if(r.ok)h=await r.json();}catch(e){}
 if(!h){toast('Service injoignable',2500);return;}
 const en=LANG()==='en';
 const fa=(a,warn,bad)=>{if(a==null)return['\u2014','var(--muted)'];const m=Math.round(a/60);const t=a<90?(a+' s'):(m<120?m+' min':Math.round(m/60)+' h');
  return[t,a>bad?'var(--down-soft)':(a>warn?'var(--warn)':'var(--up-soft)')];};
 const row=(l,v,c,sub)=>'<div class="row"><span class="rowt">'+l+(sub?'<span style="display:block;font-size:.72rem;color:var(--muted)">'+sub+'</span>':'')+'</span><b style="color:'+c+'">'+v+'</b></div>';
 let t='';
 let f=fa(h.chart_feed,120,300);t+=row(en?'Chart feed':'Flux graphique',f[0],f[1],en?'age of the last write':'\u00e2ge de la derni\u00e8re \u00e9criture');
 f=fa(h.nerv_hist,180,600);t+=row(en?'Nervousness history':'Historique nervosit\u00e9',f[0],f[1]);
 f=fa(h.notifier_log,3600,7200);t+=row(en?'Notifier':'Notificateur',f[0],f[1],(h.push_subs||0)+(en?' devices subscribed':' appareils abonn\u00e9s'));
 Object.keys(h.workers||{}).forEach(u=>{const w=fa(h.workers[u],90,300);const b=(h.bots||{})[u];const dk=(h.desks||{})[u];
  const st=b?(b.live?(b.blocked?'\u26a0 '+b.blocked:(en?'robot alive':'robot actif')):(en?'robot STOPPED':'robot ARR\u00caT\u00c9')):(dk!==undefined?(dk!=null&&dk<120?(en?'desk alive':'bureau actif'):(en?'desk STOPPED':'bureau ARR\u00caT\u00c9')):(en?'no robot':'sans robot'));
  const bad=(b&&!b.live)||(dk!==undefined&&!(dk!=null&&dk<120));
  t+=row(u,w[0],bad?'var(--down-soft)':w[1],st);});
 sheet('<h3>'+(en?'Service health':'Le service')+'</h3><p>'+(en?'Green = fresh, amber = late, red = stale or stopped.':'Vert = frais, orange = en retard, rouge = fig\u00e9 ou arr\u00eat\u00e9.')+'</p>'+
  '<div style="max-height:60vh;overflow-y:auto">'+t+'</div>'+
  '<div style="font-size:.72rem;color:var(--muted);margin-top:8px">build '+(h.build||'')+'</div>'+
  '<button class="shbtn shghost" onclick="_shDone(1)">Fermer</button>');
}
async function tradePillTap(){
 const d=window._d||{},ol=d.open_list||[];
 const pl=ol.reduce((a,p)=>a+(parseFloat(p.pl)||0),0);
 toast('<div class="evi" style="color:var(--accent-soft)"><svg class="ic ic-s"><use href="#i-activity"/></svg></div>'+
  '<div style="flex:1">Solde des trades termin\u00e9s : <b>$'+(typeof window._bal==='number'?window._bal.toFixed(2):'\u2014')+'</b>'+
  (ol.length?' \u00b7 trade en cours <b class="'+(pl>=0?'pos':'neg')+'">'+(pl>=0?'+$':'-$')+Math.abs(pl).toFixed(2)+'</b>':'')+'</div>',4200);
}
async function tradeStory(tx,x){
 const el=document.getElementById('tstory');if(!el)return;
 let st=null;try{const r=await fetch(B+'trade?t='+tx);if(r.ok)st=await r.json();}catch(e){}
 const money=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 const fd=m=>{m=Math.round(m||0);return m>=60?Math.floor(m/60)+' h '+String(m%60).padStart(2,'0'):m+' min';};
 const buy=(st&&st.found?st.dir==='BUY':x.dir==='A');
 const p=(st&&st.found)?st.p:x.p;
 let t='';
 const EN=LANG()==='en';
 const BAND={'calme':'calm','soutenu':'lively','rapide':'fast','tr\u00e8s rapide':'very fast'};
 const band=(st&&st.band)?(EN?(BAND[st.band]||st.band):st.band):'';
 const who=T('ts_who'),act=buy?T('ts_buy'):T('ts_sell');
 if(st&&st.found){const d=new Date(st.t*1000);
  const dd=String(d.getUTCDate()).padStart(2,'0')+'/'+String(d.getUTCMonth()+1).padStart(2,'0'),
   hh=String(d.getUTCHours()).padStart(2,'0')+':'+String(d.getUTCMinutes()).padStart(2,'0');
  t=who+act+T('ts_on')+dd+T('ts_at')+hh+(band?T('ts_in')+band+T('ts_in2'):'')+'.'+
   (st.risk?T('ts_risk')+st.risk.toFixed(1)+'</b>.':'')+
   T('ts_dur')+fd(st.dur_min)+T('ts_end')+
   (p>=0?T('ts_gain')+money(p)+T('ts_gain_tail'):T('ts_loss')+Math.abs(p).toFixed(2)+T('ts_loss_tail')+T('lost_tail'));}
 else{t=who+act+(x.dur!=null?T('ts_kept')+fd(x.dur):'')+T('ts_ended')+
   (p>=0?T('ts_gain')+money(p)+'</b>.':T('ts_loss')+Math.abs(p).toFixed(2)+'</b>.');}
 if(st&&st.found&&(st.plan_gain||st.risk)){const en=LANG()==='en';const oc=st.outcome||'';
  const how=(/win|tp|target/.test(oc))?(en?'target reached':'objectif atteint')
   :(/loss|sl|stop/.test(oc))?(en?'stopped at the stop':'arr\u00eat\u00e9 au stop')
   :(en?'closed before the end':'sorti avant la fin');
  t+='<div style="margin-top:8px;padding:9px 12px;border-radius:12px;background:var(--surface2);border:1px solid var(--border);font-size:.86rem;color:var(--muted2);line-height:1.45">'+
   '<b style="color:var(--text)">'+(en?'And the plan?':'Et le plan ?')+'</b> '+
   (en?'Risk ':'Risque ')+(st.risk?'<b>$'+st.risk.toFixed(2)+'</b>':'\u2014')+(st.plan_gain?(en?' to win ':' pour gagner ')+'<b>$'+st.plan_gain.toFixed(2)+'</b>':'')+
   ' \u00b7 '+(en?'Result: ':'R\u00e9sultat : ')+'<b>'+how+'</b> (<span class="'+sgn(p)+'">'+money(p)+'</span>).</div>';}
 setH(el,t);
}
window.addEventListener('load',()=>{
 const ib=document.getElementById('invbtn');
 if(ib)ib.onclick=async()=>{
  nestCodeAny();return;   // 2026-10-04: invitations are codes now
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
    'text-align:center;background:var(--bg);border-radius:14px;'+
    'padding:18px 6px;margin:6px 0 10px;color:var(--accent-soft)">'+j.code+
    '</div><p>Usage unique &middot; &agrave; entrer &agrave; '+
    'l&#39;inscription avec un compte r&eacute;el</p>'+
    '<button class="shbtn shmain" onclick="navigator.clipboard&&'+
    'navigator.clipboard.writeText(\\''+j.code+'\\');_shDone(1)">'+
    '&#128203; Copier et fermer</button>');}
   else{await info('&#10060; <h3>Mot de passe incorrect.</h3>');}}
  catch(e2){await info('<h3>Petit souci, r&eacute;essayez.</h3>');}};
});
function monthReport(){
 const R=window._mrep;if(!R)return;
 const money=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 const lab=k=>{const m=/(\d{4})-(\d\d)-(\d\d)/.exec(k||'');return m?m[3]+'/'+m[2]:k;};
 const bd=R.src.find(x=>x.p===R.best),wd=R.src.find(x=>x.p===R.worst);
 const st=R.stats;
 let t='<p style="color:var(--text)">En <b>'+R.name+'</b>'+
  (st?T('mo_n')+st.n+' trade'+(st.n>1?'s':'')+'</b>'+(st.n?' (dont '+st.won+' gagn\u00e9'+(st.won>1?'s':'')+')':''):'')+
  '. R\u00e9sultat : <b class="'+sgn(R.net)+'">'+money(R.net)+'</b>.</p>';
 const ico=(n,c)=>'<div class="evi" style="color:'+c+'"><svg class="ic ic-s"><use href="#'+n+'"/></svg></div>';
 const row=(i,h)=>'<div class="srow-ev">'+i+'<div style="flex:1">'+h+'</div></div>';
 t+=row(ico('i-calendar','var(--accent-soft)'),'<b>'+R.g+' jour'+(R.g>1?'s':'')+' vert'+(R.g>1?'s':'')+'</b>, <b>'+R.rr+' rouge'+(R.rr>1?'s':'')+'</b>.');
 if(bd&&R.best>0.005)t+=row(ico('i-check','var(--up)'),'Meilleur jour : le '+lab(bd.d)+', <b class="pos">'+money(R.best)+'</b>.');
 if(wd&&R.worst<-0.005)t+=row(ico('i-x','var(--down)'),'Jour le plus dur : le '+lab(wd.d)+', <b class="neg">'+money(R.worst)+'</b>.');
 if(st&&st.streak>1)t+=row(ico('i-activity','var(--up)'),'Plus longue s\u00e9rie : <b>'+st.streak+' gains de suite</b>.');
 t+='<p style="color:var(--text);margin-top:10px">'+(R.net>=0?T('mo_up'):(R.debt?T('mo_debt'):T('mo_down')))+'</p>';
 sheet('<h3>Rapport du mois</h3>'+t+
  '<button class="shbtn shmain" style="display:flex;align-items:center;justify-content:center;gap:8px" onclick="shareMonth()"><svg class="ic ic-s"><use href="#i-share"/></svg>Partager ce rapport</button>'+
  '<button class="shbtn shghost" onclick="_shDone(1)">Fermer</button>');
}
function shareMonth(){
 const R=window._mrep,d=window._d;if(!R||!d)return;
 const W=720,H=980,c=document.createElement('canvas');c.width=W;c.height=H;
 const g=c.getContext('2d');
 const rr=(x,y,w,h,r)=>{g.beginPath();g.roundRect(x,y,w,h,r);};
 const bg=g.createLinearGradient(0,0,0,H);bg.addColorStop(0,'#0f2740');bg.addColorStop(.45,'#0b0f14');bg.addColorStop(1,'#0b0f14');
 g.fillStyle=bg;g.fillRect(0,0,W,H);
 rr(56,52,60,60,16);g.fillStyle='#0d1117';g.fill();
 [76,96].forEach(cx=>{g.beginPath();g.arc(cx,76,9.5,0,Math.PI*2);g.fillStyle='#f0b43c';g.fill();
  g.beginPath();g.arc(cx,76,4,0,Math.PI*2);g.fillStyle='#121212';g.fill();});
 g.beginPath();g.moveTo(86,84);g.lineTo(80,98);g.lineTo(92,98);g.closePath();g.fillStyle='#c87828';g.fill();
 g.textAlign='left';g.fillStyle='#e8eef4';g.font='bold 34px Inter, system-ui, sans-serif';g.fillText('OwlNest',132,84);
 g.fillStyle='#8a9bb0';g.font='22px Inter, system-ui, sans-serif';g.fillText('Mon mois \u00b7 '+R.name+' \u00b7 '+(d.name||''),132,112);
 const up=R.net>=0;g.textAlign='center';g.fillStyle=up?'#2ecc71':'#ff5c5c';
 g.font='bold 104px Inter, system-ui, sans-serif';g.fillText((up?'+$':'-$')+Math.abs(R.net).toFixed(2),W/2,246);
 g.fillStyle='#8a9bb0';g.font='20px Inter, system-ui, sans-serif';g.fillText(R.name,W/2,280);
 // day strip: one bar per day of the month
 rr(48,318,W-96,180,26);g.fillStyle='#121a25';g.fill();g.strokeStyle='#1f2a38';g.lineWidth=1.5;g.stroke();
 const days=R.src||[];const n=Math.max(28,days.length?parseInt(days[days.length-1].d.slice(-2)):30);
 const amax=Math.max(1,...days.map(x=>Math.abs(x.p)));const bw=(W-160)/n;
 g.strokeStyle='rgba(255,255,255,.12)';g.beginPath();g.moveTo(80,408);g.lineTo(W-80,408);g.stroke();
 days.forEach(x=>{const i=parseInt(x.d.slice(-2))-1;const h=Math.max(3,Math.abs(x.p)/amax*70);
  rr(80+i*bw+bw*.2,x.p>=0?408-h:408,Math.max(3,bw*.6),h,3);g.fillStyle=x.p>=0?'#2ecc71':'#ff5c5c';g.fill();});
 // stats rows
 const st=R.stats;const rows=[];
 if(st)rows.push(['Trades',st.n+(st.n?' \u00b7 '+st.won+' gagn\u00e9'+(st.won>1?'s':''):'')]);
 rows.push(['Jours verts / rouges',R.g+' / '+R.rr]);
 if(R.best>0.005)rows.push(['Meilleur jour','+$'+R.best.toFixed(2)]);
 if(R.worst<-0.005)rows.push(['Jour le plus dur','-$'+Math.abs(R.worst).toFixed(2)]);
 if(st&&st.streak>1)rows.push(['Plus longue s\u00e9rie',st.streak+' gains de suite']);
 const top=530,dh=46;rr(48,top,W-96,30+rows.length*dh+14,26);g.fillStyle='#121a25';g.fill();g.strokeStyle='#1f2a38';g.stroke();
 rows.forEach((r,i)=>{const y=top+50+i*dh;g.textAlign='left';g.fillStyle='#a9b8c8';g.font='22px Inter, system-ui, sans-serif';g.fillText(r[0],80,y);
  g.textAlign='right';g.fillStyle='#e8eef4';g.font='bold 22px Inter, system-ui, sans-serif';g.fillText(r[1],W-80,y);});
 g.textAlign='center';g.fillStyle='#8a9bb0';g.font='20px Inter, system-ui, sans-serif';
 g.fillText('Le robot Owl trade pour vous, jour et nuit.',W/2,H-56);
 c.toBlob(async b=>{const f=new File([b],'owlnest-mois.png',{type:'image/png'});
  if(navigator.canShare&&navigator.canShare({files:[f]})){try{await navigator.share({files:[f],title:'Mon mois OwlNest'});}catch(e){}}
  else{try{window.open(URL.createObjectURL(b),'_blank');}catch(e){}}},'image/png');
}
function weekCanvas(){
 const d=window._d;
 if(!d)return null;
 const W=720,H=1120,c=document.createElement('canvas');
 c.width=W;c.height=H;
 const g=c.getContext('2d');
 const rr=(x,y,w,h,r)=>{g.beginPath();g.roundRect(x,y,w,h,r);};
 const bg=g.createLinearGradient(0,0,0,H);
 bg.addColorStop(0,'#0f2740');bg.addColorStop(.45,'#0b0f14');bg.addColorStop(1,'#0b0f14');
 g.fillStyle=bg;g.fillRect(0,0,W,H);
 // brand mark: the owl icon, drawn
 rr(56,52,60,60,16);g.fillStyle='#0d1117';g.fill();
 [76,96].forEach(cx=>{g.beginPath();g.arc(cx,76,9.5,0,Math.PI*2);g.fillStyle='#f0b43c';g.fill();
  g.beginPath();g.arc(cx,76,4,0,Math.PI*2);g.fillStyle='#121212';g.fill();});
 g.beginPath();g.moveTo(86,84);g.lineTo(80,98);g.lineTo(92,98);g.closePath();g.fillStyle='#c87828';g.fill();
 g.textAlign='left';g.fillStyle='#e8eef4';g.font='bold 34px Inter, system-ui, sans-serif';
 g.fillText('OwlNest',132,84);
 g.fillStyle='#8a9bb0';g.font='22px Inter, system-ui, sans-serif';
 g.fillText('Ma semaine \u00b7 '+(d.name||''),132,112);
 // week result
 const wk=d.week||0,up=wk>=0;
 g.textAlign='center';g.fillStyle=up?'#2ecc71':'#ff5c5c';
 g.font='bold 104px Inter, system-ui, sans-serif';
 g.fillText((up?'+$':'-$')+Math.abs(wk).toFixed(2),W/2,246);
 g.fillStyle='#8a9bb0';g.font='20px Inter, system-ui, sans-serif';
 g.fillText('depuis lundi',W/2,280);
 // curve card
 rr(48,318,W-96,240,26);g.fillStyle='#121a25';g.fill();g.strokeStyle='#1f2a38';g.lineWidth=1.5;g.stroke();
 const cv=d.curve||[];
 if(cv.length>1){
  const mn=Math.min(...cv,0),mx=Math.max(...cv,0),sp=(mx-mn)||1;
  const X=i=>84+(i/(cv.length-1))*(W-168),Y=v=>522-((v-mn)/sp)*170;
  g.beginPath();cv.forEach((v,i)=>{i?g.lineTo(X(i),Y(v)):g.moveTo(X(i),Y(v));});
  g.strokeStyle=up?'#2ecc71':'#ff5c5c';g.lineWidth=5;g.lineJoin='round';g.lineCap='round';g.stroke();
  g.lineTo(X(cv.length-1),530);g.lineTo(84,530);g.closePath();
  g.fillStyle=up?'rgba(46,204,113,.16)':'rgba(255,92,92,.16)';g.fill();
  const y0=Y(0);g.setLineDash([6,8]);g.strokeStyle='rgba(255,255,255,.18)';g.lineWidth=1.5;
  g.beginPath();g.moveTo(84,y0);g.lineTo(W-84,y0);g.stroke();g.setLineDash([]);
 }
 // days card
 const days=(d.days||[]).slice(0,7);
 const dh=44,top=590;
 rr(48,top,W-96,40+days.length*dh+18,26);g.fillStyle='#121a25';g.fill();g.strokeStyle='#1f2a38';g.stroke();
 g.textAlign='left';g.fillStyle='#8a9bb0';g.font='bold 16px Inter, system-ui, sans-serif';
 g.fillText('JOUR PAR JOUR',80,top+34);
 const amax=Math.max(1,...days.map(x=>Math.abs(x.p||0)));
 days.forEach((x,i)=>{const y=top+58+i*dh;
  g.textAlign='left';g.fillStyle='#c6d3df';g.font='22px Inter, system-ui, sans-serif';
  g.fillText(x.d,80,y+14);
  const w=Math.max(4,(Math.abs(x.p||0)/amax)*180);
  rr(300,y+2,w,14,7);g.fillStyle=x.p>=0?'rgba(46,204,113,.55)':'rgba(255,92,92,.55)';g.fill();
  g.textAlign='right';g.fillStyle=x.p>=0?'#2ecc71':'#ff5c5c';g.font='bold 22px Inter, system-ui, sans-serif';
  g.fillText((x.p>=0?'+$':'-$')+Math.abs(x.p||0).toFixed(2),W-80,y+14);});
 g.textAlign='center';g.fillStyle='#8a9bb0';g.font='20px Inter, system-ui, sans-serif';
 g.fillText('Le robot Owl trade pour vous, jour et nuit.',W/2,H-56);
 return c;
}
// 2026-09-27: the Sunday push carries this image - the phone draws it (no
// image library on the server) and uploads it when the week changes
function weekUpload(){
 const d=window._d;if(!d||!d.days||!d.days.length)return;
 const key=(new Date()).toISOString().slice(0,10)+'|'+(d.week||0).toFixed(2);
 let last=null;try{last=localStorage.getItem('owlWeekImg:'+B);}catch(e){}
 if(last===key)return;
 const c=weekCanvas();if(!c)return;
 c.toBlob(b=>{if(!b||b.size>600000)return;
  fetch(B+'week_img',{method:'POST',headers:{'Content-Type':'image/png'},body:b}).then(r=>{
   if(r&&r.ok){try{localStorage.setItem('owlWeekImg:'+B,key);}catch(e){}}}).catch(()=>{});},'image/png');
}
function shareWeek(){
 const c=weekCanvas();if(!c)return;
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
function panicCall(uid,pw,dry){
 return fetch(AB()+'nest_panic',{method:'POST',
  headers:{'Content-Type':'application/x-www-form-urlencoded'},
  body:'uid='+encodeURIComponent(uid)+'&dry='+dry+'&pwd='+
   encodeURIComponent(pw)}).then(r=>r.json()).catch(()=>null);
}
// Admin emergency stop (owner 2026-09-18). Two steps on purpose: the
// first call is a DRY RUN that only looks, so the admin sees exactly
// what is about to be closed before anything is sent to the broker.
// 2026-10-01 (owner): one line per Nid row - is this account's day
// finished, and what is the most it can risk on one trade. The ceiling is
// the package percentage applied to the balance we last saw, which is the
// same arithmetic the bot does at entry (risk_fit_pct x balance), so the
// number on screen is the number the robot uses.
// 2026-10-01 (owner): the day state and the per-trade ceiling as CHIPS.
// They were one run-on line with parentheses - "journee faite (cible
// $5.22) - reprise $4.95" - which read as a sentence nobody finishes.
// Chips wrap on a narrow phone instead of pushing the row around, and
// each fact can carry its own colour.
function dayChips(x){
 const dy=x.day,r=x.rules||{},out=[];
 if(dy){
  if(dy.killed)out.push('<span class="nchip nchip-b">arr\u00eat de s\u00e9curit\u00e9</span>');
  else if(dy.done){
   out.push('<span class="nchip nchip-ok">\u2713 journ\u00e9e faite</span>');
   if(typeof dy.cap==='number')
    out.push('<span class="nchip">cible $'+dy.cap.toFixed(2)+'</span>');
  }else if(typeof dy.cap==='number'&&dy.cap>0)
   out.push('<span class="nchip">$'+dy.pnl.toFixed(2)+' / $'+
    dy.cap.toFixed(2)+' du jour</span>');
  if(dy.debt>0.5)out.push('<span class="nchip nchip-w">reprise $'+
   dy.debt.toFixed(2)+'</span>');
 }
 if(r.risk_fit_pct>0)out.push('<span class="nchip">plafond '+
  r.risk_fit_pct+'%'+(x.bal!=null?' \u2248 $'+
  (x.bal*r.risk_fit_pct/100).toFixed(2):'')+'</span>');
 return out;
}
async function nestPanic(uid,name){
 const pw=await askPwd('Arr&ecirc;t d&rsquo;urgence sur '+name+' ?',
  'Je regarde d&rsquo;abord ce qui est ouvert. Rien ne sera ferm&eacute; '+
  'sans ton accord.','&#128269; Regarder',true);
 if(!pw)return;
 const dry=await panicCall(uid,pw,'1');
 if(!dry){await info('<h3>R&eacute;seau indisponible.</h3>');return;}
 if(!dry.ok){await info('<h3>Impossible</h3><p>'+
  (dry.err||'erreur inconnue')+'</p>');return;}
 const P=dry.positions||[],O=dry.orders||[];
 if(!P.length&&!O.length){
  await info('<h3>Rien &agrave; fermer</h3><p>Compte '+(dry.acct||'')+
   ' : aucun trade ouvert, aucun ordre en attente.</p>');return;}
 let li='';
 P.forEach(q=>{li+='<li>'+q.lot+' lot '+q.symbol+
  ' &middot; P&amp;L '+(q.pl>=0?'+$':'-$')+Math.abs(q.pl).toFixed(2)+
  '</li>';});
 O.forEach(q=>{li+='<li>ordre en attente &middot; '+q.lot+' lot '+
  q.symbol+'</li>';});
 const go=await sheet('<h3>Tout fermer sur '+name+' ?</h3>'+
  '<p>Compte '+dry.acct+'. Les trades seront ferm&eacute;s au prix du '+
  'march&eacute;, et le compte passera en manuel pour que le robot ne '+
  'rouvre rien.</p><ul style="margin:0 0 14px 18px;color:var(--text2);'+
  'font-size:.85rem;line-height:1.7">'+li+'</ul>'+
  '<button class="shbtn shdanger" onclick="_shDone(1)">'+
  '&#128721; Tout fermer maintenant</button>'+
  '<button class="shbtn shghost" onclick="_shDone(null)">Annuler'+
  '</button>');
 if(!go)return;
 const r=await panicCall(uid,pw,'0');
 if(!r){await info('<h3>R&eacute;seau indisponible.</h3>'+
  '<p>V&eacute;rifie le compte avant de recommencer.</p>');load();return;}
 const nc=r.closed||0,na=r.cancelled||0,nf=r.failed||0;
 let h=(nf?'<h3>&#9888;&#65039; Partiellement ferm&eacute;</h3>'
          :'<h3>&#9989; Compte ferm&eacute;</h3>');
 h+='<p>'+nc+' trade'+(nc>1?'s':'')+' ferm&eacute;'+(nc>1?'s':'')+
    ', '+na+' ordre'+(na>1?'s':'')+' annul&eacute;'+(na>1?'s':'')+
    '. Compte en manuel.</p>';
 if(nf)h+='<p style="color:#ff9678">'+nf+' &eacute;chec(s). '+
  ((r.left!=null)?r.left+' position(s) encore ouverte(s). ':'')+
  'Regarde le compte directement.</p>';
 if(r.err)h+='<p style="color:#ff9678">'+r.err+'</p>';
 await info(h);
 load();
}
async function nestReset(uid,name){
 // 2026-09-27: show what will be archived and what stays, before the password
 let pv=null;try{const r=await fetch(AB()+'nest_reset_preview?uid='+encodeURIComponent(uid)+'&t='+Date.now(),{cache:'no-store'});if(r.ok)pv=await r.json();}catch(e){}
 if(pv){const fd=k=>{const m=/(\d{4})-(\d\d)-(\d\d)/.exec(k||'');return m?m[3]+'/'+m[2]:'\u2014';};
  const col=(t,c,items)=>'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:10px 12px"><div style="font-size:.66rem;color:'+c+';text-transform:uppercase;letter-spacing:.06em;font-weight:700">'+t+'</div>'+
   '<div style="font-size:.84rem;color:var(--text2);line-height:1.55;margin-top:4px">'+items.map(x=>'\u2022 '+x).join('<br>')+'</div></div>';
  const ok=await sheet('<h3>Avant de r\u00e9initialiser '+name+'</h3>'+
   '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:6px 0 12px">'+
   col('Archiv\u00e9','var(--down-soft)',[pv.trades+' trade'+(pv.trades>1?'s':'')+' depuis le '+fd(pv.first||pv.era_start),pv.days+' jour'+(pv.days>1?'s':'')+' d\u2019historique',(pv.state?'le livre de comptes du robot':'aucun livre (robot absent)'),pv.journal_rows+' ligne'+(pv.journal_rows>1?'s':'')+' de journal'])+
   col('Conserv\u00e9','var(--up-soft)',['le compte et son lien','les notifications et la langue','les messages re\u00e7us','les anciens fichiers, archiv\u00e9s (.bak)'])+'</div>'+
   '<p style="color:var(--muted2);font-size:.84rem">Le robot s\u2019arr\u00eate, repart de z\u00e9ro, et l\u2019app recommence son histoire aujourd\u2019hui. Refus\u00e9 si un trade est ouvert.</p>'+
   '<button class="shbtn shmain" onclick="_shDone(1)">Continuer</button><button class="shbtn shghost" onclick="_shDone(null)">Annuler</button>');
  if(!ok)return;}
 const pw=await askPwd('R\u00e9initialiser '+name+' ?',
  'Le robot s\u2019arr\u00eate, son livre de comptes est archiv\u00e9 (jamais effac\u00e9), l\u2019historique de l\u2019app repart d\u2019aujourd\u2019hui, puis le robot red\u00e9marre de z\u00e9ro. Refus\u00e9 si un trade est ouvert.',
  '\u21bb R\u00e9initialiser',true);
 if(!pw)return;
 const r=await fetch(AB()+'nest_reset',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
  body:'uid='+encodeURIComponent(uid)+'&pwd='+encodeURIComponent(pw)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){await info('&#10060; <h3>'+(j&&j.err==='bad password'?'Mot de passe incorrect.':'Impossible pour l\u2019instant.')+'</h3>');return;}
 toast('<div class="evi" style="color:var(--accent-soft)"><svg class="ic ic-s"><use href="#i-activity"/></svg></div><div style="flex:1">R\u00e9initialisation lanc\u00e9e \u2014 le robot repart de z\u00e9ro dans ~30 s.</div>',6000);
}
// 2026-10-01 (owner): "Pourquoi rien aujourd'hui" - with the real reason,
// counted from the robot's own log rather than guessed from the market.
const WHYTXT={
 asleep:['le march\u00e9 dormait \u2014 aucun nouveau mouvement \u00e0 suivre',
         'the market was asleep \u2014 no new move to follow'],
 daycap:['l\u2019objectif du jour \u00e9tait d\u00e9j\u00e0 atteint',
         'the day\u2019s target was already reached'],
 storm:['le march\u00e9 allait trop vite',
        'the market was moving too fast'],
 nervous:['le march\u00e9 \u00e9tait nerveux',
          'the market was nervous'],
 toobig:['le risque d\u00e9passait le plafond du compte',
         'the risk was over the account ceiling'],
 recovery:['la petite structure se met en pause pendant la reprise',
           'the small structure pauses during catch-up']};
// 2026-10-01 (owner): the member's own rules, in Reglages. The ceiling is
// the package percentage applied to the balance, which is the same
// arithmetic the bot does at entry, so this is the number the robot uses.
function acctRules(d){
 const el=document.getElementById('arules');
 const sec=document.getElementById('arules-sec');
 if(!el)return;
 const r=d.acct_rules||{};const en=LANG()==='en';
 const bal=(d.ledger||{}).balance||d.balance||0;
 const rows=[];
 if(r.risk_fit_pct>0){
  const cap=bal>0?('≈ $'+(bal*r.risk_fit_pct/100).toFixed(2)):'';
  rows.push([ 'i-lock',
   (en?'Most one trade can risk: ':'Au plus par trade : ')+r.risk_fit_pct+'% '+cap,
   en?'The robot shrinks its lot to stay under this. It is your worst case on a single trade.'
     :'Le robot réduit sa taille pour rester dessous. C’est votre pire cas sur un seul trade.']);
 }else{
  rows.push([ 'i-lock',
   en?'No per-trade ceiling':'Pas de plafond par trade',
   en?'Only the 10% safety limit applies. A wide stop can risk more than usual.'
     :'Seule la limite de sécurité de 10% s’applique. Un stop large peut risquer plus que d’habitude.']);
 }
 if(r.day_cap)rows.push(['i-check',
  (en?'Daily target: ':'Objectif du jour : ')+'$'+Number(r.day_cap).toFixed(2),
  en?'Once reached the robot stops opening until the next day.'
    :'Atteint, le robot n’ouvre plus jusqu’au lendemain.']);
 // 2026-10-01 (owner): the panel should say EVERYTHING the robot
 // will do with the money, not the half that happens to be new
 if(r.lot)rows.push(['i-chart',
  (en?'Size per trade: ':'Taille par trade : ')+Number(r.lot).toFixed(2)+' lot',
  en?'It grows with the balance unless you switch that off in Settings.'
    :'Elle suit le solde, sauf si vous la désactivez dans Réglages.']);
 if(r.kill)rows.push(['i-stop',
  // the kill line is negative, so the sign goes BEFORE the dollar:
  // "$-60.00" is not how money is written
  (en?'Hard stop: ':'Arrêt total : ')+(r.kill<0?'-$':'$')
  +Math.abs(Number(r.kill)).toFixed(2),
  en?'If the robot is ever this far down overall, it closes everything and stops for good.'
    :'Si le robot descend jusque-là au total, il ferme tout et s’arrête définitivement.']);
 if(!rows.length){el.style.display='none';if(sec)sec.style.display='none';return;}
 setH(el,rows.map(x=>'<div class="srow" style="cursor:default">'+
  '<div class="sic"><svg class="ic"><use href="#'+x[0]+'"/></svg></div>'+
  '<div style="flex:1"><b>'+x[1]+'</b><div class="ssub">'+x[2]+'</div></div>'+
  '</div>').join(''));
 el.style.display='block';if(sec)sec.style.display='block';
}
// 2026-10-01 (owner): "pendant votre nuit" - the day that just closed,
// once per UTC day. Everything in it already existed and was spread over
// three tabs; the refusals existed only in a log file nobody reads.
function recapHide(){
 const el=document.getElementById('recap');if(el)el.style.display='none';
 try{localStorage.setItem('owlRecap:'+B,(d=>d)(new Date().toISOString().slice(0,10)));}catch(e){}
}
function showRecap(d){
 const el=document.getElementById('recap');if(!el)return;
 const r=d.recap;const en=LANG()==='en';
 if(!r||MAN()||d.public){el.style.display='none';return;}
 let seen=null;try{seen=localStorage.getItem('owlRecap:'+B);}catch(e){}
 const today=new Date().toISOString().slice(0,10);
 if(seen===today){el.style.display='none';return;}
 document.getElementById('recap-t').textContent=
  (en?'While you slept':'Pendant votre nuit');
 const money=(r.net>=0?'+$':'-$')+Math.abs(r.net).toFixed(2);
 let txt=(en?'Yesterday ('+r.day+'): ':'Hier ('+r.day+') : ')+money+
  (r.n?(en?' over '+r.n+' trade'+(r.n>1?'s':''):' en '+r.n+' trade'+(r.n>1?'s':'')):'')+'.';
 const w=r.why||{};
 if((w.why||[]).length&&WHYTXT[w.why[0].k])
  txt+=(en?' It also stood aside '+w.why[0].n+' time'+(w.why[0].n>1?'s':'')+': '
          :' Il s\u2019est aussi abstenu '+w.why[0].n+' fois : ')
      +WHYTXT[w.why[0].k][en?1:0]+'.';
 document.getElementById('recap-s').textContent=txt;
 el.style.display='block';
}
// 2026-10-01 (owner): the multi-timeframe payoff. Until the sample can
// carry a verdict this shows how far off it is, because a win rate off
// four trades is a number that reverses itself.
function tfPayoff(d){
 const el=document.getElementById('tfpay');if(!el)return;
 const p=d.htf_payoff;const en=LANG()==='en';
 if(!p||MAN()||d.public){el.style.display='none';return;}
 const ttl=en?'When the big timeframes agreed'
             :'Quand les grandes unit\u00e9s \u00e9taient d\u2019accord';
 if(!p.ready){
  const left=Math.max(0,(p.need||0)-(p.n||0));
  setH(el,'<div class="lbl">'+ttl+'</div>'+
   '<div style="font-size:.84rem;color:var(--muted2);line-height:1.5;'+
   'margin-top:6px">'+(en
    ?('We started recording the big picture on every trade on 1 October. '+
      'With '+p.n+' so far, it is too early to say - '+left+' more to go, '+
      'and at least '+p.need_cell+' on each side.')
    :('On enregistre la grande image \u00e0 chaque trade depuis le 1er '+
      'octobre. Avec '+p.n+' pour l\u2019instant, c\u2019est trop t\u00f4t pour '+
      'le dire \u2014 encore '+left+', et au moins '+p.need_cell+' de chaque '+
      'c\u00f4t\u00e9.'))+'</div>');
  el.style.display='block';return;
 }
 const row=(lab,c)=>'<div class="row" style="padding:9px 0"><span style="'+
  'color:var(--muted2);font-size:.86rem">'+lab+'</span><span><b>'+
  c.win.toFixed(0)+'%</b> <span style="color:var(--muted);font-size:.78rem">'+
  (en?'won, ':'gagn\u00e9s, ')+(c.avg>=0?'+$':'-$')+Math.abs(c.avg).toFixed(2)+
  (en?' each (':' chacun (')+c.n+')</span></span></div>';
 setH(el,'<div class="lbl">'+ttl+'</div>'+
  row(en?'All three agreed':'Les trois d\u2019accord',p.all)+
  row(en?'They did not':'Pas toutes',p.some)+
  '<div style="font-size:.76rem;color:var(--muted);line-height:1.45;'+
  'margin-top:4px">'+(en?'From '+p.n+' trades with a recorded snapshot. '+
   'Past results are not a promise.':'Sur '+p.n+' trades avec une photo '+
   'enregistr\u00e9e. Les r\u00e9sultats pass\u00e9s ne sont pas une promesse.')+
  '</div>');
 el.style.display='block';
}
function whyIdle(d){
 const el=document.getElementById('whyidle');if(!el)return;
 const w=d.why_idle;const en=LANG()==='en';
 if(!w||MAN()||d.public||!(d.ledger||{}).bos){el.style.display='none';return;}
 // it took trades today: the card is about a quiet day, not a busy one
 if(w.took>0||!(w.why||[]).length){el.style.display='none';return;}
 const first=WHYTXT[w.why[0].k];
 if(!first){el.style.display='none';return;}
 document.getElementById('whyidle-t').textContent=
  en?'Why nothing today':'Pourquoi rien aujourd\u2019hui';
 let txt=(en?'The robot looked and stayed out: ':'Le robot a regard\u00e9 et n\u2019est pas entr\u00e9 : ')
  +first[en?1:0]+' ('+w.why[0].n+'\u00d7).';
 const rest=(w.why||[]).slice(1).filter(x=>WHYTXT[x.k]);
 if(rest.length)txt+=(en?' Also: ':' Aussi : ')
  +rest.map(x=>WHYTXT[x.k][en?1:0]+' ('+x.n+'\u00d7)').join(', ')+'.';
 if(w.inner)txt+=(en?' It also saw '+w.inner+' small-structure chances and left them alone, as set.'
                    :' Il a aussi vu '+w.inner+' occasions de petite structure et les a laiss\u00e9es, comme r\u00e9gl\u00e9.');
 document.getElementById('whyidle-s').textContent=txt;
 el.style.display='block';
}
// 2026-09-27: the daily objective reached -> one calm card, in the phone's clock
function dayDone(d){
 const el=document.getElementById('daydone');if(!el)return;
 // 2026-10-01 (owner): yesterday's recap was rendering ABOVE today's
 // result, which reads backwards. Today leads; the recap follows it.
 {const rc=document.getElementById('recap');
  if(rc&&el.parentElement&&rc.nextElementSibling!==el)
   el.parentElement.insertBefore(rc,el.nextElementSibling);}
 const lg=d.ledger||{};const done=!!lg.day_capped||(typeof lg.cap_today==='number'&&(lg.day_pnl_bot||0)>=lg.cap_today);
 if(!lg.bos||!done||MAN()){el.style.display='none';return;}
 const en=LANG()==='en';const n=new Date();const nxt=new Date(Date.UTC(n.getUTCFullYear(),n.getUTCMonth(),n.getUTCDate()+1,0,0,0));
 const hm=String(nxt.getHours()).padStart(2,'0')+':'+String(nxt.getMinutes()).padStart(2,'0');
 const pnl=lg.day_pnl_bot||0;
 document.getElementById('daydone-t').textContent=(en?'\u2713 Day complete \u00b7 ':'\u2713 Journ\u00e9e termin\u00e9e \u00b7 ')+(pnl>=0?'+$':'-$')+Math.abs(pnl).toFixed(2);
 document.getElementById('daydone-s').textContent=en?('The robot resumes tomorrow at 00:00 UTC ('+hm+' on your phone).'):('Le robot reprend demain \u00e0 00:00 UTC ('+hm+' chez vous).');
 el.style.display='block';
 const dtc=document.getElementById('daytargetchip');if(dtc)dtc.style.display='none';
}
// ---- 2026-09-27: the commercial model in the app ----
function renderPlan(d){
 const P=d.plan,el=document.getElementById('plan-card');if(!P||!el)return;
 const en=LANG()==='en';const fd=ts=>{const x=new Date(ts*1000);return String(x.getDate()).padStart(2,'0')+'/'+String(x.getMonth()+1).padStart(2,'0');};
 const t=document.getElementById('plan-t'),sub=document.getElementById('plan-s'),bt=document.getElementById('plan-btns'),nt=document.getElementById('plan-note'),ic=document.getElementById('plan-ic');
 if(d.public){el.style.display='none';document.getElementById('plan-sec').style.display='none';return;}
 // 2026-10-04 (owner): the period ended - say it on the home, with the way to renew
 (function(){const c=document.getElementById('expcard');if(!c)return;
  const had=P.family_until||P.manual_until||P.strategy_until;const active=P.family||P.manual||P.strategy;
  if(d.is_master||!had||active||P.pending_pay){c.style.display='none';return;}
  const last=P.family_until>=Math.max(P.manual_until||0,P.strategy_until||0)?'family':(P.strategy_until>=(P.manual_until||0)?'strategy':'manual');
  const L={family:en?'Automatic':'Automatique',manual:'Signal',strategy:en?'Strategy':'Strat\u00e9gie'}[last];
  document.getElementById('exp-t').textContent=en?'Your '+L+' period has ended':'Votre p\u00e9riode '+L+' est termin\u00e9e';
  document.getElementById('exp-b').textContent=en?'Renew with a code from the Owl on Telegram'+(last==='family'?'.':', or in crypto - it comes back right away.'):'Renouvelez avec un code du Owl sur Telegram'+(last==='family'?'.':', ou en crypto \u2014 \u00e7a repart tout de suite.');
  const g=document.getElementById('exp-go');g.textContent=en?'Renew':'Renouveler';g.onclick=()=>codeModal(last);
  c.style.display='block';})();
 let title,txt,color='var(--accent-soft)';
 const plusS=P.strategy?(en?' + Strategy':' + Strat\u00e9gie'):'';
 if(P.pending_pay){title=en?'Waiting for your payment':'En attente de votre paiement';txt=en?'As soon as NOWPayments confirms it, your account comes alive (a few minutes). Not paid yet? Tap the package below.':'D\u00e8s que NOWPayments le confirme, votre compte s\u2019active (quelques minutes). Pas encore pay\u00e9 ? Touchez le paquet ci-dessous.';color='var(--warn)';}
 else if(P.family){title=(en?'Automatic':'Automatique')+plusS;txt=(P.family_until?(en?'The robot trades your account. Until ':'Le robot trade sur votre compte. Jusqu\u2019au ')+fd(P.family_until)+(en?' \u2014 renew with the Owl, then enter the code.':' \u2014 renouvelez aupr\u00e8s du Owl, puis entrez le code.'):(en?'The robot trades your account.':'Le robot trade sur votre compte.'));color='var(--warn)';}
 else if(P.family_expired){title=en?'Automatic \u2014 expired':'Automatique \u2014 expir\u00e9';txt=en?'Your period ended: the robot is paused on your account. Settle with the Owl and enter the renewal code below.':'Votre p\u00e9riode est termin\u00e9e : le robot est en pause sur votre compte. R\u00e9glez le Owl et entrez le code de renouvellement ci-dessous.';color='var(--down-soft)';}
 else if(P.manual){title='Signal'+plusS;txt=(en?'Signals on your phone, until ':'Signaux sur votre t\u00e9l\u00e9phone, jusqu\u2019au ')+fd(P.manual_until)+(P.strategy?(en?' \u00b7 full view until ':' \u00b7 vue compl\u00e8te jusqu\u2019au ')+fd(P.strategy_until):'')+'.';color='var(--up-soft)';}
 else if(P.strategy){title=en?'Strategy':'Strat\u00e9gie';txt=(en?'The full chart and the method, until ':'Le graphique complet et la m\u00e9thode, jusqu\u2019au ')+fd(P.strategy_until)+(en?'. Add Manual to trade the signals.':'. Ajoutez Manuel pour trader les signaux.');color='var(--warn)';}
 else{title=en?'No subscription':'Aucun abonnement';txt=en?'Signals and the full view are paid options. The demo is free for everyone.':'Les signaux et la vue compl\u00e8te sont des options payantes. La d\u00e9mo est gratuite pour tous.';}
 t.textContent=title;sub.textContent=txt;ic.style.color=color;
 // 2026-10-03 (owner): the one-time opening fee, until it is paid
 (function(){const F=P.setup;if(!F||F.paid||!F.usd)return;const us=v=>'$'+Number(v||0).toFixed(2);
  sub.innerHTML='<div style="margin-top:6px;padding:12px;border-radius:14px;border:1px solid rgba(232,197,90,.4);background:rgba(232,197,90,.08)"><b style="color:var(--text)">'+(en?'Opening fee \u00b7 '+us(F.usd)+', once':'Frais d\u2019ouverture \u00b7 '+us(F.usd)+', une seule fois')+'</b>'+
   '<div style="font-size:.8rem;margin-top:4px">'+(en?'Every account has its own terminal on our server. This fee opens yours.':'Chaque compte a son propre terminal sur notre serveur. Ces frais ouvrent le v\u00f4tre.')+'</div>'+
   (P.pay_ready?'<button class="shbtn shmain" style="margin:10px 0 0;padding:10px" onclick="buyPkg(&#39;setup&#39;)">'+(en?'Pay '+us(F.usd)+' in crypto':'Payer '+us(F.usd)+' en crypto')+'</button>':'<div style="font-size:.8rem;margin-top:8px;color:var(--text2)">'+(en?'Settle with the Owl.':'R\u00e9glez avec le Owl.')+'</div>')+'</div>'+sub.innerHTML;})();
 // 2026-10-03 (owner): the profit share - this month so far, and the
 // last statement with its Payer button
 (function(){const S=P.share;if(!S||!S.on||!P.family&&!P.family_expired&&!S.blocked)return;
  const mn=v=>(v>=0?'+$':'-$')+Math.abs(v||0).toFixed(2),us=v=>'$'+Number(v||0).toFixed(2);
  const MO=en?['January','February','March','April','May','June','July','August','September','October','November','December']:['janvier','f\u00e9vrier','mars','avril','mai','juin','juillet','ao\u00fbt','septembre','octobre','novembre','d\u00e9cembre'];
  const mname=ym=>MO[parseInt(ym.slice(5,7),10)-1]+' '+ym.slice(0,4);
  t.textContent=(en?'Automatic \u00b7 ':'Automatique \u00b7 ')+S.pct.toFixed(0)+(en?' % of the result':' % du r\u00e9sultat')+plusS;
  const N=S.now;
  const BF=Number(N.base_full||S.base||0);
  let h='<div style="margin-top:6px">'+(BF>0
   ?(en?'You keep '+(100-S.pct).toFixed(0)+' % of what the robot makes. A month without gain costs only the base ($'+BF.toFixed(0)+'), counted from the day the robot started on your account.':'Vous gardez '+(100-S.pct).toFixed(0)+' % de ce que le robot gagne. Un mois sans gain ne co\u00fbte que la base ('+BF.toFixed(0)+' $), compt\u00e9e depuis le jour o\u00f9 le robot a commenc\u00e9 sur votre compte.')
   :(en?'You keep '+(100-S.pct).toFixed(0)+' % of what the robot makes. A month without gain costs nothing.':'Vous gardez '+(100-S.pct).toFixed(0)+' % de ce que le robot gagne. Un mois sans gain ne co\u00fbte rien.'))+'</div>';
  h+='<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px">'+
   [[mn(N.profit),en?'robot, this month':'le robot, ce mois'],[us(N.above),en?'above your record':'au-dessus du record'],[us(N.due),en?'your share so far':'votre part, pour l\u2019instant']].map(x=>'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:9px 4px;text-align:center"><b style="display:block;font-size:.95rem">'+x[0]+'</b><span style="font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+x[1]+'</span></div>').join('')+'</div>';
  const L=S.last;
  if(L&&(L.status==='open'||L.status==='overdue')){
   h+='<div style="margin-top:12px;padding:12px;border-radius:14px;border:1px solid '+(L.status==='overdue'?'rgba(255,92,92,.45)':'rgba(232,197,90,.4)')+';background:'+(L.status==='overdue'?'rgba(255,92,92,.08)':'rgba(232,197,90,.08)')+'">'+
    '<b style="color:var(--text)">'+(en?'Statement for ':'Relev\u00e9 de ')+mname(L.ym)+' \u00b7 '+us(L.due)+'</b>'+
    '<div style="font-size:.8rem;margin-top:4px">'+(en?'Robot '+mn(L.profit)+', '+us(L.above)+' above your record \u2192 '+us(L.share)+(L.base>0?' + base '+us(L.base):'')+'.':'Robot '+mn(L.profit)+', '+us(L.above)+' au-dessus du record \u2192 '+us(L.share)+(L.base>0?' + base '+us(L.base):'')+'.')+
    (L.status==='overdue'?' <b style="color:var(--down-soft)">'+(en?'Overdue: the robot is paused on your account until it is settled.':'En retard : le robot est en pause sur votre compte jusqu\u2019au r\u00e8glement.')+'</b>':' '+(en?S.grace_days+' days to settle.':S.grace_days+' jours pour r\u00e9gler.'))+'</div>'+
    (P.pay_ready?'<button class="shbtn shmain" style="margin:10px 0 0;padding:10px" onclick="payShare(&#39;'+L.ym+'&#39;)">'+(en?'Pay '+us(L.due)+' in crypto':'Payer '+us(L.due)+' en crypto')+'</button>':'<div style="font-size:.8rem;margin-top:8px;color:var(--text2)">'+(en?'Settle with the Owl; he marks it paid and the robot goes on.':'R\u00e9glez avec le Owl ; il marque le relev\u00e9 pay\u00e9 et le robot continue.')+'</div>')+'</div>';}
  else if(L&&L.status==='paid')h+='<div style="font-size:.78rem;color:var(--up-soft);margin-top:8px">\u2713 '+(en?'Statement for ':'Relev\u00e9 de ')+mname(L.ym)+' '+(en?'settled':'r\u00e9gl\u00e9')+' ('+us(L.due)+').</div>';
  h+='<div style="font-size:.74rem;color:var(--muted);margin-top:8px">'+(en?'Your record = the account\u2019s best result since the robot started ('+us(N.hwm)+'). No share is ever taken on getting back to it.':'Votre record = le meilleur r\u00e9sultat du compte depuis le d\u00e9but du robot ('+us(N.hwm)+'). Aucune part n\u2019est prise sur un simple retour \u00e0 ce niveau.')+'</div>';
  sub.innerHTML=(P.family_expired||S.blocked?'':'')+h;})();
 const pk=P.packages||{};
 const btn=(k,lab,price,dis,sub2)=>'<button onclick="codeModal(&#39;'+k+'&#39;)" style="border:1px solid var(--border2);background:'+(dis?'var(--surface2)':'var(--surface3)')+';color:'+(dis?'var(--muted)':'var(--text2)')+';border-radius:12px;padding:10px 8px;font-size:.84rem;font-weight:700;line-height:1.35">'+lab+'<span style="display:block;font-size:.72rem;font-weight:600;color:var(--muted2)">'+price+(sub2?' \u00b7 '+sub2:'')+'</span></button>';
 const full=(P.seats_left<=0&&!P.manual);
 bt.innerHTML=(P.family?'':btn('manual','Signal'+(P.manual?' \u2713':''),'$'+(pk.manual||{}).usd+' / 30 j',!P.pay_ready||full,full?(en?'full':'complet'):''))+
  btn('strategy',(en?'Strategy':'Strat\u00e9gie')+(P.strategy?' \u2713':''),'$'+(pk.strategy||{}).usd+' / 30 j',!P.pay_ready,'');
 bt.style.gridTemplateColumns=P.family?'1fr':'1fr 1fr';
 bt.insertAdjacentHTML('afterend','');
 (function(){let o=document.getElementById('plan-offers');if(!o){o=document.createElement('button');o.id='plan-offers';o.className='shbtn shghost';o.style.cssText='margin:10px 0 0;padding:11px;font-size:.9rem';o.onclick=offersSheet;bt.parentNode.insertBefore(o,nt);}
  o.textContent=en?'See the plans in detail':'Voir les offres en d\u00e9tail';o.style.display='block';})();
 (function(){const oc=document.getElementById('offercard');if(!oc)return;let hid=0;try{hid=parseInt(localStorage.getItem('owlOfferHide:'+B)||'0',10);}catch(e){}
  const show=!d.public&&!P.family&&!P.manual&&(Date.now()-hid>3*86400000);oc.style.display=show?'block':'none';
  if(show){document.getElementById('offercard-t').textContent=en?'Trade the strategy yourself':'Tradez la strat\u00e9gie vous-m\u00eame';
   document.getElementById('offercard-s').textContent=en?'Signals + the Trader tool on your account, from $'+(pk.manual||{}).usd+' / 30 days.':'Signaux + l\u2019outil Trader sur votre compte, d\u00e8s $'+(pk.manual||{}).usd+' / 30 jours.';}})();
 (function(){let a=document.getElementById('plan-act');if(!a){a=document.createElement('a');a.id='plan-act';a.href='#';a.style.cssText='display:block;text-align:center;font-size:.76rem;color:var(--muted);margin-top:10px;text-decoration:none';
   a.onclick=e=>{e.preventDefault();openActCard();};
   nt.parentNode.insertBefore(a,nt.nextSibling);}
  a.textContent=P.family?(en?'I have a renewal code':'J\u2019ai un code de renouvellement'):(en?'I have an activation code':'J\u2019ai un code d\u2019activation');a.style.display=d.public?'none':'block';})();
 (function(){const t=document.getElementById('tgrow-t'),s=document.getElementById('tgrow-s'),pr=document.getElementById('pwdrow');
  if(t&&s){t.textContent=P.tg_linked?(en?'Telegram linked \u2713':'Telegram reli\u00e9 \u2713'):(en?'Link Telegram':'Relier Telegram');s.textContent=P.tg_linked?(en?'Write \u201clien\u201d to the bot to get your access back':'\u00c9crivez \u00ab lien \u00bb au robot pour retrouver votre acc\u00e8s'):(en?'To get your access back one day, without e-mail':'Pour retrouver votre acc\u00e8s un jour, sans e-mail');}
  if(pr)pr.style.display=P.app_account?'flex':'none';})();
 nt.textContent=(P.family&&P.strategy)?'':(P.pay_ready?(en?'Payment in crypto (NOWPayments) or a code from the Owl on Telegram. Renewing adds 30 days.':'Paiement en crypto (NOWPayments) ou code du Owl sur Telegram. Renouveler ajoute 30 jours.')
  :(en?'Payments open soon \u2014 ask the Owl for now.':'Paiements bient\u00f4t disponibles \u2014 demandez au Owl en attendant.'));
 const pr=document.getElementById('payrow');if(pr)pr.style.display=d.public?'none':'flex';
 // 2026-09-28: waiting list when the manual seats are full
 (function(){let w=document.getElementById('plan-wait');if(!w){w=document.createElement('button');w.id='plan-wait';w.className='shbtn shghost';w.style.cssText='margin:10px 0 0;padding:11px;font-size:.9rem';bt.parentNode.insertBefore(w,nt);}
  const showW=full&&!P.family;w.style.display=showW?'block':'none';
  if(showW){w.textContent=P.waitlisted?(en?'\u2713 On the waiting list \u00b7 tap to leave':'\u2713 Sur la liste d\u2019attente \u00b7 toucher pour retirer'):(en?'Tell me when a place frees up':'Me pr\u00e9venir quand une place se lib\u00e8re');w.onclick=()=>waitlistToggle(!P.waitlisted);}})();
 const sr=document.getElementById('stratrow');if(sr)sr.style.display=P.strategy?'flex':'none';
 const pb=document.getElementById('pausebtn');if(pb&&d.pause_locked&&!d.public){const ps=document.getElementById('pause-sub');if(ps&&!P.manual)ps.textContent=en?'Manual trading is the admin\u2019s only.':'Le trading manuel est r\u00e9serv\u00e9 \u00e0 l\u2019administrateur.';}
}
// The offers, in full - one screen, both languages. What is INCLUDED is
// only what the app really does today; nothing promised beyond that.
// Observers: results and the app, never the gates. the Owl's robot = the public demo account.
// Manual members: the current signal (from their desk), plain and complete.
function renderSignal(ms){
 const el=document.getElementById('sigcard');if(!el)return;
 const sg=ms&&ms.signal;const en=LANG()==='en';
 if(!sg||sg.done||sg.skipped||!MAN()||OBS()||(sg.expires&&Date.now()/1000>sg.expires)){el.style.display='none';return;}
 window._sigMs=ms;
 const buy=sg.dir===1,col=sg.ok?(buy?'var(--up)':'var(--down)'):'var(--muted)';
 el.style.display='block';el.style.borderColor=sg.ok?col:'var(--border2)';el.style.opacity=sg.ok?'1':'.75';
 document.getElementById('sig-lbl').textContent=sg.ok?(en?'Signal':'Signal'):(en?'Signal set aside':'Signal \u00e9cart\u00e9');
 const age=Math.max(0,Math.round((Date.now()/1000-sg.t)/60));const exp=new Date(sg.expires*1000);
 document.getElementById('sig-when').textContent=(age<1?(en?'just now':'\u00e0 l\u2019instant'):(en?age+' min ago':'il y a '+age+' min'))+' \u00b7 '+(en?'until ':'valable jusqu\u2019\u00e0 ')+String(exp.getHours()).padStart(2,'0')+':'+String(exp.getMinutes()).padStart(2,'0');
 const dd=document.getElementById('sig-dir');dd.textContent=(buy?'\u25b2 ':'\u25bc ')+(buy?(en?'BUY':'ACHAT'):(en?'SELL':'VENTE'));dd.style.color=col;
 const cell=(l,v)=>'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:8px 4px;text-align:center"><span style="display:block;font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+l+'</span><b style="font-size:.86rem;font-variant-numeric:tabular-nums">'+v+'</b></div>';
 setH(document.getElementById('sig-g'),cell(en?'entry':'entr\u00e9e','~'+sg.e.toFixed(0))+cell('stop',sg.sl.toFixed(0))+cell(en?'target':'cible',sg.tp.toFixed(0))+cell('lot',sg.lot.toFixed(2)+(sg.bul?'+'+sg.bul:'')));
 myLotLine(sg,en);
 const far=(ms&&typeof ms.px==='number'&&sg.e)?Math.abs(ms.px-sg.e)/sg.e:0;
 const farTxt=far>0.0025?('<div style="color:var(--warn);margin-bottom:4px">\u26a0 '+(en?'The price has moved '+(far*100).toFixed(2)+'% from the entry \u2014 careful, the risk is no longer the same.':'Le prix s\u2019est \u00e9loign\u00e9 de l\u2019entr\u00e9e ('+(far*100).toFixed(2)+'\u202f%) \u2014 prudence, le risque n\u2019est plus le m\u00eame.')+'</div>'):'';
 setH(document.getElementById('sig-note'),farTxt+(sg.ok?(en?'Take it at market as long as the price is near the entry. The stop is the level that invalidates it; the target is 0.8\u00d7 the risk.':'\u00c0 prendre au march\u00e9 tant que le prix est proche de l\u2019entr\u00e9e. Le stop est le niveau qui l\u2019invalide ; la cible vaut 0,8\u00d7 le risque.')
  :('<b>'+(en?'Not advised':'Pas conseill\u00e9')+'</b> \u2014 '+sg.why+(en?'. the Owl\u2019s robot would not take it either.':'. Le robot du Owl ne le prendrait pas non plus.'))));
 const a=document.getElementById('sig-chart');a.href=B+'chart?sig=1';a.style.display=sg.ok?'block':'none';
 window._sig=sg;
 // 2026-09-28: members trading on another broker tell the app themselves
 const mk=document.getElementById('sig-mark');
 if(mk){const bs='border:1px solid var(--border2);background:var(--surface3);border-radius:10px;padding:9px;font-size:.84rem;font-weight:700;flex:1;';
  if(!sg.ok){mk.style.display='none';}
  else if(sg.taken){mk.style.display='block';
   setH(mk,'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><span style="color:var(--up-soft);font-weight:700;font-size:.84rem">\u2713 '+(en?'Taken':'Pris')+(sg.taken_manual?'':(en?' (detected on your account)':' (d\u00e9tect\u00e9 sur votre compte)'))+(typeof sg.result==='number'?' \u00b7 '+(sg.result>=0?'+$':'-$')+Math.abs(sg.result).toFixed(2):'')+'</span>'+
    (sg.taken_manual&&typeof sg.result!=='number'?'<input id="sig-res" inputmode="decimal" placeholder="'+(en?'result in $, e.g. +12.5':'r\u00e9sultat en $, ex. +12,5')+'" style="flex:1;min-width:120px;background:var(--bg);border:1px solid var(--border2);border-radius:10px;padding:8px 10px;color:var(--text);font-size:.84rem"><button onclick="sigMarkRes()" style="'+bs+'flex:none;color:var(--text2)">'+(en?'Save':'Enregistrer')+'</button>':'')+'</div>');}
  else{mk.style.display='block';
   setH(mk,'<div style="font-size:.74rem;color:var(--muted);margin-bottom:6px">'+(en?'Trading it on another broker? Tell the app, so your history stays right:':'Vous le tradez chez un autre broker ? Dites-le \u00e0 l\u2019app, pour un historique juste :')+'</div><div style="display:flex;gap:8px"><button onclick="sigMark(1)" style="'+bs+'color:var(--up-soft)">\u2713 '+(en?'I took it':'J\u2019ai pris')+'</button><button onclick="sigMark(0)" style="'+bs+'color:var(--text2)">'+(en?'Not taken':'Pas pris')+'</button></div>');}}
}
async function sigMark(tk,res){const sg=window._sig;if(!sg)return;const en=LANG()==='en';
 const r=await fetch(B+'sigmark',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'t='+sg.t+'&taken='+tk+(res!==undefined&&res!==''?'&result='+encodeURIComponent(res):'')}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){toast(en?'Not saved, try again.':'Pas enregistr\u00e9, r\u00e9essayez.',2500);return;}
 if(tk===1){sg.taken=sg.taken||'manual';sg.taken_manual=true;if(j.mark&&typeof j.mark.result==='number')sg.result=j.mark.result;toast(typeof sg.result==='number'?(en?'Saved.':'Enregistr\u00e9.'):(en?'Noted: taken. Enter the result once closed.':'Not\u00e9 : pris. Entrez le r\u00e9sultat une fois ferm\u00e9.'),2500);}
 else{sg.skipped=true;toast(en?'Noted: not taken. The next signal shows here.':'Not\u00e9 : pas pris. Le prochain signal s\u2019affiche ici.',2500);}
 renderSignal(Object.assign({},window._sigMs||{},{signal:sg}));window._sgT=0;loadSignals();
}
function sigMarkRes(){const i=document.getElementById('sig-res');sigMark(1,i?i.value:'');}
function sigCopy(){const sg=window._sig;if(!sg)return;const en=LANG()==='en';
 const txt=(sg.dir===1?(en?'BUY':'ACHAT'):(en?'SELL':'VENTE'))+' BTCUSD \u00b7 '+(en?'entry':'entr\u00e9e')+' ~'+sg.e.toFixed(0)+' \u00b7 stop '+sg.sl.toFixed(0)+' \u00b7 '+(en?'target':'cible')+' '+sg.tp.toFixed(0)+' \u00b7 lot '+sg.lot.toFixed(2)+' \u00b7 OwlNest '+new Date(sg.t*1000).toISOString().slice(11,16)+' UTC';
 (navigator.clipboard?navigator.clipboard.writeText(txt):Promise.reject()).then(()=>toast((en?'Copied: ':'Copi\u00e9 : ')+txt,3500),()=>toast(txt,5000));}
function chime(force){try{if(!force&&localStorage.getItem('owlChime')!=='1')return;}catch(e){return;}
 try{if(navigator.vibrate)navigator.vibrate([120,60,120]);}catch(e){}
 try{const A=window._ac||(window._ac=new (window.AudioContext||window.webkitAudioContext)());const t0=A.currentTime;
  [[880,0],[1175,.16]].forEach(([f,dd])=>{const o=A.createOscillator(),g=A.createGain();o.type='sine';o.frequency.value=f;g.gain.setValueAtTime(0.0001,t0+dd);g.gain.exponentialRampToValueAtTime(0.25,t0+dd+.02);g.gain.exponentialRampToValueAtTime(0.0001,t0+dd+.28);o.connect(g);g.connect(A.destination);o.start(t0+dd);o.stop(t0+dd+.3);});}catch(e){}}
document.addEventListener('pointerdown',()=>{try{if(localStorage.getItem('owlChime')==='1'&&!window._ac)window._ac=new (window.AudioContext||window.webkitAudioContext)();}catch(e){}},{once:true});
async function pollSignal(){
 const d=window._d;if(!d||!MAN()||OBS())return;
 if(window._sigT&&Date.now()-window._sigT<8000)return;window._sigT=Date.now();
 try{const r=await fetch(B+'manual_state?t='+Date.now(),{cache:'no-store'});if(!r.ok){renderSignal(null);return;}const ms=await r.json();
  const sg=ms&&ms.signal;if(sg&&sg.ok&&!sg.done&&!sg.taken&&window._sgLastT!==undefined&&sg.t!==window._sgLastT)chime();if(sg)window._sgLastT=sg.t;else if(window._sgLastT===undefined)window._sgLastT=0;
  renderSignal(ms);}catch(e){}
}
// ---- the lab (owner 2026-09-28): ideas, replays, forward observations, decisions -
// what the auto-evolving bot stands on. Strategie members and the admin. ----
window._labTab='ideas';
function labTab(k){labStage(k);}
async function loadLab(d){const seg=document.getElementById('mxs-lab');if(seg)seg.style.display=labVisible()?'':'none';
 if(!labVisible())return;
 if(!labAllowed()){labPeek();return;}
 if(window._labT&&Date.now()-window._labT<120000){return;}window._labT=Date.now();
 // 2026-09-28 (owner): from the admin's phone the lab is read through the
 // ADMIN link - a member's link has no Strategie access and the panel stayed blank
 let adm='';try{adm=localStorage.getItem('owl_adm')||'';}catch(e){}
 const base=(adm&&adm.indexOf('/')===0&&adm!==B)?(adm.endsWith('/')?adm:adm+'/'):B;
 let j=null;try{const r=await fetch(base+'lab?t='+Date.now(),{cache:'no-store'});if(r.ok)j=await r.json();}catch(e){}
 if(!j||j.err){const en=LANG()==='en';setH(document.getElementById('lab-body'),'<div class="panel labintro" style="margin-top:12px"><b style="font-size:.95rem">'+(en?'The lab is part of the Strategy plan':'Le labo fait partie du paquet Stratégie')+'</b><div style="font-size:.84rem;color:var(--text2);line-height:1.5;margin-top:6px">'+(en?'It shows the ideas we test to make the robot better, what worked, and what did not. Settings › Subscription to add it.':'Il montre les idées qu’on teste pour rendre le robot meilleur, ce qui a marché et ce qui n’a pas marché. Réglages › Abonnement pour l’ajouter.')+'</div></div>');return;}
 window._lab=j;labRender();}
async function labPeek(){
 if(window._peekT&&Date.now()-window._peekT<300000)return;window._peekT=Date.now();
 const en=LANG()==='en';let j=null;try{const r=await fetch(B+'lab_peek?t='+Date.now(),{cache:'no-store'});if(r.ok)j=await r.json();}catch(e){}
 if(!j||j.err)return;const C=j.counts||{},n=k=>C[k]||0;
 const tile=(l,v,c)=>'<span class="ls"><b style="color:'+c+'">'+v+'</b>'+l+'</span>';
 document.getElementById('lab-stats').className='labstat';document.getElementById('lab-stats').style.cssText='';
 setH(document.getElementById('lab-stats'),tile(en?'ideas':'id\u00e9es',(j.n_ideas||0)+n('idea')+n('observation'),'var(--warn)')+tile(en?'to try':'\u00e0 essayer',n('candidate')+n('planned'),'#b98cff')+tile(en?'watching':'en observation',n('forward'),'var(--accent-soft)')+tile(en?'in the robot':'dans le robot',n('deployed'),'var(--up-soft)')+tile(en?'said no':'\u00e9cart\u00e9es',n('rejected'),'var(--muted2)'));
 setH(document.getElementById('lab-tabs'),'');
 document.getElementById('lab-hint').textContent='\u00b7 '+(en?'a glance':'un aper\u00e7u');
 const it=j.sample;
 const esc=x=>String(x||'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
 const chip=(t,c)=>'<span class="pchip" style="color:'+c+';background:rgba(255,255,255,.05)">'+t+'</span>';
 const sample=it?'<div class="panel lc" style="cursor:default"><div class="lct"><span class="lcb" style="color:var(--up-soft);background:rgba(46,204,113,.14)">A</span><div style="flex:1;min-width:0"><h4>'+esc(en?it.title_en:it.title_fr)+'</h4><div class="lcc">'+chip(en?'In the robot':'Dans le robot','var(--up-soft)')+chip(en?'the weather':'la m\u00e9t\u00e9o','var(--warn)')+'</div></div></div><div class="lcn">'+esc(en?it.note_en:it.note_fr)+'</div><div class="lcm"><span>'+esc(it.date||'')+'</span><span>'+(en?'one of the rules':'une des r\u00e8gles')+'</span></div></div>':'';
 const ghost=(t)=>'<div class="panel lc" style="cursor:default;filter:blur(4px);opacity:.55;pointer-events:none;user-select:none" aria-hidden="true"><div class="lct"><span class="lcb" style="color:var(--warn);background:rgba(232,197,90,.14)">B</span><div style="flex:1"><h4>'+t+'</h4><div class="lcc">'+chip('\u2022\u2022\u2022','var(--muted)')+chip('\u2022\u2022\u2022\u2022','var(--muted)')+'</div></div></div><div class="lcn">'+(en?'Same money at the end, a smaller hole along the way, on both halves of the period. To watch on the demo first.':'M\u00eame argent \u00e0 la fin, un trou moins profond en chemin, sur les deux moiti\u00e9s de la p\u00e9riode. \u00c0 observer sur la d\u00e9mo d\u2019abord.')+'</div></div>';
 setH(document.getElementById('lab-body'),
  '<div class="panel labintro"><b style="font-size:.95rem">'+(en?'The lab, in one minute':'Le labo, en une minute')+'</b><div style="font-size:.84rem;color:var(--text2);line-height:1.5;margin-top:6px">'+(en?'Here we look for ways to make the robot better over time. Every idea goes through three steps before it touches an account: checked on the past, watched live for pretend, then put in the robot or dropped.':'Ici, on cherche comment rendre le robot meilleur avec le temps. Chaque id\u00e9e passe par trois \u00e9tapes avant de toucher \u00e0 un compte : v\u00e9rifi\u00e9e sur le pass\u00e9, observ\u00e9e en direct pour de faux, puis mise dans le robot ou \u00e9cart\u00e9e.')+'</div><div style="font-size:.74rem;color:var(--muted);margin-top:8px">'+(j.live_trades||0)+' '+(en?'real trades studied so far':'vrais trades \u00e9tudi\u00e9s jusqu\u2019ici')+'</div></div>'+
  '<div class="sec" style="margin:16px 8px 8px">'+(en?'One rule the robot follows today':'Une r\u00e8gle que le robot suit aujourd\u2019hui')+'</div>'+sample+
  '<div class="sec" style="margin:16px 8px 8px">'+(en?'And in the full lab':'Et dans le labo complet')+'</div>'+ghost(en?'Aim for a smaller gain on each trade':'Viser un gain plus petit \u00e0 chaque trade')+ghost(en?'Do not enter right after a big run':'Ne pas entrer juste apr\u00e8s une grosse envol\u00e9e')+
  '<div class="panel" style="margin-top:10px;border-color:rgba(59,130,246,.35)"><b style="font-size:.95rem">'+(en?'The full lab comes with the Strategy plan':'Le labo complet vient avec le paquet Strat\u00e9gie')+'</b><div style="font-size:.84rem;color:var(--text2);line-height:1.5;margin-top:6px">'+(en?'Every idea found in the real trades, every check on the past with its verdict, the robots playing for pretend, and the decisions - updated all the time. Plus the full chart with the levels.':'Toutes les id\u00e9es trouv\u00e9es dans les vrais trades, chaque v\u00e9rification sur le pass\u00e9 avec son verdict, les robots qui jouent pour de faux, et les d\u00e9cisions \u2014 mis \u00e0 jour en continu. Avec le graphique complet et ses niveaux.')+'</div><button class="shbtn shmain" style="margin-top:12px" onclick="offersSheet()">'+(en?'See the Strategy plan':'Voir l\u2019offre Strat\u00e9gie')+'</button></div>');
}
// ---- 2026-09-29 (owner): "the board is the lab" - one screen, one story
// left to right: seeds, replayed, tested, decided, in the robot; the
// chercheur feeds it from the top; the big cards keep their design ----
function labRender(){const j=window._lab;if(!j)return;const en=LANG()==='en';const J=j.journeys||[];const seeds=labSeeds(j);
 const cnt=k=>J.filter(x=>x.col===k).length+(k==='idea'?seeds.length:0);
 const st=document.getElementById('lab-stats');st.innerHTML='';st.style.display='none';
 const tabs=document.getElementById('lab-tabs');if(tabs){tabs.innerHTML='';tabs.style.display='none';}
 // 2026-10-01 (owner): if the nightly job dies, every check built this
 // week quietly stops running and nothing says so. The lab already had the
 // timestamp and never looked at it. 36 h, not 24: one missed night is a
 // hiccup, two is a broken job.
 (function(){const u=(j.auto||{}).updated;const el=document.getElementById('lab-stale');
  if(!el)return;
  if(!u){el.style.display='block';el.style.borderLeft='2px solid var(--down)';
   el.innerHTML='<b style="color:var(--down)">'+(en?'The night run has never reported'
     :'La s\u00e9ance de nuit n\u2019a jamais rendu de r\u00e9sultat')+'</b>';return;}
  const hrs=(Date.now()-new Date(u).getTime())/3600000;
  if(hrs<36){el.style.display='none';return;}
  el.style.display='block';el.style.borderLeft='2px solid var(--down)';
  el.innerHTML='<b style="color:var(--down)">'+
   (en?'The night run has not finished for '+Math.round(hrs)+' h'
     :'La s\u00e9ance de nuit n\u2019a pas tourn\u00e9 depuis '+Math.round(hrs)+' h')+
   '</b><div style="color:var(--muted2);margin-top:3px">'+
   (en?'The checks that watch the robot are not running. Everything below is that old.'
     :'Les v\u00e9rifications qui surveillent le robot ne tournent plus. Tout ce qui suit date d\u2019autant.')+
   '</div>';})();
 (function(){const P=(j.auto||{}).parity;const el=document.getElementById('lab-parity');
  if(!el)return;
  if(!P){el.style.display='none';return;}
  window._labParityOk=!P.drift;
  el.style.display=P.drift?'block':'none';
  el.style.borderLeft='2px solid var(--down)';
  el.innerHTML=P.drift
   ?'<b style="color:var(--down)">'+(en?'The test no longer matches the robot'
     :'Le test ne correspond plus au robot')+'</b><div style="color:var(--muted2);margin-top:3px">'+
     (en?'Everything below describes a strategy that may not be the one running. Fix before trusting a number.'
       :'Tout ce qui suit d\u00e9crit une strat\u00e9gie qui n\u2019est peut-\u00eatre pas celle qui tourne. \u00c0 corriger avant de croire un chiffre.')+'</div>'
   :'<span style="color:var(--muted)">'+(en?'Checked last night: the test still matches the robot rule for rule.'
     :'V\u00e9rifi\u00e9 cette nuit : le test correspond toujours au robot, r\u00e8gle par r\u00e8gle.')+'</span>';
 })();
 document.getElementById('lab-hint').innerHTML='\u00b7 '+(en?'where the robot learns':'l\u00e0 o\u00f9 le robot apprend')+' <span onclick="labStage(&#39;how&#39;)" style="display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:99px;background:var(--surface3);color:var(--accent-soft);font-weight:800;cursor:pointer;margin-left:4px">?</span>';
 let h='';const N=j.note||{};const esc=_escS;
 // 2026-10-02 (owner): the doors ARE the landing, so they come first. The
 // chercheur's night was a 389px card sitting above them - a dense report
 // standing between a reader and the navigation. Same treatment as "Quoi
 // de neuf" on the home: one line, opening the full thing.
 h+=labHero(en);
 h+=labWeek(en);
 h+=labBoard(en);
 h+=labLabo(en);
 h+=labSeedRow(en);
 setH(document.getElementById('lab-body'),h);
 try{if(!localStorage.getItem('owlLabIntro')){localStorage.setItem('owlLabIntro','1');setTimeout(()=>labStage('how'),700);}}catch(e){}
}
function labStageHtml(k){const j=window._lab;if(!j)return '';const en=LANG()==='en';
 const C=j.counts||{};const n=k=>C[k]||0;
 const tile=(l,v,c,k)=>'<button class="ls'+(window._labTab===k?' on':'')+'" onclick="labTab(&#39;'+k+'&#39;)"><b style="color:'+c+'">'+v+'</b>'+l+'</button>';
 const FAM={structure:[en?'how it enters':'comment il entre','var(--accent-soft)'],meteo:[en?'the weather':'la m\u00e9t\u00e9o','var(--warn)'],cible:[en?'gain and loss limits':'gain et limite de perte','#b98cff'],rythme:[en?'when it trades':'quand il trade','#e8743b'],argent:[en?'the money':'l\u2019argent','var(--up-soft)'],donnees:[en?'the data':'les donn\u00e9es','var(--muted2)']};
 const VB={A:['\u2713\u2713','var(--up-soft)','rgba(46,204,113,.14)'],B:['\u2713','var(--warn)','rgba(232,197,90,.14)'],C:['\u2717','var(--down-soft)','rgba(255,92,92,.12)']};
 const ST={deployed:[en?'In the robot':'Dans le robot','var(--up-soft)'],candidate:[en?'To try':'\u00c0 essayer','#b98cff'],planned:[en?'To start':'\u00c0 lancer','#b98cff'],forward:[en?'Watching live':'Observ\u00e9 en direct','var(--accent-soft)'],observation:[en?'Not sure yet':'Pas encore s\u00fbr','var(--warn)'],idea:[en?'Idea':'Id\u00e9e','var(--warn)'],rejected:[en?'Said no':'\u00c9cart\u00e9e','var(--muted2)']};
 const chip=(t,c,bg)=>'<span class="pchip" style="color:'+c+';background:'+(bg||'rgba(255,255,255,.05)')+'">'+t+'</span>';
 const esc=x=>String(x||'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
 const item=it=>{const f=FAM[it.family]||FAM.donnees,v=VB[it.verdict],st=ST[it.status]||ST.idea;
  const badge=v?'<span class="lcb" style="color:'+v[1]+';background:'+v[2]+'">'+v[0]+'</span>':'<span class="lcb" style="background:rgba(255,255,255,.05);color:'+st[1]+'"><svg class="ic ic-s"><use href="#i-target"/></svg></span>';
  return '<div class="panel lc" onclick="labItem(&#39;'+it.id+'&#39;)" role="button" tabindex="0"><div class="lct">'+badge+'<div style="flex:1;min-width:0"><h4>'+esc(en?it.title_en:it.title_fr)+'</h4>'+
   '<div class="lcc">'+chip(st[0],st[1])+chip(f[0],f[1])+(it.robot==='oui'?chip(en?'robot: yes':'robot : oui','var(--up-soft)'):(it.robot==='candidat'?chip(en?'robot: candidate':'robot : candidat','#b98cff'):''))+'</div></div></div>'+
   '<div class="lcn">'+esc(en?it.note_en:it.note_fr)+'</div><div class="lcm"><span>'+esc(it.date||'')+'</span><span style="max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc(it.src||'')+'</span></div><svg class="ic chv"><use href="#i-chev"/></svg></div>';};
 const items=j.items||[];let h='';
 if(k==='ideas'){
  const L={trop_tot:[en?'too few trades':'pas assez de trades','var(--muted)'],a_tester:[en?'worth checking':'\u00e0 v\u00e9rifier','var(--up-soft)'],divergent:[en?'not clear':'pas net','var(--warn)']};
  h+='<div class="sec" style="margin:16px 8px 8px">'+(en?'What the real trades say so far':'Ce que disent les vrais trades pour l\u2019instant')+' <span class="hint">\u00b7 '+(en?'how often the robot won in each situation':'combien de fois le robot a gagn\u00e9 dans chaque situation')+'</span></div>';
  const pc=v=>v===null||v===undefined?'\u2014':v+'\u202f%';
  h+='<div class="panel" style="padding:4px 14px">'+(j.candidates||[]).map(c=>{const l=L[c.label]||L.trop_tot;const d=(c.win!==null&&c.rest_win!==null)?c.win-c.rest_win:null;
   return '<div class="kv"><div class="kvt"><b>'+esc(en?c.name_en:c.name_fr)+'</b><span>'+c.n+' trades \u00b7 '+pc(c.win)+' '+(en?'won, against':'gagn\u00e9s, contre')+' '+pc(c.rest_win)+' '+(en?'for the others':'pour les autres')+(d===null?'':' <b style="display:inline;font-size:.74rem;color:'+(d>=0?'var(--up-soft)':'var(--down-soft)')+'">('+(d>=0?'+':'')+d+')</b>')+'</span></div>'+chip(l[0],l[1])+'</div>';}).join('')+'</div>';
  h+='<div style="font-size:.72rem;color:var(--muted);margin:6px 8px 0;line-height:1.45">'+(en?'Under 30 trades a number means little; it is shown so you can watch it grow.':'Sous 30 trades, un chiffre veut dire peu de chose ; on le montre pour le voir grandir.')+'</div>';
  h+='<div class="sec" style="margin:18px 8px 8px">'+(en?'Ideas on the table':'Id\u00e9es sur la table')+'</div>'+items.filter(it=>it.status==='idea'||it.status==='observation').map(item).join('');
 }else if(k==='tests'){
  h+='<div class="panel labintro"><b style="font-size:.95rem">'+(en?'How we check an idea':'Comment on v\u00e9rifie une id\u00e9e')+'</b><div style="font-size:.84rem;color:var(--text2);line-height:1.5;margin-top:6px">'+(en?'We rerun the last 42 days of the market with the robot as it is, then with the idea. We look at the money at the end, the biggest hole along the way, and whether the first half and the second half of the period agree.':'On refait les 42 derniers jours du march\u00e9 avec le robot tel qu\u2019il est, puis avec l\u2019id\u00e9e. On regarde l\u2019argent \u00e0 la fin, le plus gros trou en chemin, et si la premi\u00e8re et la deuxi\u00e8me moiti\u00e9 de la p\u00e9riode disent la m\u00eame chose.')+'</div>'+
   '<div class="st"><div><b style="color:var(--up-soft)">\u2713\u2713</b>'+(en?'better on both halves':'mieux sur les deux moiti\u00e9s')+'</div><div><b style="color:var(--warn)">\u2713</b>'+(en?'a little better':'un peu mieux')+'</div><div><b style="color:var(--down-soft)">\u2717</b>'+(en?'no':'non')+'</div></div>'+
   '<div style="font-size:.8rem;color:var(--text2);line-height:1.5;margin-top:10px">'+(en?'Three looks at every idea. <b>42 days</b> gives the mark. <b>The long window</b> is all the history the terminal holds ('+(((j.auto||{}).days_long)||'\u2014')+' days today; it grows when the history grows). <b>The real trades</b> replay the idea on the exact entries the robot took since the journal began ('+(((j.auto||{}).real_n)||0)+' so far). Weaker on the last two is a caution, never a reason to drop an idea.':'Trois regards sur chaque id\u00e9e. <b>42 jours</b> donne la note. <b>La fen\u00eatre longue</b>, c\u2019est tout l\u2019historique que le terminal garde ('+(((j.auto||{}).days_long)||'\u2014')+' jours aujourd\u2019hui ; elle grandit avec l\u2019historique). <b>Les vrais trades</b> testent l\u2019id\u00e9e sur les entr\u00e9es exactes que le robot a prises depuis le d\u00e9but du journal ('+(((j.auto||{}).real_n)||0)+' pour l\u2019instant). Plus faible sur ces deux-l\u00e0, c\u2019est une prudence, jamais une raison d\u2019\u00e9carter une id\u00e9e.')+'</div></div>';
  const AU=j.auto||{},AV=AU.variants||[];
  if(AV.length){const mn=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(0);const VB2={A:['\u2713\u2713','var(--up-soft)','rgba(46,204,113,.14)'],B:['\u2713','var(--warn)','rgba(232,197,90,.14)'],C:['\u2717','var(--down-soft)','rgba(255,92,92,.12)'],'=':['=','var(--muted)','rgba(255,255,255,.05)']};
   const order={A:0,B:1,'=':2,C:3};const sorted=[...AV].sort((a,b)=>(order[a.verdict]??9)-(order[b.verdict]??9)||(b.diff_net||0)-(a.diff_net||0));
   h+='<div class="sec" style="margin:16px 8px 8px">'+(en?'Tested last night by the chercheur':'Test\u00e9 cette nuit par le chercheur')+' <span class="hint">\u00b7 '+AV.length+' '+(en?'what-ifs':'\u00ab et si \u00bb')+(AU.days?' \u00b7 '+AU.days+' '+(en?'days':'jours'):'')+'</span></div>';
   h+='<div class="panel" style="padding:4px 14px">'+sorted.map(v=>{const b=VB2[v.verdict]||VB2['='];const bt=AU.base||{};
    return '<div class="kv"><span class="lcb" style="width:30px;height:30px;font-size:.9rem;color:'+b[1]+';background:'+b[2]+'">'+b[0]+'</span><div class="kvt"><b>'+esc(en?v.title_en:v.title_fr)+'</b><span>'+(v.verdict==='='?(en?'no real change':'pas de vrai changement'):(en?'money ':'argent ')+mn(v.diff_net||0)+' \u00b7 '+(en?'biggest hole ':'plus gros trou ')+mn(v.diff_worst||0)+' \u00b7 '+(en?'halves':'moiti\u00e9s')+' '+mn(((v.h1||{}).net||0)-(((AU.base||{}).h1||{}).net||0))+' / '+mn(((v.h2||{}).net||0)-(((AU.base||{}).h2||{}).net||0)))+(v.long?' \u00b7 '+v.long.days+(en?' days: ':' jours : ')+v.long.verdict+' '+mn(v.long.diff_net||0):'')+(v.real?' \u00b7 '+(en?'real trades ':'vrais trades ')+mn(v.real.diff_net||0)+' ('+v.real.n_real+')':'')+(v.src==='chercheur'?' \u00b7 '+(en?'proposed by the chercheur':'propos\u00e9 par le chercheur'):'')+'</span></div></div>';}).join('')+'</div>';
   h+='<div style="font-size:.72rem;color:var(--muted);margin:6px 8px 0;line-height:1.45">'+(en?'\u2713\u2713 more money on both halves of the period. \u2713 a smaller hole without losing money, or more money with one half agreeing. \u2717 no. = nothing changed.':'\u2713\u2713 plus d\u2019argent sur les deux moiti\u00e9s de la p\u00e9riode. \u2713 un trou moins profond sans perdre d\u2019argent, ou plus d\u2019argent avec une moiti\u00e9 d\u2019accord. C : non. = : rien ne change.')+'</div>';}
  h+='<div class="sec" style="margin:16px 8px 8px">'+(en?'Worth trying':'\u00c0 essayer')+'</div>'+items.filter(it=>it.status==='candidate'||it.status==='planned').map(item).join('')+'<div class="sec" style="margin:18px 8px 8px">'+(en?'We said no':'On a dit non')+' <span class="hint">\u00b7 '+(en?'kept here so nobody proposes them again':'gard\u00e9es ici pour ne pas les reproposer')+'</span></div>'+items.filter(it=>it.status==='rejected').map(item).join('');
 }else if(k==='forward'){
  const tw=j.twin||{},fw=j.forward||{},lv=fw.live||{},e=j.e017||{};
  const mn=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
  const spark=(cv)=>{if(!cv||cv.length<2)return '';const mx=Math.max(...cv),mnv=Math.min(...cv),sp=Math.max(1e-6,mx-mnv);const pts=cv.map((v,i)=>((i/(cv.length-1))*296+2).toFixed(1)+','+(40-((v-mnv)/sp)*36+2).toFixed(1)).join(' ');const z=(40-((0-mnv)/sp)*36+2).toFixed(1);return '<svg viewBox="0 0 300 44" style="width:100%;height:44px;display:block;margin-top:8px"><line x1="2" y1="'+z+'" x2="298" y2="'+z+'" style="stroke:var(--border2)" stroke-dasharray="3 4"/><polyline points="'+pts+'" fill="none" style="stroke:var(--accent-soft)" stroke-width="1.6"/></svg>';};
  const cell=(l,v,c)=>'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:9px 4px;text-align:center"><b style="display:block;font-size:1rem;'+(c?'color:'+c:'')+'">'+v+'</b><span style="font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+l+'</span></div>';
  const days=tw.since?Math.max(1,Math.round((Date.now()/1000-tw.since)/86400)):0;
  h+='<div class="panel labintro"><b style="font-size:.95rem">'+(en?'Robots that play for pretend':'Des robots qui jouent pour de faux')+'</b><div style="font-size:.84rem;color:var(--text2);line-height:1.5;margin-top:6px">'+(en?'Before an idea touches a real account, a copy of the robot runs it on paper, next to the real one, with no money. We compare them over weeks.':'Avant qu\u2019une id\u00e9e touche un vrai compte, une copie du robot l\u2019essaie sur papier, \u00e0 c\u00f4t\u00e9 du vrai, sans argent. On les compare pendant des semaines.')+'</div></div>';
  h+='<div class="panel" style="margin-top:12px"><div class="lbl">'+(en?'The twin without brakes':'Le jumeau sans freins')+'</div>'+
   '<div style="font-size:.8rem;color:var(--muted2);margin-top:4px;line-height:1.45">'+(en?'Takes every trade, never stops for the weather or after a loss. Playing for pretend since '+days+' days. It shows what the brakes cost and what they avoid.':'Prend tous les trades, ne s\u2019arr\u00eate jamais pour la m\u00e9t\u00e9o ni apr\u00e8s une perte. Joue pour de faux depuis '+days+' jours. Il montre ce que les freins co\u00fbtent et ce qu\u2019ils \u00e9vitent.')+'</div>'+
   '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px">'+cell('trades',tw.trades||0)+cell(en?'win':'gagn\u00e9s',tw.win===null||tw.win===undefined?'\u2014':tw.win+' %')+cell('net',mn(tw.net||0),(tw.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+cell(en?'last 20':'20 derniers',mn(tw.rolling20||0),(tw.rolling20||0)>=0?'var(--up-soft)':'var(--down-soft)')+'</div>'+spark(tw.curve)+'<div style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:4px;display:flex;justify-content:space-between"><span>'+(en?'net, last 60 trades':'net cumul\u00e9, 60 derniers trades')+'</span><span>'+(tw.since?(en?'since ':'depuis le ')+new Date(tw.since*1000).toLocaleDateString(en?'en-GB':'fr-FR',{day:'2-digit',month:'2-digit'}):'')+'</span></div>'+
   '<div style="font-size:.74rem;color:var(--muted);margin-top:6px">'+(en?'The real robot, with its brakes, over the same period: ':'Le vrai robot, avec ses freins, sur la m\u00eame p\u00e9riode : ')+(lv.trades||0)+' trades \u00b7 '+mn(lv.net||0)+' \u00b7 '+(en?'last 20':'20 derniers')+' '+mn(lv.rolling20||0)+'</div></div>';
  h+='<div class="panel" style="margin-top:12px"><div class="lbl">'+(en?'When people are forced to sell all at once':'Quand des gens sont forc\u00e9s de vendre d\u2019un coup')+'</div><div style="display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin-top:10px">'+cell(en?'cases recorded':'cas enregistr\u00e9s',e.events||0)+cell(en?'cases needed to judge':'cas n\u00e9cessaires pour juger',e.need||30)+'</div><div style="font-size:.78rem;color:var(--muted2);margin-top:8px;line-height:1.45">'+(en?'Does the price bounce after that? We record each case without looking at the result, so we do not fool ourselves. We judge after 30 cases.':'Le prix rebondit-il apr\u00e8s \u00e7a ? On note chaque cas sans regarder le r\u00e9sultat, pour ne pas se raconter d\u2019histoires. On jugera apr\u00e8s 30 cas.')+'</div></div>';
  const TW=j.twins||[];
  if(TW.length){h+='<div class="sec" style="margin:16px 8px 8px">'+(en?'Twins started by the chercheur':'Jumeaux lanc\u00e9s par le chercheur')+'</div>'+TW.map(t=>'<div class="panel" style="margin-top:10px"><div class="lbl">'+esc(en?t.title_en:t.title_fr)+'</div><div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px">'+cell('trades',t.trades||0)+cell(en?'win':'gagn\u00e9s',t.win===null||t.win===undefined?'\u2014':t.win+' %')+cell('net',mn(t.net||0),(t.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+cell(en?'last 20':'20 derniers',mn(t.rolling20||0),(t.rolling20||0)>=0?'var(--up-soft)':'var(--down-soft)')+'</div>'+duelBlock(t.duel,en)+'<div style="font-size:.72rem;color:var(--muted);margin-top:8px">'+(en?'since ':'depuis le ')+esc((t.started||'').slice(0,10))+' \u00b7 '+(t.alive?(en?'running':'en marche'):(en?'stopped':'arr\u00eat\u00e9'))+' \u00b7 '+(en?'playing for pretend':'joue pour de faux')+'</div></div>').join('');}
  h+=items.filter(it=>it.status==='planned').map(item).join('');
 }else{
  h+='<div class="panel labintro"><b style="font-size:.95rem">'+(en?'The rules the robot follows today':'Les r\u00e8gles que le robot suit aujourd\u2019hui')+'</b><div style="font-size:.84rem;color:var(--text2);line-height:1.5;margin-top:6px">'+(en?'Each one earned its place through the three steps. Tap a card to see why.':'Chacune a gagn\u00e9 sa place en passant les trois \u00e9tapes. Touchez une carte pour voir pourquoi.')+'</div></div>';
  h+=items.filter(it=>it.status==='deployed').map(item).join('');
  h+='<div class="panel" style="margin-top:14px;border-color:rgba(59,130,246,.35)"><div class="lbl">'+(en?'How a new rule gets in':'Comment une nouvelle r\u00e8gle entre')+'</div><div style="font-size:.86rem;color:var(--text);line-height:1.6;margin-top:6px">'+(en?'1. An idea comes from the real trades or from the Owl.<br>2. We replay it on the last 42 days of the market.<br>3. A copy of the robot tries it for pretend, next to the real one.<br>4. It goes on the demo account first, then on real accounts, one at a time, on the Owl\u2019s decision.<br>5. We keep watching it; if it starts losing, we take it out.':'1. Une id\u00e9e vient des vrais trades ou du Owl.<br>2. On la teste sur les 42 derniers jours du march\u00e9.<br>3. Une copie du robot l\u2019essaie pour de faux, \u00e0 c\u00f4t\u00e9 du vrai.<br>4. Elle passe d\u2019abord sur le compte d\u00e9mo, puis sur les vrais comptes, un par un, sur d\u00e9cision du Owl.<br>5. On continue de la surveiller ; si elle se met \u00e0 perdre, on la retire.')+'</div></div>';
 }
 return h;
}
// ---- 2026-09-29 (owner): the story board - where every idea stands ----
// 2026-10-02 (owner): four columns, plain words. "Decided" is gone - the
// lab deploys a duel winner by itself, so there is nothing left to decide.
const JCOLS=[['idea','Id\u00e9es','Ideas','#d2b8ff','id\u00e9es','ideas'],['replay','Test\u00e9es','Tested','#b98cff','test\u00e9es','tested'],['test','Pour de faux','For pretend','var(--accent-soft)','pour de faux','for pretend'],['live','Dans le robot','In the robot','var(--up-soft)','dans le robot','in the robot']];
const JSTAGE={idea:'ideas',replay:'tests',test:'forward',live:'decisions'};
// 2026-10-02 (owner): the letter alone taught nobody anything. These are
// the same three verdicts in words, used on the cards beside it.
// 2026-10-02 (owner): no bare letter anywhere a member looks. The mark
// is what a card wears; the word is what a tile or a sentence says.
function vMark(v){return {A:'\u2713\u2713',B:'\u2713',C:'\u2717','=':'='}[v]||'';}
function vShort(v,en){return {A:en?'better':'mieux',B:en?'a bit':'un peu',C:en?'no':'non','=':en?'same':'pareil'}[v]||'';}
function vWord(v,en){
 if(v==='A')return en?'better on both halves':'mieux sur les deux moiti\u00e9s';
 if(v==='B')return en?'a little better':'un peu mieux';
 if(v==='C')return en?'no':'non';
 if(v==='=')return en?'no change':'sans changement';
 return '';
}
function labMaps(en){return {FAM:{structure:[en?'how it enters':'comment il entre','var(--accent-soft)'],meteo:[en?'the weather':'la m\u00e9t\u00e9o','var(--warn)'],cible:[en?'gain and loss limits':'gain et limite de perte','#b98cff'],rythme:[en?'when it trades':'quand il trade','#e8743b'],argent:[en?'the money':'l\u2019argent','var(--up-soft)'],donnees:[en?'the data':'les donn\u00e9es','var(--muted2)']},
 VB:{A:['\u2713\u2713','var(--up-soft)','rgba(46,204,113,.14)'],B:['\u2713','var(--warn)','rgba(232,197,90,.14)'],C:['\u2717','var(--down-soft)','rgba(255,92,92,.12)']}};}
const lchip=(t,c,bg)=>'<span class="pchip" style="color:'+c+';background:'+(bg||'rgba(255,255,255,.05)')+'">'+t+'</span>';
function labSeeds(j){return (j.candidates||[]).map(c=>Object.assign({sid:'seed_'+c.id},c));}
function jGet(id){return ((window._lab||{}).journeys||[]).find(j=>j.id===id||(j.keys||[]).indexOf(id)>=0)||null;}
function jLine(j,en){const S=j.steps||{};const mn=v=>(v>=0?'+$':'-$')+Math.abs(v||0).toFixed(0);
 if(j.col==='live'){const w=(S.live||{}).watch;const wl=w&&w.labo?' \u00b7 '+(en?'watched: ':'surveill\u00e9e : ')+(w.labo.trades||0)+' / '+(w.need||30)+' trades \u00b7 '+(en?'lab ':'labo ')+'<b style="color:'+((w.labo.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+'">'+mn(w.labo.net)+'</b> \u00b7 '+(en?'real robot ':'vrai robot ')+'<b>'+mn(w.real.net)+'</b>':'';
  return (en?'in the robot since ':'dans le robot depuis le ')+_escS((S.live||{}).date||'')+((S.live||{}).labo?' \u00b7 '+(en?'the lab\u2019s robot':'robot du labo'):'')+wl;}
 if(j.col==='test'){const t=S.test||{};if(t.forward)return en?'watched live, no money':'observ\u00e9e en direct, sans argent';const d=t.duel;const du=d&&d.twin?' \u00b7 '+(en?'robot ':'robot ')+'<b style="color:'+((d.real.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+'">'+mn(d.real.net)+'</b> '+(en?'same period':'m\u00eame p\u00e9riode'):'';return (t.status==='stopped'?(en?'twin stopped':'jumeau arr\u00eat\u00e9'):(en?'twin playing for pretend':'jumeau qui joue pour de faux'))+' \u00b7 '+(t.trades||0)+' / '+((d&&d.need)||30)+' trades \u00b7 '+(en?'twin ':'jumeau ')+'<b style="color:'+((t.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+'">'+mn(t.net)+'</b>'+du;}
 if(j.col==='replay'){const r=S.replay||{};const dd=S.decision||{};
  if(!r.verdict&&dd.d)return (dd.d==='yes'?'<b style="color:var(--up-soft)">'+(en?'yes':'oui')+'</b>':'<b style="color:var(--down-soft)">'+(en?'no':'non')+'</b> \u00b7 '+(en?'the numbers said no':'les chiffres ont dit non'))+(dd.date?' \u00b7 '+_escS(dd.date):'');
  const c={A:'var(--up-soft)',B:'var(--warn)',C:'var(--down-soft)'}[r.verdict]||'var(--muted)';return '<b style="color:'+c+'">'+(vShort(r.verdict,en)||'\u2014')+'</b>'+(r.streak>1?' '+r.streak+(en?' nights in a row':' nuits de suite'):(r.nights?' '+(en?'last night':'cette nuit'):(r.hand?(en?' by hand':' \u00e0 la main'):(en?' first test':' premier test'))))+(r.diff_net!==undefined?' \u00b7 '+(en?'money ':'argent ')+mn(r.diff_net)+' \u00b7 '+(en?'hole ':'trou ')+mn(r.diff_worst):'');}
 return en?'waiting for its first night of testing':'attend sa premi\u00e8re nuit de test';}
function jCard(j,en){const M=labMaps(en);const col=JCOLS.find(c=>c[0]===j.col)||JCOLS[0];const S=j.steps||{};const r=S.replay||{};const v=M.VB[r.verdict];const esc=_escS;
 const badge=v?'<span class="lcb" style="color:'+v[1]+';background:'+v[2]+'">'+v[0]+'</span>':'<span class="lcb" style="background:rgba(255,255,255,.05);color:'+col[3]+'"><svg class="ic ic-s"><use href="#i-target"/></svg></span>';
 const f=M.FAM[j.family]||M.FAM.donnees;const d=S.decision||{};
 // 2026-10-02 (owner): the verdict in words, leading, because "B" alone
 // told a reader nothing. The letter survives in the badge for anyone
 // following the chercheur's own shorthand.
 let chips='';
 if(r.verdict&&vWord(r.verdict,en))
  chips+=lchip(vWord(r.verdict,en),v?v[1]:'var(--muted)',
   v?v[2]:'rgba(255,255,255,.05)');
 chips+=lchip(f[0],f[1]);
 if(r.verdict&&r.streak>1)chips+=lchip(r.streak+(en?' nights in a row':' nuits de suite'),v?v[1]:'var(--muted)');
 if(j.kind==='proposal'&&j.col!=='idea')chips+=lchip(en?'by the chercheur':'par le chercheur','#b98cff');
 if(j.kind==='battery')chips+=lchip(en?'asked every night':'question de chaque nuit','var(--muted2)');
 if(j.stale)chips+=lchip(en?'to re-check':'\u00e0 rev\u00e9rifier','var(--warn)');
 if(j.archived)chips+=lchip(en?'set aside':'mise de c\u00f4t\u00e9','var(--muted2)');
 if(j.reference)chips+=lchip(en?'yardstick · never for the robot':'étalon · jamais pour le robot','var(--muted2)');
 if(j.critique&&j.critique.verdict==='bloque')chips+=lchip(en?'the critic said no':'le critique a dit non','var(--down-soft)','rgba(255,92,92,.12)');
 if(j.critique&&j.critique.verdict==='doute')chips+=lchip(en?'the critic doubts':'le critique doute','var(--warn)','rgba(232,197,90,.14)');
 if(d.d==='yes'&&j.col!=='live')chips+=lchip(en?'yes, waiting':'oui, en attente','var(--up-soft)');
 if(j.robot==='oui'&&j.col!=='live')chips+=lchip(en?'robot: yes':'robot : oui','var(--up-soft)');
 const note=en?(j.note_en||j.note_fr):(j.note_fr||j.note_en);
 const mn=x=>(x>=0?'+$':'-$')+Math.abs(x||0).toFixed(0);
 const tile=(l,x,c)=>'<div style="flex:1;background:var(--tile-bg);border:1px solid var(--tile-bd);border-radius:12px;padding:8px 4px;text-align:center"><b style="display:block;font-size:.92rem;color:'+c+'">'+x+'</b><span style="font-size:.56rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+l+'</span></div>';
 const tiles=(r.diff_net!==undefined&&j.col!=='live'&&!j.stale)?'<div style="display:flex;gap:6px;margin-top:10px">'+tile(en?'money':'argent',mn(r.diff_net),(r.diff_net||0)>=0?'var(--up-soft)':'var(--down-soft)')+tile(en?'biggest hole':'plus gros trou',mn(r.diff_worst),(r.diff_worst||0)<=0?'var(--up-soft)':'var(--down-soft)')+tile(en?'halves':'moiti\u00e9s',mn(r.h1)+' / '+mn(r.h2),((r.h1||0)>0&&(r.h2||0)>0)?'var(--up-soft)':'var(--text)')+'</div>':'';
 const line=(j.col==='test'||j.col==='live'||(j.col==='replay'&&d.d))?'<div style="font-size:.76rem;color:var(--text2);margin-top:8px;line-height:1.45">'+jLine(j,en)+'</div>':'';
 return '<div class="panel lc" data-jid="'+esc(j.id)+'" style="padding-right:14px" onclick="labJourney(&#39;'+esc(j.id)+'&#39;)" role="button" tabindex="0"><div class="lct">'+badge+'<div style="flex:1;min-width:0"><h4>'+esc(en?j.title_en:j.title_fr)+'</h4><div class="lcc">'+chips+'</div></div></div>'+
  (note?'<div class="lcn" style="display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">'+esc(note)+'</div>':'')+tiles+(tiles?xTiles(r,en):'')+line+
  // 2026-10-02: the line above already says "dans le robot depuis le
  // ...", so repeating the date here was saying it twice; and j.src is a
  // study id (E010) that belongs in the detail sheet, not on a card.
  '<div class="lcm"><span>'+(j.col==='live'?'':esc(j.date||''))+'</span><span style="color:var(--accent-soft);font-weight:700">'+(en?'Its story':'Son histoire')+' \u203a</span></div></div>';}
function seedCard(c,en){const L={trop_tot:[en?'too few trades':'pas assez de trades','var(--muted)'],a_tester:[en?'worth checking':'\u00e0 v\u00e9rifier','var(--up-soft)'],divergent:[en?'not clear':'pas net','var(--warn)'],doublon:[en?'same trades as another':'m\u00eames trades qu\u2019une autre','var(--muted)'],invalide:[en?'badly written':'mal \u00e9crite','var(--down-soft)']};const l=L[c.label]||L.trop_tot;const esc=_escS;
 const pc=x=>x===null||x===undefined?'\u2014':x+'\u202f%';const d=(c.win!==null&&c.rest_win!==null)?c.win-c.rest_win:null;
 return '<div class="panel lc" style="padding-right:14px" onclick="labSeed(&#39;'+esc(c.id)+'&#39;)" role="button" tabindex="0"><div class="lct"><span class="lcb" style="background:rgba(255,255,255,.05);color:'+l[1]+'"><svg class="ic ic-s"><use href="#i-activity"/></svg></span><div style="flex:1;min-width:0"><h4>'+esc(en?c.name_en:c.name_fr)+'</h4><div class="lcc">'+lchip(en?'clue':'piste','var(--warn)')+lchip(l[0],l[1])+(c.by==='chercheur'?lchip(en?'by the chercheur':'par le chercheur','#b98cff'):'')+(function(){const a=seedAsk(c.id);return a?lchip(a.status==='open'?(en?'asked the chercheur':'demand\u00e9 au chercheur'):(a.status==='proposed'?(en?'became an idea':'devenue une id\u00e9e'):(en?'answered':'r\u00e9pondu')),'#b98cff','rgba(185,140,255,.14)'):'';})()+'</div></div></div>'+
 // 2026-10-02 (owner): under 30 trades this printed a confident
 // comparison - "10 trades, 20 % contre 67 % (-47)" - which reads as
 // a finding and is noise. Same gate as the multi-timeframe payoff
 // card: say how far off it is, show the figure when it earns it.
 // (the line above already ends in '+', so this must NOT start with one:
 //  '...' + +('<div>') is unary plus on a string, which is NaN)
 ((c.n||0)>=LAB_MIN_N
   ? '<div class="lcn">'+c.n+' trades \u00b7 '+pc(c.win)+' '+
     (en?'won, against':'gagn\u00e9s, contre')+' '+pc(c.rest_win)+' '+
     (en?'for the others':'pour les autres')+(d===null?'':
      ' <b style="color:'+(d>=0?'var(--up-soft)':'var(--down-soft)')+
      '">('+(d>=0?'+':'')+d+')</b>')+'</div>'
   : '<div class="lcn" style="color:var(--muted)">'+(c.n||0)+
     ' trades \u00b7 '+(en
       ? 'still '+(LAB_MIN_N-(c.n||0))+' to go before this says anything'
       : 'encore '+(LAB_MIN_N-(c.n||0))+
         ' avant de pouvoir se prononcer')+'</div>')+
 '<div class="lcm"><span>'+(en?'seen in the real trades':'vu dans les vrais trades')+'</span><span style="color:var(--accent-soft);font-weight:700">'+(en?'Details':'D\u00e9tails')+' \u203a</span></div></div>';}
// 2026-10-02 (owner): a first visit used to land on IDEAS - eleven seeds
// that all say "not enough trades". Land on what is settled instead; the
// rail is right there for anyone who wants the rest.
// 2026-10-02 (owner): the page opens on what is new. The column you were
// on survives within a visit, not across visits - a returning reader
// should meet tonight's ideas, not last week's tab.
function jCol(){let i=window._jcol;if(!(i>=0&&i<JCOLS.length)){const J=((window._lab||{}).journeys||[]);
 const pref=['idea','live','test','replay'];
 i=-1;for(const k of pref){if(J.some(x=>x.col===k)){i=JCOLS.findIndex(c=>c[0]===k);break;}}
 if(i<0)i=0;}return i;}
function jCount(k){const j=window._lab||{};return (j.journeys||[]).filter(x=>x.col===k&&!x.archived).length;}
function jRail(en){const cur=jCol();
 return '<div class="jrail" id="jrail">'+JCOLS.map(([k,fr,eg,c,fs,es],i)=>'<div class="jn'+(i===cur?' on':'')+(i<cur?' past':'')+'" onclick="jGo('+i+')" role="tab" aria-selected="'+(i===cur?'true':'false')+'" style="--jc:'+c+'"><i>'+jCount(k)+'</i><span>'+(en?es:fs)+'</span></div>').join('')+'</div>';}
function jFold(id,label,items,en){if(!items.length)return '';
 return '<button class="tfc jfoldbtn" onclick="const f=document.getElementById(&#39;'+id+'&#39;);f.hidden=!f.hidden;this.firstChild.textContent=f.hidden?&#39;\u25b8&#39;:&#39;\u25be&#39;"><span>\u25b8</span>&nbsp;'+label+'</button><div id="'+id+'" hidden>'+items.map(x=>jCard(x,en)).join('')+'</div>';}
function jStage(en){const j=window._lab||{};const J=j.journeys||[];const cur=jCol();const [k,fr,eg,c]=JCOLS[cur];let L=J.filter(x=>x.col===k);
 const ST=x=>x.steps||{};const VO={A:0,B:1,'=':2,C:3};
 let cards;
 if(k==='replay'){const AR=L.filter(x=>x.archived);L=L.filter(x=>!x.archived);
  const vd=x=>(ST(x).replay||{}).verdict||((ST(x).decision||{}).d==='no'?'C':'');
  const S2=[...L].sort((a,b)=>((VO[vd(a)]??2)-(VO[vd(b)]??2))||(((ST(b).replay||{}).diff_net||0)-((ST(a).replay||{}).diff_net||0)));
  const keep=S2.filter(x=>vd(x)!=='C'),no=S2.filter(x=>vd(x)==='C');
  cards=keep.map(x=>jCard(x,en)).join('')+(AR.length?'<div class="pf-cap" style="margin-top:10px">'+AR.length+' '+(en?(AR.length>1?'ideas set aside after three nights of no':'idea set aside after three nights of no'):(AR.length>1?'id\u00e9es mises de c\u00f4t\u00e9 apr\u00e8s trois nuits de non':'id\u00e9e mise de c\u00f4t\u00e9 apr\u00e8s trois nuits de non'))+'. '+(en?'The chercheur still knows about them.':'Le chercheur les conna\u00eet toujours.')+'</div>':'')+
   jFold('jfold',no.length+' '+(en?(no.length>1?'ideas said no':'idea said no'):(no.length>1?'id\u00e9es ont dit non':'id\u00e9e a dit non')),no,en);}
 else if(k==='test'){const off=x=>['stopped','retired','reverted'].indexOf((ST(x).test||{}).status)>=0;const on=L.filter(x=>!off(x)),no=L.filter(off);
  cards=on.map(x=>jCard(x,en)).join('')+jFold('jfold2',no.length+' '+(en?(no.length>1?'twins stopped':'twin stopped'):(no.length>1?'jumeaux arr\u00eat\u00e9s':'jumeau arr\u00eat\u00e9')),no,en);}
 else if(k==='idea'){cards=[...L].sort((a,b)=>(VO[(ST(a).replay||{}).verdict]??2)-(VO[(ST(b).replay||{}).verdict]??2)).map(x=>jCard(x,en)).join('');}
 else cards=L.map(x=>jCard(x,en)).join('');
 const sub={idea:[en?'The researcher\u2019s new ideas. Each one gets its first full night of testing tonight.':'Les nouvelles id\u00e9es du chercheur. Chacune passe sa premi\u00e8re vraie nuit de test ce soir.'],replay:[en?'Tested on the last 42 days of the market, against the robot as it is.':'Test\u00e9es sur les 42 derniers jours du march\u00e9, contre le robot tel qu\u2019il est.'],test:[en?'A copy of the robot tries them live, with no money, next to the real one.':'Une copie du robot les essaie en direct, sans argent, \u00e0 c\u00f4t\u00e9 du vrai.'],live:[en?'The rules the robot follows today.':'Les r\u00e8gles que le robot suit aujourd\u2019hui.']}[k][0];
 return '<div class="jhead"><div style="flex:1;min-width:0"><div class="jht" style="color:'+c+'">'+(en?eg:fr)+' <b>'+L.length+'</b></div><div class="jhs">'+sub+'</div></div><button class="tfc" style="flex:none" onclick="labStage(&#39;'+JSTAGE[k]+'&#39;)">'+(en?'The stage':'L\u2019\u00e9tape')+' \u203a</button></div>'+
  '<div class="jcards" id="jcards">'+(cards||'<div class="jempty">'+(k==='idea'?(en?'Nothing new tonight.':'Rien de nouveau ce soir.'):(en?'Nothing here right now.':'Rien ici pour l\u2019instant.'))+'</div>')+'</div>'+
  '<div class="jfoot">'+(cur>0?'<button class="tfc" onclick="jGo('+(cur-1)+')">\u2039 '+(en?JCOLS[cur-1][5]:JCOLS[cur-1][4])+'</button>':'<span></span>')+(cur<JCOLS.length-1?'<button class="tfc" onclick="jGo('+(cur+1)+')">'+(en?JCOLS[cur+1][5]:JCOLS[cur+1][4])+' \u203a</button>':'<span></span>')+'</div>';}
const LAB_MIN_N = 30;   // trades before a seed figure is worth printing
// 2026-10-02 (owner): "he must replace me, he is now digital Kino" - the
// chercheur is awake during the day; this is his last word, and when.
function labLive(en){const j=window._lab||{};const V=j.veille||[];if(!V.length)return '';const v=V[V.length-1];const esc=_escS;
 let ago='';try{const m=Math.round((Date.now()-new Date(v.t).getTime())/60000);ago=m<60?(en?m+' min ago':'il y a '+m+' min'):(en?Math.round(m/60)+' h ago':'il y a '+Math.round(m/60)+' h');}catch(e){}
 const K={observation:[en?'saw':'a vu','var(--accent-soft)'],piste:[en?'opened a clue':'a ouvert une piste','var(--warn)'],essai:[en?'ran a test':'a fait un essai','#b98cff'],idee:[en?'proposed an idea':'a propos\u00e9 une id\u00e9e','var(--up-soft)'],reponse:[en?'answered':'a r\u00e9pondu','#b98cff'],rien:[en?'is waiting':'attend','var(--muted)']}[v.kind]||[en?'noted':'a not\u00e9','var(--muted)'];
 return '<div class="lh-live"><span class="lh-dot"></span><span style="flex:1;min-width:0"><b>Le chercheur</b> <span style="color:'+K[1]+'">'+K[0]+'</span>'+(ago?' <span class="lh-ago">\u00b7 '+ago+'</span>':'')+'<span class="lh-say">'+esc(en?(v.en||v.fr):(v.fr||v.en))+'</span></span></div>';}
function labHero(en){
 const j=window._lab||{};const N=j.note||{};const esc=_escS;
 if(!N.date)return '<div class="jempty" style="margin-top:12px">'+(en?'The researcher has not had its first night yet.':'Le chercheur n\u2019a pas encore fait sa premi\u00e8re nuit.')+'</div>';
 const cc=(j.auto||{}).counts||{};
 const tot=(cc.A||0)+(cc.B||0)+(cc.C||0)+(cc['=']||0);
 const worth=(cc.A||0)+(cc.B||0);
 const PRn=(j.proposals||[]).filter(p=>p.status==='pending'||!p.status).length;
 const head=String(en?(N.headline_en||N.headline_fr):(N.headline_fr||N.headline_en)||'').split('**').join('');
 const stat=(n,l,c)=>'<div><b style="color:'+c+'">'+n+'</b><span>'+l+'</span></div>';
 return '<button class="labhero" onclick="labNight()">'+
  '<div class="lh-top"><span class="lh-eye">'+(en?'Last night':'Cette nuit')+' \u00b7 '+esc(N.date)+'</span><span class="lh-read">'+(en?'Read':'Lire')+' \u203a</span></div>'+
  (head?'<div class="lh-head">'+esc(head)+'</div>':'')+labLive(en)+
  '<div class="lh-stats">'+stat(tot,en?'ideas tested':'id\u00e9es test\u00e9es','var(--text)')+stat(worth,en?'worth a look':'\u00e0 regarder','var(--up-soft)')+stat(PRn,en?(PRn>1?'new ideas':'new idea'):(PRn>1?'nouvelles id\u00e9es':'nouvelle id\u00e9e'),'#d2b8ff')+'</div>'+
  (window._labParityOk?'<div class="lh-ok"><svg class="ic ic-s"><use href="#i-check"/></svg>'+(en?'The test still matches the robot, rule by rule':'Le test correspond toujours au robot, r\u00e8gle par r\u00e8gle')+'</div>':'')+
  '</button>';}
// 2026-10-02 (owner): the clues leave the board. They are a waiting room
// (not one has ever become an idea) - one quiet row, and a panel for
// anyone curious.
// 2026-10-03 (owner): the lab's own robot, where ideas go to prove
// themselves - it was invisible (not a member, so not in Le Nid).
function labLabo(en){const j=window._lab||{};const L=j.labo;if(!L)return '';const esc=_escS;
 const mn=v=>(v>=0?'+$':'-$')+Math.abs(v||0).toFixed(2);
 const dep=L.deployed,w=L.watch;
 let what;
 if(dep){const t=esc(en?(dep.title_en||dep.title_fr):(dep.title_fr||dep.title_en));
  what=(en?'Trying ':'Essaie ')+'\u00ab '+t+' \u00bb'+(en?' since ':' depuis le ')+esc(dep.date||'')+
   (w&&w.labo?' \u00b7 '+(w.labo.trades||0)+' / '+(w.need||30)+' trades \u00b7 '+(en?'lab ':'labo ')+'<b style="color:'+((w.labo.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+'">'+mn(w.labo.net)+'</b> \u00b7 '+(en?'real robot ':'vrai robot ')+'<b>'+mn((w.real||{}).net)+'</b>':'')+
   (L.confirmed?' \u00b7 <span style="color:var(--up-soft)">'+(en?'confirmed':'confirm\u00e9e')+'</span>':'');}
 else if(L.paused)what=en?'<b style="color:var(--warn)">Paused by the Owl</b>'+(L.paused_since?' \u00b7 '+esc(L.paused_since):'')+'. Runs the robot\u2019s base rules; no idea goes in until the brake is lifted.':'<b style="color:var(--warn)">En pause, par le Owl</b>'+(L.paused_since?' \u00b7 '+esc(L.paused_since):'')+'. Suit les r\u00e8gles de base du robot ; aucune id\u00e9e n\u2019entre tant que le frein est tir\u00e9.';
 else what=en?'Runs the robot\u2019s base rules. A duel winner goes in here first, by itself.':'Suit les r\u00e8gles de base du robot. Une id\u00e9e qui gagne son duel entre ici en premier, toute seule.';
 const tile=(l,x,c)=>'<div><b style="color:'+(c||'var(--text)')+'">'+x+'</b><span>'+l+'</span></div>';
 // 2026-10-03 (owner): every night the gates are rehearsed with a pretend
 // winner in a sandbox - the card says whether every door still closes
 const R=L.rehearsal;let reh='';
 if(R){reh='<div class="lablabo-reh'+(R.ok?'':' bad')+'">'+(R.ok?'<svg class="ic ic-s"><use href="#i-check"/></svg>':'<b>!</b>')+
   (R.ok?(en?'Every gate rehearsed last night, '+R.passed+' of '+R.total+' fired':'Chaque contr\u00f4le r\u00e9p\u00e9t\u00e9 cette nuit, '+R.passed+' sur '+R.total+' ont ferm\u00e9')
        :(en?'Rehearsal: '+((R.misses||[])[0]||{}).en:'R\u00e9p\u00e9tition : '+((R.misses||[])[0]||{}).fr))+(R.date?' <span>\u00b7 '+esc(R.date)+'</span>':'')+'</div>';}
 // the hand brake - Kino only (the server checks the password too)
 let adm=false;try{adm=!!((window._d||{}).is_master||localStorage.getItem('owl_adm'));}catch(e){}
 const brake=adm?'<button class="shbtn '+(L.paused?'shmain':'shghost')+' lablabo-brake" onclick="labPause('+(L.paused?0:1)+')">'+(L.paused?(en?'Lift the brake':'Rel\u00e2cher le frein'):(en?'Pull the brake':'Tirer le frein'))+'</button>':'';
 return '<div class="panel lablabo'+(L.paused?' paused':'')+'"><div class="lbl"><span class="lab-dot" style="background:'+(L.paused?'var(--warn)':(L.alive?'var(--up)':'var(--muted)'))+'"></span>'+(en?'The lab\u2019s robot':'Le robot du labo')+'<span class="hint">\u00b7 '+(en?'demo money':'argent de d\u00e9monstration')+'</span></div>'+
  '<div class="lablabo-what">'+what+'</div>'+
  '<div class="lablabo-tiles">'+tile(en?'trades':'trades',L.trades)+tile(en?'won':'gagn\u00e9s',L.trades?Math.round(100*L.won/L.trades)+'\u202f%':'\u2014')+tile(en?'since start':'depuis le d\u00e9but',mn(L.net),(L.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+'</div>'+
  reh+brake+
  (L.since?'<div class="pf-cap">'+(en?'Started ':'D\u00e9marr\u00e9 le ')+esc(L.since)+(L.start?' \u00b7 '+(en?'with ':'avec ')+'$'+L.start.toFixed(2):'')+' \u00b7 '+(en?'real accounts still need your tap':'les vrais comptes attendent toujours votre accord')+'</div>':'')+'</div>';}
async function labPause(on){const en=LANG()==='en';
 const Q=on?[en?'Pull the brake?':'Tirer le frein ?',en?'No idea goes into the lab\u2019s robot while it is pulled. An idea already inside comes back out now; the twins keep playing for pretend.':'Aucune id\u00e9e n\u2019entre dans le robot du labo tant qu\u2019il est tir\u00e9. Une id\u00e9e d\u00e9j\u00e0 dedans ressort maintenant ; les jumeaux continuent pour de faux.',en?'Pull':'Tirer']
            :[en?'Lift the brake?':'Rel\u00e2cher le frein ?',en?'Duel winners go in by themselves again, on demo money.':'Les id\u00e9es qui gagnent leur duel entrent de nouveau toutes seules, en argent de d\u00e9monstration.',en?'Lift':'Rel\u00e2cher'];
 const pw=await askPwd(Q[0],Q[1],Q[2],!!on);if(!pw)return;
 const r=await fetch(AB()+'lab_pause',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'on='+(on?1:0)+'&pwd='+encodeURIComponent(pw)}).catch(()=>null);
 let ok=false,msg='';try{const x=await r.json();ok=!!x.ok;msg=x.err||x.msg||'';}catch(e){}
 if(!ok){await info('&#10060; <h3>'+(msg==='bad password'?(en?'Wrong password.':'Mot de passe incorrect.'):_escS(msg||(en?'It did not work.':'\u00c7a n\u2019a pas march\u00e9.')))+'</h3>');return;}
 toast(on?(en?'Brake pulled':'Frein tir\u00e9'):(en?'Brake lifted':'Frein rel\u00e2ch\u00e9'),1800);window._labT=0;await loadLab(window._d||{});}
// 2026-10-03 (owner): the week in five lines, written on Sunday night
function labWeek(en){const j=window._lab||{};const D=j.digest;if(!D||!(D.fr||[]).length)return '';const esc=_escS;
 const L=en?(D.en||D.fr):(D.fr||D.en);
 return '<details class="panel labweek"><summary><span class="lbl">'+(en?'This week':'Cette semaine')+'<span class="hint">\u00b7 '+esc(D.week_end||'')+'</span></span><b>'+esc(L[0]||'')+'</b><svg class="ic chv"><use href="#i-chev"/></svg></summary>'+
  '<ul>'+L.slice(1).map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul></details>';}
function labSeedRow(en){const seeds=labSeeds(window._lab||{});if(!seeds.length)return '';
 const ready=seeds.filter(c=>(c.n||0)>=LAB_MIN_N).length;
 return '<button class="labseedrow" onclick="labSeedsSheet()"><span class="lsr-n">'+seeds.length+'</span><span style="flex:1;min-width:0"><b>'+(en?'clues in your real trades':'pistes dans vos vrais trades')+'</b><span class="lsr-s">'+(ready?(en?ready+' ready to read':ready+' lisibles'):(en?'none has enough trades to read yet':'aucune n\u2019a encore assez de trades'))+'</span></span><svg class="ic chv"><use href="#i-chev"/></svg></button>';}
function labSeedsSheet(){const j=window._lab||{};const en=LANG()==='en';const seeds=labSeeds(j);
 sheet('<div class="nt-eye" style="color:var(--warn)">'+(en?'The clues':'Les pistes')+'</div><h3 style="margin:6px 0 8px">'+(en?'What your real trades hint at':'Ce que vos vrais trades laissent entrevoir')+'</h3>'+
  '<p style="font-size:.86rem;color:var(--text2);line-height:1.5;margin:0 0 4px">'+(en?'Each clue is a question put to the real trades: a pile of them, against all the others. The first eleven came from the Owl; the chercheur adds one when the data gives it a reason, one a night at most. A clue is not an idea yet: under 30 trades a number can still be luck. When both halves of the period agree, the researcher can turn it into an idea.':'Chaque piste est une question pos\u00e9e aux vrais trades : une pile de trades, contre tous les autres. Les onze premi\u00e8res viennent du Owl ; le chercheur en ajoute une quand les donn\u00e9es lui en donnent une raison, une par nuit au plus. Une piste n\u2019est pas encore une id\u00e9e : sous 30 trades, un chiffre peut encore \u00eatre de la chance. Quand les deux moiti\u00e9s de la p\u00e9riode sont d\u2019accord, le chercheur peut en faire une id\u00e9e.')+'</p>'+
  '<div style="max-height:60vh;overflow-y:auto;margin:0 -4px;padding:0 4px">'+seeds.map(c=>seedCard(c,en)).join('')+'</div>'+
  '<button class="shbtn shghost" onclick="_shDone(1)">'+(en?'Close':'Fermer')+'</button>');}
function labBoard(en){setTimeout(jSwipe,80);
 return '<div class="panel jboard" id="jb">'+jRail(en)+
  '<div id="jstage">'+jStage(en)+'</div></div>';}
function jGo(i,land){if(!(i>=0&&i<JCOLS.length))return;const dir=i>jCol()?1:-1;window._jcol=i;try{localStorage.setItem('owlLabCol',String(i));}catch(e){}
 const en=LANG()==='en';const r=document.getElementById('jrail');if(r)r.outerHTML=jRail(en);const st=document.getElementById('jstage');if(!st)return;
 st.style.transition='none';st.style.opacity='0';st.style.transform='translateX('+(dir*18)+'px)';st.innerHTML=jStage(en);
 requestAnimationFrame(()=>{st.style.transition='opacity .22s ease,transform .22s ease';st.style.opacity='1';st.style.transform='translateX(0)';});
 const top=document.getElementById('jb');
 // 2026-10-02 (owner): a door tap changed the rail but the board is below
 // the fold, so nothing seemed to happen. A door now carries the view to the
 // board and rings it once; the rail's own tabs keep the old rule (only
 // scroll back up when the board has gone off the top).
 if(top&&land){window.scrollTo({top:top.getBoundingClientRect().top+window.scrollY-72,behavior:'smooth'});
  top.classList.remove('jland');void top.offsetWidth;top.classList.add('jland');}
 else if(top&&top.getBoundingClientRect().top<0)window.scrollTo({top:top.getBoundingClientRect().top+window.scrollY-70,behavior:'smooth'});}
function jSwipe(){const b=document.getElementById('jb');if(!b||b._sw)return;b._sw=1;let x0=null,y0=null;
 b.addEventListener('touchstart',e=>{x0=e.touches[0].clientX;y0=e.touches[0].clientY;},{passive:true});
 b.addEventListener('touchend',e=>{if(x0===null)return;const dx=e.changedTouches[0].clientX-x0,dy=e.changedTouches[0].clientY-y0;x0=null;if(Math.abs(dx)>60&&Math.abs(dx)>Math.abs(dy)*1.5){jGo(jCol()+(dx<0?1:-1));}},{passive:true});}
function jSync(){}
// ---- 2026-09-29 (owner batch 34): the duel - a twin against the real robot
// over the same period; the seeds' "Demander au chercheur" ----
function duelBlock(d,en){if(!d||!d.twin)return '';const mn=v=>(v>=0?'+$':'-$')+Math.abs(v||0).toFixed(0);const T=d.twin,R=d.real;
 const ST={ahead:[en?'twin ahead':'jumeau devant','var(--up-soft)'],behind:[en?'twin behind':'jumeau derri\u00e8re','var(--down-soft)'],even:[en?'about even':'\u00e0 \u00e9galit\u00e9','var(--warn)'],early:[en?'too early':'trop t\u00f4t','var(--muted)']}[d.status]||['','var(--muted)'];
 const pts=[...(T.curve||[]).map(p=>[p[0],p[1],0]),...(R.curve||[]).map(p=>[p[0],p[1],1])];let svg='';
 if(pts.length>=2){const t0=Math.min(...pts.map(p=>p[0])),t1=Math.max(...pts.map(p=>p[0]),t0+60);const ys=pts.map(p=>p[1]).concat([0]);const mx=Math.max(...ys),mnv=Math.min(...ys),sp=Math.max(1e-6,mx-mnv);
  const X=t=>(4+(t-t0)/(t1-t0)*292).toFixed(1),Y=v=>(46-((v-mnv)/sp)*40).toFixed(1);const line=(cv,c)=>{if(!cv||!cv.length)return '';const p=[[t0,0]].concat(cv).map(q=>X(q[0])+','+Y(q[1])).join(' ');return '<polyline points="'+p+'" fill="none" style="stroke:'+c+'" stroke-width="1.8" stroke-linejoin="round"/>';};
  svg='<svg viewBox="0 0 300 52" style="width:100%;height:52px;display:block;margin-top:8px"><line x1="4" y1="'+Y(0)+'" x2="296" y2="'+Y(0)+'" style="stroke:var(--border2)" stroke-dasharray="3 4"/>'+line(R.curve,'var(--accent-soft)')+line(T.curve,'#b98cff')+'</svg>';}
 const cell=(l,v,c)=>'<div style="flex:1;background:var(--tile-bg);border:1px solid var(--tile-bd);border-radius:12px;padding:8px 4px;text-align:center"><b style="display:block;font-size:.9rem;color:'+c+'">'+v+'</b><span style="font-size:.56rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+l+'</span></div>';
 return '<div style="display:flex;align-items:center;gap:8px;margin-top:10px;font-size:.62rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)"><i style="width:14px;height:3px;border-radius:2px;background:#b98cff;display:inline-block"></i>'+(en?'twin':'jumeau')+'<i style="width:14px;height:3px;border-radius:2px;background:var(--accent-soft);display:inline-block;margin-left:6px"></i>'+(en?'real robot':'vrai robot')+'<span class="pchip" style="margin-left:auto;color:'+ST[1]+';background:rgba(255,255,255,.05)">'+ST[0]+'</span></div>'+svg+
  '<div style="display:flex;gap:6px;margin-top:8px">'+cell(en?'twin':'jumeau',mn(T.net),(T.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+cell(en?'real robot':'vrai robot',mn(R.net),(R.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+cell(en?'twin trades':'trades jumeau',(T.trades||0)+' / '+(d.need||30),'var(--text)')+cell(en?'biggest hole':'plus gros trou',mn(-(T.worst||0))+' | '+mn(-(R.worst||0)),'var(--text)')+'</div>'+
  '<div style="font-size:.68rem;color:var(--muted);margin-top:6px;line-height:1.4">'+(en?'Same period, same lot, base trades only. After 30 twin trades: behind on money and deeper in its hole = the twin stops by itself; ahead = it goes into the lab\u2019s robot by itself.':'M\u00eame p\u00e9riode, m\u00eame mise, trades de base seulement. Apr\u00e8s 30 trades du jumeau : derri\u00e8re en argent et trou plus profond = le jumeau s\u2019arr\u00eate tout seul ; devant = elle entre toute seule dans le robot du labo.')+'</div>';}
function seedAsk(id){const j=window._lab||{};return (j.asks||[]).filter(a=>a.seed===id).sort((a,b)=>(a.date||'').localeCompare(b.date||'')).pop()||null;}
async function labAsk(id){const en=LANG()==='en';const j=window._lab||{};const c=(j.candidates||[]).find(x=>x.id===id);if(!c)return;
 const note=(document.getElementById('ask-note')||{}).value||'';
 const r=await fetch(AB()+'lab_ask',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'seed='+encodeURIComponent(id)+'&note='+encodeURIComponent(note)}).catch(()=>null);
 let ok=false,msg='';try{const x=await r.json();ok=!!x.ok;msg=x.err||'';}catch(e){}
 if(!ok){await info('&#10060; <h3>'+(msg==='strategy'?(en?'The Strategy plan is needed to ask the chercheur.':'Le paquet Strat\u00e9gie est n\u00e9cessaire pour demander au chercheur.'):(en?'It did not work.':'\u00c7a n\u2019a pas march\u00e9.'))+'</h3>');return;}
 toast(en?'Sent to the chercheur for tonight':'Envoy\u00e9 au chercheur pour cette nuit',2200);window._labT=0;await loadLab(window._d||{});labSeed(id);}
function labSeed(id){const j=window._lab||{};const c=(j.candidates||[]).find(x=>x.id===id);if(!c)return;const en=LANG()==='en';const esc=_escS;const pc=x=>x===null||x===undefined?'\u2014':x+'\u202f%';
 const L={trop_tot:[en?'too few trades':'pas assez de trades','var(--muted)',en?'Under 30 trades, a number can still be luck. We show it so you can watch it grow.':'Sous 30 trades, un chiffre peut encore \u00eatre de la chance. On le montre pour le voir grandir.'],a_tester:[en?'worth checking':'\u00e0 v\u00e9rifier','var(--up-soft)',en?'The first half and the second half of the period say the same thing. The chercheur can turn it into an idea to test.':'La premi\u00e8re et la deuxi\u00e8me moiti\u00e9 de la p\u00e9riode disent la m\u00eame chose. Le chercheur peut en faire une id\u00e9e \u00e0 tester.'],divergent:[en?'not clear':'pas net','var(--warn)',en?'The two halves of the period disagree. Noise for now.':'Les deux moiti\u00e9s de la p\u00e9riode ne sont pas d\u2019accord. Du bruit pour l\u2019instant.'],doublon:[en?'same trades as another':'m\u00eames trades qu\u2019une autre','var(--muted)',(en?'Mostly the same trades as \u201c':'Presque les m\u00eames trades que \u00ab ')+_escS(en?(c.dup_name_en||''):(c.dup_name_fr||''))+(en?'\u201d, so it says nothing new and is never asked about.':' \u00bb : elle n\u2019apprend rien de plus, on ne la demande jamais.')],invalide:[en?'badly written':'mal \u00e9crite','var(--down-soft)',(en?'The chercheur wrote this pile in a form the app cannot read: ':'Le chercheur a \u00e9crit cette pile dans une forme que l\u2019appli ne sait pas lire : ')+_escS(c.error||'')]};const l=L[c.label]||L.trop_tot;
 const cell=(lb,x)=>'<div style="flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:11px;padding:8px 4px;text-align:center"><b style="display:block;font-size:.95rem">'+x+'</b><span style="font-size:.56rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+lb+'</span></div>';
 const a=seedAsk(id);let ask='';
 if(a&&a.status==='open')ask='<div class="panel" style="margin-top:12px;border-color:rgba(185,140,255,.35);padding:12px"><b style="font-size:.86rem;color:#b98cff">'+(en?'Sent to the chercheur':'Envoy\u00e9 au chercheur')+' \u00b7 '+esc(a.date||'')+(a.by==='labo'?' \u00b7 '+(en?'by the lab itself':'par le labo lui-m\u00eame'):'')+'</b><div style="font-size:.8rem;color:var(--text2);margin-top:4px">'+(en?'It answers during its next night: an idea to test, or why not yet.':'Il r\u00e9pond \u00e0 sa prochaine nuit : une id\u00e9e \u00e0 tester, ou pourquoi pas encore.')+(a.note?'<br><i>\u00ab '+esc(a.note)+' \u00bb</i>':'')+'</div></div>';
 else if(a&&a.status==='answered')ask='<div class="panel" style="margin-top:12px;border-color:rgba(185,140,255,.35);padding:12px"><b style="font-size:.86rem;color:#b98cff">'+(en?'The chercheur answered':'Le chercheur a r\u00e9pondu')+'</b><div style="font-size:.86rem;color:var(--text);margin-top:4px;line-height:1.5">'+esc(en?(a.answer_en||a.answer_fr):(a.answer_fr||a.answer_en))+'</div></div>';
 else if(a&&a.status==='proposed')ask='<div class="panel" style="margin-top:12px;border-color:rgba(185,140,255,.35);padding:12px"><b style="font-size:.86rem;color:#b98cff">'+(en?'The chercheur made it an idea':'Le chercheur en a fait une id\u00e9e')+'</b><div style="margin-top:6px"><button class="tfc" onclick="labJourney(&#39;'+esc(a.proposal||'')+'&#39;)">'+(en?'See the idea':'Voir l\u2019id\u00e9e')+' \u203a</button></div></div>';
 else if(labAllowed())ask='<div class="lbl" style="margin-top:14px">'+(en?'Ask the chercheur':'Demander au chercheur')+'</div><textarea id="ask-note" placeholder="'+(en?'Why it intrigues you (optional)':'Pourquoi \u00e7a vous intrigue (facultatif)')+'" style="width:100%;box-sizing:border-box;margin-top:6px;min-height:56px;background:var(--surface2);border:1px solid var(--border);border-radius:10px;color:var(--text);padding:8px;font:inherit;font-size:.86rem"></textarea><button class="shbtn shmain" style="margin:8px 0 0;padding:11px" onclick="labAsk(&#39;'+esc(id)+'&#39;)">'+(en?'Send to the chercheur for tonight':'Envoyer au chercheur pour cette nuit')+'</button>';
 sheet('<div style="font-size:.6rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--warn)">'+(en?'A clue \u00b7 seen in the real trades':'Une piste \u00b7 vue dans les vrais trades')+'</div><h3 style="margin:6px 0 10px">'+esc(en?c.name_en:c.name_fr)+'</h3>'+
  '<div style="display:flex;gap:6px">'+cell('trades',c.n)+cell(en?'won':'gagn\u00e9s',pc(c.win))+cell(en?'the others':'les autres',pc(c.rest_win))+'</div>'+
  '<div style="display:flex;gap:6px;margin-top:6px">'+cell(en?'first half':'1\u00e8re moiti\u00e9',pc(c.h1)+' <small style="color:var(--muted)">('+c.h1n+')</small>')+cell(en?'second half':'2e moiti\u00e9',pc(c.h2)+' <small style="color:var(--muted)">('+c.h2n+')</small>')+'</div>'+
  '<div style="margin-top:12px">'+lchip(l[0],l[1])+'</div><p style="font-size:.9rem;line-height:1.55;color:var(--text);margin:8px 0 0">'+l[2]+'</p>'+((en?c.why_en:c.why_fr)?'<div class="lbl" style="margin-top:12px">'+(en?'Why this pile':'Pourquoi cette pile')+(c.by==='chercheur'?' \u00b7 '+(en?'the chercheur':'le chercheur'):'')+(c.date?' \u00b7 '+esc(c.date):'')+'</div><p style="font-size:.88rem;line-height:1.5;color:var(--text2);margin:6px 0 0">'+esc(en?c.why_en:c.why_fr)+'</p>':'')+ask+
  '<div style="font-size:.74rem;color:var(--muted);margin-top:10px;line-height:1.45">'+(en?'Clues are counted again every ten minutes from the real trades of every account. The chercheur reads them every night.':'Les pistes sont recompt\u00e9es toutes les dix minutes \u00e0 partir des vrais trades de tous les comptes. Le chercheur les lit chaque nuit.')+'</div>'+
  '<button class="shbtn shghost" onclick="_shDone(1)">'+(en?'Close':'Fermer')+'</button>');}
function labStage(k){const en=LANG()==='en';let title='',body='';
 if(k==='how'){title=en?'The lab, in one minute':'Le labo, en une minute';
  body='<p style="font-size:.92rem;line-height:1.55;color:var(--text);margin:0">'+(en?'Here we look for ways to make the robot better over time. Every idea travels left to right through four columns before it touches your account.':'Ici, on cherche comment rendre le robot meilleur avec le temps. Chaque id\u00e9e voyage de gauche \u00e0 droite, par quatre colonnes, avant de toucher \u00e0 votre compte.')+'</p>'+
   '<div style="margin-top:12px">'+JCOLS.map(([kk,fr,eg,c],i)=>'<div class="jev"><span style="width:26px;color:'+c+';font-weight:800">'+(i+1)+'</span><div><b>'+(en?eg:fr)+'</b><br><span style="color:var(--text2)">'+[en?'An idea is born: from the researcher, from the Owl, or from a clue in the real trades.':'Une id\u00e9e na\u00eet : du chercheur, du Owl, ou d\u2019une piste vue dans les vrais trades.',en?'We test it on the last 42 days of the market. Three possible answers: better on both halves, a little better, or no.':'On la teste sur les 42 derniers jours du march\u00e9. Trois r\u00e9ponses possibles : mieux sur les deux moiti\u00e9s, un peu mieux, ou non.',en?'A copy of the robot tries it live, with no money, next to the real one. After 30 trades, the duel.':'Une copie du robot l\u2019essaie en direct, sans argent, \u00e0 c\u00f4t\u00e9 du vrai. Apr\u00e8s 30 trades, le duel.',en?'If it beats the robot, it goes into the lab\u2019s robot by itself (demo money). The real accounts are the Owl\u2019s yes.':'Si elle bat le robot, elle entre toute seule dans le robot du labo (argent de d\u00e9monstration). Les vrais comptes, c\u2019est Kino qui dit oui.'][i]+'</span></div></div>').join('')+'</div>'+
   '<div style="font-size:.78rem;color:var(--muted);margin-top:10px;line-height:1.45">'+(en?'The chercheur is an AI that reads the data every night and challenges the robot. It proposes; the tests decide.':'Le chercheur est une intelligence artificielle qui lit les donn\u00e9es chaque nuit et bouscule le robot. Il propose ; ce sont les tests qui d\u00e9cident.')+'</div>'+
   // 2026-10-03 (owner): the three agents, and what each is NOT allowed to do
   '<div class="lbl" style="margin-top:16px">'+(en?'Who does what':'Qui fait quoi')+'</div>'+
   [['var(--accent-soft)',en?'The researcher':'Le chercheur',en?'Watches the robot all day and all night, remembers everything, proposes ideas and clues. May never decide, never touch the robot, never name a member.':'Surveille le robot jour et nuit, se souvient de tout, propose des id\u00e9es et des pistes. Ne d\u00e9cide jamais, ne touche jamais au robot, ne nomme jamais un membre.'],
    ['#b98cff',en?'The critic':'Le critique',en?'Tries to break every idea that scored well before it earns a twin. May only say yes, doubt, or no - with its reasons for you to read.':'Essaie de casser chaque id\u00e9e qui a bien marqu\u00e9 avant qu\u2019elle n\u2019ait droit \u00e0 un jumeau. Ne peut que dire oui, douter, ou non \u2014 avec ses raisons, que vous lisez.'],
    ['var(--up-soft)',en?'The builder':'Le constructeur',en?'Builds what the researcher asks for - a dial for the test, a fact, a tool. Every build passes the same gates or is undone. May never change how money is risked.':'Construit ce que le chercheur demande \u2014 un r\u00e9glage pour le test, un fait, un outil. Chaque construction passe les m\u00eames contr\u00f4les ou est annul\u00e9e. Ne peut jamais changer la fa\u00e7on dont l\u2019argent est risqu\u00e9.'],
    ['var(--muted2)',en?'The gates':'Les contr\u00f4les',en?'Not an agent: fixed rules that never get smarter. Tested on the past, a twin for pretend, a 30-trade duel, then the lab\u2019s own robot, watched. Real accounts still need the Owl\u2019s tap.':'Pas une intelligence : des r\u00e8gles fixes qui ne deviennent jamais plus malignes. Test\u00e9e sur le pass\u00e9, un jumeau pour de faux, un duel de 30 trades, puis le robot du labo, surveill\u00e9. Les vrais comptes attendent toujours l\u2019accord du Owl.']]
   .map(a=>'<div class="jev"><span style="width:10px;padding-top:6px"><i style="display:inline-block;width:8px;height:8px;border-radius:99px;background:'+a[0]+'"></i></span><div><b>'+a[1]+'</b><br><span style="color:var(--text2)">'+a[2]+'</span></div></div>').join('');}
 else{const T={ideas:[en?'Ideas':'Id\u00e9es'],tests:[en?'Tested':'Test\u00e9es'],forward:[en?'For pretend':'Pour de faux'],decisions:[en?'In the robot':'Dans le robot']};title=(T[k]||[''])[0];body=labStageHtml(k);}
 sheet('<h3 style="margin:0 0 10px">'+title+'</h3><div style="max-height:72vh;overflow-y:auto;margin:0 -4px;padding:0 4px">'+body+'</div><button class="shbtn shghost" onclick="_shDone(1)">'+(en?'Close':'Fermer')+'</button>');}
function jStrip(j,en){const S=j.steps||{};const r=S.replay||{};const N=[['idea',en?'Idea':'Id\u00e9e',(S.idea||{}).date],['replay',en?'Tested':'Test\u00e9e',r.pretest?'':(r.last||(S.decision||{}).date)],['test',en?'For pretend':'Pour de faux',(S.test||{}).started],['live',en?'In the robot':'Dans le robot',(S.live||{}).date]];
 const idx={idea:1,replay:2,test:3,live:4};const cur=idx[j.col]||1;
 const no=(S.decision||{}).d==='no'||['stopped','retired','reverted'].indexOf((S.test||{}).status)>=0;
 return '<div class="jst">'+N.map(([k,l,d],i)=>{const n=i+1;const done=n<=cur;const cls=(done?'done':'')+(n===cur?' now':'')+(no&&n===cur?' no':'');
  return '<div class="'+cls+'"><i>'+(no&&n===cur?'\u00d7':(done&&n<cur?'\u2713':n))+'</i>'+l+'<small>'+(d?_escS(String(d).slice(5)):'\u00a0')+'</small></div>';}).join('')+'</div>';}
function labJourney(id){const j=jGet(id);if(!j)return;const en=LANG()==='en';const S=j.steps||{};const mn=v=>(v>=0?'+$':'-$')+Math.abs(v||0).toFixed(0);
 const col=JCOLS.find(c=>c[0]===j.col)||JCOLS[0];
 const chips=(j.cfg?dialChips(j.cfg,en):[]).map(([t,c])=>'<span class="pchip" style="color:'+c+';background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);margin:0 4px 4px 0">'+_escS(t)+'</span>').join('');
 const r=S.replay||{};const tile=(l,v,c)=>'<div style="flex:1;background:var(--tile-bg);border:1px solid var(--tile-bd);border-radius:12px;padding:8px 4px;text-align:center"><b style="display:block;font-size:.92rem;color:'+c+'">'+v+'</b><span style="font-size:.56rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+l+'</span></div>';
 const tiles=(r.diff_net!==undefined)?'<div style="display:flex;gap:6px;margin-top:8px">'+tile(en?'money':'argent',mn(r.diff_net),(r.diff_net||0)>=0?'var(--up-soft)':'var(--down-soft)')+tile(en?'biggest hole':'plus gros trou',mn(r.diff_worst),(r.diff_worst||0)<=0?'var(--up-soft)':'var(--down-soft)')+tile(en?'halves':'moiti\u00e9s',mn(r.h1)+' / '+mn(r.h2),((r.h1||0)>0&&(r.h2||0)>0)?'var(--up-soft)':'var(--text)')+'</div>':'';
 const note=en?(j.note_en||j.note_fr||''):(j.note_fr||j.note_en||'');const nums=en?(j.nums_en||''):(j.nums_fr||'');
 const ev=(j.events||[]).map(e=>'<div class="jev"><span>'+_escS(String(e.d||'').slice(5))+'</span><div>'+_escS(en?e.en:e.fr)+'</div></div>').join('');
 let adm=false;try{adm=!!((window._d||{}).is_master||localStorage.getItem('owl_adm'));}catch(e){}
 let btns='';
 if(j.reference){btns='<div style="font-size:.78rem;color:var(--muted2);margin-top:14px;line-height:1.5">'+(en?'A yardstick. It measures the brakes; there is no decision to take on it.':'Un étalon. Il mesure les freins ; il n’y a pas de décision à prendre dessus.')+'</div>';}
 else if(adm&&j.col!=='live'){const dec=S.decision||{};const canTwin=(j.col==='replay'||j.col==='idea')&&!!j.cfg||(j.col==='replay'&&j.kind!=='registry');
  btns='<div class="lbl" style="margin-top:14px">'+(en?'Your call, Kino':'\u00c0 vous, Kino')+'</div><div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">'+
   (canTwin&&!S.test?'<button class="shbtn shmain" style="flex:1 1 46%;margin:0;padding:11px" onclick="labDecide(&#39;'+_escS(j.id)+'&#39;,&#39;twin&#39;)">'+(en?'Start a twin':'Lancer un jumeau')+'</button>':'')+
   (dec.d!=='yes'?'<button class="shbtn shmain" style="flex:1 1 46%;margin:0;padding:11px;background:var(--up-soft);color:#08120c" onclick="labDecide(&#39;'+_escS(j.id)+'&#39;,&#39;yes&#39;)">'+(en?'Put on the real accounts':'Mettre sur les vrais comptes')+'</button>':'')+
   (dec.d!=='no'?'<button class="shbtn shghost" style="flex:1 1 46%;margin:0;padding:11px;color:var(--down-soft)" onclick="labDecide(&#39;'+_escS(j.id)+'&#39;,&#39;no&#39;)">'+(en?'Reject':'Rejeter')+'</button>':'')+'</div>'+
   '<div style="font-size:.7rem;color:var(--muted);margin-top:6px;line-height:1.4">'+(en?'Real accounts = the developer puts it on the real accounts. Reject = its twin stops and the idea is kept as a no.':'Vrais comptes = le d\u00e9veloppeur la pose sur les comptes r\u00e9els. Rejeter = son jumeau s\u2019arr\u00eate et l\u2019id\u00e9e est gard\u00e9e comme un non.')+'</div>';}
 sheet('<div style="display:flex;align-items:center;gap:8px;font-size:.6rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:'+col[3]+'"><i style="display:inline-block;width:8px;height:8px;border-radius:99px;background:'+col[3]+'"></i>'+(en?col[2]:col[1])+'<span style="margin-left:auto;color:var(--muted)">'+_escS(j.date||'')+'</span></div>'+
  '<h3 style="margin:6px 0 2px">'+_escS(en?j.title_en:j.title_fr)+'</h3>'+jStrip(j,en)+
  (chips?'<div class="lbl" style="margin-top:10px">'+(en?'What changes':'Ce qui change')+'</div><div style="margin-top:6px">'+chips+'</div>':'')+
  (tiles?'<div class="lbl" style="margin-top:10px">'+(en?'Against the robot as it is':'Contre le robot tel qu\u2019il est')+'</div>'+tiles+xTiles(r,en)+'<div style="font-size:.66rem;color:var(--muted);margin-top:4px;line-height:1.4">'+(en?'42 days give the mark. The long window and the real trades are two more looks: weaker there is a caution, not a no.':'Les 42 jours donnent la note. La fen\u00eatre longue et les vrais trades sont deux regards de plus : plus faible l\u00e0, c\u2019est une prudence, pas un non.')+'</div>':'')+
  ((S.test||{}).duel?'<div class="lbl" style="margin-top:12px">'+(en?'The duel, for pretend':'Le duel, pour de faux')+'</div>'+duelBlock(S.test.duel,en):'')+
  (j.critique?'<div class="lbl" style="margin-top:12px">'+(en?'The critic':'Le critique')+' \u00b7 '+_escS(j.critique.date||'')+'</div><div class="panel" style="margin-top:6px;padding:11px 12px;border-color:'+({bloque:'rgba(255,92,92,.4)',doute:'rgba(232,197,90,.4)'}[j.critique.verdict]||'rgba(46,204,113,.35)')+'"><b style="font-size:.84rem;color:'+({bloque:'var(--down-soft)',doute:'var(--warn)'}[j.critique.verdict]||'var(--up-soft)')+'">'+({bloque:en?'No, not on this evidence':'Non, pas avec ces preuves',doute:en?'A doubt':'Un doute'}[j.critique.verdict]||(en?'Could not break it':'N\u2019a pas r\u00e9ussi \u00e0 la casser'))+'</b><p style="font-size:.88rem;line-height:1.5;color:var(--text);margin:5px 0 0">'+_escS(en?(j.critique.en||j.critique.fr):(j.critique.fr||j.critique.en))+'</p></div>':'')+
  (note?'<div class="lbl" style="margin-top:12px">'+(en?'The idea':'L\u2019id\u00e9e')+'</div><p style="font-size:.9rem;line-height:1.55;color:var(--text);margin:6px 0 0">'+_escS(note)+'</p>':'')+
  (nums?'<p style="font-size:.8rem;color:var(--text2);margin:6px 0 0;line-height:1.5">'+_escS(nums)+'</p>':'')+
  '<div class="lbl" style="margin-top:12px">'+(en?'Its story':'Son histoire')+'</div><div style="max-height:34vh;overflow-y:auto;margin-top:4px">'+(ev||'<div class="jev"><span></span><div>'+(en?'Nothing yet.':'Rien encore.')+'</div></div>')+'</div>'+btns+
  '<button class="shbtn shghost" onclick="_shDone(1)">'+(en?'Close':'Fermer')+'</button>');}
async function labDecide(id,d){const en=LANG()==='en';const j=jGet(id)||{};const t=en?(j.title_en||id):(j.title_fr||id);
 const Q={twin:[en?'Start a twin?':'Lancer un jumeau ?',en?'A copy of the robot will try this idea for pretend, next to the real one, from now on.':'Une copie du robot essaiera cette id\u00e9e pour de faux, \u00e0 c\u00f4t\u00e9 du vrai, \u00e0 partir de maintenant.',en?'Start':'Lancer'],
  yes:[en?'Put it on the real accounts?':'La mettre sur les vrais comptes ?',en?'It goes to the developer to put on the real accounts. The lab\u2019s demo robot takes it by itself.':'Elle part chez le d\u00e9veloppeur pour entrer sur les vrais comptes. Le robot d\u00e9mo du labo, lui, la prend tout seul.',en?'Yes':'Oui'],
  no:[en?'Reject this idea?':'Rejeter cette id\u00e9e ?',en?'Its twin stops. The idea stays in the lab as a no.':'Son jumeau s\u2019arr\u00eate. L\u2019id\u00e9e reste dans le labo comme un non.',en?'Reject':'Rejeter']}[d];
 const pw=await askPwd(Q[0],'<b>'+_escS(t)+'</b><br>'+Q[1],Q[2],d==='no');if(!pw)return;
 const r=await fetch(AB()+'lab_decide',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'id='+encodeURIComponent(id)+'&d='+d+'&pwd='+encodeURIComponent(pw)}).catch(()=>null);
 let ok=false,msg='';try{const x=await r.json();ok=!!x.ok;msg=x.err||x.msg||'';}catch(e){}
 if(!ok){await info('&#10060; <h3>'+(msg==='bad password'?(en?'Wrong password.':'Mot de passe incorrect.'):_escS(msg||(en?'It did not work.':'\u00c7a n\u2019a pas march\u00e9.')))+'</h3>');return;}
 toast(en?'Saved':'Enregistr\u00e9',1800);window._labT=0;await loadLab(window._d||{});labJourney(id);}
// a proposal as a card: what changes (dial chips), why in two lines, the
// pre-test tiles when the chercheur ran the engine, tap for the full text
const DIAL_BASE={rr:0.8,n_cont:1,wait_min:0,ext_pts:0,size_hot:1.0,nerv_gate:false,debt_nerv_gate:false,bullets:3,k_streak:2};
function dialChips(cfg,en){const c=cfg||{};const out=[];const DN=en?['Mon','Tue','Wed','Thu','Fri','Sat','Sun']:['lundi','mardi','mercredi','jeudi','vendredi','samedi','dimanche'];
 if(c.rr!==undefined&&c.rr!==DIAL_BASE.rr)out.push([(en?'aim for ':'viser ')+String(c.rr).replace('.',en?'.':',')+(en?'\u00d7 what we risk':'\u00d7 ce qu\u2019on risque'),'#b98cff']);
 if(c.n_cont!==undefined&&c.n_cont!==DIAL_BASE.n_cont)out.push([c.n_cont+(en?' extra trade'+(c.n_cont>1?'s':''):' trade'+(c.n_cont>1?'s':'')+' de plus'),'var(--accent-soft)']);
 if(c.wait_min)out.push([(en?'wait ':'pause ')+c.wait_min+' min','#e8743b']);
 if(c.ext_pts)out.push([(en?'not after ':'pas apr\u00e8s ')+c.ext_pts+' pts','#e8743b']);
 (c.skip_wd||[]).forEach(d=>out.push([(en?'no ':'pas de ')+DN[d],'#e8743b']));
 if((c.skip_hours||[]).length){const hs=c.skip_hours;out.push([(en?'not ':'pas ')+hs[0]+'\u2013'+(hs[hs.length-1]+1)+' h','#e8743b']);}
 if(c.size_hot!==undefined&&c.size_hot!==DIAL_BASE.size_hot)out.push([(en?'stake \u00d7':'mise \u00d7')+c.size_hot+(en?' nervous':' nerveux'),'var(--warn)']);
 if(c.nerv_gate)out.push([en?'nothing if nervous':'rien si nerveux','var(--warn)']);
 if(c.debt_nerv_gate)out.push([en?'nothing if red + nervous':'rien si rouge + nerveux','var(--warn)']);
 if(c.bullets!==undefined&&c.bullets!==DIAL_BASE.bullets)out.push([(en?'up to '+c.bullets+' catch-up trade'+(c.bullets>1?'s':''):'jusqu\u2019\u00e0 '+c.bullets+' trade'+(c.bullets>1?'s':'')+' de rattrapage'),'var(--up-soft)']);
 if(c.k_streak!==undefined&&c.k_streak!==DIAL_BASE.k_streak)out.push([(en?'catch up until '+c.k_streak+' loss'+(c.k_streak>1?'es':'')+' in a row':'se rattraper jusqu\u2019\u00e0 '+c.k_streak+' perte'+(c.k_streak>1?'s':'')+' de suite'),'var(--up-soft)']);
 return out;}
function propAuto(id){const v=(((window._lab||{}).auto||{}).variants||[]).find(x=>x.id===id);if(!v)return null;return {net:v.diff_net||0,worst:v.diff_worst||0,h1:(v.h1||{}).net||0,h2:(v.h2||{}).net||0,base_net:0,base_worst:0,long:v.long,real:v.real};}
// 2026-09-29 (owner): two more views under the 42-day tiles - the long
// window and the real trades. Weaker here = a caution, never a drop.
function xTiles(r,en){const L=r&&r.long,T=r&&r.real;if(!L&&!T)return '';const mn=v=>Math.abs(v||0)<0.5?'$0':(v>=0?'+$':'-$')+Math.abs(v).toFixed(0);const VC={A:'var(--up-soft)',B:'var(--warn)',C:'var(--down-soft)','=':'var(--muted)'};
 const tile=(l,x,c)=>'<div style="flex:1;background:var(--tile-bg);border:1px solid var(--tile-bd);border-radius:12px;padding:8px 4px;text-align:center"><b style="display:block;font-size:.88rem;color:'+c+'">'+x+'</b><span style="font-size:.56rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+l+'</span></div>';
 return '<div style="display:flex;gap:6px;margin-top:6px">'+(L?tile((en?'over ':'sur ')+(L.days||'')+(en?' days':' jours'),'<span style="color:'+(VC[L.verdict]||'var(--text)')+'">'+vShort(L.verdict,en)+'</span> '+mn(L.diff_net),'var(--text)'):'')+(T?tile((en?'real trades (':'vrais trades (')+(T.n_real||0)+')',mn(T.diff_net),(T.diff_net||0)>=0?'var(--up-soft)':'var(--down-soft)'):'')+'</div>';}
function propCard(p,en){const esc=_escS;const chips=dialChips(p.cfg,en).map(([t,c])=>'<span class="pchip" style="color:'+c+';background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08)">'+esc(t)+'</span>').join('');
 const why=esc(en?(p.why_en||''):(p.why_fr||''));const pt=p.pretest||propAuto(p.id);const mn=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(0);
 const tile=(l,v,c)=>'<div style="flex:1;background:var(--tile-bg);border:1px solid var(--tile-bd);border-radius:12px;padding:8px 4px;text-align:center"><b style="display:block;font-size:.92rem;color:'+c+'">'+v+'</b><span style="font-size:.56rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+l+'</span></div>';
 const tiles=pt?'<div style="display:flex;gap:6px;margin-top:10px">'+tile(en?'money':'argent',mn(pt.net-(pt.base_net||0)),(pt.net-(pt.base_net||0))>=0?'var(--up-soft)':'var(--down-soft)')+tile(en?'biggest hole':'plus gros trou',mn(pt.worst-(pt.base_worst||0)),(pt.worst-(pt.base_worst||0))<=0?'var(--up-soft)':'var(--down-soft)')+tile(en?'halves':'moiti\u00e9s',(pt.h1>=0?'+':'')+Math.round(pt.h1)+' / '+(pt.h2>=0?'+':'')+Math.round(pt.h2),(pt.h1>0&&pt.h2>0)?'var(--up-soft)':'var(--text)')+'</div>'+xTiles(pt,en)+'<div style="font-size:.62rem;color:var(--muted);margin-top:4px;text-transform:uppercase;letter-spacing:.05em">'+(en?'its own pre-test, against the robot as it is':'son pr\u00e9-test, contre le robot tel qu\u2019il est')+'</div>':'';
 return '<div class="panel lc" style="padding-right:14px" onclick="labProp(&#39;'+esc(p.id)+'&#39;)" role="button" tabindex="0"><div class="lct"><span class="lcb" style="color:#b98cff;background:rgba(185,140,255,.14)"><svg class="ic ic-s"><use href="#i-target"/></svg></span><div style="flex:1;min-width:0"><h4>'+esc(en?p.title_en:p.title_fr)+'</h4><div class="lcc">'+'<span class="pchip" style="color:#b98cff;background:rgba(185,140,255,.14)">'+(en?'replayed tonight':'rejou\u00e9 cette nuit')+'</span>'+chips+'</div></div></div>'+
  '<div class="lcn" style="display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">'+why+'</div>'+tiles+
  '<div class="lcm"><span>'+esc(p.date||'')+'</span><span style="color:var(--accent-soft);font-weight:700">'+(en?'Read':'Lire')+' \u203a</span></div></div>';}
function labProp(id){const j=window._lab;if(!j)return;const p=(j.proposals||[]).find(x=>x.id===id);if(!p)return;const en=LANG()==='en';const esc=_escS;
 const chips=dialChips(p.cfg,en).map(([t,c])=>'<span class="pchip" style="color:'+c+';background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);margin:0 4px 4px 0">'+esc(t)+'</span>').join('');
 const _jj=jGet(id);
 sheet('<div style="color:#b98cff;font-size:.6rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase">'+(en?'The chercheur proposes':'Le chercheur propose')+' \u00b7 '+esc(p.date||'')+'</div><h3 style="margin:6px 0 4px">'+esc(en?p.title_en:p.title_fr)+'</h3>'+(_jj?jStrip(_jj,en)+'<button class="tfc" style="margin:4px 0 8px" onclick="labJourney(&#39;'+esc(id)+'&#39;)">'+(en?'Its story':'Son histoire')+' \u203a</button>':'')+
  '<div class="lbl">'+(en?'What changes':'Ce qui change')+'</div><div style="margin:6px 0 12px">'+chips+'</div>'+
  '<div class="lbl">'+(en?'Why':'Pourquoi')+'</div><p style="font-size:.95rem;line-height:1.6;color:var(--text);margin:6px 0 0;max-height:46vh;overflow-y:auto">'+esc(en?(p.why_en||''):(p.why_fr||''))+'</p>'+
  '<div style="font-size:.74rem;color:var(--muted);margin-top:10px">'+(en?'Tested tonight by the engine, with the fixed rules. Its mark shows tomorrow under \u201cV\u00e9rifi\u00e9 sur le pass\u00e9\u201d.':'Test\u00e9 cette nuit par le moteur, avec les r\u00e8gles fixes. Sa note appara\u00eet demain sous \u00ab V\u00e9rifi\u00e9 sur le pass\u00e9 \u00bb.')+'</div>'+
  '<button class="shbtn shghost" onclick="_shDone(1)">'+(en?'Close':'Fermer')+'</button>');}
// the chercheur's night as slides (owner 2026-09-29: "a summary, then a
// click to show a professional slide that tells the full story")
const _escS=x=>String(x||'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
function labNight(){const j=window._lab;if(!j)return;const N=j.note||{};const en=LANG()==='en';const esc=_escS;
 const AU=j.auto||{};const cc=AU.counts||{};
 const LF=String.fromCharCode(10);
 const strip=t=>String(t||'').split('**').join('');
 const paras=t=>strip(t).split(LF).map(x=>x.trim()).filter(Boolean).map(x=>'<p>'+esc(x)+'</p>').join('');
 const head=strip(en?(N.headline_en||N.headline_fr):(N.headline_fr||N.headline_en));
 const tot=(cc.A||0)+(cc.B||0)+(cc.C||0)+(cc['=']||0);
 const bel=N.beliefs||[];
 const PR=(j.proposals||[]).filter(p=>p.status==='pending'||!p.status);
 const RQ=j.requests||[];
 const JJ0=j.journeys||[];const titleOf=id=>{const x=JJ0.find(y=>y.id===id||(y.keys||[]).indexOf(id)>=0);return x?(en?(x.title_en||x.title_fr):(x.title_fr||x.title_en)):id;};
 const CRQ=(j.critiques||[]).slice(-8).reverse();
 const BLD=(j.builds||[]).slice(-6).reverse();
 const VW={passe:[en?'could not break it':'n\u2019a pas r\u00e9ussi \u00e0 la casser','var(--up-soft)','rgba(46,204,113,.14)'],doute:[en?'a doubt':'un doute','var(--warn)','rgba(232,197,90,.14)'],bloque:[en?'said no':'a dit non','var(--down-soft)','rgba(255,92,92,.12)']};
 const BW={built:[en?'delivered':'livr\u00e9','var(--up-soft)','rgba(46,204,113,.14)'],declined:[en?'declined':'d\u00e9clin\u00e9','var(--warn)','rgba(232,197,90,.14)'],failed:[en?'could not':'n\u2019y arrive pas','var(--down-soft)','rgba(255,92,92,.12)']};
 const chip=(w)=>w?'<span class="nt-chip" style="color:'+w[1]+';background:'+w[2]+'">'+w[0]+'</span>':'';
 // the night's own "what I believe / propose / ask" sections say what
 // sections 3-5 below say, structured - so they are not shown twice
 const dup=x=>{const t=(x.title_fr||x.title_en||'');
  return (/^Ce que je crois|^What I believe/.test(t)&&bel.length)||
   (/^Ce que je propose|^What I propose/.test(t)&&PR.length)||
   (/^Ce que je demande|^What I ask/.test(t)&&RQ.length);};
 const secs=(N.sections||[]).filter(x=>(x.fr||x.en)&&!dup(x));
 const parts=[];
 if(tot)parts.push(['res',en?'The results':'Les r\u00e9sultats']);
 const DAY=(j.veille||[]).filter(v=>v.kind!=='rien').slice(-6).reverse();
 if(DAY.length)parts.push(['day',en?'During the day':'Dans la journ\u00e9e']);
 if(CRQ.length)parts.push(['crit',en?'The critic':'Le critique']);
 if(BLD.length)parts.push(['build',en?'The builder':'Le constructeur']);
 if(secs.length||(!secs.length&&(N.fr||N.en)))parts.push(['ret',en?'To remember':'\u00c0 retenir']);
 if(bel.length)parts.push(['bel',en?'What it believes':'Ce qu\u2019il croit']);
 if(PR.length)parts.push(['try',en?'To try next':'\u00c0 essayer']);
 if(RQ.length)parts.push(['ask',en?'To build':'\u00c0 construire']);
 if(!parts.length&&!head)return;
 const num=k=>parts.findIndex(x=>x[0]===k)+1;
 const sh=(k,sub)=>'<div class="nt-sec" id="nt-'+k+'"><div class="nt-sh"><i>'+('0'+num(k)).slice(-2)+'</i><b>'+esc(parts[num(k)-1][1])+'</b></div>'+(sub?'<div class="nt-sub">'+sub+'</div>':'');
 let h='<div class="nt-eye">'+(en?'The researcher \u00b7 night of ':'Le chercheur \u00b7 nuit du ')+esc(N.date||'')+'</div>';
 if(head)h+='<h3 class="nt-h" onclick="this.classList.toggle(&#39;open&#39;)" title="'+(en?'Tap to read it whole':'Touchez pour lire en entier')+'">'+esc(head)+'</h3>';
 // the cast of the night, one pill each, only those who did something
 const CAST=[['day','Le chercheur','var(--accent-soft)',DAY.length],['crit',en?'The critic':'Le critique','#b98cff',CRQ.length],['build',en?'The builder':'Le constructeur','var(--up-soft)',BLD.length]].filter(c=>num(c[0]));
 if(CAST.length)h+='<div class="nt-cast">'+CAST.map(c=>'<button class="nt-pill" onclick="ntGo(&#39;'+c[0]+'&#39;)"><i style="background:'+c[2]+'"></i>'+c[1]+(c[3]?' <em>\u00b7 '+c[3]+'</em>':'')+'</button>').join('')+'</div>';
 if(parts.length>1)h+='<div class="nt-nav">'+parts.map((x,i)=>'<button data-k="'+x[0]+'"'+(i===0?' class="on"':'')+' onclick="ntGo(&#39;'+x[0]+'&#39;)"><i>'+('0'+num(x[0])).slice(-2)+'</i>'+esc(x[1])+'</button>').join('')+'</div>';
 if(tot){h+=sh('res',en?'Every idea is tested on the last 42 days of the market, cut in two halves. \u201cBetter on both\u201d is the strongest result.':'Chaque id\u00e9e est test\u00e9e sur les 42 derniers jours du march\u00e9, coup\u00e9s en deux moiti\u00e9s. \u00ab Mieux sur les deux \u00bb est le r\u00e9sultat le plus solide.')+
  '<div class="nt-tiles">'+
  '<div class="nt-tile"><b style="color:var(--up-soft)">'+(cc.A||0)+'</b><span>'+(en?'better on both halves':'mieux sur les deux moiti\u00e9s')+'</span></div>'+
  '<div class="nt-tile"><b style="color:var(--accent-soft)">'+(cc.B||0)+'</b><span>'+(en?'a little better':'un peu mieux')+'</span></div>'+
  '<div class="nt-tile"><b style="color:var(--muted)">'+((cc.C||0)+(cc['=']||0))+'</b><span>'+(en?'no':'non')+'</span></div></div>'+
  '<div class="nt-cap">'+tot+' '+(en?'ideas tested in all':'id\u00e9es test\u00e9es en tout')+
  // 2026-10-03 (owner): raw or charged? The measured cost of trading is
  // counted in every verdict once it rests on 30 like-for-like trades.
  (function(){const D=j.drag;if(!D||!D.trades)return '';const per=Math.abs(D.per_trade||0).toFixed(2);
   if(AU.charged)return ' \u00b7 '+(en?'each verdict counts the real cost of trading, about $'+per+' a trade':'chaque verdict compte le vrai co\u00fbt de trader, environ '+per.replace('.',',')+' $ par trade');
   return ' \u00b7 '+(en?'raw: the real cost of trading ($'+per+' a trade) is counted at 30 measured trades, '+D.trades+' so far':'brut : le vrai co\u00fbt de trader ('+per.replace('.',',')+' $ par trade) sera compt\u00e9 \u00e0 30 trades mesur\u00e9s, '+D.trades+' pour l\u2019instant');})()+'</div></div>';}
 if(num('day')){h+=sh('day',en?'What the researcher saw while watching the robot today.':'Ce que le chercheur a vu en surveillant le robot aujourd\u2019hui.')+
  '<div class="nt-day">'+DAY.map(v=>{let hm='';try{hm=new Date(v.t).toLocaleTimeString(en?'en-GB':'fr-FR',{hour:'2-digit',minute:'2-digit'});}catch(e){}
   return '<div class="nt-ev"><span class="nt-dot"></span><time>'+esc(hm)+'</time><p>'+esc(en?(v.en||v.fr):(v.fr||v.en))+'</p></div>';}).join('')+'</div></div>';}
 if(num('crit')){h+=sh('crit',en?'A second AI tries to break every idea that scored better on both halves, before it can earn a twin.':'Une seconde intelligence artificielle essaie de casser chaque id\u00e9e mieux sur les deux moiti\u00e9s, avant qu\u2019elle n\u2019ait droit \u00e0 un jumeau.')+
  CRQ.map(c=>{const jn=jGet(c.id);const cl=jn?JCOLS.find(x=>x[0]===jn.col):null;
   return '<div class="nt-card">'+chip(VW[c.verdict])+'<b>'+esc(titleOf(c.id))+'</b><span class="nt-w">'+esc(en?(c.en||c.fr):(c.fr||c.en))+'</span>'+
    (jn&&cl?'<button class="tfc nt-go" onclick="ntIdea(&#39;'+esc(jn.id)+'&#39;)">'+(en?'See it on the board':'La voir sur le tableau')+' \u00b7 '+esc(en?cl[2]:cl[1])+' \u203a</button>':'')+'</div>';}).join('')+'</div>';}
 if(num('build')){h+=sh('build',en?'A third AI builds what the researcher asks for - a dial for the test, a fact, a tool - behind the gates. Nothing changes in the robot until an idea wins its duel.':'Une troisi\u00e8me intelligence artificielle construit ce que le chercheur demande \u2014 un r\u00e9glage pour le test, un fait, un outil \u2014 derri\u00e8re les contr\u00f4les. Rien ne change dans le robot tant qu\u2019une id\u00e9e n\u2019a pas gagn\u00e9 son duel.')+
  BLD.map(b=>{const t=en?(b.title_en||b.title_fr):(b.title_fr||b.title_en);const note=b.status==='built'?(en?(b.built_note_en||b.built_note_fr):(b.built_note_fr||b.built_note_en)):(b.status==='declined'?(en?(b.decline_en||b.decline_fr):(b.decline_fr||b.decline_en)):(b.build_error||''));
   return '<div class="nt-card">'+chip(BW[b.status])+'<b>'+esc(t)+'</b>'+(note?'<span class="nt-w">'+esc(note)+'</span>':'')+(b.built_date||b.date?'<span class="nt-w" style="color:var(--muted)">'+esc(b.built_date||b.date)+'</span>':'')+'</div>';}).join('')+
  // 2026-10-03 (owner): what still waits, oldest first - the builder takes up to two a night
  (function(){const open=RQ.filter(r=>!r.status||r.status==='open').slice().sort((a,b)=>String(a.date||'').localeCompare(String(b.date||'')));
   if(!open.length)return '<div class="nt-cap">'+(en?'Nothing waits to be built.':'Rien n\u2019attend d\u2019\u00eatre construit.')+'</div>';
   const nx=open[0];return '<div class="nt-cap">'+(open.length>1?(en?open.length+' requests wait':open.length+' demandes attendent'):(en?'One request waits':'Une demande attend'))+' \u00b7 '+(en?'next: ':'la prochaine : ')+'\u00ab '+esc(en?(nx.title_en||nx.title_fr):(nx.title_fr||nx.title_en))+' \u00bb'+(nx.date?' ('+esc(nx.date)+')':'')+'</div>';})()+'</div>';}
 if(num('ret')){h+=sh('ret');
  if(secs.length)h+=secs.map((x,i)=>'<details class="nt-fold"'+(i===0?' open':'')+'><summary>'+esc(en?(x.title_en||x.title_fr):(x.title_fr||x.title_en))+'<svg class="ic chv"><use href="#i-chev"/></svg></summary><div class="nt-b">'+paras(en?(x.en||x.fr):(x.fr||x.en))+'</div></details>').join('');
  else h+='<div class="nt-card">'+paras(en?(N.en||N.fr):(N.fr||N.en))+'</div>';
  h+='</div>';}
 if(num('bel')){
  const SC={nouveau:'var(--accent-soft)',new:'var(--accent-soft)','renforc\u00e9':'var(--up-soft)',strengthened:'var(--up-soft)',remonte:'var(--up-soft)',rising:'var(--up-soft)',affaibli:'var(--warn)',weakened:'var(--warn)',douteux:'var(--warn)',doubtful:'var(--warn)'};
  h+=sh('bel',en?'What the researcher now holds to be true, and what it rests on.':'Ce que le chercheur tient maintenant pour vrai, et sur quoi il s\u2019appuie.')+bel.map(b=>{
   let ev=String(b.evidence||'');
   {let at=-1,best=1e9,k=ev.indexOf(' / ');
    while(k>=0){const d=Math.abs(k-(ev.length-k-3));if(d<best){best=d;at=k;}k=ev.indexOf(' / ',k+1);}
    if(at>0&&best<0.35*ev.length)ev=en?ev.slice(at+3):ev.slice(0,at);}
   let chip='';const m=ev.match(/^([A-Za-z\u00c0-\u00ff']{3,14})(, [^:]{1,30})?\s?:\s+/);
   if(m){const w=m[1].trim();const c=SC[w.toLowerCase()];if(c){chip='<span class="nt-chip" style="color:'+c+';background:rgba(255,255,255,.06)">'+esc(w)+'</span>';
    const x=m[2]?m[2].slice(2):'';ev=(x?x.charAt(0).toUpperCase()+x.slice(1)+' : ':'')+ev.slice(m[0].length);}}
   return '<div class="nt-card">'+chip+'<b>'+esc(en?(b.en||b.fr):(b.fr||b.en))+'</b>'+(ev?'<span class="nt-w">'+esc(ev)+'</span>':'')+'</div>';}).join('')+'</div>';}
 if(num('try')){const JJ=j.journeys||[];
  h+=sh('try',en?'New ideas from the researcher. Each one already had a first test; it is on the board, and the button shows you where.':'Les nouvelles id\u00e9es du chercheur. Chacune a d\u00e9j\u00e0 eu un premier test : elle est sur le tableau, et le bouton vous montre o\u00f9.')+PR.map(p=>{
   const jn=JJ.find(x=>x.id===p.id);const cl=jn?JCOLS.find(c=>c[0]===jn.col):null;
   return '<div class="nt-card">'+(jn&&jn.critique?chip(VW[jn.critique.verdict]):'')+'<b>'+esc(en?(p.title_en||p.title_fr):(p.title_fr||p.title_en))+'</b>'+((en?p.why_en:p.why_fr)?'<span class="nt-w">'+esc(en?p.why_en:p.why_fr)+'</span>':'')+
    (jn&&cl?'<button class="tfc nt-go" onclick="ntIdea(&#39;'+esc(jn.id)+'&#39;)">'+(en?'See it on the board':'La voir sur le tableau')+' \u00b7 '+esc(en?cl[2]:cl[1])+' \u203a</button>':'')+'</div>';}).join('')+'</div>';}
 if(num('ask'))h+=sh('ask',en?'Things it cannot do alone and asks us to build.':'Ce qu\u2019il ne peut pas faire seul et nous demande de construire.')+RQ.map(r=>'<div class="nt-card"><b>'+esc(en?(r.title_en||r.title_fr):(r.title_fr||r.title_en))+'</b>'+((en?(r.why_en||r.what_en):(r.why_fr||r.what_fr))?'<span class="nt-w">'+esc(en?(r.why_en||r.what_en):(r.why_fr||r.what_fr))+'</span>':'')+'</div>').join('')+'</div>';
 h+='<button class="shbtn shghost" style="margin-top:18px" onclick="_shDone(1)">'+(en?'Close':'Fermer')+'</button>';
 sheet(h);}
function ntIdea(id){const j=jGet(id);if(!j)return;const i=JCOLS.findIndex(c=>c[0]===j.col);
 window._shDone&&window._shDone(1);
 setTimeout(()=>{jGo(i,1);setTimeout(()=>{const e=document.querySelector('[data-jid="'+id+'"]');
  const f=e&&e.closest('div[hidden]');if(f&&f.previousElementSibling)f.previousElementSibling.click();
  if(e){e.scrollIntoView({behavior:'smooth',block:'center'});e.classList.remove('jland');void e.offsetWidth;e.classList.add('jland');}},650);},520);}
function ntGo(k){const e=document.getElementById('nt-'+k);if(e)e.scrollIntoView({behavior:'smooth',block:'start'});
 document.querySelectorAll('.nt-nav button').forEach(b=>{b.classList.toggle('on',b.dataset.k===k);if(b.dataset.k===k)b.scrollIntoView({block:'nearest',inline:'center'});});}
function labItem(id){const j=window._lab;if(!j)return;const it=(j.items||[]).find(x=>x.id===id);if(!it)return;const en=LANG()==='en';
 const _jj=jGet(id);
 sheet('<h3>'+(en?it.title_en:it.title_fr)+'</h3>'+(_jj?jStrip(_jj,en)+'<button class="tfc" style="margin:4px 0 8px" onclick="labJourney(&#39;'+id+'&#39;)">'+(en?'Its story':'Son histoire')+' \u203a</button>':'')+'<p style="color:var(--text)">'+(en?it.note_en:it.note_fr)+'</p>'+
  '<div class="lbl" style="margin-top:8px">'+(en?'Numbers':'Les chiffres')+'</div><p style="font-size:.86rem;color:var(--text2)">'+(en?it.nums_en:it.nums_fr)+'</p>'+
  '<div class="lbl" style="margin-top:8px">'+(en?'Where':'O\u00f9')+'</div><p style="font-size:.8rem;color:var(--muted2)">'+(it.src||'-')+' \u00b7 '+(it.date||'')+' \u00b7 '+(en?'verdict':'verdict')+' '+(vWord(it.verdict,en)||'\u2014')+' \u00b7 '+(en?'robot':'robot')+' : '+(it.robot||'non')+'</p>'+
  '<button class="shbtn shghost" onclick="_shDone(1)">'+(en?'Close':'Fermer')+'</button>');}
// ---- batch 33b (owner): the market space shows the PATTERNS being established,
// each with its evidence, its confidence and whether the robot uses it ----
// 2026-10-01: move the real block into the sheet, then put it back. The
// alternative - cloning its HTML - gives two elements with the same id, and
// loadPatterns writes by id, so the copy on screen would freeze while the
// hidden original kept updating.
// 2026-10-01 (owner): same pattern as the lessons card - the real block
// travels into the sheet and back, so nothing is ever duplicated.
function rjOpen(){
 const w=document.getElementById('rj-wrap');
 if(!w)return;
 const mark=document.createElement('span');
 mark.style.display='none';
 w.parentElement.insertBefore(mark,w);
 const p=sheet('<div class="lbl">Journal du robot</div>'+
  '<div id="rj-host"></div>');
 setTimeout(()=>{const h=document.getElementById('rj-host');
  if(h){h.appendChild(w);w.style.display='block';}},60);
 p.then(()=>{w.style.display='none';
  if(mark.parentElement){mark.parentElement.insertBefore(w,mark);mark.remove();}
  else{const r=document.getElementById('mx-robot');if(r)r.appendChild(w);}});
}
function lrnOpen(){
 const w=document.getElementById('lrn-wrap');
 if(!w)return;
 const mark=document.createElement('span');
 mark.style.display='none';
 w.parentElement.insertBefore(mark,w);
 const p=sheet('<div id="lrn-host"></div>');
 setTimeout(()=>{const h=document.getElementById('lrn-host');
  if(h){h.appendChild(w);w.style.display='block';}},60);
 p.then(()=>{w.style.display='none';
  if(mark.parentElement){mark.parentElement.insertBefore(w,mark);mark.remove();}
  else{document.getElementById('mx-market').appendChild(w);}});
}
async function loadPatterns(d){const sec=document.getElementById('lrn-sec'),list=document.getElementById('lrn-list'),nx=document.getElementById('lrn-next');if(!sec||!list)return;
 if(HIDEGAUGES()||d.public){sec.style.display='none';list.style.display='none';nx.style.display='none';{const cd=document.getElementById('lrn-card');if(cd)cd.style.display='none';}return;}
 if(window._lrnT&&Date.now()-window._lrnT<600000)return;window._lrnT=Date.now();
 let j=null;try{const r=await fetch(B+'patterns?t='+Date.now(),{cache:'no-store'});if(r.ok)j=await r.json();}catch(e){}
 if(!j||j.err){sec.style.display='none';list.style.display='none';nx.style.display='none';{const cd=document.getElementById('lrn-card');if(cd)cd.style.display='none';}return;}
 const en=LANG()==='en';
 const ST={confirme:[en?'Sure':'S\u00fbr','var(--up-soft)','rgba(46,204,113,.14)'],vivant:[en?'Measured live':'Mesur\u00e9 en direct','var(--accent-soft)','rgba(59,130,246,.14)'],observation:[en?'Not sure yet':'Pas encore s\u00fbr','var(--warn)','rgba(232,197,90,.14)'],candidat:[en?'To try':'\u00c0 essayer','#b98cff','rgba(185,140,255,.14)'],rejete:[en?'Checked: no':'V\u00e9rifi\u00e9 : non','var(--muted2)','rgba(255,255,255,.06)']};
 const RB={oui:[en?'the robot does this':'le robot le fait','var(--up-soft)'],candidat:[en?'the robot may, later':'le robot, peut-\u00eatre plus tard','#b98cff'],non:[en?'the robot does not':'le robot ne le fait pas','var(--muted)']};
 const chip=(t,c,bg)=>'<span class="pchip" style="color:'+c+';background:'+bg+'">'+t+'</span>';
 list.innerHTML=(j.cards||[]).map(c=>{const st=ST[c.status]||ST.observation,rb=RB[c.robot]||RB.non;
  const row=(k,t)=>'<div class="prow"><span class="pk">'+k+'</span><span style="flex:1;min-width:0">'+t+'</span></div>';
  return '<div class="panel pcard" style="margin-top:10px;padding:14px">'+
   '<div style="display:flex;gap:11px;align-items:flex-start"><div class="sic" style="color:'+st[1]+';background:'+st[2]+';width:36px;height:36px"><svg class="ic ic-s"><use href="#'+(c.icon||'i-activity')+'"/></svg></div>'+
   '<div style="flex:1;min-width:0"><h4 style="margin:0;font-size:.95rem;font-weight:700;line-height:1.3;color:var(--text)">'+(en?c.title_en:c.title)+'</h4><div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:6px">'+chip(st[0],st[1],st[2])+chip(rb[0],rb[1],'rgba(255,255,255,.05)')+'</div></div></div>'+
   '<div style="display:flex;align-items:baseline;gap:8px;margin:12px 0 4px"><b style="font-size:1.7rem;letter-spacing:-.02em;color:'+st[1]+';font-variant-numeric:tabular-nums">'+c.fig+'</b><span style="font-size:.76rem;color:var(--muted2);line-height:1.3">'+(en?c.fig_l_en:c.fig_l)+'</span></div>'+
   row(en?'For real':'En vrai',(en?c.live_en:c.live))+row(en?'On the past':'Sur le pass\u00e9',(en?c.back_en:c.back))+row(en?'The robot':'Le robot',(en?c.robot_note_en:c.robot_note))+
   '<div class="pman"><span class="pk">'+(en?'If you trade yourself':'Si vous tradez vous-m\u00eame')+'</span>'+(en?c.manual_en:c.manual)+'</div>'+
   '</div>';}).join('');
 document.getElementById('lrn-hint').textContent='\u00b7 '+(en?'what we have learned so far':'ce qu\u2019on a appris jusqu\u2019ici');
 list.insertAdjacentHTML('afterbegin','<div class="panel labintro"><b style="font-size:.95rem">'+(en?'Read this like a notebook':'\u00c0 lire comme un carnet')+'</b><div style="font-size:.84rem;color:var(--text2);line-height:1.5;margin-top:6px">'+(en?'Each card is one thing we noticed about the market. It says how sure we are, what the real trades show, what the past showed, and what the robot does with it. Numbers under 30 trades are just a start.':'Chaque carte est une chose qu\u2019on a remarqu\u00e9e sur le march\u00e9. Elle dit \u00e0 quel point on en est s\u00fbr, ce que montrent les vrais trades, ce que montrait le pass\u00e9, et ce que le robot en fait. Sous 30 trades, un chiffre n\u2019est qu\u2019un d\u00e9but.')+'</div><div style="font-size:.74rem;color:var(--muted);margin-top:8px">'+(j.live_trades||0)+' '+(en?'real trades':'vrais trades')+' \u00b7 '+(j.memory_days||0)+' '+(en?'days of market memory':'jours de m\u00e9moire du march\u00e9')+'</div></div>');
 setH(nx,'<div class="lbl">'+(en?'What comes next':'La suite')+'</div><div style="font-size:.9rem;color:var(--text);line-height:1.5;margin-top:6px">'+(en?j.next.en:j.next.fr)+'</div><div style="font-size:.74rem;color:var(--muted);margin-top:8px">'+(en?'The cards refresh every 10 minutes with the new trades and the market memory.':'Les cartes se mettent \u00e0 jour toutes les 10 minutes avec les nouveaux trades et la m\u00e9moire du march\u00e9.')+'</div>');
 sec.style.display='block';list.style.display='block';nx.style.display='block';
 // the card is what the member actually sees on the main page
 {const cd=document.getElementById('lrn-card');
  if(cd){const n=(j.cards||[]).length;
   document.getElementById('lrn-card-t').textContent=en
    ?'What the market teaches us':'Ce que le march\u00e9 nous apprend';
   document.getElementById('lrn-card-s').textContent=en
    ?(n+' observation'+(n>1?'s':'')+' \u00b7 what we have learned so far')
    :(n+' observation'+(n>1?'s':'')+' \u00b7 ce qu\u2019on a appris jusqu\u2019ici');
   cd.style.display=n?'block':'none';}}
}
// ---- batch 33: the two spaces grow - market hours, next action, the robot explains, journal ----
async function loadMarketHours(d){const el=document.getElementById('mhcard');if(!el)return;
 if(HIDEGAUGES()||d.public){el.style.display='none';return;}
 if(window._mhT&&Date.now()-window._mhT<600000)return;window._mhT=Date.now();
 let j=null;try{const r=await fetch(B+'market_hours?t='+Date.now(),{cache:'no-store'});if(r.ok)j=await r.json();}catch(e){}
 if(!j||j.err){el.style.display='none';return;}
 const en=LANG()==='en';
 // UTC cells -> the phone's local weekday/hour
 const M=new Map();(j.cells||[]).forEach(c=>{const dt=new Date(Date.UTC(2024,0,1+c.wd,c.h));const k=((dt.getDay()+6)%7)+'_'+dt.getHours();M.set(k,c);});
 const DN=en?['Mon','Tue','Wed','Thu','Fri','Sat','Sun']:['lun','mar','mer','jeu','ven','sam','dim'];
 const col=v=>v<1?'var(--muted)':(v<1.3?'var(--warn)':(v<1.85?'#e8743b':'var(--down)'));
 let h='<div style="display:grid;grid-template-columns:34px repeat(24,1fr);gap:2px;align-items:center">';
 h+='<span></span>'+[0,6,12,18].map((x,i)=>'<span style="grid-column:'+(2+x)+' / span 6;font-size:.6rem;color:var(--muted)">'+x+'h</span>').join('');
 // 2026-10-01 (owner): a day the five-day memory has not reached drew a
 // row of empty cells, which reads as broken rather than as not-yet.
 const seen=new Set();(j.cells||[]).forEach(c=>{const dt=new Date(
  Date.UTC(2024,0,1+c.wd,c.h));seen.add((dt.getDay()+6)%7);});
 for(let w=0;w<7;w++){h+='<span style="font-size:.64rem;color:var(--muted)'+
  (seen.has(w)?'':';opacity:.45')+'">'+DN[w]+'</span>';
  for(let hh=0;hh<24;hh++){const c=M.get(w+'_'+hh);const op=c?Math.min(1,0.25+c.n/40):0;
   h+='<i title="'+DN[w]+' '+hh+'h'+(c?' \u00b7 '+c.med.toFixed(2)+'\u00d7 ('+c.n+')':'')+'" style="display:block;height:11px;border-radius:3px;background:'+(c?col(c.med):'var(--surface3)')+';opacity:'+(c?op:0.35)+'"></i>';}}
 h+='</div>';
 setH(document.getElementById('mh-grid'),h);
 const leg=(c,l)=>'<span style="display:inline-flex;align-items:center;gap:4px"><i style="width:10px;height:10px;border-radius:3px;background:'+c+'"></i>'+l+'</span>';
 setH(document.getElementById('mh-leg'),leg('var(--muted)',en?'calm':'calme')+leg('var(--warn)',en?'brisk':'soutenu')+leg('#e8743b',en?'fast':'rapide')+leg('var(--down)',en?'very fast':'tr\u00e8s rapide')+'<span style="margin-left:auto">'+(en?'your local time':'heure locale')+'</span>');
 document.getElementById('mh-hint').textContent='\u00b7 '+(j.days||0)+' '+(en?'day'+(j.days>1?'s':'')+' of memory':'jour'+(j.days>1?'s':'')+' de m\u00e9moire');
 el.style.display='block';
}
function tfPaint(d){const el=document.getElementById('tfcard');if(!el)return;
 const a=d.tf_align;
 if(!a||!a.rows||!a.rows.length||HIDEGAUGES()||d.public){el.style.display='none';return;}
 const en=LANG()==='en';
 const UP='var(--up)',DN='var(--down)',FLAT='var(--muted2)';
 const col=t=>t===1?UP:t===-1?DN:FLAT;
 const word=t=>t===1?(en?'up':'hausse'):t===-1?(en?'down':'baisse'):(en?'flat':'sans tendance');
 const arrow=t=>t===1?'\u25b2':t===-1?'\u25bc':'\u2014';
 // plain ages: a number nobody has to convert
 const dur=sec=>{const m=Math.round(sec/60);
  if(m<60)return m+' min';
  const h=Math.round(m/60);if(h<48)return h+' h';
  return Math.round(h/24)+(en?' d':' j');};
 // the whole ladder, biggest first - the same order as the chart, where the
 // higher timeframe always sits first
 const all=a.rows.concat([{k:'M1',trend:a.m1,int:a.m1_int,me:true}]);
 // ---- verdict -------------------------------------------------------
 const n=a.n,ag=a.agree,big=(a.up===n)?1:(a.dn===n)?-1:0;
 let head,say,hc;
 if(!a.m1){head=en?'The minute has no trend yet':'La minute n\u2019a pas encore de tendance';
  say=en?'It is waiting for a structure to form.':'Elle attend qu\u2019une structure se dessine.';hc=FLAT;}
 else if(ag===n&&big){head=en?'Everything points the same way':'Tout va dans le m\u00eame sens';
  say=(en?'The big timeframes and the minute agree.':'Les grands temps et la minute sont d\u2019accord.')+
   (a.together&&(a.together_exact||a.together>=1800)
     ?(en?' Together for '+(a.together_exact?'':'over ')+dur(a.together)+'.'
        :' Ensemble depuis '+(a.together_exact?'':'plus de ')+dur(a.together)+'.'):'');hc=col(a.m1);}
 else if(ag===0&&big){head=en?'The minute goes against the big picture':'La minute va contre les grands temps';
  say=en?'Often a pullback inside the bigger move.':'Souvent un repli \u00e0 l\u2019int\u00e9rieur du grand mouvement.';hc='var(--warn)';}
 else if(!big){head=en?'The big timeframes disagree':'Les grands temps ne sont pas d\u2019accord';
  say=en?'No single direction above the minute.':'Aucun sens unique au-dessus de la minute.';hc='var(--warn)';}
 else{head=(en?ag+' of '+n+' agree with the minute':ag+' temps sur '+n+' d\u2019accord avec la minute');
  say=en?'Mixed picture.':'Image partag\u00e9e.';hc='var(--warn)';}
 setH(document.getElementById('tf-head'),
  '<div style="display:flex;align-items:center;gap:12px">'+
   '<div style="width:44px;height:44px;border-radius:14px;flex:none;display:flex;'+
    'align-items:center;justify-content:center;font-size:1.05rem;font-weight:800;'+
    'color:'+col(big||a.m1)+';background:color-mix(in srgb,'+hc+' 14%,transparent);'+
    'border:1px solid color-mix(in srgb,'+hc+' 34%,transparent)">'+arrow(big||a.m1)+'</div>'+
   '<div style="flex:1;min-width:0">'+
    '<b style="font-size:1.0rem;letter-spacing:.01em;display:block">'+head+'</b>'+
    '<div style="font-size:.78rem;color:var(--muted2);line-height:1.4;margin-top:2px">'+say+'</div>'+
   '</div></div>');
 // ---- the ladder ----------------------------------------------------
 // one diverging bar per timeframe: it grows right when the structure is
 // rising and left when it is falling, so agreement is a shape, not a word
 let h='';
 all.forEach((r,i)=>{
  const c=col(r.trend),pct=r.trend?50:6;
  const dot=(r.int&&r.trend&&r.int!==r.trend)
   ? '<i title="'+(en?'inner structure the other way':'petite structure en sens inverse')+'" style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#9d8cff;box-shadow:0 0 6px rgba(157,140,255,.7)"></i>'
   : (r.int?'<i style="display:inline-block;width:7px;height:7px;border-radius:50%;background:'+col(r.int)+';opacity:.55"></i>'
          :'<i style="display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--surface3)"></i>');
  h+='<div style="display:grid;grid-template-columns:40px 1fr 74px 12px;align-items:center;gap:9px;'+
   'padding:7px 0'+(r.me?';border-top:1px solid var(--surface3);margin-top:5px;padding-top:11px':'')+'">'+
   '<span style="font-size:.66rem;font-weight:800;letter-spacing:.06em;color:'+(r.me?'var(--fg)':'var(--muted)')+'">'+r.k+'</span>'+
   '<span style="position:relative;display:block;height:8px;border-radius:99px;background:var(--surface3);overflow:hidden">'+
    '<i style="position:absolute;top:0;bottom:0;left:50%;width:1px;background:rgba(255,255,255,.14)"></i>'+
    '<i style="position:absolute;top:0;bottom:0;'+(r.trend===-1?'right:50%':'left:50%')+';width:'+pct+'%;'+
     'background:linear-gradient(90deg,color-mix(in srgb,'+c+' 45%,transparent),'+c+');'+
     'border-radius:99px"></i></span>'+
   '<span style="font-size:.74rem;font-weight:700;color:'+c+'">'+word(r.trend)+
    ((r.held!=null&&r.trend&&(r.exact||r.held>=1800))?'<span style="display:block;font-size:.6rem;font-weight:600;color:var(--muted);margin-top:1px">'+(r.exact?'':(en?'over ':'plus de '))+dur(r.held)+'</span>':'')+
   '</span>'+
   dot+'</div>';});
 setH(document.getElementById('tf-rows'),h);
 // ---- footer --------------------------------------------------------
 setH(document.getElementById('tf-foot'),
  (()=>{const lg=(c,t)=>'<span style="display:inline-flex;align-items:center;gap:5px">'+
    '<i style="display:inline-block;width:7px;height:7px;border-radius:50%;background:'+c+'"></i>'+t+'</span>';
   return '<div style="display:flex;flex-wrap:wrap;gap:13px;font-size:.64rem;color:var(--muted)">'+
    '<span style="width:100%;font-size:.58rem;letter-spacing:.07em;text-transform:uppercase;color:var(--muted2);margin-bottom:-4px">'+
     (en?'the dot: the small structure inside':'le point : la petite structure \u00e0 l\u2019int\u00e9rieur')+'</span>'+
    lg('#9d8cff',en?'other way':'sens inverse')+
    lg('var(--up)',en?'same way':'m\u00eame sens')+
    lg('var(--surface3)',en?'none':'aucune')+'</div>';})());
 // 2026-10-01 (owner): this card looks like advice. It is not. Alignment
 // was measured twice and predicts neither the outcome of a trade (E012)
 // nor the size of a loss (E025). Say so on the card, or a member reads
 // "everything agrees" as "a better trade".
 setH(document.getElementById('tf-foot'),
  (document.getElementById('tf-foot').innerHTML||'')+
  '<div style="margin-top:9px;padding-top:8px;border-top:1px solid var(--surface3);'+
   'font-size:.68rem;color:var(--muted);line-height:1.45">'+
   (en?'This is the market\u2019s shape, not a trading signal. We measured it twice: '+
       'whether the timeframes agree does not predict whether a trade wins, '+
       'nor how big a loss will be.'
     :'C\u2019est la forme du march\u00e9, pas un signal de trade. Mesur\u00e9 deux fois : '+
      'que les temps soient d\u2019accord ne pr\u00e9dit ni si un trade gagne, '+
      'ni la taille d\u2019une perte.')+'</div>');
 document.getElementById('tf-hint').textContent='\u00b7 '+
  (a.age<90?(en?'live':'en direct'):(en?'updated '+Math.round(a.age/60)+' min ago':'il y a '+Math.round(a.age/60)+' min'));
 el.style.display='block';
}
function renderNext(d){const el=document.getElementById('rb-next');if(!el)return;const en=LANG()==='en';
 const ms=d.meteo_struct;if(!ms||HIDEGAUGES()||d.public){el.style.display='none';return;}
 const full=!!(ms.next_bos!==undefined||ms.invalid!==undefined);
 const rv=(ms.vol_now&&ms.vol_ref)?ms.vol_now/Math.max(ms.vol_ref,1):1;
 const debt=d.ledger&&d.ledger.debt>0.5,open=(d.open_positions||0)>0,tr=ms.trend;
 const lvl=v=>(full&&typeof v==='number')?' ('+(en?'level ':'niveau ')+v.toFixed(0)+')':'';
 let t;
 if(d.trading_paused)t=en?'Manual mode: the robot does not enter. The service sends you the next playable signal.':'Mode manuel : le robot n\u2019entre pas. Le service vous enverra le prochain signal jouable.';
 else if(open)t=en?'A trade is open: the robot follows it to the stop or the target, nothing else.':'Un trade est en cours : le robot le suit jusqu\u2019au stop ou \u00e0 la cible, rien d\u2019autre.';
 else if(rv>=1.85)t=en?'Very fast market: the robot does nothing until it calms down.':'March\u00e9 tr\u00e8s rapide : le robot ne fait rien tant que \u00e7a ne se calme pas.';
 else if(ms.flip_bos_ready)t=(en?'The direction may change: it waits for the confirmation before entering the other way':'Le sens peut changer : il attend la confirmation avant d\u2019entrer dans l\u2019autre sens')+lvl(ms.flip_bos)+'.';
 else if(tr===1||tr===-1){const up=tr===1;
  t=(debt?(en?'Catching up: one continuation at most, then it waits for the next flip. ':'En rattrapage : une continuation au plus, puis il attend la prochaine bascule. '):'')+
   (ms.bos_ready?(en?'It waits for a break '+(up?'upwards':'downwards'):'Il attend une cassure vers le '+(up?'haut':'bas'))+lvl(ms.next_bos)+(en?' to enter with the trend.':' pour entrer dans le sens de la tendance.')
    :(en?'It waits for the '+(up?'up':'down')+'trend to form its next level.':'Il attend que la tendance '+(up?'haussi\u00e8re':'baissi\u00e8re')+' forme son prochain niveau.'));}
 else t=en?'No trend yet: it waits for a structure to form.':'Pas de tendance pour l\u2019instant : il attend qu\u2019une structure se dessine.';
 setH(el,'<span style="font-size:.6rem;color:var(--accent-soft);text-transform:uppercase;letter-spacing:.08em;display:block;margin-bottom:3px">'+(en?'Next action':'Prochaine action')+'</span>'+t);
 el.style.display='block';
}
// ---- 2026-09-29 (owner): "La preuve" - the retention card. A report a
// client pays for: health ring, area chart with the rules and the halves,
// week by week, real vs test, progress to the 30-trade judgement, verdicts.
const PL={green:['var(--up-soft)','\u2713'],amber:['var(--warn)','!'],red:['var(--down-soft)','\u00d7'],grey:['var(--muted)','\u2026']};
window._pfLot=0.02;
const pfK=()=>(window._pfLot||0.02)/0.02;   // every replay amount is for 0.02 lot; the reader picks their stake
const pfMn=v=>(v===null||v===undefined)?'\u2014':((v>=0?'+':'\u2212')+Math.abs(v*pfK()).toFixed(0)+'\u202f$');
const pfMn2=v=>(v===null||v===undefined)?'\u2014':((v>=0?'+':'\u2212')+(LANG()==='en'?Math.abs(v*pfK()).toFixed(2):Math.abs(v*pfK()).toFixed(2).replace('.',','))+'\u202f$');
const pfRaw=v=>(v===null||v===undefined)?'\u2014':((v>=0?'+':'\u2212')+Math.abs(v).toFixed(0)+'\u202f$');
function pfSetLot(l){window._pfLot=l;try{localStorage.setItem('owlPfLot',String(l));}catch(e){}proofPage();}
function pfRef(){return 250*pfK();}
function pfRing(lights,c,word,big){const n=lights.length||3;const R=big?36:30,cx=big?46:37,C=2*Math.PI*R,seg=C/n,gap=6;
 const arcs=lights.map((l,i)=>'<circle cx="'+cx+'" cy="'+cx+'" r="'+R+'" fill="none" stroke="'+(PL[l.c]||PL.grey)[0]+'" stroke-width="7" stroke-linecap="round" stroke-dasharray="'+(seg-gap).toFixed(1)+' '+(C-(seg-gap)).toFixed(1)+'" stroke-dashoffset="'+(-(i*seg)).toFixed(1)+'" transform="rotate(-90 '+cx+' '+cx+')"/>').join('');
 return '<div class="pf-ring'+(big?' big':'')+'"><svg viewBox="0 0 '+(cx*2)+' '+(cx*2)+'"><circle cx="'+cx+'" cy="'+cx+'" r="'+R+'" fill="none" stroke="var(--surface3)" stroke-width="7"/>'+arcs+'</svg><b style="color:'+c+'">'+word+'</b></div>';}
function pfWord(c,en,big){return (big?{green:en?'Yes':'Oui',amber:en?'Watch':'Surveiller',red:en?'No':'Non',grey:en?'Soon':'Bient\u00f4t'}:{green:en?'Yes':'Oui',amber:en?'Watch':'\u00c0 voir',red:en?'No':'Non',grey:en?'Soon':'Bient\u00f4t'})[c]||'';}
function pfGreen(lights,en){const ok=lights.filter(l=>l.c==='green').length;return en?ok+' of '+lights.length+' green':ok+' sur '+lights.length+' au vert';}
function pfSince(j,en){
 let seen=0;try{seen=parseInt(localStorage.getItem('owlPfSeen:'+B)||'0')||0;}catch(e){}
 const day=t=>new Date(t).toISOString().slice(0,10);
 if(!seen){try{localStorage.setItem('owlPfSeen:'+B,String(Date.now()));}catch(e){}return '';}
 const since=day(seen);const news=[];
 (j.rules||[]).forEach(r=>{if((r.date||'')>since)news.push((en?'a new rule entered the robot: ':'une nouvelle r\u00e8gle est entr\u00e9e dans le robot : ')+_escS(en?r.title_en:r.title_fr));});
 (j.twins||[]).forEach(t=>{const st=(t.started||'').slice(0,10);if(st>since)news.push((en?'a trial copy started: ':'une copie d\u2019essai a d\u00e9marr\u00e9 : ')+_escS(en?t.title_en:t.title_fr));});
 const N=((j.history||{}).nights)||[];const after=N.filter(r=>(r.d||'')>since);
 if(after.length){const before=N.filter(r=>(r.d||'')<=since).pop();const now=after[after.length-1];
  if(before&&now&&before.o!==now.o){const W={green:en?'yes':'oui',amber:en?'watch':'\u00e0 surveiller',red:en?'no':'non',grey:'\u2026'};
   news.push((en?'the verdict changed to ':'le verdict est pass\u00e9 \u00e0 ')+'<b style="color:'+(PL[now.o]||PL.grey)[0]+'">'+(W[now.o]||'')+'</b>');}}
 try{localStorage.setItem('owlPfSeen:'+B,String(Date.now()));}catch(e){}
 if(!news.length)return '';
 return '<div style="margin-top:10px;padding:9px 11px;border-radius:12px;background:var(--surface2);border:1px solid var(--accent-soft);font-size:.78rem;line-height:1.5;color:var(--text)"><b style="color:var(--accent-soft);font-size:.62rem;letter-spacing:.08em;text-transform:uppercase;display:block;margin-bottom:3px">'+(en?'Since your last visit':'Depuis votre derni\u00e8re visite')+'</b>'+news.slice(0,3).map(x=>'\u00b7 '+x).join('<br>')+'</div>';}
function pfDots(hist,en){if(!hist||!(hist.nights||[]).length)return '';const N=hist.nights;return '<div class="pf-dots">'+N.map((r,i)=>'<i class="'+(i===N.length-1?'today':'')+'" style="background:'+(PL[r.o]||PL.grey)[0]+'" title="'+_escS(r.d)+'"></i>').join('')+'<span style="font-size:.72rem;color:var(--muted2);margin-left:4px">'+(hist.streak>1?(en?'the verdict has not moved for '+hist.streak+' nights':'le verdict n\u2019a pas boug\u00e9 depuis '+hist.streak+' nuits'):(N.length>1?(en?'last '+N.length+' nights':N.length+' derni\u00e8res nuits'):(en?'first night recorded':'premi\u00e8re nuit enregistr\u00e9e')))+'</span></div>';}
function pfSpark(cv,c){if(!cv||cv.length<2)return '';const ys=cv.map(p=>p[1]);const mx=Math.max(...ys,0),mn=Math.min(...ys,0),sp=Math.max(1e-6,mx-mn);const n=cv.length;
 const pts=cv.map((p,i)=>(1+i/(n-1)*54).toFixed(1)+','+(20-((p[1]-mn)/sp)*18).toFixed(1)).join(' ');return '<svg viewBox="0 0 56 22"><polyline points="'+pts+'" fill="none" stroke="'+c+'" stroke-width="1.6" stroke-linejoin="round"/></svg>';}
function pfWeeks(cv){if(!cv||cv.length<8)return [];const W=[];let wk=null,start=null,last=null;
 cv.forEach(p=>{const d=new Date(p[0]+'T00:00:00Z');const mon=new Date(d);mon.setUTCDate(d.getUTCDate()-((d.getUTCDay()+6)%7));const k=mon.toISOString().slice(0,10);if(k!==wk){if(wk!==null)W.push([wk,last-start]);wk=k;start=last===null?p[1]:last;}last=p[1];});
 if(wk!==null)W.push([wk,last-start]);return W;}
async function loadProof(d){const el=document.getElementById('proofcard');if(!el)return;
 if(window._prT&&Date.now()-window._prT<600000)return;window._prT=Date.now();
 let j=null;try{const r=await fetch(B+'proof?t='+Date.now(),{cache:'no-store'});if(r.ok)j=await r.json();}catch(e){}
 if(!j||j.err){el.style.display='none';return;}
 window._proof=j;const en=LANG()==='en';const F=j.base.full||{},U=j.union||{},M=j.mine,oc=(PL[(j.overall||{}).c]||PL.grey)[0];el.style.setProperty('--pfc',oc);el.style.borderColor=oc;
 const L=j.lights||[];const by=k=>L.find(l=>l.k===k)||{c:'grey'};
 document.getElementById('proof-lbl').innerHTML=(en?'Proof of profitability':'Preuve de rentabilit\u00e9')+' <span class="hint">\u00b7 '+(en?'of the strategy':'de la strat\u00e9gie')+'</span>';
 const ahead=(j.twins||[]).filter(t=>t.status==='ahead').length;
 setH(document.getElementById('proof-lights'),'<div class="pf-hero">'+pfRing(L,oc,pfWord((j.overall||{}).c,en))+'<div style="flex:1;min-width:0"><div class="pf-verdict">'+_escS(en?(j.overall||{}).en:(j.overall||{}).fr)+'</div><div class="pf-sub">'+pfGreen(L,en)+' \u00b7 '+(en?'is this strategy still worth staying with? Three checks, redone every night.':'cette strat\u00e9gie vaut-elle encore qu\u2019on reste ? Trois v\u00e9rifications, refaites chaque nuit.')+'</div></div></div>'+
  pfDots(j.history,en)+pfSince(j,en)+
  '<div class="pf-rows">'+
  '<div class="pf-row">'+proofDot(by('replay').c)+'<div class="t"><b>'+(en?'On the past, it makes money':'Sur le pass\u00e9, elle gagne')+'</b><span>'+(en?'last '+Math.round(j.days)+' days, replayed':'les '+Math.round(j.days)+' derniers jours, rejou\u00e9s')+'</span></div>'+pfSpark(F.curve,(F.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+'<div class="v" style="color:'+((F.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+'">'+pfMn(F.net)+'</div></div>'+
  '<div class="pf-row">'+proofDot(by('track').c)+'<div class="t"><b>'+(en?'In real life, it follows the test':'En vrai, elle suit le test')+'</b><span>'+(U.trades||0)+' '+(en?'real trades since ':'vrais trades depuis le ')+_escS((U.since||'').slice(8,10)+'/'+(U.since||'').slice(5,7))+'</span></div><div class="v" style="color:'+((U.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+'">'+pfMn(U.net)+'</div></div>'+
  '<div class="pf-row'+(M?'':' last')+'"'+(M?'':' style="border-bottom:0"')+'>'+proofDot(by('lab').c)+'<div class="t"><b>'+(en?'No trial copy does better':'Aucune copie d\u2019essai ne fait mieux')+'</b><span>'+(j.twins||[]).length+' '+(en?'copies in the duel':'copies en duel')+'</span></div><div class="v">'+ahead+' '+(en?'ahead':'devant')+'</div></div>'+
  (M?'<div class="pf-row" style="border-bottom:0"><i style="flex:none;display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:99px;background:var(--accent-soft);color:#0b1020;font-style:normal;font-weight:900;font-size:.72rem">\u2605</i><div class="t"><b>'+(en?'On your account':'Sur votre compte')+'</b><span>'+(M.trades||0)+' trades'+(M.expected!==undefined?' \u00b7 '+(en?'test expected ':'le test attendait ')+pfRaw(M.expected):'')+'</span></div><div class="v" style="color:'+((M.net||0)>=0?'var(--up-soft)':'var(--down-soft)')+'">'+pfRaw(M.net)+'</div></div>':'')+'</div>');
 el.querySelector('.shbtn').textContent=(en?'See the proof':'Voir la preuve')+' \u203a';el.style.display='';}
function proofDot(c){const x=PL[c]||PL.grey;return '<i style="flex:none;display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:99px;background:'+x[0]+';color:#0b1020;font-style:normal;font-weight:900;font-size:.72rem">'+x[1]+'</i>';}
function pfArea(cv,rules,en){if(!cv||cv.length<2)return '';const W=320,H=150,L=34,Rr=8,T=10,Bt=26;const ys=cv.map(p=>p[1]).concat([0]);const mx=Math.max(...ys),mn=Math.min(...ys),sp=Math.max(1e-6,mx-mn);const n=cv.length;
 const X=i=>(L+i/(n-1)*(W-L-Rr)),Y=v=>(T+(1-(v-mn)/sp)*(H-T-Bt));const pts=cv.map((p,i)=>X(i).toFixed(1)+','+Y(p[1]).toFixed(1));
 const last=cv[n-1][1],col=last>=0?'var(--up-soft)':'var(--down-soft)';
 const grid=[mx,(mx+mn)/2,mn].map(v=>'<line x1="'+L+'" y1="'+Y(v).toFixed(1)+'" x2="'+(W-Rr)+'" y2="'+Y(v).toFixed(1)+'" stroke="var(--border)" stroke-width="1"/><text x="'+(L-4)+'" y="'+(Y(v)+3).toFixed(1)+'" text-anchor="end" font-size="7" fill="var(--muted)">'+(v>=0?'+':'\u2212')+Math.abs(v).toFixed(0)+'</text>').join('');
 const mid=Math.floor(n/2);const half='<rect x="'+X(mid).toFixed(1)+'" y="'+T+'" width="'+(X(n-1)-X(mid)).toFixed(1)+'" height="'+(H-T-Bt)+'" fill="var(--accent-soft)" opacity=".05"/><text x="'+((X(0)+X(mid))/2).toFixed(1)+'" y="'+(H-Bt+9)+'" text-anchor="middle" font-size="6.5" fill="var(--muted)">'+(en?'first half':'1\u00e8re moiti\u00e9')+'</text><text x="'+((X(mid)+X(n-1))/2).toFixed(1)+'" y="'+(H-Bt+9)+'" text-anchor="middle" font-size="6.5" fill="var(--muted)">'+(en?'second half':'2e moiti\u00e9')+'</text>';
 const idx={};cv.forEach((p,i)=>{idx[p[0]]=i;});const G={};(rules||[]).forEach((r,k)=>{const i=idx[r.date];if(i!==undefined)(G[i]=G[i]||[]).push(k);});
 const marks=Object.keys(G).map(i=>{i=+i;const ks=G[i];const lab=ks.length>1?(ks[0]+1)+'\u2013'+(ks[ks.length-1]+1):String(ks[0]+1);const w=lab.length>1?14:10;return '<g style="cursor:pointer" onclick="pfRule(['+ks.join(',')+'])"><line x1="'+X(i).toFixed(1)+'" y1="'+T+'" x2="'+X(i).toFixed(1)+'" y2="'+(H-Bt)+'" stroke="var(--warn)" opacity=".6" stroke-dasharray="2 3"/><rect x="'+(X(i)-w/2-4).toFixed(1)+'" y="'+(H-Bt+8)+'" width="'+(w+8)+'" height="16" rx="8" fill="transparent"/><rect x="'+(X(i)-w/2).toFixed(1)+'" y="'+(H-Bt+11)+'" width="'+w+'" height="10" rx="5" fill="var(--warn)"/><text x="'+X(i).toFixed(1)+'" y="'+(H-Bt+18.5)+'" text-anchor="middle" font-size="6.5" font-weight="800" fill="#0b1020">'+lab+'</text></g>';}).join('');
 window._pfcv=cv;window._pfgeo={L,W,Rr,n};
 return '<svg id="pf-svg" viewBox="0 0 '+W+' '+H+'" style="touch-action:pan-y" onpointerdown="pfRead(event)" onpointermove="pfRead(event)"><defs><linearGradient id="pfg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+col+'" stop-opacity=".35"/><stop offset="1" stop-color="'+col+'" stop-opacity="0"/></linearGradient></defs>'+half+grid+
  '<line x1="'+L+'" y1="'+Y(0).toFixed(1)+'" x2="'+(W-Rr)+'" y2="'+Y(0).toFixed(1)+'" stroke="var(--border2)" stroke-dasharray="3 4"/>'+
  '<polygon points="'+X(0).toFixed(1)+','+Y(0).toFixed(1)+' '+pts.join(' ')+' '+X(n-1).toFixed(1)+','+Y(0).toFixed(1)+'" fill="url(#pfg)"/>'+marks+
  '<polyline points="'+pts.join(' ')+'" fill="none" stroke="'+col+'" stroke-width="2.2" stroke-linejoin="round"/><line id="pf-cur" x1="0" y1="'+T+'" x2="0" y2="'+(H-Bt)+'" stroke="var(--text)" opacity="0"/><circle id="pf-dot" cx="0" cy="0" r="3.5" fill="var(--text)" opacity="0"/><circle cx="'+X(n-1).toFixed(1)+'" cy="'+Y(last).toFixed(1)+'" r="3.5" fill="'+col+'"/><rect x="'+(X(n-1)-34).toFixed(1)+'" y="'+(Y(last)-16).toFixed(1)+'" width="30" height="12" rx="6" fill="'+col+'"/><text x="'+(X(n-1)-19).toFixed(1)+'" y="'+(Y(last)-7.3).toFixed(1)+'" text-anchor="middle" font-size="7" font-weight="800" fill="#0b1020">'+(last>=0?'+':'\u2212')+Math.abs(last).toFixed(0)+'</text>'+
  '<text x="'+L+'" y="'+(H-2)+'" font-size="7" fill="var(--muted)">'+_escS(cv[0][0].slice(5))+'</text><text x="'+(W-Rr)+'" y="'+(H-2)+'" text-anchor="end" font-size="7" fill="var(--muted)">'+_escS(cv[n-1][0].slice(5))+'</text></svg><div class="pf-tip" id="pf-tip">'+(en?'Touch the curve to read a day. Tap a number to read the rule.':'Touchez la courbe pour lire un jour. Touchez un num\u00e9ro pour lire la r\u00e8gle.')+'</div>';}
function pfRead(e){const svg=document.getElementById('pf-svg'),cv=window._pfcv,g=window._pfgeo;if(!svg||!cv||!g)return;if(e.type==='pointermove'&&e.pointerType==='mouse'&&e.buttons===0)return;
 const r=svg.getBoundingClientRect();const x=(e.clientX-r.left)/r.width*g.W;let i=Math.round((x-g.L)/(g.W-g.L-g.Rr)*(g.n-1));i=Math.max(0,Math.min(g.n-1,i));
 const pl=svg.querySelector('polyline');const pt=pl.points.getItem(i);const cur=document.getElementById('pf-cur'),dot=document.getElementById('pf-dot');cur.setAttribute('x1',pt.x);cur.setAttribute('x2',pt.x);cur.setAttribute('opacity','.5');dot.setAttribute('cx',pt.x);dot.setAttribute('cy',pt.y);dot.setAttribute('opacity','1');
 const en=LANG()==='en';const d=cv[i][0];const tip=document.getElementById('pf-tip');if(tip)tip.innerHTML='<b>'+(en?d.slice(5):d.slice(8,10)+'/'+d.slice(5,7))+'</b> \u00b7 '+(en?'the account was at ':'le compte \u00e9tait \u00e0 ')+'<b style="color:'+(cv[i][1]>=0?'var(--up-soft)':'var(--down-soft)')+'">'+pfMn(cv[i][1])+'</b>';}
function pfRule(ks){const j=window._proof;if(!j)return;const en=LANG()==='en';const tip=document.getElementById('pf-tip');if(!tip)return;
 tip.innerHTML=ks.map(k=>{const r=(j.rules||[])[k];if(!r)return '';return '<div style="margin-top:3px"><b style="color:var(--warn)">'+(k+1)+'</b> '+_escS((r.date||'').slice(8,10)+'/'+(r.date||'').slice(5,7))+' \u00b7 '+_escS(en?r.title_en:r.title_fr)+(r.verdict?' <span style="color:var(--muted)">('+(en?'graded ':'not\u00e9e ')+_escS(r.verdict)+(en?' on the past':' sur le pass\u00e9')+')</span>':'')+'</div>';}).join('');}
function pfKpi(el){el.classList.toggle('open');}
// the normal-range band: where the real result sits among what the test
// calls normal for that many trades
function pfBand(b,v,en,who){if(!b)return '';const lo=Math.min(b.lo,v,0),hi=Math.max(b.hi,v,0);const sp=Math.max(1e-6,hi-lo);const P=x=>((x-lo)/sp*100).toFixed(1);const inside=v>=b.lo&&v<=b.hi;
 return '<div style="margin-top:12px"><div style="display:flex;justify-content:space-between;font-size:.72rem;color:var(--muted2)"><span>'+(en?'Normal range for '+b.n+' trades':'Fourchette normale pour '+b.n+' trades')+'</span><span>'+pfMn(b.lo)+' \u2192 '+pfMn(b.hi)+'</span></div>'+
  '<div style="position:relative;height:14px;margin-top:6px"><div style="position:absolute;left:0;right:0;top:5px;height:4px;border-radius:99px;background:var(--surface3)"></div><div style="position:absolute;top:5px;height:4px;border-radius:99px;background:var(--accent-soft);opacity:.55;left:'+P(b.lo)+'%;width:'+(P(b.hi)-P(b.lo)).toFixed(1)+'%"></div><div style="position:absolute;top:0;width:14px;height:14px;border-radius:99px;background:'+(inside?'var(--up-soft)':'var(--down-soft)')+';border:2px solid var(--surface);left:calc('+P(v)+'% - 7px)"></div><div style="position:absolute;top:2px;width:1px;height:10px;background:var(--muted);left:'+P(0)+'%"></div></div>'+
  '<div style="font-size:.74rem;color:var(--text);margin-top:4px;line-height:1.45">'+(inside?(en?(who||'The result')+' ('+pfMn(v)+') is <b style="color:var(--up-soft)">inside</b> what the test calls normal for so few trades.':(who||'Le r\u00e9sultat')+' ('+pfMn(v)+') est <b style="color:var(--up-soft)">dans</b> ce que le test consid\u00e8re normal pour si peu de trades.'):(en?(who||'The result')+' ('+pfMn(v)+') is <b style="color:var(--down-soft)">outside</b> the normal range: watch closely.':(who||'Le r\u00e9sultat')+' ('+pfMn(v)+') est <b style="color:var(--down-soft)">en dehors</b> de la fourchette normale : \u00e0 surveiller de pr\u00e8s.'))+'</div></div>';}
function pfWeekBars(cv,en){const W=pfWeeks(cv);if(W.length<2)return '';const w=320,h=92,L=6,T=12,B=20;const mx=Math.max(...W.map(x=>Math.abs(x[1])),1);const bw=(w-L*2)/W.length;const Y0=T+(h-T-B)/2;const sc=(h-T-B)/2/mx;
 return '<svg viewBox="0 0 '+w+' '+h+'"><line x1="'+L+'" y1="'+Y0+'" x2="'+(w-L)+'" y2="'+Y0+'" stroke="var(--border2)"/>'+W.map((x,i)=>{const v=x[1],c=v>=0?'var(--up-soft)':'var(--down-soft)';const bh=Math.abs(v)*sc;const y=v>=0?Y0-bh:Y0;return '<rect x="'+(L+i*bw+bw*.18).toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+(bw*.64).toFixed(1)+'" height="'+Math.max(1.5,bh).toFixed(1)+'" rx="3" fill="'+c+'" opacity=".9"/><text x="'+(L+i*bw+bw/2).toFixed(1)+'" y="'+(v>=0?y-3:y+bh+8).toFixed(1)+'" text-anchor="middle" font-size="6.5" font-weight="800" fill="'+c+'">'+(v>=0?'+':'\u2212')+Math.abs(v).toFixed(0)+'</text><text x="'+(L+i*bw+bw/2).toFixed(1)+'" y="'+(h-4)+'" text-anchor="middle" font-size="6.5" fill="var(--muted)">'+_escS(x[0].slice(5))+'</text>';}).join('')+'</svg>';}
function pfBars(rows,en){const mx=Math.max(...rows.map(r=>Math.abs(r[1]||0)),1);return rows.map(r=>{const v=r[1]||0,c=v>=0?'var(--up-soft)':'var(--down-soft)';const pct=Math.abs(v)/mx*100;return '<div class="pf-bar"><div class="l">'+r[0]+'</div><div class="b"><i style="background:'+c+';left:0;width:'+pct.toFixed(0)+'%"></i></div><div class="v" style="color:'+c+'">'+pfMn(v)+'</div></div>';}).join('');}
function pfPct(rows){return rows.map(r=>'<div class="pf-bar"><div class="l">'+r[0]+'</div><div class="b"><i style="background:'+r[2]+';left:0;width:'+Math.max(0,Math.min(100,r[1]||0))+'%"></i></div><div class="v">'+(r[1]===null||r[1]===undefined?'\u2014':r[1]+'\u202f%')+'</div></div>').join('');}
// ---- 2026-09-30 (owner): "preuve de rentabilite de la strategie" - full
// screen slides, few words, the STRATEGY measured once on a reference
// account so the numbers never depend on whose balance it is, and one slide
// that answers "and does MY bot match the test?" ----
function pvPct(v, bal){return ((v>=0?'+':'\u2212')+Math.abs(v/(bal||200)*100).toFixed(1)+'\u202f%');}
function pvCard(v,l,sm,c){return '<div class="pv-c"><b style="color:'+(c||'var(--text)')+'">'+v+'</b><span>'+l+'</span>'+(sm?'<small>'+sm+'</small>':'')+'</div>';}
function proofPage(){const j=window._proof;if(!j)return;const en=LANG()==='en';const esc=_escS;
 const F=j.base.full||{},H1=j.base.h1||{},H2=j.base.h2||{},S=j.stats||{},Lg=(j.base_long||{}).full||null;
 const U=j.union||{},E=j.expected||{},M=j.mine,MR=j.mine_run||{},LB=j.lab||{},SRC=j.sources||{};
 const D=Math.round(j.days||0),BAL=j.ref_balance||200,oc=(PL[(j.overall||{}).c]||PL.grey)[0];
 const dmy=d=>d?(en?d.slice(5):d.slice(8,10)+'/'+d.slice(5,7)):'';
 const up='var(--up-soft)',down='var(--down-soft)';
 const S2=[];
 // 1 - the verdict
 S2.push({k:en?'The verdict':'Le verdict',b:()=>
  '<div style="display:flex;gap:14px;align-items:center;margin-top:6px">'+pfRing(j.lights||[],oc,pfWord((j.overall||{}).c,en),true)+
   '<div style="flex:1;min-width:0"><div class="pv-h" style="color:'+oc+';margin:0">'+esc(en?(j.overall||{}).en:(j.overall||{}).fr)+'</div>'+
   '<div class="pv-p" style="margin-top:4px">'+pfGreen(j.lights||[],en)+'</div></div></div>'+
  pfDots(j.history,en)+
  '<div style="margin-top:14px">'+(j.lights||[]).map(l=>'<div class="pv-row">'+proofDot(l.c)+'<div class="t">'+
    ({replay:en?'On the past, it makes money':'Sur le pass\u00e9, elle gagne',track:en?'In real life, it follows the test':'En vrai, elle suit le test',lab:en?'No trial copy does better':'Aucune copie d\u2019essai ne fait mieux'}[l.k]||l.k)+'</div></div>').join('')+'</div>'+
  '<div class="pv-note">'+(en?'Three checks, redone every night by the same engine, with rules of judgement that never change.':'Trois v\u00e9rifications, refaites chaque nuit par le m\u00eame moteur, avec des r\u00e8gles de jugement qui ne changent jamais.')+'</div>'});
 // 2 - the strategy on the past
 S2.push({k:en?'The strategy, tested':'La strat\u00e9gie, test\u00e9e',b:()=>
  '<div class="pv-h">'+(en?'What the strategy earns on the past':'Ce que la strat\u00e9gie rapporte sur le pass\u00e9')+'</div>'+
  '<div class="pv-p">'+(en?'The robot as it is today, replayed on the last '+D+' days, on a reference account of '+BAL+' $. Costs counted.':'Le robot tel qu\u2019il est aujourd\u2019hui, rejou\u00e9 sur les '+D+' derniers jours, sur un compte de r\u00e9f\u00e9rence de '+BAL+' $. Frais compt\u00e9s.')+'</div>'+
  '<div class="pv-big"><b style="color:'+((F.net||0)>=0?up:down)+'">'+pvPct(F.net||0,BAL)+'</b><span>'+(en?'in '+D+' days':'en '+D+' jours')+'</span></div>'+
  '<div class="pv-g">'+
   pvCard((S.wr||0).toFixed(0)+'\u202f%',en?'trades won':'trades gagn\u00e9s',(F.trades||0)+' trades',up)+
   pvCard((S.pf||0).toFixed(2),en?'profit factor':'profit factor',en?'won per 1 $ lost':'gagn\u00e9 pour 1 $ perdu',(S.pf>1?up:down))+
   pvCard('\u2212'+Math.abs((S.maxdd||0)/BAL*100).toFixed(1)+'\u202f%',en?'biggest dip':'plus grosse baisse',en?'the patience it asks for':'la patience qu\u2019elle demande',down)+
   pvCard((S.per_week||0).toFixed(0),en?'trades a week':'trades par semaine',en?'it works while you sleep':'elle travaille pendant que vous dormez')+
  '</div>'+
  '<div class="pv-chart">'+pfArea(F.curve,j.rules,en)+'</div>'+
  '<div class="pv-note">'+(en?'Percentages are of the reference account. Your own money depends on your balance and your stake.':'Les pourcentages sont ceux du compte de r\u00e9f\u00e9rence. Votre argent d\u00e9pend de votre solde et de votre mise.')+'</div>'});
 // 3 - does it hold over time
 S2.push({k:en?'Does it hold?':'Est-ce que \u00e7a tient ?',b:()=>
  '<div class="pv-h">'+(en?'The same strategy, cut in pieces':'La m\u00eame strat\u00e9gie, coup\u00e9e en morceaux')+'</div>'+
  '<div class="pv-p">'+(en?'A strategy that only wins once may have been lucky. We cut the period in two, and we look at a longer window.':'Une strat\u00e9gie qui ne gagne qu\u2019une fois a peut-\u00eatre eu de la chance. On coupe la p\u00e9riode en deux, et on regarde une fen\u00eatre plus longue.')+'</div>'+
  '<div class="pv-g">'+
   pvCard(pvPct(H1.net||0,BAL),en?'first half':'1\u00e8re moiti\u00e9',en?'the older days':'les jours les plus anciens',(H1.net||0)>=0?up:down)+
   pvCard(pvPct(H2.net||0,BAL),en?'second half':'2e moiti\u00e9',en?'the recent days':'les jours r\u00e9cents',(H2.net||0)>=0?up:down)+
   (Lg?pvCard(pvPct(Lg.net||0,BAL),(en?'over ':'sur ')+j.days_long+(en?' days':' jours'),(Lg.trades||0)+' trades',(Lg.net||0)>=0?up:down):'')+
   pvCard((S.max_streak||0)+'',en?'losses in a row':'pertes d\u2019affil\u00e9e',en?'the worst run to sit through':'la pire s\u00e9rie \u00e0 encaisser','var(--warn)')+
  '</div>'+
  '<div class="pv-chart"><div style="font-size:.66rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--muted2);margin-bottom:2px">'+(en?'Week by week':'Semaine par semaine')+'</div>'+pfWeekBars(F.curve,en)+'</div>'+
  '<div class="pv-note">'+(en?'Green weeks and red weeks are both normal. What matters is the sum over time, and that both halves agree.':'Des semaines vertes et des semaines rouges, c\u2019est normal. Ce qui compte, c\u2019est la somme dans le temps, et que les deux moiti\u00e9s soient d\u2019accord.')+'</div>'});
 // 4 - in real life
 S2.push({k:en?'In real life':'En vrai',b:()=>
  '<div class="pv-h">'+(en?'Do the real trades match the test?':'Les vrais trades ressemblent-ils au test ?')+'</div>'+
  (U.trades?('<div class="pv-p">'+(en?'Every real trade the robot took since '+dmy(U.since)+', on accounts nobody has touched by hand.':'Tous les vrais trades pris par le robot depuis le '+dmy(U.since)+', sur des comptes que personne n\u2019a touch\u00e9s \u00e0 la main.')+'</div>'+
  '<div class="pv-g">'+
   pvCard((U.trades||0)+'',en?'real trades':'vrais trades',(en?'since ':'depuis le ')+dmy(U.since))+
   pvCard((U.wr===null||U.wr===undefined?'\u2014':U.wr+'\u202f%'),en?'won in real life':'gagn\u00e9s en vrai',(en?'the test says ':'le test dit ')+(S.wr||0).toFixed(0)+'\u202f%'+(U.clean?(en?' \u00b7 '+U.clean.wr.toFixed(0)+'\u202f% without the retired rule':' \u00b7 '+U.clean.wr.toFixed(0)+'\u202f% sans la r\u00e8gle retir\u00e9e'):''),(U.wr>=(S.wr||0)-8)?up:'var(--warn)')+
  '</div>'+
  '<div class="pv-chart">'+pfBars([[en?'In real life':'En vrai',U.net],[en?'Expected':'Attendu',E?E.net:null],[en?'Test, same entries':'Test, m\u00eames entr\u00e9es',(j.replay_same||{}).net]],en)+
   pfBand(j.band,U.net,en,en?'The real result':'Le r\u00e9sultat r\u00e9el')+'</div>'+
  '<div class="pf-prog" style="margin-top:12px"><div style="display:flex;justify-content:space-between;font-size:.78rem"><b>'+(U.trades||0)+' / 30 '+(en?'real trades':'vrais trades')+'</b><span style="color:var(--muted2)">'+(en?'before we judge':'avant de juger')+'</span></div><div class="b"><i style="width:'+Math.min(100,(U.trades||0)/30*100).toFixed(0)+'%"></i></div></div>'+
  (function(){var DG=SRC.drag;
   if(!DG||!DG.trades)return '';
   var per=(DG.per_trade==null?null:DG.per_trade);
   var h=(DG.history||[]).filter(function(x){return x.per_trade!=null;});
   var trend='';
   if(h.length>=3){
    var a=h[0].per_trade, b=h[h.length-1].per_trade;
    trend=(en?' Over '+h.length+' readings it has gone from '
             :' Sur '+h.length+' relev\u00e9s, il est pass\u00e9 de ')
       +a.toFixed(2)+(en?' to ':' \u00e0 ')+b.toFixed(2)+'.';}
   return '<div class="pv-note" style="border-left:2px solid var(--muted2);'+
    'padding-left:9px;margin-bottom:8px;color:var(--muted2)">'+
    (en?('Cost of trading: the test says these '+DG.trades+' entries should '+
         'have made '+(DG.expected>=0?'+$':'-$')+Math.abs(DG.expected).toFixed(2)+
         ' and they made '+(DG.actual>=0?'+$':'-$')+Math.abs(DG.actual).toFixed(2)+
         '. The '+(DG.gap>=0?'+$':'-$')+Math.abs(DG.gap).toFixed(2)+' difference is '+
         'spread and fills'+(per==null?'':', about $'+Math.abs(per).toFixed(2)+' a trade')+
         '.'+trend)
      :('Ce que trader co\u00fbte : le test dit que ces '+DG.trades+' entr\u00e9es '+
        'auraient d\u00fb faire '+(DG.expected>=0?'+$':'-$')+Math.abs(DG.expected).toFixed(2)+
        ', elles ont fait '+(DG.actual>=0?'+$':'-$')+Math.abs(DG.actual).toFixed(2)+
        '. L\u2019\u00e9cart de '+(DG.gap>=0?'+$':'-$')+Math.abs(DG.gap).toFixed(2)+
        ' vient du spread et des ex\u00e9cutions'+
        (per==null?'':', environ $'+Math.abs(per).toFixed(2)+' par trade')+'.'+trend))+
    // 2026-10-03 (owner): when does the test start counting this cost
    ('<div style="margin-top:6px">'+(DG.usable
      ?(en?'Measured on '+DG.trades+' trades: the lab\u2019s tests count this cost in every verdict.':'Mesur\u00e9 sur '+DG.trades+' trades : les tests du labo comptent ce co\u00fbt dans chaque verdict.')
      :(en?DG.trades+' / 30 trades measured \u00b7 at 30, the lab\u2019s tests will count this cost in every verdict.':DG.trades+' / 30 trades mesur\u00e9s \u00b7 \u00e0 30, les tests du labo compteront ce co\u00fbt dans chaque verdict.'))+'</div>')+
    '</div>';})()+
  (function(){var RC=SRC.rule_change;
   if(!RC||!RC.live_trades)return '';
   return '<div class="pv-note" style="border-left:2px solid var(--warn);'+
    'padding-left:9px;margin-bottom:8px;color:var(--muted2)">'+
    (en?('Honest note: until '+RC.off_since+' the robot also traded the small '+
         'inner structure, and this test never included that rule. '+
         RC.live_trades+' of the '+RC.of_total+' real trades below came from '+
         'it, for '+(RC.live_net>=0?'+$':'-$')+Math.abs(RC.live_net).toFixed(2)+
         '. The rule is switched off since '+RC.off_since+', so the test and '+
         'the real trades follow the same rules from that date.')
       :('Note honn\u00eate : jusqu\u2019au '+RC.off_since+', le robot tradait '+
         'aussi la petite structure interne, et ce test n\u2019a jamais '+
         'inclus cette r\u00e8gle. '+RC.live_trades+' des '+RC.of_total+
         ' vrais trades ci-dessous en '+(RC.live_trades>1?'viennent':'vient')+
         ', pour '+
         (RC.live_net>=0?'+$':'-$')+Math.abs(RC.live_net).toFixed(2)+
         '. La r\u00e8gle est coup\u00e9e depuis le '+RC.off_since+
         ', donc le test et les vrais trades suivent les m\u00eames '+
         'r\u00e8gles \u00e0 partir de cette date.'))+'</div>';})()+
  '<div class="pv-note">'+(en?'Sources: '+(SRC.real_accounts||0)+' real account'+((SRC.real_accounts||0)>1?'s':'')+(SRC.demo?' and one demo':'')+', never touched by hand. Names are not shown.':'Sources : '+(SRC.real_accounts||0)+' compte'+((SRC.real_accounts||0)>1?'s':'')+' r\u00e9el'+((SRC.real_accounts||0)>1?'s':'')+(SRC.demo?' et un d\u00e9mo':'')+', jamais touch\u00e9s \u00e0 la main. Les noms ne sont pas montr\u00e9s.')+'</div>')
   :('<div class="pv-p" style="color:var(--muted);margin-top:10px">'+(en?'No real trades in the journal yet.':'Pas encore de vrais trades dans le journal.')+'</div>'))});
 // 5 - your account
 if(M)S2.push({k:en?'Your account':'Votre compte',b:()=>
  '<div class="pv-h">'+(en?'Is your bot doing what the test says?':'Votre robot fait-il ce que dit le test ?')+'</div>'+
  '<div class="pv-p">'+(en?'The test rerun with YOUR balance, YOUR stake and YOUR daily cap, against what your bot actually did.':'Le test refait avec VOTRE solde, VOTRE mise et VOTRE plafond du jour, face \u00e0 ce que votre robot a vraiment fait.')+'</div>'+
  '<div class="pv-g">'+
   pvCard(pfRaw(M.net),en?'your result':'votre r\u00e9sultat',(M.trades||0)+' trades '+(en?'since ':'depuis le ')+dmy(M.since),(M.net||0)>=0?up:down)+
   pvCard(pfRaw(M.expected),en?'test, your days':'test, vos jours',en?'what it expected':'ce qu\u2019il attendait',(M.expected||0)>=0?up:down)+
  '</div>'+
  pfBandRaw(M.band,M.net,en,en?'Your result':'Votre r\u00e9sultat')+
  '<div class="pv-g" style="margin-top:12px">'+
   pvCard((MR.lot||0).toFixed(2),en?'your stake':'votre mise',(en?'balance ':'solde ')+Math.round(MR.balance||0)+' $')+
   pvCard((MR.day_cap?('+'+(MR.day_cap||0).toFixed(2)+' $'):(en?'none':'aucun')),en?'your daily stop':'votre plafond du jour',en?'it stops for the day there':'il s\u2019arr\u00eate pour la journ\u00e9e l\u00e0')+
  '</div>'+
  '<div class="pv-note">'+((M.trades||0)<30?(en?'Under 30 trades, luck still weighs a lot. The band above shows what the test calls normal for '+(M.trades||0)+' trades.':'Sous 30 trades, la chance p\u00e8se encore beaucoup. La barre ci-dessus montre ce que le test consid\u00e8re normal pour '+(M.trades||0)+' trades.'):'')+'</div>'});
 // 6 - the lab keeps changing it
 S2.push({k:en?'It keeps improving':'Elle continue d\u2019avancer',b:()=>{const cc=LB.counts||{};
  return '<div class="pv-h">'+(en?'The strategy is not frozen':'La strat\u00e9gie n\u2019est pas fig\u00e9e')+'</div>'+
  '<div class="pv-p">'+(en?'Every night an AI replays the market, challenges the robot and proposes changes. Nothing reaches your account before it passes the three steps.':'Chaque nuit, une intelligence artificielle rejoue le march\u00e9, bouscule le robot et propose des changements. Rien n\u2019arrive sur votre compte avant d\u2019avoir pass\u00e9 les trois \u00e9tapes.')+'</div>'+
  '<div class="pv-g">'+
   pvCard(((cc.A||0)+(cc.B||0)+(cc.C||0)+(cc['=']||0))+'',en?'ideas replayed last night':'id\u00e9es test\u00e9es cette nuit',(cc.A||0)+' A \u00b7 '+(cc.B||0)+' B \u00b7 '+(cc.C||0)+' C')+
   pvCard((LB.rules||0)+'',en?'rules in the robot':'r\u00e8gles dans le robot',en?'each one earned its place':'chacune a gagn\u00e9 sa place',up)+
   pvCard((LB.twins||0)+'',en?'copies on trial':'copies \u00e0 l\u2019essai',en?'playing for pretend, no money':'jouent pour de faux, sans argent','var(--accent-soft)')+
   pvCard((LB.archived||0)+'',en?'ideas set aside':'id\u00e9es mises de c\u00f4t\u00e9',en?'said no three nights running':'ont dit non trois nuits de suite','var(--muted2)')+
  '</div>'+
  '<div class="pv-note">'+(en?'Last replay '+esc((LB.updated||'').slice(0,16).replace('T',' '))+' UTC, over '+Math.round(LB.days||0)+' days. The lab is in the Labo tab.':'Dernier rejeu le '+esc((LB.updated||'').slice(0,16).replace('T',' '))+' UTC, sur '+Math.round(LB.days||0)+' jours. Le labo est dans l\u2019onglet Labo.')+'</div>';}});
 // 7 - how we judge
 S2.push({k:en?'How we judge':'Comment on juge',b:()=>
  '<div class="pv-h">'+(en?'The rules never move':'Les r\u00e8gles ne bougent jamais')+'</div>'+
  '<div class="pf-steps" style="margin-top:12px"><div><b>A</b>'+(en?'better on both halves and overall':'mieux sur les deux moiti\u00e9s et au total')+'</div><div><b>B</b>'+(en?'a little better':'un peu mieux')+'</div><div><b>C</b>'+(en?'no':'non')+'</div></div>'+
  '<div style="margin-top:14px">'+
   '<div class="pv-row"><div class="t">'+(en?'An idea must win on an account with a daily cap AND on one without':'Une id\u00e9e doit gagner sur un compte avec plafond ET sur un sans')+'</div></div>'+
   '<div class="pv-row"><div class="t">'+(en?'Two good nights in a row before a copy is started':'Deux bonnes nuits de suite avant de lancer une copie')+'</div></div>'+
   '<div class="pv-row"><div class="t">'+(en?'A copy must beat the robot over 30 trades before anyone decides':'Une copie doit battre le robot sur 30 trades avant qu\u2019on d\u00e9cide')+'</div></div>'+
   '<div class="pv-row"><div class="t">'+(en?'Demo first, then one real account at a time':'La d\u00e9mo d\u2019abord, puis un vrai compte \u00e0 la fois')+'</div></div>'+
  '</div>'+
  '<div class="pv-note">'+(en?'Tests use one-minute candles from MetaTrader 5 ('+esc(j.symbol||'BTCUSD')+'), the jar, the daily cap and the stop line exactly as the live bot has them. Past results are not a promise.':'Les tests utilisent les bougies d\u2019une minute de MetaTrader 5 ('+esc(j.symbol||'BTCUSD')+'), la tirelire, le plafond du jour et la ligne d\u2019arr\u00eat exactement comme le robot les a. Les r\u00e9sultats pass\u00e9s ne sont pas une promesse.')+'</div>'});
 window._pv={S:S2,i:0};
 sheet('<div class="pv" id="pv"></div>');
 (function paint(n){if(!document.getElementById('pv')){if(n>0)setTimeout(()=>paint(n-1),110);return;}pvPaint();})(25);}
function lotFrX(){return String(window._pfLot||0.02).replace('.',LANG()==='en'?'.':',');}
function pfBandRaw(b,v,en,who){if(!b)return '';const k=pfK();return pfBand({n:b.n,lo:b.lo/k,hi:b.hi/k,mid:b.mid/k},v/k,en,who);}
function pvPaint(){const st=window._pv;if(!st)return;const el=document.getElementById('pv');const s=st.S[st.i];if(!el||!s)return;const en=LANG()==='en';const j=window._proof||{};
 const dots=st.S.map((x,k)=>'<i style="width:'+(k===st.i?18:6)+'px;background:'+(k===st.i?'var(--accent-soft)':'var(--border2)')+'"></i>').join('');
 el.innerHTML='<div class="pv-top"><span class="pv-k">'+(en?'Proof of profitability':'Preuve de rentabilit\u00e9')+'</span><span class="pv-n">'+(st.i+1)+' / '+st.S.length+'</span></div>'+
  '<div class="pv-k" style="color:var(--muted2)">'+_escS(s.k)+'</div>'+
  '<div class="pv-body">'+s.b()+'</div>'+
  '<div class="pv-dots">'+dots+'</div>'+
  '<div class="pv-nav">'+(st.i===0?'<button class="shbtn shghost" style="flex:1;margin:0" onclick="pfShare()">'+(en?'Share':'Partager')+'</button>':'<button class="shbtn shghost" style="flex:1;margin:0" onclick="window._pv.i--;pvPaint()">'+(en?'Back':'Retour')+'</button>')+
  (st.i<st.S.length-1?'<button class="shbtn shmain" style="flex:1;margin:0" onclick="window._pv.i++;pvPaint()">'+(en?'Next':'Suivant')+'</button>':'<button class="shbtn shmain" style="flex:1;margin:0" onclick="_shDone(1)">'+(en?'Close':'Fermer')+'</button>')+'</div>';
 let x0=null,y0=null;el.ontouchstart=e=>{x0=e.touches[0].clientX;y0=e.touches[0].clientY;};
 el.ontouchend=e=>{if(x0===null)return;const dx=e.changedTouches[0].clientX-x0,dy=e.changedTouches[0].clientY-y0;x0=null;
  if(Math.abs(dx)>55&&Math.abs(dx)>Math.abs(dy)*1.4){if(dx<0&&st.i<st.S.length-1){st.i++;pvPaint();}else if(dx>0&&st.i>0){st.i--;pvPaint();}}};}
function pfGo(n){const sc=document.getElementById('pf-scroll'),el=document.getElementById('pf-s'+n);if(!sc||!el)return;sc.scrollTo({top:el.offsetTop-sc.offsetTop-52,behavior:'smooth'});}
async function loadWhy(d){const el=document.getElementById('whycard');if(!el)return;
 if(HIDEGAUGES()||d.public){el.style.display='none';return;}
 if(window._whyT&&Date.now()-window._whyT<300000)return;window._whyT=Date.now();
 let j=null;try{const r=await fetch(B+'robot_why?t='+Date.now(),{cache:'no-store'});if(r.ok)j=await r.json();}catch(e){}
 if(!j||j.err||j.src==='none'){el.style.display='none';return;}
 const en=LANG()==='en';
 const L={meteo:[en?'the weather':'la m\u00e9t\u00e9o','var(--warn)'],rattrapage:[en?'the catch-up pause':'la pause du rattrapage','var(--accent-soft)'],tendance:[en?'against the trend':'contre la tendance','var(--muted2)'],limite:[en?'level already taken':'niveau d\u00e9j\u00e0 pris','var(--text3)'],autre:[en?'other':'autre','var(--muted)']};
 const T=j.today||{},W=j.week||{};
 const parts=Object.keys(L).filter(k=>T[k]).sort((a,b)=>T[b]-T[a]).map(k=>T[k]+' '+(en?'for ':'pour ')+L[k][0]);
 document.getElementById('why-sum').innerHTML=(j.total_today?(en?'Today the robot let <b>'+j.total_today+'</b> opportunit'+(j.total_today>1?'ies':'y')+' go: ':'Aujourd\u2019hui, le robot a laiss\u00e9 passer <b>'+j.total_today+'</b> occasion'+(j.total_today>1?'s':'')+' : ')+parts.join(', ')+'.':(en?'No opportunity let go today.':'Aucune occasion laiss\u00e9e passer aujourd\u2019hui.'))+
  ' <span style="color:var(--muted2)">'+(en?'This week: ':'Cette semaine : ')+(j.total_week||0)+'.</span>';
 const mx=Math.max(1,...Object.keys(L).map(k=>W[k]||0));
 document.getElementById('why-bars').innerHTML=Object.keys(L).filter(k=>W[k]).map(k=>'<div style="display:flex;align-items:center;gap:8px;padding:5px 0;font-size:.78rem"><span style="width:150px;color:var(--muted2)">'+L[k][0]+'</span><span style="flex:1;height:7px;border-radius:99px;background:var(--surface3);overflow:hidden;position:relative"><i style="position:absolute;left:0;top:0;bottom:0;width:'+Math.round((W[k]||0)/mx*100)+'%;background:'+L[k][1]+';border-radius:99px;opacity:.85"></i></span><b style="width:52px;text-align:right">'+(T[k]||0)+' / '+(W[k]||0)+'</b></div>').join('')+
  '<div style="font-size:.66rem;color:var(--muted);margin-top:6px;text-align:right">'+(en?'today / 7 days':'aujourd\u2019hui / 7 jours')+'</div>';
 el.style.display='block';
}
async function loadJournal(d){const el=document.getElementById('rjcard');if(!el)return;
 if(HIDEGAUGES()||d.public){el.style.display='none';return;}
 if(window._rjT&&Date.now()-window._rjT<120000)return;window._rjT=Date.now();
 let j=null;try{const r=await fetch(B+'robot_journal?t='+Date.now(),{cache:'no-store'});if(r.ok)j=await r.json();}catch(e){}
 const it=(j&&j.items)||[];const en=LANG()==='en';
 if(!it.length){el.style.display='none';return;}
 const bandL={calme:[en?'calm':'calme','var(--muted)'],soutenu:[en?'brisk':'soutenu','var(--warn)'],rapide:[en?'fast':'rapide','#e8743b'],'tres rapide':[en?'very fast':'tr\u00e8s rapide','var(--down)']};
 const mn=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 // 2026-10-01 (owner): the card is what shows on the page now; the
 // list itself opens in a sheet. Say how many and how they went, so
 // the card is worth a tap rather than a mystery.
 {const sb=document.getElementById('rj-sub');
  if(sb){const w=it.filter(x=>(+x.p||0)>0).length;
   sb.textContent=(en
    ?it.length+' last trades · '+w+' won'
    :it.length+' derniers trades · '+w+' gagné'+(w>1?'s':''));}}
 document.getElementById('rj-list').innerHTML=it.map(x=>{const buy=(x.dir||'').toUpperCase().startsWith('A')||(x.dir||'').toUpperCase()==='BUY';const up=(+x.p||0)>=0;const b=x.band?bandL[x.band]||[x.band,'var(--muted)']:null;
  const q=B+'chart?t='+x.t+'&x='+x.x+(x.ep!=null?'&ep='+x.ep:'')+(x.xp!=null?'&xp='+x.xp:'')+'&d='+encodeURIComponent(x.dir||'')+'&p='+x.p;
  return '<a href="'+q+'" style="display:flex;align-items:center;gap:8px;padding:8px 0;border-top:1px solid var(--border);text-decoration:none;color:inherit;font-size:.82rem"><span style="color:'+(buy?'var(--up)':'var(--down)')+';font-weight:800">'+(buy?'\u25b2':'\u25bc')+'</span><span style="width:78px;color:var(--muted)">'+(x.w||'')+'</span>'+
   (b?'<span style="font-size:.62rem;font-weight:700;color:'+b[1]+';border:1px solid '+b[1]+';border-radius:99px;padding:1px 7px;opacity:.9">'+b[0]+'</span>':'<span></span>')+
   '<span style="flex:1;color:var(--muted2);text-align:right;font-size:.74rem">'+(x.dur!=null?Math.round(x.dur)+' min':'')+'</span><b style="width:64px;text-align:right;color:'+(up?'var(--up-soft)':'var(--down-soft)')+'">'+mn(+x.p||0)+'</b></a>';}).join('');
 el.style.display='block';
}
// ---- batch 32: "Ce que j'ai manque" (after a day away) + "Vous et le robot" ----
function missedCard(d){const el=document.getElementById('missedcard');if(!el)return;const en=LANG()==='en';
 const now=Date.now();
 if(window._lastVisit===undefined){let lv=0;try{lv=parseInt(localStorage.getItem('owlLastVisit:'+B)||'0',10)||0;}catch(e){}window._lastVisit=lv;}
 try{localStorage.setItem('owlLastVisit:'+B,String(now));}catch(e){}
 const lv=window._lastVisit;
 if(!lv||now-lv<86400000||d.public||window._missedDone){el.style.display='none';return;}
 const y=new Date().getUTCFullYear();let n=0,net=0;
 (d.trades||[]).forEach(x=>{const m=/^(\d\d)\/(\d\d) (\d\d):(\d\d)$/.exec(x.w||'');if(!m)return;let t=Date.UTC(y,+m[2]-1,+m[1],+m[3],+m[4]);if(t>now+86400000)t=Date.UTC(y-1,+m[2]-1,+m[1],+m[3],+m[4]);if(t>lv){n++;net+=(+x.p||0);}});
 const days=Math.max(1,Math.round((now-lv)/86400000));
 const robot=d.trading_paused?(en?'manual mode':'mode manuel'):(en?'robot on':'robot en marche');
 document.getElementById('missed-t').textContent=en?'While you were away':'Ce que vous avez manqu\u00e9';
 document.getElementById('missed-s').textContent=en?(days+' day'+(days>1?'s':'')+' away'):(days+' jour'+(days>1?'s':'')+' sans passer');
 const mn=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 const cell=(l,v,c)=>'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:10px 6px;text-align:center"><b style="display:block;font-size:1rem;'+(c?'color:'+c:'')+'">'+v+'</b><span style="font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+l+'</span></div>';
 setH(document.getElementById('missed-g'),cell('trades',n)+cell('net',n?mn(net):'\u2014',n?(net>=0?'var(--up-soft)':'var(--down-soft)'):'')+cell(en?'now':'maintenant',robot));
 el.style.display='block';
 const P=d.plan||{};
 if((P.manual||P.family)&&!window._missedSigT){window._missedSigT=1;fetch(B+'signals?t='+Date.now(),{cache:'no-store'}).then(r=>r.json()).then(j=>{const c=(j.items||[]).filter(x=>x.ok&&x.t*1000>lv).length;const sg=document.getElementById('missed-sig');if(sg)sg.textContent=c?(en?c+' signal'+(c>1?'s':'')+' sent since':c+' signal'+(c>1?'s':'')+' envoy\u00e9'+(c>1?'s':'')+' depuis'):'';}).catch(()=>{});}
}
async function loadCompare(d){const sec=document.getElementById('cmp-sec'),el=document.getElementById('cmpcard');if(!sec||!el)return;
 const P=d.plan||{};
 if(!P.manual||P.family||d.public){sec.style.display='none';el.style.display='none';return;}
 if(window._cmpT&&Date.now()-window._cmpT<60000)return;window._cmpT=Date.now();
 let j=null;try{const r=await fetch(B+'compare?t='+Date.now(),{cache:'no-store'});if(r.ok)j=await r.json();}catch(e){}
 if(!j||j.err){sec.style.display='none';el.style.display='none';return;}
 const en=LANG()==='en',me=j.me||[],rb=j.robot||[];
 const mm=new Map(me.map(x=>[x.d,+x.p||0])),rm=new Map(rb.map(x=>[x.d,+x.p||0]));
 const days=[...new Set([...mm.keys(),...rm.keys()])].sort();
 const tme=me.reduce((a,x)=>a+(+x.p||0),0),trb=days.reduce((a,dd)=>a+(mm.has(dd)?(rm.get(dd)||0):0),0);
 const mn=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 const big=(l,v,c)=>'<div style="flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:14px;padding:12px 8px;text-align:center"><b style="display:block;font-size:1.25rem;color:'+c+'">'+v+'</b><span style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">'+l+'</span></div>';
 const mx=Math.max(1,...days.map(dd=>Math.max(Math.abs(mm.get(dd)||0),Math.abs(rm.get(dd)||0))));
 const bar=(v)=>'<span style="flex:1;height:7px;border-radius:99px;background:var(--surface3);position:relative;overflow:hidden"><i style="position:absolute;left:0;top:0;bottom:0;width:'+Math.round(Math.abs(v)/mx*100)+'%;background:'+(v>=0?'var(--up)':'var(--down)')+';border-radius:99px;opacity:.85"></i></span>';
 const rows=days.slice(-14).map(dd=>{const a=mm.has(dd)?mm.get(dd):null,b=rm.get(dd)||0;return '<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--border);font-size:.78rem"><span style="width:44px;color:var(--muted)">'+dd.slice(8,10)+'/'+dd.slice(5,7)+'</span>'+bar(a||0)+'<b style="width:58px;text-align:right;color:'+(a===null?'var(--muted)':(a>=0?'var(--up-soft)':'var(--down-soft)'))+'">'+(a===null?'\u2014':mn(a))+'</b>'+bar(b)+'<b style="width:58px;text-align:right;color:'+(b>=0?'var(--up-soft)':'var(--down-soft)')+'">'+mn(b)+'</b></div>';}).join('');
 setH(el,'<div style="display:flex;gap:8px">'+big(en?'You':'Vous',mn(tme),tme>=0?'var(--up-soft)':'var(--down-soft)')+big(j.robot_name||(en?'the Owl\u2019s robot':'Le robot du Owl'),mn(trb),trb>=0?'var(--up-soft)':'var(--down-soft)')+'</div>'+
  '<div style="font-size:.74rem;color:var(--muted);margin:8px 0 2px">'+(en?'Same days, this month. Left: you. Right: the robot on its public account.':'M\u00eames jours, ce mois. \u00c0 gauche vous, \u00e0 droite le robot sur son compte public.')+'</div>'+rows+
  (days.length?'':'<div class="empty"><p>'+(en?'No day yet this month.':'Aucun jour ce mois pour l\u2019instant.')+'</p></div>'));
 sec.style.display='block';el.style.display='block';
}
// ---- batch 29: "Quoi de neuf" - one card per update, dismissed once ----
const NEWS_V='2026-10-04a';
const NEWS=[
 {fr:'<b>Signal remplace Manuel</b> \u2014 les signaux du robot sur votre t\u00e9l\u00e9phone et tout ce que montre la d\u00e9mo, sans compte MT5. Vous tradez o\u00f9 vous voulez.',en:'<b>Signal replaces Manual</b> \u2014 the robot\u2019s signals on your phone and everything the demo shows, no MT5 account. You trade wherever you like.'},
 {fr:'<b>Un compte s\u2019ouvre avec un code</b> \u2014 Le Owl vous l\u2019envoie sur Telegram ; la page owltrader.duckdns.org/activate fait le reste. Le m\u00eame code renouvelle, dans R\u00e9glages \u203a Abonnement.',en:'<b>An account opens with a code</b> \u2014 the Owl sends it on Telegram; the page owltrader.duckdns.org/activate does the rest. The same code renews, in Settings \u203a Subscription.'},
 {fr:'<b>L\u2019application Android</b> \u2014 un vrai fichier APK, sur la page d\u2019accueil et dans R\u00e9glages \u203a Application. Les mises \u00e0 jour se posent par-dessus, sans rien d\u00e9sinstaller.',en:'<b>The Android app</b> \u2014 a real APK, on the front page and in Settings \u203a Application. Updates install over the old one, nothing to uninstall.'},
 {fr:'<b>Sortir et le num\u00e9ro de compte</b> \u2014 \u00ab Sortir \u00bb est dans R\u00e9glages et verrouille l\u2019\u00e9cran sans quitter la page ; le num\u00e9ro de compte ne montre plus que ses trois derniers chiffres.',en:'<b>Exit and the account number</b> \u2014 \u201cSortir\u201d lives in Settings and locks the screen without leaving the page; the account number shows only its last three digits.'},
 {fr:'<b>Le chercheur veille toute la journ\u00e9e</b> \u2014 le chercheur se r\u00e9veille quand un trade se ferme ou toutes les quatre heures ; sa derni\u00e8re observation est sur la carte \u00ab Cette nuit \u00bb du Labo.',en:'<b>The researcher watches all day</b> \u2014 the researcher wakes when a trade closes or every four hours; his last observation sits on the Labo\u2019s \u201cLast night\u201d card.',need:'strategy'},
 {fr:'<b>Le critique</b> \u2014 une seconde intelligence artificielle essaie de casser chaque id\u00e9e qui a bien marqu\u00e9, avant qu\u2019elle n\u2019ait droit \u00e0 un jumeau. Son avis est sur la carte de l\u2019id\u00e9e et dans le rapport de la nuit.',en:'<b>The critic</b> \u2014 a second AI tries to break every idea that scored well before it earns a twin. Its verdict sits on the idea\u2019s card and in the night report.',need:'strategy'},
 {fr:'<b>Le constructeur</b> \u2014 une troisi\u00e8me intelligence artificielle construit ce que le chercheur demande (un r\u00e9glage pour le test, un fait, un outil), derri\u00e8re des contr\u00f4les. Rien ne change dans le robot tant qu\u2019une id\u00e9e n\u2019a pas gagn\u00e9 son duel.',en:'<b>The builder</b> \u2014 a third AI builds what the researcher asks for (a dial for the test, a fact, a tool), behind the gates. Nothing changes in the robot until an idea wins its duel.',need:'strategy'},
 {fr:'<b>Le robot du labo</b> \u2014 un compte d\u00e9mo o\u00f9 une id\u00e9e qui gagne son duel entre toute seule, puis est surveill\u00e9e contre le vrai robot. Sa carte est sous le tableau du Labo. Les vrais comptes attendent toujours l\u2019accord du Owl.',en:'<b>The lab\u2019s robot</b> \u2014 a demo account where a duel winner goes in by itself, then is watched against the real robot. Its card sits under the Labo board. Real accounts still need the Owl\u2019s tap.',need:'strategy'},
 {fr:'<b>Le Labo, une seule page</b> \u2014 quatre colonnes : Id\u00e9es, Test\u00e9es, Pour de faux, Dans le robot. Les nouvelles id\u00e9es de la nuit en premier ; les pistes dans leur propre panneau.',en:'<b>The Labo, one page</b> \u2014 four columns: Ideas, Tested, For pretend, In the robot. The night\u2019s new ideas first; the clues in their own panel.',need:'strategy'},
 {fr:'<b>Le rapport de la nuit</b> \u2014 tout dans l\u2019ordre : les r\u00e9sultats, la journ\u00e9e, le critique, le constructeur, \u00e0 retenir, ce qu\u2019il croit, les nouvelles id\u00e9es, \u00e0 construire.',en:'<b>The night report</b> \u2014 everything in order: results, the day, the critic, the builder, to remember, beliefs, new ideas, to build.',need:'strategy'},
 {fr:'<b>Des mots simples</b> \u2014 plus de lettres A/B/C ni de \u00ab renforts \u00bb : on dit \u00ab mieux sur les deux moiti\u00e9s \u00bb, \u00ab un peu mieux \u00bb, \u00ab non \u00bb, et \u00ab trades de rattrapage \u00bb. Aucun nom de membre dans le Labo.',en:'<b>Plain words</b> \u2014 no more A/B/C letters or \u201cboosts\u201d: we say \u201cbetter on both halves\u201d, \u201ca little better\u201d, \u201cno\u201d, and \u201ccatch-up trades\u201d. No member\u2019s name in the Labo.',need:'strategy'},
 {fr:'<b>Les pistes</b> \u2014 des piles de vrais trades, chacune une question pos\u00e9e au robot. Le chercheur peut en ajouter quand les donn\u00e9es lui en donnent une raison ; une piste pr\u00eate est envoy\u00e9e au chercheur toute seule.',en:'<b>The clues</b> \u2014 piles of real trades, each a question put to the robot. The researcher can add one when the data gives it a reason; a ready clue is sent to the researcher by itself.',need:'strategy'},
 {fr:'<b>Un nouveau look</b> \u2014 Accueil, Robot, Historique, Le Nid et March\u00e9 revus : moins de cadres, des chiffres plus lisibles, un seul accent par bloc.',en:'<b>A new look</b> \u2014 Home, Robot, History, the Nest and Market reworked: fewer boxes, numbers easier to read, one accent per block.'},
 {fr:'<b>Signal jouable</b> \u2014 la notification ne tient plus compte de la petite structure quand votre robot ne la trade pas.',en:'<b>Playable signal</b> \u2014 the push no longer counts the small structure when your robot does not trade it.',need:'manual'},
 {fr:'<b>Le test, mesur\u00e9 contre la r\u00e9alit\u00e9</b> \u2014 l\u2019\u00e9cart entre ce que le test pr\u00e9voit et ce que vos vrais trades font est mesur\u00e9 chaque nuit, trade par trade, et affich\u00e9 dans La preuve.',en:'<b>The test, measured against reality</b> \u2014 the gap between what the test expects and what your real trades make is measured every night, trade by trade, and shown in The proof.'},
 {fr:'<b>M\u00e9t\u00e9o sur le graphique</b> \u2014 touchez la puce m\u00e9t\u00e9o en haut, le d\u00e9tail glisse sans quitter le graphique.',en:'<b>Weather on the chart</b> \u2014 tap the weather chip at the top, the detail slides up without leaving the chart.'},
 {fr:'<b>Le robot en un tap</b> \u2014 la puce robot ouvre son \u00e9tat : trades en cours, rattrapage, et le changement de mode.',en:'<b>The robot in one tap</b> \u2014 the robot chip opens its state: open trades, catch-up, and the mode switch.',need:'switch'},
 {fr:'<b>Signal sur le graphique</b> \u2014 une puce ACHAT / VENTE clignote tant qu\u2019un signal est valable ; tout se fait depuis l\u00e0.',en:'<b>Signal on the chart</b> \u2014 a BUY / SELL chip pulses while a signal is live; everything happens from there.',need:'manual'},
 {fr:'<b>Votre lot</b> \u2014 entrez votre solde une fois, le signal s\u2019adapte \u00e0 votre compte.',en:'<b>Your lot</b> \u2014 enter your balance once, the signal scales to your account.',need:'manual'},
 {fr:'<b>J\u2019ai pris / Pas pris</b> \u2014 et l\u2019historique des signaux dans Historique.',en:'<b>Taken / Not taken</b> \u2014 and the signal history in History.',need:'manual'},
 {fr:'<b>Mes paiements</b> \u2014 vos re\u00e7us et vos dates de fin, dans R\u00e9glages.',en:'<b>My payments</b> \u2014 your receipts and end dates, in Settings.'},
 {fr:'<b>Mode clair</b> \u2014 le graphique suit maintenant le th\u00e8me de l\u2019app.',en:'<b>Light mode</b> \u2014 the chart now follows the app theme.'},
 {fr:'<b>Le graphique en anglais</b> \u2014 il suit la langue de l\u2019app.',en:'<b>The chart in English</b> \u2014 it follows the app language.'},
 {fr:'<b>Touchez un trade</b> sur le graphique \u2014 ses chiffres et son histoire.',en:'<b>Tap a trade</b> on the chart \u2014 its figures and its story.'},
 {fr:'<b>La semaine</b> \u2014 une puce sur le graphique, le d\u00e9tail jour par jour.',en:'<b>The week</b> \u2014 a chip on the chart, day by day.'},
 {fr:'<b>Son et vibration</b> \u00e0 chaque signal \u2014 \u00e0 activer dans Notifications.',en:'<b>Sound and vibration</b> on every signal \u2014 enable it in Notifications.',need:'manual'},
 {fr:'<b>Une journ\u00e9e pass\u00e9e</b> sur le graphique \u2014 le calendrier en bas, choisissez un jour.',en:'<b>A past day</b> on the chart \u2014 the calendar at the bottom, pick a day.'},
 {fr:'<b>La r\u00e8gle</b> sur le graphique \u2014 deux touches, la distance en points et en dollars.',en:'<b>The ruler</b> on the chart \u2014 two taps, the distance in points and dollars.'},
 {fr:'<b>Vous et le robot</b> \u2014 votre mois face au sien, dans Historique.',en:'<b>You and the robot</b> \u2014 your month against its, in History.',need:'manual'},
 {fr:'<b>Raccourcis</b> \u2014 Graphique, Signal, Historique depuis l\u2019ic\u00f4ne de l\u2019app (appui long).',en:'<b>Shortcuts</b> \u2014 Chart, Signal, History from the app icon (long press).'},
 {fr:'<b>Deux espaces</b> dans March\u00e9 \u2014 le march\u00e9 d\u2019un c\u00f4t\u00e9, le robot de l\u2019autre.',en:'<b>Two spaces</b> in Market \u2014 the market on one side, the robot on the other.'},
 {fr:'<b>Les heures du march\u00e9</b> \u2014 calme ou rapide, heure par heure, se remplit avec les jours.',en:'<b>Market hours</b> \u2014 calm or fast, hour by hour, fills in with the days.'},
 {fr:'<b>Le robot explique</b> \u2014 les occasions laiss\u00e9es passer, par raison, et sa prochaine action.',en:'<b>The robot explains</b> \u2014 the opportunities let go, by reason, and its next action.'},
 {fr:'<b>Journal du robot</b> \u2014 ses 20 derniers trades, touchez-en un pour le voir sur le graphique.',en:'<b>Robot journal</b> \u2014 its last 20 trades, tap one to see it on the chart.'},
 {fr:'<b>Ce que le march\u00e9 nous apprend</b> \u2014 les patterns, leur preuve, et ce que le robot en fait.',en:'<b>What the market teaches us</b> \u2014 the patterns, their evidence, and what the robot does with them.'},
 {fr:'<b>Le labo</b> \u2014 id\u00e9es, replays, observations en cours et d\u00e9cisions, dans March\u00e9.',en:'<b>The lab</b> \u2014 ideas, replays, observations in progress and decisions, in Market.',need:'strategy'}];
// 2026-10-01 (owner): the worst dip reads under the chart that draws it,
// and ONLY on the 7-day range - it is a 7-day figure and would be a lie
// over 30 days or 3 months. Its own function so the range chips can
// refresh it without re-rendering the whole page.
function ddCap(d){
 const dc=document.getElementById('ddcap');
 if(!dc||!d||d.max_dd_7d===undefined)return;
 if(String(window._cvz||'7')!=='7'){dc.style.display='none';return;}
 const dv=Number(d.max_dd_7d).toFixed(0);
 dc.textContent=(LANG()==='en'
  ?'Worst dip over these 7 days: '+(dv==0?'$0':'-$'+dv)
  :'Pire passage sur ces 7 jours : '+(dv==0?'$0':'-$'+dv));
 dc.style.display='block';
}
function newsCard(d){const el=document.getElementById('newscard');if(!el)return;const en=LANG()==='en';
 let seen='';try{seen=localStorage.getItem('owlNewsSeen:'+B)||'';}catch(e){}
 const P=d.plan||{};
 if(seen===NEWS_V){el.style.display='none';return;}
 const items=NEWS.filter(n=>!n.need||(n.need==='manual'&&(P.manual||P.family))||(n.need==='switch'&&!d.pause_locked)||(n.need==='strategy'&&(P.strategy||d.is_master)));
 document.getElementById('news-t').textContent=en?'What\u2019s new':'Quoi de neuf';
 document.getElementById('news-s').textContent=en?'Since your last visit':'Depuis votre derni\u00e8re visite';
 // 2026-10-01 (owner): the list lives in a sheet; the card says how
 // many there are. A changelog is a reference, and the home screen
 // answers "how am I doing".
 const _nh=items.map(n=>'<div style="display:flex;gap:8px;margin-top:10px"><span style="color:var(--accent-soft);flex:none">\u2022</span><span>'+(en?n.en:n.fr)+'</span></div>').join('');
 setH(document.getElementById('news-list'),_nh);
 // 2026-10-01 (owner): "since your last visit" is wrong for somebody
 // who has never visited - and the absence of the key says exactly that.
 document.getElementById('news-s').textContent=
  (seen===''
   ?(en?items.length+' thing'+(items.length>1?'s':'')+' this app can do'
       :items.length+' choses que l\u2019app sait faire')
   :(en?items.length+' new thing'+(items.length>1?'s':'')+' since your last visit'
       :items.length+' nouveaut\u00e9'+(items.length>1?'s':'')+' depuis votre derni\u00e8re visite'));
 const ob=document.getElementById('news-open');
 ob.textContent=en?'See them':'Les voir';
 ob.onclick=()=>{sheet('<div class="lbl">'+(en?'What\u2019s new':'Quoi de neuf')+
  '</div><div style="font-size:.9rem;color:var(--text2);line-height:1.55">'+
  _nh+'</div>');};
 const b=document.getElementById('news-b');b.textContent=en?'Got it':'Compris';
 b.onclick=()=>{try{localStorage.setItem('owlNewsSeen:'+B,NEWS_V);}catch(e){}el.style.display='none';};
 el.style.display='block';}
// ---- batch 28 ----
function noPushBanner(d){const el=document.getElementById('nopushcard');if(!el)return;const en=LANG()==='en';
 const show=!d.public&&MAN()&&!OBS()&&!d.push_on&&!window._pushLocal;
 if(!show){el.style.display='none';return;}
 const nb=document.getElementById('notifbtn');const can=!!(nb&&nb.style.display!=='none');
 document.getElementById('nopush-t').textContent=en?'Your signals will not reach you':'Vos signaux ne vous arriveront pas';
 document.getElementById('nopush-s').textContent=can?(en?'Notifications are off on this phone. A signal is pushed the second it appears.':'Les notifications sont d\u00e9sactiv\u00e9es sur ce t\u00e9l\u00e9phone. Un signal est envoy\u00e9 \u00e0 la seconde o\u00f9 il appara\u00eet.')
  :(en?'Install the app first (Settings \u203a Install), then enable notifications.':'Installez d\u2019abord l\u2019app (R\u00e9glages \u203a Installer), puis activez les notifications.');
 const b=document.getElementById('nopush-b');b.textContent=can?(en?'Enable':'Activer'):(en?'How':'Comment');
 b.onclick=()=>{if(can){nb.click();}else{tab('set',document.querySelectorAll('.tb')[3]);}};
 el.style.display='block';}
async function myBalSet(){const en=LANG()==='en';let my='';try{my=localStorage.getItem('owlMyBal:'+B)||'';}catch(e){}
 const v=await sheet('<h3>'+(en?'Your balance':'Votre solde')+'</h3><p>'+(en?'The balance of the account you trade the signals on. Kept on this phone only. The lot is scaled in proportion; the stop and target do not change.':'Le solde du compte sur lequel vous tradez les signaux. Gard\u00e9 sur ce t\u00e9l\u00e9phone seulement. Le lot est mis \u00e0 l\u2019\u00e9chelle en proportion ; le stop et la cible ne changent pas.')+'</p>'+
  '<input id="shbal" inputmode="decimal" value="'+String(my).replace(/"/g,'')+'" placeholder="500" style="width:100%;box-sizing:border-box;border:1px solid var(--border2);background:var(--surface2);color:var(--text);border-radius:12px;padding:12px 14px;font-size:1rem;margin-bottom:8px">'+
  '<button class="shbtn shmain" onclick="_shDone({b:document.getElementById(&#39;shbal&#39;).value})">'+(en?'Save':'Enregistrer')+'</button><button class="shbtn shghost" onclick="_shDone(null)">'+(en?'Cancel':'Annuler')+'</button>');
 if(!v)return;const nn=parseFloat(String(v.b||'').replace(',','.'));try{if(nn>0)localStorage.setItem('owlMyBal:'+B,String(nn));else localStorage.removeItem('owlMyBal:'+B);}catch(e){}
 if(window._sigMs)renderSignal(window._sigMs);}
function myLotLine(sg,en){const lt=document.getElementById('sig-mylot');if(!lt)return;
 if(!sg.ok||!sg.bal||!sg.risk){lt.style.display='none';return;}
 let my=0;try{my=parseFloat(localStorage.getItem('owlMyBal:'+B)||'0');}catch(e){}
 lt.style.display='block';
 if(my>0){const k=my/sg.bal;const l=Math.max(0.01,Math.round(sg.lot*k*100)/100);
  setH(lt,'<span>'+(en?'Your lot for $':'Votre lot pour $')+my.toFixed(0)+' : <b style="color:var(--text)">'+l.toFixed(2)+'</b> \u00b7 '+(en?'risk ~$':'risque ~$')+(sg.risk*k).toFixed(2)+'</span> \u00b7 <a href="#" onclick="event.preventDefault();myBalSet()" style="color:var(--muted);text-decoration:none">'+(en?'change':'modifier')+'</a>');}
 else setH(lt,'<span>'+(en?'Lot sized for a $':'Lot calcul\u00e9 pour un compte de $')+sg.bal.toFixed(0)+(en?' account \u00b7 risk ~$':' \u00b7 risque ~$')+sg.risk.toFixed(2)+'.</span> <a href="#" onclick="event.preventDefault();myBalSet()" style="color:var(--accent-soft);text-decoration:none">'+(en?'Another broker? Enter your balance':'Autre broker ? Entrez votre solde')+'</a>');}
// ---- batch 26 ----
function renewBanner(d){
 const el=document.getElementById('renewcard'),P=d.plan;if(!el||!P||d.public){if(el)el.style.display='none';return;}
 const en=LANG()==='en',now=Date.now()/1000;let best=null;
 [['family',P.family_until,en?'Automatic':'Automatique'],['strategy',P.strategy_until,en?'Strategy':'Strat\u00e9gie'],['manual',P.manual_until,en?'Manual':'Manuel']].forEach(([k,u,l])=>{
  if(u&&u>now&&(u-now)<=5*86400&&(!best||u<best.u))best={k,u,l};});
 if(!best||(best.k==='manual'&&P.strategy_until>now)){el.style.display='none';return;}
 const days=Math.max(0,Math.ceil((best.u-now)/86400));
 document.getElementById('renew-t').textContent=best.l+(en?' ends in ':' expire dans ')+days+(en?' day'+(days>1?'s':''):' jour'+(days>1?'s':''));
 const b=document.getElementById('renew-b');
 if(best.k==='family'){document.getElementById('renew-s').textContent=en?'Settle with the Owl, then enter the code he sends you.':'R\u00e9glez le Owl, puis entrez le code qu\u2019il vous envoie.';
  b.textContent=en?'Enter the code':'Entrer le code';b.onclick=()=>{window._showAct=true;const c=document.getElementById('actcard');if(c){c.style.display='block';c.scrollIntoView({block:'center'});const i=document.getElementById('actcode');if(i)i.focus();}};}
 else{document.getElementById('renew-s').textContent=en?'Renewing adds 30 days from the current end \u2014 no interruption.':'Renouveler ajoute 30 jours \u00e0 la fin actuelle \u2014 sans coupure.';
  b.textContent=en?'Renew':'Renouveler';b.onclick=()=>buyPkg(best.k);}
 el.style.display='block';
}
async function loadSignals(){
 const sec=document.getElementById('sig-sec'),el=document.getElementById('siglist');if(!sec||!el)return;
 const d=window._d||{},P=d.plan||{};
 const scEl=document.getElementById('sigscore');
 if(!(P.manual||P.family)||d.public){sec.style.display='none';el.style.display='none';if(scEl)scEl.style.display='none';return;}
 if(window._sgT&&Date.now()-window._sgT<30000)return;window._sgT=Date.now();
 let it=[],sc=null;try{const r=await fetch(B+'signals?t='+Date.now(),{cache:'no-store'});if(r.ok){const j=await r.json();it=j.items||[];sc=j.score||null;}}catch(e){}
 const en=LANG()==='en';
 // 2026-09-28: the month's scorecard (same numbers the owner sees in Le Nid)
 if(scEl){if(sc&&sc.sent){const cell=(l,v,c)=>'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:10px 4px;text-align:center"><b style="display:block;font-size:1.05rem;'+(c?'color:'+c:'')+'">'+v+'</b><span style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+l+'</span></div>';
   const dec=sc.wins+sc.losses,mn=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
   setH(scEl,'<div class="lbl">'+(en?'This month':'Ce mois')+'</div><div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px">'+cell(en?'signals':'signaux',sc.sent)+cell(en?'taken':'pris',sc.taken)+cell(en?'wins':'gagn\u00e9s',dec?Math.round(100*sc.wins/dec)+'\u202f%':'\u2014')+cell('net',mn(sc.net),sc.net>=0?'var(--up-soft)':'var(--down-soft)')+'</div><div style="font-size:.74rem;color:var(--muted);margin-top:8px;line-height:1.45">'+(en?'Net = the results recorded on taken signals, by your desk or by you.':'Net = les r\u00e9sultats enregistr\u00e9s sur les signaux pris, par votre poste ou par vous.')+'</div>');scEl.style.display='block';}
  else scEl.style.display='none';}
 if(!it.length){sec.style.display='block';el.style.display='block';el.innerHTML='<div class="empty"><p>'+(en?'No signal yet. They will appear here as they come.':'Aucun signal pour l\u2019instant. Ils appara\u00eetront ici au fil de l\u2019eau.')+'</p></div>';return;}
 const hm=t=>{const x=new Date(t*1000),n0=new Date();const same=x.toDateString()===n0.toDateString();return (same?'':String(x.getDate()).padStart(2,'0')+'/'+String(x.getMonth()+1).padStart(2,'0')+' ')+String(x.getHours()).padStart(2,'0')+':'+String(x.getMinutes()).padStart(2,'0');};
 const money=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 el.innerHTML=it.slice(0,40).map(x=>{const buy=x.dir===1;
  let st,c;
  if(!x.ok){st=(en?'set aside':'\u00e9cart\u00e9')+' \u00b7 '+(x.why||'');c='var(--muted)';}
  else if(x.taken){st=(en?'taken':'pris')+(typeof x.result==='number'?' \u00b7 '+money(x.result):'');c=typeof x.result==='number'?(x.result>=0?'var(--up-soft)':'var(--down-soft)'):'var(--accent-soft)';}
  else if(x.skipped||x.done){st=en?'not taken':'non pris';c='var(--muted2)';}
  else{st=en?'live':'en cours';c='var(--up-soft)';}
  return '<div class="row"><span class="rowt"><span style="color:'+(buy?'var(--up)':'var(--down)')+';font-weight:800">'+(buy?'\u25b2':'\u25bc')+'</span> '+hm(x.t)+' \u00b7 ~'+Number(x.e).toFixed(0)+' \u00b7 '+Number(x.lot).toFixed(2)+'</span><b style="color:'+c+';font-size:.8rem;text-align:right;max-width:52%">'+st+'</b></div>';}).join('');
 sec.style.display='block';el.style.display='block';
}
function renderRevenue(d){
 const el=document.getElementById('revcard'),R=d.revenue;if(!el)return;if(!d.is_master||!R){el.style.display='none';return;}
 const cell=(l,v)=>'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:10px 6px;text-align:center"><b style="display:block;font-size:1.05rem">'+v+'</b><span style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">'+l+'</span></div>';
 setH(document.getElementById('rev-g'),cell('Auto',R.active.family)+cell('Signal',R.active.manual)+cell('Strat\u00e9gie',R.active.strategy)+cell('MRR','$'+Math.round(R.mrr)));
 // 2026-10-03 (owner): the profit share, this month so far
 (function(){const S=R.share;const g=document.getElementById('rev-g');if(!S||!g)return;
  const us=v=>'$'+Number(v||0).toFixed(2);
  const old=document.getElementById('rev-share');if(old)old.remove();
  g.insertAdjacentHTML('afterend','<div id="rev-share" style="margin-top:10px;font-size:.82rem;line-height:1.5"><b>Part '+Number(S.cfg.pct).toFixed(0)+' %</b> \u00b7 attendu ce mois <b>'+us(S.expected)+'</b>'+(S.open?' \u00b7 relev\u00e9s ouverts <b style="color:var(--warn)">'+us(S.open)+'</b>':'')+(S.overdue.length?' \u00b7 <b style="color:var(--down-soft)">'+S.overdue.length+' en retard</b>':'')+
   '<div style="color:var(--muted2);margin-top:2px">'+S.rows.map(r=>r.name+' '+us(r.now.due)+(r.last&&(r.last.status==='open'||r.last.status==='overdue')?' (relev\u00e9 '+r.last.ym.slice(5)+' : '+us(r.last.due)+(r.last.status==='overdue'?', retard':'')+')':'')).join(' \u00b7 ')+'</div></div>');})();
 setH(document.getElementById('rev-due'),(R.due.length?'<b>\u00c0 renouveler sous 7 j :</b> '+R.due.map(x=>x.name+' ('+x.pkg+', '+x.days+' j)').join(' \u00b7 '):'Aucun renouvellement sous 7 jours.')+(R.family_usd?'':' <span style="color:var(--muted)">\u00b7 prix Automatique non d\u00e9fini (Paiements)</span>'));
 setH(document.getElementById('rev-pay'),R.payments.length?R.payments.map(p=>{const x=new Date(p.t*1000);return '<div class="row" style="padding:6px 0;font-size:.82rem"><span class="rowt">'+String(x.getDate()).padStart(2,'0')+'/'+String(x.getMonth()+1).padStart(2,'0')+' \u00b7 '+(p.order||'').split('|')[0]+' \u00b7 '+p.granted+'</span><b class="pos">+$'+Number(p.amount||0).toFixed(0)+'</b></div>';}).join(''):'<div style="font-size:.78rem;color:var(--muted)">Aucun paiement NOWPayments encore.</div>');
 el.style.display='block';
}
async function nestSharePaid(uid,name,ym,due){
 const pw=await askPwd(ym==='setup'?'Frais d\u2019ouverture de '+name+' pay\u00e9s ?':'Relev\u00e9 '+ym+' de '+name+' pay\u00e9 ?','$'+Number(due).toFixed(2)+' re\u00e7u.'+(ym==='setup'?'':' Le robot reprend si la pause venait du relev\u00e9.'),'Marquer pay\u00e9');if(!pw)return;
 const r=await fetch(AB()+'share_paid',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'uid='+encodeURIComponent(uid)+'&ym='+encodeURIComponent(ym)+'&pwd='+encodeURIComponent(pw)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){await info('&#10060; <h3>'+(j&&j.err==='bad password'?'Mot de passe incorrect.':_escS((j&&j.err)||'\u00c7a n\u2019a pas march\u00e9.'))+'</h3>');return;}
 toast('Relev\u00e9 marqu\u00e9 pay\u00e9',1800);}
// 2026-10-03 (owner): a code for ANYONE - pick the package and the days.
// New member: they enter it on the /activate page with their MT5 account.
// Existing member: Reglages > Abonnement > "J'ai un code".
async function nestActivate(uid,name,lab){
 const pick=await sheet('<h3>Activer '+_escS(name)+'</h3><p style="color:var(--text2)">'+lab+' \u2014 sans code : le compte s\u2019active tout de suite. '+(lab==='Automatique'?'Le robot d\u00e9marre sur son compte dans quelques minutes.':'')+'</p>'+
  '<div class="lbl">Dur\u00e9e</div><div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">'+[30,90,365].map(d=>'<label style="display:block;text-align:center;border:1px solid var(--border);border-radius:12px;padding:10px 4px;cursor:pointer;background:var(--surface2)"><input type="radio" name="na-days" value="'+d+'" '+(d===30?'checked':'')+' style="margin:0 0 6px"><br><b>'+d+' j</b></label>').join('')+'</div>'+
  '<button class="shbtn shmain" style="margin-top:14px" onclick="_shDone({d:(document.querySelector(&#39;input[name=na-days]:checked&#39;)||{}).value})">Activer</button><button class="shbtn shghost" onclick="_shDone(null)">Annuler</button>');
 if(!pick)return;
 const pw=await askPwd('Activer '+name+' ?',(pick.d||30)+' jours de '+lab+'.','Activer');if(!pw)return;
 const r=await fetch(AB()+'nest_activate',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'uid='+encodeURIComponent(uid)+'&days='+encodeURIComponent(pick.d||30)+'&pwd='+encodeURIComponent(pw)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){await info('&#10060; <h3>'+(j&&j.err==='bad password'?'Mot de passe incorrect.':_escS((j&&(j.msg||j.err))||'\u00c7a n\u2019a pas march\u00e9.'))+'</h3>');return;}
 toast(name+' activ\u00e9',2200);load();}
// 2026-10-04 (owner): a member who forgot the password - a temporary one,
// sent on Telegram; they can keep it or change it later
async function nestResetPwd(uid,name){
 const pw=await askPwd('Nouveau mot de passe pour '+name+' ?','Un mot de passe provisoire est cr\u00e9\u00e9 ; envoyez-le sur Telegram.','Cr\u00e9er');if(!pw)return;
 const r=await fetch(AB()+'nest_reset_pwd',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'uid='+encodeURIComponent(uid)+'&pwd='+encodeURIComponent(pw)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){await info('&#10060; <h3>'+(j&&j.err==='bad password'?'Mot de passe incorrect.':_escS((j&&j.err)||'\u00c7a n\u2019a pas march\u00e9.'))+'</h3>');return;}
 const msg='Bonjour '+name+', votre nouveau mot de passe OwlNest : '+j.temp+' \u2014 identifiant : '+uid+'. Connectez-vous sur owltrader.duckdns.org.';
 sheet('<h3>Mot de passe de '+_escS(name)+'</h3><div style="font-size:1.6rem;font-weight:800;letter-spacing:.2em;text-align:center;background:var(--bg);border-radius:14px;padding:16px 6px;margin:6px 0 10px;color:var(--up-soft)">'+_escS(j.temp)+'</div>'+
  '<p style="font-size:.86rem;color:var(--muted2)">'+_escS(msg)+'</p>'+
  '<button class="shbtn shmain" onclick="(navigator.clipboard?navigator.clipboard.writeText('+JSON.stringify(msg).replace(/"/g,'&quot;')+'):Promise.reject()).then(()=>toast(&#39;Message copi\u00e9&#39;,2000),()=>toast(&#39;Copie impossible ici&#39;,2000))">Copier le message</button>'+
  '<button class="shbtn shghost" onclick="_shDone(1)">Fermer</button>');}
async function nestPendingDel(uid,name){
 const pw=await askPwd('Supprimer la demande de '+name+' ?','Elle dispara\u00eet du Nid ; rien n\u2019a \u00e9t\u00e9 activ\u00e9.','Supprimer');if(!pw)return;
 const r=await fetch(AB()+'nest_pending_del',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'uid='+encodeURIComponent(uid)+'&pwd='+encodeURIComponent(pw)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){await info('&#10060; <h3>'+(j&&j.err==='bad password'?'Mot de passe incorrect.':'\u00c7a n\u2019a pas march\u00e9.')+'</h3>');return;}
 toast('Demande supprim\u00e9e',2000);load();}
async function nestCodeAny(){
 const pick=await sheet('<h3>G\u00e9n\u00e9rer un code</h3><p style="color:var(--text2)">Le code ouvre un compte (page <b>owltrader.duckdns.org/activate</b>) ou renouvelle un membre (R\u00e9glages \u203a Abonnement). Usage unique, valable 7 jours.</p>'+
  '<div class="lbl">Pour qui (facultatif)</div><input id="cd-for" placeholder="Pr\u00e9nom" style="width:100%;box-sizing:border-box;background:var(--surface2);border:1px solid var(--border);border-radius:12px;color:var(--text);padding:12px;font-size:1rem">'+
  '<div class="lbl" style="margin-top:12px">Paquet</div><div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">'+
  [['family','Automatique','famille'],['manual','Signal','$29'],['strategy','Strat\u00e9gie','$49']].map(x=>'<label style="display:block;text-align:center;border:1px solid var(--border);border-radius:12px;padding:10px 4px;cursor:pointer;background:var(--surface2)"><input type="radio" name="cd-pkg" value="'+x[0]+'" '+(x[0]==='family'?'checked':'')+' style="margin:0 0 6px"><br><b>'+x[1]+'</b><div style="font-size:.7rem;color:var(--muted)">'+x[2]+'</div></label>').join('')+'</div>'+
  '<div class="lbl" style="margin-top:12px">Dur\u00e9e</div><div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">'+
  [30,90,365].map(d=>'<label style="display:block;text-align:center;border:1px solid var(--border);border-radius:12px;padding:10px 4px;cursor:pointer;background:var(--surface2)"><input type="radio" name="cd-days" value="'+d+'" '+(d===30?'checked':'')+' style="margin:0 0 6px"><br><b>'+d+' j</b></label>').join('')+'</div>'+
  '<button class="shbtn shmain" style="margin-top:16px" onclick="_shDone({f:document.getElementById(&#39;cd-for&#39;).value,p:(document.querySelector(&#39;input[name=cd-pkg]:checked&#39;)||{}).value,d:(document.querySelector(&#39;input[name=cd-days]:checked&#39;)||{}).value})">\U0001f511 G\u00e9n\u00e9rer</button>'+
  '<button class="shbtn shghost" onclick="_shDone(null)">Annuler</button>');
 if(!pick||!pick.p)return;
 nestCodeFor(pick.f||'',pick.p,pick.d||30);
}
async function nestCodeFor(name,pkg,days){
 pkg=pkg||'family';days=days||30;
 const LAB={family:'Automatique',manual:'Signal',strategy:'Strat\u00e9gie'}[pkg]||pkg;
 const pw=await askPwd('Code '+LAB+(name?' pour '+name:''),days+' jours, usage unique, valable 7 jours.','🔑 G\u00e9n\u00e9rer');if(!pw)return;
 const r=await fetch(AB()+'actcode',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'pwd='+encodeURIComponent(pw)+'&pkg='+encodeURIComponent(pkg)+'&days='+encodeURIComponent(days)+'&for='+encodeURIComponent(name||'')}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){await info('&#10060; <h3>'+(j&&j.err==='bad password'?'Mot de passe incorrect.':'Impossible pour l\u2019instant.')+'</h3>');return;}
 const msg='Bonjour'+(name?' '+name:'')+', votre code OwlNest '+LAB+' : '+j.code+' ('+days+' jours, valable 7 jours). Nouveau compte : https://owltrader.duckdns.org/activate \u2014 D\u00e9j\u00e0 membre : R\u00e9glages \u203a Abonnement \u203a \u00ab J\u2019ai un code \u00bb.';
 sheet('<h3>Code pour '+name+'</h3><div style="font-size:2rem;font-weight:800;letter-spacing:.3em;text-align:center;background:var(--bg);border-radius:14px;padding:18px 6px;margin:6px 0 10px;color:var(--up-soft)">'+j.code+'</div>'+
  '<p style="font-size:.86rem;color:var(--muted2)">'+msg+'</p>'+
  '<button class="shbtn shmain" onclick="(navigator.clipboard?navigator.clipboard.writeText('+JSON.stringify(msg).replace(/"/g,'&quot;')+'):Promise.reject()).then(()=>toast(&#39;Message copi\u00e9&#39;,2000),()=>toast(&#39;Copie impossible&#39;,2000))">Copier le message</button>'+
  '<button class="shbtn shghost" onclick="_shDone(1)">Fermer</button>');
}
function observerView(d){
 const obs=OBS();
 const hide=HIDEGAUGES();['mx-chips','mx-nerv','jcard'].forEach(id=>{const el=document.getElementById(id);if(el)el.style.display=hide?'none':'';});
 if(hide)['mhcard','whycard','rjcard','rb-next','lrn-sec','lrn-list','lrn-next','lrn-card'].forEach(id=>{const el=document.getElementById(id);if(el)el.style.display='none';});
 const kc=document.getElementById('kinocard');if(!kc)return;
 if(!obs){kc.style.display='none';return;}
 kc.style.display='block';
 if(window._kinoT&&Date.now()-window._kinoT<60000)return;window._kinoT=Date.now();
 (async()=>{try{const r=await fetch('/demo',{redirect:'follow'});if(!r.ok)return;const base=new URL(r.url).pathname.replace(/\/+$/,'')+'/';
  const k=await (await fetch(base+'api?t='+Date.now(),{cache:'no-store'})).json();if(!k||typeof k.equity!=='number')return;
  const en=LANG()==='en',money=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2),S=k.since_start||{};
  const cell=(l,v,c)=>'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:10px 8px;text-align:center"><b style="display:block;font-size:1.05rem" class="'+c+'">'+v+'</b><span style="font-size:.64rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">'+l+'</span></div>';
  setH(document.getElementById('kino-g'),cell(en?'today':'aujourd\u2019hui',money(k.today||0),sgn(k.today||0))+cell(en?'this week':'cette semaine',money(k.week||0),sgn(k.week||0))+cell(en?'this month':'ce mois',money(k.month||0),sgn(k.month||0)));
  setH(document.getElementById('kino-s'),(S.n?(S.n+' trade'+(S.n>1?'s':'')+' \u00b7 '+Math.round(S.won/Math.max(1,S.n)*100)+'\u202f% '+(en?'won':'gagn\u00e9s')+' \u00b7 '):'')+(en?'live public account':'compte public en direct'));
  const c=k.curve||[],sv=document.getElementById('kino-spark');
  if(c.length>1&&sv){const mn=Math.min(...c,0),mx=Math.max(...c,0),sp=(mx-mn)||1;const X=i=>(i/(c.length-1))*300,Y=v=>40-((v-mn)/sp*34);
   const col=c[c.length-1]>=0?'var(--up)':'var(--down)';let p='';c.forEach((v,i)=>{p+=(i?' L':'M')+X(i).toFixed(1)+','+Y(v).toFixed(1);});
   sv.innerHTML='<path d="'+p+'" fill="none" style="stroke:'+col+'" stroke-width="2"/>';sv.style.display='block';}
  const a=document.getElementById('kino-link');if(a)a.href=base;}catch(e){}})();
}
// 2026-10-04 (owner): no dead end - every offer leads to the Owl (Telegram)
// and to the code page
function kinoBtns(P,en,main){const c=P.contact_url||'';
 return (c?'<a class="shbtn '+(main?'shmain':'shghost')+'" style="display:block;text-align:center;text-decoration:none;margin:10px 0 0" href="'+_escS(c)+'" target="_blank" rel="noopener">\u2709 '+(en?'Write to the Owl on Telegram':'\u00c9crire au Owl sur Telegram')+'</a>':'')+
  '<button class="shbtn shghost" style="display:block;width:100%;margin:8px 0 0" onclick="_shDone(1);openActCard()">\U0001f511 '+(en?'I have a code':'J\u2019ai un code')+'</button>';}
// 2026-10-04 (owner): choose an offer -> this modal. A code activates it on
// THIS account; no code -> the Owl on Telegram; Signal / Strategie -> crypto, instant.
async function codeModal(pkg){const en=LANG()==='en';const P=(window._d&&window._d.plan)||{};
 const L={manual:'Signal',strategy:en?'Strategy':'Strat\u00e9gie',family:en?'Automatic':'Automatique'}[pkg]||(en?'Your package':'Votre formule');
 const contact=P.contact_url||'';
 const inp='<input id="cm-code" maxlength="6" placeholder="ABC123" autocapitalize="characters" style="width:100%;box-sizing:border-box;background:var(--surface2);border:1px solid var(--border);border-radius:12px;color:var(--text);padding:13px;font-size:1.3rem;font-weight:800;letter-spacing:.3em;text-align:center;text-transform:uppercase;margin-top:6px">';
 const v=await sheet('<h3>'+L+' \u00b7 '+(en?'activation code':'code d\u2019activation')+'</h3>'+
  '<p style="color:var(--text2)">'+(pkg==='family'?(en?'The Owl sends the code on Telegram after a word together.':'Le Owl vous envoie le code sur Telegram apr\u00e8s un mot ensemble.'):(en?'Enter your code, or buy now: it activates right away.':'Entrez votre code, ou achetez maintenant : activation imm\u00e9diate.'))+'</p>'+inp+
  '<button class="shbtn shmain" style="margin-top:12px" onclick="_shDone({c:document.getElementById(&#39;cm-code&#39;).value})">'+(en?'Activate':'Activer')+'</button>'+
  (pkg&&pkg!=='family'&&P.pay_ready?'<button class="shbtn shmain" style="margin-top:8px;background:var(--up-soft);color:#08120c" onclick="_shDone({buy:1})">'+(en?'Buy now in crypto \u00b7 instant':'Acheter maintenant en crypto \u00b7 imm\u00e9diat')+'</button><div style="font-size:.76rem;color:var(--muted);line-height:1.45;margin-top:6px">'+(en?'The payment page (NOWPayments) is in English: pick the coin (USDT on Tron is cheapest), \u201cNext step\u201d, send the exact amount. Your package activates by itself once confirmed.':'La page de paiement (NOWPayments) est en anglais : choisissez la monnaie (USDT sur Tron, le moins cher), \u00ab Next step \u00bb, envoyez le montant exact. Votre formule s\u2019active toute seule d\u00e8s confirmation.')+'</div>':'')+
  (contact?'<a class="shbtn shghost" style="display:block;text-align:center;text-decoration:none;margin-top:8px" href="'+_escS(contact)+'" target="_blank" rel="noopener">\u2709 '+(en?'No code? Contact the Owl on Telegram':'Pas de code ? Contacter le Owl sur Telegram')+'</a>':'')+
  '<button class="shbtn shghost" onclick="_shDone(null)">'+(en?'Close':'Fermer')+'</button>');
 if(!v)return;
 if(v.buy){buyPkg(pkg);return;}
 const code=(v.c||'').trim().toUpperCase();if(code.length<6){toast(en?'Enter the full code.':'Entrez le code complet.',2200);return;}
 const send=async(extra)=>{const r=await fetch(B+'activate',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'code='+encodeURIComponent(code)+(extra||'')}).catch(()=>null);try{return await r.json();}catch(e){return null;}};
 let j=await send('');
 if(j&&!j.ok&&j.need==='mt5'){
  const f=(id,ph,t)=>'<input id="'+id+'" type="'+(t||'text')+'" placeholder="'+ph+'" style="width:100%;box-sizing:border-box;background:var(--surface2);border:1px solid var(--border);border-radius:12px;color:var(--text);padding:12px;font-size:1rem;margin-top:8px">';
  const m=await sheet('<h3>'+(en?'Your MT5 account':'Votre compte MT5')+'</h3><p style="color:var(--text2)">'+(en?'This code puts the robot on your own account. Tell it which one - once.':'Ce code met le robot sur votre propre compte. Dites-lui lequel \u2014 une seule fois.')+'</p>'+
   f('am-l',en?'MT5 account number':'Num\u00e9ro de compte MT5')+f('am-s','Exness-MT5Real30')+f('am-p',en?'account password (main)':'mot de passe du compte (principal)','password')+
   '<button class="shbtn shmain" style="margin-top:14px" onclick="_shDone({l:document.getElementById(&#39;am-l&#39;).value,s:document.getElementById(&#39;am-s&#39;).value,p:document.getElementById(&#39;am-p&#39;).value})">'+(en?'Put the robot on it':'Mettre le robot dessus')+'</button><button class="shbtn shghost" onclick="_shDone(null)">'+(en?'Cancel':'Annuler')+'</button>');
  if(!m||!m.l||!m.s||!m.p)return;
  j=await send('&mt5_login='+encodeURIComponent(m.l)+'&mt5_server='+encodeURIComponent(m.s)+'&mt5_password='+encodeURIComponent(m.p));}
 if(!j||!j.ok){await info('&#10060; <h3>'+(j&&j.err==='bad code'?(en?'Unknown or already used code.':'Code inconnu ou d\u00e9j\u00e0 utilis\u00e9.'):(en?'It did not work.':'\u00c7a n\u2019a pas march\u00e9.'))+'</h3>');return;}
 try{confetti();}catch(e){}toast(en?'Activated':'Activ\u00e9',2000);setTimeout(load,1200);}
function openActCard(){codeModal(null);}
function offersSheet(){
 const P=(window._d||{}).plan||{},en=LANG()==='en',pk=P.packages||{manual:{usd:29},strategy:{usd:49}};
 const T2=(fr,e)=>en?e:fr;
 const tier=(name,price,tag,gets,nots,cta,accent)=>'<div style="background:var(--surface2);border:1px solid '+(accent?accent:'var(--border)')+';border-radius:16px;padding:14px;margin-bottom:10px">'+
  '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px"><b style="font-size:1.05rem">'+name+'</b><span style="font-size:.9rem;font-weight:700;color:'+(accent||'var(--text2)')+'">'+price+'</span></div>'+
  (tag?'<div style="font-size:.74rem;color:var(--muted2);margin-top:2px">'+tag+'</div>':'')+
  '<div style="font-size:.86rem;line-height:1.55;margin-top:8px;color:var(--text)">'+gets.map(x=>'<div style="display:flex;gap:8px"><span style="color:var(--up)">\u2713</span><span>'+x+'</span></div>').join('')+
  nots.map(x=>'<div style="display:flex;gap:8px;color:var(--muted)"><span>\u2013</span><span>'+x+'</span></div>').join('')+'</div>'+
  (cta||'')+'</div>';
 const btn=(k,l,dis)=>'<button '+(dis?'disabled ':'')+'onclick="_shDone(1);buyPkg(&#39;'+k+'&#39;)" class="shbtn shmain" style="margin:10px 0 0;padding:11px;font-size:.9rem'+(dis?';opacity:.5':'')+'">'+l+'</button>';
 const step=(n,t,x)=>'<div style="display:flex;gap:10px;align-items:flex-start;padding:6px 0"><div style="flex:none;width:24px;height:24px;border-radius:99px;background:var(--accent);color:#fff;font-weight:800;font-size:.8rem;display:flex;align-items:center;justify-content:center">'+n+'</div><div><b style="font-size:.9rem">'+t+'</b><div style="font-size:.82rem;color:var(--muted2);line-height:1.45">'+x+'</div></div></div>';
 const full=P.seats_left<=0&&!P.manual;
 const h='<h3>'+T2('Les offres','The plans')+'</h3><div style="font-size:.76rem;color:var(--muted);line-height:1.45;margin:-4px 2px 10px">'+T2('OwlNest vend un logiciel et un service de copie \u2014 pas de conseil ni de gestion d\u2019investissement.','OwlNest sells software and a copy service \u2014 not investment advice or management.')+'</div><p style="color:var(--text)">'+T2('Une seule strat\u00e9gie \u2014 celle du robot du Owl. Vous choisissez comment la suivre.','One strategy \u2014 the Owl\u2019s robot. You choose how to follow it.')+'</p>'+
  tier(T2('D\u00e9mo','Demo'),T2('Gratuit, toujours','Free, always'),T2('Le robot en direct, sans compte','The robot live, no account needed'),
   [T2('Un vrai compte de d\u00e9monstration : solde, trades, m\u00e9t\u00e9o du march\u00e9, bilan du soir','A real demo account: balance, trades, market weather, evening review'),T2('Ouvert \u00e0 tous, depuis la page d\u2019accueil','Open to everyone, from the front page')],
   [T2('Pas de signaux, pas de compte personnel','No signals, no personal account')],'')+
  tier(T2('Signal','Signal'),'$'+(pk.manual||{}).usd+' / 30 j',T2('Les signaux du robot, vous tradez vous-m\u00eame','The robot\u2019s signals, you trade yourself'),
   [T2('Notification \u00ab Signal jouable \u00bb quand les conditions sont r\u00e9unies, et quand c\u2019est fini','\u201cPlayable signal\u201d push when conditions are met, and when it is over'),T2('Tout ce que montre la d\u00e9mo, sous votre nom ; sans compte MT5, vous tradez o\u00f9 vous voulez','Everything the demo shows, under your name; no MT5 account, you trade wherever you like'),T2('\u00ab Prochain signal ici \u00bb sur le graphique, la carte March\u00e9 en mode signal','\u201cNext signal here\u201d on the chart, the Market card in signal mode'),T2('Le rattrapage et le lot conseill\u00e9 apr\u00e8s une perte','Catch-up and the advised lot after a loss')],
   [T2('Le robot ne trade pas \u00e0 votre place','The robot does not trade for you'),T2('Les r\u00e8gles restent priv\u00e9es (voir Strat\u00e9gie)','The rules stay private (see Strategy)')],
   '<button class="shbtn shmain" style="margin:10px 0 0" onclick="_shDone(1);codeModal(&#39;manual&#39;)">'+T2('Choisir Signal','Choose Signal')+'</button>','var(--up-soft)')+
  tier(T2('Strat\u00e9gie','Strategy'),'$'+(pk.strategy||{}).usd+' / 30 j',T2('Tout comprendre \u2014 un paquet \u00e0 part, qui se combine','Understand everything \u2014 a separate package that combines'),
   [T2('Le graphique complet : points prot\u00e9g\u00e9s, cassures, niveaux attendus, en direct','The full chart: protected points, breaks, expected levels, live'),T2('La m\u00e9thode expliqu\u00e9e en mots simples (entr\u00e9es, stop, freins, rattrapage, limites)','The method in plain words (entries, stop, brakes, catch-up, limits)'),T2('Se combine avec Signal ou Automatique','Combines with Signal or Automatic')],
   [T2('Sans les signaux (voir Signal)','Without the signals (see Signal)')],
   '<button class="shbtn shmain" style="margin:10px 0 0" onclick="_shDone(1);codeModal(&#39;strategy&#39;)">'+T2('Choisir Strat\u00e9gie','Choose Strategy')+'</button>','var(--warn)')+
  tier(T2('Automatique','Automatic'),T2('Famille, sur invitation','Family, by invitation'),T2('Le robot sur votre compte, avec ses r\u00e8gles et ses freins','The robot on your account, with its rules and its brakes'),
   [T2('Le robot trade sur votre compte MT5, jour et nuit, depuis notre serveur','The robot trades your MT5 account, day and night, from our server'),T2('Votre page en direct : solde, trades, m\u00e9t\u00e9o du march\u00e9, bilan du soir','Your page live: balance, trades, market weather, evening review'),T2('Prix fixe chaque mois, r\u00e9gl\u00e9 avec le Owl ; code d\u2019activation par Telegram','Fixed monthly price, settled with the Owl; activation code by Telegram')],
   [T2('50 places, pour la famille','50 places, for the family')],
   '<button class="shbtn shmain" style="margin:10px 0 0" onclick="_shDone(1);codeModal(&#39;family&#39;)">'+T2('Choisir Automatique','Choose Automatic')+'</button>','var(--accent-soft)')+
  '<div class="lbl" style="margin:14px 0 4px">'+T2('Comment \u00e7a marche','How it works')+'</div>'+
  step(1,T2('Choisissez une offre','Pick a plan'),T2('Ici en crypto, ou avec le Owl sur Telegram : il vous envoie un code.','Here in crypto, or with the Owl on Telegram: he sends you a code.'))+
  step(2,T2('Payez en crypto','Pay in crypto'),T2('NOWPayments ouvre une page : USDT (Tron, BSC, Ethereum) ou USDC (Ethereum, Polygon, Solana), 20 minutes pour envoyer le montant exact. Le moins cher : USDT sur Tron. Rien n\u2019est pr\u00e9lev\u00e9 automatiquement.','NOWPayments opens a page: USDT (Tron, BSC, Ethereum) or USDC (Ethereum, Polygon, Solana), 20 minutes to send the exact amount. Cheapest: USDT on Tron. Nothing is charged automatically.'))+
  step(3,T2('Activation automatique','Automatic activation'),T2('D\u00e8s que le paiement est confirm\u00e9, l\u2019app s\u2019active seule et vous pr\u00e9vient.','As soon as the payment is confirmed, the app activates itself and tells you.'))+
  step(4,T2('Activez les notifications','Turn on notifications'),T2('R\u00e9glages \u203a Notifications. Les signaux du robot et le bilan du soir arrivent sur votre t\u00e9l\u00e9phone.','Settings \u203a Notifications. The robot\u2019s signals and the evening review reach your phone.'))+
  '<div class="lbl" style="margin:14px 0 4px">'+T2('Bon \u00e0 savoir','Good to know')+'</div>'+
  '<div style="font-size:.84rem;color:var(--muted2);line-height:1.55">'+
   '\u2022 '+T2('30 jours, sans reconduction automatique. Renouveler ajoute 30 jours.','30 days, no auto-renewal. Renewing adds 30 days.')+'<br>'+
   '\u2022 '+T2('Pour arr\u00eater : ne rien faire, l\u2019abonnement expire. Pas de remboursement une fois activ\u00e9.','To stop: do nothing, it expires. No refund once activated.')+'<br>'+
   '\u2022 '+T2('Trader comporte un risque de perte. Aucun r\u00e9sultat n\u2019est garanti.','Trading carries a risk of loss. No result is guaranteed.')+'</div>'+
  '<button class="shbtn shghost" onclick="_shDone(1)">Fermer</button>';
 sheet(h);
}
async function waitlistToggle(on){const en=LANG()==='en';
 const r=await fetch(B+'waitlist',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'on='+(on?1:0)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){toast(en?'Not saved, try again.':'Pas enregistr\u00e9, r\u00e9essayez.',2500);return;}
 if(window._d&&window._d.plan){window._d.plan.waitlisted=!!j.waitlisted;renderPlan(window._d);}
 toast(j.waitlisted?(en?'Noted. You get a notification when a place frees up.':'Not\u00e9. Vous recevrez une notification quand une place se lib\u00e8re.'):(en?'Removed from the waiting list.':'Retir\u00e9 de la liste d\u2019attente.'),3000);
}
async function paySheet(){const en=LANG()==='en';
 let j={items:[],ends:{}};try{const r=await fetch(B+'payments?t='+Date.now(),{cache:'no-store'});if(r.ok)j=await r.json();}catch(e){}
 const fd=ts=>{const x=new Date(ts*1000);return String(x.getDate()).padStart(2,'0')+'/'+String(x.getMonth()+1).padStart(2,'0')+'/'+x.getFullYear();};
 const now=Date.now()/1000,E=j.ends||{},L={family:en?'Automatic':'Automatique',manual:en?'Manual':'Manuel',strategy:en?'Strategy':'Strat\u00e9gie'};
 const ends=Object.keys(L).filter(k=>E[k]).map(k=>'<div class="row"><span class="rowt">'+L[k]+'</span><b style="color:'+(E[k]>now?'var(--up-soft)':'var(--down-soft)')+'">'+(E[k]>now?(en?'until ':'jusqu\u2019au ')+fd(E[k]):(en?'ended ':'termin\u00e9 le ')+fd(E[k]))+'</b></div>').join('');
 const rows=(j.items||[]).map(p=>{const ok=p.granted&&p.granted!=='short';const st=ok?(en?'activated':'activ\u00e9'):((p.status==='finished'||p.status==='confirmed')?(en?'amount short':'montant insuffisant'):(p.status||'\u2014'));
  return '<div class="row"><span class="rowt">'+fd(p.t)+' \u00b7 '+(L[p.pkg]||p.pkg||'')+'</span><b style="color:'+(ok?'var(--up-soft)':'var(--muted2)')+'">$'+Number(p.amount||0).toFixed(0)+' \u00b7 '+st+'</b></div>';}).join('');
 sheet('<h3>'+(en?'My payments':'Mes paiements')+'</h3>'+
  '<div class="lbl" style="margin-top:4px">'+(en?'Current access':'Acc\u00e8s en cours')+'</div>'+(ends||'<p style="color:var(--muted2)">'+(en?'No paid package yet.':'Aucun paquet pay\u00e9 pour l\u2019instant.')+'</p>')+
  '<div class="lbl" style="margin-top:14px">'+(en?'Receipts (NOWPayments)':'Re\u00e7us (NOWPayments)')+'</div>'+(rows||'<p style="color:var(--muted2)">'+(en?'No crypto payment recorded. Packages settled with the Owl directly do not appear here.':'Aucun paiement crypto enregistr\u00e9. Les paquets r\u00e9gl\u00e9s directement aupr\u00e8s du Owl n\u2019apparaissent pas ici.')+'</p>')+
  '<p style="font-size:.78rem;color:var(--muted)">'+(en?'A payment activates the package by itself, minutes after confirmation. If a receipt is missing, contact the Owl with the date.':'Un paiement active le paquet tout seul, quelques minutes apr\u00e8s confirmation. S\u2019il manque un re\u00e7u, contactez Kino avec la date.')+'</p>'+
  '<button class="shbtn shghost" onclick="_shDone(1)">'+(en?'Close':'Fermer')+'</button>');
}
// 2026-10-04 (owner): recovery through the Telegram bot - link once, then
// 'lien' gives the identifiant + personal link, 'nouveau mot de passe' a new one
async function tgLink(){const en=LANG()==='en';const P=(window._d&&window._d.plan)||{};
 const r=await fetch(B+'tg_link',{method:'POST'}).catch(()=>null);let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){toast(en?'Not available right now.':'Indisponible pour l\u2019instant.',2500);return;}
 const v=await sheet('<h3>'+(en?'Link Telegram':'Relier Telegram')+'</h3><p style="color:var(--text2)">'+(j.linked?(en?'Already linked. In Telegram, write \u201clien\u201d to the OwlNest bot to get your identifiant and your personal link back; \u201cnouveau mot de passe\u201d gives a new password.':'D\u00e9j\u00e0 reli\u00e9. Sur Telegram, \u00e9crivez \u00ab lien \u00bb au robot OwlNest pour retrouver votre identifiant et votre lien personnel ; \u00ab nouveau mot de passe \u00bb en cr\u00e9e un nouveau.'):(en?'Tap the button: Telegram opens the OwlNest bot and links it to this account. From then on, \u201clien\u201d brings your access back, any day, without e-mail.':'Touchez le bouton : Telegram ouvre le robot OwlNest et le relie \u00e0 ce compte. Ensuite, \u00ab lien \u00bb vous rend votre acc\u00e8s, n\u2019importe quel jour, sans e-mail.'))+'</p>'+
  '<a class="shbtn shmain" style="display:block;text-align:center;text-decoration:none" href="'+_escS(j.url)+'" target="_blank" rel="noopener">'+(j.linked?(en?'Open the bot':'Ouvrir le robot'):(en?'Link in Telegram':'Relier dans Telegram'))+'</a>'+
  '<button class="shbtn shghost" onclick="_shDone(1)">'+(en?'Close':'Fermer')+'</button>');}
async function pwdChange(){const en=LANG()==='en';
 const f=(id,ph)=>'<input id="'+id+'" type="password" placeholder="'+ph+'" style="width:100%;box-sizing:border-box;background:var(--surface2);border:1px solid var(--border);border-radius:12px;color:var(--text);padding:12px;font-size:1rem;margin-top:8px">';
 const v=await sheet('<h3>'+(en?'Change my password':'Changer mon mot de passe')+'</h3>'+f('pc-old',en?'current password':'mot de passe actuel')+f('pc-new',en?'new password (6+)':'nouveau mot de passe (6+)')+
  '<button class="shbtn shmain" style="margin-top:14px" onclick="_shDone({o:document.getElementById(&#39;pc-old&#39;).value,n:document.getElementById(&#39;pc-new&#39;).value})">'+(en?'Change':'Changer')+'</button><button class="shbtn shghost" onclick="_shDone(null)">'+(en?'Cancel':'Annuler')+'</button>');
 if(!v)return;if(!v.n||v.n.length<6){toast(en?'6 characters at least.':'6 caract\u00e8res au moins.',2200);return;}
 const r=await fetch(B+'app_pwd',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'old='+encodeURIComponent(v.o||'')+'&new='+encodeURIComponent(v.n)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){await info('&#10060; <h3>'+(j&&j.err==='bad password'?(en?'Current password incorrect.':'Mot de passe actuel incorrect.'):(en?'It did not work.':'\u00c7a n\u2019a pas march\u00e9.'))+'</h3>');return;}
 toast(en?'Password changed':'Mot de passe chang\u00e9',2200);}
async function payShare(ym){
 const en=LANG()==='en';
 const r=await fetch(B+'pay_share',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'ym='+encodeURIComponent(ym)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){toast(en?'Payment page unavailable - settle with the Owl.':'Page de paiement indisponible \u2014 r\u00e9glez avec le Owl.',3200);return;}
 try{window.open(j.url,'_blank');}catch(e){location.href=j.url;}
}
async function buyPkg(k){
 const en=LANG()==='en';
 const r=await fetch(B+'buy',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'pkg='+encodeURIComponent(k)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){toast(j&&j.err==='complet'?(en?'No place left for now \u2014 use \u201cTell me when a place frees up\u201d.':'Plus de place pour l\u2019instant \u2014 utilisez \u00ab Me pr\u00e9venir quand une place se lib\u00e8re \u00bb.'):(j&&j.err==='not ready'?(en?'Payments open soon.':'Paiements bient\u00f4t disponibles.'):(en?'Cannot create the invoice right now.':'Impossible de cr\u00e9er la facture pour l\u2019instant.')),3500);return;}
 try{window.open(j.url,'_blank');}catch(e){location.href=j.url;}
}
function stratSheet(){
 const en=LANG()==='en';
 const row=(ic,c,t,x)=>'<div class="srow-ev"><div class="evi" style="color:'+c+'"><svg class="ic ic-s"><use href="#'+ic+'"/></svg></div><div style="flex:1;min-width:0"><b style="font-size:.92rem">'+t+'</b><div style="font-size:.84rem;color:var(--muted2);line-height:1.45;margin-top:2px">'+x+'</div></div></div>';
 const F=[
  ['i-activity','var(--accent-soft)','La structure du march\u00e9','Le robot lit les hauts et les bas du march\u00e9 sur 1 minute. Un <b>point prot\u00e9g\u00e9</b> (le point sur le graphique) est le dernier creux ou sommet qui tient la tendance.'],
  ['i-chart','var(--up)','Les trois entr\u00e9es','<b>Bascule</b> : le prix casse le point prot\u00e9g\u00e9, la tendance change, on entre dans le nouveau sens. <b>Continuation</b> : dans une tendance en cours, le prix casse le dernier sommet (ou creux) : on entre dans le sens de la tendance, une fois par niveau. <b>Toucher</b> : le prix vient toucher le point prot\u00e9g\u00e9 sans le casser et repart.'],
  ['i-lock','var(--warn)','Le stop et la cible','Le stop est plac\u00e9 au niveau de la structure (pas sur la bougie). La cible vaut 0,8 fois le risque : le robot gagne un peu plus souvent qu\u2019il ne perd, et c\u2019est la fr\u00e9quence qui paie.'],
  ['i-cloud','var(--muted2)','Les freins','Nervosit\u00e9 : la taille des bougies de l\u2019heure compar\u00e9e aux 24 h. Au-dessus de 1,85\u00d7 (\u00ab tr\u00e8s agit\u00e9 \u00bb) personne ne trade. Mouvement : sans grand mouvement depuis 2 h, on attend. Une petite structure interne existe aussi, avec ses propres r\u00e8gles, plus prudente.'],
  ['i-target','var(--down-soft)','Le rattrapage','Apr\u00e8s une perte, le robot ne prend que la bascule et <b>une</b> continuation apr\u00e8s elle (ou apr\u00e8s un toucher). La petite structure est en pause. Une r\u00e9serve, aliment\u00e9e par une part de chaque gain, permet un lot un peu plus gros \u2014 jamais plus de 10 % du solde sur un trade.'],
  ['i-stop','var(--down)','Les limites','Objectif par jour selon le solde ; ligne de s\u00e9curit\u00e9 \u00e0 \u2212$60 net : le robot s\u2019arr\u00eate seul. Le graphique complet vous montre tout \u00e7a en direct : points, cassures, niveaux attendus.']];
 sheet('<h3>'+(en?'The strategy':'La strat\u00e9gie')+'</h3><p style="color:var(--text)">'+(en?'The method, in plain words. The full chart shows it live.':'La m\u00e9thode, en mots simples. Le graphique complet la montre en direct.')+'</p>'+F.map(f=>row(f[0],f[1],f[2],f[3])).join('')+
  '<a class="shbtn shmain" style="display:block;text-align:center;text-decoration:none;margin-top:12px" href="'+B+'chart">'+(en?'Open the full chart':'Ouvrir le graphique complet')+'</a><button class="shbtn shghost" onclick="_shDone(1)">Fermer</button>');
}
async function payCfg(){
 const d=window._d||{};
 const inp=(id,ph,val,type)=>'<input id="'+id+'" type="'+(type||'text')+'" placeholder="'+ph+'" value="'+String(val||'').replace(/"/g,'&quot;')+'" style="width:100%;box-sizing:border-box;border:1px solid var(--border2);background:var(--surface2);color:var(--text);border-radius:12px;padding:11px 14px;font-size:.92rem;margin-bottom:8px">';
 const P=d.plan||{};
 const v=await sheet('<h3>Paiements</h3><p>Cl\u00e9s NOWPayments (compte marchand), secret IPN (m\u00eame valeur que dans NOWPayments \u203a IPN). Laissez vide pour ne pas changer.</p>'+
  '<div style="font-size:.8rem;color:var(--muted2);margin:-4px 0 10px">\u00c9tat : '+(P.np_key_tail?'cl\u00e9 API enregistr\u00e9e (\u2026'+P.np_key_tail+')':'cl\u00e9 API absente')+' \u00b7 secret IPN '+(P.np_secret_set?'enregistr\u00e9':'absent')+(P.np_sandbox?' \u00b7 mode test':'')+'</div>'+
  inp('shnpk','Cl\u00e9 API NOWPayments','', 'password')+inp('shnps','Secret IPN','', 'password')+
  inp('shfam','Prix Automatique (famille) en $ / 30 j, pour le calcul des revenus',(d.revenue&&d.revenue.family_usd)||'', 'number')+
  '<label style="display:flex;align-items:center;gap:8px;font-size:.86rem;color:var(--muted2);margin:2px 0 10px"><input id="shsbx" type="checkbox"'+(P.np_sandbox?' checked':'')+'> Mode test (sandbox NOWPayments)</label>'+
  '<button class="shbtn shmain" onclick="_shDone({k:document.getElementById(&#39;shnpk&#39;).value,s:document.getElementById(&#39;shnps&#39;).value,m:document.getElementById(&#39;shmq&#39;).value,b:document.getElementById(&#39;shsbx&#39;).checked,f:document.getElementById(&#39;shfam&#39;).value})">Enregistrer</button>'+
  '<button class="shbtn shghost" onclick="_shDone(null)">Annuler</button>');
 if(!v)return;
 const pw=await askPwd('Enregistrer ?','Mot de passe ma\u00eetre.','Enregistrer');if(!pw)return;
 let body='pwd='+encodeURIComponent(pw)+'&np_sandbox='+(v.b?'1':'0')+(v.f!==''&&v.f!=null?'&family_usd='+encodeURIComponent(v.f):'');
 if(v.k)body+='&np_api_key='+encodeURIComponent(v.k);if(v.s)body+='&np_ipn_secret='+encodeURIComponent(v.s);
 const r=await fetch(AB()+'nest_config',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){await info('&#10060; <h3>'+(j&&j.err==='bad password'?'Mot de passe incorrect.':'Impossible pour l\u2019instant.')+'</h3>');return;}
 toast('Enregistr\u00e9',2000);window._lastS=null;load();
}
function agoTxt(ts){if(!ts)return LANG()==='en'?'never seen':'jamais vu';const s=Math.max(0,Date.now()/1000-ts),en=LANG()==='en';
 if(s<120)return en?'seen just now':'vu \u00e0 l\u2019instant';if(s<3600)return (en?'seen ':'vu il y a ')+Math.round(s/60)+' min'+(en?' ago':'');
 if(s<86400)return (en?'seen ':'vu il y a ')+Math.round(s/3600)+' h'+(en?' ago':'');return (en?'seen ':'vu il y a ')+Math.round(s/86400)+(en?' d ago':' j');}
async function contactCfg(){
 const d=window._d||{};
 const v=await sheet('<h3>Lien de contact</h3><p>Montr\u00e9 dans les R\u00e9glages de chaque membre (\u00ab Contacter le Owl \u00bb). WhatsApp : https://wa.me/33612345678 \u00b7 Telegram : https://t.me/votrenom \u00b7 ou mailto:</p>'+
  '<input id="shcurl" type="url" placeholder="https://wa.me/..." value="'+String(d.contact_url||'').replace(/"/g,'&quot;')+'" style="width:100%;box-sizing:border-box;border:1px solid var(--border2);background:var(--surface2);color:var(--text);border-radius:12px;padding:12px 14px;font-size:.95rem;margin-bottom:8px">'+
  '<input id="shclbl" type="text" maxlength="60" placeholder="Libell\u00e9 (Contacter le Owl)" value="'+String(d.contact_label||'').replace(/"/g,'&quot;')+'" style="width:100%;box-sizing:border-box;border:1px solid var(--border2);background:var(--surface2);color:var(--text);border-radius:12px;padding:12px 14px;font-size:.95rem;margin-bottom:10px">'+
  '<button class="shbtn shmain" onclick="_shDone({u:document.getElementById(&#39;shcurl&#39;).value,l:document.getElementById(&#39;shclbl&#39;).value})">Enregistrer</button>'+
  '<button class="shbtn shghost" onclick="_shDone(null)">Annuler</button>');
 if(!v)return;
 const pw=await askPwd('Enregistrer le lien ?','Mot de passe ma\u00eetre.','Enregistrer');if(!pw)return;
 const r=await fetch(AB()+'nest_config',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
  body:'contact_url='+encodeURIComponent(v.u||'')+'&contact_label='+encodeURIComponent(v.l||'')+'&pwd='+encodeURIComponent(pw)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){await info('&#10060; <h3>'+(j&&j.err==='bad password'?'Mot de passe incorrect.':(j&&j.err==='bad url'?'Lien invalide (https://, mailto: ou tel:).':'Impossible pour l\u2019instant.'))+'</h3>');return;}
 toast('Lien enregistr\u00e9',2000);window._lastS=null;load();
}
async function nestNote(uid,name){
 const cur=((window._nest||[]).find(x=>x.id===uid)||{}).note||'';
 const v=await sheet('<h3>Note \u00b7 '+name+'</h3><p>Priv\u00e9e, visible seulement par vous, dans Le Nid et Vos comptes.</p>'+
  '<textarea id="shnote" maxlength="300" rows="3" style="width:100%;box-sizing:border-box;border:1px solid var(--border2);background:var(--surface2);color:var(--text);border-radius:12px;padding:10px 12px;font-size:.95rem;font-family:inherit;resize:vertical">'+cur.replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))+'</textarea>'+
  '<button class="shbtn shmain" onclick="_shDone(document.getElementById(&#39;shnote&#39;).value)">Enregistrer</button>'+
  (cur?'<button class="shbtn shghost" onclick="_shDone(&#39;&#39;)">Effacer la note</button>':'')+
  '<button class="shbtn shghost" onclick="_shDone(null)">Annuler</button>');
 if(v===null)return;
 const pw=await askPwd('Enregistrer la note ?','Mot de passe ma\u00eetre.','Enregistrer');if(!pw)return;
 const r=await fetch(AB()+'nest_note',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
  body:'uid='+encodeURIComponent(uid)+'&text='+encodeURIComponent(v)+'&pwd='+encodeURIComponent(pw)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){await info('&#10060; <h3>'+(j&&j.err==='bad password'?'Mot de passe incorrect.':'Impossible pour l\u2019instant.')+'</h3>');return;}
 const n=(window._nest||[]).find(x=>x.id===uid);if(n)n.note=v;
 toast('Note enregistr\u00e9e',2000);
}
async function nestPause(uid,on){
 const pw=await askPwd(
  on=='1'?'Mettre ce membre en pause ?':'Reprendre ce membre ?',
  'Le robot '+(on=='1'?'ne prendra plus':'reprendra')+
  ' de nouveaux trades sur ce compte.',
  on=='1'?'&#9208;&#65039; Mettre en pause':'&#9654;&#65039; Reprendre',
  on=='1');
 if(!pw)return;
 const r=await fetch(AB()+'nest_pause',{method:'POST',
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
   '&#9203; <b>Essai termin&eacute;.</b> Contactez le Owl pour passer au '+
   'Premium et continuer.';return}
  if(d.error){document.getElementById('st').innerHTML=
   '&#9203; '+(d.error.includes('patientez')?d.error:
   'Petit souci technique, r&eacute;essai automatique...');return}
  const lv=document.getElementById('lv'),lvd=document.getElementById('lvd'),
   lvt=document.getElementById('lvt');
  // 2026-10-01: while the offline banner is up it owns the chip - this
  // render may be the CACHED payload being redrawn, and saying EN DIRECT
  // over "Connexion perdue" is how the contradiction happened.
  if(window._offNow){/* the banner has it */}
  else if(d.stale){lv.style.background='rgba(230,160,40,.16)';
   lv.style.color='#ffd27a';lvd.style.background='#e6a028';
   lvt.textContent='RECONNEXION';}
  else{lv.style.background='rgba(46,204,113,.16)';lv.style.color='var(--up-soft)';
   lvd.style.background='var(--up)';lvt.textContent='EN DIRECT';}
  {
   const mc=document.getElementById('meteo');
   let cls='mx-sun',orb='\\u2600\\ufe0f',
    ti='March\\u00e9 normal',
    ln='Grand beau temps sur la mer \\u2014 le hibou laisse son '+
     'robot travailler tranquillement.';
   const chips=[];
   if(d.meteo_struct){
    const ms2=d.meteo_struct;
    // Owner 2026-09-17, after the retraction: the card must say what the
    // evidence says. Only ONE thing held under both anchors - when the
    // internal structure has not broken recently, trades tend to go worse,
    // and a busy MAIN structure does not rescue it. So the internal gate is
    // the headline and everything else is context, which is the opposite of
    // how this card used to be built.
    const mv=ms2.moves_2h!==undefined?ms2.moves_2h:(ms2.flips_2h||0);
    const rv=(ms2.vol_now&&ms2.vol_ref)
     ?ms2.vol_now/Math.max(ms2.vol_ref,1):1;
    const nb=ms2.int_brk_1h||0, aw=nb>=1;
    // Owner 2026-09-17: written for someone who has never heard of a
    // "structure" or a "break". Plain words, one short line, no jargon.
    // The long version belongs in the info sheet, not on the card.
    // Owner 2026-09-27: two voices. AUTO - the robot is in charge and says
    // what it will do. MANUAL - the app is a signal service and leaves the
    // decision to the member. The two gates only ever STOP a trade (owner
    // 2026-09-17), so "feu vert" means "nothing holds it back", never a
    // promise of profit.
    const ST=T('wx');
    (function(){const J=document.getElementById('mx-jump');
  // 2026-10-01: `en` is NOT in scope in render(). Every nearby use of
  // it is inside a NESTED function that declares its own. Assuming it
  // was there threw a ReferenceError right after dataset.on had been
  // set - which is why the row existed with zero buttons and nothing
  // in the error list.
  const en=LANG()==='en';
  if(J&&!J.dataset.on){J.dataset.on='1';
   const items=[['meteo',en?'Weather':'M\u00e9t\u00e9o'],
                ['tfcard',en?'Timeframes':'Les temps'],
                ['mhcard',en?'Hours':'Heures'],
                ['lrn-card',en?'Lessons':'Le\u00e7ons']];
   J.innerHTML=items.map(it=>'<button data-go="'+it[0]+'" style="flex:none;'+
    'border:1px solid var(--border);background:var(--surface2);color:var(--muted2);'+
    'border-radius:99px;padding:11px 14px;min-height:40px;'+
    'font-size:.78rem;font-weight:700">'+it[1]+
    '</button>').join('');
   J.querySelectorAll('button').forEach(b=>{b.onclick=()=>{
    const t=document.getElementById(b.dataset.go);
    if(t&&getComputedStyle(t).display!=='none')t.scrollIntoView({behavior:'smooth',block:'start'});};});
   // 2026-10-03 (owner): a button only for a card that is on the page. The
   // public demo hides Les temps / Heures / Lecons by design; the buttons
   // were drawn anyway and led nowhere. The cards load at their own pace,
   // so the row is re-checked rather than computed once.
   const sync=()=>{let shown=0;J.querySelectorAll('button').forEach(b=>{const t=document.getElementById(b.dataset.go);const on=!!t&&getComputedStyle(t).display!=='none';b.style.display=on?'':'none';if(on)shown++;});J.style.display=shown>1?'':'none';};
   sync();setInterval(sync,1500);}
  })();
 (function(){const hh=document.getElementById('mx-hint');
     if(hh)setH(hh,T('mx_hint'));})();
    // The card must say exactly what weather_gate() would say, in the same
    // order, or it explains a refusal that is not the real one.
    //
    // Owner 2026-09-18 caught two mistakes here. (1) The small-move count
    // was the headline even with NO internal structure, when the live rule
    // falls back to the big-move count over 2 h - so the card judged on a
    // number the bots were ignoring. (2) The "none" wording claimed the
    // market was CALM while nervosity said 1.18x AGITATED: nervosity is
    // checked first by the gate, so it must be checked first here too.
    // each half is a per-account dial now (owner 2026-09-20). A brake this
    // account does not run must not appear in the headline at all.
    const gN=!(d.gates&&d.gates.nervosity===false);
    const gM=!(d.gates&&d.gates.movement===false);
    // the "tres agite" exception outranks every dial (owner 2026-09-21):
    // NO account trades here, so a no-brakes account must not be told it
    // takes every signal. 1.85 is NERV_STORM in structure_bos_bot.py and
    // the "tres agite" band boundary below - change the three together.
    const storm=rv>=1.85;
    const nerv_bad=storm||(gN&&rv>1.0);
    const hasInt=!!ms2.int_trend;          // 0 = no internal structure
    // 2026-10-01 (owner): "it should only consider the big structure right?"
    // Yes. The inner movement rule is only ever applied to an INNER entry,
    // and those are switched off, so the deciding rule is the big one. This
    // follows the FLAG rather than today's answer, so it comes back by
    // itself if an account ever re-enables inner entries.
    const intOn=!!ms2.internal_entries;
    const intRule=hasInt&&intOn;          // is the inner rule the one deciding?
    const mvOk=gM?(intRule?(nb>=1):(mv>=1)):true;
    const k=storm?'nervous'
      :((!gN&&!gM)?'nogate'
      :(nerv_bad?(rv<1.30?'brisk':'nervous')
      :(!mvOk?'none'
      :(intRule?(ms2.int_state||'ready'):'ready'))));
    const S=ST[k]||ST.none;
    window._mxk=k;
    orb=S[0]; ti=S[1]; ln=S[3];
    cls=nerv_bad?'mx-cloud':(!mvOk?'mx-sleep'
         :(k==='ready'?'mx-fish':'mx-sun'));
    // The GATE stays at 1.0 - that is the measured line, the only one that
    // held under both window anchors. These are only the WORDS.
    //
    // Owner 2026-09-18: "so most of the time it's agitated?" No - 47%. The
    // threshold sits on the median (0.98 over 41.7 days), so "agité" was
    // lighting up on a coin flip and stopped meaning anything. 1.18x, which
    // the card called agitated, is the 68th percentile: brisk, not a storm.
    // Measured bands, so each word matches how often it is true:
    //   < 1.00  calme        53% of the time
    //   < 1.30  vif          22%   (68th-75th percentile territory)
    //   < 1.85  rapide       15%   (1 hour in 4 is above 1.31)
    //   >=1.85  tres rapide  10%   (1 hour in 10)
    // Owner 2026-09-22 (measured, review/chop_vs_nerv.py): this number
    // correlates +0.64 with the DISTANCE price walks in the hour and only
    // +0.13 with chop - and that sign is POSITIVE, so the top band is the
    // most DIRECTIONAL state in the sample, not the messiest (efficiency
    // 0.099 calme -> 0.131 top band; distance walked 1080 -> 2697 pts/h).
    // "agité" told the owner the market was messy when it was simply big,
    // so the words now say size. The 1.0 / 1.30 / 1.85 lines are unchanged.
    const vw=rv<1.0?['calme','var(--text)']
      :(rv<1.30?['soutenu','var(--warn)']
      :(rv<1.85?['rapide','#e8743b']:['très rapide','var(--down)']));
    const NW='white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
    // Owner 2026-09-17: the spread is gone. It is a cost judged against the
    // stop, and this card cannot know the stop - it answered a different
    // question. The space goes to the two figures that actually decide.
    // Top row = the two brakes, accented. Bottom row = context, plain.
    // 2026-10-01 (owner): two real columns. The grid was already
    // 1fr 1fr, but a track will not shrink below its content and every
    // label carried white-space:nowrap - so "GRANDS MOUVEMENTS" forced
    // each track full width and the grid collapsed to one column. The
    // label wraps now; only the figure stays on one line. The accented
    // tile gets a left bar rather than a blue wash: emphasis without
    // shouting.
    const cell=(l,v,c,acc)=>'<div style="min-width:0;padding:9px 11px;'+
     'border-radius:13px;background:var(--tile-bg);border:1px solid '+
     (acc?'rgba(59,130,246,.34)':'var(--tile-bd)')+
     (acc?';box-shadow:inset 3px 0 0 var(--accent-soft)':'')+'">'+
     '<div style="font-size:.62rem;line-height:1.25;color:'+
     (acc?'var(--accent-soft)':'var(--muted2)')+
     ';text-transform:uppercase;letter-spacing:.07em">'+l+'</div>'+
     // 2026-10-01: the value WRAPS. Some of these are figures ("0 / 1h")
     // and some are short phrases ("7 pts - 26 % d'une bougie"); nowrap
     // ellipsised the phrases mid-word in a half-width tile. Grid rows
     // stretch to the tallest cell, so a pair stays aligned either way.
     '<b style="display:block;font-size:1.02rem;margin-top:3px;'+
     'line-height:1.3;color:'+(c||'var(--text)')+
     ';font-variant-numeric:tabular-nums">'+v+'</b></div>';
    const tcol=ms2.trend===1?'var(--up-soft)':(ms2.trend===-1?'var(--down-soft)':'var(--muted2)');
    const ttxt=ms2.trend===1?'▲ hausse'
     :(ms2.trend===-1?'▼ baisse':'—');
    // Accent = the two figures that DECIDE right now. Which movement rule
    // that is depends on whether there is an internal structure, so the
    // accent moves with it instead of always sitting on the small count
    // (owner 2026-09-18).
    // 2026-10-01 (owner): with no internal structure this drew a full row
    // containing a dash. Say what is actually true instead of nothing.
    const small=cell('petits mouvements',
     hasInt?(nb+'&thinsp;/&thinsp;1h')
      :(LANG()==='en'?'none right now':'aucune pour l\u2019instant'),
     intRule?(aw?'var(--accent-soft)':'var(--muted)'):'var(--muted)',intRule&&gM);
    const big=cell('grands mouvements',mv+'&thinsp;/&thinsp;2h',
     intRule?(mv===0?'var(--muted)':'var(--text)')
      :(mv>=1?'var(--accent-soft)':'var(--muted)'),(!intRule)&&gM);
    // the deciding movement rule first, then nervosity - always a brake
    chips.push(intRule?small:big);
    // 2026-10-01: the same figure, promoted to the header. It stays in
    // the tiles too - the tile gives it its name, the header gives it
    // the size it deserves.
    {const nw=document.getElementById('mx-now');
     if(nw){nw.querySelector('b').textContent=rv.toFixed(2)+'\u00d7';
      nw.querySelector('b').style.color=vw[1];
      nw.querySelector('span').textContent=vw[0];
      nw.style.display='block';}}
    // 2026-10-01: the nervosity TILE is gone. The header readout above is
    // the same figure at 1.7rem, and seeing them rendered together made
    // the duplication obvious - "0.58x CALME" and "0.58x calme" inside
    // 300px is not emphasis. The header carries it; the tiles carry what
    // it does not say.
    // then the context
    chips.push(intRule?big:small);
    chips.push(cell('sens',ttxt,tcol,false));
    // 2026-09-29 (owner): two market facts the robot does not use yet.
    // The spread is fixed at 7 pts on this broker, so what changes is how
    // big a bite it takes out of a candle; and nervosity is a ratio, so a
    // market can look normal while being tiny in absolute points.
    const _vn=+(ms2.vol_now||0),_sp=+(ms2.spread||0);
    if(_vn>0&&_sp>0){
     const _sh=Math.round(_sp/_vn*100);
     chips.push(cell('prix du ticket',_sp.toFixed(0)+' pts \u00b7 '+_sh+'\u202f% d\u2019une bougie',
      _sh>=22?'var(--warn)':'var(--muted2)',false));
     const _cal=_vn<32?['tr\u00e8s calme','var(--warn)']:(_vn<45?['calme','var(--muted2)']:(_vn<58?['normal','var(--text)']:['ample','var(--up-soft)']));
     chips.push(cell('taille des bougies',_vn.toFixed(0)+' pts \u00b7 '+_cal[0],_cal[1],false));
    }
   }
   else if(d.meteo==='storm'||d.meteo==='shelter'){
    cls='mx-storm';window._mxk='storm';orb='\\u26c8\\ufe0f';
    ti='March\\u00e9 tr\\u00e8s agit\\u00e9';
    ln='Gros orage sur la mer \\u2014 le hibou met son robot '+
     '\\u00e0 l\\u2019abri et attend.';}
   else if(d.meteo==='floor'){
    cls='mx-cloud';window._mxk='nervous';orb='\\u{1F326}\\ufe0f';
    ti='March\\u00e9 nerveux';
    ln='Temps couvert \\u2014 le hibou ne laisse passer que de '+
     'petits trades, prudemment.';}
   else if(d.meteo==='clear'){
    cls='mx-sun';window._mxk='ready';orb='\\u{1F324}\\ufe0f';
    ti='Retour au calme';
    ln='\\u00c9claircie sur la mer \\u2014 le hibou renvoie son '+
     'robot travailler.';}
   if((d.meteo==='storm'||d.meteo==='shelter'||d.meteo==='floor')
      &&d.meteo_since){
    const s=Math.max(0,Math.round(Date.now()/1000-d.meteo_since));
    const hh=Math.floor(s/3600),mm=Math.floor((s%3600)/60);
    chips.push('\\u23f8 depuis '+(hh>0?hh+' h ':'')+mm+' min');}
   mc.className='status '+cls;
   document.getElementById('mx-orb').innerHTML=ORB[cls]||ORB['mx-sun'];
   setH(document.getElementById('mx-title'),ti);
   setH(document.getElementById('mx-line'),ln);
   // 2026-10-01: with two real columns an odd count leaves the last tile
   // half width with a gap beside it. It spans instead.
   {const _tiles=chips.map(c=>c.indexOf('<div')===0?c
     :'<div style="grid-column:1/-1"><span class="mxc">'+c+
      '</span></div>');
    const _n=_tiles.filter(c=>c.indexOf('grid-column')<0).length;
    if(_n%2===1){for(let i=_tiles.length-1;i>=0;i--){
     if(_tiles[i].indexOf('grid-column')<0){
      _tiles[i]=_tiles[i].replace('<div style="','<div style="grid-column:1 / -1;');
      break;}}}
    setH(document.getElementById('mx-chips'),_tiles.join(''));}
   const _so=document.getElementById('mxs-orb');
   if(_so){_so.innerHTML=ORB[cls]||ORB['mx-sun'];
    setH(document.getElementById('mxs-title'),ti);
    setH(document.getElementById('mxs-sub'),ln);}
  }
  if(d.ftest){
   const ft=d.ftest;
   const fc=document.getElementById('ftcard');
   fc.style.display='block';
   const wr=ft.n?ft.w/Math.max(1,ft.w+ft.l):0;
   const col=(ft.w+ft.l)<5?'#7fb0ff'
    :(wr>=ft.wr_pass?'#2ecc71':(wr>=0.60?'#e8c55a':'#ff5c5c'));
   document.getElementById('ft-txt').innerHTML=
    'Trade <b>'+ft.n+'</b> sur '+ft.target+' &middot; '+
    '<span style="color:var(--up-soft)">'+ft.w+' gagn&eacute;s</span> / '+
    '<span style="color:var(--down-soft)">'+ft.l+' perdus</span>'+
    ((ft.w+ft.l)?' (<b style="color:'+col+'">'+
     Math.round(wr*100)+'&nbsp;%</b>)':'')+
    ' &middot; <b class="'+(sgn(ft.net))+'">'+
    (ft.net>=0?'+$':'-$')+Math.abs(ft.net).toFixed(2)+'</b>';
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
   lc.style.boxShadow='';lc.style.borderColor='var(--border2)';
   document.getElementById('led-hd').style.display=
    d.ledger.debt>0.5?'block':'none';
   if(d.ledger.debt>0.5){
    {
     // Owner 2026-09-17: ONE design, manual or automatic. There used to be
     // a second layout for the paused state, and once "paused" came to mean
     // manual it became the one the owner saw every day - the old magazine
     // look, not the redesign. The branch is gone.

     const am=d.ledger.chest;
     const need=Math.max(d.ledger.need_min||0.01,0.01);
     const bos=!!d.ledger.bos;
     let nl=Math.max(d.ledger.next_lot||0.02,0.01);
     let SL,prog,ok,gain1=0;
     if(bos){
      SL=d.ledger.max_extra||3;   // the possible extra lots
      // the jar stakes only PART of itself per attempt, and a recovery is
      // never bigger than the tab needs - mirror the bot exactly instead of
      // recomputing with the old whole-jar rule (owner 2026-09-16)
      const stF=(d.ledger.stake!==undefined)?d.ledger.stake:1;
      gain1=(d.ledger.rr||0.8)*need;         // what one extra 0.01 wins
      const g1=gain1;
      const byDebt=g1>0?Math.ceil(d.ledger.debt/g1):0;
      prog=Math.max(0,Math.min(SL,am*stF/need));
      prog=Math.min(prog,byDebt);
      nl=(d.ledger.base_lot||0.02)+Math.min(SL,Math.floor(prog+1e-9))*0.01;
      ok=prog>=SL;
     }else{
      SL=Math.max(2,Math.min(10,Math.round(nl/0.01)));
      prog=Math.max(0,Math.min(SL,am/need*SL));
      ok=am>=need-0.005;
     }
     const fillN=Math.floor(prog+1e-9);
     const fr=prog-fillN;
     // the trade opens at the BASE lot and risks its full stop: that is
     // 2 bullets priced at the full stop = 4 midpoint-bullets. Each
     // reinforcement that can still fire adds one more (owner 2026-09-20).
     const stake=(4+Math.min(SL,fillN))*need;
     const fm=v=>v<10?v.toFixed(1):v.toFixed(0);
     window._ledD={mode:bos?'bos':'bot',debt:d.ledger.debt,
      chest:am,need:need,nl:nl,fill:fillN,stake:stake};
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
     // Owner 2026-09-16 redesign. One hero (what is owed), one bar (how
     // loaded the reserve is against its live ceiling), one action row
     // (the next lot, its risk, what a win clears). The old layout made the
     // STAKE the biggest number on a card about recovery, and spent five
     // accent colours on a small surface.
     const jarPct=Math.max(0,Math.min(100,
      100*am/Math.max(d.ledger.cap||1,0.01)));
     const clears=fillN*gain1;
     const stillNeed=Math.max(0,need/(d.ledger.stake||0.5)-am);
     Object.assign(window._ledD,{clears:clears,stillNeed:stillNeed,
      cap:d.ledger.cap,base_lot:d.ledger.base_lot});
     lt2.innerHTML=
      '<div style="text-align:center;padding:2px 0 10px">'+
       '<b style="color:var(--down-soft);font-size:2.4rem;line-height:1;'+
        'font-variant-numeric:tabular-nums;letter-spacing:-.02em">'+
        '$<span id="rz-debt">'+d.ledger.debt.toFixed(2)+'</span></b>'+
       '<div style="font-size:.66rem;color:var(--muted2);margin-top:4px;'+
        'text-transform:uppercase;letter-spacing:.1em">'+
        '&agrave; rattraper</div>'+
      '</div>'+
      '<div style="display:flex;align-items:center;gap:8px;'+
       'font-size:.7rem;color:var(--muted2);margin-bottom:3px">'+
       '<span style="flex:1">R&eacute;serve</span>'+
       '<span style="font-variant-numeric:tabular-nums;color:var(--warn)">'+
        '$<span id="rz-ammo">'+am.toFixed(2)+'</span>'+
        '<span style="color:#6b5f38"> / $'+fm(d.ledger.cap||0)+
        '</span></span>'+
      '</div>'+
      // 2026-10-01 (owner): an empty track reads as broken rather than
      // as "not started" - the same complaint that turned out to be a
      // real bug on the growth bar. At zero, say what fills it.
      (am>0.005
       ?'<div style="background:rgba(255,255,255,.07);border-radius:99px;'+
        'height:7px;overflow:hidden">'+
        '<div style="height:7px;border-radius:99px;width:'+
         jarPct.toFixed(0)+'%;background:linear-gradient(90deg,'+
         '#b8963f,#e8c55a);transition:width .8s"></div>'+
        '</div>'
       :'<div style="font-size:.76rem;color:var(--muted);line-height:1.45">'+
        'Elle se remplit sur les gains, puis paie les trades de '+
        'rattrapage.</div>')+
      '<div style="margin-top:12px;background:rgba(127,179,224,.06);'+
       'border:1px solid rgba(127,179,224,.16);border-radius:12px;'+
       'padding:10px 12px">'+
       '<div style="display:flex;align-items:baseline;gap:6px">'+
        '<span style="flex:1;font-size:.7rem;color:var(--muted2);'+
         'text-transform:uppercase;letter-spacing:.08em">'+
         'Prochain trade</span>'+
        '<b style="color:var(--text2);font-size:1.15rem;'+
         'font-variant-numeric:tabular-nums"><span id="rz-lot">'+
         nl.toFixed(2)+'</span></b>'+
        '<span style="font-size:.72rem;color:var(--muted2)"> lot</span>'+
       '</div>'+
       '<div style="font-size:.72rem;color:var(--muted2);margin-top:5px;'+
        'line-height:1.45">'+
        (fillN>0
         ? 'Risque $'+fm(stake)+' &middot; un gain en enl&egrave;ve '+
           '<b style="color:var(--up-soft)">$'+fm(clears)+'</b>'
         : 'Taille normale. Encore $'+fm(stillNeed)+' pour miser plus.')+
       '</div>'+
      '</div>';
     lw.style.display='none';
     ls2.innerHTML=(bos&&!MAN()&&typeof d.ledger.cap_today!=='number')?
      'Pas de limite journali\u00e8re pendant le rattrapage.':'';
     lc.style.transition='box-shadow .8s,border-color .8s';
     lc.style.boxShadow=ok?'0 0 24px rgba(232,197,90,.3)':'';
     lc.style.borderColor=ok?'rgba(232,197,90,.55)':'#23405e';
     const rz=window._rz||{};
     const roll=(id,a,b,dec)=>{
      if(a===undefined||Math.abs(a-b)<0.005)return;
      const el=lc.querySelector('#'+id);if(!el)return;
      const t0=performance.now();
      const st=t=>{const k=Math.min(1,(t-t0)/600);
       el.textContent=(a+(b-a)*k).toFixed(dec===undefined?2:dec);
       if(k<1)requestAnimationFrame(st);};
      requestAnimationFrame(st);};
     const fl=(id,a,b,good)=>{
      if(a===undefined||Math.abs(a-b)<0.005)return;
      const el=lc.querySelector('#'+id);if(!el)return;
      el.style.transition='color .25s';
      el.style.color=good?'#2ecc71':'#ff5c5c';
      setTimeout(()=>{el.style.color='';},1100);};
     const bigV=bos?stake:nl;
     roll('rz-debt',rz.d,d.ledger.debt);
     fl('rz-debt',rz.d,d.ledger.debt,d.ledger.debt<rz.d);
     roll('rz-ammo',rz.a,am);
     fl('rz-ammo',rz.a,am,am>rz.a);
     roll('rz-lot',rz.m,bigV,bos?(stake<10?1:0):2);
     fl('rz-lot',rz.m,bigV,bigV>rz.m);
     window._rz={d:d.ledger.debt,a:am,m:bigV};
    }
   }else{
    // 2026-10-01 (owner): the last two emoji on the home screen. They
    // sat directly under cards using the stroked set, and the mismatch
    // got more visible once everything else was converted, not less.
    lt2.innerHTML='<span style="display:inline-flex;align-items:center;'+
     'gap:7px"><svg class="ic ic-s" style="color:var(--up)">'+
     '<use href="#i-check"/></svg>Tout va bien &mdash; rien &agrave; '+
     'rattraper.</span>'+(d.ledger.chest>0
     ?'<br><span style="display:inline-flex;align-items:center;gap:7px">'+
      '<svg class="ic ic-s" style="color:var(--warn)">'+
      '<use href="#i-lock"/></svg>Gard&eacute; pour les jours '+
      'difficiles : <b style="color:var(--warn)">$'+
      d.ledger.chest.toFixed(2)+'</b></span>':'');
    lw.style.display='none';ls2.innerHTML='';
   }
  }
  if(d.trial_days_left!==undefined){
   const tb=document.getElementById('trial');tb.style.display='block';
   tb.innerHTML='&#127873; Essai gratuit &mdash; <b>'+d.trial_days_left+
    ' jour'+(d.trial_days_left>1?'s':'')+' restant'+
    (d.trial_days_left>1?'s':'')+'</b>';}
  const f=(x)=>(x>=0?'+$':'-$')+Math.abs(x).toFixed(2);
  document.querySelectorAll('.skel').forEach(el=>
   el.classList.remove('skel'));
  const eqEl=document.getElementById('eq');
  const prevEq=parseFloat(eqEl.dataset.v||'NaN');
  if(isNaN(prevEq)||Math.abs(prevEq-d.equity)<0.005){
   eqEl.textContent='$'+d.equity.toFixed(2);}
  else{
   const from=prevEq,to=d.equity,t0=performance.now();
   eqEl.classList.remove('flash-up','flash-dn');void eqEl.offsetWidth;
   eqEl.classList.add(to>=from?'flash-up':'flash-dn');
   (function stepA(ts){const k=Math.min(1,(ts-t0)/500);
    eqEl.textContent='$'+(from+(to-from)*(1-Math.pow(1-k,3)))
     .toFixed(2);
    if(k<1)requestAnimationFrame(stepA);})(t0);
  }
  eqEl.dataset.v=d.equity;
  window._lastd=d;drawJourney(d);
  if(d.push_quiet!==undefined&&window._pquiet===undefined){
   window._pquiet=!!d.push_quiet;if(window.qPaint)window.qPaint();}
  if(d.push_level&&window._plvl===undefined){
   window._plvl=d.push_level;
   if(window.npcPaint)window.npcPaint();
  }
  if(d.eurusd){const _eqe=document.getElementById('eqe');
   _eqe.style.display='block';_eqe.innerHTML=
   '&asymp; '+(d.equity/d.eurusd).toFixed(0)+' &euro;';}
  // 2026-09-27: one line under the number - today's result and the trade
  // count; the closed balance is one tap on the running-trade pill
  window._bal=d.balance;
  (function(){const dl=document.getElementById('dayline');if(!dl)return;
   let h='';
   if(typeof d.today==='number'){const up=d.today>=0,z=Math.abs(d.today)<0.005;
    h+='<b style="color:'+(z?'rgba(219,233,247,.72)':up?'#8df0bb':'#ffb3b3')+'">'+
     (z?'$0.00':(up?'+$':'-$')+Math.abs(d.today).toFixed(2))+'</b> aujourd\u2019hui';}
   if(d.trades){const _td=new Date();
    const _k=String(_td.getUTCDate()).padStart(2,'0')+'/'+String(_td.getUTCMonth()+1).padStart(2,'0');
    const _n=d.trades.filter(x=>(x.w||'').startsWith(_k)).length;
    if(_n)h+=(h?'<span class="sep">\u00b7</span>':'')+_n+' trade'+(_n>1?'s':'');}
   setH(dl,h||'&nbsp;');})();
  const dtc=document.getElementById('daytargetchip');
  const _lg2=d.ledger||{};
  if(dtc){
   if(_lg2.bos&&typeof _lg2.cap_today==='number'){
    const _pnl=_lg2.day_pnl_bot||0,_cap=_lg2.cap_today;
    const _pct=Math.max(0,Math.min(100,_cap>0?(100*_pnl/_cap):0));
    const _done=!!_lg2.day_capped||_pnl>=_cap;
    dtc.style.display='inline-flex';dtc.style.alignItems='center';
    dtc.style.gap='7px';
    dtc.style.background=_done?'rgba(46,204,113,.22)':'rgba(255,255,255,.1)';
    dtc.style.color=_done?'var(--up-soft)':'#dbe9f7';
    const _off=(94.2*(1-_pct/100)).toFixed(1);
    // 2026-10-02 (owner): an empty ring at zero progress read as broken.
    // No ring until something is earned; the text says what the target is.
    const _ring=(_pct>0||_done)?('<svg width="16" height="16" viewBox="0 0 36 36" style="flex:none">'+
     '<circle cx="18" cy="18" r="15" fill="none" stroke="rgba(255,255,255,.18)" stroke-width="4"/>'+
     '<circle cx="18" cy="18" r="15" fill="none" stroke="'+(_done?'var(--up)':'var(--warn)')+
     '" stroke-width="4" stroke-linecap="round" stroke-dasharray="94.2" stroke-dashoffset="'+
     _off+'" transform="rotate(-90 18 18)"/></svg>'):'';
    dtc.innerHTML=_ring+
     (_done?'Objectif atteint \\u00b7 $'+_pnl.toFixed(2)
      :(_pct>0?'$'+_pnl.toFixed(2)+' / $'+_cap.toFixed(2)+' aujourd\\u2019hui'
              :'Objectif du jour \\u00b7 $'+_cap.toFixed(2)));
    if(_done){const _dk='owlDayDone:'+new Date().toISOString().slice(0,10)+':'+B;
     let _seen=false;try{_seen=!!localStorage.getItem(_dk);localStorage.setItem(_dk,'1');}catch(e){}
     if(!_seen){toast('<div class="evi" style="color:var(--up)"><svg class="ic ic-s"><use href="#i-check"/></svg></div>'+
      '<div style="flex:1">Objectif du jour atteint \\u00b7 <b class="pos">+$'+_pnl.toFixed(2)+'</b> \\u2014 le robot a fini sa journ\\u00e9e.</div>',7000);
      try{confetti();}catch(e){}}}
   }else{dtc.style.display='none';}   // "en rattrapage" lives on the rattrapage card now
  }
  if(d.build&&d.build!==APP_BUILD&&!window._newBuildShown){window._newBuildShown=true;
   toast('<div class="evi" style="color:var(--accent-soft)"><svg class="ic ic-s"><use href="#i-download"/></svg></div>'+
    '<div style="flex:1">Nouvelle version disponible</div>'+
    '<button class="shbtn shmain" style="width:auto;margin:0;padding:8px 12px;font-size:.82rem;min-height:0" '+
    'onclick="appRefresh()">Actualiser</button>',600000);}
  const _k0=(d.trades&&d.trades[0])?(d.trades[0].w+'|'+d.trades[0].p):'';
  if(window._lastTradeKey!==undefined&&_k0&&_k0!==window._lastTradeKey){
   const x=d.trades[0],up=x.p>=0;
   toast('<div class="evi" style="color:'+(up?'var(--up)':'var(--down)')+'"><svg class="ic ic-s">'+
    '<use href="#'+(up?'i-check':'i-x')+'"/></svg></div><div style="flex:1">Trade termin\u00e9 \u00b7 '+
    '<b class="'+(up?'pos':'neg')+'">'+(up?'+$':'-$')+Math.abs(x.p).toFixed(2)+'</b>'+
    (up?' \u2014 bien jou\u00e9.':T('toast_lost'))+'</div>');
   try{navigator.vibrate&&navigator.vibrate(up?[20,40,20]:[40])}catch(e){}}
  window._lastTradeKey=_k0;
  const _wc=document.getElementById('welcome');
  if(_wc)_wc.style.display=(!(d.trades||[]).length&&!(d.days||[]).length)?'block':'none';
  const _dbtNow=((d.ledger||{}).debt||0);
  if(window._prevDebt!==undefined&&window._prevDebt>0.5&&_dbtNow<=0.5){
   toast('<div class="evi" style="color:var(--up)"><svg class="ic ic-s"><use href="#i-check"/></svg></div>'+
    '<div style="flex:1">Rattrapage termin\\u00e9 \\u2014 '+T('toast_debt_done')+'</div>',8000);
   try{confetti();}catch(e){}}
  window._prevDebt=_dbtNow;
  const _tp=document.getElementById('tradepill'),_ol=d.open_list||[];
  if(_tp){if(_ol.length){const _pl=_ol.reduce((a,p)=>a+(parseFloat(p.pl)||0),0);
    _tp.style.display='inline-flex';
    _tp.innerHTML='<span class="dot" style="width:7px;height:7px;background:currentColor"></span>'+
     'Trade en cours \u00b7 '+(_pl>=0?'+$':'-$')+Math.abs(_pl).toFixed(2);
    _tp.style.background=_pl>=0?'rgba(46,204,113,.18)':'rgba(255,92,92,.18)';
    _tp.style.color=_pl>=0?'var(--up-soft)':'var(--down-soft)';}
   else _tp.style.display='none';}
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
   setH(document.getElementById('acctline'),
    '<i style="background:'+(d.real?'var(--up)':'var(--warn)')+'"></i>'+
    // 2026-10-03 (owner): the number is masked - its last three digits only
    (d.real?'R&Eacute;EL':'D&Eacute;MO')+' &middot; &bull;&bull;&bull;&bull;'+String(d.acct).slice(-3));
  }
  if(d.palier&&d.equity){
   const pb0=(d.palier_base&&d.palier_base<d.palier)
    ?d.palier_base:0;
   const pc=Math.max(0,Math.min(100,
    (d.equity-pb0)/(d.palier-pb0)*100));
   document.getElementById('palier').style.display='block';
   document.getElementById('palier-lbl').innerHTML=
    (d.palier_kind==='scale'
     ?'Prochain palier $'+d.palier.toFixed(0)+' &rarr; $'+
      d.palier_next_cap.toFixed(0)+'/jour'
     :d.palier_def
     ?'Objectif de la semaine : +$'+(d.palier_step||50).toFixed(0)
     :'Objectif : $'+d.palier.toFixed(0))+
    ' &middot; '+pc.toFixed(0)+'&nbsp;%';
   document.getElementById('palier-bar').style.width=pc+'%';
   const _gl=document.getElementById('grow-lot'),_lg3=d.ledger||{};
   if(_gl){const _lot=_lg3.scale_base_lot||_lg3.base_lot;
    _gl.textContent=(_lot?'Lot de base actuel : '+Number(_lot).toFixed(2)+' lot'
     +(_lg3.scale_active?' \\u00b7 mise \\u00e0 l\\u2019\\u00e9chelle active':''):'');}
   if(pc>=100&&!window._conf){window._conf=1;confetti();}
  }
  const n=d.open_positions;
  if(d.public){const db=document.getElementById('delbtn');
   if(db)db.style.display='none';}
  if(d.trading_paused!==undefined){
   isPaused=d.trading_paused;
   pauseLocked=!!d.pause_locked;
   document.getElementById('rob-sec').style.display='block';
   document.getElementById('rob-card').style.display='block';
   document.getElementById('pausebtn').style.display='flex';
   const lb=document.getElementById('pause-lbl');
   const ic=document.getElementById('pause-ic');
   const sb=document.getElementById('pause-sub');
   const cv=document.getElementById('pause-sw');
   // everyone sees the switch; only two accounts may use it
   ic.innerHTML=pauseLocked?SVGI('i-lock')
    :(isPaused?SVGI('i-pause'):SVGI('i-bot'));
   // Owner 2026-09-17: "en pause" meant nothing to read. On this account
   // the two states are MANUAL and AUTO, and the label names the state you
   // are IN, with the action underneath.
   // 2026-09-27: a paying member has NO robot on this VPS - "auto" for them
   // means following the MQL5 copy, so the words must say so
   const _pl=d.plan||{},_paid=!_pl.family&&!d.is_master;
   lb.innerHTML=isPaused
    ?(_paid?'Mode manuel \u00b7 signaux + outil':'Mode manuel')
    :'Trading automatique';
   lb.style.color=pauseLocked?'#6f8299':'';
   sb.textContent=pauseLocked
    ?(_pl.manual?'':(isPaused?'Le trading manuel est r\u00e9serv\u00e9 \u00e0 l\u2019administrateur.':'Le trading manuel est r\u00e9serv\u00e9 \u00e0 l\u2019administrateur.'))
    :(_paid
      ?(isPaused?'Vous tradez vous-m\u00eame avec les signaux.'
        :'Rien ne tourne ici : le robot ne trade pas sur ce compte.')
      :(isPaused
        ?'Le robot n\u2019entre pas seul. Touchez pour le lancer.'
        :'Le robot entre seul. Touchez pour repasser en manuel.'));
   cv.classList.toggle('on',!isPaused);cv.style.opacity=pauseLocked?'.35':'';
   document.getElementById('pausebtn').style.opacity=
    pauseLocked?'.6':'';
  }
  // 2026-09-24: the balance-scaling opt in/out. Shown for every account
  // running its own structure bot (not only the two pause-capable ones
  // above), independent of the pause switch.
  const _lg3=d.ledger||{};
  if(_lg3.bos&&_lg3.scale_can_toggle){
   document.getElementById('rob-sec').style.display='block';
   document.getElementById('rob-card').style.display='block';
   document.getElementById('scalebtn').style.display='flex';
   window._scaleOn=!_lg3.scale_opt_out;
   {const _ss=document.getElementById('scale-sw');if(_ss)_ss.classList.toggle('on',!!window._scaleOn);}
   const _capTxt=(typeof _lg3.scale_base_cap==='number')
    ?'$'+_lg3.scale_base_cap.toFixed(2)+'/jour fixe'
    :'la taille fixe';
   document.getElementById('scale-sub').innerHTML=window._scaleOn
    ?'Activ&eacute;e (par d&eacute;faut) &mdash; le lot et la cible du '+
     'jour suivent le solde. Toucher pour revenir &agrave; '+_capTxt+'.'
    :'D&eacute;sactiv&eacute;e &mdash; '+_capTxt+', quel que soit le '+
     'solde. Toucher pour activer la mise &agrave; l&#39;&eacute;chelle.';
  }
  // 2026-09-27: the activation code is for the owner's circle - never a
  // prompt on the home; a discreet link under the plan card shows the box
  document.getElementById('actcard').style.display=
   (window._showAct||d.family_expired)?'block':'none';   // 2026-09-28: stays once opened
  (function(){const t=document.querySelector('#actcard .lbl'),x=document.querySelector('#actcard div[style*="line-height:1.5"]');if(!t||!x)return;
   if(d.family_expired){t.textContent='Renouveler l\u2019acc\u00e8s';x.innerHTML='Votre acc\u00e8s Automatique a expir\u00e9 le <b>'+d.family_expired+'</b>. Le robot est en pause sur votre compte. R\u00e9glez le Owl, puis entrez le code re\u00e7u :';}
   else{t.textContent='Activer le robot';x.innerHTML='Votre compte est connect\u00e9. Il reste un code \u00e0 entrer : demandez-le \u00e0 <b>le Owl sur Telegram</b>.';}})();
  document.getElementById('adminlock-sec').style.display=
   d.is_master?'none':'block';
  document.getElementById('adminlock-card').style.display=
   d.is_master?'none':'block';
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
   ? '<svg class="ic ic-s" style="vertical-align:-3px;margin-right:5px"><use href="#i-pause"/></svg>'+T('st_manual')+
     (n>0?' &middot; '+n+' trade'+(n>1?'s':'')+' ouvert'+(n>1?'s':''):'')
   : (d.bot_killed
   ? '<svg class="ic ic-s" style="vertical-align:-3px;margin-right:5px"><use href="#i-stop"/></svg><b>'+T('st_killed')+'</b>'
   : n>0
   ? '<svg class="ic ic-s" style="vertical-align:-3px;margin-right:5px"><use href="#i-bot"/></svg>Le robot travaille &mdash; <b>'+n+' trade'+(n>1?'s':'')+
     ' en cours</b>'
   : '<svg class="ic ic-s" style="vertical-align:-3px;margin-right:5px"><use href="#i-eye"/></svg>March&eacute; sous surveillance &mdash; aucun trade ouvert');
  const bs=document.getElementById('battles-sec');
  const met=document.getElementById('meteo');
  const lc0=document.getElementById('ledcard');
  if(d.open_list&&d.open_list.length){
   // 2026-09-29 (owner): the weather card and its nervosity gauge stay
   // visible while a trade is open - they live in the Marche space now
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
      'background:var(--muted2)"></div>'+
      '<div style="position:absolute;top:-3px;left:calc('+
      cp.toFixed(1)+'% - 6px);width:12px;height:12px;'+
      'border-radius:50%;background:'+col+';box-shadow:0 0 8px '+col+
      '"></div></div>'+
      '<div style="display:flex;justify-content:space-between;'+
      'margin:-8px 4px 8px;font-size:.6rem;color:var(--muted)">'+
      '<span>mur</span><span>cible</span></div>';
    }
    return '<div class="row" style="border-bottom-color:var(--surface3);'+
    'border-bottom:0">'+
    '<span style="display:flex;align-items:center;gap:8px">'+
    (x.d=='A'?'<span style="color:var(--up)">&#9650;</span> <b>Achat</b>'
     :'<span style="color:var(--down)">&#9660;</span> <b>Vente</b>')+
    ' <span style="color:var(--muted);font-size:.85rem">'+
    (x.sl>0
     ?(m=>'mise $'+(m<10?m.toFixed(1):m.toFixed(0))+
       ' <span style="font-size:.72rem;color:#51687e">('+
       x.lot.toFixed(2)+' lot)</span>')(Math.abs(x.e-x.sl)*x.lot)
     :x.lot.toFixed(2)+' lot')+
    '</span>'+(x.k=='s'?' <span style="background:'+
    'rgba(232,197,90,.15);color:var(--warn);padding:2px 8px;'+
    'border-radius:99px;font-size:.68rem;font-weight:700">'+
    'soldat</span>':'')+
    '</span><b style="font-size:1.12rem" class="'+
    (sgn(x.pl))+'">'+
    (x.pl>=0?'+$':'-$')+Math.abs(x.pl).toFixed(2)+'</b></div>'+bar;
   }).join('');
  }else{bs.style.display='none';met.style.display='block';
   if(lc0)lc0.style.marginTop='12px';}
  const t=document.getElementById('today');
  t.innerHTML=f(d.today);
  t.className='val '+(sgn(d.today));
  const w=document.getElementById('week');
  w.innerHTML=f(d.week);   // 2026-10-02: the colour carries the sign; no glyph
  w.className='val '+(sgn(d.week));
  const dv=d.max_dd_7d.toFixed(0);
  document.getElementById('dd').textContent=(dv==0?'$0':'-$'+dv);
  ddCap(d);
  // 2026-10-01: a one-day-old month next to a seven-day week is not a
  // comparison, and the tiles sit side by side. Say so while it matters.
  {const ms=document.getElementById('monthsub');
   if(ms){const dn=new Date().getUTCDate();const en=LANG()==='en';
    ms.textContent=(dn<=4
     ?(en?'since the 1st \u00b7 day '+dn:'depuis le 1er \u00b7 jour '+dn)
     :(en?'since the 1st':'depuis le 1er'));}}
  if(d.month!==undefined){
   const mo=document.getElementById('month');
   mo.innerHTML=f(d.month);
   mo.className='val '+(sgn(d.month));
  }
  window._c7=d.curve||[];window._c30=d.curve30||[];
  // 2026-09-27: 3-month curve built from the worker's day-by-day months
  (function(){const M=d.months||{};
   const ds=[].concat(...Object.keys(M).sort().map(k=>M[k]||[])).sort((a,b)=>a.d<b.d?-1:1);
   let c=0;window._c90=ds.map(x=>{c+=(x.p||0);return Math.round(c*100)/100;});})();
  // 2026-09-27: a reset (new era_start) clears this phone's own marks too
  if(d.era_start){let prev=null;try{prev=localStorage.getItem('owlEra:'+B);}catch(e){}
   if(prev&&prev!==d.era_start){['owlBadges:'+B,'owlInboxSeen:'+B,'owlWeekImg:'+B].forEach(k=>{try{localStorage.removeItem(k);}catch(e){}});
    Object.keys(localStorage||{}).filter(k=>k.indexOf('owlDayDone:')===0).forEach(k=>{try{localStorage.removeItem(k);}catch(e){}});
    window._badges=null;toast('<div class="evi" style="color:var(--accent-soft)"><svg class="ic ic-s"><use href="#i-activity"/></svg></div><div style="flex:1">'+(LANG()==='en'?'Fresh start \u2014 the history restarts from today.':'Nouveau d\u00e9part \u2014 l\u2019historique repart d\u2019aujourd\u2019hui.')+'</div>',6000);}
   try{localStorage.setItem('owlEra:'+B,d.era_start);}catch(e){}}
  (function(){const cr=document.getElementById('contactrow');if(!cr)return;
   if(d.contact_url){cr.style.display='flex';cr.href=d.contact_url;if(d.contact_label)document.getElementById('contact-lbl').textContent=d.contact_label;}
   else cr.style.display='none';
   const cs=document.getElementById('contactcfg-sub');if(cs&&d.contact_url)cs.textContent=d.contact_url;
   const ps=document.getElementById('paycfg-sub'),P=d.plan||{};
   if(ps&&d.is_master)ps.textContent=(P.np_key_tail?'Cl\u00e9 API \u2026'+P.np_key_tail:'Cl\u00e9 API : non d\u00e9finie')+' \u00b7 secret IPN '+(P.np_secret_set?'\u2713':'\u2717')+(P.np_sandbox?' \u00b7 sandbox':'')+(P.mql5_url?' \u00b7 MQL5 \u2713':'');})();
  (function(){const P=d.plan;if(!P)return;const cur=P.family?'family':P.strategy?'strategy':P.manual?'manual':'none';
   let prev=null;try{prev=localStorage.getItem('owlPlan:'+B);}catch(e){}
   if(prev&&prev!==cur&&cur!=='none'){const en=LANG()==='en';const lab=cur==='strategy'?(en?'Strategy':'Strat\u00e9gie'):cur==='manual'?'Signal':'Famille';
    toast('<div class="evi" style="color:var(--up)"><svg class="ic ic-s"><use href="#i-check"/></svg></div><div style="flex:1">'+(en?'Subscription active: <b>'+lab+'</b>. Settings \u203a The robot \u203a Manual mode to start.':'Abonnement activ\u00e9 : <b>'+lab+'</b>. R\u00e9glages \u203a Le robot \u203a Mode manuel pour commencer.')+'</div>',9000);
    try{confetti();}catch(e){}}
   try{localStorage.setItem('owlPlan:'+B,cur);}catch(e){}})();
  try{tfPaint(d);}catch(e){}
  drawSpark();drawGoal(d);renderSince(d);checkBadges(d);renderMvM(d);renderTimeline(d);renderEmpty(d);dayDone(d);whyIdle(d);acctRules(d);showRecap(d);tfPayoff(d);renderPlan(d);observerView(d);loadProof(d);pollSignal();renewBanner(d);noPushBanner(d);newsCard(d);missedCard(d);renderRevenue(d);loadSignals();loadCompare(d);renderNext(d);loadWhy(d);loadJournal(d);loadMarketHours(d);loadPatterns(d);(function(){const sg=document.getElementById('mxs-lab');if(sg)sg.style.display=labVisible()?'':'none';if(document.getElementById('mx-lab')&&document.getElementById('mx-lab').style.display!=='none')loadLab(d);})();
  if(d.is_master&&d.nest){
   // Owner 2026-09-18: remember the ADMIN's own base path in this
   // browser. Switching into another account makes every page speak with
   // that account's token, so the chart of any account uses this to call
   // the emergency stop as the admin. The route still checks is_admin and
   // still demands the master password - nothing here grants anything.
   try{localStorage.setItem('owl_adm',B);}catch(e){}
   document.getElementById('tb-nid').style.display='flex';
   window._nest=d.nest;
   (function(){const hr=document.getElementById('healthrow');if(hr)hr.style.display='flex';})();
   (function(){const ch=document.getElementById('acctchip');if(!ch)return;ch.style.display='inline-flex';
    document.getElementById('acctchip-n').textContent=d.nest.length;})();
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
   // 2026-10-01 (owner): real money only. A missing flag counts as
   // NOT real - a total that quietly includes an unknown is the bug
   // being fixed here.
   const _rl=d.nest.filter(x=>x.real===true);
   const tb=_rl.reduce((a,x)=>a+(x.bal||0),0);
   const tt=_rl.reduce((a,x)=>a+(x.today||0),0);
   const _dm=d.nest.length-_rl.length;
   // 2026-09-27: alerts strip + family week bars above the list
   const _al=d.nest.filter(x=>!x.observer&&(x.err||x.stale||(x.bot&&!x.botlive)||x.blocked)||(x.family_until&&x.family_until-Date.now()/1000<5*86400));
   const _man=d.nest.filter(x=>!x.bot&&x.paused).length;
   const _alh=_al.length
    ?'<div style="display:flex;align-items:flex-start;gap:10px;padding:10px 12px;border-radius:12px;'+
     'background:rgba(232,197,90,.08);border:1px solid rgba(232,197,90,.28);margin-bottom:10px">'+
     '<div class="evi" style="color:var(--warn);flex:none"><svg class="ic ic-s"><use href="#i-cloud"/></svg></div>'+
     '<div style="flex:1;min-width:0;font-size:.86rem;line-height:1.4"><b>'+_al.length+' compte'+(_al.length>1?'s':'')+' &agrave; surveiller</b><br>'+
     '<span style="color:var(--muted2)">'+_al.map(x=>x.name+' \u00b7 '+(x.err?'probl\u00e8me':x.stale?'hors ligne':x.blocked?x.blocked:(x.bot&&!x.botlive)?'robot arr\u00eat\u00e9':(x.family_until-Date.now()/1000<=0?'acc\u00e8s expir\u00e9':'expire dans '+Math.max(0,Math.ceil((x.family_until-Date.now()/1000)/86400))+' j'))).join(' \u00b7 ')+'</span></div></div>'
    :'<div style="display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:12px;'+
     'background:rgba(46,204,113,.07);border:1px solid rgba(46,204,113,.22);margin-bottom:10px;font-size:.86rem">'+
     '<div class="evi" style="color:var(--up);flex:none"><svg class="ic ic-s"><use href="#i-check"/></svg></div>'+
     '<div>Tout roule \u00b7 '+d.nest.filter(x=>x.bot&&x.botlive&&!x.paused).length+' robot'+(d.nest.filter(x=>x.bot&&x.botlive&&!x.paused).length>1?'s':'')+' actif'+(d.nest.filter(x=>x.bot&&x.botlive&&!x.paused).length>1?'s':'')+(_man?' \u00b7 '+_man+' en manuel':'')+'</div></div>';
   const _fam={};d.nest.forEach(x=>(x.days||[]).forEach(y=>{_fam[y.d]=(_fam[y.d]||0)+(y.p||0);}));
   const _pd=k=>{const m=/(\d\d)\/(\d\d)$/.exec(k||'');return m?(parseInt(m[2])*100+parseInt(m[1])):0;};
   const _fk=Object.keys(_fam).sort((a,b)=>_pd(a)-_pd(b)).slice(-7);
   const _fmx=Math.max(1,..._fk.map(k=>Math.abs(_fam[k])));
   const _famh=_fk.length?'<div style="padding:8px 4px 12px"><div class="lbl">Famille \u00b7 7 jours</div>'+
    '<svg viewBox="0 0 300 70" style="width:100%;height:70px;display:block;margin-top:6px">'+
    '<line x1="6" y1="40" x2="294" y2="40" style="stroke:var(--border2)"/>'+
    _fk.map((k,i)=>{const v=_fam[k],h=Math.max(2,Math.abs(v)/_fmx*30),x=6+i*(288/_fk.length)+6,w=288/_fk.length-12;
     return '<rect x="'+x.toFixed(1)+'" y="'+(v>=0?40-h:40).toFixed(1)+'" width="'+w.toFixed(1)+'" height="'+h.toFixed(1)+'" rx="3" style="fill:'+(v>=0?'var(--up)':'var(--down)')+';opacity:.85"/>'+
      '<text x="'+(x+w/2).toFixed(1)+'" y="64" text-anchor="middle" font-size="8" style="fill:var(--muted)">'+k.slice(-5)+'</text>';}).join('')+'</svg></div>':'';
   // 2026-10-01: the day line for one row, and the family tally.
   const _dn=d.nest.filter(x=>x.day&&x.day.done).length;
   const _dt=d.nest.filter(x=>x.day).length;
   const _dayh=_dt?('<div class="row" style="border-bottom:1px solid '+
    '#24344a"><span style="color:var(--muted2);font-size:.82rem">'+
    'Journ\u00e9e</span><span style="font-size:.82rem;color:'+
    (_dn>=_dt?'var(--up-soft)':'var(--muted2)')+'">'+
    (_dn>=_dt?'\u2713 tous ont fini \u00b7 '+_dn+'/'+_dt
     :_dn+'/'+_dt+' ont fini leur journ\u00e9e')+'</span></div>'):'';
   const hdr=_alh+_famh+'<div class="row" style="border-bottom:2px solid '+
    '#24344a"><span><b>Total famille</b> <span style="'+
    'color:var(--muted);font-size:.75rem">'+_rl.length+
    ' compte'+(_rl.length>1?'s':'')+' r\u00e9el'+(_rl.length>1?'s':'')+
    (_dm?' <span style="color:#5f7185">(+'+_dm+' d\u00e9mo non '+
     'compt\u00e9'+(_dm>1?'s':'')+')</span>':'')+'</span></span>'+
    '<span style="text-align:right"><b>$'+tb.toFixed(2)+'</b>'+
    '<span style="display:block;font-size:.78rem" class="'+
    (sgn(tt))+'">auj. '+(tt>=0?'+$':'-$')+
    Math.abs(tt).toFixed(2)+'</span></span></div>'+_dayh;
   document.getElementById('nest').innerHTML=hdr+d.nest.map(x=>{
    // Owner 2026-09-18: the list showed people's names and their plan, so
    // it could not answer "what is still running here". Now each row says
    // which ROBOT holds the account and whether that robot is alive - an
    // account with no robot says so instead of pretending to be paused.
    // The plan is gone: it is billing, not state.
    const noBot=!x.bot;
    const dot=noBot?'#4a5a6b'
     :(x.err||x.stale?'#e6a028':(x.paused?'#8fa1b3':'#2ecc71'));
    const st=noBot?'aucun robot'
     :(x.err?'probl&egrave;me':(x.stale?'hors ligne'
     :(!x.botlive?'robot arr&ecirc;t&eacute;'
     :(x.blocked?x.blocked
     :(x.paused?'en pause':'actif')))));
    const stc=noBot?'#5f7185'
     :(x.err||!x.botlive||x.blocked?'#ffb3b3'
     :(x.paused?'#8fa1b3':'#8df0bb'));
    // Owner 2026-09-18: leading with the robot hid the owner's own
    // accounts - "where is Valere?" - because the person's name had been
    // demoted to small grey text. The NAME is what you scan for, so it
    // leads again; the robot and the account number sit under it, which
    // still answers "what is running here" without stealing the anchor.
    // 2026-10-01 (owner): three bands, not one squeezed flex. The name
    // and the balance share a baseline so the money reads as a column
    // down the list; the robot/account string is the one allowed to
    // truncate; the day state and the ceiling are chips, which wrap
    // instead of shoving the layout about; and the actions sit at the end
    // of the chip line, small and quiet.
    const esc=t=>String(t).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
    const chips=[];
    // the status word only when it is NOT the ordinary case - a green dot
    // already says "actif", and saying it on every row was noise
    if(st!=='actif')chips.push('<span class="nchip '+
     (noBot||x.paused?'':(x.err||!x.botlive||x.blocked?'nchip-b':'nchip-w'))+
     '">'+st+'</span>');
    chips.push(...dayChips(x));
    return '<div class="nrow">'+
    '<div class="nr-l">'+
    '<span style="display:inline-block;width:8px;height:8px;flex:none;'+
    'border-radius:50%;background:'+dot+'"></span>'+
    '<span class="nr-nm">'+x.name+'</span>'+
    '<span class="nr-bal">'+(x.bal!=null?'$'+x.bal.toFixed(2):'--')+
    '</span></div>'+
    '<div class="nr-l" style="margin-top:2px">'+
    '<span class="nr-mt" style="padding-left:18px">'+
    (x.bot?x.bot:'&#8212;')+
    (x.login?' &middot; '+x.login:'')+
    (x.seen?' &middot; '+agoTxt(x.seen).replace(/^vu /,''):'')+'</span>'+
    (x.today!=null?'<span class="nr-td '+(sgn(x.today))+'">'+
     (x.today>=0?'+$':'-$')+Math.abs(x.today).toFixed(2)+'</span>':'')+
    '</div>'+
    (x.note?'<div style="font-size:.72rem;color:var(--warn);'+
     'margin:6px 0 0 18px;line-height:1.4">\u270e '+esc(x.note)+'</div>':'')+
    '<div class="nr-b">'+chips.join('')+
    '<span class="nr-a">'+
    // the app's own stroked icons, not emoji: the row reads as
    // typography and should not end in four multi-coloured pictograms
    // that outshout the numbers. Danger is still red - by border and
    // colour, which is enough.
    (x.tok?'<a class="nact" href="/'+x.tok+'/" target="_blank" '+
     'title="Ouvrir ce compte" aria-label="Ouvrir ce compte">'+
     '<svg class="ic ic-s"><use href="#i-eye"/></svg></a>':'')+
    (x.trade?'<button class="nact" data-u="'+x.id+'" data-o="'+
     (x.paused?0:1)+'" onclick="nestPause(this.dataset.u,this.dataset.o)" '+
     'title="'+(x.paused?'Reprendre':'Mettre en pause')+'" '+
     'aria-label="'+(x.paused?'Reprendre':'Mettre en pause')+'">'+
     '<svg class="ic ic-s"><use href="#'+(x.paused?'i-bot':'i-pause')+
     '"/></svg></button>':'')+
    '<button class="nact nact-b" data-u="'+x.id+'" data-n="'+x.name+
    '" onclick="nestPanic(this.dataset.u,this.dataset.n)" '+
    'title="Arret d&rsquo;urgence : tout fermer sur ce compte" '+
    'aria-label="Arret d urgence">'+
    '<svg class="ic ic-s"><use href="#i-stop"/></svg>'+
    (x.pos?'<span style="margin-left:4px;font-size:.72rem;'+
     'font-weight:700">'+x.pos+'</span>':'')+'</button>'+
    (x.bot?'<button class="nact" data-u="'+x.id+'" data-n="'+x.name+
     '" onclick="nestReset(this.dataset.u,this.dataset.n)" '+
     'title="R&eacute;initialiser : le robot repart de z&eacute;ro" '+
     'aria-label="Reinitialiser">'+
     '<svg class="ic ic-s"><use href="#i-reset"/></svg></button>':'')+
    '</span></div></div>';
   }).join('');
  }
  if(d.days&&!d.days.length){
   const de=document.getElementById('days');de.style.display='block';
   de.innerHTML='<div class="empty"><i><img src="icon192.png" alt="" style="width:34px;height:34px;border-radius:9px;opacity:.85"></i>'+
    '<p>Le hibou surveille la mer &mdash; vos journ&eacute;es '+
    'appara&icirc;tront ici</p></div>';
  }
  if(d.days&&d.days.length){
   const de=document.getElementById('days');de.style.display='block';
   window._dtr=d.day_trades||{};window._days=d.days;
   const _wkc=document.getElementById('weekcard'),_wks=document.getElementById('week-sum');
   if(_wkc&&_wks){const _n=new Date();const _mon=new Date(_n);
    _mon.setDate(_n.getDate()-((_n.getDay()+6)%7));_mon.setHours(0,0,0,0);
    let _g=0,_r=0;d.days.forEach(x=>{const m=/(\d\d)\/(\d\d)$/.exec(x.d||'');if(!m)return;
     const dt=new Date(_n.getFullYear(),parseInt(m[2])-1,parseInt(m[1]));
     if(dt>_n)dt.setFullYear(dt.getFullYear()-1);
     if(dt>=_mon){if(x.p>0.005)_g++;else if(x.p<-0.005)_r++;}});
    const wk=d.week||0,_dbt=((d.ledger||{}).debt||0)>0.5;
    _wks.innerHTML='Cette semaine : <b class="'+sgn(wk)+'">'+(wk>=0?'+$':'-$')+Math.abs(wk).toFixed(2)+
     '</b>'+((_g||_r)?' \u2014 '+_g+' jour'+(_g>1?'s':'')+' vert'+(_g>1?'s':'')+', '+_r+' rouge'+(_r>1?'s':''):'')+
     '. '+(wk>=0?T('wk_up'):(_dbt?T('wk_debt'):T('wk_down')));
    _wkc.style.display='block';setTimeout(weekUpload,1500);}
   de.innerHTML=d.days.map(x=>{
    const tr=window._dtr[x.d]||[];
    const open=false;   // 2026-09-26: a day opens as a story sheet
    return '<div class="row" style="cursor:pointer;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none" data-l="'+x.d+
    '" onclick="dayx(this.dataset.l)" onpointerdown="lpDayStart(event,this.dataset.l)" onpointerup="lpEnd()" onpointercancel="lpEnd()" onpointerleave="lpEnd()" oncontextmenu="return false"><span class="rowt">'+
    (tr.length?'<svg class="ic ic-s" style="vertical-align:-3px;margin-right:5px;'+
     'color:var(--muted);transform:rotate('+(open?'90':'0')+'deg)">'+
     '<use href="#i-chev"/></svg>':'<span style="display:inline-block;width:21px"></span>')+x.d+
    '</span><b class="'+(sgn(x.p))+'">'+
    (x.p>=0?'+$':'-$')+Math.abs(x.p).toFixed(2)+'</b></div>'+
    (open?'<div style="padding:0 0 6px 18px;border-bottom:1px solid '+
    'var(--border)">'+tr.map(t=>'<div class="row" style="font-size:.85rem;'+
    'padding:6px 4px;border-bottom:0"><span class="rowt">'+t.t+
    '</span><span class="'+(sgn(t.p))+'">'+
    (t.p>=0?'+$':'-$')+Math.abs(t.p).toFixed(2)+'</span></div>')
    .join('')+'</div>':'');
   }).join('');
  }
  if(d.month_days&&d.month_days.length){
   const _off=window._calOff||0,_n0=new Date();
   const _bm=new Date(Date.UTC(_n0.getUTCFullYear(),_n0.getUTCMonth()-_off,1));
   const _ym=_bm.getUTCFullYear()+'-'+String(_bm.getUTCMonth()+1).padStart(2,'0');
   const _src=(_off===0)?d.month_days:(((d.months||{})[_ym])||[]);
   const _MN=['janvier','f\u00e9vrier','mars','avril','mai','juin','juillet','ao\u00fbt',
    'septembre','octobre','novembre','d\u00e9cembre'];
   const _cy=document.getElementById('cal-ym');
   if(_cy)_cy.textContent=_MN[_bm.getUTCMonth()]+' '+_bm.getUTCFullYear();
   const _cp=document.getElementById('cal-prev'),_cn=document.getElementById('cal-next');
   if(_cp)_cp.style.visibility=(_off>=2)?'hidden':'visible';
   if(_cn)_cn.style.visibility=(_off<=0)?'hidden':'visible';
   const vals=_src.length?_src.map(x=>x.p):[0];
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
    cell(_off?'Net du mois':'Net du mois',f(net),sgn(net),_off?_MN[_bm.getUTCMonth()]:'depuis le 1er')+
    cell('Jours','<span class="pos">'+g+'</span> / <span class="neg">'+
     rr+'</span>','neu','verts / rouges')+
    cell('Meilleur jour',f(best),'pos','le plus gagnant')+
    cell('Pire jour',f(worst),sgn(worst),'le plus dur'));
   window._mrep={ym:_ym,name:_MN[_bm.getUTCMonth()]+' '+_bm.getUTCFullYear(),net:net,g:g,rr:rr,
    best:best,worst:worst,src:_src,stats:((d.month_stats||{})[_ym])||null,
    debt:((d.ledger||{}).debt||0)>0.5};
   const _mv=document.getElementById('msum-verdict');
   if(_mv){const _dbt=((d.ledger||{}).debt||0)>0.5;_mv.style.display='block';
    _mv.innerHTML=(_off?'En '+_MN[_bm.getUTCMonth()]+' : ':'Ce mois : ')+'<b class="'+sgn(net)+'">'+f(net)+'</b>, '+g+' jour'+(g>1?'s':'')+
     ' vert'+(g>1?'s':'')+' sur '+(g+rr)+'. '+(net>=0?'Le robot avance.'
     :(_dbt?'Le robot est en train de se rattraper \u2014 il avance prudemment.'
     :'Un mois difficile ; le robot continue.'));}
   const md={};_src.forEach(x=>md[x.d]=x.p);
   const now=new Date();
   const y=_bm.getUTCFullYear(),m=_bm.getUTCMonth();
   const nd=new Date(Date.UTC(y,m+1,0)).getUTCDate();
   const off=(new Date(Date.UTC(y,m,1)).getUTCDay()+6)%7;
   const _bv=[];for(let q=1;q<=nd;q++){const kk=y+'-'+String(m+1).padStart(2,'0')+
    '-'+String(q).padStart(2,'0');_bv.push([kk,md[kk],
    ['dim','lun','mar','mer','jeu','ven','sam'][new Date(kk+'T00:00:00Z').getUTCDay()]+' '+
    String(q).padStart(2,'0')+'/'+String(m+1).padStart(2,'0')]);}
   const _mx=Math.max(1,..._bv.map(x=>Math.abs(x[1]||0)));const _bw=300/nd;
   let h='<svg viewBox="0 0 300 64" style="width:100%;height:64px;display:block;'+
    'margin:2px 0 10px"><line x1="0" y1="32" x2="300" y2="32" '+
    'stroke="rgba(128,128,128,.3)" stroke-width="1"/>'+
    _bv.map((x,i)=>{const v=x[1];if(v===undefined||Math.abs(v)<0.005)return '';
     const hh=Math.max(2,Math.abs(v)/_mx*28),yy=v>0?32-hh:32;
     return '<rect x="'+(i*_bw+_bw*0.2).toFixed(1)+'" y="'+yy.toFixed(1)+'" width="'+
      (_bw*0.6).toFixed(1)+'" height="'+hh.toFixed(1)+'" rx="1.5" style="fill:var(--'+
      (v>0?'up':'down')+');cursor:pointer" onclick="dayx(\\''+x[2]+'\\')"><title>'+
      x[0]+' '+(v>=0?'+$':'-$')+Math.abs(v).toFixed(2)+'</title></rect>';}).join('')+
    '</svg><div style="display:grid;'+
    'grid-template-columns:repeat(7,1fr);gap:6px">';
   ['L','M','M','J','V','S','D'].forEach(w=>h+=
    '<div style="text-align:center;font-size:.62rem;'+
    'color:var(--muted)">'+w+'</div>');
   for(let i=0;i<off;i++)h+='<div></div>';
   for(let dd2=1;dd2<=nd;dd2++){
    const k=y+'-'+String(m+1).padStart(2,'0')+'-'+
     String(dd2).padStart(2,'0');
    const p=md[k];let bg='transparent',fg='var(--muted)',
     bd='var(--tile-bd)';
    if(p!==undefined){
     if(p>0.005){bg='rgba(46,204,113,'+
      Math.min(.42,.14+p/12).toFixed(2)+')';fg='var(--up-soft)';
      bd='rgba(46,204,113,.35)';}
     else if(p<-0.005){bg='rgba(255,92,92,'+
      Math.min(.42,.14-p/12).toFixed(2)+')';fg='var(--down-soft)';
      bd='rgba(255,92,92,.35)';}
     else{bg='var(--tile-bg)';fg='var(--muted2)';bd='var(--tile-bd)';}
    }
    const isT=(_off===0&&dd2===now.getUTCDate());
    const _lab=['dim','lun','mar','mer','jeu','ven','sam'][new Date(k+'T00:00:00Z').getUTCDay()]+
     ' '+String(dd2).padStart(2,'0')+'/'+String(m+1).padStart(2,'0');
    h+='<div'+(p!==undefined?' onclick="dayx(\\''+_lab+'\\')" onpointerdown="lpDayStart(event,\\''+_lab+'\\')" onpointerup="lpEnd()" onpointercancel="lpEnd()" onpointerleave="lpEnd()" oncontextmenu="return false" role="button"':'')+
     ' style="cursor:'+(p!==undefined?'pointer':'default')+';aspect-ratio:1;border-radius:10px;background:'+bg+
     ';border:1px solid '+bd+
     (isT?';box-shadow:inset 0 0 0 1.5px var(--accent-soft)':'')+
     ';display:flex;align-items:center;justify-content:center;'+
     'font-size:.72rem;font-weight:600;color:'+fg+'" title="'+
     (p===undefined?'':((p>=0?'+$':'-$')+Math.abs(p).toFixed(2)))+
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
    SR('Gain moyen','+$'+(sw/Math.max(1,W.length)).toFixed(2),
     'pos')+
    SR('Perte moyenne','-$'+(slo/Math.max(1,Lo.length)).toFixed(2),
     'neg')+
    SR('Gains / pertes',slo>0?(sw/slo).toFixed(2):'&#8734;',
     sw>=slo?'pos':'neg')+
    SR('Meilleure s&eacute;rie',bs+' gains de suite','pos'));
  }
  if(d.trades&&!d.trades.length){
   document.getElementById('hist').innerHTML=
    '<div class="empty"><i><img src="icon192.png" alt="" style="width:34px;height:34px;border-radius:9px;opacity:.85"></i>'+
    '<p>Aucun trade encore &mdash; le hibou attend la bonne '+
    'vague</p></div>';
  }
  if(d.trades&&d.trades.length){
   window._tr=d.trades;
   const N=window._trN||10;
   // 2026-09-27: filter chips (Tous / Gagnes / Perdus / Cette semaine);
   // data-i stays the index in d.trades so tradeSheet() keeps working.
   const F=window._trF||'all';
   const wk=(()=>{const n=new Date();const m=new Date(Date.UTC(n.getUTCFullYear(),n.getUTCMonth(),n.getUTCDate()));
    m.setUTCDate(m.getUTCDate()-((m.getUTCDay()+6)%7));return m.getTime();})();
   const inWeek=x=>{const m=/^(\d\d)\/(\d\d)/.exec(x.w||'');if(!m)return false;const n=new Date();
    let y=n.getUTCFullYear();if(parseInt(m[2],10)-1>n.getUTCMonth())y--;
    return Date.UTC(y,parseInt(m[2],10)-1,parseInt(m[1],10))>=wk;};
   const L=d.trades.map((x,i)=>[x,i]).filter(([x])=>F==='won'?x.p>0.005:F==='lost'?x.p<-0.005:F==='week'?inWeek(x):true);
   setH(document.getElementById('hist'),
    (L.length?'':'<div class="empty"><p>Aucun trade dans cette s\u00e9lection</p></div>')+
    L.slice(0,N).map(([x,i])=>
    '<div class="row" style="cursor:pointer;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none" data-i="'+i+
    '" onclick="tradeSheet(this.dataset.i)" onpointerdown="lpStart(event,this)" onpointerup="lpEnd()" onpointercancel="lpEnd()" onpointerleave="lpEnd()" oncontextmenu="return false"><span class="rowt">'+x.w+
    (x.k==='soldat'?' <span class="pill pill-w">soldat</span>'
     :(x.k&&x.k!=='page'?' <span class="pill">'+x.k+'</span>':''))+
    (x.dur!=null?' &middot; '+fdur(x.dur):'')+
    tfDots(x)+
    '</span><b class="'+
    (sgn(x.p))+'">'+(x.p>=0?'+$':'-$')+Math.abs(x.p).toFixed(2)+
    '</b></div>').join('')+
    (L.length>N
    ?'<div class="row" style="cursor:pointer;justify-content:center;'+
     'color:var(--accent-soft);font-size:.9rem" onclick="window._trN=99;render(window._d)">'+
     'Voir plus ('+L.length+')</div>':''));
  }
}
async function load(){
 try{
  const r=await fetch(B+'api?t='+Date.now(),{cache:'no-store'});
  if(!r.ok)throw new Error('http '+r.status);
  const d=await r.json();
  const s=JSON.stringify(d);
  if(s!==window._lastS){
   window._lastS=s;
   render(d);
   (function(){const ff=document.getElementById('firstfail');if(ff)ff.style.display='none';})();
   try{localStorage.setItem('owlLast:'+B,s)}catch(e){}
  }
  lastOk=Date.now();ago();
  window._offFail=0;offlineUI(false);
 }catch(e){
  window._offFail=(window._offFail||0)+1;
  document.getElementById('upd').textContent=
   'hors ligne - nouvel essai...';
  if(window._offFail>=2)offlineUI(true);
  if(!window._offR){window._offR=1;
   try{const c=JSON.parse(
    localStorage.getItem('owlLast:'+B)||'null');
    if(c){render(c);window._cached=1;
     document.getElementById('st').innerHTML='&#128244; '+
      '<b>Hors ligne</b> &mdash; derni&egrave;res donn&eacute;es '+
      'connues';}}catch(e2){}}
  if(!window._lastS&&!window._cached){const ff=document.getElementById('firstfail');if(ff)ff.style.display='block';}
 }
}
// 2026-09-27: an honest offline state - a banner with the retry countdown
// and the time of the last good update; polling pauses entirely while the
// app is hidden and resumes with an immediate refresh when it comes back.
function offlineUI(on){
 const el=document.getElementById('offline');if(!el)return;
 el.classList.toggle('on',!!on);
 // 2026-10-01 (owner): the banner used to say "Connexion perdue" while
 // the chip a few pixels above still said EN DIRECT in green. The chip
 // only ever turned to RECONNEXION when the SERVER reported itself
 // stale - and when the phone cannot reach the server at all, render()
 // never runs. While the banner is up, the chip belongs to it.
 window._offNow=!!on;
 {const lv=document.getElementById('lv'),lvd=document.getElementById('lvd'),
   lvt=document.getElementById('lvt');
  if(lv&&lvd&&lvt){
   if(on){lv.style.background='rgba(230,160,40,.16)';
    lv.style.color='#ffd27a';lvd.style.background='#e6a028';
    lvt.textContent=LANG()==='en'?'OFFLINE':'HORS LIGNE';}
   else if(window._d){lv.style.background='rgba(46,204,113,.16)';
    lv.style.color='var(--up-soft)';lvd.style.background='var(--up)';
    lvt.textContent='EN DIRECT';}}}
 if(!on){clearInterval(window._offT);window._offT=null;return;}
 if(window._offT)return;
 window._offNext=Date.now()+POLL_MS;
 const tick=()=>{const s=Math.max(0,Math.ceil((window._offNext-Date.now())/1000));
  const la=lastOk?new Date(lastOk):null;
  document.getElementById('offline-t').textContent='Connexion perdue \u2014 nouvel essai dans '+
   s+' s'+(la?' \u00b7 derni\u00e8re mise \u00e0 jour '+String(la.getHours()).padStart(2,'0')+':'+
   String(la.getMinutes()).padStart(2,'0'):'');
  if(s<=0)window._offNext=Date.now()+POLL_MS;};
 tick();window._offT=setInterval(tick,500);
}
const POLL_MS=5000;
setTimeout(acctChipInit,1500);
(function(){const l=LANG();document.querySelectorAll('.lgc').forEach(b=>{const on=b.dataset.l===l;
 b.style.background=on?'var(--surface3)':'transparent';b.style.borderColor=on?'var(--border2)':'var(--border)';b.style.color=on?'var(--text2)':'var(--muted2)';});
 applyLang();i18nWatch();})();
load();loadInbox();
let pollT=setInterval(load,POLL_MS);
setInterval(pollSignal,10000);
setInterval(ago,1000);
document.addEventListener('visibilitychange',()=>{
 clearInterval(pollT);pollT=null;
 if(!document.hidden){load();loadDay();loadInbox();pollT=setInterval(load,POLL_MS);}
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
// 2026-10-03 (owner): the Android app. This phone's link is remembered so
// the app opens straight on it; inside the app (?twa=<version>) a newer
// APK is announced; in a browser on Android the APK is suggested once a
// fortnight. The APK installs over the old one - nothing to uninstall.
(function(){try{var m=location.pathname.match(/^[/]([A-Za-z0-9_-]{6,})[/]/);var adm=localStorage.getItem('owl_adm');
  // the admin's phone remembers the admin's own page, not the member's it is visiting
  if(m&&(!adm||adm==='/'+m[1]+'/'))localStorage.setItem('owlLink','/'+m[1]+'/');}catch(e){}
 try{var q=new URLSearchParams(location.search).get('twa');if(q)sessionStorage.setItem('owlTwa',q);}catch(e){}
 setTimeout(apkCheck,1800);
 // 2026-10-04 (owner): a Signal / Strategie member has no robot - the robot settings stay out of sight
 setInterval(function(){document.documentElement.classList.toggle('apponly',!!(window._d&&window._d.app_only));},1200);})();
async function apkCheck(){const c=document.getElementById('apkcard');if(!c)return;const en=LANG()==='en';
 const and=/Android/i.test(navigator.userAgent);let twa='';try{twa=sessionStorage.getItem('owlTwa')||'';}catch(e){}
 let j=null;try{j=await (await fetch('/apk.json',{cache:'no-store'})).json();}catch(e){}
 if(!j||!j.versionCode)return;
 // the Reglages row: version, and inside the app whether it is the latest
 (function(){const s=document.getElementById('apkrow-s');if(!s)return;
  if(twa)s.textContent=(+j.versionCode>+twa)?(en?'Version '+j.version+' available - tap to update':'Version '+j.version+' disponible \u2014 touchez pour mettre \u00e0 jour'):(en?'You have the latest version ('+j.version+')':'Vous avez la derni\u00e8re version ('+j.version+')');
  else s.textContent=(en?'Download the APK file \u00b7 version ':'T\u00e9l\u00e9charger le fichier APK \u00b7 version ')+j.version+(and?'':(en?' \u00b7 Android only':' \u00b7 Android seulement'));})();
 const T=document.getElementById('apk-t'),B=document.getElementById('apk-b'),G=document.getElementById('apk-go'),N=document.getElementById('apk-no');
 if(twa){if(+j.versionCode<=+twa)return;
  T.textContent=en?'A new version of the app':'Une nouvelle version de l\u2019application';
  B.textContent=en?'Version '+j.version+'. Tap, then install: it goes over the old one, nothing to uninstall.':'Version '+j.version+'. Touchez, puis installez : elle se pose par-dessus l\u2019ancienne, rien \u00e0 d\u00e9sinstaller.';
  G.textContent=en?'Update':'Mettre \u00e0 jour';N.textContent=en?'Later':'Plus tard';c.style.display='block';return;}
 if(!and)return;
 let dis=0;try{dis=+localStorage.getItem('owlApkDis')||0;}catch(e){}
 if(Date.now()-dis<14*86400000)return;
 T.textContent=en?'OwlNest as a real app':'OwlNest en vraie application';
 B.textContent=en?'Faster to open, its own icon, no browser bar. Android asks once to allow the install.':'Plus rapide \u00e0 ouvrir, sa propre ic\u00f4ne, sans barre de navigateur. Android demande une fois d\u2019autoriser l\u2019installation.';
 G.textContent=en?'Install the app':'Installer l\u2019application';N.textContent=en?'No thanks':'Non merci';c.style.display='block';}
function apkDismiss(){try{localStorage.setItem('owlApkDis',String(Date.now()));}catch(e){}const c=document.getElementById('apkcard');if(c)c.style.display='none';}
</script>
<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">
<symbol id="i-home" viewBox="0 0 24 24"><path d="M3 11 12 3l9 8"/><path d="M5 10v10h5v-6h4v6h5V10"/></symbol>
<symbol id="i-calendar" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/></symbol>
<symbol id="i-settings" viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2.5"/><circle cx="9" cy="17" r="2.5"/></symbol>
<symbol id="i-users" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><circle cx="17" cy="9" r="2.6"/><path d="M15.5 14.3c3 .2 6 2.3 6 5.7"/></symbol>
<symbol id="i-chart" viewBox="0 0 24 24"><path d="M3 20h18"/><path d="M4 15l5-5 4 4 7-8"/><path d="M16 6h4v4"/></symbol>
<symbol id="i-bell" viewBox="0 0 24 24"><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/></symbol>
<symbol id="i-phone" viewBox="0 0 24 24"><rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18h2"/></symbol>
<symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></symbol>
<symbol id="i-book" viewBox="0 0 24 24"><path d="M12 6c-2-1.5-4.5-2-8-2v14c3.5 0 6 .5 8 2 2-1.5 4.5-2 8-2V4c-3.5 0-6 .5-8 2z"/><path d="M12 6v14"/></symbol>
<symbol id="i-pause" viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></symbol>
<symbol id="i-lock" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></symbol>
<symbol id="i-target" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/></symbol>
<symbol id="i-key" viewBox="0 0 24 24"><circle cx="8" cy="14" r="4"/><path d="M11 11 20 2M16 6l3 3M18 4l2 2"/></symbol>
<symbol id="i-switch" viewBox="0 0 24 24"><path d="M4 8h13l-3-3M20 16H7l3 3"/></symbol>
<symbol id="i-trash" viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/></symbol>
<symbol id="i-share" viewBox="0 0 24 24"><path d="M12 15V4M8 8l4-4 4 4"/><path d="M5 13v6h14v-6"/></symbol>
<symbol id="i-ticket" viewBox="0 0 24 24"><path d="M3 9V6h18v3a2 2 0 0 0 0 4v3H3v-3a2 2 0 0 0 0-4z"/><path d="M10 6v12"/></symbol>
<symbol id="i-bot" viewBox="0 0 24 24"><rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4M9 4h6"/><circle cx="9" cy="14" r="1.2"/><circle cx="15" cy="14" r="1.2"/></symbol>
<symbol id="i-exit" viewBox="0 0 24 24"><path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"/><path d="M10 16l-4-4 4-4M6 12h10"/></symbol>
<symbol id="i-reset" viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v4h-4"/></symbol>
<symbol id="i-eye" viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></symbol>
<symbol id="i-gift" viewBox="0 0 24 24"><rect x="3" y="9" width="18" height="4"/><path d="M5 13v8h14v-8M12 9v12"/><path d="M12 9c-2-4-6-4-6-1.5S12 9 12 9zM12 9c2-4 6-4 6-1.5S12 9 12 9z"/></symbol>
<symbol id="i-download" viewBox="0 0 24 24"><path d="M12 4v11M8 11l4 4 4-4"/><path d="M5 19h14"/></symbol>
<symbol id="i-chev" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></symbol>
<symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></symbol>
<symbol id="i-moon" viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></symbol>
<symbol id="i-cloud" viewBox="0 0 24 24"><path d="M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 11.5 3.5 3.5 0 0 0 7 18z"/></symbol>
<symbol id="i-bolt" viewBox="0 0 24 24"><path d="M7 15h9.5a3.5 3.5 0 0 0 .4-7A5.5 5.5 0 0 0 6.3 9 3 3 0 0 0 7 15z"/><path d="M12.5 13l-2.5 4h4l-2.5 4"/></symbol>
<symbol id="i-wave" viewBox="0 0 24 24"><path d="M3 10c2-3 4-3 6 0s4 3 6 0 4-3 6 0"/><path d="M3 16c2-3 4-3 6 0s4 3 6 0 4-3 6 0"/></symbol>
<symbol id="i-activity" viewBox="0 0 24 24"><path d="M3 12h4l3-7 4 14 3-7h4"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7"/></symbol>
<symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></symbol>
<symbol id="i-stop" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></symbol>
</svg>
</body></html>"""


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


CODE_TTL = 7 * 86400          # a code lives a week: Telegram takes its time
CODE_PKGS = ("family", "manual", "strategy")


def new_activation_code(pkg="family", days=30, for_name=""):
    """One-time activation code (2026-09-05 user; 2026-10-03 owner: it
    names a PACKAGE and a duration). The master generates it in HIS app
    and sends it on Telegram; entering it - in the app to renew, or on
    the /activate page to open an account - grants that package. Single
    use, one week."""
    import random
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no O/0/I/1
    code = "".join(random.choice(alphabet) for _ in range(6))
    c = _load_codes()
    c["codes"].append({"code": code, "t": time.time(), "used_by": None,
                       "pkg": pkg if pkg in CODE_PKGS else "family", "days": int(days or 30),
                       "for": (for_name or "")[:40]})
    c["codes"] = c["codes"][-500:]
    _save_codes(c)
    return code


def peek_activation_code(code):
    """The code's entry if it is valid and unused, else None."""
    c = _load_codes()
    for e in c["codes"]:
        if (e["code"] == code.strip().upper() and not e.get("used_by")
                and time.time() - float(e["t"]) < CODE_TTL):
            return e
    return None


def redeem_activation_code(code, uid):
    """Marks the code used; returns its entry (pkg, days) or None."""
    c = _load_codes()
    for e in c["codes"]:
        if (e["code"] == code.strip().upper() and not e.get("used_by")
                and time.time() - float(e["t"]) < CODE_TTL):
            e["used_by"] = uid
            e["used_t"] = time.time()
            _save_codes(c)
            return e
    return None


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


def day_payload(user):
    """Today, for the account being viewed: nervosity history (24 h, from
    the chart feed), closed trades from the bot's own journal, and the
    signals the bot ignored - COARSE on purpose (meteo / robot), never the
    rule that fired (owner 2026-09-26: the strategy stays private)."""
    out = {"nerv": [], "trades": [], "ignored": [], "now": int(time.time())}
    try:
        pts = json.load(open(os.path.join(DIR, "owl_nerv_hist.json")))
        cut = time.time() - 86400
        out["nerv"] = [[int(p[0]), float(p[1])] for p in pts if p[0] >= cut]
    except Exception:
        pass
    bot = BOT_OF.get(user.get("id"))
    if not bot or not bot[1].startswith("bos_state"):
        return out
    sfx = bot[1][len("bos_state"):-len(".json")]
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _ep(x):
        try:
            return int(datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp())
        except Exception:
            return None
    try:
        import csv as _csv
        with open(os.path.join(DIR, f"bos_journal{sfx}.csv"),
                  encoding="utf-8", errors="replace") as jf:
            _era = era_ts(user)
            for r in _csv.DictReader(jf):
                et = r.get("entry_time_utc") or ""
                xt = r.get("exit_time_utc") or ""
                if not (et.startswith(day) or xt.startswith(day)):
                    continue
                if _era and (_ep(xt) or _ep(et) or 0) < _era:
                    continue
                out["trades"].append({"t": _ep(et), "x": _ep(xt),
                                      "p": float(r.get("profit_usd") or 0),
                                      "d": r.get("direction") or ""})
    except Exception:
        pass
    try:
        with open(os.path.join(DIR, bot[2]), "rb") as lf:
            lf.seek(0, 2)
            n = lf.tell()
            lf.seek(max(0, n - 400000))
            raw = lf.read().decode("utf-8", "replace")
        for line in raw.splitlines():
            if not line.startswith(day) or " refuse: " not in line:
                continue
            t = _ep(line.split(" ", 1)[0])
            if t is None:
                continue
            low = line.lower()
            kind = ("meteo" if ("nerveux" in low or "rapide" in low
                                or "mouvement" in low) else "robot")
            out["ignored"].append([t, kind])
    except Exception:
        pass
    return out


INBOX_FILE = os.path.join(DIR, "owl_push_inbox.json")


NOTES_FILE = os.path.join(DIR, "owl_nest_notes.json")
CONFIG_FILE = os.path.join(DIR, "owl_nest_config.json")
SEEN_FILE = os.path.join(DIR, "owl_last_seen.json")
_seen_mem = {}


def nest_config():
    try:
        c = json.load(open(CONFIG_FILE, encoding="utf-8"))
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def touch_seen(uid):
    """2026-09-27: when a member's page polls, remember it (once a minute)."""
    now = time.time()
    if now - _seen_mem.get(uid, 0) < 60:
        return
    _seen_mem[uid] = now
    try:
        try:
            d = json.load(open(SEEN_FILE, encoding="utf-8"))
            if not isinstance(d, dict):
                d = {}
        except Exception:
            d = {}
        d[uid] = int(now)
        json.dump(d, open(SEEN_FILE + ".tmp", "w", encoding="utf-8"))
        os.replace(SEEN_FILE + ".tmp", SEEN_FILE)
    except Exception:
        pass


def reset_preview(uid):
    """What a reset would archive and what it keeps, for the owner's sheet."""
    out = {"uid": uid, "trades": 0, "days": 0, "first": None, "journal_rows": 0,
           "state": False, "era_start": None}
    try:
        u = next(x for x in json.load(open(USERS_FILE, encoding="utf-8")) if x.get("id") == uid)
    except Exception:
        return out
    out["era_start"] = u.get("era_start")
    try:
        nd = json.load(open(os.path.join(NEST_DATA, uid + ".json")))
        out["trades"] = int((nd.get("since_start") or {}).get("n") or 0)
        out["days"] = int((nd.get("since_start") or {}).get("days") or 0)
        out["first"] = (nd.get("since_start") or {}).get("first")
    except Exception:
        pass
    bot = BOT_OF.get(uid)
    if bot and bot[1].startswith("bos_state"):
        out["state"] = os.path.exists(os.path.join(DIR, bot[1]))
        sfx = bot[1][len("bos_state"):-len(".json")]
        try:
            import csv as _csv
            _era = era_ts(u)
            with open(os.path.join(DIR, f"bos_journal{sfx}.csv"), encoding="utf-8", errors="replace") as jf:
                for r in _csv.DictReader(jf):
                    try:
                        xt = int(datetime.fromisoformat((r.get("exit_time_utc") or "").replace("Z", "+00:00")).timestamp())
                    except Exception:
                        xt = 0
                    if not _era or xt >= _era:
                        out["journal_rows"] += 1
        except Exception:
            pass
    return out


def era_ts(user):
    """The member's era start as epoch (0 if none) - every journal reader
    skips rows closed before it, so a reset gives a clean history even if
    an old journal is still around."""
    try:
        return int(datetime.fromisoformat(
            str(user.get("era_start")).replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def service_health():
    """Ages (s) of every file the service lives on, plus who is alive."""
    now = time.time()

    def age(p):
        try:
            return int(now - os.path.getmtime(os.path.join(DIR, p)))
        except Exception:
            return None
    out = {"t": int(now), "build": APP_BUILD,
           "chart_feed": age("owl_chart_btc.json"),
           "nerv_hist": age("owl_nerv_hist.json"),
           "notifier_log": age("owl_push_notifier.log"),
           "mode_switch_log": age("owl_mode_switch.log"),
           "workers": {}, "bots": {}, "desks": {}, "push_subs": 0}
    try:
        for x in json.load(open(USERS_FILE, encoding="utf-8")):
            uid = x.get("id")
            out["workers"][uid] = age(os.path.join("nest_data", uid + ".json"))
            lab, live, blk = bot_on(uid)
            if lab:
                out["bots"][uid] = {"label": lab, "live": bool(live), "blocked": blk}
            if x.get("mode") in MANUAL_MODES:
                out["desks"][uid] = age(f"manual_state_{uid}.json")
    except Exception:
        pass
    try:
        out["push_subs"] = sum(len(v) for v in json.load(open(PUSH_SUBS_FILE)).values())
    except Exception:
        pass
    return out


def inbox_items(user):
    """2026-09-27: the member's last notifications, newest first (written by
    owl_push_notifier.send_all) - so a missed push is never lost."""
    try:
        allx = json.load(open(INBOX_FILE, encoding="utf-8"))
    except Exception:
        allx = {}
    lst = allx.get(str(user.get("id")), []) if isinstance(allx, dict) else []
    lst = [x for x in lst if isinstance(x, dict)]
    lst.sort(key=lambda x: x.get("t", 0), reverse=True)
    return {"items": lst[:30]}


def trade_story(user, t_close):
    """Find the journal row whose exit is within 3 min of t_close and
    return plain-words material: direction, times, duration, max risk in
    dollars, how the market felt at entry (calme / soutenu / rapide /
    tres rapide), the result. No levels, no rule names."""
    out = {"found": False}
    bot = BOT_OF.get(user.get("id"))
    if not (bot and bot[1].startswith("bos_state") and t_close):
        return out
    sfx = bot[1][len("bos_state"):-len(".json")]
    import csv as _csv

    def _ep(x):
        try:
            return int(datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp())
        except Exception:
            return None
    best = None
    try:
        with open(os.path.join(DIR, f"bos_journal{sfx}.csv"),
                  encoding="utf-8", errors="replace") as jf:
            _era = era_ts(user)
            for r in _csv.DictReader(jf):
                xt = _ep(r.get("exit_time_utc") or "")
                if xt is None or (_era and xt < _era):
                    continue
                dd = abs(xt - t_close)
                if dd <= 180 and (best is None or dd < best[0]):
                    best = (dd, r, xt)
    except Exception:
        return out
    if best is None:
        return out
    r, xt = best[1], best[2]
    et = _ep(r.get("entry_time_utc") or "") or xt
    try:
        nv = float(r.get("nervosity") or 0)
    except Exception:
        nv = 0.0
    band = ("calme" if nv < 1.0 else "soutenu" if nv < 1.30
            else "rapide" if nv < 1.85 else "tr\u00e8s rapide") if nv else ""
    try:
        risk = round(float(r.get("dist_pts") or 0) * float(r.get("lot") or 0), 2)
    except Exception:
        risk = None
    try:
        p = float(r.get("profit_usd") or 0)
    except Exception:
        p = 0.0
    # 2026-09-27: the plan vs what happened - words only in the app
    try:
        _ep, _sl, _tp, _lot = (float(r.get("entry_price") or 0), float(r.get("sl") or 0),
                               float(r.get("tp") or 0), float(r.get("lot") or 0))
        plan_gain = round(abs(_tp - _ep) * _lot, 2) if _tp and _ep else None
    except Exception:
        plan_gain = None
    return {"found": True, "dir": r.get("direction") or "", "t": et, "x": xt,
            "dur_min": round((xt - et) / 60), "risk": risk, "band": band,
            "p": p, "outcome": (r.get("outcome") or "").lower(),
            "plan_gain": plan_gain}


def export_csv(user):
    """date,heure,sens,lot,entree,sortie,duree_min,resultat - nothing from
    the journal's strategy columns (kind, nervosity, gates...)."""
    import csv as _csv
    import io as _io
    out = _io.StringIO()
    wr = _csv.writer(out, lineterminator="\n")
    wr.writerow(["date", "heure", "sens", "lot", "entree", "sortie",
                 "duree_min", "resultat_usd"])
    bot = BOT_OF.get(user.get("id"))
    if bot and bot[1].startswith("bos_state"):
        sfx = bot[1][len("bos_state"):-len(".json")]
        try:
            with open(os.path.join(DIR, f"bos_journal{sfx}.csv"),
                      encoding="utf-8", errors="replace") as jf:
                _era = era_ts(user)
                for r in _csv.DictReader(jf):
                    xt = (r.get("exit_time_utc") or r.get("entry_time_utc") or "")
                    try:
                        if _era and int(datetime.fromisoformat(xt.replace("Z", "+00:00")).timestamp()) < _era:
                            continue
                    except Exception:
                        pass
                    wr.writerow([xt[:10], xt[11:16],
                                 "achat" if (r.get("direction") or "") == "BUY" else "vente",
                                 r.get("lot") or "", r.get("entry_price") or "",
                                 r.get("tp") if (r.get("outcome") or "") == "WIN" else r.get("sl") or "",
                                 r.get("duration_min") or "", r.get("profit_usd") or ""])
        except Exception:
            pass
    return "\ufeff" + out.getvalue()


def user_by_token(tok):
    for u in users():
        if u.get("token") == tok:
            return u
    return None


MKT_DIR = os.path.join(DIR, "mkt_mem")
_MH_CACHE = {"t": 0.0, "data": None}


def market_hours(days=30):
    """Weekday x hour (UTC) medians of the nervosity ratio from mkt_mem."""
    if _MH_CACHE["data"] is not None and time.time() - _MH_CACHE["t"] < 600:
        return _MH_CACHE["data"]
    import statistics as _st
    cells = {}
    ndays = 0
    cut = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    try:
        files = sorted(f for f in os.listdir(MKT_DIR) if f.endswith(".jsonl") and f[:10] >= cut)
    except Exception:
        files = []
    for fn in files:
        ndays += 1
        try:
            for line in open(os.path.join(MKT_DIR, fn), encoding="utf-8"):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("nerv") is None:
                    continue
                g = time.gmtime(int(r["t"]))
                cells.setdefault((g.tm_wday, g.tm_hour), []).append(float(r["nerv"]))
        except Exception:
            continue
    out = {"days": ndays, "cells": [{"wd": k[0], "h": k[1], "n": len(v), "med": round(_st.median(v), 3)}
                                    for k, v in cells.items()],
           "updated": int(time.time())}
    _MH_CACHE.update(t=time.time(), data=out)
    return out


def _why_family(text):
    l = text.lower()
    if "dette active" in l or "rattrapage" in l:
        return "rattrapage"
    if "contre la tendance" in l:
        return "tendance"
    if ("nerveux" in l or "tres rapide" in l or "pas calme" in l or "mouvement" in l
            or "asleep" in l or "agit" in l or "storm" in l):
        return "meteo"
    if "deja pris" in l or "continuation" in l or "limite du jour" in l or "un seul" in l or "niveau" in l:
        return "limite"
    return "autre"


def robot_why(user):
    """Refusals of the account's robot (or its desk's signals) by family,
    today and the last 7 days (UTC)."""
    uid = user.get("id")
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    week0 = now - 7 * 86400
    fams = ("meteo", "rattrapage", "tendance", "limite", "autre")
    T = {k: 0 for k in fams}
    W = {k: 0 for k in fams}
    src = None
    m = BOT_OF.get(uid)
    if m and m[2]:
        src = "robot"
        try:
            lines = open(os.path.join(DIR, m[2]), encoding="utf-8", errors="replace").readlines()[-6000:]
        except Exception:
            lines = []
        for ln in lines:
            if not (" refuse: " in ln or "skipped" in ln or "pas pris" in ln or "LIMITE DU JOUR" in ln):
                continue
            try:
                ts = datetime.fromisoformat(ln[:32].split(" ")[0]).timestamp()
            except Exception:
                continue
            if ts < week0:
                continue
            f = _why_family(ln)
            W[f] += 1
            if ln[:10] == today:
                T[f] += 1
    if user.get("mode") in MANUAL_MODES or src is None:
        try:
            for x in json.load(open(os.path.join(DIR, f"owl_signals_{uid}.json"), encoding="utf-8")):
                if x.get("ok") or float(x.get("t") or 0) < week0:
                    continue
                f = _why_family(x.get("why") or "")
                W[f] += 1
                if time.strftime("%Y-%m-%d", time.gmtime(float(x["t"]))) == today:
                    T[f] += 1
            src = src or "desk"
        except Exception:
            pass
    return {"today": T, "week": W, "total_today": sum(T.values()), "total_week": sum(W.values()),
            "src": src or "none"}


def robot_journal(user, n=20):
    """The account's last n closed trades with the story trade_story() tells."""
    uid = user.get("id")
    try:
        nd = json.load(open(os.path.join(DIR, "nest_data", f"{uid}.json")))
    except Exception:
        return {"items": []}
    _now = datetime.now(timezone.utc)
    _era = era_ts(user)
    out = []
    for p in (nd.get("trades") or [])[:n]:
        mw = re.match(r"^(\d\d)/(\d\d) (\d\d):(\d\d)$", p.get("w") or "")
        if not mw:
            continue
        y = _now.year - (1 if int(mw.group(2)) > _now.month else 0)
        try:
            xt = int(datetime(y, int(mw.group(2)), int(mw.group(1)), int(mw.group(3)), int(mw.group(4)),
                              tzinfo=timezone.utc).timestamp())
        except Exception:
            continue
        et = xt - int(round(float(p.get("dur") or 0) * 60))
        if _era and xt < _era:
            continue
        st = {}
        try:
            st = trade_story(user, xt) or {}
        except Exception:
            st = {}
        out.append({"w": p.get("w"), "p": p.get("p"), "dir": p.get("dir"), "lot": p.get("lot"),
                    "ep": p.get("ep"), "xp": p.get("xp"), "dur": p.get("dur"), "t": et, "x": xt,
                    "band": st.get("band") if st.get("found") else None,
                    "risk": st.get("risk") if st.get("found") else None,
                    "kind": p.get("k")})
    return {"items": out}


_PAT_CACHE = {"t": 0.0, "data": None}


def _journal_unique():
    """Every closed main trade across the bot journals, each entry counted
    once (the accounts take the same entries)."""
    import csv as _csv, glob as _glob
    seen = {}
    for f in _glob.glob(os.path.join(DIR, "bos_journal*.csv")):
        try:
            for r in _csv.DictReader(open(f, encoding="utf-8", errors="replace")):
                o = (r.get("outcome") or "").lower()
                if o not in ("win", "loss") or r.get("is_add") == "True":
                    continue
                k = ((r.get("entry_time_utc") or "")[:16], r.get("direction"))
                if k in seen:
                    continue
                try:
                    et = datetime.fromisoformat(r["entry_time_utc"]).timestamp()
                    xt = datetime.fromisoformat(r["exit_time_utc"]).timestamp() if r.get("exit_time_utc") else et
                except Exception:
                    continue
                seen[k] = {"t": et, "x": xt, "win": o == "win", "p": float(r.get("profit_usd") or 0),
                           "nerv": float(r["nervosity"]) if r.get("nervosity") else None,
                           "kind": r.get("kind") or "", "internal": r.get("internal") == "True",
                           "dir": (r.get("direction") or "").upper()}
        except Exception:
            continue
    return sorted(seen.values(), key=lambda x: x["t"])


def _wr(rows):
    n = len(rows)
    return {"n": n, "win": (round(100 * sum(1 for r in rows if r["win"]) / n) if n else None),
            "net": round(sum(r["p"] for r in rows), 2)}


_SN_FR = {"asie": "nuit (00–08 h)", "europe": "journée (08–16 h)", "us": "soirée (16–24 h)"}
_SN_EN = {"asie": "night (00–08)", "europe": "day (08–16)", "us": "evening (16–24)"}


def _pct(rows):
    w = _wr(rows)["win"]
    return "—" if w is None else f"{w} %"


def patterns():
    """2026-09-28 (owner): the market space must show the PATTERNS being
    established - each with its evidence, how sure we are, and whether the
    robot already uses it. Backtest figures are the published replays
    (review/*.md); live figures are recomputed here from the journals and
    the market memory. A live number under 30 trades is 'en observation'."""
    if _PAT_CACHE["data"] is not None and time.time() - _PAT_CACHE["t"] < 600:
        return _PAT_CACHE["data"]
    J = _journal_unique()
    # --- market memory shares ---
    shares = {"calme": 0, "soutenu": 0, "rapide": 0, "tres_rapide": 0}
    mdays = 0
    try:
        for fn in sorted(os.listdir(MKT_DIR)):
            if not fn.endswith(".jsonl"):
                continue
            mdays += 1
            for line in open(os.path.join(MKT_DIR, fn), encoding="utf-8"):
                try:
                    v = json.loads(line).get("nerv")
                except Exception:
                    continue
                if v is None:
                    continue
                shares["calme" if v < 1.0 else ("soutenu" if v < 1.3 else ("rapide" if v < 1.85 else "tres_rapide"))] += 1
    except Exception:
        pass
    tot = sum(shares.values()) or 1
    shares_pct = {k: round(100 * v / tot) for k, v in shares.items()}
    # --- live cuts ---
    calm = [r for r in J if r["nerv"] is not None and r["nerv"] < 1.0]
    hot = [r for r in J if r["nerv"] is not None and r["nerv"] >= 1.0]
    flips = [r for r in J if r["kind"] == "FLIP-BOS"]
    conts = [r for r in J if r["kind"] == "BOS"]
    quick, slow = [], []
    for i, r in enumerate(J):
        prev = J[i - 1] if i else None
        (quick if (prev and r["t"] - prev["x"] < 1800) else slow).append(r)
    sess = {"asie": [], "europe": [], "us": []}
    for r in J:
        h = time.gmtime(r["t"]).tm_hour
        sess["asie" if h < 8 else ("europe" if h < 16 else "us")].append(r)
    live_n = len(J)

    def conf(n, min_n=30):
        return "observation" if n < min_n else "vivant"

    cards = [
        {"id": "calm", "icon": "i-cloud",
         "title": "Quand le march\u00e9 est calme, le robot gagne plus souvent",
         "title_en": "When the market is calm, the robot wins more often",
         "fig": _pct(calm),
         "fig_l": "de trades gagn\u00e9s en march\u00e9 calme, en vrai", "fig_l_en": "of trades won in a calm market, for real",
         "live": f"{_wr(calm)['n']} trades en march\u00e9 calme ({_pct(calm)} gagn\u00e9s) contre {_wr(hot)['n']} en march\u00e9 nerveux ({_pct(hot)} gagn\u00e9s)",
         "live_en": f"{_wr(calm)['n']} trades in a calm market ({_pct(calm)} won) vs {_wr(hot)['n']} in a nervous one ({_pct(hot)} won)",
         "back": "Sur 42 jours de pass\u00e9 rejou\u00e9s : 64 % de gagn\u00e9s quand le march\u00e9 \u00e9tait juste sous la normale, 37 % juste au-dessus. Le nerveux fait perdre ; le calme ne garantit rien.",
         "back_en": "Over 42 replayed days: 64 % won when the market was just below normal, 37 % just above. Nervous loses; calm guarantees nothing.",
         "status": "confirme", "robot": "oui", "robot_note": "Il laisse passer les trades quand le march\u00e9 est plus nerveux que d\u2019habitude (r\u00e9glable par compte), et personne ne trade en plein orage.",
         "robot_note_en": "It lets trades go when the market is more nervous than usual (per-account setting), and nobody trades in a storm.",
         "manual": "Si le signal arrive alors que le march\u00e9 est nerveux, misez moins, ou laissez passer.",
         "manual_en": "If the signal comes while the market is nervous, bet less, or let it go."},
        {"id": "shares", "icon": "i-wave",
         "title": "Le march\u00e9 est calme la plupart du temps", "title_en": "The market is calm most of the time",
         "fig": f"{shares_pct['calme']} %", "fig_l": f"du temps en march\u00e9 calme (sur {mdays} jour{'s' if mdays > 1 else ''} de m\u00e9moire)", "fig_l_en": f"of the time in a calm market (over {mdays} day{'s' if mdays > 1 else ''} of memory)",
         "live": f"un peu agit\u00e9 {shares_pct['soutenu']} % \u00b7 rapide {shares_pct['rapide']} % \u00b7 orage {shares_pct['tres_rapide']} %",
         "live_en": f"a bit brisk {shares_pct['soutenu']} % \u00b7 fast {shares_pct['rapide']} % \u00b7 storm {shares_pct['tres_rapide']} %",
         "back": "Sur 42 jours : calme 53 % du temps, un peu agit\u00e9 22 %, rapide 15 %, orage 10 %. Les mots de la m\u00e9t\u00e9o viennent de l\u00e0.",
         "back_en": "Over 42 days: calm 53 % of the time, a bit brisk 22 %, fast 15 %, storm 10 %. The weather words come from there.",
         "status": "vivant" if mdays >= 7 else "observation", "robot": "oui", "robot_note": "C\u2019est la m\u00e9t\u00e9o que vous voyez sur la carte : calme, soutenu, rapide, tr\u00e8s rapide.",
         "robot_note_en": "It is the weather you see on the card: calm, brisk, fast, very fast.",
         "manual": "Les heures agit\u00e9es reviennent souvent aux m\u00eames moments : regardez la grille des heures plus bas.",
         "manual_en": "Busy hours tend to come back at the same times: look at the hours grid below."},
        {"id": "flip", "icon": "i-switch",
         "title": "Le premier trade apr\u00e8s un changement de sens vaut mieux que les suivants", "title_en": "The first trade after a change of direction is worth more than the next ones",
         "fig": _pct(flips), "fig_l": "de gagn\u00e9s sur les changements de sens, en vrai", "fig_l_en": "won on changes of direction, for real",
         "live": f"changements de sens {_wr(flips)['n']} ({_pct(flips)} gagn\u00e9s) \u00b7 trades dans le m\u00eame sens ensuite {_wr(conts)['n']} ({_pct(conts)} gagn\u00e9s)",
         "live_en": f"changes of direction {_wr(flips)['n']} ({_pct(flips)} won) \u00b7 same-direction follow-ups {_wr(conts)['n']} ({_pct(conts)} won)",
         "back": "Sur 42 jours rejou\u00e9s : le changement de sens plus un seul trade de plus donne +$164. Sans trade de plus, +$83. Avec deux ou trois de plus, on perd.",
         "back_en": "Over 42 replayed days: the change of direction plus one more trade gives +$164. With none, +$83. With two or three more, it loses.",
         "status": "confirme", "robot": "oui", "robot_note": "Apr\u00e8s une perte, il prend le changement de sens et un seul trade de plus dans ce sens.",
         "robot_note_en": "After a loss it takes the change of direction and only one more trade that way.",
         "manual": "Le premier signal apr\u00e8s que le march\u00e9 a chang\u00e9 de sens est le plus s\u00fbr. Le troisi\u00e8me de suite l\u2019est rarement.",
         "manual_en": "The first signal after the market changes direction is the safest. The third in a row rarely is."},
        {"id": "quick", "icon": "i-bolt",
         "title": "Les trades qui s\u2019encha\u00eenent vite perdent plus souvent \u2014 mais les \u00e9viter co\u00fbte cher", "title_en": "Trades that follow quickly lose more often \u2014 but avoiding them is costly",
         "fig": _pct(quick), "fig_l": "de gagn\u00e9s quand le trade arrive moins de 30 min apr\u00e8s le pr\u00e9c\u00e9dent", "fig_l_en": "won when the trade comes less than 30 min after the previous one",
         "live": f"trades rapproch\u00e9s {_wr(quick)['n']} ({_pct(quick)} gagn\u00e9s) \u00b7 trades espac\u00e9s {_wr(slow)['n']} ({_pct(slow)} gagn\u00e9s)",
         "live_en": f"quick follow-ups {_wr(quick)['n']} ({_pct(quick)} won) \u00b7 spaced trades {_wr(slow)['n']} ({_pct(slow)} won)",
         "back": "Sur 42 jours rejou\u00e9s : faire une pause de 30 minutes apr\u00e8s chaque trade perd $106. Les trades rapproch\u00e9s sont ceux qui rattrapent les pertes.",
         "back_en": "Over 42 replayed days: a 30-minute break after each trade loses $106. The quick follow-ups are the ones that recover the losses.",
         "status": "rejete", "robot": "non", "robot_note": "Test\u00e9, pas retenu : le robot ne fait pas de pause apr\u00e8s un trade.", "robot_note_en": "Tested, not kept: the robot takes no break after a trade.",
         "manual": "Un signal juste apr\u00e8s une perte n\u2019est pas mauvais en soi. Ce qui compte, c\u2019est de ne pas miser plus gros pour se refaire.",
         "manual_en": "A signal right after a loss is not bad in itself. What matters is not betting bigger to get even."},
        {"id": "target", "icon": "i-target",
         "title": "Viser un gain plus petit rend la route plus douce, sans changer l\u2019arriv\u00e9e", "title_en": "Aiming for a smaller gain makes the road smoother, without changing the destination",
         "fig": "\u221238 %", "fig_l": "de profondeur pour le plus gros trou, en visant moiti\u00e9 moins", "fig_l_en": "depth for the biggest hole, aiming for half",
         "live": "Val\u00e8re depuis le 14/09 : en visant comme aujourd\u2019hui +$24 (24 gagn\u00e9s, 14 perdus) \u00b7 en visant moiti\u00e9 moins +$27 (33 gagn\u00e9s, 5 perdus)", "live_en": "Val\u00e8re since 14/09: aiming as today +$24 (24 won, 14 lost) \u00b7 aiming for half +$27 (33 won, 5 lost)",
         "back": "Sur 42 jours rejou\u00e9s : m\u00eame argent \u00e0 la fin, mais le plus gros trou passe de 63 \u00e0 39 dollars, sur les deux moiti\u00e9s de la p\u00e9riode.",
         "back_en": "Over 42 replayed days: same money at the end, but the biggest hole goes from 63 to 39 dollars, on both halves of the period.",
         "status": "candidat", "robot": "candidat", "robot_note": "Pas encore dans le robot. \u00c0 observer d\u2019abord sur la d\u00e9mo, sans argent r\u00e9el.", "robot_note_en": "Not in the robot yet. To watch on the demo first, no real money.",
         "manual": "Prendre la moiti\u00e9 de la cible du signal donne le m\u00eame r\u00e9sultat avec bien moins de trades perdus.",
         "manual_en": "Taking half of the signal's target gives the same result with far fewer losing trades."},
        {"id": "session", "icon": "i-sun",
         "title": "Y a-t-il un meilleur moment de la journ\u00e9e ? On ne sait pas encore", "title_en": "Is there a better time of day? We do not know yet",
         "fig": "\u2014", "fig_l": "trop t\u00f4t pour le dire", "fig_l_en": "too early to say",
         "live": " \u00b7 ".join(_SN_FR[k] + f" {_wr(v)['n']} trades ({_pct(v)} gagn\u00e9s)" for k, v in sess.items() if _wr(v)["n"]),
         "live_en": " \u00b7 ".join(_SN_EN[k] + f" {_wr(v)['n']} trades ({_pct(v)} won)" for k, v in sess.items() if _wr(v)["n"]),
         "back": "Sur le pass\u00e9, la matin\u00e9e europ\u00e9enne a l\u2019air un peu meilleure (65 % de gagn\u00e9s sur 65 trades), mais pas sur les deux moiti\u00e9s de la p\u00e9riode. Donc pas de r\u00e8gle.",
         "back_en": "On the past the European morning looks a bit better (65 % won on 65 trades), but not on both halves of the period. So no rule.",
         "status": "observation", "robot": "non", "robot_note": "Le robot ne regarde pas l\u2019heure.", "robot_note_en": "The robot does not look at the clock.",
         "manual": "Rien \u00e0 en faire pour l\u2019instant. La grille des heures se remplit jour apr\u00e8s jour.",
         "manual_en": "Nothing to act on yet. The hours grid fills in day after day."},
    ]
    out = {"cards": cards, "live_trades": live_n, "memory_days": mdays, "updated": int(time.time()),
           "next": {"fr": "La suite : attendre 40 trades par compte pour \u00eatre s\u00fbr de l\u2019effet du march\u00e9 calme en vrai, 30 jours de m\u00e9moire pour conna\u00eetre les heures, puis essayer \u00ab viser plus petit \u00bb sur la d\u00e9mo, sans argent r\u00e9el.",
                    "en": "Next: wait for 40 trades per account to be sure of the calm-market effect for real, 30 days of memory to know the hours, then try \u201caim smaller\u201d on the demo, no real money."}}
    _PAT_CACHE.update(t=time.time(), data=out)
    return out


LAB_REG = os.path.join(DIR, "lab", "registry.json")
_LAB_CACHE = {"t": 0.0, "data": None}


# ---- 2026-10-02 (owner): the piles are DATA, written by the chercheur with
# a reason, not a fixed list in code. lab/cuts.json; grammar below.
LAB_CUTS = os.path.join(DIR, "lab", "cuts.json")
CUT_FIELDS = ("nerv", "kind", "dir", "hour", "wday", "gap_min", "dur_min", "prev_win", "p", "internal")
CUT_OPS = ("<", "<=", ">", ">=", "==", "!=", "in", "between")
CUT_MAX_ACTIVE = 24      # not a flood
CUT_MIN_N = 30           # trades before a pile can be read
CUT_STRICT_GAP = 10      # past eleven piles, a pile must also beat the rest by this many points
CUT_DUP = 0.8            # share of common trades that makes a pile a duplicate of an older one
CUT_SEED = [
    {"id": "calm", "title_fr": "Quand le march\u00e9 est calme", "title_en": "When the market is calm", "where": [{"field": "nerv", "op": "<", "value": 1.0}]},
    {"id": "hot", "title_fr": "Quand le march\u00e9 est nerveux", "title_en": "When the market is nervous", "where": [{"field": "nerv", "op": ">=", "value": 1.0}]},
    {"id": "flip", "title_fr": "Juste apr\u00e8s un changement de sens", "title_en": "Right after a change of direction", "where": [{"field": "kind", "op": "==", "value": "FLIP-BOS"}]},
    {"id": "cont", "title_fr": "Un trade de plus dans le m\u00eame sens", "title_en": "One more trade the same way", "where": [{"field": "kind", "op": "==", "value": "BOS"}]},
    {"id": "int", "title_fr": "Sur les petits mouvements", "title_en": "On the small moves", "where": [{"field": "kind", "op": "==", "value": "INT"}]},
    {"id": "quick", "title_fr": "Moins de 30 min apr\u00e8s le trade d\u2019avant", "title_en": "Less than 30 min after the previous trade", "where": [{"field": "gap_min", "op": "<", "value": 30}]},
    {"id": "weekend", "title_fr": "Le week-end", "title_en": "On weekends", "where": [{"field": "wday", "op": "in", "value": [5, 6]}]},
    {"id": "asia", "title_fr": "La nuit (00\u201308 h UTC)", "title_en": "At night (00\u201308 UTC)", "where": [{"field": "hour", "op": "<", "value": 8}]},
    {"id": "europe", "title_fr": "En journ\u00e9e (08\u201316 h UTC)", "title_en": "During the day (08\u201316 UTC)", "where": [{"field": "hour", "op": "between", "value": [8, 15]}]},
    {"id": "us", "title_fr": "En soir\u00e9e (16\u201324 h UTC)", "title_en": "In the evening (16\u201324 UTC)", "where": [{"field": "hour", "op": ">=", "value": 16}]},
    {"id": "long", "title_fr": "Quand le robot ach\u00e8te", "title_en": "When the robot buys", "where": [{"field": "dir", "op": "==", "value": "BUY"}]},
]
_CUTS_CACHE = {"m": None, "cuts": None}


def _labo_card():
    """2026-10-03 (owner): the lab's own demo robot, as a card. Start
    balance from the bot's first log line, trades/net from its journal,
    what it runs from the labo package (deploy / watch / confirmed)."""
    import csv as _csv, re as _re
    out = {"since": None, "start": None, "trades": 0, "net": 0.0, "won": 0, "alive": False,
           "deployed": None, "watch": None, "confirmed": None, "reverted": None}
    try:
        first = open(os.path.join(DIR, "bos_bot_labo.log"), encoding="utf-8", errors="replace").readline()
        m = _re.search(r"balance ([0-9.]+)", first)
        out["start"] = float(m.group(1)) if m else None
        out["since"] = first[:10]
    except Exception:
        pass
    try:
        w = json.load(open(os.path.join(DIR, "bos_weather_labo.json"), encoding="utf-8"))
        out["alive"] = (time.time() - float(w.get("updated") or 0)) < 600
    except Exception:
        pass
    try:
        for r in _csv.DictReader(open(os.path.join(DIR, "bos_journal_labo.csv"), encoding="utf-8", errors="replace")):
            if r.get("is_add") == "True" or (r.get("outcome") or "").lower() not in ("win", "loss"):
                continue
            out["trades"] += 1
            p = float(r.get("profit_usd") or 0)
            out["net"] = round(out["net"] + p, 2)
            if p > 0:
                out["won"] += 1
    except Exception:
        pass
    try:
        pk = json.load(open(os.path.join(DIR, "owl_packages.json"), encoding="utf-8"))["packages"]["labo"]
        for k in ("_deployed", "_watch", "_confirmed", "_reverted"):
            if pk.get(k):
                out[k.strip("_")] = pk[k]
    except Exception:
        pass
    # 2026-10-03 (owner): the hand brake and last night's rehearsal of the gates
    try:
        p = json.load(open(os.path.join(DIR, "lab", "pause.json"), encoding="utf-8"))
        out["paused"] = bool(p.get("on"))
        out["paused_since"] = p.get("date") if p.get("on") else None
    except Exception:
        out["paused"] = False
    try:
        r = json.load(open(os.path.join(DIR, "lab", "rehearsal.json"), encoding="utf-8"))
        out["rehearsal"] = {"date": r.get("date"), "ok": bool(r.get("ok")), "passed": r.get("passed"), "total": r.get("total"),
                            "misses": [{"fr": s.get("fr"), "en": s.get("en")} for s in r.get("steps", []) if not s.get("ok")]}
    except Exception:
        pass
    return out


def _critiques_recent(n=10):
    """The critic's last n verdicts, oldest first, with the idea's title."""
    try:
        d = json.load(open(os.path.join(DIR, "lab", "critiques.json"), encoding="utf-8"))
        lst = d if isinstance(d, list) else d.get("critiques", [])
        lst = sorted([c for c in lst if isinstance(c, dict) and c.get("id")], key=lambda c: c.get("date", ""))[-n:]
        return [{k: c.get(k) for k in ("id", "date", "verdict", "fr", "en")} for c in lst]
    except Exception:
        return []


def _veille(n=8):
    """The last n lines of lab/veille.jsonl, newest last."""
    out = []
    try:
        for ln in open(os.path.join(DIR, "lab", "veille.jsonl"), encoding="utf-8").read().splitlines()[-n:]:
            try:
                o = json.loads(ln)
                if isinstance(o, dict) and (o.get("fr") or o.get("en")):
                    out.append({k: o.get(k) for k in ("t", "kind", "fr", "en", "ref")})
            except Exception:
                continue
    except Exception:
        pass
    return out


def lab_cuts():
    """Every pile, from lab/cuts.json. Written once with the eleven starting
    piles (by "kino"); the chercheur appends its own."""
    try:
        m = os.path.getmtime(LAB_CUTS)
    except OSError:
        doc = {"cuts": [dict(c, by="kino", date="2026-09-29", status="open",
                             why_fr="Une des onze piles de d\u00e9part.", why_en="One of the eleven starting piles.") for c in CUT_SEED]}
        tmp = LAB_CUTS + ".tmp"
        json.dump(doc, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, LAB_CUTS)
        m = os.path.getmtime(LAB_CUTS)
    if _CUTS_CACHE["m"] != m:
        try:
            doc = json.load(open(LAB_CUTS, encoding="utf-8"))
            cuts = [c for c in doc.get("cuts", []) if isinstance(c, dict)]
        except Exception:
            cuts = list(CUT_SEED)
        _CUTS_CACHE.update(m=m, cuts=cuts)
    return list(_CUTS_CACHE["cuts"] or [])


def cut_error(c):
    """'' when the pile is well formed, else what is wrong with it."""
    if not isinstance(c.get("id"), str) or not c["id"].strip():
        return "id manquant"
    if not (c.get("title_fr") and c.get("title_en")):
        return "titre manquant"
    w = c.get("where")
    if not isinstance(w, list) or not (1 <= len(w) <= 3):
        return "where : 1 \u00e0 3 conditions"
    for k in w:
        if not isinstance(k, dict) or k.get("field") not in CUT_FIELDS or k.get("op") not in CUT_OPS:
            return "condition : champ ou op\u00e9rateur inconnu"
        v = k.get("value")
        if k["op"] == "in" and not (isinstance(v, list) and v):
            return "in : une liste"
        if k["op"] == "between" and not (isinstance(v, list) and len(v) == 2):
            return "between : [bas, haut]"
        if k["op"] in ("<", "<=", ">", ">=") and not isinstance(v, (int, float)):
            return "comparaison : un nombre"
    return ""


def _cut_match(where, r):
    for k in where:
        f, op, v = k["field"], k["op"], k["value"]
        x = r.get(f)
        if x is None:
            return False
        try:
            if op == "<" and not x < v: return False
            if op == "<=" and not x <= v: return False
            if op == ">" and not x > v: return False
            if op == ">=" and not x >= v: return False
            if op == "==" and not x == v: return False
            if op == "!=" and not x != v: return False
            if op == "in" and x not in v: return False
            if op == "between" and not (v[0] <= x <= v[1]): return False
        except TypeError:
            return False
    return True


def lab_candidates(J):
    """Each pile, cut against the rest, with the chronological halves.
    n < 30 = too early; halves that agree = worth a replay; halves that
    disagree = noise for now; 80 % the same trades as an older pile =
    a duplicate."""
    if not J:
        return []
    mid = J[len(J) // 2]["t"]
    R = []
    for i, r in enumerate(J):
        g = time.gmtime(r["t"])
        R.append(dict(r, hour=g.tm_hour, wday=g.tm_wday,
                      gap_min=((r["t"] - J[i - 1]["x"]) / 60.0) if i else 1e9,
                      dur_min=max(0.0, (r["x"] - r["t"]) / 60.0),
                      prev_win=(J[i - 1]["win"] if i else None),
                      t=r["t"]))
    cuts = [c for c in lab_cuts() if c.get("status", "open") != "retired"]
    strict = len(cuts) > len(CUT_SEED)
    out, picks = [], {}
    for c in cuts:
        base = {"id": c.get("id"), "name_fr": c.get("title_fr"), "name_en": c.get("title_en"), "by": c.get("by", "kino"),
                "date": c.get("date"), "why_fr": c.get("why_fr", ""), "why_en": c.get("why_en", "")}
        err = cut_error(c)
        if err:
            out.append(dict(base, n=0, win=None, net=0, rest_n=len(R), rest_win=None, h1=None, h2=None, h1n=0, h2n=0,
                            agree=False, label="invalide", error=err))
            continue
        idx = [i for i, r in enumerate(R) if _cut_match(c["where"], r)]
        if not idx:
            continue
        sel = set(idx)
        rows = [R[i] for i in idx]
        rest = [r for i, r in enumerate(R) if i not in sel]
        w = _wr(rows); wr = _wr(rest)
        h1 = [r for r in rows if r["t"] < mid]; h2 = [r for r in rows if r["t"] >= mid]
        r1 = [r for r in rest if r["t"] < mid]; r2 = [r for r in rest if r["t"] >= mid]
        def diff(a, b):
            wa, wb = _wr(a)["win"], _wr(b)["win"]
            return None if (wa is None or wb is None or len(a) < 5 or len(b) < 5) else (wa - wb)
        d1, d2 = diff(h1, r1), diff(h2, r2)
        agree = (d1 is not None and d2 is not None and ((d1 > 0) == (d2 > 0)))
        gap_ok = (not strict) or (w["win"] is not None and wr["win"] is not None and abs(w["win"] - wr["win"]) >= CUT_STRICT_GAP)
        label = "trop_tot" if w["n"] < CUT_MIN_N else ("a_tester" if (agree and gap_ok) else "divergent")
        picks[c["id"]] = sel
        out.append(dict(base, n=w["n"], win=w["win"], net=w["net"], rest_n=wr["n"], rest_win=wr["win"],
                        h1=_wr(h1)["win"], h2=_wr(h2)["win"], h1n=len(h1), h2n=len(h2), agree=agree, label=label))
    # a later pile that is mostly the same trades as an older one says
    # nothing new; it is shown as such and never asked about
    for i, c in enumerate(out):
        a = picks.get(c["id"])
        if not a:
            continue
        for e in out[:i]:
            b = picks.get(e["id"])
            if not b or e.get("dup_of"):
                continue
            j = len(a & b) / float(len(a | b))
            if j >= CUT_DUP:
                c["label"] = "doublon"; c["dup_of"] = e["id"]; c["dup_name_fr"] = e["name_fr"]; c["dup_name_en"] = e["name_en"]
                break
    return out

# ---- 2026-09-29 (owner): "is there a way to see how an idea is doing, has
# it moved to testing, was it approved, is it live in the bot now, is there
# a story board?" One journey per idea, derived from the files that already
# exist (registry, proposals, auto_history, twins) plus lab/decisions.json
# written by the owner's Approuver / Rejeter. Five steps:
#   1 idea -> 2 tested on the past -> 3 tried for pretend -> 4 in the robot
#   (2026-10-02: "decided" dropped - the lab deploys a duel winner itself)
LAB_ALIAS = {"twin_06": "rr06", "half_tp": "rr04", "sunday": "nosun", "weekend": "nowe",
             "wait": "wait30", "sizehot": "hothalf"}
LAB_DEC = os.path.join(DIR, "lab", "decisions.json")
# 2026-10-02 (owner): a story line never shows the bare letter
VW_FR = {"A": "mieux sur les deux moiti\u00e9s", "B": "un peu mieux", "C": "non", "=": "pareil"}
VW_EN = {"A": "better on both halves", "B": "a little better", "C": "no", "=": "same"}


def _vw(v, en=False):
    return (VW_EN if en else VW_FR).get(str(v or ""), str(v or ""))


def _lab_hist():
    rows = []
    try:
        with open(os.path.join(DIR, "lab", "auto_history.jsonl"), encoding="utf-8") as f:
            for ln in f:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
    except Exception:
        pass
    return rows


def lab_journeys(items, props, twins, auto, decisions, arch_on=None):
    arch_on = arch_on or {}
    hist = _lab_hist()
    by_id = {}
    for r in hist:
        by_id.setdefault(r.get("id"), []).append(r)
    av = {v.get("id"): v for v in (auto.get("variants") or [])}
    tw = {t.get("id"): t for t in twins}
    dec = decisions.get("decisions", {}) if isinstance(decisions, dict) else {}
    base = auto.get("base") or {}
    # 2026-10-02 (phase 3): the critic's last word per idea
    CR = {}
    try:
        _cd = json.load(open(os.path.join(DIR, "lab", "critiques.json"), encoding="utf-8"))
    except Exception:
        _cd = {}
    for c in sorted([x for x in (_cd if isinstance(_cd, list) else _cd.get("critiques", [])) if isinstance(x, dict)], key=lambda c: c.get("date", "")):
        if c.get("id"):
            CR[c["id"]] = {k: c.get(k) for k in ("date", "verdict", "fr", "en")}
    out = []
    seen = set()

    def build(jid, keys, title_fr, title_en, kind, fam, note_fr, note_en, nums_fr, nums_en, src, date, reg=None, prop=None):
        ev = []
        st = {"idea": {"date": date, "src": src}}
        who_fr = {"registry": "Une id\u00e9e du Owl ou des vrais trades", "proposal": "Propos\u00e9e par le chercheur",
                  "twin": "Lanc\u00e9e par le chercheur apr\u00e8s un A", "battery": "Une question que le moteur pose chaque nuit"}
        who_en = {"registry": "An idea from the Owl or the real trades", "proposal": "Proposed by the chercheur",
                  "twin": "Started by the chercheur after an A", "battery": "A question the engine asks every night"}
        ev.append({"d": date or "", "fr": who_fr.get(kind, ""), "en": who_en.get(kind, ""), "k": "idea"})
        # 2 - replayed on the past
        rows = []
        for k in keys:
            rows += by_id.get(k, [])
        rows.sort(key=lambda r: r.get("d", ""))
        rp = None
        if rows:
            last = rows[-1]
            streak = 0
            for r in reversed(rows):
                if r.get("verdict") == last.get("verdict"):
                    streak += 1
                else:
                    break
            nights = len({r.get("d") for r in rows})
            rp = {"verdict": last.get("verdict"), "nights": nights, "streak": streak, "last": last.get("d"),
                  "trades": last.get("trades")}
            v = next((av[k] for k in keys if k in av), None)
            if v:
                rp.update({"engine": v.get("engine"), "byref": v.get("byref"),
                       "diff_net": v.get("diff_net"), "diff_worst": v.get("diff_worst"),
                           "h1": round(((v.get("h1") or {}).get("net") or 0) - ((base.get("h1") or {}).get("net") or 0), 2),
                           "h2": round(((v.get("h2") or {}).get("net") or 0) - ((base.get("h2") or {}).get("net") or 0), 2),
                           "long": v.get("long"), "real": v.get("real")})
            first = rows[0]
            ev.append({"d": first.get("d", ""), "fr": "Test\u00e9e pour la premi\u00e8re fois : " + _vw(first.get("verdict")),
                       "en": "Tested for the first time: " + _vw(first.get("verdict"), True), "k": "replay"})
            if nights > 1:
                ev.append({"d": last.get("d", ""), "fr": "Derni\u00e8re nuit : " + _vw(last.get("verdict")) + (" (" + str(streak) + " nuits de suite)" if streak > 1 else ""),
                           "en": "Last night: " + _vw(last.get("verdict"), True) + (" (" + str(streak) + " nights in a row)" if streak > 1 else ""), "k": "replay"})
        elif prop and prop.get("pretest"):
            pt = prop["pretest"]
            rp = {"verdict": pt.get("verdict"), "nights": 0, "streak": 0, "last": (pt.get("at") or "")[:10], "pretest": True,
                  "diff_net": round((pt.get("net") or 0) - (pt.get("base_net") or 0), 2),
                  "diff_worst": round((pt.get("worst") or 0) - (pt.get("base_worst") or 0), 2),
                  "h1": round((pt.get("h1") or 0) - (pt.get("base_h1") or 0), 2), "h2": round((pt.get("h2") or 0) - (pt.get("base_h2") or 0), 2),
                  "long": pt.get("long"), "real": pt.get("real")}
            ev.append({"d": max((pt.get("at") or "")[:10], date or ""), "fr": "Premier test, par le chercheur : " + _vw(pt.get("verdict")),
                       "en": "First test, by the chercheur: " + _vw(pt.get("verdict"), True), "k": "replay"})
        elif reg and reg.get("verdict") in ("A", "B", "C"):
            rp = {"verdict": reg.get("verdict"), "nights": 0, "streak": 0, "last": reg.get("date"), "hand": True}
            ev.append({"d": reg.get("date", ""), "fr": "V\u00e9rifi\u00e9e \u00e0 la main : " + _vw(reg.get("verdict")),
                       "en": "Checked by hand: " + _vw(reg.get("verdict"), True), "k": "replay"})
        if rp:
            st["replay"] = rp
        _cr = next((CR[k] for k in keys if k in CR), None)
        if _cr:
            _w = {"passe": ("Le critique a essay\u00e9 de la casser, sans y arriver", "The critic tried to break it and could not"),
                  "doute": ("Le critique doute", "The critic doubts"),
                  "bloque": ("Le critique a dit non", "The critic said no")}.get(_cr.get("verdict"), ("Le critique", "The critic"))
            ev.append({"d": _cr.get("date", ""), "fr": _w[0] + " : " + str(_cr.get("fr") or ""), "en": _w[1] + ": " + str(_cr.get("en") or _cr.get("fr") or ""), "k": "replay"})
        # 3 - tested for pretend
        t = next((tw[k] for k in keys if k in tw), None)
        if t:
            started = (t.get("started") or "")[:10]
            days = 0
            try:
                days = max(0, int((time.time() - datetime.fromisoformat(t["started"]).timestamp()) / 86400))
            except Exception:
                pass
            st["test"] = {"started": started, "days": days, "trades": t.get("trades"), "net": t.get("net"),
                          "win": t.get("win"), "alive": t.get("alive"), "status": t.get("status"), "by": t.get("by"),
                          "reason": t.get("reason"), "duel": t.get("duel")}
            ev.append({"d": started, "fr": "Un jumeau joue pour de faux" + (" (lanc\u00e9 par le Owl)" if t.get("by") == "owner" else " (lanc\u00e9 par le chercheur)"),
                       "en": "A twin plays for pretend" + (" (started by the Owl)" if t.get("by") == "owner" else " (started by the chercheur)"), "k": "test"})
            if t.get("status") == "stopped":
                ev.append({"d": (t.get("stopped") or "")[:10], "fr": "Jumeau arr\u00eat\u00e9", "en": "Twin stopped", "k": "test"})
            # 2026-10-02: a twin that won its duel went into the lab's robot
            # by itself (lab/twin_judge.py deploy). That IS "in the robot".
            if t.get("status") == "deployed":
                st["live"] = {"date": (t.get("deployed") or ""), "labo": True}
                ev.append({"d": t.get("deployed") or "", "fr": "Entr\u00e9e toute seule dans le robot du labo",
                           "en": "Went into the lab\u2019s robot by itself", "k": "live"})
                # 2026-10-02: the lab's robot is watched after the deploy
                # (lab/twin_judge.py watch_deployed); the card shows where it stands
                try:
                    _pk = json.load(open(os.path.join(DIR, "owl_packages.json"), encoding="utf-8"))["packages"]["labo"]
                    if (_pk.get("_watch") or {}).get("id") == t.get("id"):
                        st["live"]["watch"] = _pk["_watch"]
                    if _pk.get("_confirmed"):
                        ev.append({"d": _pk["_confirmed"], "fr": "Confirm\u00e9e dans le robot du labo : devant le vrai robot sur 30 trades",
                                   "en": "Confirmed in the lab\u2019s robot: ahead of the real robot over 30 trades", "k": "live"})
                except Exception:
                    pass
            if t.get("status") == "reverted":
                ev.append({"d": t.get("reverted") or "", "fr": "Ressortie du robot du labo : derri\u00e8re le vrai robot une fois dedans",
                           "en": "Came back out of the lab\u2019s robot: behind the real robot once inside", "k": "test"})
        elif reg and reg.get("status") == "forward":
            st["test"] = {"started": reg.get("date"), "days": None, "forward": True}
            ev.append({"d": reg.get("date", ""), "fr": "Observ\u00e9e en direct, sans argent", "en": "Watched live, no money", "k": "test"})
        # 4 - decided
        d = next((dec[k] for k in keys if k in dec), None)
        if d:
            lab = d.get("by") == "lab"
            who_fr, who_en = ("Le labo", "The lab") if lab else ("Le Owl", "The Owl")
            st["decision"] = {"d": d.get("d"), "date": d.get("date"), "note": d.get("note", ""), "by": who_fr}
            ev.append({"d": d.get("date", ""), "fr": (who_fr + " a dit oui" if d.get("d") == "yes" else who_fr + " a dit non") + ((" : " + d.get("note")) if d.get("note") else ""),
                       "en": (who_en + " said yes" if d.get("d") == "yes" else who_en + " said no") + ((": " + d.get("note")) if d.get("note") else ""), "k": "decision"})
        elif reg and reg.get("status") == "rejected":
            st["decision"] = {"d": "no", "date": reg.get("date"), "by": "Kino"}
            ev.append({"d": reg.get("date", ""), "fr": "\u00c9cart\u00e9e : les chiffres ont dit non", "en": "Dropped: the numbers said no", "k": "decision"})
        elif reg and reg.get("status") == "deployed":
            st["decision"] = {"d": "yes", "date": reg.get("date"), "by": "Kino"}
        # 5 - in the robot
        if reg and reg.get("status") == "deployed":
            st["live"] = {"date": reg.get("date")}
            ev.append({"d": reg.get("date", ""), "fr": "Dans le robot", "en": "In the robot", "k": "live"})
        # where it stands
        # 2026-10-02 (owner): four columns. "Decided" is gone - a yes means
        # the idea went in (the lab deploys it itself), and a no is a test
        # that said no, which the Tested column folds. A proposal that only
        # has the chercheur's first test has not had its night: still an idea.
        if "live" in st:
            step, col = 4, "live"
        elif "test" in st:
            step, col = 3, "test"
        elif ("replay" in st and not st["replay"].get("pretest")) or "decision" in st:
            step, col = 2, "replay"
        else:
            step, col = 1, "idea"
        ev = [e for e in ev if e.get("fr")]
        ev.sort(key=lambda e: (0 if e.get("k") == "idea" else 1, e.get("d") or ""))
        out.append({"id": jid, "keys": keys, "title_fr": title_fr, "title_en": title_en, "kind": kind, "family": fam,
                    "note_fr": note_fr, "note_en": note_en, "nums_fr": nums_fr, "nums_en": nums_en, "src": src,
                    "date": date, "steps": st, "step": step, "col": col, "events": ev,
                    "cfg": (prop or {}).get("cfg") or (t or {}).get("cfg"),
                    "reg_status": (reg or {}).get("status"), "robot": (reg or {}).get("robot"),
                    "reference": bool((reg or {}).get("reference")),
                    "archived": (jid in arch_on) or any(k in arch_on for k in keys),
                    "critique": next((CR[k] for k in keys if k in CR), None),
                    "stale": bool(rp and rp.get("engine") and rp.get("engine") != auto.get("engine"))})
        seen.update(keys)

    for it in items:
        keys = [it["id"]] + ([LAB_ALIAS[it["id"]]] if it["id"] in LAB_ALIAS else [])
        build(it["id"], keys, it.get("title_fr"), it.get("title_en"), "registry", it.get("family"), it.get("note_fr"), it.get("note_en"),
              it.get("nums_fr"), it.get("nums_en"), it.get("src"), it.get("date"), reg=it)
    for p in props:
        if p.get("id") in seen:
            continue
        build(p["id"], [p["id"]], p.get("title_fr"), p.get("title_en"), "proposal", p.get("family"), p.get("why_fr"), p.get("why_en"),
              "", "", "chercheur", p.get("date"), prop=p)
    for t in twins:
        if t.get("id") in seen:
            continue
        build(t["id"], [t["id"]], t.get("title_fr"), t.get("title_en"), "twin", "rythme", "", "", "", "", "chercheur",
              (t.get("started") or "")[:10])
    # 2026-09-29 (owner): everything replayed is a card - the standing menu
    # of nightly questions too; the page folds the C's
    for v in (auto.get("variants") or []):
        vid = v.get("id")
        if not vid or vid in seen:
            continue
        first = min((r.get("d", "") for r in by_id.get(vid, []) if r.get("d")), default=(auto.get("updated") or "")[:10])
        build(vid, [vid], v.get("title_fr"), v.get("title_en"), "battery", v.get("family"), "", "", "", "", "battery", first,
              prop={"cfg": v.get("cfg")})
    order = {"live": 0, "test": 1, "replay": 2, "idea": 3}
    out.sort(key=lambda j: (order.get(j["col"], 9), j.get("date") or ""), reverse=False)
    return out


def _lab_cfg_for(jid):
    """The dial config behind an idea id: a proposal, a twin, or a battery line."""
    try:
        for p in json.load(open(os.path.join(DIR, "lab", "proposals.json"), encoding="utf-8")).get("proposals", []):
            if p.get("id") == jid and isinstance(p.get("cfg"), dict):
                return p.get("title_fr"), p.get("title_en"), p["cfg"]
    except Exception:
        pass
    try:
        sys.path.insert(0, DIR)
        import lab_researcher as LR
        for vid, fr, en, fam, cfg in LR.BATTERY:
            if vid == jid:
                return fr, en, cfg
    except Exception:
        pass
    return None


def lab_decide(jid, d, note):
    """Owner's Approuver / Rejeter / Lancer un jumeau. Returns (ok, msg)."""
    jid = LAB_ALIAS.get(jid, jid) if d == "twin" else jid
    try:
        dec = json.load(open(LAB_DEC, encoding="utf-8"))
    except Exception:
        dec = {"decisions": {}}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if d in ("yes", "no"):
        dec.setdefault("decisions", {})[jid] = {"d": d, "date": today, "note": (note or "")[:200], "by": "owner"}
        tmp = LAB_DEC + ".tmp"
        json.dump(dec, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, LAB_DEC)
    if d == "no":
        # a rejected idea's twin stops (owner 2026-09-29: auto-delete what failed)
        try:
            twp = os.path.join(DIR, "lab", "twins.json")
            tw = json.load(open(twp, encoding="utf-8"))
            hit = False
            for t in tw.get("twins", []):
                if t.get("id") in (jid, LAB_ALIAS.get(jid)) and t.get("status") == "running":
                    t["status"] = "stopped"; t["stopped"] = today; hit = True
                    subprocess.Popen(["powershell", "-NoProfile", "-Command",
                                      "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*bos_paper_variant.py " + t["id"] + "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if hit:
                tmp = twp + ".tmp"
                json.dump(tw, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                os.replace(tmp, twp)
        except Exception:
            pass
    if d == "twin":
        got = _lab_cfg_for(jid)
        if not got:
            return False, "no dials for this idea"
        fr, en, cfg = got
        try:
            sys.path.insert(0, DIR)
            import lab_researcher as LR
            import harness as H
            ok = LR.ensure_twin(jid, fr, en, H.cfg_of(cfg), "owner")
            if ok:
                try:
                    import twin_judge as TJ
                    TJ.emit("twin_started", ("\U0001f9ea Le labo : un jumeau d\u00e9marre",
                                             f"Le Owl lance \u00ab {fr} \u00bb : une copie du robot l\u2019essaie pour de faux \u00e0 partir de maintenant."),
                            ("\U0001f9ea The lab: a twin starts",
                             f"The Owl started \u201c{en}\u201d: a copy of the robot tries it for pretend from now on."), members=True)
                except Exception:
                    pass
                tw = json.load(open(os.path.join(DIR, "lab", "twins.json"), encoding="utf-8"))
                for t in tw.get("twins", []):
                    if t.get("id") == jid:
                        t["by"] = "owner"
                tmp = os.path.join(DIR, "lab", "twins.json.tmp")
                json.dump(tw, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                os.replace(tmp, os.path.join(DIR, "lab", "twins.json"))
        except Exception as e:
            return False, str(e)[:80]
    _LAB_CACHE.update(t=0.0, data=None)
    _PROOF_CACHE.clear()
    return True, "ok"

# ---- 2026-09-29 (owner): "La preuve" - the replay of the whole strategy,
# the real trades against it, and whether to stay in. Numbers come from
# lab/proof.json (lab/proof_build.py, nightly); the twins come live. ----
_PROOF_CACHE = {}


def _proof_lab():
    """What the lab changed lately, for the slide that says the strategy is
    not frozen (owner 2026-09-30)."""
    try:
        L = lab_payload()
    except Exception:
        return {}
    auto = L.get("auto") or {}
    props = [x for x in (L.get("proposals") or []) if x.get("status") in (None, "pending")]
    tw = [t for t in (L.get("twins") or []) if t.get("status") == "running"]
    return {"counts": auto.get("counts") or {}, "days": auto.get("days"),
            "updated": auto.get("updated"), "engine": auto.get("engine"),
            "to_try": len(props), "twins": len(tw),
            "rules": len([i for i in (L.get("items") or []) if i.get("status") == "deployed"]),
            "archived": len(L.get("archive") or {})}


def proof_payload(pkg="base"):
    _c = _PROOF_CACHE.get(pkg)
    if _c and time.time() - _c[0] < 300:
        return _c[1]
    try:
        p = json.load(open(os.path.join(DIR, "lab", "proof.json"), encoding="utf-8"))
    except Exception:
        p = {}
    PKGS = p.get("packages") or {}
    # the strategy itself: one canonical run on the reference account, so the
    # headline never depends on whose balance it is
    base = PKGS.get("base") or (p.get("base") or {})
    # the member's own rules, used only for "does my bot match the test?"
    mine_run = PKGS.get(pkg) or base
    full, h1, h2 = base.get("full") or {}, base.get("h1") or {}, base.get("h2") or {}
    days = round(p.get("days") or 0)
    lights = []
    # 1 - on the past, the strategy makes money
    if full.get("net") is None:
        lights.append({"k": "replay", "c": "grey", "fr": "Pas encore de test cette nuit.", "en": "No test yet tonight."})
    elif full["net"] > 0 and h1.get("net", 0) > 0 and h2.get("net", 0) > 0:
        lights.append({"k": "replay", "c": "green",
                       "fr": f"Sur les {days} derniers jours, la strat\u00e9gie gagne ({full['net']:+.0f} $), et elle gagne sur chacune des deux moiti\u00e9s de la p\u00e9riode.",
                       "en": f"Over the last {days} days the strategy makes money ({full['net']:+.0f} $), and it does so on each half of the period."})
    elif full["net"] > 0:
        lights.append({"k": "replay", "c": "amber",
                       "fr": f"Sur les {days} derniers jours, la strat\u00e9gie gagne au total ({full['net']:+.0f} $) mais perd sur une moiti\u00e9 de la p\u00e9riode ({h1.get('net',0):+.0f} $ puis {h2.get('net',0):+.0f} $). \u00c0 surveiller.",
                       "en": f"Over the last {days} days the strategy wins overall ({full['net']:+.0f} $) but loses on one half of the period ({h1.get('net',0):+.0f} $ then {h2.get('net',0):+.0f} $). Watch it."})
    else:
        lights.append({"k": "replay", "c": "red",
                       "fr": f"Sur les {days} derniers jours, la strat\u00e9gie perd ({full['net']:+.0f} $). Elle est en question.",
                       "en": f"Over the last {days} days the strategy loses ({full['net']:+.0f} $). It is in question."})
    # 2 - in real life, it follows the test
    ex, un = p.get("expected") or {}, p.get("union") or {}
    if not un or not ex:
        lights.append({"k": "track", "c": "grey", "fr": "Pas encore assez de vrais trades.", "en": "Not enough real trades yet."})
    else:
        n = un.get("trades") or 0
        rs = ((un.get("replay_same_entries") or {}).get("net"))
        gap = abs((un.get("net") or 0) - (ex.get("net") or 0))
        tol = 0.5 * abs(ex.get("net") or 0) + 20
        same_sign = ((un.get("net") or 0) >= 0) == ((ex.get("net") or 0) >= 0)
        since = (un.get("since") or "")
        since_fr = since[8:10] + "/" + since[5:7] if len(since) >= 10 else since
        band = proof_band(full.get("pnls"), n)
        inside = bool(band and band["lo"] <= (un.get("net") or 0) <= band["hi"])
        if n < 30:
            c = "amber"
            fr = f"{n} vrais trades depuis le {since_fr} : trop peu pour juger. Sur les m\u00eames jours, le test attendait {ex.get('net',0):+.0f} $ ; en vrai, {un.get('net',0):+.0f} $."
            en = f"{n} real trades since {since}: too few to judge. Over the same days the test expected {ex.get('net',0):+.0f} $; in real life, {un.get('net',0):+.0f} $."
            if band:
                fr += (f" Pour {n} trades, le test consid\u00e8re normal tout r\u00e9sultat entre {band['lo']:+.0f} et {band['hi']:+.0f} $ : " + ("on est dedans." if inside else "on est en dehors, \u00e0 surveiller de pr\u00e8s."))
                en += (f" For {n} trades the test calls normal anything between {band['lo']:+.0f} and {band['hi']:+.0f} $: " + ("we are inside." if inside else "we are outside, watch closely."))
        elif same_sign or gap <= tol:
            c = "green"
            fr = f"Les {n} vrais trades suivent le test : {un.get('net',0):+.0f} $ en vrai, {ex.get('net',0):+.0f} $ attendus sur les m\u00eames jours."
            en = f"The {n} real trades follow the test: {un.get('net',0):+.0f} $ in real life, {ex.get('net',0):+.0f} $ expected over the same days."
        elif gap <= 2 * tol:
            c = "amber"
            fr = f"Les vrais trades s\u2019\u00e9loignent du test : {un.get('net',0):+.0f} $ en vrai, {ex.get('net',0):+.0f} $ attendus. \u00c0 surveiller."
            en = f"The real trades drift from the test: {un.get('net',0):+.0f} $ in real life, {ex.get('net',0):+.0f} $ expected. Watch it."
        else:
            c = "red"
            fr = f"Les vrais trades ne suivent pas le test : {un.get('net',0):+.0f} $ en vrai, {ex.get('net',0):+.0f} $ attendus."
            en = f"The real trades do not follow the test: {un.get('net',0):+.0f} $ in real life, {ex.get('net',0):+.0f} $ expected."
        if rs is not None:
            fr += f" Le test sur exactement les m\u00eames entr\u00e9es : {rs:+.0f} $."
            en += f" The test on exactly the same entries: {rs:+.0f} $."
        lights.append({"k": "track", "c": c, "fr": fr, "en": en})
    # 3 - no trial copy beats the robot
    twins = []
    try:
        twins = [t for t in (lab_payload().get("twins") or []) if t.get("status") == "running"]
    except Exception:
        pass
    ahead = [t for t in twins if ((t.get("duel") or {}).get("status") == "ahead")]
    ready = [t for t in ahead if (t.get("duel") or {}).get("ready")]
    if ready:
        t = ready[0]
        lights.append({"k": "lab", "c": "red", "fr": f"Une copie d\u2019essai fait mieux que le robot apr\u00e8s 30 trades : \u00ab {t.get('title_fr')} \u00bb. Le Owl doit d\u00e9cider.",
                       "en": f"A trial copy beats the robot after 30 trades: \u201c{t.get('title_en')}\u201d. The Owl must decide."})
    elif ahead:
        t = ahead[0]
        k = ((t.get("duel") or {}).get("twin") or {}).get("trades", 0)
        lights.append({"k": "lab", "c": "amber", "fr": f"Une copie d\u2019essai est devant le robot, mais c\u2019est trop t\u00f4t pour conclure ({k} trades sur 30) : \u00ab {t.get('title_fr')} \u00bb.",
                       "en": f"A trial copy is ahead of the robot, but it is too early to conclude ({k} of 30 trades): \u201c{t.get('title_en')}\u201d."})
    else:
        lights.append({"k": "lab", "c": "green", "fr": f"Aucune des {len(twins)} copies d\u2019essai ne fait mieux que le robot pour l\u2019instant. Le robot reste notre meilleure version.",
                       "en": f"None of the {len(twins)} trial copies beats the robot for now. The robot is still our best version."})
    rank = {"green": 0, "grey": 1, "amber": 2, "red": 3}
    worst = max(lights, key=lambda l: rank[l["c"]])["c"]
    overall = {"green": ("Oui, on reste.", "Yes, we stay."), "grey": ("Trop t\u00f4t pour dire.", "Too early to say."),
               "amber": ("On reste, en surveillant.", "We stay, and keep watching."), "red": ("En question.", "In question.")}[worst]
    out = {"updated": p.get("updated"), "days": days, "days_long": p.get("days_long"), "symbol": p.get("symbol"),
           "base": {"full": {k: v for k, v in full.items() if k != "pnls"},
                    "h1": {k: h1.get(k) for k in ("net", "worst_debt", "trades", "wr")},
                    "h2": {k: h2.get(k) for k in ("net", "worst_debt", "trades", "wr")}},
           "base_long": {"full": {k: v for k, v in ((p.get("base_long") or {}).get("full") or {}).items() if k != "curve"}} if p.get("base_long") else None,
           "expected": ex, "union": {k: v for k, v in un.items() if k != "replay_same_entries"} if un else None,
           "replay_same": (un.get("replay_same_entries") if un else None),
           "sources": p.get("sources") or {}, "rules": p.get("rules") or [],
           "twins": [{"id": t.get("id"), "title_fr": t.get("title_fr"), "title_en": t.get("title_en"),
                      "status": (t.get("duel") or {}).get("status"), "trades": t.get("trades"),
                      "net": t.get("net"), "real_net": ((t.get("duel") or {}).get("real") or {}).get("net")} for t in twins],
           "band": (proof_band(full.get("pnls"), (un.get("trades") or 0)) if un else None),
           "stats": proof_stats(full, days), "stats_long": proof_stats((p.get("base_long") or {}).get("full"), p.get("days_long") or 0),
           "lights": lights, "overall": {"c": worst, "fr": overall[0], "en": overall[1]},
           "package": pkg, "day_cap": mine_run.get("day_cap"), "jar": base.get("jar"),
           "ref_balance": 200.0, "ref_lot": base.get("lot") or 0.02,
           "mine_run": {"net": (mine_run.get("full") or {}).get("net"),
                        "trades": (mine_run.get("full") or {}).get("trades"),
                        "wr": (mine_run.get("full") or {}).get("wr"),
                        "worst": (mine_run.get("full") or {}).get("worst_debt"),
                        "balance": mine_run.get("balance"), "lot": mine_run.get("lot"),
                        "day_cap": mine_run.get("day_cap")},
           # what the lab is doing to the strategy right now
           "lab": _proof_lab()}
    _PROOF_CACHE[pkg] = (time.time(), out)
    return out


def proof_stats(full, days):
    """The numbers a trader asks for, from the replay's per-trade money."""
    pn = (full or {}).get("pnls") or []
    if not pn:
        return None
    wins = [x for x in pn if x > 0]
    losses = [x for x in pn if x < 0]
    gw, gl = sum(wins), -sum(losses)
    streak = worst_streak = 0
    for x in pn:
        streak = streak + 1 if x <= 0 else 0
        worst_streak = max(worst_streak, streak)
    cum = pk = mdd = 0.0
    for x in pn:
        cum += x
        pk = max(pk, cum)
        mdd = max(mdd, pk - cum)
    return {"trades": len(pn), "wr": round(100 * len(wins) / len(pn), 1), "pf": (round(gw / gl, 2) if gl > 0 else None),
            "avg_win": round(gw / len(wins), 2) if wins else None, "avg_loss": round(-gl / len(losses), 2) if losses else None,
            "expectancy": round(sum(pn) / len(pn), 2), "best": round(max(pn), 2), "worst": round(min(pn), 2),
            "max_streak": worst_streak, "maxdd": round(mdd, 2), "per_week": round(len(pn) / max(1, days) * 7, 1),
            "net": round(sum(pn), 2)}


def proof_band(pnls, n, lot_ratio=1.0):
    """What the test calls normal for n trades: 2000 draws of n trades
    from the replay's own trades (with replacement), 5th to 95th percent
    of the sum. Deterministic seed so the page does not flicker."""
    if not pnls or not n or n < 1:
        return None
    import random
    rng = random.Random(7 + n)
    sums = []
    for _ in range(2000):
        sums.append(sum(rng.choice(pnls) for _ in range(n)) * lot_ratio)
    sums.sort()
    return {"n": n, "lo": round(sums[int(0.05 * len(sums))], 2), "hi": round(sums[int(0.95 * len(sums)) - 1], 2),
            "mid": round(sums[len(sums) // 2], 2)}


def proof_mine(uid):
    """The member's own robot journal against the strategy's test over the
    same days (owner 2026-09-29: 'make it personal'). Names never leave."""
    import csv as _csv
    cand = {"u224016179": "bos_journal_valere.csv", "bos": "bos_journal.csv"}.get(uid, f"bos_journal_{uid}.csv")
    f = os.path.join(DIR, cand)
    if not os.path.exists(f):
        return None
    try:
        rows = [r for r in _csv.DictReader(open(f, encoding="utf-8", errors="replace")) if r.get("exit_time_utc")]
    except Exception:
        return None
    if not rows:
        return None
    base = [r for r in rows if r.get("is_add") != "True"]
    wins = sum(1 for r in base if float(r.get("profit_usd") or 0) > 0)
    lots = sorted(float(r.get("lot") or 0) for r in base if r.get("lot"))
    lot = lots[len(lots) // 2] if lots else 0.02
    since = min([r["entry_time_utc"][:10] for r in rows if r.get("entry_time_utc")] or [""])
    out = {"trades": len(base), "adds": len(rows) - len(base), "net": round(sum(float(r.get("profit_usd") or 0) for r in rows), 2),
           "wr": (round(100 * wins / len(base)) if base else None), "since": since, "lot": lot}
    try:
        p = json.load(open(os.path.join(DIR, "lab", "proof.json"), encoding="utf-8"))
        full = ((p.get("base") or {}).get("full") or {})
        cv = full.get("curve") or []
        start = next((v for d, v in cv if d >= since), None)
        if start is not None and cv:
            out["expected"] = round((cv[-1][1] - start) * (lot / 0.02 if lot else 1), 2)
        out["band"] = proof_band(full.get("pnls"), len(base), (lot / 0.02 if lot else 1))
    except Exception:
        pass
    return out


def proof_history(current):
    """One line per night in lab/proof_history.jsonl (keyed by the proof's
    build time); returns the last 14 for the dots strip."""
    hp = os.path.join(DIR, "lab", "proof_history.jsonl")
    rows = []
    try:
        with open(hp, encoding="utf-8") as f:
            for ln in f:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
    except Exception:
        pass
    key = current.get("updated")
    if key and not any(r.get("k") == key for r in rows):
        rec = {"k": key, "d": key[:10], "c": {l["k"]: l["c"] for l in current.get("lights", [])}, "o": (current.get("overall") or {}).get("c")}
        rows.append(rec)
        try:
            with open(hp, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass
    # one per day, the last of each day
    byday = {}
    for r in rows:
        byday[r.get("d")] = r
    hist = [byday[d] for d in sorted(byday)][-14:]
    streak = 0
    if hist:
        last = hist[-1].get("o")
        for r in reversed(hist):
            if r.get("o") == last:
                streak += 1
            else:
                break
    return {"nights": hist, "streak": streak}


def lab_payload():
    if _LAB_CACHE["data"] is not None and time.time() - _LAB_CACHE["t"] < 120:
        return _LAB_CACHE["data"]
    try:
        reg = json.load(open(LAB_REG, encoding="utf-8"))
    except Exception:
        reg = {"items": []}
    J = _journal_unique()
    for r in J:                     # direction for the long/short cut
        r.setdefault("dir", "")
    # the paper twin (flip + touch, no brakes)
    twin = {}
    try:
        st = json.load(open(os.path.join(DIR, "bos_paper_touch_state.json"), encoding="utf-8"))
        tr = [t for t in (st.get("trades") or []) if isinstance(t, dict) and t.get("t_close")]
        wins = sum(1 for t in tr if (t.get("pnl") or 0) > 0)
        cum, acc = [], 0.0
        for t in tr[-60:]:
            acc += float(t.get("pnl") or 0); cum.append(round(acc, 2))
        twin = {"trades": len(tr), "wins": wins, "win": (round(100 * wins / len(tr)) if tr else None),
                "net": round(float(st.get("net") or 0), 2), "since": int(tr[0]["t_open"]) if tr else None,
                "last": int(tr[-1]["t_close"]) if tr else None, "curve": cum,
                "rolling20": round(sum(float(t.get("pnl") or 0) for t in tr[-20:]), 2),
                "open": bool(st.get("pos"))}
    except Exception:
        pass
    try:
        fwd = json.load(open(os.path.join(DIR, "bos_forward_observer.json"), encoding="utf-8"))
    except Exception:
        fwd = {}
    e017 = {}
    try:
        st = json.load(open(os.path.join(DIR, "liq_shadow_state.json"), encoding="utf-8"))
        with open(os.path.join(DIR, "liq_shadow_events.csv"), encoding="utf-8", errors="replace") as f:
            ev = max(0, sum(1 for _ in f) - 1)
        e017 = {"events": ev, "fills": st.get("fills"), "alive": st.get("alive"), "need": 30}
    except Exception:
        pass
    items = reg.get("items") or []
    counts = {}
    for it in items:
        counts[it.get("status")] = counts.get(it.get("status"), 0) + 1
    # 2026-09-28: the chercheur's outputs (nightly researcher + the Claude session)
    def _lj(p, d):
        try:
            return json.load(open(os.path.join(DIR, "lab", p), encoding="utf-8"))
        except Exception:
            return d
    auto = _lj("auto.json", {})
    note = _lj("chercheur_latest.json", {})
    props = _lj("proposals.json", {}).get("proposals", [])
    twins_reg = _lj("twins.json", {}).get("twins", [])
    requests = [r for r in _lj("requests.json", {}).get("requests", []) if r.get("status", "open") == "open"][-10:]
    # 2026-09-29 (owner): ideas that went three nights at C leave the board but
    # stay in the archive, so the chercheur keeps knowing they were tried
    archive = _lj("archive.json", {})
    arch_on = {k: v for k, v in (archive.get("archived") or {}).items() if v.get("since")}
    def _duel(tw):
        try:
            sys.path.insert(0, os.path.join(DIR, "lab"))
            import twin_judge as TJ
            return TJ.duel(tw)
        except Exception:
            return None
    twins = []
    for tw in twins_reg:
        st = _lj(f"twin_{tw.get('id')}_state.json", {})
        tr = [t for t in (st.get("trades") or []) if isinstance(t, dict)]
        wins = sum(1 for t in tr if (t.get("pnl") or 0) > 0)
        twins.append({"id": tw.get("id"), "title_fr": tw.get("title_fr"), "title_en": tw.get("title_en"),
                      "cfg": tw.get("cfg"), "verdict": tw.get("verdict"), "started": tw.get("started"),
                      "status": tw.get("status"), "by": tw.get("by"), "stopped": tw.get("stopped"),
                      "trades": len(tr), "wins": wins,
                      "win": (round(100 * wins / len(tr)) if tr else None), "net": round(float(st.get("net") or 0), 2),
                      "rolling20": round(sum(float(t.get("pnl") or 0) for t in tr[-20:]), 2),
                      "alive": bool(st.get("last_bar") and time.time() - int(st.get("last_bar")) < 900),
                      "duel": _duel(tw)})
    counts["auto_ab"] = sum(1 for v in auto.get("variants", []) if v.get("verdict") in ("A", "B"))
    counts["pending"] = sum(1 for p in props if p.get("status", "pending") == "pending")
    out = {"items": items, "counts": counts, "candidates": lab_candidates(J), "live_trades": len(J),
           "twin": twin, "forward": fwd, "e017": e017, "updated": int(time.time()),
           "registry_updated": reg.get("updated"),
           "auto": {"updated": auto.get("updated"), "days": auto.get("days"), "counts": auto.get("counts", {}),
                    "days_long": auto.get("days_long"), "real_n": auto.get("real_n"),
                    "base": auto.get("base") or {}, "variants": auto.get("variants", []), "minutes": auto.get("minutes"),
                    # 2026-09-30: does the backtest still describe the
                    # bot? It runs every night before the battery; if it
                    # drifts, the verdicts above are about a strategy
                    # nobody runs, and the lab has to say so out loud.
                    "parity": auto.get("parity")},
           "note": note, "proposals": props[-20:], "twins": twins, "requests": requests,
           "engine": auto.get("engine"), "archive": arch_on,
           "asks": _lj("asks.json", {}).get("asks", [])[-40:],
           # 2026-10-02 (owner): Kino numerique watches during the day; the
           # members see his last words and when he last looked
           "veille": _veille(8), "veille_last": (_lj("veille_state.json", {}) or {}).get("last_wake"),
           # 2026-10-02 (owner): the night report shows the whole cast
           "critiques": _critiques_recent(10),
           "labo": _labo_card(),
           # 2026-10-03 (owner): are the verdicts charged with the measured
           # cost of trading yet, and how far is the measure from 30 trades
           "drag": {k: ((_lj("proof.json", {}) or {}).get("sources") or {}).get("drag", {}).get(k)
                    for k in ("trades", "per_trade", "usable", "gap")} if ((_lj("proof.json", {}) or {}).get("sources") or {}).get("drag") else None,
           "digest": _lj("digest.json", None),
           "builds": [{k: r.get(k) for k in ("id", "date", "title_fr", "title_en", "status", "key", "built_date", "built_note_fr", "built_note_en", "decline_fr", "decline_en", "build_error", "by")}
                      for r in sorted((r for r in _lj("requests.json", {}).get("requests", []) if r.get("status") in ("built", "declined", "failed")),
                                      key=lambda r: r.get("built_date") or r.get("date") or "")[-8:]]}
    try:
        out["journeys"] = lab_journeys(items, props, twins, auto, _lj("decisions.json", {}), arch_on)
    except Exception as e:
        out["journeys"] = []; out["journeys_err"] = str(e)[:100]
    _LAB_CACHE.update(t=time.time(), data=out)
    return out


def user_stats(u, admin_override=False):
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
            # Owner 2026-09-18: the legacy sun/sea weather came from
            # owl_weather.json, written by the retired KINO bot and last
            # touched 2026-09-07. It was kino-only and it is what made this
            # account's page look different from every other one. Gone; the
            # account reads the measured card like the other structure
            # accounts.
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
                    os.path.join(DIR, pause_file(u["id"])),
                    encoding="utf-8"))
                    .get("paused", u["id"] in PAUSE_ALLOWED))
            except Exception:
                d["trading_paused"] = u["id"] in PAUSE_ALLOWED
        # 2026-10-01 (owner): "Pourquoi rien aujourd'hui" and the account's
        # own per-trade ceiling. Both already existed - in the robot's log
        # and in owl_packages.json - and neither reached the phone.
        d["why_idle"] = why_idle(u["id"])
        # 2026-10-01 (owner): the snapshot was stored and never seen
        try:
            _hf = htf_of(u["id"])
            if _hf:
                for _t in (d.get("trades") or []):
                    _k = str(_t.get("pid") or "")
                    if _k in _hf:
                        _t["tf"] = _hf[_k]
        except Exception:
            pass
        d["acct_rules"] = (lambda _p: {
            "package": _p.get("package"),
            "risk_fit_pct": _p.get("risk_fit_pct") or 0,
            "day_cap": _p.get("day_cap"),
            # 2026-10-01 (owner): one panel that says everything the robot
            # will ever do with the money, not half of it
            "lot": _p.get("base_lot"),
            "kill": _p.get("kill_net"),
        })(PKG.for_account(u["id"]))
        try:
            d["recap"] = recap_yesterday(u["id"], d.get("days"),
                                         d.get("trades"))
        except Exception:
            d["recap"] = None
        try:
            d["htf_payoff"] = htf_payoff(u["id"])
        except Exception:
            d["htf_payoff"] = None
        d["era_start"] = u.get("era_start")
        d["contact_url"] = nest_config().get("contact_url") or ""
        d["contact_label"] = nest_config().get("contact_label") or ""
        d["era_prev"] = u.get("era_prev") or []
        # per-account books (2026-09-07): std has its own ledger/
        # fights; family mirrors follow the master's
        _sfx = "_std" if u.get("id") == "std" else ""
        try:
            # war-chest books exist only on the kino/std accounts;
            # the fresh demo (harvest engine) has no ledger card
            # Owner 2026-09-18: an account running its OWN structure
            # instance is checked FIRST. kino used to be caught by the
            # legacy branch below and shown the retired KINO bot's ledger,
            # so it never reached the structure cards after the switch.
            # Owner 2026-09-19: "the UI must be uniform". Both Kino (09-18)
            # and the demo (today) got the OLD cards because their record
            # lacked the "dedicated" field the structure branch keys on. An
            # account the bot table says runs a structure instance IS one,
            # whether or not the record says so - derive it.
            _bo = BOT_OF.get(u.get("id"))
            if (not u.get("dedicated") and _bo
                    and _bo[1].startswith("bos_state_")):
                u["dedicated"] = ("structure_bos_bot.py "
                                  + _bo[1][len("bos_state_"):-len(".json")])
            if u.get("dedicated") or u.get("id") == "bos":
                pass                      # handled by the branch below
            elif u.get("id") in ("kino", "std") or str(
                    u.get("login")) == str(LOGIN):
                d["ledger"] = json.load(open(os.path.join(
                    DIR, f"owl_ledger{_sfx}.json")))
                d["ledger"]["cap"] = 5.0  # CHEST_FUND_MAX in the bots
            if u.get("id") == "bos" or u.get("dedicated"):
                # the weather card must say what weather_gate() would say,
                # and both halves are now per-account dials (owner
                # 2026-09-20, package "special"). Without this the card
                # would explain a refusal that never happened.
                try:
                    _pk = PKG.for_account(u.get("id") or "")
                    d["gates"] = {"nervosity": bool(_pk.get("nervosity",
                                                            True)),
                                  "movement": bool(_pk.get("movement",
                                                           True)),
                                  "package": _pk.get("package", "")}
                except Exception:
                    pass                  # a broken file must not blank the card
                # the Structure Bot keeps its own debt/bullet books.
                # 2026-09-14: a member running his OWN instance (field
                # "dedicated" = "structure_bos_bot.py <variant>") gets
                # the same card, read from HIS state file.
                _var = (u.get("dedicated") or "").split()
                _var = _var[-1] if len(_var) > 1 else ""
                _bsfx = f"_{_var}" if _var else ""
                # 2026-09-16: a half-manual account's books live in the
                # DESK's state, not in the bot's. The live account stopped
                # its bot on 2026-09-15, so bos_state.json is frozen and the
                # card was showing a dead ledger (jar off, stale debt).
                _bs = None
                if u.get("mode") in ("manual", "semi"):
                    try:
                        _bs = json.load(open(os.path.join(
                            DIR, f"manual_state_{u['id']}.json")))
                    except Exception:
                        _bs = None
                if _bs is None:
                    _bs = json.load(open(os.path.join(
                        DIR, f"bos_state{_bsfx}.json")))
                # the recovery dials come from the bot's own state file,
                # so the card can never describe a system the bot is not
                # running (owner 2026-09-16)
                _dbt = float(_bs.get("debt") or 0.0)
                _jar = float(_bs.get("chest") or 0.0)
                _bl0 = float(_bs.get("base_lot") or 0.02)
                _mx = int(_bs.get("max_extra") or 3)
                d["ledger"] = {
                    "debt": _dbt, "chest": _jar, "bos": True,
                    "cap": float(_bs.get("jar_cap") or 10.0),
                    "jar": bool(_bs.get("jar")),
                    "skim": float(_bs.get("jar_skim") or 0.5),
                    "stake": float(_bs.get("jar_stake") or 0.5),
                    "base_lot": _bl0, "max_extra": _mx,
                    # the page needs it to show the reinforcement alone
                    "opening_lot": _bl0,
                    "rr": float(_bs.get("rr") or 0.8),
                    "next_lot": round(_bl0 + _mx * 0.01, 2),
                    "need_min": 3.0}  # ~one bullet at typical stop
                # 2026-09-24: balance scaling, read from the bot's own
                # state so the card can never describe a target the bot
                # is not actually enforcing (same discipline as the
                # recovery dials above).
                d["ledger"]["scale_active"] = bool(_bs.get("scale_active"))
                d["ledger"]["scale_ref_balance"] = float(
                    _bs.get("scale_ref_balance") or 0.0)
                d["ledger"]["scale_base_lot"] = float(
                    _bs.get("scale_base_lot") or _bl0)
                if _bs.get("scale_base_cap") is not None:
                    d["ledger"]["scale_base_cap"] = float(
                        _bs["scale_base_cap"])
                if _bs.get("sized_day_cap") is not None:
                    d["ledger"]["sized_day_cap"] = float(
                        _bs["sized_day_cap"])
                # 2026-09-24: the REAL number stopping (or not stopping)
                # entries today, straight from effective_cap_today() via
                # the bot's own state - never reconstructed here, so the
                # card can't drift from what the bot actually enforces
                # (a staleness bug in exactly that gap was caught and
                # fixed the same day).
                _ct = _bs.get("cap_today")
                if isinstance(_ct, (int, float)):
                    d["ledger"]["cap_today"] = float(_ct)
                d["ledger"]["day_pnl_bot"] = float(_bs.get("day_pnl") or 0.0)
                d["ledger"]["day_capped"] = bool(_bs.get("day_capped"))
                d["bot_killed"] = bool(_bs.get("killed"))
                d["ledger"]["scale_opt_out"] = bool(u.get("scale_opt_out"))
                try:
                    d["ledger"]["scale_can_toggle"] = (
                        u.get("id") in SCALE_TOGGLE_ALLOWED
                        and not u.get("public"))
                except Exception:
                    pass
                try:
                    try:
                        d["meteo_struct"] = json.load(open(os.path.join(
                            DIR, f"bos_weather{_bsfx}.json")))
                    except Exception:
                        d["meteo_struct"] = json.load(open(os.path.join(
                            DIR, "bos_weather.json")))
                    # the card speaks the chart's language, so it must read
                    # the chart's numbers - volatility and spread live in
                    # the feed, not in the bot's weather file (2026-09-17)
                    try:
                        _cj = json.load(open(os.path.join(
                            DIR, "owl_chart_btc.json")))
                        for _k in ("moves_2h", "vol_now", "vol_ref",
                                   "spread", "int_state", "int_trend",
                                   "int_brk_1h", "int_awake"):
                            if _cj.get(_k) is not None:
                                d["meteo_struct"][_k] = _cj[_k]
                        # 2026-09-28: "Prochaine action" - the readiness flags for
                        # everyone, the LEVELS only for Strategie members and the admin
                        # 2026-10-01: which movement rule decides. The bot
                        # only applies the inner one to an INNER entry, and
                        # those are off, so the card must stop choosing the
                        # inner rule just because an inner structure exists.
                        try:
                            d["meteo_struct"]["internal_entries"] = bool(
                                PKG.for_account(u["id"]).get(
                                    "internal_entries", False))
                        except Exception:
                            d["meteo_struct"]["internal_entries"] = False
                        for _k in ("bos_ready", "flip_bos_ready", "int_bos_ready", "int_flip_bos_ready", "trend", "choch"):
                            d["meteo_struct"][_k] = _cj.get(_k)
                        if is_admin(u) or has(u.get("id"), "strategy"):
                            for _k in ("next_bos", "flip_bos", "invalid", "int_bos", "int_inv", "int_flip_bos"):
                                d["meteo_struct"][_k] = _cj.get(_k)
                    except Exception:
                        pass
                    # 2026-09-30 (owner): the Marche tab reads the higher
                    # timeframes against the minute one. Directions only -
                    # no price leaves this block, so there is no tier to
                    # gate and nothing to leak.
                    try:
                        _hf = json.load(open(os.path.join(
                            DIR, "owl_chart_htf.json")))
                        _rows = []
                        for _k in ("H4", "H1", "M15"):
                            _t = (_hf.get("tf") or {}).get(_k)
                            if not _t:
                                continue
                            _rows.append({
                                "k": _k,
                                "trend": int(_t.get("trend") or 0),
                                "int": int(_t.get("int_trend") or 0),
                                "held": (max(0, int(time.time())
                                             - int(_t["since"]))
                                         if _t.get("since") else None),
                                "exact": bool(_t.get("since_exact"))})
                        _m1t = int(_cj.get("trend") or 0)
                        d["tf_align"] = {
                            "rows": _rows,
                            "m1": _m1t,
                            "m1_int": int(_cj.get("int_trend") or 0),
                            "agree": sum(1 for _r in _rows
                                         if _r["trend"] and _r["trend"] == _m1t),
                            "n": len(_rows),
                            "up": sum(1 for _r in _rows if _r["trend"] == 1),
                            "dn": sum(1 for _r in _rows if _r["trend"] == -1),
                            "age": max(0, int(time.time())
                                       - int(_hf.get("updated") or 0)),
                            "together": (min([_r["held"] for _r in _rows
                                              if _r["held"] is not None] or [0])
                                         if _rows and len(set(
                                             _r["trend"] for _r in _rows)) == 1
                                         and _rows[0]["trend"] else None),
                            "together_exact": all(_r.get("exact")
                                                  for _r in _rows) if _rows
                            else False}
                    except Exception:
                        pass
                    # live bullet price from the bot (stop distance)
                    _bl = d["meteo_struct"].get("bullet")
                    if _bl:
                        # Owner 2026-09-20: bullets are fired at the MIDPOINT
                        # now, where the stop is half as far, so one costs
                        # half what the bot's "bullet" figure says (that one
                        # is priced at the full stop). Halve it here and every
                        # number the card derives follows.
                        _bl = float(_bl) / 2.0
                        d["ledger"]["need_min"] = _bl
                        _L = d["ledger"]
                        if _L["jar"] and _dbt > 0.5 and _bl > 0:
                            import math as _m
                            _byb = int((_jar * _L["stake"]) // _bl)
                            _g1 = _L["rr"] * _bl / 0.01 * 0.01
                            _byd = (int(_m.ceil(_dbt / _g1))
                                    if _g1 > 0 else 0)
                            _ex = max(0, min(_mx, _byb, _byd))
                            # 2026-09-20: this is the MIDPOINT reinforcement
                            # now, not the opening lot. A bullet there risks
                            # half as much, so the same jar buys more.
                            _byb2 = int((_jar * _L["stake"]) // max(_bl / 2, 0.01))
                            _g2 = _L["rr"] * max(_bl / 2, 0.01)
                            _byd2 = (int(_m.ceil(_dbt / _g2)) if _g2 > 0 else 0)
                            _ex = max(0, min(_mx, _byb2, _byd2))
                            _L["next_lot"] = round(_bl0 + _ex * 0.01, 2)
                            _L["fill_n"] = _ex
                        elif _dbt <= 0.5:
                            _L["next_lot"] = _bl0
                except Exception:
                    pass
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
        # Owner 2026-09-18: "the UI must be uniform, same for all accounts."
        # The "combats des soldats" card existed on kino/std alone and was
        # fed by the retired KINO bot's fight history, so it showed trades
        # from 2026-09-07 on an account whose books had just been cleared.
        # Removed rather than generalised: no other account has that data.
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
            _pp = json.load(open(PUSH_PREFS_FILE))
            d["push_level"] = _pp.get(u["id"], "all")
            d["build"] = APP_BUILD
            d["push_quiet"] = bool((_pp.get("_quiet") or {})
                                   .get(u["id"], {}).get("on"))
        except Exception:
            d["push_level"] = "all"
            d["push_quiet"] = False
        # 2026-09-24 (owner): "the objective feature must be used to
        # reflect the next account balance to reach the next $/day
        # target". On an account whose lot/day-cap scale with balance,
        # the Objectif bar's own default now chases THAT balance instead
        # of the generic weekly step - it is a much more concrete number
        # ("$X more unlocks $Y/day") and reuses the exact bar the master
        # can already override by hand (goalbtn, below, unchanged).
        try:
            _lg = d.get("ledger") or {}
            if (not d.get("palier") and not d.get("palier_off")
                    and d.get("balance") is not None
                    and _lg.get("scale_active")
                    and _lg.get("scale_base_cap")
                    and _lg.get("scale_ref_balance")):
                _base_cap = float(_lg["scale_base_cap"])
                _ref_bal = float(_lg["scale_ref_balance"])
                _now_cap = float(_lg.get("sized_day_cap") or _base_cap)
                if _base_cap > 0 and _ref_bal > 0:
                    _next_cap = math.floor(_now_cap) + 1
                    d["palier"] = round(_ref_bal * _next_cap / _base_cap, 2)
                    # 2026-10-01: this was the CURRENT balance, which makes
                    # the bar (bal - bal) / (target - bal) = 0% forever -
                    # it has never moved on any account. The honest base is
                    # the balance the CURRENT daily cap started at, so the
                    # bar shows the distance actually travelled between one
                    # step and the next.
                    _prev_cap = math.floor(_now_cap)
                    d["palier_base"] = (
                        round(_ref_bal * _prev_cap / _base_cap, 2)
                        if _prev_cap >= 1 else 0.0)
                    d["palier_def"] = True
                    d["palier_kind"] = "scale"
                    d["palier_next_cap"] = _next_cap
        except Exception:
            pass
        # default weekly objective (+$50 from Monday's balance) so the
        # bar is always alive unless explicitly disabled (2026-09-08)
        try:
            if (not d.get("palier") and not d.get("palier_off")
                    and d.get("balance") is not None):
                # 2026-09-14: the weekly step is per member
                # ("week_goal" on the nest record, default +$50)
                _step = float(u.get("week_goal") or 50.0)
                _wb = float(d["balance"]) - float(d.get("week") or 0)
                d["palier"] = round(_wb + _step, 2)
                d["palier_base"] = round(_wb, 2)
                d["palier_def"] = True
                d["palier_step"] = _step
        except Exception:
            pass
        # 2026-10-03 (owner): admin accounts only. "login == LOGIN" used to
        # make master any member whose MT5 login is the server's own, and
        # that member saw the account switcher and Le Nid.
        if (u.get("id") in ("kino", "std")
                or admin_override):
            d["is_master"] = True
            # v2 Le Nid: one row per member for the master console
            try:
                _rows = []
                _SHARE_EL = SHARE.eligible() if SHARE.on() else {}
                try:
                    _notes = json.load(open(NOTES_FILE, encoding="utf-8"))
                except Exception:
                    _notes = {}
                try:
                    _seen = json.load(open(SEEN_FILE, encoding="utf-8"))
                except Exception:
                    _seen = {}
                for x in json.load(open(USERS_FILE, encoding="utf-8")):
                    if x.get("pending_code"):
                        continue          # 2026-10-04: a request, not an account yet (listed apart)
                    _ndp = os.path.join(NEST_DATA, x["id"] + ".json")
                    try:
                        nd = json.load(open(_ndp))
                    except Exception:
                        nd = {}
                    _ppf = pause_file(x["id"])
                    try:
                        _pz = bool(json.load(open(os.path.join(
                            DIR, _ppf))).get("paused"))
                    except Exception:
                        _pz = False
                    try:
                        _age = time.time() - os.path.getmtime(_ndp)
                    except Exception:
                        _age = 9e9
                    _bot, _live, _blk = bot_on(x["id"])
                    _rows.append({
                        "id": x["id"],
                        "name": x.get("name", x["id"]),
                        "login": x.get("login"),
                        "tok": x.get("token"),
                        # 2026-10-01 (owner): "only real accounts count"
                        # - the broker's own trade_mode, already computed by
                        # the worker, never passed on until now
                        "real": nd.get("real"),
                        "bal": nd.get("balance"),
                        "today": nd.get("today"),
                        "err": bool(nd.get("error")),
                        "stale": _age > 60, "paused": _pz,
                        "share": (SHARE.statement(x["id"]) if (SHARE.on() and x.get("trade") and x["id"] in _SHARE_EL) else None),
                        "setup": (SHARE.setup_info(x["id"]) if (x["id"] not in OWNER_UIDS and not x.get("public")) else None),
                        "app": bool(x.get("app_only") or x.get("app_login")), "pkg": x.get("plan"),
                        "pos": nd.get("open_positions"),
                        "bot": _bot, "botlive": _live, "blocked": _blk,
                        # 2026-10-01 (owner): "all accounts done for the
                        # day?" - he had to ask a person, because only the
                        # single-account home card knew.
                        "day": day_state(x["id"]),
                        "why": why_idle(x["id"]),
                        "trade": bool(x.get("trade")
                                      or x.get("id") == "kino"),
                        "days": (nd.get("days") or [])[:7],
                        "note": (_notes.get(x["id"]) or {}).get("text", ""),
                        "seen": _seen.get(x["id"]),
                        "family_until": int((ent(x["id"]) or {}).get("family_until") or 0),
                        "plan": x.get("plan"),
                        # 2026-10-01 (owner): accounts really differ now -
                        # a 3% per-trade ceiling here, none there, another
                        # package on 441 - and the only way to see it was to
                        # read a config file.
                        "rules": (lambda _p: {
                            "package": _p.get("package"),
                            "label": _p.get("label"),
                            "lot": _p.get("base_lot"),
                            "day_cap": _p.get("day_cap"),
                            "kill": _p.get("kill_net"),
                            "risk_fit_pct": _p.get("risk_fit_pct") or 0,
                            "internal": bool(_p.get("internal_entries")),
                            "nervosity": bool(_p.get("nervosity", True)),
                            "movement": bool(_p.get("movement", True)),
                        })(PKG.for_account(x["id"])),
                        "push": bool(_push_subs().get(x["id"])),
                        # 2026-09-28: an observer (no Automatique, no Manuel) has no
                        # robot to run - not a fault, so Le Nid must not flag it
                        "observer": (x["id"] not in OWNER_UIDS and not x.get("public")
                                     and not has(x["id"], "manual")),
                        "sigs": (sig_score(x["id"], era_ts(x)) if x.get("mode") in MANUAL_MODES else None)})
                d["nest"] = _rows
                # 2026-10-04 (owner): requests waiting for a code (Le Nid > En attente)
                d["pending"] = [{"id": x.get("id"), "name": x.get("name"), "pkg": x.get("pending_code"),
                                 "asked": x.get("asked_at"), "telegram": x.get("telegram"),
                                 "mt5": (str(x.get("mt5_login"))[-3:] if x.get("mt5_login") else None),
                                 "has_mt5": bool(x.get("mt5_login") and x.get("mt5_server"))}
                                for x in json.load(open(USERS_FILE, encoding="utf-8")) if x.get("pending_code")]
                # 2026-09-28: the owner's "Revenus" card
                try:
                    _E = _ents()
                    _now = time.time()
                    _act = {"family": 0, "manual": 0, "strategy": 0}
                    _due = []
                    _names = {x["id"]: x.get("name", x["id"]) for x in json.load(open(USERS_FILE, encoding="utf-8"))}
                    for _uid, _e in _E.items():
                        if _uid in OWNER_UIDS or not isinstance(_e, dict):
                            continue
                        for _k, _lab in (("family_until", "family"), ("manual_until", "manual"), ("strategy_until", "strategy")):
                            _u = float(_e.get(_k) or 0)
                            if _u > _now:
                                _act[_lab] += 1
                                if _u - _now < 7 * 86400:
                                    _due.append({"name": _names.get(_uid, _uid), "pkg": _lab, "days": int((_u - _now) // 86400)})
                    try:
                        _pays = [p for p in json.load(open(PAY_FILE, encoding="utf-8")) if p.get("granted") in PACKAGES and not p.get("test")][-10:][::-1]
                    except Exception:
                        _pays = []
                    _cfg = nest_config()
                    _fam_usd = float(_cfg.get("family_usd") or 0)
                    d["revenue"] = {"active": _act, "due": _due, "payments": _pays,
                                    "mrr": _act["manual"] * PACKAGES["manual"]["usd"] + _act["strategy"] * PACKAGES["strategy"]["usd"] + _act["family"] * _fam_usd,
                                    "family_usd": _fam_usd,
                                    # 2026-10-03 (owner): the profit share, this month so far + what is open
                                    "share": (SHARE.owner_view() if SHARE.on() else None)}
                except Exception:
                    pass
            except Exception:
                pass
        elif not u.get("trade"):
            d["activation_needed"] = True
        _ef = ent(u.get("id"))
        if _ef.get("family_until") and float(_ef["family_until"]) <= time.time() \
                and u.get("id") not in OWNER_UIDS:
            d["activation_needed"] = True
            d["family_expired"] = time.strftime("%d/%m", time.gmtime(float(_ef["family_until"])))
        # Owner 2026-09-16: every trading account SEES the switch, but it is
        # locked for everyone except the admin and the Structure account.
        # The lock is enforced on the write route too, not just in the UI.
        if u.get("id") != "kino" and u.get("trade"):
            try:
                d["trading_paused"] = bool(json.load(open(os.path.join(
                    DIR, f"owl_trading_pause_{u['id']}.json")))
                    .get("paused", u["id"] in PAUSE_ALLOWED))
            except Exception:
                # no file: MANUAL on the accounts that may switch, which is
                # the desk's own safe default
                d["trading_paused"] = u["id"] in PAUSE_ALLOWED
        # follow the flag wherever it was set, not just on this path, so no
        # account can end up with an unlocked-looking switch
        if "trading_paused" in d:
            d["pause_locked"] = not can_switch(u)
        d["plan"] = plan_of(u)
        # 2026-09-28: a manual member without a push subscription gets no signal
        d["push_on"] = bool(_push_subs().get(u.get("id")))
        if d.get("is_master"):
            _c = nest_config()
            d["plan"]["np_key_tail"] = (_c.get("np_api_key") or "")[-4:]
            d["plan"]["np_secret_set"] = bool(_c.get("np_ipn_secret"))
            d["plan"]["np_sandbox"] = bool(_c.get("np_sandbox"))
        if u.get("public"):
            # view-only: no switch, no settings that change anything
            d["public"] = True
            d.pop("trading_paused", None)
            d.pop("pause_locked", None)
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
   (t[5]>=0?'  +$':'  -$')+Math.abs(t[5]).toFixed(2),
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
  pe.textContent='$'+D.px.toFixed(0);
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

# 2026-10-03 (owner): where the Android app starts. The app cannot know
# the member's link, so this page sends it to the one this phone used
# last (the member app remembers it), or asks for it once.
APP_PAGE = """<!doctype html><html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f2740"><title>OwlNest</title>
<link rel="icon" href="/icon192.png"><link rel="manifest" href="/manifest.json">
<style>
body{margin:0;background:#0b0f14;color:#e8eef4;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px;box-sizing:border-box}
.c{max-width:380px;width:100%;text-align:center}
img{width:72px;height:72px;border-radius:18px}
h1{font-size:1.4rem;margin:14px 0 6px}
p{color:#c6d3df;line-height:1.55;font-size:.95rem;margin:0 0 14px}
input{width:100%;box-sizing:border-box;background:#141c28;border:1px solid #1f2c3d;border-radius:12px;color:#e8eef4;padding:13px 14px;font-size:1rem;margin-top:6px}
button,a.b{display:block;width:100%;box-sizing:border-box;margin-top:12px;border:0;border-radius:14px;padding:14px;font-size:1rem;font-weight:700;cursor:pointer;text-decoration:none;text-align:center}
.m{background:#3b82f6;color:#fff}.g{background:#141c28;color:#c6d3df;border:1px solid #1f2c3d}
.s{font-size:.8rem;color:#8a9bb0;margin-top:16px;line-height:1.5}
#ask{display:none}
</style></head><body><div class="c">
<img src="/icon192.png" alt="">
<div id="ask"><h1>Bienvenue dans OwlNest</h1>
<p>Collez le lien que vous avez re&ccedil;u (il contient votre cl&eacute;). L&#8217;application s&#8217;en souviendra.</p>
<input id="lnk" placeholder="Collez votre lien ici" autocomplete="off" inputmode="url">
<button class="m" onclick="go()">Ouvrir mon compte</button>
<a class="b g" href="/demo">Voir le compte d&eacute;mo</a>
<div class="s">Pas encore de lien ? <a href="/" style="color:#9fc2de">Demander un acc&egrave;s</a></div>
</div>
<script>
var V=(new URLSearchParams(location.search).get('v')||'');
(function(){var l=null;try{l=localStorage.getItem('owlLink');}catch(e){}
 if(l&&/^[/][A-Za-z0-9_-]{6,}[/]$/.test(l)){location.replace(l+(V?'?twa='+encodeURIComponent(V):''));return;}
 location.replace('/');})();
function go(){var t=document.getElementById('lnk').value.trim();var m=t.match(/[/]([A-Za-z0-9_-]{6,})[/]?(?:[?#]|$)/);
 var tok=m?m[1]:(/^[A-Za-z0-9_-]{6,}$/.test(t)?t:'');
 if(!tok){alert('Ce lien ne ressemble pas &agrave; un lien OwlNest.');return;}
 location.href='/'+tok+'/'+(V?'?twa='+encodeURIComponent(V):'');}
</script></div></body></html>"""

# 2026-10-03 (owner): "the creation of a family account must be done in a
# special way" - one page, one code. The code (from the Owl on Telegram, or
# bought in crypto for Signal / Strategie) names the package; the member
# gives the MT5 account; the server creates the terminal and, for
# Automatique, the robot. No trial, no self-registration without a code.
ACTIVATE_PAGE = """<!doctype html><html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f2740"><title>OwlNest &middot; Activer</title>
<link rel="icon" href="/icon192.png">
<style>
@font-face{font-family:'Inter';src:url('/fonts/inter.woff2') format('woff2');font-weight:100 900;font-display:swap}
body{margin:0;background:#0b0f14;color:#e8eef4;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:22px 18px 40px}
.c{max-width:420px;margin:0 auto}
.top{display:flex;align-items:center;gap:10px;margin-bottom:18px}.top img{width:40px;height:40px;border-radius:11px}.top b{font-size:1.1rem}
h1{font-size:1.35rem;margin:0 0 6px}p{color:#c6d3df;line-height:1.55;font-size:.95rem;margin:0 0 14px}
label{display:block;font-size:.76rem;color:#8a9bb0;text-transform:uppercase;letter-spacing:.06em;margin:14px 0 6px}
input,select{width:100%;box-sizing:border-box;background:#141c28;border:1px solid #1f2c3d;border-radius:12px;color:#e8eef4;padding:13px 14px;font-size:1rem}
input#code{letter-spacing:.3em;text-transform:uppercase;font-weight:800;text-align:center;font-size:1.3rem}
.h{font-size:.78rem;color:#8a9bb0;line-height:1.45;margin-top:6px}
button{display:block;width:100%;box-sizing:border-box;margin-top:18px;border:0;border-radius:14px;padding:14px;font-size:1rem;font-weight:700;cursor:pointer;background:#3b82f6;color:#fff}
a{color:#9fc2de}.k{background:#121a25;border:1px solid #1f2a38;border-radius:18px;padding:16px;margin-top:16px;font-size:.86rem;color:#c6d3df;line-height:1.5}
</style></head><body><div class="c">
<div class="top"><img src="/icon192.png" alt=""><b>OwlNest</b></div>
<h1>Activer mon compte</h1>
<p>Un code et c&#8217;est tout : votre page personnelle se pr&eacute;pare en 2&ndash;3 minutes. Pas encore de code ? Le Owl vous le donne sur Telegram.</p>
%%CONTACTBTN%%
<form method="POST" action="/activate" autocomplete="off">
<label for="code">Code d&#8217;activation</label>
<input id="code" name="code" maxlength="6" placeholder="ABC123" autocapitalize="characters">
<div class="h" id="ch">Re&ccedil;u du Owl sur Telegram (Automatique, Signal, Strat&eacute;gie).</div>
<label for="buy">Pas de code ? Acheter en crypto</label>
<select id="buy" name="buy"><option value="">&mdash; j&#8217;ai un code &mdash;</option><option value="manual">Signal &middot; $29 / 30 jours</option><option value="strategy">Strat&eacute;gie &middot; $49 / 30 jours</option></select>
<div class="h">NOWPayments ouvre une page : USDT, BTC ou autre. Votre compte s&#8217;active d&egrave;s que le paiement est confirm&eacute;.</div>
<label for="name">Votre pr&eacute;nom</label>
<input id="name" name="name" required maxlength="30" placeholder="Pr&eacute;nom">
<div id="mt5">
<label for="login">Num&eacute;ro de compte MT5</label>
<input id="login" name="login" inputmode="numeric" placeholder="12345678">
<label for="server">Serveur MT5</label>
<input id="server" name="server" placeholder="Exness-MT5Real30" list="srv">
<datalist id="srv"><option value="Exness-MT5Real30"><option value="Exness-MT5Real27"><option value="Exness-MT5Trial9"></datalist>
<div class="h">Visible dans votre application MT5 : Param&egrave;tres &rsaquo; Comptes. Le robot a besoin du mot de passe principal du compte.</div>
</div>
<label for="pw" id="pwl">Mot de passe</label>
<input id="pw" name="password" type="password" required maxlength="64" placeholder="mot de passe">
<div class="h" id="pwh">Automatique : le mot de passe du compte MT5. Signal / Strat&eacute;gie : un mot de passe de votre choix, pour vous connecter.</div>
<label for="tg">Telegram (facultatif)</label>
<input id="tg" name="telegram" maxlength="40" placeholder="@votre_nom">
<button>Activer &#10142;</button>
</form>
<script>
function mode(p){var fam=(p==='family');var m=document.getElementById('mt5');m.style.display=fam?'':'none';
 document.getElementById('login').required=fam;document.getElementById('server').required=fam;
 document.getElementById('pwl').textContent=fam?'Mot de passe du compte MT5':'Choisissez un mot de passe';
 document.getElementById('pwh').textContent=fam?'Le mot de passe principal : le robot doit pouvoir trader sur le compte.':'Il vous servira pour vous connecter, avec votre identifiant. Pas de compte MT5 n\u00e9cessaire.';}
mode('family');
document.getElementById('code').addEventListener('input',function(){var c=this.value.trim().toUpperCase();var h=document.getElementById('ch');
 if(c.length<6){h.textContent='Re\u00e7u du Owl sur Telegram (Automatique, Signal, Strat\u00e9gie).';return;}
 fetch('/codeinfo?c='+encodeURIComponent(c)).then(function(r){return r.json();}).then(function(j){
  if(j&&j.ok){h.textContent='Code '+j.label+' \u00b7 '+j.days+' jours';mode(j.pkg);}else{h.textContent='Code inconnu ou d\u00e9j\u00e0 utilis\u00e9.';mode('family');}}).catch(function(){});});
document.getElementById('buy').addEventListener('change',function(){mode(this.value?'manual':'family');});
</script>
<div class="k">D&eacute;j&agrave; membre et vous renouvelez ? Entrez le code dans l&#8217;app : R&eacute;glages &rsaquo; Abonnement &rsaquo; &laquo; J&#8217;ai un code &raquo;.<br><br>Pas encore de code ? <a href="%%CONTACT%%">&Eacute;crivez au Owl sur Telegram</a> &middot; <a href="/">Retour</a></div>
<div class="h" style="margin-top:14px;text-align:center">Vos identifiants servent uniquement &agrave; relier votre compte. OwlNest vend un logiciel et un service de copie &mdash; pas de conseil ni de gestion d&#8217;investissement.</div>
</div></body></html>"""

JOIN_PAGE = """<!doctype html><html lang="fr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="google" content="notranslate">
<meta name="theme-color" content="#0b0f14">
<meta property="og:type" content="website">
<meta property="og:title" content="OwlNest">
<meta property="og:description" content="Le robot Owl trade pour vous, jour et nuit. Vous, vous regardez.">
<meta property="og:image" content="%%ORIGIN%%/shots/shot_home.png">
<meta property="og:url" content="%%ORIGIN%%/join">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="OwlNest">
<meta name="twitter:image" content="%%ORIGIN%%/shots/shot_home.png">
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/icon192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="OwlNest">
<title>OwlNest</title>
<style>
@font-face{font-family:'Inter';src:url('/fonts/inter.woff2') format('woff2');
 font-weight:100 900;font-style:normal;font-display:swap}
:root{--bg:#0b0f14;--surface:#121a25;--surface2:#172130;--border:#1f2a38;
 --border2:#2b3a4d;--text:#e8eef4;--text2:#c6d3df;--text3:#9fc2de;--muted:#8a9bb0;
 --accent:#3b82f6;--accent-soft:#8fc6ff;--up:#2ecc71;--r:16px;--r-lg:24px}
:root[data-theme=light]{--bg:#eef2f7;--surface:#ffffff;--surface2:#f6f8fb;
 --border:#dde4ed;--border2:#c7d2df;--text:#0f172a;--text2:#33415a;--text3:#46556b;
 --muted:#5f6f85;--accent:#2563eb;--accent-soft:#1d4ed8;--up:#15803d}
:root[data-theme=light] .blob{opacity:.18}
*{box-sizing:border-box;margin:0}
.ic{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:1.9;
 stroke-linecap:round;stroke-linejoin:round;flex:none;vertical-align:-4px}
.ic-l{width:24px;height:24px}
body{background:var(--bg);color:var(--text);padding:0 0 44px;overflow-x:hidden;
 font-family:'Inter',-apple-system,'Segoe UI',Roboto,sans-serif;
 font-feature-settings:'tnum' 1,'cv11' 1}
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
.tag{color:var(--text3);font-size:1rem;margin-top:8px;line-height:1.6}
.preview{margin:30px auto 0;background:linear-gradient(150deg,
 var(--surface2) 0%,var(--surface) 100%);border:1px solid var(--border2);
 border-radius:var(--r-lg);padding:20px 18px;
 box-shadow:0 18px 44px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.05);
 max-width:360px;text-align:center}
.pv-lbl{font-size:.68rem;color:var(--muted);text-transform:uppercase;
 letter-spacing:.1em}
.pv-money{font-size:2.2rem;font-weight:800;margin-top:5px}
.pv-eur{color:var(--text3);font-size:.95rem}
.pv-row{display:flex;justify-content:space-around;margin-top:12px;
 font-size:.85rem}
.pv-chip{background:rgba(46,204,113,.12);color:#2ecc71;font-weight:700;
 border-radius:999px;padding:5px 12px}
.pv-chip2{background:rgba(59,130,246,.14);color:var(--accent-soft);font-weight:700;
 border-radius:999px;padding:5px 12px}
.pv-bot{margin-top:13px;font-size:.82rem;color:var(--text2);display:flex;
 align-items:center;justify-content:center;gap:7px}
.feats{margin-top:30px}
/* 2026-10-02 (owner): the 1-2-3 steps as small-caps numerals, not boxes */
.feats:not(#plans) .fi.stp{background:transparent!important;border:0!important;color:#b98cff!important;
 font-size:.66rem!important;font-weight:700!important;letter-spacing:.12em;width:auto!important;
 height:auto!important;min-width:30px;border-radius:0!important;padding-top:5px;box-shadow:none!important}
.feats:not(#plans) .fi.stp::before{content:"0"}
.how{margin:0 4px 6px;font-size:.68rem;font-weight:700;color:var(--muted);
 text-transform:uppercase;letter-spacing:.09em}
.fi.stp{font-weight:800;font-size:1rem;color:var(--accent-soft)}
.fr{display:flex;align-items:center;gap:14px;background:var(--surface);
 border:1px solid var(--border);border-radius:var(--r);padding:14px 16px;
 box-shadow:inset 0 1px 0 rgba(255,255,255,.04);
 margin-top:12px}
.fi{width:42px;height:42px;border-radius:12px;display:flex;flex:none;
 align-items:center;justify-content:center;font-size:1.3rem;
 background:#1d2a3b;color:var(--accent-soft)}
.ft b{display:block;font-size:.98rem}
.ft span{font-size:.8rem;color:var(--muted);line-height:1.45}
.bigbtn{display:block;width:100%;margin-top:16px;border:0;
 border-radius:16px;padding:19px;font-size:1.12rem;font-weight:700;
 text-align:center;cursor:pointer}
.bigbtn:active{transform:scale(.98)}
.b1{background:var(--accent);color:#fff;
 box-shadow:0 10px 26px rgba(59,130,246,.35);margin-top:32px}
.b2{background:var(--surface);color:var(--text2);border:1px solid var(--border2);
 display:flex;align-items:center;justify-content:center;gap:9px}
.b3{background:none;border:0;color:var(--muted);font-size:.95rem;
 font-weight:600;padding:12px;box-shadow:none;display:flex;
 align-items:center;justify-content:center;gap:8px}
.b3:hover{color:var(--text2)}
.view{display:none}
.view.on{display:block}
.card{background:var(--surface);border:1px solid var(--border);
 border-radius:20px;padding:22px 18px;
 box-shadow:inset 0 1px 0 rgba(255,255,255,.04);margin-top:22px}
.back{color:var(--muted);text-decoration:none;font-size:.95rem;
 display:inline-block;margin:18px 0 0 4px;cursor:pointer}
h2{font-size:1.25rem;margin-bottom:4px}
label{display:block;margin:16px 0 7px;color:var(--text3);font-size:.92rem;
 font-weight:600}
input{width:100%;padding:15px;border-radius:12px;border:1px solid
 var(--border2);background:var(--bg);color:var(--text);font-size:1.05rem}
input:focus{outline:none;border-color:var(--accent)}
button.go{width:100%;margin-top:24px;background:var(--accent);color:#fff;
 border:0;border-radius:14px;padding:17px;font-size:1.1rem;
 font-weight:700}
.note{background:#0d2417;border:1px solid #1d4a2f;border-radius:14px;
 padding:14px;font-size:.88rem;color:#7fd6a0;margin-top:18px;
 line-height:1.5}
.fq{background:var(--surface);border:1px solid var(--border);border-radius:14px;margin-bottom:8px;padding:0 14px}
.fq summary{cursor:pointer;padding:13px 0;font-weight:700;font-size:.92rem;list-style:none;display:flex;justify-content:space-between;align-items:center;gap:10px}
.fq summary::-webkit-details-marker{display:none}
.fq summary::after{content:'+';color:var(--muted);font-size:1.25rem;line-height:1;flex:none}
.fq[open] summary::after{content:'−'}
.fq p{padding:0 0 14px;font-size:.88rem;color:var(--muted);line-height:1.55}
.shots{display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x mandatory;padding:4px 2px 10px;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.shots::-webkit-scrollbar{display:none}
.shots figure{flex:0 0 68%;scroll-snap-align:center;margin:0}
.shots img{width:100%;display:block;border-radius:22px;border:1px solid var(--border);box-shadow:0 14px 34px rgba(0,0,0,.4)}
.shots figcaption{text-align:center;font-size:.74rem;color:var(--muted);margin-top:8px}
.pfoot{margin-top:34px;text-align:center;font-size:.75rem;color:var(--muted);
 display:flex;align-items:center;justify-content:center;gap:6px}
.pfoot img{width:16px;height:16px;border-radius:4px}
</style></head><body>
<script>try{if(localStorage.getItem('owlTheme')==='light')document.documentElement.dataset.theme='light';if(localStorage.getItem('owlPin:'+location.pathname))document.documentElement.classList.add('locked');if(localStorage.getItem('owlBig')==='1')document.documentElement.style.fontSize='112.5%'}catch(e){}</script>
<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">
<symbol id="i-home" viewBox="0 0 24 24"><path d="M3 11 12 3l9 8"/><path d="M5 10v10h5v-6h4v6h5V10"/></symbol>
<symbol id="i-calendar" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/></symbol>
<symbol id="i-settings" viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2.5"/><circle cx="9" cy="17" r="2.5"/></symbol>
<symbol id="i-users" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><circle cx="17" cy="9" r="2.6"/><path d="M15.5 14.3c3 .2 6 2.3 6 5.7"/></symbol>
<symbol id="i-chart" viewBox="0 0 24 24"><path d="M3 20h18"/><path d="M4 15l5-5 4 4 7-8"/><path d="M16 6h4v4"/></symbol>
<symbol id="i-bell" viewBox="0 0 24 24"><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/></symbol>
<symbol id="i-phone" viewBox="0 0 24 24"><rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18h2"/></symbol>
<symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></symbol>
<symbol id="i-book" viewBox="0 0 24 24"><path d="M12 6c-2-1.5-4.5-2-8-2v14c3.5 0 6 .5 8 2 2-1.5 4.5-2 8-2V4c-3.5 0-6 .5-8 2z"/><path d="M12 6v14"/></symbol>
<symbol id="i-pause" viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></symbol>
<symbol id="i-lock" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></symbol>
<symbol id="i-target" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/></symbol>
<symbol id="i-key" viewBox="0 0 24 24"><circle cx="8" cy="14" r="4"/><path d="M11 11 20 2M16 6l3 3M18 4l2 2"/></symbol>
<symbol id="i-switch" viewBox="0 0 24 24"><path d="M4 8h13l-3-3M20 16H7l3 3"/></symbol>
<symbol id="i-trash" viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/></symbol>
<symbol id="i-share" viewBox="0 0 24 24"><path d="M12 15V4M8 8l4-4 4 4"/><path d="M5 13v6h14v-6"/></symbol>
<symbol id="i-ticket" viewBox="0 0 24 24"><path d="M3 9V6h18v3a2 2 0 0 0 0 4v3H3v-3a2 2 0 0 0 0-4z"/><path d="M10 6v12"/></symbol>
<symbol id="i-bot" viewBox="0 0 24 24"><rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4M9 4h6"/><circle cx="9" cy="14" r="1.2"/><circle cx="15" cy="14" r="1.2"/></symbol>
<symbol id="i-exit" viewBox="0 0 24 24"><path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"/><path d="M10 16l-4-4 4-4M6 12h10"/></symbol>
<symbol id="i-reset" viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v4h-4"/></symbol>
<symbol id="i-eye" viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></symbol>
<symbol id="i-gift" viewBox="0 0 24 24"><rect x="3" y="9" width="18" height="4"/><path d="M5 13v8h14v-8M12 9v12"/><path d="M12 9c-2-4-6-4-6-1.5S12 9 12 9zM12 9c2-4 6-4 6-1.5S12 9 12 9z"/></symbol>
<symbol id="i-download" viewBox="0 0 24 24"><path d="M12 4v11M8 11l4 4 4-4"/><path d="M5 19h14"/></symbol>
<symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></symbol>
<symbol id="i-moon" viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></symbol>
<symbol id="i-cloud" viewBox="0 0 24 24"><path d="M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 11.5 3.5 3.5 0 0 0 7 18z"/></symbol>
<symbol id="i-bolt" viewBox="0 0 24 24"><path d="M7 15h9.5a3.5 3.5 0 0 0 .4-7A5.5 5.5 0 0 0 6.3 9 3 3 0 0 0 7 15z"/><path d="M12.5 13l-2.5 4h4l-2.5 4"/></symbol>
<symbol id="i-wave" viewBox="0 0 24 24"><path d="M3 10c2-3 4-3 6 0s4 3 6 0 4-3 6 0"/><path d="M3 16c2-3 4-3 6 0s4 3 6 0 4-3 6 0"/></symbol>
<symbol id="i-activity" viewBox="0 0 24 24"><path d="M3 12h4l3-7 4 14 3-7h4"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7"/></symbol>
<symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></symbol>
<symbol id="i-stop" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></symbol>
</svg>
<div class="bg"><div class="blob bl1"></div><div class="blob bl2"></div></div>
<div class="wrap">

<div class="view on" id="v-home">
<div class="hero">
<div class="ring"><img src="/icon192.png" alt="" style="width:64px;height:64px;border-radius:16px"></div>
<h1>OwlNest</h1>
<div class="tag">Le robot Owl trade pour vous,<br>
jour et nuit. Vous, vous regardez.</div>
</div>
<div class="preview">
<div class="pv-lbl" id="pv-lbl">Aper&ccedil;u en direct</div>
<div class="pv-money" id="pv-money">$1 234,56</div>
<div class="pv-eur" id="pv-eur">&asymp; 1 062 &euro;</div>
<svg viewBox="0 0 260 44" style="width:100%;height:44px;margin-top:10px">
<defs><linearGradient id="pg" x1="0" y1="0" x2="0" y2="1">
<stop id="pv-g1" offset="0%" stop-color="#2ecc71" stop-opacity=".35"/>
<stop id="pv-g2" offset="100%" stop-color="#2ecc71" stop-opacity="0"/>
</linearGradient></defs>
<polygon id="pv-area" fill="url(#pg)" points="0,44 0,34 30,30 60,33 90,24 120,27
 150,18 180,21 210,12 240,15 260,7 260,44"/>
<polyline id="pv-line" fill="none" stroke="#2ecc71" stroke-width="2.5"
 stroke-linecap="round" stroke-linejoin="round"
 points="0,34 30,30 60,33 90,24 120,27 150,18 180,21 210,12 240,15 260,7"/>
</svg>
<div class="pv-row"><span class="pv-chip" id="pv-chip">&#9650; +23,40 $
 aujourd&#8217;hui</span>
<span class="pv-chip2" id="pv-chip2">2 trades</span></div>
<div class="pv-bot"><svg class="ic ic-s"><use href="#i-bot"/></svg> <span id="pv-bot-t">L&#8217;Owl vient de gagner un trade
 pour vous</span></div>
</div>
<div class="feats" id="shots-sec">
<div class="how">Ce que vous verrez</div>
<div class="shots" id="shots">
 <figure><img src="/shots/shot_home.png" alt="Accueil OwlNest" loading="lazy" onerror="this.closest('figure').style.display='none'"><figcaption>Accueil &middot; solde et journ&eacute;e</figcaption></figure>
 <figure><img src="/shots/shot_marche.png" alt="March&eacute;" loading="lazy" onerror="this.closest('figure').style.display='none'"><figcaption>March&eacute; &middot; ce que le robot voit</figcaption></figure>
 <figure><img src="/shots/shot_hist.png" alt="Historique" loading="lazy" onerror="this.closest('figure').style.display='none'"><figcaption>Historique &middot; jour par jour</figcaption></figure>
</div>
</div>
<div class="feats">
<div class="how">Comment &ccedil;a marche</div>
<div class="fr"><div class="fi stp">1</div>
<div class="ft"><b>Choisissez votre formule</b>
<span>Signal : les alertes et la d&eacute;mo en direct, sans compte MT5.
 Automatique (famille) : le robot sur votre compte MT5. Rien &agrave;
 installer sur l&#8217;ordinateur.</span></div></div>
<div class="fr"><div class="fi stp">2</div>
<div class="ft"><b>Le robot veille, jour et nuit</b>
<span>Il surveille le march&eacute; en continu et n&#8217;agit que lorsque
 ses conditions sont r&eacute;unies.</span></div></div>
<div class="fr"><div class="fi stp">3</div>
<div class="ft"><b>Vous suivez tout, en direct</b>
<span>Solde, gains, trades du jour &mdash; mis &agrave; jour toutes les
 5 secondes, sur votre t&eacute;l&eacute;phone.</span></div></div>
</div>
<a class="bigbtn b1" href="/demo" style="display:block;
 text-decoration:none;text-align:center"><svg class="ic"><use href="#i-eye"/></svg> Voir le robot en direct
 &middot; gratuit</a>
<button class="bigbtn b2" onclick="show('v-login')" style="margin-top:12px">
Se connecter</button>
<a class="bigbtn b2" href="/offres" style="display:block;margin-top:12px;
 text-decoration:none;text-align:center">Cr&eacute;er un compte</a>
<button class="bigbtn b3" id="inst2" onclick="inst2()"
 style="margin-top:4px"><svg class="ic ic-s"><use href="#i-download"/></svg> Installer l&#8217;application</button>
<a class="bigbtn b3" id="apk2" href="/owlnest.apk" style="display:none;margin-top:4px;text-decoration:none;text-align:center"><svg class="ic ic-s"><use href="#i-phone"/></svg> T&eacute;l&eacute;charger l&#8217;application Android <span id="apk2-v" style="opacity:.7;font-weight:600"></span></a>
<div id="apk2-note" style="display:none;margin-top:8px;text-align:center;font-size:.78rem;color:var(--muted);line-height:1.5">Un fichier APK : Android demande une fois d&#8217;autoriser l&#8217;installation. Les mises &agrave; jour se posent par-dessus, sans rien d&eacute;sinstaller. Sur iPhone : &laquo; Installer l&#8217;application &raquo; ci-dessus.</div>
<div style="margin-top:14px;text-align:center;font-size:.8rem;color:var(--muted);
 line-height:1.5">La d&eacute;mo est gratuite, toujours. Les abonnements se paient
 chaque mois, &agrave; l&#8217;avance.<br>OwlNest vend un logiciel et un service de copie &mdash;
 pas de conseil ni de gestion d&#8217;investissement.</div>
<div id="howto2" style="display:none;margin-top:12px;background:#141c28;
 border:1px solid #1f2c3d;border-radius:14px;padding:14px;
 font-size:.9rem;color:#c6d3df;line-height:1.6;text-align:left">
&#128241; <b>Pour installer :</b><br>
1. Touchez le menu <b>&#8942;</b> en haut &agrave; droite de Chrome<br>
2. Choisissez <b>&laquo; Ajouter &agrave; l&#8217;&eacute;cran
 d&#8217;accueil &raquo;</b><br>
3. L&#8217;ic&ocirc;ne &#129417; appara&icirc;t !</div>
<div class="feats" id="plans">
<div class="how">Nos offres</div>
<div class="fr"><div class="fi stp" style="color:var(--muted2)">0</div>
<div class="ft"><b>D&eacute;mo &middot; gratuit, toujours</b>
<span>Le robot en direct sur un vrai compte de d&eacute;monstration : solde, trades, m&eacute;t&eacute;o du march&eacute;, bilan du soir. Sans compte.</span></div></div>
<div class="fr"><div class="fi stp" style="color:var(--up)">$29</div>
<div class="ft"><b>Signal &middot; 30 jours</b>
<span>Les signaux du robot sur votre t&eacute;l&eacute;phone, et tout ce que montre la d&eacute;mo. Sans compte MT5 : vous tradez o&ugrave; vous voulez.</span></div></div>
<div class="fr"><div class="fi stp" style="color:var(--warn)">$49</div>
<div class="ft"><b>Strat&eacute;gie &middot; 30 jours</b>
<span>Le graphique complet et la m&eacute;thode expliqu&eacute;e. Un paquet &agrave; part, qui se combine avec Signal ou Automatique.</span></div></div>
<div class="fr"><div class="fi stp" style="color:var(--accent-soft)">&#9733;</div>
<div class="ft"><b>Automatique &middot; famille, sur invitation</b>
<span>Le robot sur votre compte, avec ses r&egrave;gles et ses freins. Prix fixe chaque mois, r&eacute;gl&eacute; avec le Owl ; code d&#39;activation par Telegram. 50 places.</span></div></div>
<div style="font-size:.74rem;color:var(--muted);margin:6px 4px 0;line-height:1.5">Signal et Strat&eacute;gie : en crypto dans l&#39;app ou par code. Le d&eacute;tail complet est dans l&#39;application, R&eacute;glages &rsaquo; Abonnement.</div>
</div>
<div class="feats" id="faq">
<div class="how">Questions fr&eacute;quentes</div>
<details class="fq"><summary>Dois-je installer quelque chose sur mon ordinateur ?</summary>
<p>Non. Le robot tourne sur nos serveurs, jour et nuit. Vous, vous ouvrez cette page sur votre t&eacute;l&eacute;phone.</p></details>
<details class="fq"><summary>O&ugrave; est mon argent ?</summary>
<p>Sur votre propre compte MT5, chez votre courtier. Le robot y passe les ordres ; il ne peut ni retirer ni d&eacute;placer votre argent.</p></details>
<details class="fq"><summary>Et si le robot perd ?</summary>
<p>&Ccedil;a arrive. Il garde alors une petite r&eacute;serve de c&ocirc;t&eacute; et avance prudemment jusqu&#39;&agrave; se rattraper. Vous le voyez dans l&#39;application.</p></details>
<details class="fq"><summary>Puis-je arr&ecirc;ter quand je veux ?</summary>
<p>Oui. Un message suffit, et le robot ne prend plus de trade sur votre compte.</p></details>
<details class="fq"><summary>Puis-je suivre depuis plusieurs t&eacute;l&eacute;phones ?</summary>
<p>Oui. Votre lien personnel fonctionne partout ; vous pouvez le prot&eacute;ger avec un code &agrave; 4 chiffres.</p></details>
</div>
<div class="pfoot"><img src="/icon192.png" alt="">OwlNest &middot; fait avec amour
 par la famille Owl<br><span style="display:block;margin-top:8px;opacity:.75;line-height:1.5">Vos identifiants servent uniquement &agrave; relier le robot &agrave; votre compte. Ils ne sont jamais partag&eacute;s.</span></div>
</div>

<div class="view" id="v-login">
<a class="back" onclick="show('v-home')">&#8592; Retour</a>
<form class="card" method="POST" action="login">
<h2>Se connecter</h2>
<label for="lg">Identifiant <span style="font-weight:400;color:var(--muted)">(famille : num&eacute;ro de compte MT5)</span></label>
<input id="lg" name="login" required autocomplete="username"
 placeholder="votre identifiant">
<label for="pw">Mot de passe</label>
<div style="position:relative">
 <input id="pw" name="password" type="password" required
  autocomplete="current-password" placeholder="votre mot de passe"
  style="padding-right:52px">
 <button type="button" id="pweye" aria-label="Afficher le mot de passe"
  onclick="const p=document.getElementById('pw');p.type=p.type==='password'?'text':'password';this.style.opacity=p.type==='text'?'1':'.6'"
  style="position:absolute;right:8px;top:50%;transform:translateY(-50%);
  width:40px;height:40px;border:0;background:transparent;color:var(--text3);
  opacity:.6;display:flex;align-items:center;justify-content:center">
  <svg class="ic"><use href="#i-eye"/></svg></button>
</div>
<button class="go" id="gobtn">Continuer &#10142;</button>
<div style="margin-top:12px;font-size:.8rem;color:var(--muted);text-align:center;line-height:1.5">Pas encore membre ? <a href="/offres" style="color:#9fc2de">Cr&eacute;er un compte</a><br>Identifiant ou mot de passe oubli&eacute; ?
 <a href="https://t.me/%%TGBOT%%" style="color:#9fc2de">&Eacute;crivez &laquo; lien &raquo; au robot OwlNest sur Telegram</a></div>
</form>
</div>

</div><script>
document.addEventListener('submit',e=>{const b=document.getElementById('gobtn');
 if(b&&e.target.contains(b)){b.disabled=true;b.textContent='Un instant\u2026';}});
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
// 2026-10-03 (owner): the Android app, when a build exists (apk.json)
fetch('/apk.json',{cache:'no-store'}).then(r=>r.json()).then(j=>{
 if(!j||!j.versionCode||/iPad|iPhone|iPod/.test(navigator.userAgent))return;
 document.getElementById('apk2').style.display='block';
 document.getElementById('apk2-v').textContent='v'+j.version;
 document.getElementById('apk2-note').style.display='block';
 if(/Android/i.test(navigator.userAgent)){document.getElementById('apk2').className='bigbtn b2';document.getElementById('inst2').innerHTML='<svg class="ic ic-s"><use href="#i-download"/></svg> Ou ajouter &agrave; l&#8217;&eacute;cran d&#8217;accueil';}
}).catch(()=>{});
// 2026-09-26: the preview shows the PUBLIC demo account for real - its
// balance, today's result, its 7-day curve. Falls back to the static
// mock if the fetch fails. Set PV_LIVE=false to go back to the mock.
const PV_LIVE=true;
(async function(){
 if(!PV_LIVE)return;
 try{
  const r=await fetch('/demo',{redirect:'follow'});if(!r.ok)return;
  const base=new URL(r.url).pathname.replace(/\\/+$/,'')+'/';
  const d=await (await fetch(base+'api')).json();
  if(!d||typeof d.equity!=='number')return;
  const $=id=>document.getElementById(id);
  $('pv-money').textContent='$'+d.equity.toFixed(2);
  $('pv-eur').innerHTML=d.eurusd?('&asymp; '+(d.equity/d.eurusd).toFixed(0)+' &euro;')
   :'compte d\\u00e9mo public';
  const t=d.today||0,up=t>=0,ch=$('pv-chip');
  ch.innerHTML=(t>0?'&#9650; ':(t<0?'&#9660; ':''))+(up?'+':'-')+'$'+
   Math.abs(t).toFixed(2)+' aujourd\\u2019hui';
  ch.style.background=up?'rgba(46,204,113,.12)':'rgba(255,92,92,.12)';
  ch.style.color=up?'#2ecc71':'#ff5c5c';
  const n=(d.trades||[]).length;$('pv-chip2').textContent=n+' trade'+(n>1?'s':'');
  const wk=d.week||0;
  let nt=0;try{const dt=d.day_trades||{};const lim=Date.now()-7*86400e3;
   Object.keys(dt).forEach(k=>{if(new Date(k+'T00:00:00Z').getTime()>=lim)nt+=(dt[k]||[]).length;});}catch(e){}
  $('pv-bot-t').textContent='Cette semaine : '+(wk>=0?'+':'-')+'$'+
   Math.abs(wk).toFixed(2)+(nt?' \\u00b7 '+nt+' trade'+(nt>1?'s':''):'')+' \\u00b7 vrai compte';
  const c=d.curve||[];
  if(c.length>1){const mn=Math.min(...c,0),mx=Math.max(...c,0),sp=(mx-mn)||1;
   const P=(v,i)=>((i/(c.length-1))*260).toFixed(1)+','+
    (40-((v-mn)/sp*34)).toFixed(1);
   const pts=c.map(P).join(' '),col=c[c.length-1]>=0?'#2ecc71':'#ff5c5c';
   $('pv-line').setAttribute('points',pts);$('pv-line').setAttribute('stroke',col);
   $('pv-area').setAttribute('points','0,44 '+pts+' 260,44');
   $('pv-g1').setAttribute('stop-color',col);$('pv-g2').setAttribute('stop-color',col);}
  $('pv-lbl').textContent='Compte d\\u00e9mo public \\u00b7 '+(d.bot_killed?'en pause':'en direct');
  if(d.bot_killed){$('pv-bot-t').textContent='La d\\u00e9mo est en pause \\u2014 elle red\\u00e9marre bient\\u00f4t.';}
  else if(d.era_start){const es=new Date(d.era_start);if(!isNaN(es)&&Date.now()-es.getTime()<7*86400e3){
   $('pv-bot-t').textContent='D\\u00e9mo red\\u00e9marr\\u00e9e le '+String(es.getUTCDate()).padStart(2,'0')+'/'+String(es.getUTCMonth()+1).padStart(2,'0')+' \\u00b7 elle repart de z\\u00e9ro';}}
 }catch(e){}
})();
</script></body></html>"""


def _join_result(title, body_html):
    return ("<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,"
            "initial-scale=1\"><title>OwlNest</title>"
            "<style>@font-face{font-family:'Inter';src:url('/fonts/inter.woff2') format('woff2');font-weight:100 900;font-display:swap}body{background:#0b0f14;color:#e8eef4;margin:0;"
            "padding:40px 20px;font-family:'Inter',-apple-system,'Segoe UI',Roboto,"
            "sans-serif;text-align:center}a{color:#8fc6ff;font-size:1rem;"
            "word-break:break-all}.k{background:#121a25;border:1px solid #1f2a38;border-radius:24px;"
            "box-shadow:inset 0 1px 0 rgba(255,255,255,.04);padding:26px 20px;"
            "max-width:420px;margin:0 auto;line-height:1.6}h2{font-size:1.2rem;margin:0 0 8px}"
            "p{color:#c6d3df;font-size:.95rem;margin:8px 0}"
            "</style></head><body><div class=\"k\">"
            f"<h2>{title}</h2>{body_html}</div></body></html>")


def _step2_page(login, pwd):
    """Smart login step 2 (2026-09-06 user): the account is new - ask
    ONLY the missing pieces (first name + server)."""
    import html as _h
    return ("<!doctype html><html lang=\"fr\"><head>"
            "<meta charset=\"utf-8\"><meta name=\"viewport\" "
            "content=\"width=device-width,initial-scale=1\">"
            "<title>OwlNest</title><style>@font-face{font-family:'Inter';"
            "src:url('/fonts/inter.woff2') format('woff2');font-weight:100 900;"
            "font-display:swap}body{background:#0b0f14;"
            "color:#e8eef4;margin:0;padding:34px 20px;font-family:'Inter',"
            "-apple-system,'Segoe UI',Roboto,sans-serif}.k{background:"
            "#121a25;border:1px solid #1f2a38;border-radius:24px;padding:24px 20px;"
            "max-width:420px;margin:0 auto;box-shadow:inset 0 1px 0 rgba(255,255,255,.04)}"
            "h2{font-size:1.2rem;margin:0 0 6px}"
            "label{display:block;margin:16px 0 7px;color:#9fc2de;"
            "font-size:.92rem;font-weight:600}input{width:100%;"
            "box-sizing:border-box;padding:15px;border-radius:12px;"
            "border:1px solid #2b3a4d;background:#0b0f14;color:"
            "#e8eef4;font-size:1.05rem}input:focus{outline:none;border-color:#3b82f6}"
            "button{width:100%;margin-top:"
            "22px;background:#3b82f6;color:#fff;border:0;border-radius:"
            "14px;padding:16px;font-size:1.05rem;font-weight:700}"
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


def _offers_page(login, pwd, pending_pkg=None, name=""):
    """2026-10-04 (owner): after the login, when the account does not
    exist (or has no package): the three offers; 'Choisir' opens the code
    modal - a code activates, the Owl on Telegram gives one, Signal and
    Strategie can be bought in crypto on the spot. What was typed at the
    login is carried over, hidden."""
    import html as _h
    cfg = nest_config()
    contact = _h.escape(cfg.get("contact_url") or "")
    pay = bool(cfg.get("np_api_key"))
    numeric = login.isdigit()
    note = ""
    if pending_pkg:
        lab = {"family": "Automatique", "manual": "Signal", "strategy": "Strat&eacute;gie"}.get(pending_pkg, pending_pkg)
        note = (f"<div class=\"note\">Votre demande <b>{lab}</b> est en attente. Entrez le code d&egrave;s que le Owl vous l&#8217;envoie, "
                "ou choisissez une autre formule.</div>")

    def tier(k, title, price, lines, color):
        return (f"<div class=\"t\" style=\"border-color:{color}\"><div class=\"th\"><b>{title}</b><span style=\"color:{color}\">{price}</span></div>"
                + "".join(f"<div class=\"tl\">&#10003; {x}</div>" for x in lines)
                + f"<button type=\"button\" class=\"go\" onclick=\"pick('{k}')\">Choisir {title}</button></div>")
    tiers = (tier("manual", "Signal", "$%d / 30 jours" % PACKAGES["manual"]["usd"],
                  ["Les signaux du robot sur votre t&eacute;l&eacute;phone", "Tout ce que montre la d&eacute;mo, en direct", "Sans compte MT5 : vous tradez o&ugrave; vous voulez"], "var(--up)")
             + tier("strategy", "Strat&eacute;gie", "$%d / 30 jours" % PACKAGES["strategy"]["usd"],
                    ["Le graphique complet : points prot&eacute;g&eacute;s, cassures, niveaux", "La m&eacute;thode expliqu&eacute;e en mots simples", "Se combine avec Signal ou Automatique"], "var(--warn)")
             + tier("family", "Automatique", "Famille, sur invitation",
                    ["Le robot trade sur votre compte MT5, jour et nuit", "Ses r&egrave;gles, ses freins, son rattrapage", "Prix fixe chaque mois, code par Telegram"], "var(--accent-soft)"))
    return ("<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
            "<meta name=\"theme-color\" content=\"#0f2740\"><title>OwlNest</title><link rel=\"icon\" href=\"/icon192.png\">"
            "<style>@font-face{font-family:'Inter';src:url('/fonts/inter.woff2') format('woff2');font-weight:100 900;font-display:swap}"
            ":root{--up:#2ecc71;--warn:#e8c55a;--accent-soft:#8fc6ff}"
            "body{margin:0;background:#0b0f14;color:#e8eef4;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:22px 18px 40px}"
            ".c{max-width:440px;margin:0 auto}.top{display:flex;align-items:center;gap:10px;margin-bottom:16px}.top img{width:40px;height:40px;border-radius:11px}.top b{font-size:1.1rem}"
            "h1{font-size:1.3rem;margin:0 0 4px}p{color:#c6d3df;line-height:1.5;font-size:.92rem;margin:0 0 14px}"
            ".note{background:rgba(232,197,90,.1);border:1px solid rgba(232,197,90,.4);border-radius:12px;padding:10px 12px;font-size:.86rem;margin-bottom:14px;line-height:1.45}"
            ".t{background:#121a25;border:1px solid #1f2a38;border-radius:18px;padding:16px;margin-top:12px}.th{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:8px}.th b{font-size:1.1rem}.th span{font-weight:700;font-size:.9rem;text-align:right}"
            ".tl{font-size:.88rem;color:#c6d3df;line-height:1.45;margin:4px 0}"
            ".go{display:block;width:100%;box-sizing:border-box;margin-top:12px;border:0;border-radius:14px;padding:13px;font-size:1rem;font-weight:700;cursor:pointer;background:#3b82f6;color:#fff}"
            ".ghost{background:#141c28;color:#c6d3df;border:1px solid #1f2c3d;text-decoration:none;text-align:center;display:block}"
            "label{display:block;font-size:.74rem;color:#8a9bb0;text-transform:uppercase;letter-spacing:.06em;margin:12px 0 6px}"
            "input{width:100%;box-sizing:border-box;background:#141c28;border:1px solid #1f2c3d;border-radius:12px;color:#e8eef4;padding:13px 14px;font-size:1rem}"
            "input#code{letter-spacing:.3em;text-transform:uppercase;font-weight:800;text-align:center;font-size:1.3rem}"
            ".h{font-size:.78rem;color:#8a9bb0;line-height:1.45;margin-top:6px}"
            "#bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:5}#md{display:none;position:fixed;left:0;right:0;bottom:0;background:#121a25;border-radius:22px 22px 0 0;padding:18px 18px 28px;z-index:6;max-height:92vh;overflow:auto}"
            "#md h2{margin:0 0 6px;font-size:1.15rem}a{color:#9fc2de}.back{display:inline-block;margin-bottom:12px;color:#9fc2de;text-decoration:none}"
            "</style></head><body><div class=\"c\"><div class=\"top\"><img src=\"/icon192.png\" alt=\"\"><b>OwlNest</b></div>"
            "<a class=\"back\" href=\"/\">&#8592; Retour</a>"
            f"<h1>Choisissez votre formule</h1><p>Un code d&#8217;activation ouvre votre compte. Le Owl vous le donne sur Telegram ; Signal et Strat&eacute;gie s&#8217;ach&egrave;tent aussi en crypto, activation imm&eacute;diate. Vos identifiants vous sont demand&eacute;s apr&egrave;s votre choix &mdash; un compte MT5 seulement pour Automatique.</p>{note}{tiers}"
            "</div><div id=\"bg\" onclick=\"closeM()\"></div><div id=\"md\">"
            "<h2 id=\"mt\"></h2><p id=\"mp\"></p>"
            "<form method=\"POST\" action=\"/activate\" id=\"f\" autocomplete=\"off\">"
            "<input type=\"hidden\" name=\"pkg\" id=\"pkg\"><input type=\"hidden\" name=\"action\" id=\"act\" value=\"activate\">"
            f"<label for=\"name\">Votre pr&eacute;nom</label><input id=\"name\" name=\"name\" maxlength=\"30\" placeholder=\"Pr&eacute;nom\" value=\"{_h.escape(name)}\">"
            "<label for=\"lg\" id=\"lgl\">Choisissez un identifiant</label>"
            f"<input id=\"lg\" name=\"login\" maxlength=\"24\" autocomplete=\"off\" placeholder=\"ex. mike77\" value=\"{_h.escape(login)}\">"
            "<div class=\"h\" id=\"lgh\">Lettres et chiffres. Pas besoin de compte MT5 pour Signal et Strat&eacute;gie.</div>"
            "<label for=\"pw\" id=\"pwl\">Choisissez un mot de passe</label>"
            f"<input id=\"pw\" name=\"password\" type=\"password\" maxlength=\"64\" autocomplete=\"new-password\" placeholder=\"6 caract&egrave;res au moins\" value=\"{_h.escape(pwd)}\">"
            "<div id=\"mt5\"><label for=\"server\">Serveur MT5</label><input id=\"server\" name=\"server\" placeholder=\"Exness-MT5Real30\" list=\"srv\">"
            "<datalist id=\"srv\"><option value=\"Exness-MT5Real30\"><option value=\"Exness-MT5Real27\"><option value=\"Exness-MT5Trial9\"></datalist>"
            "<div class=\"h\">Visible dans votre application MT5 : Param&egrave;tres &rsaquo; Comptes.</div></div>"
            "<label for=\"code\">Code d&#8217;activation</label><input id=\"code\" name=\"code\" maxlength=\"6\" placeholder=\"ABC123\" autocapitalize=\"characters\">"
            "<button class=\"go\" id=\"ok\" onclick=\"document.getElementById('act').value='activate'\">Activer</button>"
            + ("<button class=\"go\" id=\"buy\" type=\"button\" onclick=\"buyNow()\">Acheter maintenant en crypto &middot; activation imm&eacute;diate</button>" if pay else "")
            + (f"<a class=\"go ghost\" id=\"tg\" href=\"{contact}\" target=\"_blank\" rel=\"noopener\" onclick=\"pend()\">&#9993; Pas de code ? Contacter le Owl sur Telegram</a>" if contact else "")
            + "<div class=\"h\" id=\"mh\"></div></form></div>"
            "<script>var P='';function pick(k){P=k;document.getElementById('pkg').value=k;var L={manual:'Signal',strategy:'Strat\u00e9gie',family:'Automatique'}[k];"
            "document.getElementById('mt').textContent=L+' \u00b7 code d\u2019activation';"
            "document.getElementById('mp').textContent=k==='family'?'Le Owl vous envoie le code sur Telegram apr\u00e8s un mot ensemble.':'Entrez votre code, ou achetez maintenant : votre compte s\u2019active tout de suite.';"
            "document.getElementById('mt5').style.display=k==='family'?'':'none';var b=document.getElementById('buy');if(b)b.style.display=k==='family'?'none':'';"
            "var fam=(k==='family');document.getElementById('lgl').textContent=fam?'Num\u00e9ro de compte MT5':'Choisissez un identifiant';document.getElementById('lg').placeholder=fam?'12345678':'ex. mike77';document.getElementById('lg').setAttribute('inputmode',fam?'numeric':'text');"
            "document.getElementById('lgh').textContent=fam?'Le compte que le robot va trader.':'Lettres et chiffres. Pas besoin de compte MT5 pour Signal et Strat\u00e9gie.';"
            "document.getElementById('pwl').textContent=fam?'Mot de passe du compte MT5 (principal)':'Choisissez un mot de passe';document.getElementById('pw').placeholder=fam?'le robot doit pouvoir trader':'6 caract\u00e8res au moins';"
            "document.getElementById('mh').textContent=k==='family'?'':'La page de paiement (NOWPayments) est en anglais : choisissez la monnaie (USDT sur Tron, le moins cher), \u00ab Next step \u00bb, envoyez le montant exact ; votre compte s\u2019active tout seul d\u00e8s confirmation.';"
            "document.getElementById('bg').style.display='block';document.getElementById('md').style.display='block';setTimeout(function(){document.getElementById('code').focus();},150);}"
            "function closeM(){document.getElementById('bg').style.display='none';document.getElementById('md').style.display='none';}"
            "function need(){var n=document.getElementById('name').value.trim();if(!n){alert('Votre pr\u00e9nom, s\u2019il vous pla\u00eet.');return false;}"
            "var l=document.getElementById('lg').value.trim(),p=document.getElementById('pw').value;if(!l){alert(P==='family'?'Le num\u00e9ro de votre compte MT5.':'Choisissez un identifiant.');return false;}"
            "if(P!=='family'&&!/^[A-Za-z0-9]{3,24}$/.test(l)){alert('Identifiant : lettres et chiffres seulement, 3 \u00e0 24.');return false;}"
            "if(P==='family'&&!/^\\d{5,12}$/.test(l)){alert('Le num\u00e9ro de compte MT5, en chiffres.');return false;}"
            "if(!p||p.length<6){alert('Mot de passe : 6 caract\u00e8res au moins.');return false;}return true;}"
            "function buyNow(){if(!need())return;document.getElementById('act').value='buy';document.getElementById('f').submit();}"
            "function pend(){if(!need()){event.preventDefault();return;}var fd=new FormData(document.getElementById('f'));fd.set('action','pending');"
            "try{navigator.sendBeacon('/activate',new URLSearchParams(fd));}catch(e){}}"
            "document.getElementById('f').addEventListener('submit',function(e){if(document.getElementById('act').value==='activate'){if(!need()){e.preventDefault();return;}if(document.getElementById('code').value.trim().length<6){e.preventDefault();alert('Entrez le code complet (6 caract\u00e8res).');}}});"
            + (f"pick('{pending_pkg}');" if pending_pkg in ("manual", "strategy", "family") else "")
            + "</script></body></html>")


def _code_page(mode, login, pwd, name=""):
    """2026-10-04 (owner): the second step of the login. `mode` = "new"
    (no such account: a code opens one) or "renew" (the package ended:
    a code renews it). What was typed is carried over, hidden."""
    import html as _h
    cfg = nest_config()
    contact = cfg.get("contact_url") or ""
    title = "Abonnement termin&eacute;" if mode == "renew" else "Pas encore de compte"
    intro = ((f"<p>Bonjour {_h.escape(name)} &mdash; votre p&eacute;riode est termin&eacute;e. Entrez le code de renouvellement : "
              "il ajoute 30 jours (ou plus) et tout repart.</p>") if mode == "renew" else
             "<p>Ce compte n&#8217;est pas encore dans le nid. Un <b>code d&#8217;activation</b> l&#8217;ouvre : "
             "Le Owl vous l&#8217;envoie sur Telegram (Automatique, Signal, Strat&eacute;gie), ou vous l&#8217;achetez en crypto ci-dessous.</p>")
    cta = (f"<a class=\"b g\" href=\"{_h.escape(contact)}\" target=\"_blank\" rel=\"noopener\">&#9993; &Eacute;crire au Owl sur Telegram</a>" if contact else
           "<div class=\"h\" style=\"text-align:center\">Le Owl vous donne le code sur Telegram.</div>")
    name_field = "" if mode == "renew" else (
        "<label for=\"name\">Votre pr&eacute;nom</label>"
        f"<input id=\"name\" name=\"name\" required maxlength=\"30\" placeholder=\"Pr&eacute;nom\" value=\"{_h.escape(name)}\">")
    mt5 = "" if mode == "renew" else (
        "<div id=\"mt5\"><label for=\"server\">Serveur MT5</label>"
        "<input id=\"server\" name=\"server\" placeholder=\"Exness-MT5Real30\" list=\"srv\">"
        "<datalist id=\"srv\"><option value=\"Exness-MT5Real30\"><option value=\"Exness-MT5Real27\"><option value=\"Exness-MT5Trial9\"></datalist>"
        "<div class=\"h\">Visible dans votre application MT5 : Param&egrave;tres &rsaquo; Comptes. Pour Automatique, le mot de passe tap&eacute; doit &ecirc;tre le mot de passe principal du compte.</div></div>")
    buy = "" if mode == "renew" else (
        "<label for=\"buy\">Pas de code ? Acheter en crypto</label>"
        "<select id=\"buy\" name=\"buy\"><option value=\"\">&mdash; j&#8217;ai un code &mdash;</option>"
        "<option value=\"manual\">Signal &middot; $29 / 30 jours</option><option value=\"strategy\">Strat&eacute;gie &middot; $49 / 30 jours</option></select>"
        "<div class=\"h\">NOWPayments ouvre une page : USDT, BTC ou autre. Votre compte s&#8217;active d&egrave;s que le paiement est confirm&eacute;.</div>")
    js = ("<script>function mode(p){var m=document.getElementById('mt5');if(m){m.style.display=p==='family'?'':'none';"
          "var s=document.getElementById('server');if(s)s.required=(p==='family');}}mode('family');"
          "document.getElementById('code').addEventListener('input',function(){var c=this.value.trim().toUpperCase();var h=document.getElementById('ch');"
          "if(c.length<6){h.textContent='';return;}fetch('/codeinfo?c='+encodeURIComponent(c)).then(function(r){return r.json();}).then(function(j){"
          "if(j&&j.ok){h.textContent='Code '+j.label+' \u00b7 '+j.days+' jours';mode(j.pkg);}else{h.textContent='Code inconnu ou d\u00e9j\u00e0 utilis\u00e9.';mode('family');}}).catch(function(){});});"
          "var b=document.getElementById('buy');if(b)b.addEventListener('change',function(){mode(this.value?'manual':'family');});</script>")
    return ("<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
            "<meta name=\"theme-color\" content=\"#0f2740\"><title>OwlNest</title><link rel=\"icon\" href=\"/icon192.png\">"
            "<style>@font-face{font-family:'Inter';src:url('/fonts/inter.woff2') format('woff2');font-weight:100 900;font-display:swap}"
            "body{margin:0;background:#0b0f14;color:#e8eef4;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:22px 18px 40px}"
            ".c{max-width:420px;margin:0 auto}.top{display:flex;align-items:center;gap:10px;margin-bottom:18px}.top img{width:40px;height:40px;border-radius:11px}.top b{font-size:1.1rem}"
            "h1{font-size:1.35rem;margin:0 0 6px}p{color:#c6d3df;line-height:1.55;font-size:.95rem;margin:0 0 14px}"
            "label{display:block;font-size:.76rem;color:#8a9bb0;text-transform:uppercase;letter-spacing:.06em;margin:14px 0 6px}"
            "input,select{width:100%;box-sizing:border-box;background:#141c28;border:1px solid #1f2c3d;border-radius:12px;color:#e8eef4;padding:13px 14px;font-size:1rem}"
            "input#code{letter-spacing:.3em;text-transform:uppercase;font-weight:800;text-align:center;font-size:1.3rem}"
            ".h{font-size:.78rem;color:#8a9bb0;line-height:1.45;margin-top:6px}"
            "button,a.b{display:block;width:100%;box-sizing:border-box;margin-top:14px;border:0;border-radius:14px;padding:14px;font-size:1rem;font-weight:700;cursor:pointer;text-decoration:none;text-align:center}"
            "button{background:#3b82f6;color:#fff}a.b.g{background:#141c28;color:#c6d3df;border:1px solid #1f2c3d}a{color:#9fc2de}"
            "</style></head><body><div class=\"c\"><div class=\"top\"><img src=\"/icon192.png\" alt=\"\"><b>OwlNest</b></div>"
            f"<h1>{title}</h1>{intro}{cta}"
            "<form method=\"POST\" action=\"/activate\" autocomplete=\"off\">"
            f"<input type=\"hidden\" name=\"login\" value=\"{_h.escape(login)}\"><input type=\"hidden\" name=\"password\" value=\"{_h.escape(pwd)}\">"
            "<label for=\"code\">Code d&#8217;activation</label><input id=\"code\" name=\"code\" maxlength=\"6\" placeholder=\"ABC123\" autocapitalize=\"characters\"><div class=\"h\" id=\"ch\"></div>"
            f"{buy}{name_field}{mt5}"
            "<label for=\"tg\">Telegram (facultatif)</label><input id=\"tg\" name=\"telegram\" maxlength=\"40\" placeholder=\"@votre_nom\">"
            f"<button>{'Renouveler' if mode == 'renew' else 'Ouvrir mon compte'} &#10142;</button></form>"
            "<p style=\"margin-top:16px;text-align:center\"><a href=\"/\">&larr; Retour</a></p>"
            f"{js}</div></body></html>")


def _member_active(u):
    """Does this member have a running package? Owners always."""
    uid = u.get("id")
    if uid in OWNER_UIDS or u.get("public"):
        return True
    return has(uid, "family") or has(uid, "manual") or has(uid, "strategy")


def handle_login(form):
    """Smart login (2026-09-06 user): one page for everyone.
    Known account+password -> straight in. Known account, wrong
    password -> error. Unknown account -> step 2 (auto-register)."""
    import re as _re
    raw = (form.get("login", [""])[0] or "").strip()[:40]
    pwd = (form.get("password", [""])[0] or "").strip()[:64]
    if _re.search(r"[A-Za-z]", raw):
        # 2026-10-03 (owner): a Signal / Strategie member logs in with the
        # identifiant given at activation and the password they chose
        ident = _re.sub(r"[^a-z0-9]", "", raw.lower())
        if rate_limited(("login", ident)):
            return ("page", _join_result("&#9203; Trop d&#8217;essais", "<p>Attendez 10 minutes puis r&eacute;essayez.</p>"))
        au = next((x for x in users() if (x.get("app_only") or x.get("app_login")) and x.get("id") == ident), None)
        if au is not None and au.get("app_pwd") == _app_hash(pwd):
            if _member_active(au):
                return ("redirect", f"https://owltrader.duckdns.org/{au['token']}/")
            return ("page", _offers_page(raw, pwd, au.get("pending_code") or au.get("plan"), au.get("name", "")))
        if au is not None:
            rate_fail(("login", ident))
            return ("page", _join_result("&#128274; Mot de passe incorrect",
                                         "<p>Cet identifiant existe ; le mot de passe est celui que vous avez choisi &agrave; l&#8217;activation.</p>"
                                         "<p><a href=\"/\">&larr; R&eacute;essayer</a></p>"))
        # 2026-10-04 (owner): one door - unknown -> the offers
        return ("page", _offers_page(raw, pwd))
    login = _re.sub(r"\D", "", raw)[:12]
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
        if u.get("app_pwd") and not u.get("mt5_password"):
            # 2026-10-04: an app account whose identifiant is a number
            if u.get("app_pwd") != _app_hash(pwd):
                rate_fail(("login", login))
                return ("page", _join_result("&#128274; Mot de passe incorrect",
                                             "<p>Le mot de passe est celui choisi &agrave; l&#8217;activation.</p><p><a href=\"/\">&larr; R&eacute;essayer</a></p>"))
            if _member_active(u):
                return ("redirect", f"https://owltrader.duckdns.org/{u['token']}/")
            return ("page", _offers_page(login, pwd, u.get("pending_code") or u.get("plan"), u.get("name", "")))
        if (u.get("mt5_password") or "") == pwd:
            if not _member_active(u):
                # 2026-10-04 (owner): known, but no running package - the offers
                return ("page", _offers_page(login, pwd, u.get("pending_code") or u.get("plan"), u.get("name", "")))
            return ("redirect", f"https://owltrader.duckdns.org/"
                                f"{u['token']}/")
        rate_fail(("login", login))
        return ("page", _join_result(
            "&#128274; Mot de passe incorrect",
            "<p>Ce compte existe d&eacute;j&agrave; dans le nid, mais "
            "le mot de passe ne correspond pas. V&eacute;rifiez-le dans "
            "votre application MT5, puis r&eacute;essayez.</p>"
            "<p><a href=\"/\">&larr; R&eacute;essayer</a></p>"))
    # 2026-10-04 (owner): one door - unknown account -> the offers
    return ("page", _offers_page(login, pwd))


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
                            "<p>Contactez le Owl pour une place.</p>")
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


def _app_hash(p):
    import hashlib as _hl
    return _hl.sha256(("owl|" + (p or "")).encode("utf-8")).hexdigest()


def _data_user(u):
    """2026-10-03 (owner): a Signal / Strategie member has no MT5 account.
    Their page shows the PUBLIC DEMO's live view - balance, trades, market
    weather, evening review - under their own name and package."""
    if not (u and u.get("app_only")):
        return u
    return next((x for x in users() if x.get("public")), u)


def family_count():
    """Family (Automatique) accounts on this VPS: members whose account the robot trades."""
    return sum(1 for x in users() if x.get("trade") and x.get("id") not in OWNER_UIDS and not x.get("public"))


def _find_member(raw_login, pwd):
    """The member these credentials belong to, or None (wrong password
    counts as none - the offers page then creates nothing on top)."""
    import re as _re
    if not raw_login:
        return None
    if _re.search(r"[A-Za-z]", raw_login):
        ident = _re.sub(r"[^a-z0-9]", "", raw_login.lower())
        u = next((x for x in users() if x.get("id") == ident and x.get("app_pwd")), None)
        return u if (u and u.get("app_pwd") == _app_hash(pwd)) else None
    login = _re.sub(r"\D", "", raw_login)[:12]
    u = next((x for x in users() if str(x.get("login")) == login or str(x.get("mt5_login") or "") == login), None)
    if u and u.get("app_pwd") and not u.get("mt5_password"):
        return u if u.get("app_pwd") == _app_hash(pwd) else None
    return u if (u and (u.get("mt5_password") or "") == pwd) else None


def _file_pending(form):
    """'Contact the Owl': the request is kept so the admin sees it in Le
    Nid and can activate it from there. Nothing is granted yet."""
    import re as _re
    raw = (form.get("login", [""])[0] or "").strip()[:40]
    pwd = (form.get("password", [""])[0] or "").strip()[:64]
    name = (form.get("name", [""])[0] or "").strip()[:30]
    pkg = (form.get("pkg", [""])[0] or "").strip()
    server = (form.get("server", [""])[0] or "").strip()[:48]
    ml = _re.sub(r"\D", "", form.get("mt5_login", [""])[0] or raw)[:12]
    if pkg not in ("family", "manual", "strategy") or not pwd:
        return None
    u = _find_member(raw, pwd)
    allu = json.load(open(USERS_FILE, encoding="utf-8"))
    if u is None:
        if not name:
            return None
        rec = _new_app_only_record(name, pwd, "", pkg, allu, raw)
        if rec is None:
            return None
        rec.pop("app_only", None)
        rec.update({"via": "telegram"})
        if pkg == "family" and ml:
            rec.update({"login": int(ml), "mt5_login": int(ml), "mt5_password": pwd, "mt5_server": server})
        allu.append(rec)
        u = rec
    for x in allu:
        if x.get("id") == u.get("id"):
            x["pending_code"] = pkg
            x["asked_at"] = int(time.time())
            if pkg == "family" and ml and not x.get("mt5_login"):
                x.update({"login": int(ml), "mt5_login": int(ml), "mt5_password": pwd, "mt5_server": server})
    json.dump(allu, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    _users_cache["t"] = 0.0
    try:
        _qf = os.path.join(DIR, "owl_push_queue.json")
        try:
            _q = json.load(open(_qf, encoding="utf-8"))
        except Exception:
            _q = []
        _lab = {"family": "Automatique", "manual": "Signal", "strategy": "Strategie"}[pkg]
        _q.append({"uid": "kino", "t": int(time.time()), "title": "\U0001f511 Demande de code \u00b7 " + (u.get("name") or u.get("id")),
                   "body": f"{_lab} \u00b7 identifiant {u.get('id')}" + (f" \u00b7 compte {ml}" if pkg == "family" and ml else "") + " \u00b7 Le Nid \u203a En attente"})
        json.dump(_q, open(_qf, "w", encoding="utf-8"))
    except Exception:
        pass
    return u


def grant_pending(uid, days=30, pkg=None):
    """The admin's 'Activer' on a pending request (or the code's grant on
    an existing record): the package goes on; a family account gets its
    robot. Returns (ok, message)."""
    allu = json.load(open(USERS_FILE, encoding="utf-8"))
    x = next((r for r in allu if r.get("id") == uid), None)
    if x is None:
        return False, "inconnu"
    pkg = pkg or x.get("pending_code") or x.get("plan") or "manual"
    if pkg == "family":
        if not (x.get("mt5_login") and x.get("mt5_password") and x.get("mt5_server")):
            return False, "compte MT5 manquant"
        if not x.get("trade") and family_count() >= FAMILY_CAP:
            return False, "plein"
        x.pop("app_only", None)
        x.update({"terminal": x.get("terminal") or "", "symbol": "BTCUSD", "bot_only": True, "plan": "family", "mode": x.get("mode") or "auto",
                  "trade": True, "dedicated": x.get("dedicated") or f"structure_bos_bot.py {uid}", "managed": True})
        if x.get("app_pwd"):
            x["app_login"] = True
    else:
        if not x.get("trade"):
            x["app_only"] = True
        x["plan"] = x.get("plan") if x.get("trade") else pkg
    x.pop("pending_code", None)
    x.pop("asked_at", None)
    json.dump(allu, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    _users_cache["t"] = 0.0
    ent_grant(uid, pkg, int(days), "kino")
    try:
        _pf = os.path.join(DIR, pause_file(uid))
        if json.load(open(_pf, encoding="utf-8")).get("by") == "expiry":
            json.dump({"paused": False, "by": "renewal", "t": time.time()}, open(_pf, "w"))
    except Exception:
        pass
    return True, pkg


def handle_activate(form, origin="https://owltrader.duckdns.org"):
    """2026-10-03 (owner): open an account from an activation code. The
    code names the package; the MT5 account is checked for duplicates;
    the terminal is created by the provisioner, the robot by the manager
    (Automatique). A known account with the right password is renewed
    instead of duplicated."""
    import re as _re
    code = (form.get("code", [""])[0] or "").strip().upper()[:12]
    name = (form.get("name", [""])[0] or "").strip()[:30]
    raw_login = (form.get("login", [""])[0] or "").strip()[:40]
    login = _re.sub(r"\D", "", raw_login)[:12]
    pwd = (form.get("password", [""])[0] or "").strip()[:64]
    server = (form.get("server", [""])[0] or "").strip()[:48]
    tg = (form.get("telegram", [""])[0] or "").strip()[:40]
    buy = (form.get("buy", [""])[0] or "").strip()
    action = (form.get("action", [""])[0] or "").strip()
    pkg_chosen = (form.get("pkg", [""])[0] or "").strip()
    if action == "buy" and pkg_chosen in ("manual", "strategy"):
        buy = pkg_chosen
    if action == "pending":
        u = _file_pending(form)
        return _join_result("&#9993; Demande envoy&eacute;e",
                            "<p>Le Owl vous r&eacute;pond sur Telegram. D&egrave;s que c&#8217;est r&eacute;gl&eacute;, reconnectez-vous avec les m&ecirc;mes identifiants : votre compte sera actif, ou entrez le code re&ccedil;u.</p>"
                            "<p><a href=\"/\">&larr; Retour</a></p>") if u else _join_result("&#10060; Il manque une information", "<p>Votre pr&eacute;nom et un mot de passe.</p>")
    # the offers modal names the MT5 account in its own field
    if not login and form.get("mt5_login", [""])[0]:
        login = _re.sub(r"\D", "", form.get("mt5_login", [""])[0] or "")[:12]
    if rate_limited(("activate", code or login or "?"), limit=8):
        return _join_result("&#9203; Trop d&#8217;essais", "<p>Attendez 10 minutes puis r&eacute;essayez.</p>")
    if not pwd or not (code or buy in ("manual", "strategy")):
        return _join_result("&#10060; Il manque une information",
                            "<p>Revenez en arri&egrave;re et remplissez toutes les cases : un code, ou un paquet &agrave; acheter.</p>")
    if not code:
        if not name:
            return _join_result("&#10060; Il manque votre pr&eacute;nom", "<p>Revenez en arri&egrave;re et indiquez votre pr&eacute;nom.</p>")
        return _activate_buy(name, pwd, tg, buy, origin, raw_login)
    ce = peek_activation_code(code)
    if not ce:
        rate_fail(("activate", code))
        return _join_result("&#10060; Code inconnu ou d&eacute;j&agrave; utilis&eacute;",
                            "<p>V&eacute;rifiez le code, ou demandez-en un nouveau au Owl sur Telegram.</p>"
                            "<p><a href=\"/activate\">&larr; R&eacute;essayer</a></p>")
    pkg, days = ce.get("pkg") or "family", int(ce.get("days") or 30)
    labels = {"family": "Automatique", "manual": "Signal", "strategy": "Strat&eacute;gie"}
    ex = _find_member(raw_login, pwd)
    if ex is not None and (ex.get("pending_code") or ex.get("app_pwd")):
        # a pending request, or a Signal / Strategie member: the code activates THIS record
        if pkg == "family" and not (ex.get("mt5_login") and ex.get("mt5_server")):
            ml = _re.sub(r"\D", "", form.get("mt5_login", [""])[0] or "")[:12]
            if not (ml and server):
                return _join_result("&#10060; Il manque le compte MT5",
                                    "<p>Un code Automatique demande le num&eacute;ro de compte MT5 et le serveur.</p><p><a href=\"/\">&larr; Retour</a></p>")
            allu = json.load(open(USERS_FILE, encoding="utf-8"))
            for x in allu:
                if x.get("id") == ex["id"]:
                    x.update({"login": int(ml), "mt5_login": int(ml), "mt5_password": pwd, "mt5_server": server})
            json.dump(allu, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            _users_cache["t"] = 0.0
        ok, why = grant_pending(ex["id"], days, pkg)
        if not ok:
            return _join_result("&#9203; Pas possible pour l&#8217;instant", f"<p>{why}</p><p><a href=\"/\">&larr; Retour</a></p>")
        redeem_activation_code(code, ex["id"])
        ex = _find_member(raw_login, pwd) or ex
        return _join_result("&#9989; " + labels.get(pkg, pkg) + " activ&eacute;",
                            f"<p>{days} jours pour {ex.get('name') or ex.get('id')}.</p>"
                            + ("<p>Le robot tourne sur votre compte dans quelques minutes.</p>" if pkg == "family" else "")
                            + f"<p><a href=\"https://owltrader.duckdns.org/{ex['token']}/\">Ouvrir mon OwlNest</a></p>")
    if pkg == "family" and not (login and server):
        return _join_result("&#10060; Il manque le compte MT5",
                            "<p>Un code Automatique demande le num&eacute;ro de compte MT5, le serveur et le mot de passe du compte.</p>"
                            "<p><a href=\"/\">&larr; R&eacute;essayer</a></p>")
    if pkg != "family":
        # 2026-10-03 (owner): Signal / Strategie = app-only - no MT5 account, no terminal
        nm = name or (raw_login if _re.search(r"[A-Za-z]", raw_login) else "")
        if not nm:
            return _join_result("&#10060; Il manque votre pr&eacute;nom", "<p>Revenez en arri&egrave;re et indiquez votre pr&eacute;nom.</p>")
        return _activate_app_only(nm, pwd, tg, pkg, days, code, raw_login)
    us = users()
    known = next((x for x in us if str(x.get("login")) == login or str(x.get("mt5_login") or "") == login), None)
    if known is not None:
        if (known.get("mt5_password") or "") != pwd:
            rate_fail(("activate", code))
            return _join_result("&#128274; Ce compte est d&eacute;j&agrave; dans le nid",
                                "<p>Le mot de passe ne correspond pas. Connectez-vous avec le bon mot de passe, puis entrez le code dans l&#8217;app : R&eacute;glages &rsaquo; Abonnement.</p>")
        # a renewal from the public page: same as the in-app "J'ai un code"
        redeem_activation_code(code, known["id"])
        ent_grant(known["id"], pkg, days, "code")
        if pkg == "family":
            _us = json.load(open(USERS_FILE, encoding="utf-8"))
            for x in _us:
                if x.get("id") == known["id"]:
                    x["trade"] = True
                    x["mode"] = x.get("mode") or "auto"
                    if not x.get("dedicated"):
                        x["dedicated"] = f"structure_bos_bot.py {x['id']}"
                        x["managed"] = True
            json.dump(_us, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            try:
                _pf = os.path.join(DIR, pause_file(known["id"]))
                if json.load(open(_pf, encoding="utf-8")).get("by") == "expiry":
                    json.dump({"paused": False, "by": "renewal", "t": time.time()}, open(_pf, "w"))
            except Exception:
                pass
        _users_cache["t"] = 0.0
        link = f"https://owltrader.duckdns.org/{known['token']}/"
        return _join_result("&#9989; " + labels.get(pkg, pkg) + " renouvel&eacute;",
                            f"<p>{days} jours de plus sur le compte de {known.get('name') or name}.</p>"
                            f"<p><a href=\"{link}\">Ouvrir mon OwlNest</a></p>")
    if not name:
        return _join_result("&#10060; Il manque votre pr&eacute;nom", "<p>Revenez en arri&egrave;re et indiquez votre pr&eacute;nom.</p>")
    if pkg == "family" and family_count() >= FAMILY_CAP:
        return _join_result("&#9203; Le nid est plein",
                            "<p>Toutes les places Automatique sont prises pour l&#8217;instant. Le Owl vous pr&eacute;viendra quand une place se lib&egrave;re.</p>")
    base = _re.sub(r"[^a-z0-9]", "", name.lower()) or "membre"
    try:
        allu = json.load(open(USERS_FILE, encoding="utf-8"))
    except Exception:
        allu = []
    uid, n = base, 1
    while any(u.get("id") == uid for u in allu):
        n += 1
        uid = f"{base}{n}"
    token = uid + secrets.token_hex(2)
    rec = {"id": uid, "name": name, "token": token, "terminal": "",
           "login": int(login), "mt5_login": int(login), "mt5_password": pwd, "mt5_server": server,
           "era_start": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "symbol": "BTCUSD", "bot_only": True, "plan": "family" if pkg == "family" else pkg,
           "mode": "auto", "telegram": tg, "created": int(time.time()), "via": "code"}
    if pkg == "family":
        rec.update({"trade": True, "dedicated": f"structure_bos_bot.py {uid}", "managed": True})
    allu.append(rec)
    json.dump(allu, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    _users_cache["t"] = 0.0
    redeem_activation_code(code, uid)
    ent_grant(uid, pkg, days, "code")
    try:
        _qf = os.path.join(DIR, "owl_push_queue.json")
        try:
            _q = json.load(open(_qf, encoding="utf-8"))
        except Exception:
            _q = []
        _q.append({"uid": "kino", "t": int(time.time()), "title": "\U0001f423 Nouveau membre \u00b7 " + name,
                   "body": f"{labels.get(pkg, pkg).replace('&eacute;', 'e')} {days} j \u00b7 compte {login} \u00b7 {server}" + (f" \u00b7 {tg}" if tg else "")})
        json.dump(_q, open(_qf, "w", encoding="utf-8"))
    except Exception:
        pass
    link = f"https://owltrader.duckdns.org/{token}/"
    what = ("<p>Le robot tourne sur votre compte dans quelques minutes, avec ses r&egrave;gles et ses freins.</p>" if pkg == "family"
            else "<p>Vos signaux arrivent sur votre t&eacute;l&eacute;phone d&egrave;s que vous activez les notifications dans l&#8217;app.</p>" if pkg == "manual"
            else "<p>Le graphique complet et la m&eacute;thode vous attendent dans l&#8217;app.</p>")
    return _join_result("&#127881; Bienvenue dans le nid, " + name + " !",
                        f"<p><b>{labels.get(pkg, pkg)}</b> &middot; {days} jours. Votre OwlNest se pr&eacute;pare (2-3 minutes).</p>" + what +
                        f"<p>Votre lien personnel :</p><p><a href=\"{link}\">{link}</a></p>"
                        "<p style=\"color:#9aa7b4;font-size:.85rem\">Gardez-le pr&eacute;cieusement, ajoutez-le &agrave; votre &eacute;cran d&#8217;accueil "
                        "ou installez l&#8217;application Android depuis la page d&#8217;accueil.</p>")


def _new_app_only_record(name, pwd, tg, pkg, allu, ident=""):
    """2026-10-04 (owner): the identifiant is what was typed at the login
    (letters or digits), when given and free; else it comes from the
    name. Returns None when the typed identifiant is already taken."""
    import re as _re
    want = _re.sub(r"[^a-z0-9]", "", (ident or "").lower())[:24]
    if want:
        if any(u.get("id") == want or str(u.get("login") or "") == want or str(u.get("mt5_login") or "") == want for u in allu):
            return None
        uid = want
    else:
        base = _re.sub(r"[^a-z0-9]", "", name.lower()) or "membre"
        uid, n = base, 1
        while any(u.get("id") == uid for u in allu):
            n += 1
            uid = f"{base}{n}"
    token = uid + secrets.token_hex(2)
    rec = {"id": uid, "name": name, "token": token, "app_only": True, "app_pwd": _app_hash(pwd),
           "plan": pkg, "telegram": tg, "created": int(time.time()),
           "era_start": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if uid.isdigit():
        rec["login"] = int(uid)          # found by number at the login, like a family account
    return rec


def _tg_link_html(uid):
    """A 'Relier Telegram' button for the welcome pages (one-week code)."""
    try:
        import random as _rl
        code = "".join(_rl.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
        lp = os.path.join(DIR, "owl_tg_links.json")
        try:
            links = json.load(open(lp, encoding="utf-8"))
        except Exception:
            links = {}
        links[code] = {"uid": uid, "t": int(time.time())}
        json.dump(links, open(lp, "w", encoding="utf-8"), indent=1)
        bot = nest_config().get("tg_bot") or "Kino_owl_bot"
        return (f"<p style=\"margin-top:14px\"><a href=\"https://t.me/{bot}?start={code}\" style=\"display:inline-block;background:#141c28;border:1px solid #1f2c3d;border-radius:12px;padding:10px 14px;color:#c6d3df;text-decoration:none;font-weight:700\">"
                "&#128279; Relier Telegram</a><br><span style=\"color:#9aa7b4;font-size:.82rem\">Pour retrouver votre acc&egrave;s un jour, sans e-mail : le robot OwlNest vous renverra votre lien.</span></p>")
    except Exception:
        return ""


def _activate_app_only(name, pwd, tg, pkg, days, code, ident=""):
    """A Signal / Strategie account from a code: identifiant + password,
    the package for `days`, the public demo's view under their name."""
    try:
        allu = json.load(open(USERS_FILE, encoding="utf-8"))
    except Exception:
        allu = []
    rec = _new_app_only_record(name, pwd, tg, pkg, allu, ident)
    if rec is None:
        return _join_result("&#128274; Cet identifiant est d&eacute;j&agrave; pris",
                            "<p>Si c&#8217;est le v&ocirc;tre, connectez-vous avec son mot de passe ; sinon choisissez-en un autre.</p><p><a href=\"/\">&larr; Retour</a></p>")
    rec["via"] = "code"
    allu.append(rec)
    json.dump(allu, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    _users_cache["t"] = 0.0
    redeem_activation_code(code, rec["id"])
    ent_grant(rec["id"], pkg, days, "code")
    labels = {"manual": "Signal", "strategy": "Strat&eacute;gie"}
    try:
        _qf = os.path.join(DIR, "owl_push_queue.json")
        try:
            _q = json.load(open(_qf, encoding="utf-8"))
        except Exception:
            _q = []
        _q.append({"uid": "kino", "t": int(time.time()), "title": "\U0001f423 Nouveau membre \u00b7 " + name,
                   "body": f"{labels.get(pkg, pkg).replace('&eacute;', 'e')} {days} j \u00b7 identifiant {rec['id']}" + (f" \u00b7 {tg}" if tg else "")})
        json.dump(_q, open(_qf, "w", encoding="utf-8"))
    except Exception:
        pass
    link = f"https://owltrader.duckdns.org/{rec['token']}/"
    return _join_result("&#127881; Bienvenue dans le nid, " + name + " !",
                        f"<p><b>{labels.get(pkg, pkg)}</b> &middot; {days} jours. Votre page est pr&ecirc;te.</p>"
                        f"<p>Votre identifiant : <b>{rec['id']}</b> &mdash; celui que vous avez tap&eacute; &agrave; la connexion, avec le m&ecirc;me mot de passe. Ils vous reconnectent depuis n&#8217;importe quel t&eacute;l&eacute;phone.</p>"
                        + ("<p>Activez les notifications dans l&#8217;app : les signaux du robot arrivent sur votre t&eacute;l&eacute;phone.</p>" if pkg == "manual"
                           else "<p>Le graphique complet et la m&eacute;thode vous attendent dans l&#8217;app.</p>")
                        + f"<p>Votre lien personnel :</p><p><a href=\"{link}\">{link}</a></p>"
                        "<p style=\"color:#9aa7b4;font-size:.85rem\">Ajoutez-le &agrave; votre &eacute;cran d&#8217;accueil ou installez l&#8217;application Android depuis la page d&#8217;accueil.</p>"
                        + _tg_link_html(rec["id"]))


def _activate_buy(name, pwd, tg, pkg, origin, ident=""):
    """Signal / Strategie bought in crypto from the public page: the
    account is created 'waiting for the payment' (no terminal yet), the
    NOWPayments page opens; the webhook activates it (and the provisioner
    then builds the terminal). Unpaid 48 h -> removed by the manager."""
    import re as _re
    import urllib.request as _urq
    cfg = nest_config()
    if not cfg.get("np_api_key"):
        return _join_result("&#9888;&#65039; Paiement en crypto indisponible",
                            "<p>Demandez un code au Owl sur Telegram.</p><p><a href=\"/activate\">&larr; Retour</a></p>")
    try:
        allu = json.load(open(USERS_FILE, encoding="utf-8"))
    except Exception:
        allu = []
    rec = _new_app_only_record(name, pwd, tg, pkg, allu, ident)
    if rec is None:
        return _join_result("&#128274; Cet identifiant est d&eacute;j&agrave; pris",
                            "<p>Si c&#8217;est le v&ocirc;tre, connectez-vous avec son mot de passe ; sinon choisissez-en un autre.</p><p><a href=\"/\">&larr; Retour</a></p>")
    rec.update({"via": "crypto", "pending_pay": True})
    uid, token = rec["id"], rec["token"]
    allu.append(rec)
    json.dump(allu, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    _users_cache["t"] = 0.0
    api = "https://api-sandbox.nowpayments.io" if cfg.get("np_sandbox") else "https://api.nowpayments.io"
    body = json.dumps({
        "price_amount": PACKAGES[pkg]["usd"], "price_currency": "usd",
        "order_id": f"{uid}|{pkg}|{int(time.time())}",
        "order_description": f"OwlNest {PACKAGES[pkg]['label']} - {PACKAGES[pkg]['days']} jours",
        "ipn_callback_url": f"{origin}/np_ipn",
        "success_url": f"{origin}/{token}/#set", "cancel_url": f"{origin}/{token}/#set"}).encode()
    try:
        req = _urq.Request(api + "/v1/invoice", data=body, method="POST",
                           headers={"x-api-key": cfg["np_api_key"], "Content-Type": "application/json"})
        with _urq.urlopen(req, timeout=20) as r:
            inv = json.loads(r.read().decode("utf-8", "replace"))
        url = inv.get("invoice_url")
    except Exception as e:
        url = None
    link = f"https://owltrader.duckdns.org/{token}/"
    if not url:
        return _join_result("&#9888;&#65039; La page de paiement n&#8217;a pas r&eacute;pondu",
                            f"<p>Votre compte est cr&eacute;&eacute; mais pas encore actif. Ouvrez votre lien et payez depuis R&eacute;glages &rsaquo; Abonnement :</p><p><a href=\"{link}\">{link}</a></p>")
    return ("redirect", url)


def handle_join(form):
    # 2026-10-03 (owner): no trial, no secret word - accounts open with a code
    return _join_result("&#129417; Un code, pas un formulaire",
                        "<p>Un compte s&#8217;ouvre avec un code d&#8217;activation.</p>"
                        "<p><a href=\"/activate\">J&#8217;ai un code &rarr;</a></p><p><a href=\"/\">&larr; Retour</a></p>")
    import re as _re
    code = (form.get("code", [""])[0] or "").strip().lower()
    if code != FAMILY_CODE:
        return _join_result("&#10060; Code famille incorrect",
                           "<p>Demandez le mot secret au Owl.</p>")
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
                "d&#8217;invitation</b> au Owl si vous &ecirc;tes "
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

    def _send_file_fresh(self, path, ctype, disposition=None):
        """A file that changes between releases: never cached by the
        browser (the APK and its version must always be the latest)."""
        try:
            body = open(path, "rb").read()
        except Exception:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path, ctype):
        try:
            body = open(path, "rb").read()
        except Exception:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        # Owner 2026-09-19: the public showcase is view-only. Its token is
        # in everyone's hands, so EVERY action on it is refused here, on the
        # server, before any password check - a hidden button is not a
        # permission. Only notification prefs stay open: watching is the
        # point.
        if len(_parts) == 2 and _parts[1] not in ("push_pref", "push_sub"):
            _pu = user_by_token(_parts[0])
            if _pu is not None and _pu.get("public"):
                self._send(json.dumps({"ok": False,
                                       "err": "compte demo: lecture seule"}),
                           "application/json")
                return
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
        if len(_parts) == 2 and _parts[1] == "nest_panic":
            # ADMIN EMERGENCY STOP on ANY account (owner 2026-09-18).
            # Pauses the account, cancels its pending orders and closes
            # every open position. Admin only, master password, and the
            # work is done by owl_panic.py because only that script holds
            # the account's own terminal + credentials - the stats worker
            # is read-only by construction.
            u = user_by_token(_parts[0])
            if not is_admin(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _up9
                _f9 = _up9.parse_qs(self.rfile.read(ln)
                                    .decode("utf-8", "replace"))
                _pw = (_f9.get("pwd", [""])[0] or "").strip()
                _uid = (_f9.get("uid", [""])[0] or "").strip()
                _dry = (_f9.get("dry", ["0"])[0] == "1")
                if not master_pwd_ok(_pw):
                    self._send(json.dumps({"ok": False,
                                           "err": "mot de passe incorrect"}),
                               "application/json")
                    return
                us = json.load(open(USERS_FILE, encoding="utf-8"))
                if not any(x.get("id") == _uid for x in us):
                    self._send(json.dumps({"ok": False,
                                           "err": "compte inconnu"}),
                               "application/json")
                    return
                import subprocess as _sp
                # the server runs under pythonw; use the console
                # interpreter so the child's stdout is definitely captured
                _exe = sys.executable
                if _exe.lower().endswith("pythonw.exe"):
                    _c = _exe[:-len("pythonw.exe")] + "python.exe"
                    if os.path.exists(_c):
                        _exe = _c
                _cmd = [_exe, os.path.join(DIR, "owl_panic.py"), _uid]
                if not _dry:
                    _cmd.append("--armed")
                _r = _sp.run(_cmd, cwd=DIR, capture_output=True,
                             text=True, timeout=90)
                _last = [x for x in (_r.stdout or "").splitlines() if x.strip()]
                try:
                    _out = json.loads(_last[-1])
                except Exception:
                    _out = {"ok": False,
                            "err": "arret d'urgence illisible",
                            "raw": ((_r.stderr or _r.stdout or "")[-400:])}
                self._send(json.dumps(_out), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 1 and _parts[0] == "np_ipn":
            # 2026-09-27: NOWPayments IPN - HMAC-SHA512 of the JSON with keys
            # sorted, hex, in x-nowpayments-sig. A finished payment grants
            # the package named in order_id "uid|pkg|ts". Never trusts the
            # body without the signature.
            import hmac as _hmac
            import hashlib as _hashlib
            try:
                ln = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(min(ln, 200000))
                secret = (nest_config().get("np_ipn_secret") or "").encode()
                sig = self.headers.get("x-nowpayments-sig") or ""
                data = json.loads(raw.decode("utf-8", "replace"))
                try:
                    open(os.path.join(DIR, "owl_ipn_raw.log"), "a", encoding="utf-8").write(
                        time.strftime("%Y-%m-%d %H:%M:%S ") + sig[:16] + " " + raw.decode("utf-8", "replace")[:4000] + "\n")
                except Exception:
                    pass
                # 2026-10-04: NOWPayments signs the JS canonical form; Python prints
                # some numbers differently (1e-07 vs 1e-7, non-ASCII escapes), so
                # several forms are tried
                _c1 = json.dumps(data, sort_keys=True, separators=(",", ":"))
                _c2 = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                _c3 = re.sub(r"e([+-])0(\d)", r"e\1\2", _c2)
                good = bool(secret) and any(_hmac.compare_digest(_hmac.new(secret, _c.encode("utf-8"), _hashlib.sha512).hexdigest(), sig)
                                            for _c in (_c1, _c2, _c3))
                if not good and data.get("payment_id") and data.get("payment_status") in ("finished", "confirmed", "partially_paid"):
                    # the signature disagrees: ask NOWPayments itself (our API key) before trusting the body
                    try:
                        import urllib.request as _uri
                        _cfgk = nest_config().get("np_api_key") or ""
                        _api = "https://api-sandbox.nowpayments.io" if nest_config().get("np_sandbox") else "https://api.nowpayments.io"
                        _pr = json.loads(_uri.urlopen(_uri.Request(f"{_api}/v1/payment/{data.get('payment_id')}", headers={"x-api-key": _cfgk}), timeout=20).read().decode("utf-8", "replace"))
                        good = (_pr.get("payment_status") == data.get("payment_status") and str(_pr.get("order_id")) == str(data.get("order_id"))
                                and abs(float(_pr.get("price_amount") or 0) - float(data.get("price_amount") or 0)) < 0.01)
                        if good:
                            data["price_amount"] = _pr.get("price_amount")
                    except Exception:
                        good = False
                rec = {"t": int(time.time()), "sig_ok": bool(good),
                       "status": data.get("payment_status"), "order": data.get("order_id"),
                       "amount": data.get("price_amount"), "pay_amount": data.get("pay_amount"),
                       "currency": data.get("pay_currency"), "id": data.get("payment_id")}
                if good and data.get("payment_status") in ("finished", "confirmed"):
                    try:
                        _uid, _pkg, _ts = str(data.get("order_id")).split("|")[:3]
                        if _pkg == "setup":
                            # 2026-10-03 (owner): the opening fee, paid in crypto
                            SHARE.mark_setup(_uid, f"nowpayments:{data.get('payment_id')}", float(data.get("price_amount") or 0))
                            rec["granted"] = "setup"
                            _pkg = "_setup_done"
                        if _pkg == "share":
                            # 2026-10-03 (owner): a share statement paid in crypto
                            _per = SHARE.mark_paid(_uid, _ts, f"nowpayments:{data.get('payment_id')}", float(data.get("price_amount") or 0))
                            rec["granted"] = "share"
                            if _per:
                                _en = member_lang(_uid) == "en"
                                try:
                                    _qf = os.path.join(DIR, "owl_push_queue.json")
                                    try:
                                        _q = json.load(open(_qf, encoding="utf-8"))
                                    except Exception:
                                        _q = []
                                    _q.append({"uid": _uid, "t": int(time.time()),
                                               "title": "\u2705 " + ("Statement settled" if _en else "Relev\u00e9 r\u00e9gl\u00e9"),
                                               "body": (f"Thank you - {_ts} is settled (${_per['due']:.2f}). The robot goes on." if _en
                                                        else f"Merci \u2014 {_ts} est r\u00e9gl\u00e9 ({_per['due']:.2f} $). Le robot continue.")})
                                    _q.append({"uid": "kino", "t": int(time.time()), "title": "\U0001f4b5 Part r\u00e9gl\u00e9e en crypto",
                                               "body": f"{_uid} \u00b7 {_ts} \u00b7 ${_per['due']:.2f}"})
                                    json.dump(_q, open(_qf, "w", encoding="utf-8"))
                                except Exception:
                                    pass
                        if _pkg in PACKAGES:
                            paid = float(data.get("price_amount") or 0)
                            if paid + 0.01 >= PACKAGES[_pkg]["usd"] * 0.97:
                                _r = ent_grant(_uid, _pkg, PACKAGES[_pkg]["days"],
                                               f"nowpayments:{data.get('payment_id')}")
                                rec["granted"] = _pkg
                                # 2026-10-03 (owner): an account opened from the public
                                # page waits for this; now the provisioner may build it
                                try:
                                    _usp = json.load(open(USERS_FILE, encoding="utf-8"))
                                    for _x in _usp:
                                        if _x.get("id") == _uid and _x.get("pending_pay"):
                                            _x.pop("pending_pay", None)
                                            _x["paid_at"] = int(time.time())
                                    json.dump(_usp, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                                    _users_cache["t"] = 0.0
                                except Exception:
                                    pass
                                _end = time.strftime("%d/%m", time.gmtime(float(_r.get(_pkg + "_until") or time.time())))
                                _en = member_lang(_uid) == "en"
                                try:
                                    _qf = os.path.join(DIR, "owl_push_queue.json")
                                    try:
                                        _q = json.load(open(_qf, encoding="utf-8"))
                                    except Exception:
                                        _q = []
                                    _q.append({"uid": _uid, "t": int(time.time()),
                                               "title": ("\u2705 Subscription activated" if _en else "\u2705 Abonnement activ\u00e9"),
                                               "body": ((f"{PACKAGES[_pkg]['label']} \u00b7 {PACKAGES[_pkg]['days']} days \u00b7 until {_end} \u00b7 ${paid:.0f}. "
                                                         "Receipt in Settings \u203a My payments.") if _en else
                                                        (f"{PACKAGES[_pkg]['label']} \u00b7 {PACKAGES[_pkg]['days']} jours \u00b7 jusqu\u2019au {_end} \u00b7 ${paid:.0f}. "
                                                         "Re\u00e7u dans R\u00e9glages \u203a Mes paiements."))})
                                    json.dump(_q, open(_qf, "w", encoding="utf-8"), ensure_ascii=False)
                                except Exception:
                                    pass
                            else:
                                rec["granted"] = "short"
                    except Exception as e:
                        rec["err"] = str(e)
                try:
                    pays = json.load(open(PAY_FILE, encoding="utf-8"))
                    if not isinstance(pays, list):
                        pays = []
                except Exception:
                    pays = []
                pays.append(rec)
                json.dump(pays[-500:], open(PAY_FILE, "w", encoding="utf-8"), indent=1)
                self._send("ok" if good else "bad signature", "text/plain")
            except Exception as e:
                self._send("error " + str(e), "text/plain")
            return
        if len(_parts) == 2 and _parts[1] == "sigmark":
            # 2026-09-28: "J'ai pris / Pas pris" + result, for members who
            # trade the signals on another broker
            u = user_by_token(_parts[0])
            if u is None or not (is_admin(u) or has(u["id"], "manual")):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upm
                _fm = _upm.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                _t = int(float(_fm.get("t", ["0"])[0] or 0))
                _tk = (_fm.get("taken", [""])[0] or "").strip()
                _rs = (_fm.get("result", [""])[0] or "").strip().replace(",", ".").replace("$", "").replace("+", "").replace(" ", "")
                if not _t:
                    self._send(json.dumps({"ok": False, "err": "bad t"}), "application/json")
                    return
                m = sig_marks(u["id"])
                r = m.get(str(_t)) or {}
                if _tk == "1":
                    r["taken"] = True
                elif _tk == "0":
                    r["taken"] = False
                if _rs != "":
                    try:
                        r["result"] = round(max(-100000.0, min(100000.0, float(_rs))), 2)
                    except Exception:
                        pass
                r["mt"] = int(time.time())
                m[str(_t)] = r
                m = dict(list(m.items())[-300:])
                _f = SIGMARK_FILE(u["id"])
                json.dump(m, open(_f + ".tmp", "w", encoding="utf-8"))
                os.replace(_f + ".tmp", _f)
                self._send(json.dumps({"ok": True, "mark": r}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:100]}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "waitlist":
            # 2026-09-28: "Me prevenir" when the manual seats are full; the
            # notifier tells the waiting members when one frees up
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upw
                _fw = _upw.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                on = (_fw.get("on", ["1"])[0] == "1")
                w = waitlist()
                if on:
                    w[u["id"]] = {"t": int(time.time()), "name": u.get("name", u["id"])}
                else:
                    w.pop(u["id"], None)
                json.dump(w, open(WAIT_FILE + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                os.replace(WAIT_FILE + ".tmp", WAIT_FILE)
                self._send(json.dumps({"ok": True, "waitlisted": on, "pos": len(w)}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:100]}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "buy":
            # 2026-09-27: create a NOWPayments invoice for a package
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upb
                import urllib.request as _urq
                _fb = _upb.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                pkg = (_fb.get("pkg", [""])[0] or "").strip()
                cfg = nest_config()
                if pkg not in PACKAGES:
                    self._send(json.dumps({"ok": False, "err": "bad pkg"}), "application/json")
                    return
                if not cfg.get("np_api_key"):
                    self._send(json.dumps({"ok": False, "err": "not ready"}), "application/json")
                    return
                if pkg == "manual" and not has(u["id"], "manual") and manual_seats() >= MANUAL_CAP:
                    self._send(json.dumps({"ok": False, "err": "complet"}), "application/json")
                    return
                host = self.headers.get("Host") or "owlnest.local"
                proto = "https" if ("127.0.0.1" not in host and "localhost" not in host) else "http"
                origin = f"{proto}://{host}"
                api = "https://api-sandbox.nowpayments.io" if cfg.get("np_sandbox") else "https://api.nowpayments.io"
                body = json.dumps({
                    "price_amount": PACKAGES[pkg]["usd"], "price_currency": "usd",
                    "order_id": f"{u['id']}|{pkg}|{int(time.time())}",
                    "order_description": f"OwlNest {PACKAGES[pkg]['label']} - {PACKAGES[pkg]['days']} jours",
                    "ipn_callback_url": f"{origin}/np_ipn",
                    "success_url": f"{origin}/{u['token']}/#set",
                    "cancel_url": f"{origin}/{u['token']}/#set"}).encode()
                req = _urq.Request(api + "/v1/invoice", data=body, method="POST",
                                   headers={"x-api-key": cfg["np_api_key"],
                                            "Content-Type": "application/json"})
                with _urq.urlopen(req, timeout=20) as r:
                    inv = json.loads(r.read().decode("utf-8", "replace"))
                url = inv.get("invoice_url")
                if not url:
                    self._send(json.dumps({"ok": False, "err": "no invoice"}), "application/json")
                    return
                self._send(json.dumps({"ok": True, "url": url}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:120]}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "tg_link":
            # 2026-10-04 (owner): a one-week code that the Telegram bot turns into a link
            u = user_by_token(_parts[0])
            if u is None or u.get("public"):
                self.send_response(404)
                self.end_headers()
                return
            try:
                import random as _rl
                code = "".join(_rl.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
                lp = os.path.join(DIR, "owl_tg_links.json")
                try:
                    links = json.load(open(lp, encoding="utf-8"))
                except Exception:
                    links = {}
                now = time.time()
                links = {k: v for k, v in links.items() if now - float((v or {}).get("t") or 0) < 7 * 86400}
                links[code] = {"uid": u["id"], "t": int(now)}
                json.dump(links, open(lp, "w", encoding="utf-8"), indent=1)
                bot = nest_config().get("tg_bot") or "Kino_owl_bot"
                self._send(json.dumps({"ok": True, "url": f"https://t.me/{bot}?start={code}", "linked": bool(u.get("telegram_chat"))}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:100]}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "app_pwd":
            # 2026-10-04 (owner): a member changes the app password (current one required)
            u = user_by_token(_parts[0])
            if u is None or u.get("public") or not (u.get("app_only") or u.get("app_login") or u.get("app_pwd")):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upw
                _fw = _upw.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                old_, new_ = (_fw.get("old", [""])[0] or ""), (_fw.get("new", [""])[0] or "").strip()[:64]
                if rate_limited(("pwd", u["id"]), limit=6):
                    self._send(json.dumps({"ok": False, "err": "wait"}), "application/json")
                    return
                if u.get("app_pwd") != _app_hash(old_):
                    rate_fail(("pwd", u["id"]))
                    self._send(json.dumps({"ok": False, "err": "bad password"}), "application/json")
                    return
                if len(new_) < 6:
                    self._send(json.dumps({"ok": False, "err": "short"}), "application/json")
                    return
                allu = json.load(open(USERS_FILE, encoding="utf-8"))
                for x in allu:
                    if x.get("id") == u["id"]:
                        x["app_pwd"] = _app_hash(new_)
                        x["app_login"] = True
                json.dump(allu, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                _users_cache["t"] = 0.0
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:100]}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "pay_share":
            # 2026-10-03 (owner): a NOWPayments invoice for one share statement
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _ups
                import urllib.request as _urs
                _fs = _ups.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                ym = (_fs.get("ym", [""])[0] or "").strip()[:7]
                cfg = nest_config()
                per = next((p for p in ((SHARE.load()["accounts"].get(u["id"]) or {}).get("periods") or []) if p.get("ym") == ym), None)
                if not per or per.get("status") not in ("open", "overdue") or float(per.get("due") or 0) <= 0:
                    self._send(json.dumps({"ok": False, "err": "no statement"}), "application/json")
                    return
                if not cfg.get("np_api_key"):
                    self._send(json.dumps({"ok": False, "err": "not ready"}), "application/json")
                    return
                host = self.headers.get("Host") or "owlnest.local"
                proto = "https" if ("127.0.0.1" not in host and "localhost" not in host) else "http"
                origin = f"{proto}://{host}"
                api = "https://api-sandbox.nowpayments.io" if cfg.get("np_sandbox") else "https://api.nowpayments.io"
                body = json.dumps({
                    "price_amount": round(float(per["due"]), 2), "price_currency": "usd",
                    "order_id": f"{u['id']}|share|{ym}",
                    "order_description": f"OwlNest - part {ym}",
                    "ipn_callback_url": f"{origin}/np_ipn",
                    "success_url": f"{origin}/{u['token']}/#set",
                    "cancel_url": f"{origin}/{u['token']}/#set"}).encode()
                req = _urs.Request(api + "/v1/invoice", data=body, method="POST",
                                   headers={"x-api-key": cfg["np_api_key"], "Content-Type": "application/json"})
                with _urs.urlopen(req, timeout=20) as r:
                    inv = json.loads(r.read().decode("utf-8", "replace"))
                url = inv.get("invoice_url")
                self._send(json.dumps({"ok": bool(url), "url": url, "err": None if url else "no invoice"}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:120]}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "share_paid":
            # 2026-10-03 (owner): "Marquer paye" in Le Nid (master pwd)
            u = user_by_token(_parts[0])
            if not is_admin(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upp
                _fp = _upp.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                if not master_pwd_ok((_fp.get("pwd", [""])[0] or "").strip()):
                    self._send(json.dumps({"ok": False, "err": "bad password"}), "application/json")
                    return
                _uid = (_fp.get("uid", [""])[0] or "").strip()[:40]
                _ym = (_fp.get("ym", [""])[0] or "").strip()[:7]
                if _ym == "setup":
                    # the opening fee, settled with the Owl
                    SHARE.mark_setup(_uid, "kino")
                    self._send(json.dumps({"ok": True}), "application/json")
                    return
                per = SHARE.mark_paid(_uid, _ym, "kino")
                if per:
                    _en = member_lang(_uid) == "en"
                    _qf = os.path.join(DIR, "owl_push_queue.json")
                    try:
                        _q = json.load(open(_qf, encoding="utf-8"))
                    except Exception:
                        _q = []
                    _q.append({"uid": _uid, "t": int(time.time()),
                               "title": "\u2705 " + ("Statement settled" if _en else "Relev\u00e9 r\u00e9gl\u00e9"),
                               "body": (f"Thank you - {_ym} is settled (${per['due']:.2f}). The robot goes on." if _en
                                        else f"Merci \u2014 {_ym} est r\u00e9gl\u00e9 ({per['due']:.2f} $). Le robot continue.")})
                    json.dump(_q, open(_qf, "w", encoding="utf-8"))
                self._send(json.dumps({"ok": bool(per), "err": None if per else "no statement"}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:100]}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "nest_config":
            # 2026-09-27: owner settings shared by every member page (contact link)
            u = user_by_token(_parts[0])
            if not is_admin(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upc
                _fc = _upc.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                if not master_pwd_ok((_fc.get("pwd", [""])[0] or "").strip()):
                    self._send(json.dumps({"ok": False, "err": "bad password"}), "application/json")
                    return
                cfg = nest_config()
                _url = (_fc.get("contact_url", [cfg.get("contact_url", "")])[0] or "").strip()[:300]
                if _url and not (_url.startswith("https://") or _url.startswith("http://") or _url.startswith("mailto:") or _url.startswith("tel:")):
                    self._send(json.dumps({"ok": False, "err": "bad url"}), "application/json")
                    return
                cfg["contact_url"] = _url
                cfg["contact_label"] = (_fc.get("contact_label", [""])[0] or "").strip()[:60]
                try:
                    with open(os.path.join(DIR, "owl_admin_actions.log"), "a", encoding="utf-8") as _al:
                        _al.write(time.strftime("%Y-%m-%dT%H:%M:%S") + f" nest_config by {u.get('id')}: keys="
                                  + ",".join(k for k in ("np_api_key", "np_ipn_secret", "mql5_url", "contact_url") if _fc.get(k, [""])[0]) + "\n")
                except Exception:
                    pass
                # 2026-09-27: payments + MQL5 (only the keys that were sent)
                for k in ("np_api_key", "np_ipn_secret", "mql5_url"):
                    if k in _fc:
                        cfg[k] = (_fc.get(k, [""])[0] or "").strip()[:200]
                if "family_usd" in _fc:
                    try:
                        cfg["family_usd"] = float(_fc.get("family_usd", ["0"])[0] or 0)
                    except Exception:
                        pass
                if "np_sandbox" in _fc:
                    cfg["np_sandbox"] = _fc.get("np_sandbox", ["0"])[0] == "1"
                json.dump(cfg, open(CONFIG_FILE + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
                os.replace(CONFIG_FILE + ".tmp", CONFIG_FILE)
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "nest_note":
            # 2026-09-27: a private note per account, for the owner (master pwd)
            u = user_by_token(_parts[0])
            if not is_admin(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upn
                _fn = _upn.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                _pw = (_fn.get("pwd", [""])[0] or "").strip()
                _uid = (_fn.get("uid", [""])[0] or "").strip()
                _txt = (_fn.get("text", [""])[0] or "").strip()[:300]
                if not master_pwd_ok(_pw):
                    self._send(json.dumps({"ok": False, "err": "bad password"}), "application/json")
                    return
                try:
                    notes = json.load(open(NOTES_FILE, encoding="utf-8"))
                    if not isinstance(notes, dict):
                        notes = {}
                except Exception:
                    notes = {}
                if _txt:
                    notes[_uid] = {"text": _txt, "t": int(time.time())}
                else:
                    notes.pop(_uid, None)
                _tmpn = NOTES_FILE + ".tmp"
                json.dump(notes, open(_tmpn, "w", encoding="utf-8"), ensure_ascii=False)
                os.replace(_tmpn, NOTES_FILE)
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "nest_reset":
            # 2026-09-27: restart an account's robot from zero (master pwd);
            # owl_mode_switch.py does the stop / archive / era / start
            u = user_by_token(_parts[0])
            if not is_admin(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upr
                _fr = _upr.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                _pw = (_fr.get("pwd", [""])[0] or "").strip()
                _uid = (_fr.get("uid", [""])[0] or "").strip()
                if not master_pwd_ok(_pw):
                    self._send(json.dumps({"ok": False, "err": "bad password"}),
                               "application/json")
                    return
                us = json.load(open(USERS_FILE, encoding="utf-8"))
                if not any(x.get("id") == _uid for x in us):
                    self._send(json.dumps({"ok": False, "err": "no such user"}),
                               "application/json")
                    return
                _tmp = os.path.join(DIR, "owl_reset_request.json.tmp")
                json.dump({"uid": _uid, "t": time.time(), "by": u.get("id")},
                          open(_tmp, "w"))
                os.replace(_tmp, os.path.join(DIR, "owl_reset_request.json"))
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "lab_ask":
            # 2026-09-29: "Demander au chercheur" on a seed - Kino and Strategie members
            u = user_by_token(_parts[0])
            if u is None or u.get("public"):
                self.send_response(404)
                self.end_headers()
                return
            try:
                if not (is_admin(u) or has(u.get("id"), "strategy") or admin_cookie_ok(self.headers)):
                    self._send(json.dumps({"ok": False, "err": "strategy"}), "application/json")
                    return
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _up8
                _f8 = _up8.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                _seed = (_f8.get("seed", [""])[0] or "").strip()[:30]
                _note = (_f8.get("note", [""])[0] or "").strip()[:200]
                _cands = {c["id"]: c for c in lab_payload().get("candidates", [])}
                if _seed not in _cands:
                    self._send(json.dumps({"ok": False, "err": "no such seed"}), "application/json")
                    return
                _ap = os.path.join(DIR, "lab", "asks.json")
                try:
                    _asks = json.load(open(_ap, encoding="utf-8"))
                except Exception:
                    _asks = {"asks": []}
                if any(a.get("seed") == _seed and a.get("status") == "open" for a in _asks.get("asks", [])):
                    self._send(json.dumps({"ok": True, "msg": "already"}), "application/json")
                    return
                _asks.setdefault("asks", []).append({"id": f"ask_{int(time.time())}", "seed": _seed,
                                                     "seed_fr": _cands[_seed].get("name_fr"), "seed_en": _cands[_seed].get("name_en"),
                                                     "by": u.get("id"), "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                                     "note": _note, "status": "open"})
                _tmp = _ap + ".tmp"
                json.dump(_asks, open(_tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                os.replace(_tmp, _ap)
                _LAB_CACHE.update(t=0.0, data=None)
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:100]}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "lab_decide":
            # 2026-09-29: the owner's Approuver / Rejeter / Lancer un jumeau on an idea
            u = user_by_token(_parts[0])
            if not (is_admin(u) or admin_cookie_ok(self.headers)):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _up9
                _f9 = _up9.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                _pw = (_f9.get("pwd", [""])[0] or "").strip()
                _id = (_f9.get("id", [""])[0] or "").strip()[:40]
                _d = (_f9.get("d", [""])[0] or "").strip()
                _note = (_f9.get("note", [""])[0] or "").strip()
                if not master_pwd_ok(_pw):
                    self._send(json.dumps({"ok": False, "err": "bad password"}), "application/json")
                    return
                if _d not in ("yes", "no", "twin") or not _id:
                    self._send(json.dumps({"ok": False, "err": "bad request"}), "application/json")
                    return
                ok, msg = lab_decide(_id, _d, _note)
                self._send(json.dumps({"ok": ok, "msg": msg}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:100]}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "lab_pause":
            # 2026-10-03 (owner): the hand brake on the lab's robot. The
            # judge owns the file and the revert, so this only asks it.
            u = user_by_token(_parts[0])
            if not (is_admin(u) or admin_cookie_ok(self.headers)):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upb
                _fb = _upb.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                _pw = (_fb.get("pwd", [""])[0] or "").strip()
                _on = (_fb.get("on", ["1"])[0] == "1")
                if not master_pwd_ok(_pw):
                    self._send(json.dumps({"ok": False, "err": "bad password"}), "application/json")
                    return
                import subprocess as _spb
                _r = _spb.run([sys.executable, os.path.join(DIR, "lab", "twin_judge.py"), "--pause" if _on else "--resume"],
                              cwd=DIR, capture_output=True, text=True, timeout=120)
                _LAB_CACHE.update(t=0.0)
                self._send(json.dumps({"ok": _r.returncode == 0, "msg": (_r.stdout or _r.stderr or "").strip()[-160:]}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:100]}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "nest_reset_pwd":
            # 2026-10-04 (owner): a temporary app password for a member (master pwd)
            u = user_by_token(_parts[0])
            if not is_admin(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upr
                _fr = _upr.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                if not master_pwd_ok((_fr.get("pwd", [""])[0] or "").strip()):
                    self._send(json.dumps({"ok": False, "err": "bad password"}), "application/json")
                    return
                _uid = (_fr.get("uid", [""])[0] or "").strip()[:40]
                import random as _rnd
                temp = "".join(_rnd.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(8))
                allu = json.load(open(USERS_FILE, encoding="utf-8"))
                hit = False
                for x in allu:
                    if x.get("id") == _uid and (x.get("app_only") or x.get("app_login") or x.get("app_pwd")):
                        x["app_pwd"] = _app_hash(temp)
                        x["app_login"] = True
                        hit = True
                if hit:
                    json.dump(allu, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                    _users_cache["t"] = 0.0
                self._send(json.dumps({"ok": hit, "temp": temp if hit else None, "err": None if hit else "pas un compte app"}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:100]}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] in ("nest_activate", "nest_pending_del"):
            # 2026-10-04 (owner): the admin activates a pending request (no code
            # needed) or drops it (master pwd)
            u = user_by_token(_parts[0])
            if not is_admin(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upn
                _fn = _upn.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                if not master_pwd_ok((_fn.get("pwd", [""])[0] or "").strip()):
                    self._send(json.dumps({"ok": False, "err": "bad password"}), "application/json")
                    return
                _uid = (_fn.get("uid", [""])[0] or "").strip()[:40]
                if _parts[1] == "nest_pending_del":
                    allu = json.load(open(USERS_FILE, encoding="utf-8"))
                    keep = [x for x in allu if not (x.get("id") == _uid and x.get("pending_code") and not x.get("trade") and not x.get("terminal"))]
                    json.dump(keep, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                    _users_cache["t"] = 0.0
                    self._send(json.dumps({"ok": len(keep) < len(allu)}), "application/json")
                    return
                try:
                    _days = max(1, min(366, int(_fn.get("days", ["30"])[0] or 30)))
                except Exception:
                    _days = 30
                ok, why = grant_pending(_uid, _days)
                self._send(json.dumps({"ok": ok, "msg": why}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)[:100]}), "application/json")
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
                _ppf = pause_file(_uid)
                json.dump({"paused": _on, "by": "master",
                           "t": time.time()},
                          open(os.path.join(DIR, _ppf), "w"))
                # 2026-09-28: same swap as the member's own switch - an
                # account that can run a desk gets it started / stopped
                try:
                    _tu = next((x for x in us if x.get("id") == _uid), None)
                    if _tu is not None and can_switch(_tu):
                        _mtmp = os.path.join(DIR, "owl_mode_switch_request.json.tmp")
                        json.dump({"uid": _uid, "want": "semi" if _on else "auto",
                                   "t": time.time()}, open(_mtmp, "w"))
                        os.replace(_mtmp, os.path.join(DIR, "owl_mode_switch_request.json"))
                except Exception:
                    pass
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
                qs = _up2.parse_qs(
                    self.rfile.read(ln).decode("utf-8", "replace"))
                try:
                    prefs = json.load(open(PUSH_PREFS_FILE))
                except Exception:
                    prefs = {}
                if "level" in qs:
                    lvl = qs.get("level", ["all"])[0]
                    if lvl not in ("all", "important"):
                        lvl = "all"
                    prefs[u["id"]] = lvl
                if "lang" in qs:
                    # 2026-09-27: the pushes follow the phone's language
                    _lg = qs.get("lang", ["fr"])[0]
                    prefs.setdefault("_lang", {})[u["id"]] = (
                        "en" if _lg == "en" else "fr")
                if "quiet" in qs:
                    # 2026-09-26: silence 22h-7h in the phone's timezone
                    try:
                        _tz = int(qs.get("tz", ["0"])[0])
                    except Exception:
                        _tz = 0
                    prefs.setdefault("_quiet", {})[u["id"]] = {
                        "on": qs["quiet"][0] == "1", "tz": _tz}
                json.dump(prefs, open(PUSH_PREFS_FILE, "w"))
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "share":
            # 2026-09-27: Web Share Target - a note or an image lands in the
            # member's Messages (image kept in nest_data, <= 3 MB)
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(min(ln, 3_500_000))
                ctype = self.headers.get("Content-Type", "")
                from email.parser import BytesParser
                from email.policy import default as _pol
                msg = BytesParser(policy=_pol).parsebytes(
                    b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
                text, title, img = "", "", None
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    nm = part.get_param("name", header="content-disposition")
                    fn = part.get_filename()
                    pay = part.get_payload(decode=True) or b""
                    if fn and nm == "media" and pay[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb"):
                        img = (pay, ".png" if pay[:4] == b"\x89PNG" else ".jpg")
                    elif nm == "text":
                        text = pay.decode("utf-8", "replace").strip()[:500]
                    elif nm == "title":
                        title = pay.decode("utf-8", "replace").strip()[:120]
                if img and len(img[0]) <= 3_000_000:
                    os.makedirs(NEST_DATA, exist_ok=True)
                    with open(os.path.join(NEST_DATA, f"share_{u['id']}_{int(time.time())}{img[1]}"), "wb") as f:
                        f.write(img[0])
                try:
                    ib = json.load(open(INBOX_FILE, encoding="utf-8"))
                    if not isinstance(ib, dict):
                        ib = {}
                except Exception:
                    ib = {}
                lst = [x for x in ib.get(u["id"], []) if isinstance(x, dict)]
                lst.append({"t": int(time.time()), "kind": "share",
                            "title": "\U0001f4ce " + (title or "Re\u00e7u"),
                            "body": text or ("Image re\u00e7ue." if img else "Partage re\u00e7u.")})
                ib[u["id"]] = lst[-30:]
                json.dump(ib, open(INBOX_FILE, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception:
                pass
            self.send_response(303)
            self.send_header("Location", f"/{u['token']}/#hist")
            self.end_headers()
            return
        if len(_parts) == 2 and _parts[1] == "inbox_del":
            # 2026-09-27: the member removes one of their own messages (by time)
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upd
                _t = int((_upd.parse_qs(self.rfile.read(ln).decode("utf-8", "replace")).get("t", ["0"])[0]) or 0)
                ib = json.load(open(INBOX_FILE, encoding="utf-8"))
                ib[u["id"]] = [x for x in ib.get(u["id"], []) if not (isinstance(x, dict) and x.get("t") == _t)]
                json.dump(ib, open(INBOX_FILE, "w", encoding="utf-8"), ensure_ascii=False)
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}), "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "week_img":
            # 2026-09-27: the member's own week card, drawn by the app,
            # kept for the Sunday push (PNG only, <= 600 KB)
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(min(ln, 700000))
                if ln > 600000 or not body.startswith(b"\x89PNG\r\n\x1a\n"):
                    self._send(json.dumps({"ok": False}), "application/json")
                    return
                os.makedirs(NEST_DATA, exist_ok=True)
                _wp = os.path.join(NEST_DATA, f"week_{u['id']}.png")
                with open(_wp + ".tmp", "wb") as f:
                    f.write(body)
                os.replace(_wp + ".tmp", _wp)
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}), "application/json")
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
        if len(_parts) == 2 and _parts[1] == "manual_order":
            # the chart drags SL/TP and confirms; the daemon validates,
            # sizes from the debt ledger and sends it to the broker
            u = user_by_token(_parts[0])
            if not manual_ok(u):
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upm
                q = _upm.parse_qs(self.rfile.read(ln).decode("utf-8", "replace"))
                req = {"d": int(q.get("d", ["0"])[0]),
                       "sl": float(q.get("sl", ["0"])[0]),
                       "tp": float(q.get("tp", ["0"])[0]),
                       "entry": float(q.get("entry", ["0"])[0] or 0),
                       "cancel": q.get("cancel", [""])[0],
                       "modify": q.get("modify", [""])[0],
                       "close": q.get("close", [""])[0],
                       "ts": time.time(), "by": u.get("id")}
                if req["close"]:
                    # close the running position at market, on demand
                    try:
                        os.remove(os.path.join(
                            DIR, f"manual_order_result_{u['id']}.json"))
                    except Exception:
                        pass
                    with open(os.path.join(
                            DIR, f"manual_order_{u['id']}.json"), "w") as f:
                        json.dump(req, f)
                    self._send(json.dumps({"ok": True}), "application/json")
                    return
                if req["modify"]:
                    # moving the SL/TP of a position that is already open:
                    # only the two levels matter, direction and lot are the
                    # position's own
                    if req["sl"] <= 0 or req["tp"] <= 0:
                        self._send(json.dumps(
                            {"ok": False, "err": "SL et TP requis"}),
                            "application/json")
                        return
                    try:
                        os.remove(os.path.join(
                            DIR, f"manual_order_result_{u['id']}.json"))
                    except Exception:
                        pass
                    with open(os.path.join(
                            DIR, f"manual_order_{u['id']}.json"), "w") as f:
                        json.dump(req, f)
                    self._send(json.dumps({"ok": True}), "application/json")
                    return
                if req["cancel"]:
                    req["cancel"] = int(req["cancel"])
                    with open(os.path.join(
                            DIR, f"manual_order_{u['id']}.json"), "w") as f:
                        json.dump(req, f)
                    self._send(json.dumps({"ok": True}), "application/json")
                    return
                if req["d"] not in (1, -1) or req["sl"] <= 0 or req["tp"] <= 0:
                    self._send(json.dumps({"ok": False, "err": "champs invalides"}),
                               "application/json")
                    return
                try:
                    os.remove(os.path.join(
                        DIR, f"manual_order_result_{u['id']}.json"))
                except Exception:
                    pass
                with open(os.path.join(
                        DIR, f"manual_order_{u['id']}.json"), "w") as f:
                    json.dump(req, f)
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "activate":
            # family member enters the one-time code from the Owl
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
                _ce = peek_activation_code(code)
                if not _ce:
                    self._send(json.dumps({"ok": False,
                                           "err": "bad code"}),
                               "application/json")
                    return
                # 2026-10-03 (owner): the code names the package
                _cpkg, _cdays = _ce.get("pkg") or "family", int(_ce.get("days") or 30)
                if _cpkg != "family":
                    redeem_activation_code(code, u["id"])
                    ent_grant(u["id"], _cpkg, _cdays, "code")
                    _users_cache["t"] = 0.0
                    self._send(json.dumps({"ok": True, "pkg": _cpkg, "days": _cdays}), "application/json")
                    return
                _fq = _up.parse_qs(body)
                _ml = re.sub(r"\D", "", _fq.get("mt5_login", [""])[0] or "")[:12]
                _ms = (_fq.get("mt5_server", [""])[0] or "").strip()[:48]
                _mp = (_fq.get("mt5_password", [""])[0] or "").strip()[:64]
                if u.get("app_only") and not (_ml and _ms and _mp):
                    # 2026-10-04 (owner): a Signal member switching to Automatique
                    # - the robot needs the MT5 account; asked once, code kept
                    self._send(json.dumps({"ok": False, "need": "mt5"}), "application/json")
                    return
                if u.get("app_only") and family_count() >= FAMILY_CAP:
                    self._send(json.dumps({"ok": False, "err": "plein"}), "application/json")
                    return
                redeem_activation_code(code, u["id"])
                us = json.load(open(USERS_FILE, encoding="utf-8"))
                for x in us:
                    if x.get("id") == u["id"]:
                        x["trade"] = True
                        if x.get("app_only"):
                            # becomes a family account: the provisioner builds the
                            # terminal, the manager starts the robot; the identifiant
                            # + password still log in
                            x.pop("app_only", None)
                            x.update({"terminal": "", "login": int(_ml), "mt5_login": int(_ml),
                                      "mt5_password": _mp, "mt5_server": _ms, "symbol": "BTCUSD",
                                      "bot_only": True, "plan": "family", "mode": "auto",
                                      "dedicated": f"structure_bos_bot.py {x['id']}", "managed": True})
                            x["app_login"] = True
                json.dump(us, open(USERS_FILE, "w", encoding="utf-8"),
                          indent=2)
                _users_cache["t"] = 0.0
                ent_grant(u["id"], "family", _cdays, "code")      # the family package, for the code's days
                try:
                    _pf = os.path.join(DIR, pause_file(u["id"]))
                    _pz = json.load(open(_pf, encoding="utf-8"))
                    if _pz.get("by") == "expiry":
                        json.dump({"paused": False, "by": "renewal", "t": time.time()},
                                  open(_pf, "w"))
                except Exception:
                    pass
                start_copier(u["id"])
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "admin_unlock":
            # 2026-09-23 (owner): "the nid menu must not exist for all but
            # me." Works from ANY account's page (that is the point - the
            # owner should not have to go back to the Owl), so this only
            # requires a valid token to route through, not a master one.
            # The password is what proves identity, checked fresh here
            # exactly like every other master action.
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(ln).decode("utf-8", "replace")
                import urllib.parse as _up
                pw = (_up.parse_qs(body).get("pwd", [""])[0] or "")
                if not master_pwd_ok(pw):
                    self._send(json.dumps({"ok": False,
                                           "err": "bad password"}),
                               "application/json")
                    return
                secret = issue_admin_cookie()
                body_out = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header(
                    "Set-Cookie",
                    f"{ADMIN_COOKIE}={secret}; Path=/; Max-Age="
                    f"{ADMIN_MAX_AGE}; HttpOnly; SameSite=Lax")
                self.send_header("Content-Length", str(len(body_out)))
                self.end_headers()
                self.wfile.write(body_out)
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
                _fq = _up.parse_qs(body)
                _pw = (_fq.get("pwd", [""])[0] or "").strip()
                if not master_pwd_ok(_pw):
                    self._send(json.dumps({"ok": False,
                                           "err": "bad password"}),
                               "application/json")
                    return
                _pkg = (_fq.get("pkg", ["family"])[0] or "family").strip()
                try:
                    _days = max(1, min(366, int(_fq.get("days", ["30"])[0] or 30)))
                except Exception:
                    _days = 30
                self._send(json.dumps({"ok": True, "pkg": _pkg if _pkg in CODE_PKGS else "family", "days": _days,
                                       "code": new_activation_code(_pkg, _days, _fq.get("for", [""])[0])}),
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
            _pp = pause_file(u["id"])
            if _parts[1] == "pause":
                # the lock is enforced HERE, not only in the UI: a hidden
                # button is not a permission (owner 2026-09-16)
                if not can_switch(u):
                    self._send(json.dumps(
                        {"ok": False, "err": "verrouille"}),
                        "application/json")
                    return
                try:
                    on = (_form.get("on", ["1"])[0] == "1")
                    # seat cap: a switch INTO manual needs a free terminal
                    if (on and u.get("mode") not in MANUAL_MODES
                            and not is_admin(u) and manual_seats() >= MANUAL_CAP):
                        self._send(json.dumps({"ok": False, "err": "complet"}),
                                   "application/json")
                        return
                    if (str(u.get("login")) == str(LOGIN)
                            or u.get("trade")
                            or can_switch(u)):
                        json.dump({"paused": on, "by": u["id"],
                                   "t": time.time()},
                                  open(os.path.join(DIR, _pp), "w"))
                    # 2026-09-23 (owner): "we switch from manual to auto in
                    # the reglage page" - this IS that switch. For the one
                    # account that has a manual desk to hand off to, pausing
                    # must also swap WHICH PROCESS runs the account: the
                    # trade tool only works when the desk (not the bot) is
                    # running, and having both live at once risks two
                    # processes trading the same account under different
                    # magic numbers. owl_mode_switch.py performs the actual
                    # swap; this only records the request.
                    if can_switch(u):
                        _want = "semi" if on else "auto"
                        _mtmp = os.path.join(
                            DIR, "owl_mode_switch_request.json.tmp")
                        json.dump({"uid": u["id"], "want": _want,
                                  "t": time.time()}, open(_mtmp, "w"))
                        os.replace(_mtmp, os.path.join(
                            DIR, "owl_mode_switch_request.json"))
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
        if len(_parts) == 2 and _parts[1] == "scale_pref":
            # Owner 2026-09-24: "a professional opt in/out... default
            # opted in" for the balance-scaling dial deployed the same
            # day. Self-service, gated the same way as /pause - the
            # account's OWN broker password, not the admin one - because
            # it is that account's own risk setting, not a master action.
            # Read fresh by the bot once a day (structure_bos_bot.py
            # day_roll()), so the switch takes effect at the next UTC
            # rollover, same cadence as the resize itself.
            u = user_by_token(_parts[0])
            if u is None:
                self.send_response(404)
                self.end_headers()
                return
            if u.get("id") not in SCALE_TOGGLE_ALLOWED:
                self._send(json.dumps({"ok": False,
                                       "err": "pas disponible sur ce compte"}),
                           "application/json")
                return
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _up6
                _f6 = _up6.parse_qs(self.rfile.read(ln)
                                    .decode("utf-8", "replace"))
                _pwd6 = (_f6.get("pwd", [""])[0] or "").strip()
                if not pwd_ok(u, _pwd6):
                    self._send(json.dumps({"ok": False,
                                           "err": "bad password"}),
                               "application/json")
                    return
                _on = (_f6.get("on", ["1"])[0] == "1")
                us = json.load(open(USERS_FILE, encoding="utf-8"))
                for x in us:
                    if x.get("token") == u.get("token"):
                        x["scale_opt_out"] = not _on
                _tmp = USERS_FILE + ".tmp"
                json.dump(us, open(_tmp, "w", encoding="utf-8"), indent=2)
                os.replace(_tmp, USERS_FILE)
                _users_cache["t"] = 0.0
                self._send(json.dumps({"ok": True, "scale_on": _on}),
                           "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 1 and _parts[0] == "activate":
            # 2026-10-03 (owner): the /activate form
            try:
                ln = int(self.headers.get("Content-Length", 0))
                import urllib.parse as _upa
                _host = self.headers.get("Host") or "owltrader.duckdns.org"
                _origin = ("http" if ("127.0.0.1" in _host or "localhost" in _host) else "https") + "://" + _host
                _res = handle_activate(_upa.parse_qs(self.rfile.read(ln).decode("utf-8", "replace")), _origin)
                if isinstance(_res, tuple):
                    self.send_response(302)
                    self.send_header("Location", _res[1])
                    self.end_headers()
                else:
                    self._send(_res, "text/html; charset=utf-8")
            except Exception as e:
                self._send(_join_result("&#9888;&#65039; Petit souci", f"<p>{e}</p>"), "text/html; charset=utf-8")
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
        # 2026-10-03 (owner): the Android app - a wrapper around this site.
        # /owlnest.apk the file, /apk.json its version (the app and the
        # landing read it), /.well-known/assetlinks.json the proof that the
        # APK may own this site (no browser bar), /app where the APK starts.
        if len(parts) == 2 and parts[0] == ".well-known" and parts[1] == "assetlinks.json":
            self._send_file_fresh(os.path.join(DIR, "static", "assetlinks.json"), "application/json")
            return
        if len(parts) == 1 and parts[0] == "owlnest.apk":
            self._send_file_fresh(os.path.join(DIR, "static", "owlnest.apk"), "application/vnd.android.package-archive",
                                  disposition='attachment; filename="OwlNest.apk"')
            return
        if len(parts) == 1 and parts[0] == "apk.json":
            self._send_file_fresh(os.path.join(DIR, "static", "apk.json"), "application/json")
            return
        if len(parts) == 1 and parts[0] == "app":
            self._send(APP_PAGE, "text/html; charset=utf-8")
            return
        if len(parts) == 1 and parts[0] == "codeinfo":
            # the /activate page asks what a code is for (package, days) - nothing else
            import urllib.parse as _upc
            _q = _upc.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            _c = (_q.get("c", [""])[0] or "").strip().upper()[:12]
            _e = peek_activation_code(_c) if len(_c) >= 6 and not rate_limited(("codeinfo", _c), limit=20) else None
            _lab = {"family": "Automatique", "manual": "Signal", "strategy": "Strat\u00e9gie"}
            self._send(json.dumps({"ok": bool(_e), "pkg": (_e or {}).get("pkg"), "days": (_e or {}).get("days"),
                                   "label": _lab.get((_e or {}).get("pkg"), "")}), "application/json")
            return
        if len(parts) == 1 and parts[0] == "offres":
            # 2026-10-04 (owner): 'Creer un compte' - the offers first, credentials after the choice
            self._send(_offers_page("", ""), "text/html; charset=utf-8")
            return
        if len(parts) == 1 and parts[0] == "activate":
            # 2026-10-04 (owner): one door - everything starts at the login
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return
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
        if parts and parts[0] == "shots" and len(parts) == 2 and parts[1] in ("shot_home.png", "shot_marche.png", "shot_hist.png"):
            # 2026-09-27: landing screenshots, regenerated by review/landing_shots.mjs
            _sp = os.path.join(DIR, "static", parts[1])
            if not os.path.exists(_sp):
                self.send_response(404)
                self.end_headers()
                return
            self._send_static(_sp, "image/png")
            return
        if parts and parts[0] == "fonts" and len(parts) == 2 and parts[1] == "inter.woff2":
            self._send_static(os.path.join(DIR, "static", "InterVariable.woff2"), "font/woff2")
            return
        if parts and parts[0] == "icon512m.png":
            self._send(ICON512M, "image/png")
            return
        if parts and parts[0] == "demo":
            # front door to the showcase: no password, straight to the
            # public account's page (owner 2026-09-19)
            pu = public_user()
            if pu is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(302)
            self.send_header("Location", f"/{pu['token']}/")
            self.end_headers()
            return
        if not parts or parts[0] == "join":
            # front door: no token -> the welcome/sign-up screen
            _host = self.headers.get("Host") or "owlnest.local"
            _proto = "https" if (self.headers.get("X-Forwarded-Proto") == "https"
                                 or "127.0.0.1" not in _host and "localhost" not in _host) else "http"
            self._send(JOIN_PAGE.replace("%%ORIGIN%%", f"{_proto}://{_host}").replace("%%CONTACT%%", nest_config().get("contact_url") or "/activate").replace("%%TGBOT%%", nest_config().get("tg_bot") or "Kino_owl_bot"),
                       "text/html; charset=utf-8")
            return
        user = user_by_token(parts[0])
        if user is None:
            self.send_response(404)
            self.end_headers()
            return
        sub = parts[1] if len(parts) > 1 else ""
        if sub == "":
            page = (PAGE.replace("%%NAME%%", user.get("name", ""))
                    .replace("%%BUILD%%", APP_BUILD))
            self._send(page, "text/html; charset=utf-8")
        elif sub == "api":
            touch_seen(user.get("id"))
            if user.get("app_only"):
                # 2026-10-03 (owner): the public demo's live view, their name and package
                _d = user_stats(_data_user(user), False)
                _d.update({"name": user.get("name", ""), "plan": plan_of(user), "public": False,
                           "app_only": True, "is_master": False,
                           # a Signal member reads the app as a signal service
                           "trading_paused": bool(has(user.get("id"), "manual"))})
                _d.pop("nest", None)
                self._send(json.dumps(_d), "application/json")
            else:
                self._send(json.dumps(user_stats(
                    user, admin_cookie_ok(self.headers))), "application/json")
        elif sub == "day":
            self._send(json.dumps(day_payload(_data_user(user))), "application/json")
        elif sub == "trade":
            # 2026-09-27: the story of one closed trade, member-safe words
            try:
                import urllib.parse as _up3
                _q = _up3.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                _t = int(_q.get("t", ["0"])[0])
            except Exception:
                _t = 0
            self._send(json.dumps(trade_story(_data_user(user), _t)), "application/json")
        elif sub == "nest_reset_preview":
            if not is_admin(user):
                self.send_response(404)
                self.end_headers()
                return
            import urllib.parse as _upv
            _q = _upv.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            self._send(json.dumps(reset_preview((_q.get("uid", [""])[0] or "").strip())),
                       "application/json")
        elif sub == "week.png":
            _wp = os.path.join(NEST_DATA, f"week_{user.get('id')}.png")
            try:
                data = open(_wp, "rb").read()
            except Exception:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif sub == "health":
            # 2026-09-27: the owner's service page - ages of every feed
            if not (user.get("id") in ("kino", "std")
                    or str(user.get("login")) == str(LOGIN)
                    or admin_cookie_ok(self.headers)):
                self.send_response(404)
                self.end_headers()
                return
            self._send(json.dumps(service_health()), "application/json")
        elif sub == "proof":
            # 2026-09-29: "La preuve" - every member; the public showcase reads it
            # too (owner: the best sales page we have), without the personal block
            try:
                # the account's own run if we have one, else its package
                _uid = user.get("id") or ""
                try:
                    _pkg = (PKG.for_account(_uid) or {}).get("package") or "base"
                except Exception:
                    _pkg = "base"
                try:
                    if _uid in (json.load(open(os.path.join(DIR, "lab", "proof.json"), encoding="utf-8")).get("packages") or {}):
                        _pkg = _uid
                except Exception:
                    pass
                _pp = dict(proof_payload(_pkg))
                _pp["mine"] = None if user.get("public") else proof_mine(user.get("id") or "")
                _pp["history"] = proof_history(_pp)
                self._send(json.dumps(_pp), "application/json")
            except Exception as e:
                self._send(json.dumps({"err": str(e)[:100]}), "application/json")
        elif sub == "lab_peek":
            # 2026-09-28 (owner): every package gets a glance at the lab -
            # the counts, one rule already in the robot, and the invitation
            try:
                if user.get("public"):
                    self._send(json.dumps({"err": "public"}), "application/json")
                    return
                _lp = lab_payload()
                _sample = next((it for it in _lp.get("items", []) if it.get("id") == "storm"), None)
                self._send(json.dumps({"counts": _lp.get("counts", {}), "sample": _sample,
                                       "n_ideas": len([c for c in _lp.get("candidates", []) if c.get("label") == "a_tester"]),
                                       "live_trades": _lp.get("live_trades", 0)}), "application/json")
            except Exception as e:
                self._send(json.dumps({"err": str(e)[:100]}), "application/json")
        elif sub == "lab":
            # 2026-09-28: the lab - Strategie members and the admin
            try:
                if not (is_admin(user) or has(user.get("id"), "strategy") or admin_cookie_ok(self.headers)):
                    self._send(json.dumps({"err": "strategy"}), "application/json")
                    return
                self._send(json.dumps(lab_payload()), "application/json")
            except Exception as e:
                self._send(json.dumps({"err": str(e)[:100]}), "application/json")
        elif sub == "patterns":
            # 2026-09-28: the patterns the market space stands on
            try:
                if not (is_admin(user) or has(user.get("id"), "manual") or family_active(ent(user.get("id")))):
                    self._send(json.dumps({"err": "observer"}), "application/json")
                    return
                self._send(json.dumps(patterns()), "application/json")
            except Exception as e:
                self._send(json.dumps({"err": str(e)[:100]}), "application/json")
        elif sub == "market_hours":
            # 2026-09-28: the market memory folded into weekday x hour (UTC)
            try:
                if not (is_admin(user) or has(user.get("id"), "manual") or family_active(ent(user.get("id")))):
                    self._send(json.dumps({"err": "observer"}), "application/json")
                    return
                self._send(json.dumps(market_hours()), "application/json")
            except Exception as e:
                self._send(json.dumps({"err": str(e)[:100]}), "application/json")
        elif sub == "robot_why":
            # 2026-09-28: the occasions the robot let go, by FAMILY of reason
            # (weather / catch-up / against the trend / limit) - never the rule
            try:
                self._send(json.dumps(robot_why(user)), "application/json")
            except Exception as e:
                self._send(json.dumps({"err": str(e)[:100]}), "application/json")
        elif sub == "robot_journal":
            # 2026-09-28: the last 20 closed trades with their plain-words story
            try:
                self._send(json.dumps(robot_journal(user)), "application/json")
            except Exception as e:
                self._send(json.dumps({"err": str(e)[:100], "items": []}), "application/json")
        elif sub == "chart_day":
            # 2026-09-28 (owner): "voir une journee passee" - that UTC day's
            # candles (same silence filter), its main structure (same engine
            # as the feed) and the member's trades of the day
            try:
                import urllib.parse as _upd
                _q = _upd.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                _ds = (_q.get("d", [""])[0] or "").strip()
                _day = datetime.strptime(_ds, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                self._send(json.dumps({"err": "bad date"}), "application/json")
                return
            _nowu = datetime.now(timezone.utc)
            if _day > _nowu or (_nowu - _day).days > 60:
                self._send(json.dumps({"err": "out of range"}), "application/json")
                return
            try:
                import owl_chart_feed as _F
                # the server's own terminal (initialize() never switches an
                # already-attached process); the Pro terminal names it BTCUSDm
                with _lock:
                    if not mt5.initialize(path=TERMINAL):
                        raise RuntimeError("mt5 init")
                    _sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
                    mt5.symbol_select(_sym, True)
                    _rt = mt5.copy_rates_range(_sym, mt5.TIMEFRAME_M1,
                                               _day - timedelta(hours=8), _day + timedelta(days=1))
                    _err = mt5.last_error()
                if _rt is None or len(_rt) == 0:
                    raise RuntimeError("no history for that day " + str(_err))
                _kept = _F.build(_rt)
                _res = _F.engine(_kept)
                _t0 = int(_day.timestamp())
                _t1 = _t0 + 86400
                _cands = [k for k in _kept if _t0 <= k[0] < _t1]
                d = {"updated": int(time.time()), "symbol": "BTCUSD", "day": _ds, "past": True,
                     "candles": _cands, "live": None,
                     "dots": [x for x in _res[0] if _t0 - 8 * 3600 <= x[0] < _t1],
                     "marks": [x for x in _res[1] if _t0 - 8 * 3600 <= x[0] < _t1],
                     "int_dots": [], "int_marks": [], "trend": _res[2], "choch": 0,
                     "next_bos": None, "invalid": None, "int_trend": 0, "h1": [],
                     "px": (_cands[-1][4] if _cands else None), "trades": [], "pending": [],
                     "moves_2h": 0, "vol_now": 0, "vol_ref": 0, "closed": []}
                try:
                    nd2 = json.load(open(os.path.join(DIR, "nest_data", f"{user.get('id')}.json")))
                    for p in (nd2.get("trades") or []):
                        _mw = re.match(r"^(\d\d)/(\d\d) (\d\d):(\d\d)$", p.get("w") or "")
                        if not _mw or p.get("ep") is None or p.get("xp") is None:
                            continue
                        _y = _day.year if int(_mw.group(2)) <= _nowu.month else _day.year - 1
                        _xt = int(datetime(_y, int(_mw.group(2)), int(_mw.group(1)),
                                           int(_mw.group(3)), int(_mw.group(4)), tzinfo=timezone.utc).timestamp())
                        _et = _xt - int(round(float(p.get("dur") or 0) * 60))
                        if _t0 <= _xt < _t1 or _t0 <= _et < _t1:
                            d["closed"].append([_et, _xt, float(p["ep"]), float(p["xp"]), float(p.get("p") or 0)])
                except Exception:
                    pass
                d["acct"] = user.get("login")
                d["uid"] = user.get("id")
                d["auto"] = acct_auto(user)
                self._send(json.dumps(d), "application/json")
            except Exception as e:
                self._send(json.dumps({"err": str(e)[:100]}), "application/json")
        elif sub == "compare":
            # 2026-09-28: a manual member's month against the robot's (public
            # demo account), day by day, same period
            try:
                _uid = user.get("id")
                if not (is_admin(user) or has(_uid, "manual")):
                    self._send(json.dumps({"err": "manual only"}), "application/json")
                    return
                _pub = public_user()
                _me = json.load(open(os.path.join(DIR, "nest_data", f"{_uid}.json"))).get("month_days") or []
                _rb = (json.load(open(os.path.join(DIR, "nest_data", f"{_pub.get('id')}.json"))).get("month_days") or []) if _pub else []
                _era = era_ts(user)
                if _era:
                    _e0 = time.strftime("%Y-%m-%d", time.gmtime(_era))
                    _me = [x for x in _me if x.get("d", "") >= _e0]
                self._send(json.dumps({"me": _me, "robot": _rb, "robot_name": (_pub or {}).get("name", "Le robot du Owl"),
                                       "month": time.strftime("%Y-%m", time.gmtime())}), "application/json")
            except Exception as e:
                self._send(json.dumps({"err": str(e)[:100], "me": [], "robot": []}), "application/json")
        elif sub == "signals":
            # 2026-09-28: the signals the member's desk emitted (last 100)
            try:
                lst = json.load(open(os.path.join(DIR, f"owl_signals_{user.get('id')}.json"), encoding="utf-8"))
                _era = era_ts(user)
                lst = sig_merge(user.get("id"), [x for x in lst if isinstance(x, dict) and (not _era or x.get("t", 0) >= _era)])
                self._send(json.dumps({"items": lst[-100:][::-1], "score": sig_score(user.get("id"), _era)}), "application/json")
            except Exception:
                self._send(json.dumps({"items": [], "score": None}), "application/json")
        elif sub == "payments":
            # 2026-09-28: "Mes paiements" - this member's NOWPayments records + end dates
            try:
                _uid = user.get("id")
                try:
                    _pl = json.load(open(PAY_FILE, encoding="utf-8"))
                except Exception:
                    _pl = []
                items = [{"t": p.get("t"), "pkg": (str(p.get("order") or "").split("|") + ["", ""])[1],
                          "granted": p.get("granted"), "status": p.get("status"),
                          "amount": p.get("amount"), "currency": p.get("currency"), "id": p.get("id")}
                         for p in _pl if isinstance(p, dict) and not p.get("test") and str(p.get("order") or "").startswith(str(_uid) + "|")][-30:][::-1]
                e = ent(_uid)
                self._send(json.dumps({"items": items,
                                       "ends": {k: int(float(e.get(k + "_until") or 0)) for k in ("family", "manual", "strategy")}}),
                           "application/json")
            except Exception:
                self._send(json.dumps({"items": [], "ends": {}}), "application/json")
        elif sub == "inbox":
            self._send(json.dumps(inbox_items(user)), "application/json")
        elif sub == "export.csv":
            # 2026-09-27: member-safe columns only, from the account's journal
            self._send(export_csv(user), "text/csv; charset=utf-8")
        elif sub == "chart":
            # aura redesign 2026-09-08 lives in its own file; the
            # inline constant is only the fallback
            try:
                _cp = os.path.join(DIR, "owl_chart_page.html")
                _html = open(_cp, encoding="utf-8").read()
                # stamp the build so a stale page on a phone is obvious
                _st = time.strftime("%m%d.%H%M",
                                    time.localtime(os.path.getmtime(_cp)))
                _full = "true" if (admin_cookie_ok(self.headers)
                                   or has(user.get("id"), "strategy")) else "false"
                _tier = ("member" if (admin_cookie_ok(self.headers) or is_admin(user)
                                      or has(user.get("id"), "manual")) else "observer")
                self._send(_html.replace("%%BUILD%%", _st).replace("%%FULL%%", _full)
                           .replace("%%TIER%%", _tier),
                           "text/html; charset=utf-8")
            except Exception:
                self._send(CHART_PAGE, "text/html; charset=utf-8")
        elif sub == "chart_htf":
            # 2026-09-30 (owner): the higher timeframe panel. The chart feed
            # builds M15/H1/H4 with the SAME silence filter and the SAME
            # structure engine as the minute chart; the app only serves it.
            try:
                import urllib.parse as _uph
                _qh = _uph.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                _tf = (_qh.get("tf", ["H1"])[0] or "H1").upper()
                if _tf == "ALL":
                    _h = json.load(open(os.path.join(
                        DIR, "owl_chart_htf.json"), encoding="utf-8"))
                    _sum = {}
                    for _k in ("M15", "H1", "H4"):
                        _t = (_h.get("tf") or {}).get(_k) or {}
                        if not _t:
                            continue
                        _sum[_k] = {"trend": _t.get("trend") or 0,
                                    "int": _t.get("int_trend") or 0,
                                    "since": _t.get("since") or 0}
                    self._send(json.dumps({"tf": _sum,
                                           "updated": _h.get("updated")}),
                               "application/json")
                    return
                if _tf not in ("M15", "H1", "H4"):
                    _tf = "H1"
                _h = json.load(open(os.path.join(DIR, "owl_chart_htf.json"), encoding="utf-8"))
                _d = dict((_h.get("tf") or {}).get(_tf) or {})
                _d["tf"] = _tf
                _d["updated"] = _h.get("updated")
                _d["symbol"] = _h.get("symbol")
                self._send(json.dumps(_d), "application/json")
            except Exception as e:
                self._send(json.dumps({"err": str(e)[:100]}), "application/json")
        elif sub == "chart_data":
            # 2026-09-16 (owner): the chart shows the positions of the
            # account BEING VIEWED, never the terminal that happens to
            # serve the candles. Works for every member, and keeps
            # working if the demo account goes away.
            try:
                d = json.load(open(os.path.join(DIR, "owl_chart_btc.json")))
            except Exception:
                self._send("{}", "application/json")
                return
            tr = []
            uid = user.get("id")
            try:
                ms = json.load(open(os.path.join(
                    DIR, f"manual_state_{uid}.json")))
                for p in (ms.get("open") or []):
                    tr.append([int(p.get("d") or 1), float(p.get("lot") or 0),
                               round(float(p.get("e") or 0), 2),
                               round(float(p.get("sl") or 0), 2),
                               round(float(p.get("tp") or 0), 2),
                               round(float(p.get("pl") or 0), 2), "m"])
                d["pending"] = ms.get("pending") or []
            except Exception:
                pass
            if not tr:
                try:
                    nd = json.load(open(os.path.join(
                        DIR, "nest_data", f"{uid}.json")))
                    for p in (nd.get("open_list") or []):
                        tr.append([1 if p.get("d") == "A" else -1,
                                   float(p.get("lot") or 0),
                                   round(float(p.get("e") or 0), 2),
                                   round(float(p.get("sl") or 0), 2),
                                   round(float(p.get("tp") or 0), 2),
                                   round(float(p.get("pl") or 0), 2), "b"])
                except Exception:
                    pass
            d["trades"] = tr
            # 2026-09-27: the member's closed trades (entry -> exit arrows)
            try:
                nd2 = json.load(open(os.path.join(DIR, "nest_data", f"{uid}.json")))
                _cl = []
                _now = datetime.now(timezone.utc)
                for p in (nd2.get("trades") or [])[:40]:
                    _mw = re.match(r"^(\d\d)/(\d\d) (\d\d):(\d\d)$", p.get("w") or "")
                    if not _mw or p.get("ep") is None or p.get("xp") is None:
                        continue
                    _y = _now.year - (1 if int(_mw.group(2)) > _now.month else 0)
                    _xt = int(datetime(_y, int(_mw.group(2)), int(_mw.group(1)),
                                       int(_mw.group(3)), int(_mw.group(4)),
                                       tzinfo=timezone.utc).timestamp())
                    _et = _xt - int(round(float(p.get("dur") or 0) * 60))
                    _cl.append([_et, _xt, float(p["ep"]), float(p["xp"]),
                                round(float(p.get("p") or 0), 2),
                                1 if p.get("d") == "A" else -1])
                d["closed"] = _cl
            except Exception:
                d["closed"] = []
            d["acct"] = user.get("login")
            d["uid"] = user.get("id")     # which account this chart shows
            d["auto"] = acct_auto(user)
            # 2026-09-28: the chart's Robot sheet must not say "the robot works"
            # on an account that has no robot (a Manuel member in "auto" runs
            # nothing) - same liveness read as Le Nid
            try:
                _b, _l, _k = bot_on(user.get("id"))
                d["bot"] = bool(_b)
                d["bot_live"] = bool(_l)
            except Exception:
                pass
            # 2026-09-28: the chart's Meteo panel must say what weather_gate()
            # says for THIS account (both brakes are per-account dials)
            try:
                _pk = PKG.for_account(user.get("id") or "")
                d["gates"] = {"nervosity": bool(_pk.get("nervosity", True)),
                              "movement": bool(_pk.get("movement", True))}
                # 2026-10-01: which movement rule decides. The inner rule is
                # only ever applied to an INNER entry, and those are off, so
                # the chart must stop choosing it just because an inner
                # structure exists - same fix as the Marche card.
                d["internal_entries"] = bool(
                    _pk.get("internal_entries", False))
            except Exception:
                pass
            self._send(json.dumps(d), "application/json")
        elif sub == "manual_state":
            # assisted manual trading on the live account (2026-09-15)
            if not manual_ok(user):
                self.send_response(404)
                self.end_headers()
                return
            _uid = user.get("id")
            try:
                d = json.load(open(os.path.join(
                    DIR, f"manual_state_{_uid}.json")))
            except Exception:
                d = {}
            d["mode"] = user.get("mode")
            try:
                if isinstance(d.get("signal"), dict):
                    sig_merge(_uid, [d["signal"]])   # 2026-09-28: the member's own marks
            except Exception:
                pass
            try:
                d["last_order"] = json.load(open(os.path.join(
                    DIR, f"manual_order_result_{_uid}.json")))
            except Exception:
                pass
            self._send(json.dumps(d), "application/json")
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
        elif sub == "icon512m.png":
            self._send(ICON512M, "image/png")
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    print(f"OwlNest v2 serving on port {PORT}, token {TOKEN}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()

