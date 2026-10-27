"""owl_plans.py - the plans (owner 2026-10-27: "Kino part of the product on any package; get people attached from day one").

One place for what each plan gives, what it costs and what a member has used. The server asks:
    plan_of(user, ent, now)        -> "owner" | "premium" | "pro" | "essentiel" | "decouverte_trial" | "decouverte"
    info(plan)                     -> PLAN_INFO row (label, price, Kino replies a day, robot tests a month, call minutes, ...)
    kino_left(uid, plan)           -> Kino replies left today (None = unlimited)
    note_reply(uid) / note_test(uid)
    tests_left(uid, plan)          -> robot tests left this month (None = unlimited)
Entitlement keys (owl_entitlements.json, unchanged): manual_until = Essentiel (was "Signal"), strategy_until = Pro (was
"Stratégie"), premium_until = Premium (new), family = Automatique (invitation; Kino at the Pro level).
Découverte = every registered member with no running paid plan: Kino FULL for TRIAL_DAYS from the account's start, then
light. Nothing is cut when a paid plan ends - the member falls back to Découverte; memory and conversations stay.
"""
import json
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
USAGE = os.path.join(HERE, "robots", "plan_usage.json")
TRIAL_DAYS = 14
_LOCK = threading.Lock()

# price: USD per 30 days (NOWPayments invoices are in USD, like every page of the app)
PLAN_INFO = {
    "decouverte":       {"label": "Découverte", "label_en": "Discovery", "usd": 0, "replies": 10, "tests": 2, "voice": 0,
                         "markets": False, "background": False},
    "decouverte_trial": {"label": "Découverte · essai", "label_en": "Discovery · trial", "usd": 0, "replies": 40, "tests": 2,
                         "voice": 0, "markets": False, "background": True},
    "essentiel":        {"label": "Essentiel", "label_en": "Essential", "usd": 19, "replies": 40, "tests": 5, "voice": 0,
                         "markets": False, "background": True},
    "pro":              {"label": "Pro", "label_en": "Pro", "usd": 49, "replies": 150, "tests": None, "voice": 30,
                         "markets": True, "background": True},
    "premium":          {"label": "Premium", "label_en": "Premium", "usd": 119, "replies": 400, "tests": None, "voice": 60,
                         "markets": True, "background": True, "own_broker": True},
    "owner":            {"label": "Propriétaire", "label_en": "Owner", "usd": 0, "replies": None, "tests": None, "voice": None,
                         "markets": True, "background": True},
}
ORDER = ("decouverte", "decouverte_trial", "essentiel", "pro", "premium", "owner")


def _start(user):
    """when the account began (the trial counts from here)"""
    u = user or {}
    for k in ("created", "pending_since"):
        try:
            if u.get(k):
                return float(u[k])
        except Exception:
            pass
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(u.get("era_start")).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def trial_end(user):
    s = _start(user)
    return s + TRIAL_DAYS * 86400 if s else 0.0


def plan_of(user, e, now=None, owner=False, family=False):
    """the plan running now. e = the member's entitlement record; owner / family = what the server already knows"""
    now = now or time.time()
    if owner:
        return "owner"
    e = e or {}
    if float(e.get("premium_until") or 0) > now:
        return "premium"
    if float(e.get("strategy_until") or 0) > now or family:
        return "pro"
    if float(e.get("manual_until") or 0) > now:
        return "essentiel"
    if trial_end(user) > now:
        return "decouverte_trial"
    return "decouverte"


def info(plan):
    return PLAN_INFO.get(plan) or PLAN_INFO["decouverte"]


def rank(plan):
    return ORDER.index(plan) if plan in ORDER else 0


