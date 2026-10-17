"""owl_wallet.py - the member's cagnotte (owner 2026-10-17): referral earnings and creator earnings, kept in
dollars, SPENT ONLY AS SUBSCRIPTION TIME. Nobody is ever paid cash, and nothing is credited that was not received.

Money rules (review/REFERRAL_AND_MARKET.md has the arithmetic):
  * a referred member's confirmed payment credits the referrer REF_PCT of it (Signal / Strategie paid in crypto;
    Automatique settled with the owner, valued at nest_config "family_usd");
  * PAY ONCE (2026-10-17): robots on the place are included in the plan; the creator of the robot a member RUNS gets
    CREATOR_SHARE of that member's confirmed plan payment, in real money (cash, paid out from PAYOUT_MIN);
    (legacy: a robot month paid on its own credited CREATOR_PCT - no longer sold)
  * the cagnotte converts into days of the member's CURRENT package at that package's daily price, any time the
    member taps "Utiliser" (floor(usd / daily), at least 1 day); it can also pay a robot subscription in full.
Files: live/owl_wallet.json {uid: {"usd", "earned", "history": [...]}}; the referral links live on the member
records (ref_code, referred_by) so a referral survives everything else.
"""
import json, os, time, hashlib, threading

DIR = os.path.dirname(os.path.abspath(__file__))
WALLET = os.path.join(DIR, "owl_wallet.json")
USERS = os.path.join(DIR, "owl_nest_users.json")
REF_PCT = 0.50            # 2026-10-17: of a referred member's FIRST confirmed payment, in real money (was 20 % in days)
REF_PAYOUT_MIN = 100.0    # referral money is paid out (USDT, by the owner) from this balance
INF_PCT = 0.30            # 2026-10-17: an approved creator / YouTuber, on every payment of their users (owl_influencers)
INF_MONTHS = 12           # ... for the first 12 paid months of each user (owner 2026-10-17), then nothing
CREATOR_PCT = 0.70        # legacy: of a robot month paid on its own (no longer sold since 2026-10-17)
CREATOR_SHARE = 0.30      # 2026-10-17 (owner "Go"): PAY ONCE - the creator of the robot a member RUNS gets this share
                          # of that member's plan payment; the Owl and the owner's robots keep 100 % for the nest
MAX_REF_PER_MONTH = 10    # credited friends per referrer per calendar month (abuse brake)
_LOCK = threading.Lock()


