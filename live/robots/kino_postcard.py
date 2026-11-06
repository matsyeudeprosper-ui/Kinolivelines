"""kino_postcard.py (2026-11-06, owner: "that postcard is interesting" / opened Merci Facteur PRO, keys given).

Real postcards through La Poste (Merci Facteur PRO API, v1.2) for the best leads who did not open their email:
front = their site on a phone (kino_media.shot), back = a short personal note + a QR code to their counted preview link.

Every card is APPROVED by Matsy first (he gets the front, the back, the address and the price) - nothing is posted on Kino's word
alone. A weekly budget caps it. Keys: C:\\ProgramData\\kino_secret\\merci_facteur.json (admins only).

token()                -> access token (cached until it expires)
price()                -> {"ok", "ht"} a naked postcard to France
send(card)             -> {"ok", "id"} posts one card (only called after approval)
"""
import base64, hashlib, hmac, json, os, threading, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = r"C:\ProgramData\kino_secret\merci_facteur.json"
STATE = os.path.join(HERE, "kino_postcard.json")
LOG = os.path.join(HERE, "kino_postcard.log")
API = "https://www.merci-facteur.com/api/1.2/prod/service/"
EMAIL = "kinoverse26@gmail.com"
SENDER = {"civilite": "", "nom": "Kinoverse", "prenom": "", "societe": "Kinoverse", "adresse1": "9 B Bd des Coquibus",
          "adresse2": "", "adresse3": "", "cp": "91000", "ville": "Évry-Courcouronnes", "pays": "france", "phone": "", "email": EMAIL}
WEEK_MAX = 5
_LK = threading.Lock()


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _j(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _w(p, d):
    tmp = p + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _ip():
    st = _j(STATE, {})
    if st.get("ip") and time.time() - float(st.get("ip_t") or 0) < 86400:
        return st["ip"]
    ip = urllib.request.urlopen("https://api.ipify.org", timeout=15).read().decode().strip()
    st.update(ip=ip, ip_t=time.time())
    _w(STATE, st)
    return ip


def token(force=False):
    with _LK:
        st = _j(STATE, {})
        if not force and st.get("token") and float(st.get("expire") or 0) > time.time() + 600:
            return st["token"]
        k = _j(KEYS, {})
        ts = str(int(time.time()))
        sig = hmac.new(k["secret"].encode(), (k["service_id"] + ts).encode(), hashlib.sha256).hexdigest()
        req = urllib.request.Request(API + "getToken", data=urllib.parse.urlencode({"timeLimit": 30}).encode(), method="POST")
        for h, v in (("ww-service-id", k["service_id"]), ("ww-service-signature", sig), ("ww-timestamp", ts), ("ww-authorized-ip", _ip())):
            req.add_header(h, v)
        try:
            j = json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as e:
            raise RuntimeError("getToken %s %s" % (e.code, e.read()[:300].decode("utf-8", "replace")))
        if not j.get("success"):
            raise RuntimeError("getToken refused: %s" % j.get("error"))
        st = _j(STATE, {})
        st.update(token=j["token"], expire=j.get("expire"))
        _w(STATE, st)
        _log("TOKEN ok until %s" % time.strftime("%Y-%m-%d", time.gmtime(float(j.get("expire") or 0))))
        return j["token"]


def _call(method, op, params=None, form=None):
    k = _j(KEYS, {})
    url = API + op + (("?" + urllib.parse.urlencode(params, doseq=True)) if params else "")
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode() if form is not None else None, method=method)
    req.add_header("ww-service-id", k["service_id"])
    req.add_header("ww-access-token", token())
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        return {"success": False, "error": "%s %s" % (e.code, e.read()[:400].decode("utf-8", "replace"))}


def user_id():
    st = _j(STATE, {})
    if st.get("idUser"):
        return st["idUser"]
    j = _call("GET", "getUserId", {"emailUser": EMAIL})
    uid = j.get("user_id") or j.get("idUser") or j.get("id")
    if uid:
        st = _j(STATE, {})
        st["idUser"] = uid
        _w(STATE, st)
    return uid or j


def price():
    j = _call("GET", "getPostagePrice", {"modeEnvoi": "normal", "paysDestinataire[]": "france", "cardFormat": "naked-postcard",
                                         "cardPapier": "classic", "cardCoin": "carre", "letterPageNumber": 0, "photoNumber": 0})
    return j


def send(front_jpg, back_jpg, dest, designation=""):
    """posts ONE card - only after Matsy approved it (the approval step calls this)"""
    st = _j(STATE, {})
    wk = time.strftime("%G-%V", time.gmtime())
    sent = [x for x in st.get("sent") or [] if x.get("week") == wk]
    if len(sent) >= WEEK_MAX:
        return {"ok": False, "err": "weekly budget reached (%d cards)" % WEEK_MAX}
    b64 = lambda p: base64.b64encode(open(p, "rb").read()).decode()
    content = {"letter": "", "photo": "", "card": {"format": "naked-postcard", "coin": "carre", "papier": "classic",
                                                   "visuel": {"type": "base64", "value": b64(front_jpg)},
                                                   "text": {"type": "base64", "value": b64(back_jpg)}}}
    form = {"idUser": user_id(), "modeEnvoi": "normal", "adress": json.dumps({"exp": SENDER, "dest": [dest]}, ensure_ascii=False),
            "content": json.dumps(content), "designation": str(designation)[:50]}
    j = _call("POST", "sendCourrier", form=form)
    _log("SEND %s -> %s" % (designation, json.dumps(j)[:300]))
    if j.get("success"):
        st = _j(STATE, {})
        st.setdefault("sent", []).append({"t": time.time(), "week": wk, "to": dest.get("societe") or dest.get("nom"), "res": j})
        _w(STATE, st)
        return {"ok": True, "res": j}
    return {"ok": False, "err": str(j.get("error"))[:300]}
