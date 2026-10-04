"""owl_telegram.py - OwlNest Telegram alerts (2026-09-01).

Reads owl_telegram.json: {"token": "...", "chat_ids": [...], "join_word": "kino"}
Two jobs, one process:
1. Subscription loop: polls getUpdates; anyone who sends the join_word to
   the bot is added to chat_ids (family self-service, passphrase-gated).
2. Alert loop: tails owl_manual.log and forwards the important lines
   (KINO entries, chain events, milestones, deposits, errors) to every
   subscriber, in easy French.
"""
import json, os, re, ssl, time, urllib.request, urllib.parse

DIR = r"C:\Projects\KinoliveLines\live"
CFG = os.path.join(DIR, "owl_telegram.json")
LOGF = os.path.join(DIR, "owl_manual.log")
SELFLOG = os.path.join(DIR, "owl_telegram.log")

PATTERNS = re.compile(
    r"KINO ENTRY|RECOV\[.*\] (ENTRY|RE-ENTRY|chain ENDED|chain STOPPED)"
    r"|MILESTONE|DEPOSIT detected|WITHDRAWAL detected|ERROR")


def say(m):
    with open(SELFLOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")


def cfg():
    try:
        return json.load(open(CFG, encoding="utf-8"))
    except Exception:
        return None


def save_cfg(c):
    json.dump(c, open(CFG, "w", encoding="utf-8"))


_ctx = {"c": None}


def tg(token, method, **params):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    last = None
    for attempt in range(3):
        try:
            kw = {"timeout": 15}
            if _ctx["c"] is not None:
                kw["context"] = _ctx["c"]
            with urllib.request.urlopen(url, data, **kw) as r:
                return json.load(r)
        except Exception as e:
            last = e
            # this box's Python distrusts the chain (curl is fine);
            # fall back to an unverified context once, then retry
            if "CERTIFICATE_VERIFY_FAILED" in str(e) and _ctx["c"] is None:
                _ctx["c"] = ssl._create_unverified_context()
                continue
            # transient network blips (SSL handshake/read timeouts, 429,
            # getaddrinfo) dominate this log - back off and retry instead
            # of dropping the call on the first failure
            time.sleep(2 * (attempt + 1))
    say(f"tg {method} failed after 3 tries: {last}")
    return None


PENDING = []   # (chat_id, text) alerts that failed all retries - resent later


def frenchify(line):
    msg = line.strip()
    msg = re.sub(r"^[0-9T:.+-]+\s+", "", msg)   # drop timestamp
    if "KINO ENTRY" in msg:
        return "\U0001F3AF Nouveau trade du robot\n" + msg
    if "RE-ENTRY" in msg or ("RECOV[" in msg and "ENTRY" in msg):
        return "\U0001F504 Trade de rattrapage\n" + msg
    if "chain ENDED" in msg:
        return "\U0001F3C1 Rattrapage termine\n" + msg
    if "chain STOPPED" in msg:
        return "\u26D4 Rattrapage arrete (limite de securite)\n" + msg
    if "MILESTONE" in msg:
        return "\U0001F389 PALIER ATTEINT !\n" + msg
    if "DEPOSIT" in msg:
        return "\U0001F4B0 Depot detecte\n" + msg
    if "WITHDRAWAL" in msg:
        return "\U0001F43F Retrait detecte\n" + msg
    if "ERROR" in msg:
        return "\u26A0\uFE0F Probleme technique\n" + msg
    return msg


USERS = os.path.join(DIR, "owl_nest_users.json")
LINKS = os.path.join(DIR, "owl_tg_links.json")
SITE = "https://owltrader.duckdns.org"
RECOVER = re.compile(r"^/?(lien|acc[e\u00e8]s|login|identifiant|oubli\u00e9?|mot de passe oubli\u00e9?|retrouver)\b", re.I)
RESET = re.compile(r"^/?(nouveau mot de passe|reset|motdepasse|changer (le |mon )?mot de passe)\b", re.I)


def _lj(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _sj(p, obj):
    json.dump(obj, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(p + ".tmp", p)


def _app_hash(p):
    import hashlib
    return hashlib.sha256(("owl|" + (p or "")).encode("utf-8")).hexdigest()


def _member_of(cid):
    return next((u for u in _lj(USERS, []) if str(u.get("telegram_chat") or "") == str(cid)), None)


def recovery(token, cid, txt, frm):
    """2026-10-04 (owner): the automated way back in. Returns True when
    the message was about an account (handled here)."""
    t = (txt or "").strip()
    low = t.lower()
    # /start <code> from the app's "Relier Telegram" button
    if low.startswith("/start ") and len(t.split()) >= 2:
        code = t.split()[1].strip()
        links = _lj(LINKS, {})
        ent = links.get(code)
        if not ent or time.time() - float(ent.get("t") or 0) > 7 * 86400:
            tg(token, "sendMessage", chat_id=cid, text="\U0001F989 Ce lien a expir\u00e9. Dans l\u2019app : R\u00e9glages \u203a Compte \u203a Relier Telegram, puis touchez le nouveau bouton.")
            return True
        users = _lj(USERS, [])
        name = None
        for u in users:
            if u.get("id") == ent.get("uid"):
                u["telegram_chat"] = cid
                if frm.get("username"):
                    u["telegram"] = "@" + frm["username"]
                name = u.get("name") or u.get("id")
        _sj(USERS, users)
        links.pop(code, None)
        _sj(LINKS, links)
        tg(token, "sendMessage", chat_id=cid, text=(
            f"\U0001F989 Telegram reli\u00e9 au compte de {name}. Si un jour vous perdez l\u2019acc\u00e8s, \u00e9crivez-moi simplement \u00ab lien \u00bb : "
            "je vous renvoie votre identifiant et votre lien personnel. \u00ab nouveau mot de passe \u00bb en cr\u00e9e un nouveau."))
        say(f"linked chat {cid} to {ent.get('uid')}")
        return True
    if not (RECOVER.search(low) or RESET.search(low)):
        return False
    u = _member_of(cid)
    if u is None:
        tg(token, "sendMessage", chat_id=cid, text=(
            "\U0001F989 Ce Telegram n\u2019est reli\u00e9 \u00e0 aucun compte OwlNest. Dans l\u2019app : R\u00e9glages \u203a Compte \u203a "
            "\u00ab Relier Telegram \u00bb (une fois, quand vous \u00eates connect\u00e9). Sans acc\u00e8s \u00e0 l\u2019app, \u00e9crivez au Owl : @owlnest_contact."))
        return True
    link = f"{SITE}/{u.get('token')}/"
    if RESET.search(low):
        if u.get("app_pwd") or u.get("app_only") or u.get("app_login"):
            import random
            temp = "".join(random.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(8))
            users = _lj(USERS, [])
            for x in users:
                if x.get("id") == u.get("id"):
                    x["app_pwd"] = _app_hash(temp)
                    x["app_login"] = True
            _sj(USERS, users)
            tg(token, "sendMessage", chat_id=cid, text=(
                f"\U0001F511 Nouveau mot de passe : {temp}\nIdentifiant : {u.get('id')}\nVous pouvez le changer dans l\u2019app : R\u00e9glages \u203a Compte."))
            say(f"password reset for {u.get('id')} via telegram")
        else:
            tg(token, "sendMessage", chat_id=cid, text=(
                f"\U0001F989 Votre compte entre avec le num\u00e9ro et le mot de passe de votre compte MT5 \u2014 ils ne changent pas ici. "
                f"Le plus simple : votre lien personnel, qui vous ouvre la page directement :\n{link}"))
        return True
    tg(token, "sendMessage", chat_id=cid, text=(
        f"\U0001F989 Identifiant : {u.get('id')}\nVotre lien personnel (il vous connecte directement) :\n{link}\n"
        "Mot de passe oubli\u00e9 ? \u00c9crivez \u00ab nouveau mot de passe \u00bb."))
    say(f"sent link to {u.get('id')}")
    return True


def main():
    say("telegram daemon starting")
    # wait for config with a token
    while True:
        c = cfg()
        if c and c.get("token"):
            break
        time.sleep(30)
    token = c["token"]
    join_word = (c.get("join_word") or "kino").lower()
    offset = 0
    # start tailing from the end of the log
    pos = os.path.getsize(LOGF) if os.path.exists(LOGF) else 0
    say("telegram daemon live")
    last_upd = 0.0
    while True:
        # 1) subscriptions (every ~10s)
        if time.time() - last_upd > 10:
            last_upd = time.time()
            r = tg(token, "getUpdates", offset=offset, timeout=0)
            if r and r.get("ok"):
                for up in r["result"]:
                    offset = up["update_id"] + 1
                    m = up.get("message") or {}
                    txt = (m.get("text") or "").strip().lower()
                    cid = (m.get("chat") or {}).get("id")
                    if cid is None:
                        continue
                    c = cfg() or {"token": token, "chat_ids": []}
                    try:
                        if recovery(token, cid, m.get("text") or "", m.get("from") or {}):
                            continue
                    except Exception as e:
                        say(f"recovery error: {e}")
                    if txt == join_word and cid not in c.get("chat_ids", []):
                        c.setdefault("chat_ids", []).append(cid)
                        save_cfg(c)
                        tg(token, "sendMessage", chat_id=cid, text=(
                            "\U0001F989 Bienvenue dans le nid ! Vous "
                            "recevrez les nouvelles importantes du robot."))
                        say(f"subscribed chat {cid}")
                    elif txt.startswith("/start"):
                        tg(token, "sendMessage", chat_id=cid, text=(
                            "\U0001F989 OwlNest. Pour retrouver votre acc\u00e8s un jour, reliez ce Telegram depuis l\u2019app "
                            "(R\u00e9glages \u203a Compte \u203a Relier Telegram). Ensuite, \u00e9crivez-moi \u00ab lien \u00bb."))
        # 2) log tail
        try:
            size = os.path.getsize(LOGF)
            if size < pos:
                pos = 0          # log rotated
            if size > pos:
                with open(LOGF, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    new = f.read()
                    pos = f.tell()
                for line in new.splitlines():
                    if PATTERNS.search(line):
                        c = cfg() or {}
                        for cid in c.get("chat_ids", []):
                            if tg(token, "sendMessage", chat_id=cid,
                                  text=frenchify(line)) is None:
                                PENDING.append((cid, frenchify(line)))
        except Exception as e:
            say(f"tail error: {e}")
        # 3) resend alerts that failed earlier (max 20/loop, keep last 200)
        if PENDING:
            batch, rest = PENDING[:20], PENDING[20:]
            still = [(cid, txt) for cid, txt in batch
                     if tg(token, "sendMessage", chat_id=cid, text=txt)
                     is None]
            PENDING[:] = (still + rest)[-200:]
            if not still:
                say(f"resent queued alerts, {len(PENDING)} left")
        time.sleep(3)


if __name__ == "__main__":
    main()