def _load(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def _save(p, obj):
    tmp = p + ".%d.tmp" % os.getpid()
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


# ---- referral codes ----
_ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def code_of(uid):
    """a stable, pronounceable-enough code per member: OWL-XXXXX (no O/0/I/1)"""
    h = hashlib.sha256(("owl-ref|" + str(uid)).encode()).digest()
    return "OWL-" + "".join(_ALPHA[b % len(_ALPHA)] for b in h[:5])


def uid_of_code(code):
    c = str(code or "").strip().upper().replace(" ", "")
    if not c.startswith("OWL-") or len(c) != 9:
        return None
    for u in _load(USERS, []) or []:
        if not u.get("public") and code_of(u.get("id")) == c:
            return u.get("id")
    return None


def referrer_of(uid):
    for u in _load(USERS, []) or []:
        if u.get("id") == uid:
            return u.get("referred_by")
    return None


def friends_of(uid):
    """members who signed up with this member's code: [{id, name, since, plan}]"""
    out = []
    for u in _load(USERS, []) or []:
        if u.get("referred_by") == uid:
            out.append({"id": u.get("id"), "name": u.get("name") or u.get("id"), "since": u.get("created"), "plan": u.get("plan")})
    return out


# ---- the wallet ----
def balance(uid):
    w = (_load(WALLET, {}) or {}).get(uid) or {}
    return float(w.get("usd") or 0.0)


def account(uid):
    w = (_load(WALLET, {}) or {}).get(uid) or {}
    return {"usd": round(float(w.get("usd") or 0.0), 2), "earned": round(float(w.get("earned") or 0.0), 2), "history": (w.get("history") or [])[-30:]}


def _credit(uid, usd, kind, note):
    with _LOCK:
        W = _load(WALLET, {}) or {}
        w = W.setdefault(uid, {"usd": 0.0, "earned": 0.0, "history": []})
        w["usd"] = round(float(w.get("usd") or 0) + usd, 2)
        w["earned"] = round(float(w.get("earned") or 0) + usd, 2)
        w.setdefault("history", []).append({"t": int(time.time()), "usd": round(usd, 2), "kind": kind, "note": note})
        w["history"] = w["history"][-200:]
        _save(WALLET, W)
        return w["usd"]


def _debit(uid, usd, kind, note):
    with _LOCK:
        W = _load(WALLET, {}) or {}
        w = W.setdefault(uid, {"usd": 0.0, "earned": 0.0, "history": []})
        if float(w.get("usd") or 0) + 1e-9 < usd:
            return False
        w["usd"] = round(float(w.get("usd") or 0) - usd, 2)
        w.setdefault("history", []).append({"t": int(time.time()), "usd": -round(usd, 2), "kind": kind, "note": note})
        w["history"] = w["history"][-200:]
        _save(WALLET, W)
        return True


def on_member_payment(uid, pkg, usd, label=""):
    """2026-10-17 (owner changed his mind): a referred member's FIRST confirmed payment -> REF_PCT (50 %) of it to the
    referrer, in REAL MONEY (the cash ledger, kind "referral"), paid out from REF_PAYOUT_MIN. Later months of the
    same friend credit nothing; at most MAX_REF_PER_MONTH new friends a month. Returns (referrer_uid, credited_usd)."""
    ref = referrer_of(uid)
    if not ref or ref == uid or usd <= 0:
        return None, 0.0
    # 2026-10-17 (owner): an APPROVED creator / YouTuber earns INF_PCT on EVERY payment of their users, for as long
    # as those users pay - one code, one rule, never both (owl_influencers)
    kind, pct = "referral", REF_PCT
    try:
        import owl_influencers as _INF
        if _INF.is_approved(ref):
            kind, pct = "influencer", INF_PCT
    except Exception:
        pass
    month = time.strftime("%Y-%m", time.gmtime())
    W = _load(WALLET, {}) or {}
    hist = (W.get(ref) or {}).get("cash_history") or []
    if kind == "influencer":
        if sum(1 for h in hist if h.get("kind") == "influencer" and h.get("friend") == uid) >= INF_MONTHS:
            return ref, 0.0                               # the first INF_MONTHS paid months of this user, then nothing
    if kind == "referral":
        if any(h.get("kind") in ("referral", "influencer") and h.get("friend") == uid for h in hist):
            return ref, 0.0                               # only the first month ever
        friends_this_month = {h.get("friend") for h in hist if h.get("kind") == "referral" and time.strftime("%Y-%m", time.gmtime(int(h.get("t") or 0))) == month}
        if len(friends_this_month) >= MAX_REF_PER_MONTH:
            return ref, 0.0
    credit = round(usd * pct, 2)
    with _LOCK:
        W = _load(WALLET, {}) or {}
        w = W.setdefault(ref, {"usd": 0.0, "earned": 0.0, "history": []})
        w["cash"] = round(float(w.get("cash") or 0) + credit, 2)
        w["cash_earned"] = round(float(w.get("cash_earned") or 0) + credit, 2)
        w["cash_ref"] = round(float(w.get("cash_ref") or 0) + credit, 2)
        w.setdefault("cash_history", []).append({"t": int(time.time()), "usd": credit, "kind": kind, "friend": uid, "note": label or pkg, "paid_usd": round(float(usd), 2)})
        w["cash_history"] = w["cash_history"][-300:]
        _save(WALLET, W)
    return ref, credit


# ---- link traffic (owner 2026-10-17: "do we track traffic to the referral link?") ----
CLICKS = os.path.join(DIR, "owl_ref_clicks.json")
SALT_F = os.path.join(DIR, "owl_ref_salt")


def _salt():
    try:
        return open(SALT_F, encoding="utf-8").read().strip() or "owl"
    except Exception:
        import secrets
        s = secrets.token_hex(16)
        try:
            open(SALT_F, "w", encoding="utf-8").write(s)
        except Exception:
            pass
        return s


def record_click(code, ip):
    """a visit to /offres?p=<code>: +1 for the day, and a daily unique through a salted hash (no IP is stored).
    {code: {"YYYY-MM-DD": {"n": hits, "u": [hash, ...]}}} - the last 90 days only"""
    uid = uid_of_code(code)
    if not uid:
        return False
    code = str(code).strip().upper()
    day = time.strftime("%Y-%m-%d", time.gmtime())
    h = hashlib.sha256((_salt() + "|" + day + "|" + str(ip or "")).encode()).hexdigest()[:12]
    with _LOCK:
        C = _load(CLICKS, {}) or {}
        c = C.setdefault(code, {})
        d = c.setdefault(day, {"n": 0, "u": []})
        d["n"] = int(d.get("n") or 0) + 1
        if h not in d["u"]:
            d["u"].append(h)
        cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 90 * 86400))
        for k in [k for k in c if k < cutoff]:
            c.pop(k, None)
        _save(CLICKS, C)
    return True


