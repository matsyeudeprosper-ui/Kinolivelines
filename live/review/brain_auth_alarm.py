"""brain_auth_alarm.py (2026-11-11, owner: "yes alert me by telegram").

11-08..11-11 the claude.exe login expired and the API had no credit: Kino could not think for 3 days and nobody knew.
Every 10 min (Windows task "KinoBrainAuthAlarm") this reads robots/brain_costs.jsonl. If the last 15 min hold >= 3 login /
credit failures and not one success, the owner gets ONE Telegram message (again after 3 h if still down), and one when it is back.
Standalone on purpose: no import of the app, so it still speaks if the app itself is stuck.
"""
import io, json, os, time, urllib.parse, urllib.request

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COSTS = os.path.join(LIVE, "robots", "brain_costs.jsonl")
STATE = os.path.join(LIVE, "review", "brain_auth_alarm_state.json")
OWNER = "kino"   # the owner's Telegram is linked on the "kino" account
WINDOW, MIN_FAILS, REPEAT = 900, 3, 3 * 3600
AUTH_WORDS = ("authenticate", "oauth", "credit balance", "not logged in", "invalid api key", "login",
              "hit your", "usage limit", "5-hour limit", "weekly limit")      # 11-12 02:06: the plan's 5-hour limit, same silence


def _tail(path, nbytes=400000):
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - nbytes))
        return f.read().decode("utf-8", "replace").splitlines()[1:]


def _owner_chat():
    for u in json.load(io.open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8")):
        if u.get("id") == OWNER:
            return u.get("telegram_chat")


def _ctx():
    try:
        import ssl, certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def send(text):
    tok = json.load(io.open(os.path.join(LIVE, "owl_telegram.json"), encoding="utf-8")).get("token")
    cid = _owner_chat()
    if not tok or not cid:
        return False
    data = urllib.parse.urlencode({"chat_id": cid, "text": text}).encode()
    urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, data=data, timeout=20, context=_ctx()).read()
    return True


def check(now=None):
    now = now or time.time()
    fails = oks = 0
    last_err = ""
    for ln in _tail(COSTS):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if not 0 <= now - float(d.get("t") or 0) <= WINDOW or d.get("skip"):
            continue
        err = str(d.get("err") or "")
        if not err:
            oks += 1
        elif any(w in err.lower() for w in AUTH_WORDS):
            fails += 1
            last_err = err
    return fails, oks, last_err


def main():
    try:
        st = json.load(io.open(STATE, encoding="utf-8"))
    except Exception:
        st = {"down": False, "told": 0}
    fails, oks, err = check()
    now = time.time()
    down = fails >= MIN_FAILS and oks == 0
    msg = None
    if down and (not st.get("down") or now - float(st.get("told") or 0) > REPEAT):
        el = err.lower()
        what = ("la limite d'usage Claude est atteinte (elle se remet à zéro toute seule)" if ("limit" in el and "credit" not in el)
                else "plus de crédit sur l'API" if "credit" in el else "la connexion Claude a expiré")
        msg = ("⚠️ Kino ne peut plus réfléchir : %s (%d échecs en 15 min, aucune réussite).\n"
               "À faire : sur le serveur, ouvrir Claude Code et taper /login.\n(%s)" % (what, fails, err[:160]))
        st["told"] = now
    elif st.get("down") and not down and oks > 0:
        msg = "✅ Kino réfléchit de nouveau (%d appels réussis ces 15 dernières minutes)." % oks
    if msg:
        try:
            ok = send(msg)
        except Exception as e:
            ok = False
            msg += " | " + str(e)[:120]
        print(time.strftime("%Y-%m-%d %H:%M:%S"), "SENT" if ok else "SEND FAILED", msg.splitlines()[0])
    if down:
        st["down"] = True
    elif oks > 0:
        st["down"] = False
    io.open(STATE, "w", encoding="utf-8").write(json.dumps(st))


if __name__ == "__main__":
    main()
