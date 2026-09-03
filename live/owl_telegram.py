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
                    if txt == join_word and cid not in c.get("chat_ids", []):
                        c.setdefault("chat_ids", []).append(cid)
                        save_cfg(c)
                        tg(token, "sendMessage", chat_id=cid, text=(
                            "\U0001F989 Bienvenue dans le nid ! Vous "
                            "recevrez les nouvelles importantes du robot."))
                        say(f"subscribed chat {cid}")
                    elif txt.startswith("/start"):
                        tg(token, "sendMessage", chat_id=cid, text=(
                            "\U0001F989 OwlNest. Envoyez le mot de passe "
                            "pour vous abonner aux alertes."))
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
