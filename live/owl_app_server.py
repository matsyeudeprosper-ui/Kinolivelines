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
    "shortcuts": [
        {"name": "Marché", "url": "./#marche",
         "icons": [{"src": "icon192.png", "sizes": "192x192"}]},
        {"name": "Historique", "url": "./#hist",
         "icons": [{"src": "icon192.png", "sizes": "192x192"}]},
        {"name": "Résumé du jour", "url": "./#resume",
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
    "if(e.request.mode==='navigate'){"
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
PACKAGES = {"manual": {"usd": 29, "days": 30, "label": "Manuel"},
            "strategy": {"usd": 49, "days": 30, "label": "Strat\u00e9gie"}}
MANUAL_CAP = 10          # one MT5 terminal per manual member on this VPS


def _ents():
    try:
        e = json.load(open(ENT_FILE, encoding="utf-8"))
        return e if isinstance(e, dict) else {}
    except Exception:
        return {}


def ent(uid):
    return _ents().get(uid) or {}


def has(uid, key):
    """family covers everything; strategy covers manual; dates are epochs."""
    e = ent(uid)
    if e.get("family"):
        return True
    now = time.time()
    if key == "manual":
        return (float(e.get("manual_until") or 0) > now
                or float(e.get("strategy_until") or 0) > now)
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
    if pkg == "strategy":
        r["manual_until"] = max(int(r.get("manual_until") or 0), r[k])
    r["updated"] = int(time.time())
    r["src"] = src
    e[uid] = r
    json.dump(e, open(ENT_FILE + ".tmp", "w", encoding="utf-8"), indent=1)
    os.replace(ENT_FILE + ".tmp", ENT_FILE)
    return r


def ent_family(uid, on=True):
    e = _ents()
    r = e.get(uid) or {}
    r["family"] = bool(on)
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


def can_switch(u):
    """May this account switch auto <-> manual (and use the trade tool)?"""
    return u is not None and (is_admin(u) or has(u.get("id"), "manual"))


def plan_of(u):
    e = ent(u.get("id"))
    cfg = nest_config()
    return {"family": bool(e.get("family")),
            "manual": has(u.get("id"), "manual"),
            "strategy": has(u.get("id"), "strategy"),
            "manual_until": int(e.get("manual_until") or 0),
            "strategy_until": int(e.get("strategy_until") or 0),
            "packages": PACKAGES,
            "seats_left": max(0, MANUAL_CAP - manual_seats()),
            "pay_ready": bool(cfg.get("np_api_key")),
            "mql5_url": cfg.get("mql5_url") or ""}
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
    "fresh":      ("Harvest H1", "harvest_fresh_state.json",
                   "harvest_fresh.log", 1800),
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
            and (is_admin(u) or has(u.get("id"), "manual")))


def master_pwd_ok(pw):
    """Master actions always validate against the KINO record's
    broker password, whichever admin page they come from."""
    k = next((x for x in users() if x.get("id") == "kino"), None)
    return k is not None and pwd_ok(k, pw)


# 2026-09-23 (owner): "the nid menu must not exist for all but me."
# is_master was tied to WHICH ACCOUNT's page is open (Kino's own token),
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
body{background:var(--bg);color:var(--text);padding:0 0 96px;
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
.tb{flex:1;background:none;border:0;color:var(--muted);font-size:.72rem;
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
.ssub{font-size:.78rem;color:var(--muted);margin-top:2px}
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
.live{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;flex:none;
 background:rgba(46,204,113,.14);color:var(--up-soft);font-size:.7rem;
 font-weight:700;padding:5px 11px;border-radius:999px;
 letter-spacing:.06em}
.dot{width:8px;height:8px;border-radius:50%;background:var(--up);
 animation:p 1.8s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.25}}
.hello{color:rgba(219,233,247,.62);font-size:.86rem;margin-top:22px;letter-spacing:.01em}
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
#mx-orb{width:52px;height:52px;border-radius:50%;flex:none;
 display:flex;align-items:center;justify-content:center;
 font-size:1.65rem;background:radial-gradient(circle at 35% 30%,
 rgba(255,255,255,.14),rgba(255,255,255,.03));
 border:1px solid rgba(255,255,255,.1);
 animation:orbp 3.2s ease-in-out infinite}
@keyframes orbp{0%,100%{box-shadow:0 0 0 0 var(--mxg)}
 50%{box-shadow:0 0 22px 3px var(--mxg)}}
#mx-wave{position:absolute;inset:0;pointer-events:none;
 background:linear-gradient(115deg,transparent 30%,var(--mxg) 50%,
 transparent 70%);background-size:280% 100%;opacity:.5;
 animation:wv 7s linear infinite}
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
.lbl{font-size:.72rem;color:var(--muted2);text-transform:uppercase;
 letter-spacing:.07em;font-weight:600}
.val{font-size:1.45rem;font-weight:800;margin-top:8px;
 white-space:nowrap;letter-spacing:-.3px}
.sub{font-size:.74rem;color:var(--muted);margin-top:6px}
.pos{color:var(--up)}.neg{color:var(--down)}.neu{color:var(--text)}
.sec{margin:26px 8px 10px;color:var(--muted);font-weight:700;
 font-size:.68rem;text-transform:uppercase;letter-spacing:.09em;
 text-align:left}
.sec .hint{opacity:.7;letter-spacing:.02em;text-transform:none;
 font-weight:500}
.row{display:flex;justify-content:space-between;align-items:center;
 padding:12px 4px;min-height:44px;border-bottom:1px solid var(--border);
 font-size:1rem}
.row:last-child{border-bottom:0}
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
 box-shadow:0 -10px 40px rgba(0,0,0,.5);max-width:480px;margin:0 auto}
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
<span id="acctline"></span></span>
<span style="display:flex;align-items:center;gap:10px">
<button id="acctchip" onclick="acctSheet()" aria-label="Changer de compte" style="display:none;align-items:center;gap:6px;
 color:#dbe9f7;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);
 border-radius:99px;padding:5px 10px;font-size:.7rem;font-weight:700;line-height:1"><svg class="ic ic-s"><use href="#i-users"/></svg><span id="acctchip-n"></span></button>
<a id="chartlink" href="#" title="Graphique en direct" aria-label="Graphique en direct"
 style="text-decoration:none;line-height:1;display:inline-flex;
 color:#dbe9f7;background:rgba(255,255,255,.08);
 border:1px solid rgba(255,255,255,.14);
 border-radius:99px;padding:5px 9px"><svg class="ic ic-s"><use href="#i-chart"/></svg></a>
<span class="live" id="lv"><span class="dot" id="lvd"></span><span
 id="lvt">EN DIRECT</span></span>
<a href="../" style="color:#9fc2de;text-decoration:none;font-size:1.25rem;
 line-height:1" title="Sortir" aria-label="Sortir">&#10162;</a></span></div>
