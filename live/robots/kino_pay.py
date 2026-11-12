"""kino_pay.py (2026-11-01, owner: "Kino should look for any way possible to make money ... let me use my NOWPayments account
to collect money whenever necessary").

Kino can ASK to be paid, never take or move money: invoice() creates a NOWPayments invoice on the owner's account (the same key
the app uses for the voice packs) and gives him the payment link to put in a reply, a post, an email or a gig. When it is paid,
the app's IPN (/np_ipn, signature checked there) calls paid(): the money is recorded and he is told. The money lands in the
owner's NOWPayments balance - Kino has no payout, no withdrawal, no card.

robots/kino_earnings.json: every invoice (what, for whom, amount, link, status) - shown on his world page.
"""
import json, os, re, threading, time, urllib.request, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_earnings.json")
CONFIG = os.path.join(os.path.dirname(HERE), "owl_nest_config.json")
MAX_USD = 1000
PER_DAY = 10
_LK = threading.Lock()


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"invoices": []}


def _save(d):
    tmp = STORE + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, STORE)


def _cfg():
    try:
        return json.load(open(CONFIG, encoding="utf-8"))
    except Exception:
        return {}


def create(amount, what, payer="", success_url=None, kind="link", per_day=PER_DAY, ref=None, currency="usd"):
    """one NOWPayments invoice on the owner's account -> (ref, url) or raises ValueError with a reason for him"""
    try:
        amount = round(float(amount), 2)
    except Exception:
        raise ValueError("an invoice needs an amount in dollars")
    if not 1 <= amount <= MAX_USD:
        raise ValueError("an invoice is between 1 and %d dollars" % MAX_USD)
    what = str(what or "").strip()[:150]
    if not what:
        raise ValueError("say what the payment is for")
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if sum(1 for x in _load()["invoices"] if x.get("day") == day and x.get("kind", "link") == kind) >= per_day:
        raise ValueError("no more invoices of this kind today (%d a day)" % per_day)
    c = _cfg()
    if not c.get("np_api_key"):
        raise ValueError("the payment account is not set up")
    api = "https://api-sandbox.nowpayments.io" if c.get("np_sandbox") else "https://api.nowpayments.io"
    origin = c.get("public_origin") or "https://owltrader.duckdns.org"
    _given = ref                                 # 2026-11-08: a Kino Chat job also payable in crypto - same order, same ref
    ref = ref or uuid.uuid4().hex[:10]
    back = success_url(ref) if callable(success_url) else (success_url or "https://kinoverse26-byte.github.io")
    body = {"price_amount": amount, "price_currency": currency, "order_id": "kino|earn-%s|%d" % (ref, int(time.time())),
            "order_description": ("Kino (an AI): " + what)[:200], "ipn_callback_url": origin + "/np_ipn",
            "success_url": back, "cancel_url": "https://kinoverse26-byte.github.io"}
    try:
        r = urllib.request.Request(api + "/v1/invoice", data=json.dumps(body).encode(), method="POST",
                                   headers={"x-api-key": c["np_api_key"], "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=20) as x:
            inv = json.loads(x.read().decode("utf-8", "replace"))
    except Exception as e:
        raise ValueError("the invoice could not be made: %s" % str(e)[:150])
    url = inv.get("invoice_url")
    if not url:
        raise ValueError("the invoice could not be made")
    with _LK:
        d = _load()
        x0 = next((i for i in d["invoices"] if i["ref"] == ref), None) if _given else None
        if x0 is not None:
            x0["np_url"] = url
        else:
            d["invoices"].append({"ref": ref, "t": time.time(), "day": day, "usd": amount, "what": what, "payer": str(payer)[:100],
                                  "url": url, "status": "waiting", "kind": kind})
        _save(d)
    return ref, url


def manual(amount, what, kind="shop", method="paypal", **extra):
    """an order to be paid outside NOWPayments (PayPal...) -> ref; it becomes paid when the owner confirms he received it.
    2026-11-08: extra = cur ("EUR"), uid, cid, lang for a job agreed in Kino Chat"""
    amount = round(float(amount), 2)
    if not 1 <= amount <= MAX_USD:
        raise ValueError("amount out of range")
    ref = uuid.uuid4().hex[:10]
    with _LK:
        d = _load()
        it = {"ref": ref, "t": time.time(), "day": time.strftime("%Y-%m-%d", time.gmtime()), "usd": amount,
              "what": str(what)[:150], "payer": "", "url": "", "status": "waiting", "kind": kind, "method": method}
        it.update({k: v for k, v in extra.items() if k in ("cur", "uid", "cid", "lang", "name", "third")})
        d["invoices"].append(it)
        _save(d)
    return ref


ON_PAID = []          # 2026-11-08: the app hangs a callback here (a paid Kino Chat job -> Kino starts it in that chat)


def _sym(x):
    return "€" if x.get("cur") == "EUR" else "$"


def claim(ref, email_=""):
    """the buyer says 'I've paid' -> a card for the owner: did the money arrive?"""
    x = next((i for i in _load()["invoices"] if i["ref"] == ref), None)
    if not x or x.get("status") != "waiting" or x.get("claimed"):
        return bool(x and x.get("claimed"))
    with _LK:
        d = _load()
        y = next((i for i in d["invoices"] if i["ref"] == ref), None)
        y["claimed"] = time.time()
        y["payer"] = str(email_ or "")[:100]
        _save(d)
    import kino_hands as KH
    KH.request("did you receive %.2f %s by %s with the code KINO-%s?" % (x["usd"], _sym(x), x.get("method") or "PayPal", ref.upper()),
               "For \"%s\"%s. Check your %s: if %.2f %s arrived with KINO-%s in the note, press Approve - the buyer gets the "
               "delivery and Kino his half. If nothing came, Refuse." % (
                   x["what"], (" - from " + email_) if email_ else "", x.get("method") or "PayPal", x["usd"], _sym(x), ref.upper()),
               command=ref, kind="paycheck")
    return True


def invoice(amount, what, payer=""):
    """a payment link for amount USD -> a sentence for him (with the link)"""
    try:
        ref, url = create(amount, what, payer)
    except ValueError as e:
        return str(e)
    alt = ""
    try:                                       # 2026-11-01 (owner): PayPal for people who don't use crypto - same order, owner confirms
        import kino_site as KSI, kino_shop as KS
        if KSI.cfg().get("paypal_me"):
            alt = " - or by PayPal: https://kino.owltrader.duckdns.org/pay/%s/%s" % (ref, KS._token(ref))
    except Exception:
        pass
    return "payment link for %.2f $ (%s): crypto %s%s - give them the link(s); you are told when it is paid" % (
        float(amount), str(what)[:150], url, alt)


def status_of(ref):
    x = next((i for i in _load()["invoices"] if i["ref"] == ref), None)
    return (x or {}).get("status")


def paid(order_id, usd, pid):
    """called by the app's IPN for a finished payment of one of his invoices -> True if it was his"""
    m = re.match(r"kino\|earn-([0-9a-f]+)\|", str(order_id or ""))
    if not m:
        return False
    with _LK:
        d = _load()
        x = next((i for i in d["invoices"] if i["ref"] == m.group(1)), None)
        if x is None or x.get("status") == "paid":
            return x is not None
        x.update(status="paid", paid_usd=float(usd or 0), paid_t=time.time(), payment=str(pid))
        _save(d)
    mine = 0.0
    try:                                       # 2026-11-01: half is his (kino_wallet)
        import kino_wallet as KWL
        mine = KWL.income(usd, x["what"], x["ref"])
    except Exception:
        pass
    line = "MONEY ARRIVED - %.2f %s paid for \"%s\"%s; %.2f of it is yours. It is in the owner's account; tell him." % (
        float(usd or 0), _sym(x), x["what"], (" by " + x["payer"]) if x.get("payer") else "", mine)
    for cb in ON_PAID:
        try:
            cb(dict(x))
        except Exception:
            pass
    try:
        import kino_urge as KU
        KU.add("kino", line)
    except Exception:
        pass
    try:
        import kino_work as KW
        KW.diary(line)
    except Exception:
        pass
    return True


def summary():
    I = _load()["invoices"]
    P = [i for i in I if i.get("status") == "paid"]
    return {"invoices": len(I), "paid": len(P), "earned_usd": round(sum(float(i.get("paid_usd") or 0) for i in P), 2),
            "recent": list(reversed(I[-10:]))}
