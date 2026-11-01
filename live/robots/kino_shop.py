"""kino_shop.py (2026-11-01, owner: "do all 3" - his shop).

Things Kino makes and sells himself, on his own site https://kino.owltrader.duckdns.org/shop:
  - he adds a product with the 'shop' action: title, price, description, and the file it delivers (in C:\\KinoWorld\\shop).
    Its public text is read first by the same second mind as his posts.
  - a buyer clicks Buy -> /buy/<id>: a fresh NOWPayments invoice on the owner's account (kino_pay.create) -> they pay
  - NOWPayments sends them back to /got/<ref>/<token>: once the payment is confirmed (the IPN marks it paid), the file is
    delivered from his shop folder; before that the page says to wait a few minutes.
  The money is split by kino_wallet like any of his earnings; he is told of every sale.
Guards: 30 buy clicks a day in all, 3 an hour per visitor; files only from C:\\KinoWorld\\shop, 20 MB at most.
Store robots/kino_shop.json.
"""
import hashlib, hmac, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_shop.json")
SHOP_DIR = r"C:\KinoWorld\shop"
SECRET = r"C:\ProgramData\kino_secret\fedi_key.pem"      # any admin-only secret works as the HMAC key for delivery links
BUYS_DAY, BUYS_HOUR_IP = 30, 3
_LK = threading.Lock()
_IP = {}


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"products": [], "sales": []}


def _save(d):
    tmp = STORE + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, STORE)


def _inside(path):
    p = os.path.realpath(os.path.join(SHOP_DIR, os.path.basename(str(path or ""))) if not os.path.isabs(str(path or "")) else str(path))
    return p if p.lower().startswith(os.path.realpath(SHOP_DIR).lower() + os.sep) and os.path.isfile(p) else None


def _token(ref):
    k = open(SECRET, "rb").read()
    return hmac.new(k, ref.encode(), hashlib.sha256).hexdigest()[:20]


BUYER = """You are a skeptical trader with a little money to spend, looking at a product an AI named Kino wants to sell you. You
see its title, price, description and the start of the file you would get. Would you really pay that price for it? Judge
like a buyer: is it worth more to me than it costs - enough data, a real answer, something I can use or reuse, clearly
better than what I find free in ten minutes? Honest AI authorship is fine; say no only for lack of value. If no, say what
would make you buy (concrete: more data, more markets, a tool not just a report, a lower price...).
JSON only: {"buy": true or false, "why": "one sentence", "would_buy_if": "what is missing (empty if buy)"}"""


def buyer_view(W, title, price, about, sample, log=None):
    """a buyer's eye on a product before it is listed -> (buy, why, missing)"""
    try:
        j = W.ask_json(BUYER, "TITLE: %s\nPRICE: %.2f $\nDESCRIPTION: %s\n\nTHE FILE YOU GET (start):\n%s" % (
            title, price, about, sample[:6000]), models=("sonnet",), timeout=120, log=log, warm=False)
    except Exception:
        return True, "", ""
    if not isinstance(j, dict):
        return True, "", ""
    return bool(j.get("buy")), str(j.get("why") or "")[:300], str(j.get("would_buy_if") or "")[:400]


def act(W, j, log=None):
    """his 'shop' action: op add (title, price, about, file) | remove (id) | list"""
    op = str(j.get("op") or "add").lower()
    if op == "list":
        P = [p for p in _load()["products"] if p.get("on")]
        return "your shop: " + (" | ".join("%s %s %.2f $ (%s, sold %d)" % (p["id"], p["title"], p["price"], p["file"], p.get("sold", 0)) for p in P) or "empty") + \
               " - https://kino.owltrader.duckdns.org/shop"
    if op == "remove":
        with _LK:
            d = _load()
            p = next((x for x in d["products"] if x["id"] == j.get("id")), None)
            if not p:
                return "no product %s" % j.get("id")
            p["on"] = False
            _save(d)
        return "removed %s from your shop" % p["id"]
    title = str(j.get("title") or "").strip()[:100]
    about = str(j.get("about") or j.get("text") or "").strip()[:1200]
    try:
        price = round(float(j.get("price")), 2)
    except Exception:
        return "a product needs a price in dollars"
    if not title or len(about) < 40 or not 1 <= price <= 500:
        return "a product needs a title, a description (a few sentences) and a price between 1 and 500 $"
    f = _inside(j.get("file") or j.get("path"))
    if not f:
        return "the file to deliver must be in C:\\KinoWorld\\shop (write it there first)"
    if os.path.getsize(f) > 20_000_000:
        return "the file is larger than 20 MB"
    # 2026-11-01 (owner: "people won't be buying from that"): before it goes on sale, a buyer looks at it
    ok_, why_, miss_ = buyer_view(W, title, price, about, open(f, "rb").read(6000).decode("utf-8", "replace"), log)
    if not ok_:
        try:
            import kino_inner as KI
            KI.feel("stung", 0.35, why="a buyer would not pay for \"%s\": %s" % (title, why_))
        except Exception:
            pass
        return "not listed - a buyer would not pay %.2f $ for it yet: %s. They would buy if: %s. Make it better, then add it again." % (
            price, why_, miss_)
    import kino_post as KP
    no = KP._gate(W, "shop", title, "PRODUCT FOR SALE: %s - %.2f $\n%s\n\n(the file it delivers starts with:)\n%s" % (
        title, price, about, open(f, "rb").read(3000).decode("utf-8", "replace")), log)
    if no:
        return no
    import kino_github as KG
    if any(s.encode() in open(f, "rb").read() for s in KG._secrets()):
        return "not added - the file contains one of your secrets"
    with _LK:
        d = _load()
        pid = "p%d" % (len(d["products"]) + 1)
        # what buyers get is the file as it was checked: a copy out of his world (he changes it -> a new product)
        import kino_github as KG2, shutil
        snap = os.path.join(KG2._stage_root(), "shop", "%s_%s" % (pid, os.path.basename(f)))
        os.makedirs(os.path.dirname(snap), exist_ok=True)
        shutil.copyfile(f, snap)
        d["products"].append({"id": pid, "t": time.time(), "title": title, "about": about, "price": price,
                              "file": os.path.basename(f), "snap": snap, "on": True, "sold": 0})
        _save(d)
    KP._record("shop", "%s - %.2f $" % (title, price), True, "", "https://kino.owltrader.duckdns.org/shop")
    return "in your shop: %s at %.2f $ - https://kino.owltrader.duckdns.org/shop (buy link: https://kino.owltrader.duckdns.org/buy/%s)" % (
        title, price, pid)