def clicks_of(uid):
    """{d7, d30, total, u7, u30, today} for this member's link"""
    code = code_of(uid)
    c = (_load(CLICKS, {}) or {}).get(code) or {}
    now = time.time()
    out = {"today": 0, "d7": 0, "d30": 0, "total": 0, "u7": 0, "u30": 0}
    today = time.strftime("%Y-%m-%d", time.gmtime())
    for day, d in c.items():
        try:
            age = (now - time.mktime(time.strptime(day, "%Y-%m-%d"))) / 86400.0
        except Exception:
            continue
        n, u = int(d.get("n") or 0), len(d.get("u") or [])
        out["total"] += n
        if day == today:
            out["today"] += n
        if age <= 7:
            out["d7"] += n; out["u7"] += u
        if age <= 30:
            out["d30"] += n; out["u30"] += u
    return out


def referral_stats(uid):
    """the referrer's campaign: every friend who signed up with the code, whether their first month is paid, what it
    earned, plus the totals - the numbers behind the Parrainage page"""
    W = _load(WALLET, {}) or {}
    w = W.get(uid) or {}
    hist = [h for h in (w.get("cash_history") or []) if h.get("kind") in ("referral", "influencer")]
    by_friend = {}
    for h in hist:
        f = by_friend.setdefault(h.get("friend"), {"first": h, "n": 0, "inf_n": 0, "usd": 0.0, "last_t": 0, "last_paid": 0.0})
        f["n"] += 1; f["inf_n"] += 1 if h.get("kind") == "influencer" else 0
        f["usd"] += float(h.get("usd") or 0); f["last_t"] = max(f["last_t"], int(h.get("t") or 0)); f["last_paid"] = float(h.get("paid_usd") or 0)
    friends = []
    for f in friends_of(uid):
        h = by_friend.get(f["id"])
        friends.append({"since": f.get("since"), "plan": f.get("plan"), "paid": bool(h), "usd": round((h or {}).get("usd") or 0.0, 2),
                        "paid_t": (h or {}).get("last_t"), "months": (h or {}).get("n") or 0,
                        "months_left": max(0, INF_MONTHS - ((h or {}).get("inf_n") or 0)), "last_paid": (h or {}).get("last_paid") or 0.0,
                        "label": "Ami" if not f.get("name") else str(f.get("name"))[:1].upper() + "."})
    friends.sort(key=lambda x: -(x.get("since") or 0))
    earned = round(sum(h.get("usd") or 0 for h in hist), 2)
    # the creator view: money per month (last 6), this month, and the users whose last payment is recent
    now = time.time(); months = {}
    for h in hist:
        months[time.strftime("%Y-%m", time.gmtime(int(h.get("t") or 0)))] = round(months.get(time.strftime("%Y-%m", time.gmtime(int(h.get("t") or 0))), 0.0) + float(h.get("usd") or 0), 2)
    this_month = months.get(time.strftime("%Y-%m", time.gmtime()), 0.0)
    series = [{"m": m, "usd": months.get(m, 0.0)} for m in sorted(months)[-6:]]
    active = sum(1 for f in friends if f["paid"] and (now - float(f.get("paid_t") or 0)) < 35 * 86400)
    ck = clicks_of(uid)
    return {"friends": friends, "signed": len(friends), "paid": sum(1 for x in friends if x["paid"]), "earned": earned,
            "clicks": ck, "conversion": (round(100.0 * len(friends) / ck["u30"], 1) if ck["u30"] else None),
            "cash_ref": round(float(w.get("cash_ref") or 0), 2), "pct": int(REF_PCT * 100), "payout_min": REF_PAYOUT_MIN,
            "inf_pct": int(INF_PCT * 100), "inf_months": INF_MONTHS, "this_month": this_month, "series": series, "active": active,
            "expected": round(sum(f["last_paid"] * INF_PCT for f in friends if f["paid"] and f["months_left"] > 0 and (now - float(f.get("paid_t") or 0)) < 35 * 86400), 2),
            "recurring": round(sum(float(h.get("usd") or 0) for h in hist if h.get("kind") == "influencer"), 2)}