<div class="hello" id="hello">Bonjour %%NAME%% &#128075;</div>
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
 onclick="tab('marche',document.getElementById('tb-marche'))">
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
 <button onclick="ledInfo()" aria-label="explications" style="
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
  demandez-le &agrave; <b>Kino sur Telegram</b>.</div>
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
 style="width:100%;height:80px;display:block"></svg></div>
</div>
<div class="tab" id="tab-marche">
<div class="sec" style="margin-top:26px">Le march&eacute; <span class="hint" id="mx-hint">&middot; ce que le robot voit</span></div>
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
</div>
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
  </div>
  <svg id="mx-nerv" viewBox="0 0 300 120" style="width:100%;height:120px;
   display:none;margin-top:10px"></svg>
  <div id="mx-chips" style="display:grid;
   grid-template-columns:1fr 1fr;gap:7px;margin-top:12px"></div>
 </div>
 <div id="st" style="position:relative;margin:0 16px;
  border-top:1px solid rgba(255,255,255,.06);padding:9px 0 11px;
  font-size:.8rem;color:var(--muted)">Connexion...</div>
</div>
<div class="panel" id="daycard" style="display:none;margin-top:12px">
 <div class="lbl" id="day-lbl">La journ&eacute;e du robot</div>
 <div id="day-sum" style="font-size:.95rem;color:var(--text);line-height:1.5;
  margin-top:8px"></div>
 <svg id="daybar" viewBox="0 0 300 34" style="width:100%;height:34px;
  display:block;margin-top:12px"></svg>
 <div id="day-list" style="margin-top:6px"></div>
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
<div class="panel" id="hist">
<div class="row"><span class="skel" style="width:42%">&nbsp;</span>
<span class="skel" style="width:18%">&nbsp;</span></div>
<div class="row"><span class="skel" style="width:36%">&nbsp;</span>
<span class="skel" style="width:22%">&nbsp;</span></div>
<div class="row"><span class="skel" style="width:46%">&nbsp;</span>
<span class="skel" style="width:16%">&nbsp;</span></div></div>

</div>
<div class="tab" id="tab-set">
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
  <div style="flex:1"><b id="contact-lbl">Contacter Kino</b>
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
  <div style="flex:1"><b>Mes &eacute;tapes</b>
   <div class="ssub" id="steps-sub">Vos premiers pas avec le robot</div></div>
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
  <div style="flex:1;min-width:0"><b id="plan-t" style="font-size:1rem">Observateur</b>
   <div id="plan-s" style="font-size:.84rem;color:var(--muted2);line-height:1.45;margin-top:2px"></div></div>
 </div>
 <div id="plan-btns" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px"></div>
 <div id="plan-note" style="font-size:.74rem;color:var(--muted);margin-top:8px;line-height:1.45"></div>
</div>
<a class="srow" id="mql5row" href="#" target="_blank" rel="noopener" style="display:none;text-decoration:none;color:inherit;margin-top:10px">
 <div class="sic"><svg class="ic"><use href="#i-bot"/></svg></div>
 <div style="flex:1"><b>Trading automatique</b>
  <div class="ssub">Copier le compte de Kino via MQL5 &middot; ouvrir le signal</div></div>
 <svg class="ic chv"><use href="#i-chev"/></svg>