def buy(pid, ip):
    """a visitor clicks Buy -> the invoice url, or (None, reason)"""
    d = _load()
    p = next((x for x in d["products"] if x["id"] == pid and x.get("on")), None)
    if not p:
        return None, "This item is no longer for sale."
    now = time.time()
    hits = [t for t in _IP.get(ip, []) if now - t < 3600]
    if len(hits) >= BUYS_HOUR_IP:
        return None, "Too many tries - please come back in an hour."
    _IP[ip] = hits + [now]
    import kino_pay as KPY
    try:
        ref, url = KPY.create(p["price"], "shop: " + p["title"], "", per_day=BUYS_DAY, kind="shop",
                              success_url=lambda r: "https://kino.owltrader.duckdns.org/got/%s/%s" % (r, _token(r)))
    except ValueError as e:
        return None, "Sorry, the shop can't take a payment right now (%s)." % e
    with _LK:
        d = _load()
        d["sales"].append({"ref": ref, "pid": pid, "t": now})
        d["sales"] = d["sales"][-500:]
        _save(d)
    return url, ""


def product(pid):
    return next((x for x in _load()["products"] if x["id"] == pid and x.get("on")), None)


def _ip_ok(ip):
    now = time.time()
    hits = [t for t in _IP.get(ip, []) if now - t < 3600]
    if len(hits) >= BUYS_HOUR_IP:
        return False
    _IP[ip] = hits + [now]
    return True


def buy_paypal(pid, ip):
    """a PayPal order -> (ref, token) or (None, reason)"""
    p = product(pid)
    if not p:
        return None, "This item is no longer for sale."
    if not _ip_ok(ip):
        return None, "Too many tries - please come back in an hour."
    import kino_pay as KPY
    ref = KPY.manual(p["price"], "shop: " + p["title"], kind="shop", method="PayPal")
    with _LK:
        d = _load()
        d["sales"].append({"ref": ref, "pid": pid, "t": time.time(), "method": "paypal"})
        d["sales"] = d["sales"][-500:]
        _save(d)
    return ref, _token(ref)


def tip_crypto(amount, ip):
    if not _ip_ok(ip):
        return None, "Too many tries - please come back in an hour."
    import kino_pay as KPY
    try:
        ref, url = KPY.create(amount, "a tip for Kino", "", kind="tip", per_day=30,
                              success_url="https://kino.owltrader.duckdns.org/thanks")
    except ValueError as e:
        return None, str(e)
    return url, ""


def tip_paypal_claim(amount, name, ip):
    if not _ip_ok(ip):
        return False
    import kino_pay as KPY
    try:
        ref = KPY.manual(float(amount), "a PayPal tip%s" % ((" from " + str(name)[:60]) if name else ""), kind="tip", method="PayPal")
    except Exception:
        return False
    return KPY.claim(ref, "")


def got(ref, token):
    """the buyer comes back -> (file path, product) when paid; (None, product or None) otherwise"""
    if not re.fullmatch(r"[0-9a-f]{10}", ref or "") or not hmac.compare_digest(_token(ref), str(token or "")):
        return None, None
    d = _load()
    s = next((x for x in d["sales"] if x["ref"] == ref), None)
    if not s:
        return None, None
    p = next((x for x in d["products"] if x["id"] == s["pid"]), None)
    import kino_pay as KPY
    if KPY.status_of(ref) != "paid":
        return None, p
    if not s.get("counted"):
        with _LK:
            d = _load()
            s2 = next((x for x in d["sales"] if x["ref"] == ref), None)
            p2 = next((x for x in d["products"] if x["id"] == s2["pid"]), None)
            s2["counted"] = True
            if p2:
                p2["sold"] = int(p2.get("sold") or 0) + 1
            _save(d)
    f = (p or {}).get("snap")
    return (f if f and os.path.isfile(f) else None), p


def products():
    return [p for p in _load()["products"] if p.get("on")]