PAYOUT_MIN = 50.0         # a creator is paid (USDT, by the owner) once their earnings reach this


def on_plan_share(creator_uid, follower_uid, rid, plan_usd):
    """pay once (owner 2026-10-17): a member's CONFIRMED plan payment, while they run a member's robot -> that creator
    gets CREATOR_SHARE of it in real money. Nothing when the member runs the Owl or the owner's own robots."""
    if not creator_uid or creator_uid == follower_uid or plan_usd <= 0:
        return 0.0
    credit = round(plan_usd * CREATOR_SHARE, 2)
    with _LOCK:
        W = _load(WALLET, {}) or {}
        w = W.setdefault(creator_uid, {"usd": 0.0, "earned": 0.0, "history": []})
        w["cash"] = round(float(w.get("cash") or 0) + credit, 2)
        w["cash_earned"] = round(float(w.get("cash_earned") or 0) + credit, 2)
        w.setdefault("cash_history", []).append({"t": int(time.time()), "usd": credit, "kind": "share", "note": "%s <- %s" % (rid, follower_uid)})
        w["cash_history"] = w["cash_history"][-300:]
        _save(WALLET, W)
    return credit


def accrue_share(creator_uid, follower_uid, rid, usd):
    """pay once, BY TIME (owner 2026-10-17: "what if they run it five minutes?"): called every few minutes while a
    member's plan is active AND the creator's robot is attached; usd is the share for that slice of time. Fractions
    of a cent wait in cash_frac; whole cents move to cash and into ONE history line per robot, follower and day."""
    if not creator_uid or creator_uid == follower_uid or usd <= 0:
        return 0.0
    with _LOCK:
        W = _load(WALLET, {}) or {}
        w = W.setdefault(creator_uid, {"usd": 0.0, "earned": 0.0, "history": []})
        frac = float(w.get("cash_frac") or 0) + float(usd)
        cents = int(frac * 100 + 1e-9) / 100.0
        if cents > 0:
            w["cash"] = round(float(w.get("cash") or 0) + cents, 2)
            w["cash_earned"] = round(float(w.get("cash_earned") or 0) + cents, 2)
            day = time.strftime("%Y-%m-%d", time.gmtime()); note = "%s <- %s" % (rid, follower_uid)
            H = w.setdefault("cash_history", [])
            for h in reversed(H[-60:]):
                if h.get("note") == note and h.get("kind") == "share" and time.strftime("%Y-%m-%d", time.gmtime(int(h.get("t") or 0))) == day:
                    h["usd"] = round(float(h.get("usd") or 0) + cents, 2); h["t"] = int(time.time()); break
            else:
                H.append({"t": int(time.time()), "usd": round(cents, 2), "kind": "share", "note": note})
            w["cash_history"] = H[-300:]
            frac -= cents
        w["cash_frac"] = round(frac, 6)
        _save(WALLET, W)
    return cents


def creator_earned(rid):
    """what a listed robot has earned its creator in all (the sum of its shares and legacy robot months)"""
    tot = 0.0
    for w in (_load(WALLET, {}) or {}).values():
        for h in w.get("cash_history") or []:
            if str(h.get("note") or "").startswith(rid + " <-"):
                tot += float(h.get("usd") or 0)
    return round(tot, 2)


def on_robot_payment(creator_uid, follower_uid, rid, usd):
    """a follower's CONFIRMED robot subscription -> the creator's EARNINGS in real money (CREATOR_PCT), kept
    apart from the referral cagnotte (owner 2026-10-17: referral = time, robots = money, paid out from PAYOUT_MIN)"""
    if not creator_uid or creator_uid == follower_uid or usd <= 0:
        return 0.0
    credit = round(usd * CREATOR_PCT, 2)
    with _LOCK:
        W = _load(WALLET, {}) or {}
        w = W.setdefault(creator_uid, {"usd": 0.0, "earned": 0.0, "history": []})
        w["cash"] = round(float(w.get("cash") or 0) + credit, 2)
        w["cash_earned"] = round(float(w.get("cash_earned") or 0) + credit, 2)
        w.setdefault("cash_history", []).append({"t": int(time.time()), "usd": credit, "kind": "robot", "note": "%s <- %s" % (rid, follower_uid)})
        w["cash_history"] = w["cash_history"][-300:]
        _save(WALLET, W)
    return credit