# ---------------------------------------------------------------- usage (per member, per day / per month)
def _load():
    try:
        return json.load(open(USAGE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = USAGE + ".%d.tmp" % threading.get_ident()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    for _ in range(5):
        try:
            os.replace(tmp, USAGE)
            return
        except PermissionError:
            time.sleep(0.1)
    os.replace(tmp, USAGE)


def _day(tz_off_min=0, now=None):
    return time.strftime("%Y-%m-%d", time.gmtime((now or time.time()) - int(tz_off_min or 0) * 60))


def _month(now=None):
    return time.strftime("%Y-%m", time.gmtime(now or time.time()))


def replies_today(uid, tz_off_min=0):
    r = _load().get(uid) or {}
    return int((r.get("days") or {}).get(_day(tz_off_min), 0))


def note_reply(uid, tz_off_min=0):
    """one member message answered by Kino today (counted when it is sent)"""
    with _LOCK:
        d = _load()
        r = d.setdefault(uid, {})
        D = r.setdefault("days", {})
        k = _day(tz_off_min)
        D[k] = int(D.get(k, 0)) + 1
        for old in sorted(D)[:-8]:
            D.pop(old, None)
        _save(d)
        return D[k]


def kino_left(uid, plan, tz_off_min=0):
    cap = info(plan).get("replies")
    if cap is None:
        return None
    return max(0, int(cap) - replies_today(uid, tz_off_min))


def tests_this_month(uid):
    return int(((_load().get(uid) or {}).get("tests") or {}).get(_month(), 0))


def note_test(uid):
    with _LOCK:
        d = _load()
        r = d.setdefault(uid, {})
        T = r.setdefault("tests", {})
        k = _month()
        T[k] = int(T.get(k, 0)) + 1
        for old in sorted(T)[:-3]:
            T.pop(old, None)
        _save(d)
        return T[k]


def tests_left(uid, plan):
    cap = info(plan).get("tests")
    if cap is None:
        return None
    return max(0, int(cap) - tests_this_month(uid))


def describe(plan, uid=None, tz_off_min=0, user=None, lang="fr"):
    """one plain sentence for Kino's facts: the plan, what is left today - never a sales line"""
    I = info(plan)
    lab = I["label_en"] if lang == "en" else I["label"]
    if plan == "owner":
        return ""
    parts = []
    kl = kino_left(uid, plan, tz_off_min) if uid else None
    if kl is not None:
        parts.append(("he can still write to you %d times today" if lang == "en" else "il peut encore t'écrire %d fois aujourd'hui") % kl)
    tl = tests_left(uid, plan) if uid else None
    if tl is not None:
        parts.append(("%d robot tests left this month" if lang == "en" else "encore %d tests de robot ce mois") % tl)
    if plan == "decouverte_trial" and user:
        dleft = max(0, int((trial_end(user) - time.time()) // 86400) + 1)
        parts.append(("trial: %d days left" if lang == "en" else "essai : encore %d jours") % dleft)
    return ("Plan: %s" if lang == "en" else "Sa formule : %s") % lab + (" (" + ", ".join(parts) + ")" if parts else "")


if __name__ == "__main__":
    import tempfile
    USAGE = os.path.join(tempfile.mkdtemp(), "u.json")
    now = time.time()
    u_new = {"created": now - 86400}
    u_old = {"created": now - 30 * 86400}
    assert plan_of(u_new, {}) == "decouverte_trial"
    assert plan_of(u_old, {}) == "decouverte"
    assert plan_of(u_old, {"manual_until": now + 100}) == "essentiel"
    assert plan_of(u_old, {"strategy_until": now + 100, "manual_until": now + 100}) == "pro"
    assert plan_of(u_old, {"premium_until": now + 100}) == "premium"
    assert plan_of(u_old, {"strategy_until": now - 100}) == "decouverte"          # expired -> light, not cut off
    assert plan_of(u_old, {}, family=True) == "pro"
    assert plan_of(u_old, {}, owner=True) == "owner"
    assert kino_left("x", "decouverte") == 10
    for _ in range(3):
        note_reply("x")
    assert kino_left("x", "decouverte") == 7 and kino_left("x", "owner") is None
    note_test("x")
    assert tests_left("x", "decouverte") == 1 and tests_left("x", "pro") is None
    print(describe("decouverte_trial", "x", user=u_new))
    print("ok")