</a>
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
     without going back to Kino. Password-verified server-side
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
  <div style="flex:1"><b>Paiements &amp; MQL5</b>
   <div class="ssub" id="paycfg-sub">Cl&eacute; NOWPayments, secret IPN, lien du signal MQL5</div></div>
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
 <a class="srow" href="../" style="text-decoration:none">
  <div class="sic"><svg class="ic"><use href="#i-switch"/></svg></div>
  <div style="flex:1"><b>Changer de compte</b>
   <div class="ssub">Ou cr&eacute;er un nouveau nid</div></div>
  <svg class="ic chv"><use href="#i-chev"/></svg>
 </a>
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
<div class="panel" id="nest">...</div>
<button id="invbtn" style="width:100%;margin-top:14px;
 background:var(--surface3);color:var(--text2);border:1px solid var(--border2);
 border-radius:14px;padding:15px;font-size:1rem;font-weight:700">
 <svg class="ic"><use href="#i-ticket"/></svg> Code d&#39;invitation (compte r&eacute;el)</button>
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
 <a href="../" style="margin-top:22px;color:var(--muted);font-size:.85rem;text-decoration:none">Code oubli&eacute; ? Changer de compte</a>
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
  if(_h==='marche'||_h==='hist'||_h==='set'||_h==='resume'){
   const _b=[...document.querySelectorAll('.tb')].find(x=>(x.getAttribute('onclick')||'').indexOf("'"+_h+"'")>=0);
   if(_b)tab(_h,_b);
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
function T(k){const Lb=LANG()==='en'?VOICE_EN:VOICE;const v=Lb[MAN()?'manual':'auto'];
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
 'Notifications':'Notifications','Activer les notifications':'Enable notifications','Tout':'All','Important seulement':'Important only',
 'Application':'App','Installer l\u2019application':'Install the app','Installer l\\'application':'Install the app',
 'Une icône sur votre écran d\\'accueil':'An icon on your home screen','Une icône sur votre écran d\u2019accueil':'An icon on your home screen',
 'Apparence':'Appearance','Sombre':'Dark','Clair':'Light','Taille du texte':'Text size','Normal':'Normal','Plus grand':'Larger',
 'Langue':'Language','Code d\\'accès':'Passcode','Code d\u2019accès':'Passcode','Protéger cette page avec 4 chiffres':'Protect this page with 4 digits',
 'Télécharger mes trades':'Download my trades','Fichier CSV · date, sens, lot, entrée, sortie, résultat':'CSV file · date, side, lot, entry, exit, result',
 'Messages':'Messages','Les dernières notifications reçues':'Latest notifications received','Mon objectif':'My goal','Choisir un solde à atteindre':'Pick a balance to reach',
 'Mes étapes':'My milestones','Vos premiers pas avec le robot':'Your first steps with the robot','Ce qu\\'il faut savoir':'Good to know','Ce qu\u2019il faut savoir':'Good to know',
 'Revoir le guide':'See the guide again','Le robot':'The robot','Le service':'Service health','Accès':'Access','Déverrouiller Le Nid':'Unlock The Nest',
 'Réservé à l\\'administrateur':'Admin only','Réservé à l\u2019administrateur':'Admin only',
 'Fermer':'Close','Annuler':'Cancel','Enregistrer':'Save','Voir sur le graphique':'View on the chart','Résultat':'Result','Taille':'Size','Entrée':'Entry','Sortie':'Exit','Durée':'Duration','Quand':'When',
 'Achat':'Buy','Vente':'Sell','Rapport du mois':'Month report','Vos comptes':'Your accounts','Retour à mon compte':'Back to my account','Ouvrir Le Nid':'Open The Nest',
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
  const pw=await askPwd(
   isPaused?'Lancer le trading automatique ?':'Repasser en manuel ?',
   isPaused
    ?'Le robot prendra les trades tout seul, et seulement quand les '+
     'conditions du marché sont favorables. Aucune performance '+
     'garantie. Tu peux repasser en manuel à tout moment.'
    :'Le robot n’entrera plus seul. Tu gardes la main depuis le '+
     'graphique. Les trades ouverts gardent leur SL et leur TP.',
   isPaused?'&#129302; Lancer l’automatique':'&#9995; Repasser en manuel',
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
  const r=await fetch(B+'activate',{method:'POST',
   headers:{'Content-Type':'application/x-www-form-urlencoded'},
   body:'code='+encodeURIComponent(code)}).catch(()=>null);
  ab.disabled=false;ab.textContent='Activer';
  try{const j=await r.json();
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
    'nouveau code &agrave; Kino.';}}
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
 he.innerHTML=he.innerHTML.replace('Bonjour',g)
  .replace('&#128075;',(h>=20||h<5)?'&#127769;':'&#128075;');
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
  const Y=v=>(100-(v/mx)*84);
  const band=(v,c,l)=>'<line x1="6" y1="'+Y(v).toFixed(1)+'" x2="294" y2="'+
   Y(v).toFixed(1)+'" style="stroke:'+c+';opacity:.55" stroke-width="1" '+
   'stroke-dasharray="3 4"/><text x="8" y="'+(Y(v)-3).toFixed(1)+
   '" font-size="8" style="fill:'+c+'">'+l+'</text>';
  let ticks='';for(let k=0;k<=4;k++){const t=t0+sp*k/4,x=X(t).toFixed(1);
   const h=new Date(t*1000).getHours();
   ticks+='<line x1="'+x+'" y1="102" x2="'+x+'" y2="106" style="stroke:var(--border2)"/>'+
    '<text x="'+x+'" y="117" text-anchor="'+(k===0?'start':(k===4?'end':'middle'))+
    '" font-size="8" style="fill:var(--muted)">'+(k===4?'maintenant':h+'h')+'</text>';}
  const dp=path(Y);
  el.style.display='block';
  el.innerHTML='<defs><linearGradient id="ng" x1="0" y1="0" x2="0" y2="1">'+
   '<stop offset="0" stop-color="#8fc6ff" stop-opacity=".28"/>'+
   '<stop offset="1" stop-color="#8fc6ff" stop-opacity="0"/></linearGradient></defs>'+
   '<rect x="6" y="'+Y(mx).toFixed(1)+'" width="288" height="'+(Y(1.85)-Y(mx)).toFixed(1)+
   '" style="fill:var(--down);opacity:.05"/>'+
   bands(Y,6,96)+band(1.0,'var(--muted)','1,0\\u00d7 calme')+
   band(1.85,'var(--down)','1,85\\u00d7 tr\\u00e8s agit\\u00e9')+
   '<line x1="6" y1="102" x2="294" y2="102" style="stroke:var(--border2)"/>'+ticks+
   '<path d="'+dp+' L'+X(t1).toFixed(1)+',102 L6,102 Z" fill="url(#ng)"/>'+
   '<path d="'+dp+'" fill="none" style="stroke:var(--accent-soft)" stroke-width="1.9" '+
   'stroke-linejoin="round"/>'+
   '<circle cx="'+X(t1).toFixed(1)+'" cy="'+Y(last).toFixed(1)+'" r="6" style="fill:var(--accent-soft);opacity:.25"/>'+
   '<circle cx="'+X(t1).toFixed(1)+'" cy="'+Y(last).toFixed(1)+'" r="3" style="fill:var(--accent-soft)"/>'+
   '<text x="'+Math.min(262,X(t1)-8).toFixed(1)+'" y="'+(Y(last)-9).toFixed(1)+
   '" text-anchor="end" font-size="9" font-weight="700" style="fill:var(--accent-soft)">'+
   last.toFixed(2).replace('.',',')+'\\u00d7</text>';
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
 if(md)md.textContent=(tr.length?tr.length+' trade'+(tr.length>1?'s':''):'Aucun trade pour l\u2019instant')+
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
 const last=c[c.length-1],col=last>=0?'#2ecc71':'#ff5c5c';
 const y0=Y(0).toFixed(1),ex=pts[pts.length-1][0].toFixed(1),
  ey=pts[pts.length-1][1].toFixed(1);
 const fm=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(0);
 const iMx=c.indexOf(mx),iMn=c.indexOf(mn);
 const lab=(i,v,above)=>'<text x="'+Math.min(280,Math.max(20,X(i))).toFixed(1)+
  '" y="'+(Y(v)+(above?-6:12)).toFixed(1)+'" text-anchor="middle" '+
  'style="fill:var(--muted)" font-size="9" font-weight="600">'+fm(v)+'</text>';
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
  (mx>0.005?lab(iMx,mx,true):'')+(mn<-0.005?lab(iMn,mn,false):'');
}
document.querySelectorAll('.cvc').forEach(b=>{b.onclick=()=>{
 window._cvz=b.dataset.c;
 document.querySelectorAll('.cvc').forEach(x=>{
  const on=x.dataset.c===window._cvz;
  x.style.background=on?'var(--surface3)':'transparent';
  x.style.borderColor=on?'var(--border2)':'var(--border)';
  x.style.color=on?'var(--text2)':'var(--muted2)';});
 drawSpark();};});
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
 try{if(navigator.setAppBadge){if(nw)navigator.setAppBadge(nw);else if(navigator.clearAppBadge)navigator.clearAppBadge();}}catch(e){}
}
function inboxKind(x){const t=(x.title||'')+' '+(x.body||'');
 if(/signal/i.test(t))return 'sig';if(/trade (termin|closed)/i.test(t))return 'tr';if(/bilan|semaine|your week|daily review/i.test(t))return 'bil';return 'oth';}
