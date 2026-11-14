"""
Kino's money ledger, worldwide (owner plan 2026-11-14, step 6 of mt5_kino_world_helpers_plan).

Every movement of money for people's jobs is written here, per country:
  client_in    a client paid (PayPal / card to the owner, or mobile money to a local treasurer)
  helper_out   a helper was paid (by the owner, or by the treasurer from client money - netting)
  to_owner     a treasurer sent the surplus to the owner (WorldRemit, Western Union...)
  topup        the owner topped a treasurer up (mobile money)
A TREASURER per country is a proven helper the OWNER appoints (chat: #tresorier <country> <uid> [cap EUR] [commission %]).
Kino never appoints one himself; he may only propose one (the most reliable helper: missions done, proofs ok, time).
Treasurer balance = client_in(to them) - helper_out(by them) - to_owner + topup; above the cap -> ask them to send the surplus.

Amounts are kept in EUR (the reference) with the local amount/currency as said. Store: kino_ledger.json
"""
import json
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_ledger.json")
LOG = os.path.join(HERE, "kino_ledger.log")
_LK = threading.Lock()
KINDS = ("client_in", "helper_out", "to_owner", "topup")
XAF_EUR = 655.957                     # CFA franc is pegged to the euro (XAF central Africa, XOF west Africa)
FIXED = {"xaf": XAF_EUR, "xof": XAF_EUR, "eur": 1.0}
CFA = {"congo", "republique du congo", "congo brazzaville", "cameroun", "cameroon", "gabon", "tchad", "chad",
       "centrafrique", "guinee equatoriale", "senegal", "cote d ivoire", "ivory coast", "mali", "burkina faso", "niger",
       "togo", "benin", "guinee bissau"}


def _log(line):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _j():
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"entries": [], "treasurers": {}}


def _mut(fn):
    with _LK:
        d = _j()
        r = fn(d)
        tmp = STORE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
        return r


def _norm(c):
    try:
        import kino_reach as KR
        return KR.norm(c)
    except Exception:
        return str(c or "").lower().strip()


def local(eur, country):
    """'5.00 EUR (= 3 280 FCFA)' for CFA countries, the euro amount elsewhere"""
    s = "%.2f EUR" % float(eur)
    if _norm(country) in CFA:
        s += " (= %s FCFA)" % format(int(round(float(eur) * XAF_EUR, -1)), ",").replace(",", " ")
    return s


def add(kind, country, eur, who="", ref="", how="", proof="", local_amount=""):
    if kind not in KINDS:
        return "kind must be one of " + ", ".join(KINDS)
    try:
        eur = round(float(eur), 2)
    except Exception:
        return "the amount in EUR, please"
    if eur <= 0:
        return "the amount must be above 0"
    e = {"t": time.time(), "kind": kind, "country": _norm(country), "eur": eur, "who": str(who)[:80], "ref": str(ref)[:60],
         "how": str(how)[:60], "proof": str(proof)[:300], "local": str(local_amount)[:40]}
    _mut(lambda d: d.setdefault("entries", []).append(e))
    _log("ADD %s %s %.2f %s %s" % (kind, e["country"], eur, who, ref))
    msg = "written: %s %s %s (%s)" % (kind, local(eur, country), who, ref or "-")
    tr = treasurer(country)
    if tr:
        b = balance(country)
        if b > float(tr.get("cap") or 100):
            msg += (" - the treasurer %s now holds %s, above the %s cap: ask them to send the surplus to Matsy (to_owner)"
                    % (tr["name"], local(b, country), local(tr.get("cap") or 100, country)))
        elif b < 0:
            msg += " - the treasurer %s is short by %s: Matsy tops them up (topup)" % (tr["name"], local(-b, country))
    return msg


def treasurer(country):
    return (_j().get("treasurers") or {}).get(_norm(country))


def set_treasurer(country, uid, name="", cap=100.0, commission=4.0, by="owner"):
    """the OWNER only (the app checks it)"""
    c = _norm(country)

    def f(d):
        d.setdefault("treasurers", {})[c] = {"uid": uid, "name": name or uid, "cap": float(cap), "commission": float(commission),
                                             "since": time.time(), "by": by}
    _mut(f)
    _log("TREASURER %s %s cap %.0f com %.1f" % (c, uid, cap, commission))
    return "%s is the treasurer for %s (cap %.0f EUR, commission %.1f %%)" % (name or uid, c, cap, commission)


def balance(country):
    """what the country's treasurer holds"""
    c = _norm(country)
    tr = treasurer(c)
    if not tr:
        return 0.0
    b = 0.0
    for e in _j().get("entries") or []:
        if e.get("country") != c or float(e.get("t") or 0) < float(tr.get("since") or 0):
            continue
        via = "treasurer" in str(e.get("how")).lower()
        if e["kind"] == "client_in" and via:
            b += e["eur"]
        elif e["kind"] == "helper_out" and via:
            b -= e["eur"]
        elif e["kind"] == "to_owner":
            b -= e["eur"]
        elif e["kind"] == "topup":
            b += e["eur"]
    return round(b, 2)


def block():
    d = _j()
    T = d.get("treasurers") or {}
    E = d.get("entries") or []
    month = [e for e in E if time.time() - float(e.get("t") or 0) < 30 * 86400]
    tin = sum(e["eur"] for e in month if e["kind"] == "client_in")
    tout = sum(e["eur"] for e in month if e["kind"] == "helper_out")
    s = "MONEY LEDGER (30 days): clients paid %.2f EUR, helpers paid %.2f EUR, %d movements" % (tin, tout, len(month))
    if T:
        s += "; treasurers: " + "; ".join("%s %s holds %s" % (c, t["name"], local(balance(c), c)) for c, t in T.items())
    s += (". Write every movement with ledger_add (\"kind\" client_in/helper_out/to_owner/topup, \"country\", \"eur\", \"who\", "
          "\"ref\" task or job id, \"how\" paypal / mobile money / treasurer, \"proof\"). Where a country has a treasurer, "
          "clients there pay the treasurer by mobile money and the treasurer pays local helpers from it (how: treasurer). "
          "You never appoint a treasurer: propose one to Matsy (the most reliable helper there - missions done, proofs "
          "genuine, a month of work); he decides.")
    return s


if __name__ == "__main__":
    print(local(5, "Congo"), "|", local(5, "France"))
    print(block())