def earnings(uid):
    """the creator's money side: balance, total, payout address, last payouts, and whether a payout is due"""
    w = (_load(WALLET, {}) or {}).get(uid) or {}
    cash = round(float(w.get("cash") or 0), 2)
    return {"cash": cash, "cash_earned": round(float(w.get("cash_earned") or 0), 2), "payout_addr": w.get("payout_addr") or "",
            "payout_min": PAYOUT_MIN, "due": _due(w), "payouts": (w.get("payouts") or [])[-12:], "history": (w.get("cash_history") or [])[-30:]}


def _due(w):
    """one cash balance, two doors: creator money from PAYOUT_MIN, referral money from REF_PAYOUT_MIN. The balance is
    due when it reaches the threshold of what it is mostly made of (all-referral -> 100, any creator share -> 50
    once the creator part alone reaches 50)."""
    cash = float(w.get("cash") or 0)
    ref = min(cash, float(w.get("cash_ref") or 0))
    creator = cash - ref
    return cash >= REF_PAYOUT_MIN or creator >= PAYOUT_MIN


def set_payout_addr(uid, addr):
    addr = str(addr or "").strip()[:120]
    with _LOCK:
        W = _load(WALLET, {}) or {}
        w = W.setdefault(uid, {"usd": 0.0, "earned": 0.0, "history": []})
        w["payout_addr"] = addr
        _save(WALLET, W)
    return addr


def payouts_due():
    """[(uid, cash, addr)] creators at or above PAYOUT_MIN - the owner's list"""
    out = []
    for uid, w in (_load(WALLET, {}) or {}).items():
        cash = round(float(w.get("cash") or 0), 2)
        if _due(w):
            out.append({"uid": uid, "cash": cash, "addr": w.get("payout_addr") or "", "ref": round(min(cash, float(w.get("cash_ref") or 0)), 2)})
    return sorted(out, key=lambda x: -x["cash"])


def mark_paid(uid, usd, ref):
    """the owner paid `usd` to this creator (USDT tx `ref`): debits the earnings, keeps the record"""
    with _LOCK:
        W = _load(WALLET, {}) or {}
        w = W.get(uid)
        if not w or float(w.get("cash") or 0) + 1e-9 < usd or usd <= 0:
            return False
        w["cash"] = round(float(w.get("cash") or 0) - usd, 2)
        w["cash_ref"] = round(max(0.0, float(w.get("cash_ref") or 0) - usd), 2)       # a payout empties the referral part first
        w.setdefault("payouts", []).append({"t": int(time.time()), "usd": round(usd, 2), "ref": str(ref or "")[:80], "addr": w.get("payout_addr") or ""})
        _save(WALLET, W)
        return True


def daily_price(pkg, packages, family_usd):
    """what one day of this package is worth, in dollars"""
    if pkg == "family":
        return (float(family_usd or 0) / 30.0) if family_usd else 0.0
    p = (packages or {}).get(pkg) or {}
    return (float(p.get("usd") or 0) / float(p.get("days") or 30)) if p.get("usd") else 0.0


def days_available(uid, pkg, packages, family_usd):
    dp = daily_price(pkg, packages, family_usd)
    return int(balance(uid) // dp) if dp > 0 else 0


def spend_days(uid, pkg, days, packages, family_usd):
    """turn cagnotte into `days` of `pkg`: debits usd, returns the usd spent (0.0 = not enough)"""
    dp = daily_price(pkg, packages, family_usd)
    if dp <= 0 or days <= 0:
        return 0.0
    usd = round(dp * days, 2)
    return usd if _debit(uid, usd, "time", "%d jour(s) %s" % (days, pkg)) else 0.0


def pay_from_wallet(uid, usd, note):
    """pay something (a robot subscription) from the cagnotte; True when debited"""
    return _debit(uid, round(float(usd), 2), "robot_sub", note) if usd > 0 else False