function inboxList(){
 const it=window._inbox||[],f=window._ibF||'all',q=(window._ibQ||'').toLowerCase();
 const en=LANG()==='en';
 const ic=k=>k==='bil'?['i-calendar','var(--accent-soft)']:k==='sig'?['i-activity','var(--up)']:k==='tr'?['i-chart','var(--text3)']:['i-bell','var(--warn)'];
 const esc=x=>String(x||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
 const L=it.filter(x=>(f==='all'||inboxKind(x)===f)&&(!q||((x.title||'')+' '+(x.body||'')).toLowerCase().indexOf(q)>=0));
 const el=document.getElementById('ib-list');if(!el)return;
 el.innerHTML=L.length?L.map(x=>{const [n,c]=ic(inboxKind(x));
  return '<div class="srow-ev" style="align-items:flex-start"><div class="evi" style="color:'+c+'"><svg class="ic ic-s"><use href="#'+n+'"/></svg></div>'+
  '<div style="flex:1;min-width:0"><div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline">'+
  '<b style="font-size:.9rem">'+esc(x.title)+'</b><span style="font-size:.7rem;color:var(--muted);white-space:nowrap">'+inboxWhen(x.t)+'</span></div>'+
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
 sheet(h);inboxList();
 const dot=document.getElementById('inbox-dot');if(dot)dot.style.display='none';
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
 let h='<h3>Mes \u00e9tapes</h3><p>'+(n?n+' \u00e9tape'+(n>1?'s':'')+' sur '+BADGES.length+'. Les autres viendront avec le temps.':'Vos premi\u00e8res \u00e9tapes appara\u00eetront ici d\u00e8s que le robot aura agi pour vous.')+'</p>';
 h+='<div class="bdg">'+BADGES.map(([k,l,dsc,ic])=>'<div class="stpi'+(st[k]?'':' off')+'"><div class="stpc"><svg class="ic ic-s"><use href="#'+ic+'"/></svg></div><div style="min-width:0"><b>'+l+'</b><span>'+(st[k]?'le '+fd(st[k]):dsc)+'</span></div></div>').join('')+'</div>';
 h+='<button class="shbtn shghost" onclick="_shDone(1)">Fermer</button>';
 sheet(h);
}
// swipe down on a sheet closes it (only when its content is not scrolled)
(function(){const sh=document.getElementById('sheet');if(!sh)return;let y0=null,dy=0;
 sh.addEventListener('touchstart',e=>{y0=e.touches[0].clientY;dy=0;
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
 const N=await nestFromAdmin();const ch=document.getElementById('acctchip');
 if(N&&N.length&&ch){ch.style.display='inline-flex';document.getElementById('acctchip-n').textContent=N.length;}
}
async function acctSheet(){
 const N=(await nestFromAdmin())||[],d=window._d||{};if(!N.length)return;
 const tb=N.reduce((a,x)=>a+(x.bal||0),0),tt=N.reduce((a,x)=>a+(x.today||0),0);
 const money=v=>(v>=0?'+$':'-$')+Math.abs(v).toFixed(2);
 const st=x=>{const noBot=!x.bot;
  if(noBot)return[x.paused?'manuel':'sans robot','var(--muted)','#4a5a6b'];
  if(x.err)return['probl\u00e8me','var(--down-soft)','var(--down)'];
  if(x.stale)return['hors ligne','var(--warn)','var(--warn)'];
  if(!x.botlive)return['robot arr\u00eat\u00e9','var(--down-soft)','var(--down)'];
  if(x.blocked)return[x.blocked,'var(--warn)','var(--warn)'];
  return x.paused?['manuel','var(--text3)','#8fa1b3']:['auto','var(--up-soft)','var(--up)'];};
 const rows=N.filter(x=>x.tok).map(x=>{const cur=(x.login&&d.acct&&String(x.login)===String(d.acct));const S=st(x);
  const ini=(x.name||'?').trim().split(/\s+/).map(w=>w[0]).join('').slice(0,2).toUpperCase();
  return '<div class="srow" role="button" tabindex="0" onclick="location.href=\\'/'+x.tok+'/\\'" style="'+(cur?'background:rgba(59,130,246,.08);border-radius:12px;':'')+'">'+
   '<div class="sic" style="font-weight:800;font-size:.8rem;color:var(--text2);position:relative">'+ini+
    '<i style="position:absolute;right:-2px;bottom:-2px;width:9px;height:9px;border-radius:50%;background:'+S[2]+';border:2px solid var(--surface)"></i></div>'+
   '<div style="flex:1;min-width:0"><b style="display:flex;align-items:center;gap:6px">'+x.name+(cur?'<svg class="ic ic-s" style="color:var(--accent-soft)"><use href="#i-check"/></svg>':'')+'</b>'+
    (x.note?'<div style="font-size:.74rem;color:var(--warn);line-height:1.35;margin-top:2px">\u270e '+String(x.note).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))+'</div>':'')+
    '<div class="ssub"><span style="color:'+S[1]+';font-weight:700">'+S[0]+'</span>'+(x.login?' \u00b7 '+x.login:'')+(x.pos?' \u00b7 '+x.pos+' en cours':'')+' \u00b7 <span style="color:var(--muted)">'+agoTxt(x.seen)+'</span></div></div>'+
   '<div style="text-align:right;flex:none"><b style="font-variant-numeric:tabular-nums">'+(typeof x.bal==='number'?'$'+x.bal.toFixed(2):'\u2014')+'</b>'+
    '<div style="font-size:.74rem" class="'+sgn(x.today||0)+'">'+(typeof x.today==='number'?money(x.today):'')+'</div></div></div>'+
   '<div style="display:flex;gap:6px;padding:0 0 10px 44px;margin-top:-4px">'+
    '<a href="/'+x.tok+'/chart" onclick="event.stopPropagation()" aria-label="Graphique" style="text-decoration:none;color:var(--text2);border:1px solid var(--border2);background:var(--surface3);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700;display:inline-flex;align-items:center;gap:5px"><svg class="ic ic-s"><use href="#i-chart"/></svg>Graphique</a>'+
    (x.trade?'<button onclick="event.stopPropagation();_shDone(1);nestPause(&#39;'+x.id+'&#39;,&#39;'+(x.paused?'0':'1')+'&#39;)" style="border:1px solid var(--border2);background:var(--surface3);color:var(--text2);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700;display:inline-flex;align-items:center;gap:5px"><svg class="ic ic-s"><use href="#'+(x.paused?'i-bot':'i-pause')+'"/></svg>'+(x.paused?'Reprendre':'Pause')+'</button>':'')+
    '<button onclick="event.stopPropagation();_shDone(1);nestNote(&#39;'+x.id+'&#39;,&#39;'+String(x.name||'').replace(/[&#39;"<>]/g,'')+'&#39;)" aria-label="Note" style="border:1px solid var(--border2);background:var(--surface3);color:var(--text2);border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700">\u270e</button>'+
    '<button onclick="event.stopPropagation();_shDone(1);nestPanic(&#39;'+x.id+'&#39;,&#39;'+String(x.name||'').replace(/[&#39;"<>]/g,'')+'&#39;)" style="border:1px solid rgba(255,92,92,.45);background:rgba(255,92,92,.12);color:#ff8c8c;border-radius:9px;padding:6px 10px;font-size:.74rem;font-weight:700;display:inline-flex;align-items:center;gap:5px"><svg class="ic ic-s"><use href="#i-stop"/></svg>Urgence'+(x.pos?' \u00b7 '+x.pos:'')+'</button>'+
   '</div>';}).join('');
 sheet('<h3>Vos comptes</h3>'+
  '<div style="display:flex;justify-content:space-between;align-items:baseline;padding:4px 2px 10px;border-bottom:1px solid var(--border);margin-bottom:4px">'+
   '<span style="color:var(--muted2);font-size:.84rem">'+N.length+' compte'+(N.length>1?'s':'')+' \u00b7 total</span>'+
   '<span style="text-align:right"><b style="font-size:1.05rem">$'+tb.toFixed(2)+'</b> <span class="'+sgn(tt)+'" style="font-size:.8rem;margin-left:6px">'+money(tt)+' auj.</span></span></div>'+
  '<div style="max-height:56vh;overflow-y:auto;margin:0 -6px;padding:0 6px">'+rows+'</div>'+
  ((function(){let adm=null;try{adm=localStorage.getItem('owl_adm');}catch(e){}
    return (adm&&adm!==B)?'<a class="shbtn shmain" style="display:block;text-align:center;text-decoration:none" href="'+adm+'">Retour \\u00e0 mon compte</a>':'';})())+
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
 const n=C.length;i=Math.max(0,Math.min(n-1,i||0));const c=C[i];
 const dots=C.map((_,k)=>'<i style="display:inline-block;width:'+(k===i?18:6)+'px;height:6px;border-radius:99px;margin:0 2px;background:'+(k===i?'var(--accent)':'var(--border2)')+';transition:width .2s"></i>').join('');
 const last=i===n-1;
 const nb=document.getElementById('notifbtn');const canNotif=!!(nb&&nb.style.display!=='none'&&nb.dataset.on!=='1');
 sheet('<div style="text-align:center;padding:6px 0 2px"><div class="sic" style="margin:0 auto;width:56px;height:56px;border-radius:18px;color:'+c[1]+'"><svg class="ic" style="width:26px;height:26px"><use href="#'+c[0]+'"/></svg></div>'+
  '<h3 style="margin:14px 0 6px">'+c[2]+'</h3><p style="color:var(--text);font-size:.95rem;line-height:1.55">'+c[3]+'</p><div style="margin:6px 0 14px">'+dots+'</div></div>'+
  (last?(canNotif?'<button class="shbtn shmain" onclick="_shDone(1);document.getElementById(&#39;notifbtn&#39;).click();try{localStorage.setItem(&#39;owlTourDone&#39;,&#39;1&#39;)}catch(e){}">Activer les notifications</button>'
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
 if(ev.length<2){el.style.display='none';return;}
 ev.sort((a,b)=>b.t-a.t);
 document.getElementById('tl-lbl').textContent=en?'Your journey':'Votre parcours';
 setH(document.getElementById('tl-list'),'<div style="position:absolute;left:14px;top:12px;bottom:12px;width:2px;background:var(--border2)"></div>'+
  ev.map(e=>'<div style="display:flex;align-items:center;gap:12px;padding:7px 0;position:relative"><div class="evi" style="color:'+e.c+';background:var(--surface);border:1px solid var(--border2);z-index:1"><svg class="ic ic-s"><use href="#'+e.ic+'"/></svg></div>'+
   '<div style="flex:1"><b style="font-size:.9rem">'+e.l+'</b><div style="font-size:.74rem;color:var(--muted)">'+(e.s||'')+'</div></div></div>').join(''));
 el.style.display='block';
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
// 2026-09-27: the daily objective reached -> one calm card, in the phone's clock
function dayDone(d){
 const el=document.getElementById('daydone');if(!el)return;
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
 let title,txt,color='var(--accent-soft)';
 if(P.family){title=en?'Famille':'Famille';txt=en?'Everything is open: manual, automatic, the strategy.':'Tout est ouvert : manuel, automatique, la strat\u00e9gie.';color='var(--warn)';}
 else if(P.strategy){title=en?'Strategy':'Strat\u00e9gie';txt=(en?'Manual + the full view, until ':'Manuel + la vue compl\u00e8te, jusqu\u2019au ')+fd(P.strategy_until)+'.';color='var(--warn)';}
 else if(P.manual){title=en?'Manual':'Manuel';txt=(en?'Signals and the trade tool, until ':'Signaux et outil de trading, jusqu\u2019au ')+fd(P.manual_until)+'.';color='var(--up-soft)';}
 else{title=en?'Observer':'Observateur';txt=en?'You watch. Manual trading and the full view are paid options.':'Vous regardez. Le trading manuel et la vue compl\u00e8te sont des options payantes.';}
 t.textContent=title;sub.textContent=txt;ic.style.color=color;
 const pk=P.packages||{};
 const btn=(k,lab,price,dis,sub2)=>'<button '+(dis?'disabled ':'')+'onclick="buyPkg(&#39;'+k+'&#39;)" style="border:1px solid var(--border2);background:'+(dis?'var(--surface2)':'var(--surface3)')+';color:'+(dis?'var(--muted)':'var(--text2)')+';border-radius:12px;padding:10px 8px;font-size:.84rem;font-weight:700;line-height:1.35">'+lab+'<span style="display:block;font-size:.72rem;font-weight:600;color:var(--muted2)">'+price+(sub2?' \u00b7 '+sub2:'')+'</span></button>';
 const full=(P.seats_left<=0&&!P.manual);
 bt.innerHTML=P.family?'':(btn('manual',(en?'Manual':'Manuel')+(P.manual&&!P.strategy?' \u2713':''),'$'+(pk.manual||{}).usd+' / 30 j',!P.pay_ready||full,full?(en?'full':'complet'):'')+
  btn('strategy',(en?'Strategy':'Strat\u00e9gie')+(P.strategy?' \u2713':''),'$'+(pk.strategy||{}).usd+' / 30 j',!P.pay_ready,''));
 nt.textContent=P.family?'':(P.pay_ready?(en?'Payment in crypto (NOWPayments). Renewing adds 30 days. Manual = one dedicated terminal, '+P.seats_left+' place(s) left.':'Paiement en crypto (NOWPayments). Renouveler ajoute 30 jours. Manuel = un terminal d\u00e9di\u00e9, '+P.seats_left+' place(s) restante(s).')
  :(en?'Payments open soon \u2014 ask Kino for now.':'Paiements bient\u00f4t disponibles \u2014 demandez \u00e0 Kino en attendant.'));
 const mq=document.getElementById('mql5row');if(mq){if(P.mql5_url&&!P.family){mq.style.display='flex';mq.href=P.mql5_url;}else mq.style.display='none';}
 const sr=document.getElementById('stratrow');if(sr)sr.style.display=P.strategy?'flex':'none';
 const pb=document.getElementById('pausebtn');if(pb&&d.pause_locked&&!d.public){const ps=document.getElementById('pause-sub');if(ps&&!P.manual)ps.textContent=en?'Manual trading needs the Manual plan.':'Le trading manuel demande l\u2019abonnement Manuel.';}
}
async function buyPkg(k){
 const en=LANG()==='en';
 const r=await fetch(B+'buy',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'pkg='+encodeURIComponent(k)}).catch(()=>null);
 let j=null;try{j=await r.json();}catch(e){}
 if(!j||!j.ok){toast(j&&j.err==='complet'?(en?'No place left for now.':'Plus de place pour l\u2019instant.'):(j&&j.err==='not ready'?(en?'Payments open soon.':'Paiements bient\u00f4t disponibles.'):(en?'Cannot create the invoice right now.':'Impossible de cr\u00e9er la facture pour l\u2019instant.')),3500);return;}
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
 const v=await sheet('<h3>Paiements &amp; MQL5</h3><p>Cl\u00e9s NOWPayments (compte marchand), secret IPN (m\u00eame valeur que dans NOWPayments \u203a IPN), et le lien du signal MQL5 pour le trading automatique. Laissez vide pour ne pas changer.</p>'+
  '<div style="font-size:.8rem;color:var(--muted2);margin:-4px 0 10px">\u00c9tat : '+(P.np_key_tail?'cl\u00e9 API enregistr\u00e9e (\u2026'+P.np_key_tail+')':'cl\u00e9 API absente')+' \u00b7 secret IPN '+(P.np_secret_set?'enregistr\u00e9':'absent')+(P.np_sandbox?' \u00b7 mode test':'')+'</div>'+
  inp('shnpk','Cl\u00e9 API NOWPayments','', 'password')+inp('shnps','Secret IPN','', 'password')+inp('shmq','https://www.mql5.com/fr/signals/...',d.plan&&d.plan.mql5_url||'')+
  '<label style="display:flex;align-items:center;gap:8px;font-size:.86rem;color:var(--muted2);margin:2px 0 10px"><input id="shsbx" type="checkbox"'+(P.np_sandbox?' checked':'')+'> Mode test (sandbox NOWPayments)</label>'+
  '<button class="shbtn shmain" onclick="_shDone({k:document.getElementById(&#39;shnpk&#39;).value,s:document.getElementById(&#39;shnps&#39;).value,m:document.getElementById(&#39;shmq&#39;).value,b:document.getElementById(&#39;shsbx&#39;).checked})">Enregistrer</button>'+
  '<button class="shbtn shghost" onclick="_shDone(null)">Annuler</button>');
 if(!v)return;
 const pw=await askPwd('Enregistrer ?','Mot de passe ma\u00eetre.','Enregistrer');if(!pw)return;
 let body='pwd='+encodeURIComponent(pw)+'&mql5_url='+encodeURIComponent(v.m||'')+'&np_sandbox='+(v.b?'1':'0');
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
 const v=await sheet('<h3>Lien de contact</h3><p>Montr\u00e9 dans les R\u00e9glages de chaque membre (\u00ab Contacter Kino \u00bb). WhatsApp : https://wa.me/33612345678 \u00b7 Telegram : https://t.me/votrenom \u00b7 ou mailto:</p>'+
  '<input id="shcurl" type="url" placeholder="https://wa.me/..." value="'+String(d.contact_url||'').replace(/"/g,'&quot;')+'" style="width:100%;box-sizing:border-box;border:1px solid var(--border2);background:var(--surface2);color:var(--text);border-radius:12px;padding:12px 14px;font-size:.95rem;margin-bottom:8px">'+
  '<input id="shclbl" type="text" maxlength="60" placeholder="Libell\u00e9 (Contacter Kino)" value="'+String(d.contact_label||'').replace(/"/g,'&quot;')+'" style="width:100%;box-sizing:border-box;border:1px solid var(--border2);background:var(--surface2);color:var(--text);border-radius:12px;padding:12px 14px;font-size:.95rem;margin-bottom:10px">'+
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
    const mvOk=gM?(hasInt?(nb>=1):(mv>=1)):true;
    const k=storm?'nervous'
      :((!gN&&!gM)?'nogate'
      :(nerv_bad?(rv<1.30?'brisk':'nervous')
      :(!mvOk?'none'
      :(hasInt?(ms2.int_state||'ready'):'ready'))));
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
    const cell=(l,v,c,acc)=>'<div style="min-width:0;padding:8px 10px;'+
     'border-radius:12px;background:'+(acc?'rgba(59,130,246,.12)'
      :'var(--tile-bg)')+';border:1px solid '+
     (acc?'rgba(59,130,246,.38)':'var(--tile-bd)')+'">'+
     '<div style="'+NW+'font-size:.58rem;color:'+(acc?'var(--accent-soft)':'var(--muted2)')+
     ';text-transform:uppercase;letter-spacing:.08em">'+l+'</div>'+
     '<b style="display:block;'+NW+'font-size:1rem;margin-top:2px;color:'+
     (c||'var(--text)')+';font-variant-numeric:tabular-nums">'+v+'</b></div>';
    const tcol=ms2.trend===1?'var(--up-soft)':(ms2.trend===-1?'var(--down-soft)':'var(--muted2)');
    const ttxt=ms2.trend===1?'▲ hausse'
     :(ms2.trend===-1?'▼ baisse':'—');
    // Accent = the two figures that DECIDE right now. Which movement rule
    // that is depends on whether there is an internal structure, so the
    // accent moves with it instead of always sitting on the small count
    // (owner 2026-09-18).
    const small=cell('petits mouvements',
     hasInt?(nb+'&thinsp;/&thinsp;1h'):'—',
     hasInt?(aw?'var(--accent-soft)':'var(--muted)'):'var(--muted)',hasInt&&gM);
    const big=cell('grands mouvements',mv+'&thinsp;/&thinsp;2h',
     hasInt?(mv===0?'var(--muted)':'var(--text)')
      :(mv>=1?'var(--accent-soft)':'var(--muted)'),(!hasInt)&&gM);
    // the deciding movement rule first, then nervosity - always a brake
    chips.push(hasInt?small:big);
    chips.push(cell('nervosité vs 24 h',rv.toFixed(2)+'× '+vw[0],
     vw[1],gN||storm));
    // then the context
    chips.push(hasInt?big:small);
    chips.push(cell('sens',ttxt,tcol,false));
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
   setH(document.getElementById('mx-chips'),
    chips.map(c=>c.indexOf('<div')===0?c
     :'<div style="grid-column:1/-1"><span class="mxc">'+c+
      '</span></div>').join(''));
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
      '<div style="background:rgba(255,255,255,.07);border-radius:99px;'+
       'height:7px;overflow:hidden">'+
       '<div style="height:7px;border-radius:99px;width:'+
        jarPct.toFixed(0)+'%;background:linear-gradient(90deg,'+
        '#b8963f,#e8c55a);transition:width .8s"></div>'+
      '</div>'+
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
    lt2.innerHTML='&#128522; Tout va bien &mdash; rien &agrave; '+
     'rattraper.'+(d.ledger.chest>0
     ?'<br>&#128176; Gard&eacute; pour les jours difficiles : '+
      '<b style="color:var(--warn)">$'+d.ledger.chest.toFixed(2)+
      '</b>':'');
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
    dtc.innerHTML='<svg width="16" height="16" viewBox="0 0 36 36" style="flex:none">'+
     '<circle cx="18" cy="18" r="15" fill="none" stroke="rgba(255,255,255,.22)" stroke-width="6"/>'+
     '<circle cx="18" cy="18" r="15" fill="none" stroke="'+(_done?'var(--up)':'var(--warn)')+
     '" stroke-width="6" stroke-linecap="round" stroke-dasharray="94.2" stroke-dashoffset="'+
     _off+'" transform="rotate(-90 18 18)"/></svg>'+
     (_done?'Objectif atteint \\u00b7 $'+_pnl.toFixed(2)
      :'$'+_pnl.toFixed(2)+' / $'+_cap.toFixed(2)+' aujourd\\u2019hui');
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
    (d.real?'R&Eacute;EL':'D&Eacute;MO')+' &middot; '+d.acct);
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
   lb.innerHTML=isPaused
    ?'Mode manuel'
    :'Trading automatique';
   lb.style.color=pauseLocked?'#6f8299':'';
   sb.textContent=pauseLocked
    ?(isPaused?'Mode manuel — seul le proprietaire du compte '+
      'peut lancer l’automatique'
     :'Réservé au proprietaire du compte')
    :(isPaused
      ?'Le robot n\u2019entre pas seul. Touchez pour le lancer.'
      :'Le robot entre seul. Touchez pour repasser en manuel.');
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
  document.getElementById('actcard').style.display=
   d.activation_needed?'block':'none';
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
  t.innerHTML=arw(d.today)+f(d.today);
  t.className='val '+(sgn(d.today));
  const w=document.getElementById('week');
  w.innerHTML=arw(d.week)+f(d.week);
  w.className='val '+(sgn(d.week));
  const dv=d.max_dd_7d.toFixed(0);
  document.getElementById('dd').textContent=(dv==0?'$0':'-$'+dv);
  if(d.month!==undefined){
   const mo=document.getElementById('month');
   mo.innerHTML=arw(d.month)+f(d.month);
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
  drawSpark();drawGoal(d);renderSince(d);checkBadges(d);renderMvM(d);renderTimeline(d);renderEmpty(d);dayDone(d);renderPlan(d);
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
   const tb=d.nest.reduce((a,x)=>a+(x.bal||0),0);
   const tt=d.nest.reduce((a,x)=>a+(x.today||0),0);
   // 2026-09-27: alerts strip + family week bars above the list
   const _al=d.nest.filter(x=>x.err||x.stale||(x.bot&&!x.botlive)||x.blocked);
   const _man=d.nest.filter(x=>!x.bot&&x.paused).length;
   const _alh=_al.length
    ?'<div style="display:flex;align-items:flex-start;gap:10px;padding:10px 12px;border-radius:12px;'+
     'background:rgba(232,197,90,.08);border:1px solid rgba(232,197,90,.28);margin-bottom:10px">'+
     '<div class="evi" style="color:var(--warn);flex:none"><svg class="ic ic-s"><use href="#i-cloud"/></svg></div>'+
     '<div style="flex:1;min-width:0;font-size:.86rem;line-height:1.4"><b>'+_al.length+' compte'+(_al.length>1?'s':'')+' &agrave; surveiller</b><br>'+
     '<span style="color:var(--muted2)">'+_al.map(x=>x.name+' \u00b7 '+(x.err?'probl\u00e8me':x.stale?'hors ligne':x.blocked?x.blocked:'robot arr\u00eat\u00e9')).join(' \u00b7 ')+'</span></div></div>'
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
   const hdr=_alh+_famh+'<div class="row" style="border-bottom:2px solid '+
    '#24344a"><span><b>&#127968; Total famille</b> <span style="'+
    'color:var(--muted);font-size:.75rem">'+d.nest.length+
    ' compte'+(d.nest.length>1?'s':'')+'</span></span>'+
    '<span style="text-align:right"><b>$'+tb.toFixed(2)+'</b>'+
    '<span style="display:block;font-size:.78rem" class="'+
    (sgn(tt))+'">auj. '+(tt>=0?'+$':'-$')+
    Math.abs(tt).toFixed(2)+'</span></span></div>';
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
    return '<div class="row"><span style="display:flex;'+
    'flex-direction:column;gap:3px;min-width:0"><span style="white-space:'+
    'nowrap;overflow:hidden;text-overflow:ellipsis"><span style="display:'+
    'inline-block;width:9px;height:9px;border-radius:50%;background:'+
    dot+';margin-right:8px"></span><b>'+x.name+'</b>'+
    (x.note?'<span style="display:block;font-size:.72rem;color:var(--warn);white-space:normal;margin:2px 0 0 17px">\u270e '+String(x.note).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))+'</span>':'')+
    '<span style="display:block;font-size:.7rem;color:var(--muted);margin:1px 0 0 17px">'+agoTxt(x.seen)+'</span>'+
    '<span style="color:'+stc+';font-size:.7rem"> &middot; '+st+
    '</span></span>'+
    '<span style="font-size:.72rem;color:var(--muted2);white-space:nowrap;'+
    'overflow:hidden;text-overflow:ellipsis">'+
    (x.bot?'&#129302; '+x.bot:'&#8212;')+
    (x.login?' &middot; '+x.login:'')+'</span>'+
    '<span style="font-size:.8rem;color:var(--muted2)">'+
    (x.bal!=null?'$'+x.bal.toFixed(2):'--')+
    (x.today!=null?' &middot; auj. <span class="'+
     (sgn(x.today))+'">'+(x.today>=0?'+$':'-$')+
     Math.abs(x.today).toFixed(2)+'</span>':'')+'</span></span>'+
    '<span style="display:flex;gap:6px">'+
    (x.tok?'<a href="/'+x.tok+'/" target="_blank" '+
    'style="border:1px solid #263341;background:var(--surface);'+
    'color:var(--text2);border-radius:10px;padding:8px 11px;'+
    'font-size:.85rem;text-decoration:none">&#128065;&#65039;'+
    '</a>':'')+
    (x.trade?'<button data-u="'+x.id+'" data-o="'+(x.paused?0:1)+
    '" onclick="nestPause(this.dataset.u,this.dataset.o)" '+
    'style="border:1px solid #263341;background:var(--surface);'+
    'color:var(--text2);border-radius:10px;padding:8px 13px;'+
    'font-size:.85rem">'+
    (x.paused?'&#9654;&#65039;':'&#9208;&#65039;')+'</button>':'')+
    '<button data-u="'+x.id+'" data-n="'+x.name+
    '" onclick="nestPanic(this.dataset.u,this.dataset.n)" '+
    'title="Arret d&rsquo;urgence : tout fermer sur ce compte" '+
    'style="border:1px solid rgba(255,92,92,.45);'+
    'background:rgba(255,92,92,.12);color:#ff8c8c;'+
    'border-radius:10px;padding:8px 11px;font-size:.85rem">'+
    '&#128721;'+(x.pos?' '+x.pos:'')+'</button>'+
    (x.bot?'<button data-u="'+x.id+'" data-n="'+x.name+'" onclick="nestReset(this.dataset.u,this.dataset.n)" '+
    'title="R&eacute;initialiser : le robot repart de z&eacute;ro" style="border:1px solid var(--border2);'+
    'background:var(--surface);color:var(--text2);border-radius:10px;padding:8px 11px;font-size:.85rem">&#8635;</button>':'')+
    '</span></div>';
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
                    d["palier_base"] = round(float(d["balance"]), 2)
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
        if (u.get("id") in ("kino", "std")
                or str(u.get("login")) == str(LOGIN)
                or admin_override):
            d["is_master"] = True
            # v2 Le Nid: one row per member for the master console
            try:
                _rows = []
                try:
                    _notes = json.load(open(NOTES_FILE, encoding="utf-8"))
                except Exception:
                    _notes = {}
                try:
                    _seen = json.load(open(SEEN_FILE, encoding="utf-8"))
                except Exception:
                    _seen = {}
                for x in json.load(open(USERS_FILE, encoding="utf-8")):
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
                        "bal": nd.get("balance"),
                        "today": nd.get("today"),
                        "err": bool(nd.get("error")),
                        "stale": _age > 60, "paused": _pz,
                        "pos": nd.get("open_positions"),
                        "bot": _bot, "botlive": _live, "blocked": _blk,
                        "trade": bool(x.get("trade")
                                      or x.get("id") == "kino"),
                        "days": (nd.get("days") or [])[:7],
                        "note": (_notes.get(x["id"]) or {}).get("text", ""),
                        "seen": _seen.get(x["id"]),
                        "plan": x.get("plan")})
                d["nest"] = _rows
            except Exception:
                pass
        elif not u.get("trade"):
            d["activation_needed"] = True
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
<div class="ft"><b>Connectez votre compte</b>
<span>Un num&eacute;ro de compte MT5 et son mot de passe. Rien &agrave;
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
<button class="bigbtn b1" onclick="show('v-login')">
Se connecter</button>
<a class="bigbtn b2" href="/demo" style="display:block;margin-top:12px;
 text-decoration:none;text-align:center"><svg class="ic"><use href="#i-eye"/></svg> Voir le compte
 d&eacute;mo en direct</a>
<button class="bigbtn b3" id="inst2" onclick="inst2()"
 style="margin-top:4px"><svg class="ic ic-s"><use href="#i-download"/></svg> Installer l&#8217;application</button>
<div style="margin-top:14px;text-align:center;font-size:.8rem;color:var(--muted);
 line-height:1.5">7 jours d&#8217;essai sur un compte d&eacute;mo &mdash;
 argent fictif, vraies performances.</div>
<div id="howto2" style="display:none;margin-top:12px;background:#141c28;
 border:1px solid #1f2c3d;border-radius:14px;padding:14px;
 font-size:.9rem;color:#c6d3df;line-height:1.6;text-align:left">
&#128241; <b>Pour installer :</b><br>
1. Touchez le menu <b>&#8942;</b> en haut &agrave; droite de Chrome<br>
2. Choisissez <b>&laquo; Ajouter &agrave; l&#8217;&eacute;cran
 d&#8217;accueil &raquo;</b><br>
3. L&#8217;ic&ocirc;ne &#129417; appara&icirc;t !</div>
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
 par la famille Kino<br><span style="display:block;margin-top:8px;opacity:.75;line-height:1.5">Vos identifiants servent uniquement &agrave; relier le robot &agrave; votre compte. Ils ne sont jamais partag&eacute;s.</span></div>
</div>

<div class="view" id="v-login">
<a class="back" onclick="show('v-home')">&#8592; Retour</a>
<form class="card" method="POST" action="login">
<h2>Se connecter</h2>
<div style="color:var(--muted);font-size:.85rem">Compte connu : vous entrez
 directement. Nouveau compte : on vous demande juste une info de plus.
</div>
<label for="lg">Num&eacute;ro de compte MT5</label>
<input id="lg" name="login" required inputmode="numeric" autocomplete="username"
 placeholder="12345678">
<label for="pw">Mot de passe du compte</label>
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
<div style="margin-top:12px;font-size:.8rem;color:var(--muted);line-height:1.5">
 Vos identifiants servent uniquement &agrave; relier le robot &agrave; votre
 compte. Ils ne sont jamais partag&eacute;s.</div>
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
            "le mot de passe ne correspond pas. V&eacute;rifiez-le dans "
            "votre application MT5, puis r&eacute;essayez.</p>"
            "<p><a href=\"/\">&larr; R&eacute;essayer</a></p>"))
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
                canon = json.dumps(data, sort_keys=True, separators=(",", ":"))
                good = secret and _hmac.compare_digest(
                    _hmac.new(secret, canon.encode(), _hashlib.sha512).hexdigest(), sig)
                rec = {"t": int(time.time()), "sig_ok": bool(good),
                       "status": data.get("payment_status"), "order": data.get("order_id"),
                       "amount": data.get("price_amount"), "pay_amount": data.get("pay_amount"),
                       "currency": data.get("pay_currency"), "id": data.get("payment_id")}
                if good and data.get("payment_status") in ("finished", "confirmed"):
                    try:
                        _uid, _pkg, _ts = str(data.get("order_id")).split("|")[:3]
                        if _pkg in PACKAGES:
                            paid = float(data.get("price_amount") or 0)
                            if paid + 0.01 >= PACKAGES[_pkg]["usd"] * 0.97:
                                ent_grant(_uid, _pkg, PACKAGES[_pkg]["days"],
                                          f"nowpayments:{data.get('payment_id')}")
                                rec["granted"] = _pkg
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
                ent_family(u["id"], True)      # 2026-09-27: family = everything
                start_copier(u["id"])
                self._send(json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(json.dumps({"ok": False, "err": str(e)}),
                           "application/json")
            return
        if len(_parts) == 2 and _parts[1] == "admin_unlock":
            # 2026-09-23 (owner): "the nid menu must not exist for all but
            # me." Works from ANY account's page (that is the point - the
            # owner should not have to go back to Kino), so this only
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
            self._send(JOIN_PAGE.replace("%%ORIGIN%%", f"{_proto}://{_host}"),
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
            self._send(json.dumps(user_stats(
                user, admin_cookie_ok(self.headers))), "application/json")
        elif sub == "day":
            self._send(json.dumps(day_payload(user)), "application/json")
        elif sub == "trade":
            # 2026-09-27: the story of one closed trade, member-safe words
            try:
                import urllib.parse as _up3
                _q = _up3.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                _t = int(_q.get("t", ["0"])[0])
            except Exception:
                _t = 0
            self._send(json.dumps(trade_story(user, _t)), "application/json")
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
                self._send(_html.replace("%%BUILD%%", _st).replace("%%FULL%%", _full),
                           "text/html; charset=utf-8")
            except Exception:
                self._send(CHART_PAGE, "text/html; charset=utf-8")
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

