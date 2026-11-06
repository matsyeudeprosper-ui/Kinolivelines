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


def _font(size, bold=False, italic=False, script=False):
    from PIL import ImageFont
    names = (["segoesc.ttf", "segoepr.ttf"] if script else []) + [("segoeuib.ttf" if bold else "segoeuii.ttf" if italic else "segoeui.ttf"), "arial.ttf"]
    for n in names:
        try:
            return ImageFont.truetype(os.path.join(r"C:\Windows\Fonts", n), size)
        except Exception:
            pass


def _wrap(text, width):
    out = []
    for para in str(text).split("\n"):
        cur = ""
        for w in para.split():
            if len(cur) + len(w) + 1 > width:
                out.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        out.append(cur)
    return out


def make(name, place_line, preview_url, qr_url, message, slug):
    """front: their own preview on a phone + their name; back (left half only): Kino's note and the QR code to the counted link"""
    import qrcode
    from PIL import Image, ImageDraw, ImageFilter
    import kino_media as KMD
    W, H = 1772, 1240
    sh = KMD.shot(preview_url, "card-" + slug, "x")
    if not sh.get("ok"):
        return None, "could not capture their preview (%s)" % sh.get("err")
    phone = Image.open(sh["path"]).convert("RGB").crop((955, 66, 1362, 834))
    front = Image.new("RGB", (W, H), (16, 18, 24))
    d = ImageDraw.Draw(front)
    for y in range(H):
        c = int(16 + 22 * (1 - abs(y - H / 2) / (H / 2)))
        d.line([(0, y), (W, y)], fill=(c + 6, c + 3, c))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W - 1050, 80, W - 150, 1160), fill=(201, 166, 92, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    front.paste(glow, (0, 0), glow)
    ph = phone.resize((int(phone.width * 1.42), int(phone.height * 1.42)))
    px, py = W - ph.width - 150, (H - ph.height) // 2
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((px + 30, py + 40, px + ph.width + 40, py + ph.height + 50), radius=70, fill=(0, 0, 0, 170))
    shadow = shadow.filter(ImageFilter.GaussianBlur(40))
    front.paste(shadow, (0, 0), shadow)
    front.paste(ph, (px, py))
    d = ImageDraw.Draw(front)
    nm = _wrap(name, 22)[:2]
    d.text((120, 300), "Votre nouveau site,", font=_font(84, True), fill=(244, 240, 232))
    y = 400
    for ln in nm:
        d.text((120, y), ln, font=_font(84, True), fill=(212, 175, 104))
        y += 100
    d.text((124, y + 40), str(place_line)[:44], font=_font(44), fill=(196, 196, 204))
    d.text((124, y + 110), "Déjà prêt. Il ne manque que votre « oui ».", font=_font(44), fill=(196, 196, 204))
    d.text((124, 1060), "Kinoverse", font=_font(40, True), fill=(160, 170, 255))
    d.text((124, 1112), "sites & employés IA pour les commerces", font=_font(32), fill=(150, 150, 160))
    back = Image.new("RGB", (W, H), (251, 249, 244))
    d = ImageDraw.Draw(back)
    y = 100
    for ln in _wrap(message, 42)[:13]:
        d.text((100, y), ln, font=_font(36), fill=(40, 40, 48))
        y += 47
    d.text((100, y + 4), "Kino", font=_font(64, script=True), fill=(60, 70, 150))
    d.text((310, y + 38), "assistant IA de Kinoverse", font=_font(28, italic=True), fill=(110, 110, 120))
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(qr_url)
    qr.make(fit=True)
    back.paste(qr.make_image(fill_color=(30, 30, 40), back_color=(251, 249, 244)).convert("RGB").resize((250, 250)), (100, H - 320))
    d.text((380, H - 270), "Votre aperçu", font=_font(38, True), fill=(40, 40, 48))
    d.text((380, H - 220), "scannez avec l'appareil photo", font=_font(30), fill=(110, 110, 120))
    d.text((380, H - 180), "de votre téléphone", font=_font(30), fill=(110, 110, 120))
    d.text((100, H - 60), "Kinoverse · 9 B Bd des Coquibus, 91000 Évry · STOP : kinoverse26@gmail.com", font=_font(20), fill=(130, 130, 140))
    out = r"C:\KinoWorld\media"
    f, b = os.path.join(out, "carte_%s_recto.jpg" % slug), os.path.join(out, "carte_%s_verso.jpg" % slug)
    front.save(f, quality=92)
    back.save(b, quality=92)
    return (f, b), None


CARD_EUR = 2.30


def card_for(prospect_ref, message, street, cp, city, dry=False):
    """2026-11-06 (owner: "when it comes from him we don't need confirmation"): Kino posts a card to a lead, within his spending
    rules (kino_spend) - Matsy is told after, not asked before"""
    import re as _re
    import kino_sales as KS
    import kino_spend as KSP
    p = KS.find(prospect_ref)
    if not p:
        return "no prospect called %s" % prospect_ref
    if not p.get("preview"):
        return "%s has no preview yet - the card shows their own site, build it first" % p["name"]
    if not (_re.match(r"^\d{5}$", str(cp or "").strip()) and str(street or "").strip() and str(city or "").strip()):
        return "a card needs their full postal address: street, a 5-digit postcode, city (from their site or listing)"
    if len(str(message or "").strip()) < 80:
        return "write them a real, personal note (a few lines, in French) - it is printed on the back"
    if any(x.get("to") == p["name"] for x in _j(STATE, {}).get("sent") or []):
        return "%s already got a card" % p["name"]
    ok, why = KSP.check(CARD_EUR, "postage", "postcard to %s" % p["name"])
    if not ok:
        return "no card: " + why
    slug = KS._slug(p["name"])
    files, err = make(p["name"], "%s, %s" % (str(street).strip()[:30], city), p["preview"], KS.tracked(p) + "?src=carte",
                      str(message).strip(), slug)
    if err:
        return err
    if dry:
        return "card made (not posted): %s and %s" % files
    dest = {"civilite": "", "nom": "", "prenom": "", "societe": p["name"][:38], "adresse1": str(street).strip()[:38], "adresse2": "",
            "adresse3": "", "cp": str(cp).strip(), "ville": str(city).strip()[:32], "pays": "france", "phone": "", "email": "",
            "consent": 0, "reference": p["id"]}
    r = send(files[0], files[1], dest, "Kinoverse - %s" % p["name"][:30])
    if not r.get("ok"):
        return "the card was not posted: %s" % r.get("err")
    KSP.record(CARD_EUR, "postage", "postcard to %s (%s)" % (p["name"], city), ref=p["id"])
    KS.prospect(p["name"], key=p["key"], notes=(p.get("notes") or "") + " | %s: POSTCARD sent to %s, %s %s" % (
        time.strftime("%d/%m"), street, cp, city))
    return "card posted to %s (%s %s) - it arrives in 2-4 days; its QR code is counted (src=carte)" % (p["name"], cp, city)


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
