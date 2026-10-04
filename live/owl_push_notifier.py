"""owl_push_notifier.py - phone push notifications for OwlNest.

Tails owl_manual.log and sends web-push notifications (French, easy
words) to every subscribed device in owl_push_subs.json:
  - immediately: storms, storm-lift, funded fighters, fighter results
  - batched (10 min): trade exits, summed into one message
Dead subscriptions (410/404) are pruned automatically.
"""
import json
import subprocess
import os
import re
import time

from pywebpush import webpush, WebPushException

DIR = r"C:\Projects\KinoliveLines\live"
LOG = os.path.join(DIR, "owl_manual.log")
SUBS = os.path.join(DIR, "owl_push_subs.json")
INBOX = os.path.join(DIR, "owl_push_inbox.json")
VAPID_JSON = os.path.join(DIR, "owl_push_vapid.json")
VAPID_PEM = os.path.join(DIR, "owl_push_vapid.pem")
MYLOG = os.path.join(DIR, "owl_push_notifier.log")
CLAIMS = {"sub": "mailto:owlnest@kinolivelines.local"}
BATCH_SECS = 600


def mylog(m):
    with open(MYLOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {m}\n")


if not os.path.exists(VAPID_PEM):
    pem = json.load(open(VAPID_JSON))["private_pem"]
    open(VAPID_PEM, "w").write(pem)


def _inbox_write(new):
    """2026-09-27: keep the last 30 notifications per member for the app's
    'Messages' screen - including the ones 'silence la nuit' held back."""
    if not new:
        return
    try:
        cur = json.load(open(INBOX, encoding="utf-8"))
        if not isinstance(cur, dict):
            cur = {}
    except Exception:
        cur = {}
    for uid, items in new.items():
        lst = [x for x in cur.get(uid, []) if isinstance(x, dict)] + items
        cur[uid] = lst[-30:]
    try:
        tmp = INBOX + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False)
        os.replace(tmp, INBOX)
    except Exception:
        pass


def lang_of(uid):
    """2026-09-27: the phone's language (push_pref lang=), default fr."""
    try:
        return (json.load(open(os.path.join(DIR, "owl_push_prefs.json")))
                .get("_lang") or {}).get(uid, "fr")
    except Exception:
        return "fr"


HEALTH_MARK = os.path.join(DIR, "owl_push_health.json")


def maybe_health():
    """2026-09-27: tell the owner when a feed goes stale (> 5 min), once per
    half hour per feed. The chart feed and every trading account's worker."""
    now = time.time()
    try:
        st = json.load(open(HEALTH_MARK, encoding="utf-8"))
    except Exception:
        st = {}
    late = []

    def age(p):
        try:
            return now - os.path.getmtime(os.path.join(DIR, p))
        except Exception:
            return None
    a = age("owl_chart_btc.json")
    if a is None or a > 300:
        late.append(("flux graphique", a))
    try:
        for u in json.load(open(os.path.join(DIR, "owl_nest_users.json"), encoding="utf-8")):
            if not (u.get("trade") or u.get("id") == "kino"):
                continue
            a = age(os.path.join("nest_data", u["id"] + ".json"))
            if a is None or a > 300:
                late.append((f"compte {u.get('name', u['id'])}", a))
    except Exception:
        pass
    changed = False
    for name, a in late:
        if now - float(st.get(name, 0) or 0) < 1800:
            continue
        st[name] = now
        changed = True
        mins = "inconnu" if a is None else f"{int(a // 60)} min"
        send_all("\u26a0\ufe0f Service", f"{name} : en retard de {mins}.",
                 kind="instant", only_uid="kino")
    if changed:
        try:
            json.dump(st, open(HEALTH_MARK, "w", encoding="utf-8"))
        except Exception:
            pass


DEMO_MARK = os.path.join(DIR, "owl_demo_reset.json")


def maybe_demo_reset():
    """2026-09-27 (owner): the public demo is the shop window. When its robot
    hits the kill line: tell the owner, and 24 h later ask the mode-switch
    watcher to reset it (archive, era, restart from zero). Public accounts
    only - never a real member."""
    now = time.time()
    try:
        users = json.load(open(os.path.join(DIR, "owl_nest_users.json"), encoding="utf-8"))
    except Exception:
        return
    try:
        st = json.load(open(DEMO_MARK, encoding="utf-8"))
    except Exception:
        st = {}
    changed = False
    for u in users:
        if not u.get("public"):
            continue
        uid = u["id"]
        try:
            killed = bool(json.load(open(os.path.join(DIR, f"bos_state_{uid}.json"))).get("killed"))
        except Exception:
            continue
        rec = st.get(uid) or {}
        if killed:
            if not rec.get("killed_since") and now - float(rec.get("last_reset") or 0) > 600:
                rec["killed_since"] = now
                changed = True
                send_all("\U0001f501 D\u00e9mo \u00e0 sa limite",
                         "Le robot de la d\u00e9mo s'est arr\u00eat\u00e9 (limite de s\u00e9curit\u00e9). "
                         "Red\u00e9marrage automatique dans 24 h.", kind="instant", only_uid="kino")
            elif now - float(rec["killed_since"]) > 86400 and now - float(rec.get("last_reset") or 0) > 86400:
                tmp = os.path.join(DIR, "owl_reset_request.json.tmp")
                json.dump({"uid": uid, "t": now, "by": "watchdog"}, open(tmp, "w"))
                os.replace(tmp, os.path.join(DIR, "owl_reset_request.json"))
                rec["last_reset"] = now
                rec["killed_since"] = None
                changed = True
                send_all("\U0001f501 D\u00e9mo r\u00e9initialis\u00e9e",
                         "24 h apr\u00e8s sa limite, la d\u00e9mo repart de z\u00e9ro (ancien livre archiv\u00e9).",
                         kind="instant", only_uid="kino")
        elif rec.get("killed_since"):
            rec["killed_since"] = None
            changed = True
        st[uid] = rec
    if changed:
        try:
            json.dump(st, open(DEMO_MARK, "w", encoding="utf-8"))
        except Exception:
            pass


RENEW_MARK = os.path.join(DIR, "owl_renew_marks.json")
SHARE_MARK = os.path.join(DIR, "owl_share_marks.json")
MONTHS_FR = ["janvier", "f\u00e9vrier", "mars", "avril", "mai", "juin", "juillet", "ao\u00fbt", "septembre", "octobre", "novembre", "d\u00e9cembre"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def _mname(ym, en):
    try:
        return (MONTHS_EN if en else MONTHS_FR)[int(ym[5:7]) - 1]
    except Exception:
        return ym


LAUNCH_MARK = os.path.join(DIR, "owl_launch_report_mark.json")


def maybe_launch_report():
    """2026-10-04 (owner): the evening watch while the doors are new. One
    push to Kino a day, after 13:00 VPS time (20:00 for him): who joined,
    who opened the app, who waits for a code, who got a push nobody could
    receive, whose period ends within three days."""
    import datetime as _dt
    now = _dt.datetime.now()
    if now.hour < 13:
        return
    today = now.strftime("%Y-%m-%d")
    try:
        if json.load(open(LAUNCH_MARK, encoding="utf-8")).get("day") == today:
            return
    except Exception:
        pass
    try:
        users = json.load(open(os.path.join(DIR, "owl_nest_users.json"), encoding="utf-8"))
        seen = json.load(open(os.path.join(DIR, "owl_last_seen.json"), encoding="utf-8"))
        ents = json.load(open(os.path.join(DIR, "owl_entitlements.json"), encoding="utf-8"))
    except Exception:
        return
    midnight = _dt.datetime(now.year, now.month, now.day).timestamp()
    name = lambda u: u.get("name") or u.get("id")
    members = [u for u in users if u.get("id") not in ("kino", "std", "expenses") and not u.get("public")]
    new = [name(u) for u in members if float(u.get("created") or 0) >= midnight and not u.get("pending_code")]
    opened = [name(u) for u in members if float(seen.get(u.get("id")) or 0) >= midnight]
    pend = [f"{name(u)} ({ {'family': 'Automatique', 'manual': 'Signal', 'strategy': 'Strategie'}.get(u.get('pending_code'), '?') }, {max(0, int((time.time() - float(u.get('asked_at') or time.time())) // 3600))} h)"
            for u in users if u.get("pending_code")]
    unpaid = [name(u) for u in users if u.get("pending_pay")]
    ending = []
    for u in members:
        e = ents.get(u.get("id")) or {}
        for k, lab in (("family_until", "Automatique"), ("manual_until", "Signal"), ("strategy_until", "Strategie")):
            left = (float(e.get(k) or 0) - time.time()) / 86400.0
            if 0 < left <= 3:
                ending.append(f"{name(u)} {lab} {left:.0f} j")
    nodev = 0
    try:
        for ln in open(os.path.join(DIR, "owl_push_notifier.log"), encoding="utf-8", errors="replace"):
            if ln.startswith(today) and "(no device)" in ln:
                nodev += 1
    except Exception:
        pass
    parts = [f"Nouveaux : {', '.join(new) if new else 'aucun'}",
             f"Ont ouvert l'app : {', '.join(opened) if opened else 'personne'}"]
    if pend:
        parts.append("En attente d'un code : " + ", ".join(pend))
    if unpaid:
        parts.append("Paiement crypto en attente : " + ", ".join(unpaid))
    if ending:
        parts.append("Finit sous 3 j : " + ", ".join(ending))
    if nodev:
        parts.append(f"{nodev} push(s) sans appareil aujourd'hui")
    send_all("\U0001f989 Le soir \u00b7 " + today, " \u00b7 ".join(parts)[:600], kind="instant", only_uid="kino")
    try:
        json.dump({"day": today}, open(LAUNCH_MARK, "w", encoding="utf-8"))
    except Exception:
        pass


def maybe_share():
    """2026-10-03 (owner): the profit share's clock.
    1st of the month -> the statements of the month that ended, one push
    each + one summary to the Owl; 2 days before the grace ends -> a
    reminder; past the grace -> the robot pauses on that account and both
    are told. Each step once (owl_share_marks.json / the period itself)."""
    try:
        sys.path.insert(0, DIR)
        import owl_share as SH
        if not SH.on():
            return
    except Exception:
        return
    now = time.time()
    try:
        marks = json.load(open(SHARE_MARK, encoding="utf-8"))
    except Exception:
        marks = {}
    try:
        users = {u["id"]: u for u in json.load(open(os.path.join(DIR, "owl_nest_users.json"), encoding="utf-8"))}
    except Exception:
        users = {}
    name = lambda uid: users.get(uid, {}).get("name", uid)
    # 1. the month that ended
    this_ym = SH.ym_of(now)
    prev = SH.prev_ym(this_ym)
    if marks.get("closed") != prev:
        issued = SH.close_month(prev, now)
        marks["closed"] = prev
        try:
            json.dump(marks, open(SHARE_MARK, "w", encoding="utf-8"))
        except Exception:
            pass
        tot = 0.0
        for uid, p in issued:
            en = lang_of(uid) == "en"
            m = _mname(prev, en)
            tot += float(p.get("due") or 0)
            if float(p.get("due") or 0) <= 0:
                continue
            if p["above"] > 0:
                bse = (f" + {p['base']:.2f} $ base" if en else f" + {p['base']:.2f} $ de base") if float(p.get("base") or 0) > 0 else ""
                body = ((f"The robot made {p['profit']:+.2f} $ for you in {m}; {p['above']:.2f} $ above your record. "
                         f"Your OwlNest share: {p['share']:.2f} $ ({p['pct']:.0f} %){bse} = {p['due']:.2f} $. "
                         f"{SH.cfg()['grace_days']} days to settle - Settings > Subscription.") if en else
                        (f"Le robot a gagn\u00e9 {p['profit']:+.2f} $ pour vous en {m} ; {p['above']:.2f} $ au-dessus de votre record. "
                         f"Votre part OwlNest : {p['share']:.2f} $ ({p['pct']:.0f} %){bse} = {p['due']:.2f} $. "
                         f"{SH.cfg()['grace_days']} jours pour r\u00e9gler \u2014 R\u00e9glages \u203a Abonnement."))
            else:
                body = ((f"No gain above your record in {m} ({p['profit']:+.2f} $): no share. Only the {p['base']:.0f} $ base is due. "
                         f"{SH.cfg()['grace_days']} days to settle - Settings > Subscription.") if en else
                        (f"Pas de gain au-dessus de votre record en {m} ({p['profit']:+.2f} $) : pas de part. Seule la base de {p['base']:.0f} $ est due. "
                         f"{SH.cfg()['grace_days']} jours pour r\u00e9gler \u2014 R\u00e9glages \u203a Abonnement."))
            send_all("\U0001f9fe " + (f"Your OwlNest statement - {m}" if en else f"Votre relev\u00e9 OwlNest \u2014 {m}"), body, kind="instant", only_uid=uid)
        if issued:
            send_all("\U0001f9fe Relev\u00e9s envoy\u00e9s \u00b7 " + _mname(prev, False),
                     " \u00b7 ".join(f"{name(uid)} {float(p.get('due') or 0):.2f} $" for uid, p in issued) + f" \u2014 total {tot:.2f} $",
                     kind="instant", only_uid="kino")
    # 2. reminders, 2 days before the grace ends
    doc = SH.load()
    grace = int(doc["cfg"]["grace_days"]) * 86400
    changed = False
    for uid, acc in doc["accounts"].items():
        for p in acc.get("periods") or []:
            if p.get("status") == "open" and not p.get("reminded") and float(p.get("due") or 0) > 0 \
                    and now > float(p.get("issued") or now) + grace - 2 * 86400:
                p["reminded"] = int(now)
                changed = True
                en = lang_of(uid) == "en"
                send_all("\u23f3 " + (f"Statement {_mname(p['ym'], en)}: 2 days left" if en else f"Relev\u00e9 {_mname(p['ym'], en)} : 2 jours"),
                         (f"{p['due']:.2f} $ still to settle. Past the deadline the robot pauses on your account." if en
                          else f"{p['due']:.2f} $ restent \u00e0 r\u00e9gler. Pass\u00e9 le d\u00e9lai, le robot se met en pause sur votre compte."),
                         kind="instant", only_uid=uid)
    if changed:
        SH.save(doc)
    # 3. past the grace: pause
    for uid, p in SH.overdue_sweep(now):
        en = lang_of(uid) == "en"
        send_all("\u23f8 " + ("Robot paused - statement unsettled" if en else "Robot en pause \u2014 relev\u00e9 non r\u00e9gl\u00e9"),
                 (f"The {_mname(p['ym'], en)} statement ({p['due']:.2f} $) was not settled in time. The robot is paused on your account; it goes on as soon as it is settled."
                  if en else f"Le relev\u00e9 de {_mname(p['ym'], en)} ({p['due']:.2f} $) n\u2019a pas \u00e9t\u00e9 r\u00e9gl\u00e9 \u00e0 temps. Le robot est en pause sur votre compte ; il reprend d\u00e8s le r\u00e8glement."),
                 kind="instant", only_uid=uid)
        send_all("\u23f8 Robot en pause \u00b7 " + name(uid), f"Relev\u00e9 {p['ym']} non r\u00e9gl\u00e9 ({p['due']:.2f} $). \u00ab Pay\u00e9 \u00bb dans Le Nid quand c\u2019est r\u00e9gl\u00e9.",
                 kind="instant", only_uid="kino")


def _share_on():
    try:
        sys.path.insert(0, DIR)
        import owl_share as SH
        return SH.on()
    except Exception:
        return False


def maybe_renewals():
    """2026-09-27 (owner): every dated package (family = Automatique settled
    with the owner, manual, strategy) gets a reminder 5 days and 2 days
    before its end and a notice at expiry. A family package that expires
    pauses the robot on that account (by="expiry"; the renewal code lifts
    it). One push per step per period."""
    now = time.time()
    try:
        ents = json.load(open(os.path.join(DIR, "owl_entitlements.json"), encoding="utf-8"))
    except Exception:
        return
    try:
        marks = json.load(open(RENEW_MARK, encoding="utf-8"))
    except Exception:
        marks = {}
    try:
        users = {u["id"]: u for u in json.load(open(os.path.join(DIR, "owl_nest_users.json"), encoding="utf-8"))}
    except Exception:
        users = {}
    changed = False
    for uid, e in ents.items():
        if uid in ("kino", "std") or not isinstance(e, dict):
            continue
        en = lang_of(uid) == "en"
        for key, label_fr, label_en in (("family_until", "Automatique", "Automatic"),
                                       ("strategy_until", "Strat\u00e9gie", "Strategy"),
                                       ("manual_until", "Signal", "Signal")):
            until = float(e.get(key) or 0)
            if not until:
                continue
            if key == "manual_until" and float(e.get("strategy_until") or 0) > now:
                continue          # covered by the strategy package
            if key == "family_until" and _share_on():
                continue          # 2026-10-03: the share replaces the dated period
            left = (until - now) / 86400.0
            step = "0" if left <= 0 else "2" if left <= 2 else "5" if left <= 5 else None
            if step is None:
                continue
            mk = marks.setdefault(uid, {}).setdefault(key, {})
            if mk.get(step) == int(until):
                continue
            mk[step] = int(until)
            changed = True
            fam = key == "family_until"
            if step == "0":
                if fam:
                    try:
                        json.dump({"paused": True, "by": "expiry", "t": now},
                                  open(os.path.join(DIR, f"owl_trading_pause_{uid}.json"), "w"))
                    except Exception:
                        pass
                    send_all("\u23f8 " + ("Access expired" if en else "Acc\u00e8s expir\u00e9"),
                             ("The robot is paused on your account. Settle with the Owl and enter the renewal code in the app."
                              if en else "Le robot est en pause sur votre compte. R\u00e9glez le Owl et entrez le code de renouvellement dans l'app."),
                             kind="instant", only_uid=uid)
                    send_all("\u23f8 Acc\u00e8s expir\u00e9 \u00b7 " + users.get(uid, {}).get("name", uid),
                             "Robot mis en pause. Envoyez un code de renouvellement quand c'est r\u00e9gl\u00e9.",
                             kind="instant", only_uid="kino")
                else:
                    send_all("\u23f8 " + ("Subscription ended" if en else "Abonnement termin\u00e9"),
                             ((label_en + " has ended. Renew in Settings \u203a Subscription to keep the signals.")
                              if en else (label_fr + " est termin\u00e9. Renouvelez dans R\u00e9glages \u203a Abonnement pour garder les signaux.")),
                             kind="instant", only_uid=uid)
            else:
                d_ = int(step)
                if fam:
                    send_all("\u23f3 " + (f"{label_en} ends in {d_} days" if en else f"{label_fr} expire dans {d_} jours"),
                             ("Settle with the Owl now, then enter the code he sends you, to avoid an interruption."
                              if en else "R\u00e9glez le Owl d\u00e8s maintenant, puis entrez le code qu'il vous enverra, pour \u00e9viter une coupure."),
                             kind="instant", only_uid=uid)
                    send_all("\u23f3 " + users.get(uid, {}).get("name", uid) + f" \u00b7 expire dans {d_} j",
                             "Pensez au r\u00e8glement et au code de renouvellement.", kind="instant", only_uid="kino")
                else:
                    send_all("\u23f3 " + (f"{label_en} ends in {d_} days" if en else f"{label_fr} expire dans {d_} jours"),
                             ("Renew in Settings \u203a Subscription to keep the signals without a break."
                              if en else "Renouvelez dans R\u00e9glages \u203a Abonnement pour garder les signaux sans coupure."),
                             kind="instant", only_uid=uid)
    if changed:
        try:
            json.dump(marks, open(RENEW_MARK, "w", encoding="utf-8"))
        except Exception:
            pass


WAIT_FILE = os.path.join(DIR, "owl_waitlist.json")
MANUAL_CAP = 10     # keep in step with owl_app_server.MANUAL_CAP


def maybe_waitlist():
    """2026-09-28: a manual seat freed up -> tell the waiting members
    (once each, first come first served) and the owner."""
    try:
        w = json.load(open(WAIT_FILE, encoding="utf-8"))
    except Exception:
        return
    if not isinstance(w, dict) or not w:
        return
    try:
        us = json.load(open(os.path.join(DIR, "owl_nest_users.json"), encoding="utf-8"))
    except Exception:
        return
    seats = sum(1 for u in us if u.get("mode") in ("manual", "semi"))
    free = MANUAL_CAP - seats
    if free <= 0:
        return
    names = []
    for uid, it in list(w.items()):
        en = lang_of(uid) == "en"
        try:
            send_all("\U0001f7e2 " + ("A place is free" if en else "Une place est libre"),
                     ("Manual trading is open again \u2014 Settings \u203a Subscription \u203a Manual. "
                      "First come, first served." if en else
                      "Le trading manuel est de nouveau ouvert \u2014 R\u00e9glages \u203a Abonnement \u203a Manuel. "
                      "Premier arriv\u00e9, premier servi."),
                     kind="instant", only_uid=uid)
        except Exception:
            pass
        names.append((it or {}).get("name") or uid)
        w.pop(uid, None)
    try:
        json.dump(w, open(WAIT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass
    if names:
        for _o in ("kino", "std"):
            try:
                send_all("\U0001f4cb Liste d\u2019attente",
                         f"{free} place(s) libre(s) \u2014 pr\u00e9venu(s) : " + ", ".join(names),
                         kind="instant", only_uid=_o)
            except Exception:
                pass
    mylog(f"waitlist: {free} free, told {names}")


MKT_DIR = os.path.join(DIR, "mkt_mem")
_MEM = {"last": 0, "day": None}


def market_memory_tick():
    """2026-09-28 (owner): the market analysis space grows on data. One row
    per minute from the feed's published state - nervosity ratio and its two
    halves, big moves in 2 h, trend, internal state, spread, price - in
    mkt_mem/YYYY-MM-DD.jsonl (UTC day), kept 90 days. Read-only elsewhere."""
    try:
        cj = json.load(open(os.path.join(DIR, "owl_chart_btc.json"), encoding="utf-8"))
    except Exception:
        return
    t = int(cj.get("updated") or 0)
    if not t or time.time() - t > 180:
        return                                  # stale feed: no row
    m = t - t % 60
    if m == _MEM["last"]:
        return
    _MEM["last"] = m
    vn, vr = cj.get("vol_now"), cj.get("vol_ref")
    row = {"t": m, "nerv": (round(vn / max(vr, 1), 3) if vn and vr else None), "vn": vn, "vr": vr,
           "mv2": cj.get("moves_2h"), "trend": cj.get("trend"), "int": cj.get("int_state"),
           "it": cj.get("int_trend"), "brk1h": cj.get("int_brk_1h"), "spread": cj.get("spread"),
           "px": cj.get("px")}
    try:
        os.makedirs(MKT_DIR, exist_ok=True)
        day = time.strftime("%Y-%m-%d", time.gmtime(m))
        fn = os.path.join(MKT_DIR, day + ".jsonl")
        if _MEM["day"] is None and not os.path.exists(fn):
            # first run: seed the last 24 h of nervosity from the feed's own history
            try:
                for p in json.load(open(os.path.join(DIR, "owl_nerv_hist.json"))):
                    tt = int(p[0]) - int(p[0]) % 60
                    if tt >= m:
                        continue
                    dd = time.strftime("%Y-%m-%d", time.gmtime(tt))
                    with open(os.path.join(MKT_DIR, dd + ".jsonl"), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"t": tt, "nerv": round(float(p[1]), 3), "seed": 1}, separators=(",", ":")) + "\n")
            except Exception:
                pass
        with open(fn, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
        if day != _MEM["day"]:
            _MEM["day"] = day
            cut = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 90 * 86400))
            for old in os.listdir(MKT_DIR):
                if old.endswith(".jsonl") and old[:10] < cut:
                    try:
                        os.remove(os.path.join(MKT_DIR, old))
                    except Exception:
                        pass
    except Exception as e:
        mylog(f"market memory: {type(e).__name__}: {e}")


def signal_members():
    """App-only members whose Signal package is running: they have no desk,
    so the robot's real trades reach them through the shared feed."""
    try:
        us = json.load(open(os.path.join(DIR, "owl_nest_users.json"), encoding="utf-8"))
        ents = json.load(open(os.path.join(DIR, "owl_entitlements.json"), encoding="utf-8"))
    except Exception:
        return []
    now = time.time()
    return [u["id"] for u in us if u.get("app_only") and u.get("id")
            and float((ents.get(u["id"]) or {}).get("manual_until") or 0) > now]


BOS_LOG = os.path.join(DIR, "bos_bot_kino.log")
FEED_F = os.path.join(DIR, "owl_signal_feed.json")
RX_ENTRY = re.compile(r"(?:^|\s)(BOS|FLIP-BOS) ENTRY: (BUY|SELL) [\d.]+ @ ~([\d.]+) SL ([\d.]+) TP ([\d.]+)")
RX_RESULT = re.compile(r"(?:^|\s)(WIN|LOSS) [+-]?[\d.]+ \(lot")
SIGNAL_LIFE = 1200      # a signal stays takeable for 20 minutes


def _feed_load():
    try:
        x = json.load(open(FEED_F, encoding="utf-8"))
        return x if isinstance(x, list) else []
    except Exception:
        return []


def _feed_save(lst):
    try:
        json.dump(lst[-200:], open(FEED_F + ".tmp", "w", encoding="utf-8"))
        os.replace(FEED_F + ".tmp", FEED_F)
    except Exception as e:
        mylog(f"signal feed save: {e}")


def _fmt_px(v):
    return f"{float(v):,.0f}".replace(",", "\u202f")


def feed_line(line):
    """One line of the master robot's log. A real entry becomes a signal for
    every Signal member (direction, entry, stop, target - no lot: they size
    it themselves); its WIN/LOSS line closes it. INT entries are off."""
    m = RX_ENTRY.search(line)
    if m:
        d = 1 if m.group(2) == "BUY" else -1
        now = int(time.time())
        item = {"t": now, "dir": d, "e": float(m.group(3)), "sl": float(m.group(4)),
                "tp": float(m.group(5)), "ok": True, "kind": m.group(1),
                "expires": now + SIGNAL_LIFE, "done": False, "n": []}
        who = signal_members()
        for uid in who:
            en = lang_of(uid) == "en"
            buy = d == 1
            title = ("\U0001f7e2 " + (("BUY" if buy else "SELL") + " signal" if en else
                     ("Signal \u00b7 ACHAT" if buy else "Signal \u00b7 VENTE")))
            body = (f"Entry ~{_fmt_px(item['e'])} \u00b7 stop {_fmt_px(item['sl'])} \u00b7 target {_fmt_px(item['tp'])}. Open the app." if en else
                    f"Entr\u00e9e ~{_fmt_px(item['e'])} \u00b7 stop {_fmt_px(item['sl'])} \u00b7 cible {_fmt_px(item['tp'])}. Ouvrez l\u2019app.")
            try:
                send_all(title, body, kind="instant", only_uid=uid, url=_tok_url(uid, ""))
                item["n"].append(uid)
            except Exception:
                pass
        lst = _feed_load()
        lst.append(item)
        _feed_save(lst)
        mylog(f"signal feed: {m.group(1)} {m.group(2)} -> {len(item['n'])} member(s)")
        return
    m = RX_RESULT.search(line)
    if m:
        lst = _feed_load()
        it = None
        for x in reversed(lst):
            if not x.get("done"):
                it = x
                break
        if it is None:
            return
        it["done"] = True
        it["outcome"] = "win" if m.group(1) == "WIN" else "loss"
        _feed_save(lst)
        win = it["outcome"] == "win"
        for uid in it.get("n") or []:
            en = lang_of(uid) == "en"
            if win:
                title = "\u2705 " + ("Signal over \u00b7 target reached" if en else "Signal termin\u00e9 \u00b7 cible atteinte")
            else:
                title = "\u26aa " + ("Signal over \u00b7 stop hit" if en else "Signal termin\u00e9 \u00b7 stop touch\u00e9")
            body = ("The trade is closed. The next signal will ring here." if en else
                    "Le trade est ferm\u00e9. Le prochain signal sonnera ici.")
            try:
                send_all(title, body, kind="instant", only_uid=uid, url=_tok_url(uid, ""))
            except Exception:
                pass


def is_manual(uid):
    """2026-09-27 (owner): two voices. An account in manual mode (its own
    pause file says paused, or its nest record is manual/semi) gets the
    signal-service voice; everyone else gets the robot's."""
    try:
        if json.load(open(os.path.join(DIR, f"owl_trading_pause_{uid}.json"),
                          encoding="utf-8")).get("paused"):
            return True
    except Exception:
        pass
    try:
        us = json.load(open(os.path.join(DIR, "owl_nest_users.json"),
                            encoding="utf-8"))
        # 2026-10-03 (owner): a Signal member (app-only, no MT5 account)
        # gets the signal-service voice while the package runs
        try:
            ents = json.load(open(os.path.join(DIR, "owl_entitlements.json"), encoding="utf-8"))
        except Exception:
            ents = {}
        return any(u.get("id") == uid and (u.get("mode") in ("manual", "semi")
                   or (u.get("app_only") and float((ents.get(uid) or {}).get("manual_until") or 0) > time.time()))
                   for u in us)
    except Exception:
        return False


def send_all(title, body, kind="instant", only_uid=None,
             skip_uids=None, url=None, image=None):
    try:
        subs = json.load(open(SUBS))
    except Exception:
        return
    try:
        prefs = json.load(open(os.path.join(DIR,
                                            "owl_push_prefs.json")))
    except Exception:
        prefs = {}
    changed = False
    total = 0
    _ib = {}
    if only_uid is not None:
        subs.setdefault(only_uid, [])
    for uid, lst in list(subs.items()):
        if only_uid is not None and uid != only_uid:
            continue
        if skip_uids and uid in skip_uids:
            continue
        if kind == "batch" and prefs.get(uid) == "important":
            continue    # this user only wants the big events
        # 2026-09-26: "silence la nuit" - 22:00-07:00 in the PHONE's own
        # timezone (the app sends its UTC offset with the preference)
        _ib.setdefault(str(uid), []).append({"t": int(time.time()), "kind": kind,
                                           "title": title, "body": body})
        q = (prefs.get("_quiet") or {}).get(uid) if isinstance(prefs, dict) else None
        if q and q.get("on"):
            lh = int(((time.time() - int(q.get("tz") or 0) * 60) // 3600) % 24)
            if lh >= 22 or lh < 7:
                continue
        keep = []
        for s in lst:
            try:
                resp = webpush(s, json.dumps({"title": title,
                                              "body": body,
                                              "tag": "owl",
                                              "url": url or "",
                                              "image": image or ""}),
                               vapid_private_key=VAPID_PEM,
                               vapid_claims=dict(CLAIMS), timeout=10)
                mylog(f"  {uid}: HTTP "
                      f"{getattr(resp, 'status_code', '?')}")
                keep.append(s)
                total += 1
            except WebPushException as e:
                code = getattr(getattr(e, "response", None),
                               "status_code", None)
                if code in (404, 410):
                    changed = True   # dead device: drop it
                else:
                    keep.append(s)
            except Exception:
                keep.append(s)
        subs[uid] = keep
    _inbox_write(_ib)
    if changed:
        try:
            json.dump(subs, open(SUBS, "w"))
        except Exception:
            pass
    # 2026-10-03 (owner): a member with no device still gets the inbox
    # line; that is not a push that went to nobody, so it is not logged
    # as one
    if only_uid is not None and total == 0 and not subs.get(only_uid):
        mylog(f"inbox '{title}' -> {only_uid} (no device)")
        return
    mylog(f"push '{title}' -> {total} device(s)")


RX_EXIT = re.compile(r"EXIT logged: ticket \d+ (\w+) "
                     r"profit (-?[\d.eE+]+)")


def instant_event(line):
    # 2026-09-27: the app's voice - no "soldat", no mechanics
    if "WEATHER: storm detected" in line:
        return ("\u26c8\ufe0f March\u00e9 tr\u00e8s agit\u00e9",
                "Le robot reste \u00e0 l'abri et attend que \u00e7a se calme.")
    if "WEATHER CLEAR" in line:
        return ("\U0001f324\ufe0f Le calme revient",
                "Le robot reprend le travail.")
    if "FUNDED FIGHTER:" in line:
        return ("\U0001f6e1\ufe0f Rattrapage en cours",
                "Le robot tente de r\u00e9cup\u00e9rer une partie des pertes.")
    if "FIGHTER WON" in line:
        if "EMPTY" in line:
            return ("\U0001f3c6 Rattrapage termin\u00e9",
                    "Toutes les pertes sont r\u00e9cup\u00e9r\u00e9es. "
                    "Le robot repasse en mode normal.")
        return ("\u2705 Une partie des pertes est rattrap\u00e9e",
                "Le robot continue.")
    if "FIGHTER lost" in line:
        return ("\u274c La tentative n'a pas march\u00e9",
                "\u00c7a arrive \u2014 le robot continue.")
    return None


WEEKLY_MARK = os.path.join(DIR, "owl_push_weekly.json")
SIGNAL_MARK = os.path.join(DIR, "owl_push_signal.json")
CHART_F = os.path.join(DIR, "owl_chart_btc.json")


def _package_gates(uid):
    """The two brakes of this account's package (owl_packages.json,
    'extends' chain), both default to on - and whether its robot takes
    internal-structure trades at all (off everywhere since 2026-09-30).
    Owner 2026-10-02: a signal must not ring, or hold, on a structure the
    member's robot does not trade."""
    try:
        p = json.load(open(os.path.join(DIR, "owl_packages.json"),
                           encoding="utf-8"))
        name = (p.get("accounts") or {}).get(uid, "base")
        out, seen = {}, set()
        chain = []
        while name and name not in seen:
            seen.add(name)
            pk = (p.get("packages") or {}).get(name) or {}
            chain.append(pk)
            name = pk.get("extends") or ("base" if name != "base" else None)
        for pk in reversed(chain):
            out.update(pk)
        return bool(out.get("nervosity", True)), bool(out.get("movement", True)), bool(out.get("internal_entries", False))
    except Exception:
        return True, True, False


def maybe_signal():
    """2026-09-27 (owner): in manual mode the app is a signal service, so it
    must RING when the market card turns 'Feu vert' - and say when it is
    over. Same reading as the app's weather card (storm > brakes > movement
    > internal state), per account, one push per 30 min at most."""
    try:
        if time.time() - os.path.getmtime(CHART_F) > 180:
            return
        cj = json.load(open(CHART_F, encoding="utf-8"))
    except Exception:
        return
    vn, vr = cj.get("vol_now") or 0, cj.get("vol_ref") or 0
    rv = (vn / max(vr, 1)) if vn and vr else 1.0
    storm = rv >= 1.85
    int_seen = bool(cj.get("int_trend"))
    try:
        st = json.load(open(SIGNAL_MARK, encoding="utf-8"))
    except Exception:
        st = {}
    try:
        subs = json.load(open(SUBS))
    except Exception:
        return
    changed = False
    for uid in subs:
        if not is_manual(uid) or uid in signal_members():
            continue
        gN, gM, gI = _package_gates(uid)
        # the internal structure only counts for a robot that trades it
        has_int = int_seen and gI
        int_ok = (not has_int) or (cj.get("int_state") in (None, "ready"))
        nerv_bad = storm or (gN and rv > 1.0)
        mv_ok = True if not gM else (
            (cj.get("int_brk_1h") or 0) >= 1 if has_int
            else (cj.get("moves_2h") or 0) >= 1)
        ready = (not nerv_bad) and mv_ok and int_ok
        rec = st.get(uid) or {}
        prev = rec.get("ready")
        if prev is None:
            st[uid] = {"ready": ready, "t": 0}
            changed = True
            continue
        if ready == prev:
            continue
        st[uid] = {"ready": ready, "t": rec.get("t", 0), "rang": rec.get("rang", False)}
        changed = True
        # one "playable" ring per half hour; "over" is only sent after a ring
        # and is never held back by that throttle
        if ready:
            if time.time() - (rec.get("t") or 0) < 1800:
                continue
            st[uid]["t"] = time.time()
            st[uid]["rang"] = True
        else:
            if not rec.get("rang"):
                continue
            st[uid]["rang"] = False
        en = lang_of(uid) == "en"
        if ready:
            send_all("\U0001f7e2 " + ("Playable signal" if en else "Signal jouable"),
                     ("Conditions are met. Open the chart to decide." if en else
                      "Les conditions sont r\u00e9unies. Ouvrez le graphique "
                      "pour d\u00e9cider."), kind="instant", only_uid=uid,
                     url=_tok_url(uid, "chart"))
        else:
            send_all("\u26aa " + ("Signal over" if en else "Signal termin\u00e9"),
                     ("The green light has passed \u2014 better wait for the next one." if en else
                      "Le feu vert est pass\u00e9 \u2014 mieux vaut attendre "
                      "le prochain."), kind="instant", only_uid=uid)
    if changed:
        try:
            json.dump(st, open(SIGNAL_MARK, "w", encoding="utf-8"))
        except Exception:
            pass



def _week_image(uid):
    """2026-09-27: the week card the member's phone uploaded this week."""
    try:
        for u in json.load(open(os.path.join(DIR, "owl_nest_users.json"),
                                encoding="utf-8")):
            if u.get("id") == uid and u.get("token"):
                p = os.path.join(DIR, "nest_data", f"week_{uid}.png")
                if time.time() - os.path.getmtime(p) < 8 * 86400:
                    return f"/{u['token']}/week.png"
    except Exception:
        pass
    return None


def _tok_url(uid, suffix=""):
    """2026-09-28: a push that opens one member's page (chart, Le Nid...)."""
    try:
        for u in json.load(open(os.path.join(DIR, "owl_nest_users.json"),
                                encoding="utf-8")):
            if u.get("id") == uid and u.get("token"):
                return f"/{u['token']}/{suffix}"
    except Exception:
        pass
    return None


DIGEST_MARK = os.path.join(DIR, "owl_push_digest.json")
PKG_USD = {"manual": 29, "strategy": 49}    # keep in step with owl_app_server.PACKAGES


def digest_body(now=None):
    """2026-09-28: the owner's Monday digest - packages, money, signals,
    renewals, waiting list. Pure: reads the data files, returns the text."""
    now = now or time.time()
    W = 7 * 86400
    try:
        ents = json.load(open(os.path.join(DIR, "owl_entitlements.json"), encoding="utf-8"))
    except Exception:
        ents = {}
    try:
        names = {u["id"]: u.get("name", u["id"]) for u in
                 json.load(open(os.path.join(DIR, "owl_nest_users.json"), encoding="utf-8"))}
    except Exception:
        names = {}
    act = {"family": 0, "manual": 0, "strategy": 0}
    due, new = [], 0
    for uid, e in ents.items():
        if uid in ("kino", "std") or not isinstance(e, dict):
            continue
        if float(e.get("updated") or 0) > now - W:
            new += 1
        for k in act:
            u_ = float(e.get(k + "_until") or 0)
            if u_ > now:
                act[k] += 1
                if u_ - now < W:
                    due.append(f"{names.get(uid, uid)} ({int((u_ - now) // 86400)} j)")
    try:
        cfg = json.load(open(os.path.join(DIR, "owl_nest_config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    mrr = (act["manual"] * PKG_USD["manual"] + act["strategy"] * PKG_USD["strategy"]
           + act["family"] * float(cfg.get("family_usd") or 0))
    paid_n, paid_usd = 0, 0.0
    try:
        for p in json.load(open(os.path.join(DIR, "owl_payments.json"), encoding="utf-8")):
            if (isinstance(p, dict) and p.get("granted") in PKG_USD and not p.get("test")
                    and float(p.get("t") or 0) > now - W):
                paid_n += 1
                paid_usd += float(p.get("amount") or 0)
    except Exception:
        pass
    sent = taken = 0
    import glob as _gl
    for f in _gl.glob(os.path.join(DIR, "owl_signals_*.json")):
        uid = os.path.basename(f)[len("owl_signals_"):-5]
        try:
            lst = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        try:
            marks = json.load(open(os.path.join(DIR, f"owl_sigmarks_{uid}.json"), encoding="utf-8"))
        except Exception:
            marks = {}
        for x in lst:
            if not isinstance(x, dict) or not x.get("ok") or float(x.get("t") or 0) < now - W:
                continue
            sent += 1
            if x.get("taken") or (marks.get(str(x.get("t"))) or {}).get("taken"):
                taken += 1
    try:
        wl = len(json.load(open(os.path.join(DIR, "owl_waitlist.json"), encoding="utf-8")) or {})
    except Exception:
        wl = 0
    return (f"Actifs : {act['family']} auto \u00b7 {act['manual']} manuel \u00b7 {act['strategy']} strat\u00e9gie "
            f"\u00b7 MRR ${mrr:.0f}. 7 jours : {new} activation(s), {paid_n} paiement(s) ${paid_usd:.0f}, "
            f"{sent} signaux / {taken} pris. "
            + (("\u00c0 renouveler sous 7 j : " + ", ".join(due) + ". ") if due else "Aucun renouvellement sous 7 j. ")
            + (f"Liste d\u2019attente : {wl}." if wl else "")).strip()


def maybe_digest():
    """Monday >= 07:00 UTC: one digest push to the owner (kino + std)."""
    t = time.gmtime()
    if t.tm_wday != 0 or t.tm_hour < 7:
        return
    wk = time.strftime("%Y-%W", t)
    try:
        if json.load(open(DIGEST_MARK)).get("sent") == wk:
            return
    except Exception:
        pass
    body = digest_body()
    for o in ("kino", "std"):
        try:
            send_all("\U0001f4ca Lundi \u00b7 OwlNest", body, kind="instant", only_uid=o,
                     url=_tok_url(o, "#nid"))
        except Exception:
            pass
    try:
        json.dump({"sent": wk, "t": int(time.time())}, open(DIGEST_MARK, "w"))
    except Exception:
        pass
    mylog("digest sent: " + body)


def _hist_url(uid):
    """2026-09-27: the weekly push opens the member's Historique (the week
    card lights up there)."""
    try:
        for u in json.load(open(os.path.join(DIR, "owl_nest_users.json"),
                                encoding="utf-8")):
            if u.get("id") == uid and u.get("token"):
                return f"/{u['token']}/#hist"
    except Exception:
        pass
    return None


def maybe_weekly():
    """Sunday >= 20:00 UTC: one weekly report push."""
    t = time.gmtime()
    if t.tm_wday != 6 or t.tm_hour < 20:
        return
    wk = time.strftime("%Y-%W", t)
    try:
        if json.load(open(WEEKLY_MARK)).get("sent") == wk:
            return
    except Exception:
        pass
    try:
        subs = json.load(open(SUBS))
        for uid in subs:
            src = "kino" if uid in ("kino", "std") else uid
            try:
                d = json.load(open(os.path.join(
                    DIR, "nest_data", src + ".json")))
            except Exception:
                continue
            week = float(d.get("week") or 0.0)
            days = d.get("days") or []
            g = sum(1 for x in days if x.get("p", 0) > 0)
            r = sum(1 for x in days if x.get("p", 0) < 0)
            if lang_of(uid) == "en":
                send_all(f"\U0001f4ca Your week: {week:+.2f} $",
                         f"{g} green day{'s' if g > 1 else ''}, {r} red. "
                         + (("The account is moving forward." if week >= 0 else "You are catching up.")
                            if is_manual(uid) else
                            ("The robot is moving forward." if week >= 0 else "The robot is catching up."))
                         + " Tap to share your week.",
                         only_uid=uid, url=_hist_url(uid), image=_week_image(uid))
                continue
            send_all(f"\U0001f4ca Votre semaine : {week:+.2f} $",
                     f"{g} jour{'s' if g > 1 else ''} vert"
                     f"{'s' if g > 1 else ''}, {r} rouge"
                     f"{'s' if r > 1 else ''}. "
                     + (("Le compte avance." if week >= 0 else "Vous vous rattrapez.")
                        if is_manual(uid) else
                        ("Le robot avance." if week >= 0 else "Le robot se rattrape."))
                     + " Touchez pour partager votre semaine.",
                     only_uid=uid, url=_hist_url(uid), image=_week_image(uid))
        json.dump({"sent": wk}, open(WEEKLY_MARK, "w"))
    except Exception as e:
        mylog(f"weekly failed: {e}")


PROOF_MARK = os.path.join(DIR, "owl_push_proof.json")


def maybe_proof_weekly():
    """Sunday >= 20:30 UTC: the week's proof in four numbers (owner 2026-09-29).
    Read-only from lab/proof.json, which the nightly run rebuilds."""
    t = time.gmtime()
    if t.tm_wday != 6 or t.tm_hour < 20 or (t.tm_hour == 20 and t.tm_min < 30):
        return
    wk = time.strftime("%Y-%W", t)
    try:
        if json.load(open(PROOF_MARK)).get("sent") == wk:
            return
    except Exception:
        pass
    try:
        p = json.load(open(os.path.join(DIR, "lab", "proof.json"), encoding="utf-8"))
    except Exception:
        return
    full = (p.get("base") or {}).get("full") or {}
    un = p.get("union") or {}
    days = round(p.get("days") or 0)
    if not full.get("trades"):
        return
    try:
        subs = json.load(open(SUBS))
    except Exception:
        return
    sent = 0
    for uid in list(subs):
        try:
            if lang_of(uid) == "en":
                title = "\U0001f4d0 The week's proof"
                body = (f"Tested on the past: {full['net']:+.0f} $ over {days} days, "
                        f"{full.get('wr', 0):.0f} % of trades won. "
                        f"In real life: {un.get('trades', 0)} trades, {un.get('net', 0):+.0f} $. "
                        "Tap to read the full report.")
            else:
                title = "\U0001f4d0 La preuve de la semaine"
                body = (f"Testée sur le passé : {full['net']:+.0f} $ sur {days} jours, "
                        f"{full.get('wr', 0):.0f} % de trades gagnés. "
                        f"En vrai : {un.get('trades', 0)} trades, {un.get('net', 0):+.0f} $. "
                        "Touchez pour lire le rapport complet.")
            send_all(title, body, kind="batch", only_uid=uid, url=_tok_url(uid, "#robot"))
            sent += 1
        except Exception:
            continue
    json.dump({"sent": wk}, open(PROOF_MARK, "w"))
    mylog(f"proof weekly -> {sent} member(s)")


MORNING_MARK = os.path.join(DIR, "owl_push_morning.json")


def maybe_morning():
    """Every day between 06:00 and 12:00 UTC, one good-morning push
    with the overnight story of both accounts."""
    t = time.gmtime()
    if not (6 <= t.tm_hour < 12):
        return
    day = time.strftime("%Y-%m-%d", t)
    try:
        if json.load(open(MORNING_MARK)).get("sent") == day:
            return
    except Exception:
        pass
    try:
        parts = []
        for uid, label in (("kino", "Pro"), ("std", "Standard")):
            try:
                d = json.load(open(os.path.join(
                    DIR, "nest_data", uid + ".json")))
                today = float(d.get("today") or 0.0)
                n = sum(1 for x in (d.get("trades") or [])
                        if x.get("w", "").startswith(
                            time.strftime("%d/%m", t)))
                parts.append(f"{label} {today:+.2f} $ "
                             f"({n} trade{'s' if n > 1 else ''})")
            except Exception:
                continue
        if not parts:
            return
        send_all("\u2600\ufe0f Bonjour !",
                 "Pendant la nuit : " + " \u00b7 ".join(parts)
                 + ". Bonne journ\u00e9e !", only_uid="kino")
        json.dump({"sent": day}, open(MORNING_MARK, "w"))
    except Exception as e:
        mylog(f"morning failed: {e}")


_member_today = {}
EVENING_MARK = os.path.join(DIR, "owl_push_evening.json")


def maybe_evening():
    """Owner 2026-09-26: one 'Bilan du jour' push per member, in the plain
    voice of the app, between 18:30 and 23:00 UTC. Routine (kind=batch), so
    members on 'important seulement' don't get it."""
    t = time.gmtime()
    if not (t.tm_hour > 18 or (t.tm_hour == 18 and t.tm_min >= 30)):
        return
    if t.tm_hour >= 23:
        return
    day = time.strftime("%Y-%m-%d", t)
    try:
        if json.load(open(EVENING_MARK)).get("sent") == day:
            return
    except Exception:
        pass
    try:
        subs = json.load(open(SUBS))
        label = (["lun", "mar", "mer", "jeu", "ven", "sam", "dim"][t.tm_wday]
                 + " " + time.strftime("%d/%m", t))
        for uid in subs:
            src = "kino" if uid in ("kino", "std") else uid
            try:
                d = json.load(open(os.path.join(DIR, "nest_data", src + ".json")))
            except Exception:
                continue
            today = float(d.get("today") or 0.0)
            tr = (d.get("day_trades") or {}).get(label) or []
            n = len(tr)
            g = sum(1 for x in tr if float(x.get("p") or 0) > 0.005)
            man = is_manual(uid)
            en = lang_of(uid) == "en"
            if n == 0:
                body = (("No confirmed signal today. See you tomorrow!" if man else
                         "Today the robot watched the market without trading. See you tomorrow!") if en else
                        ("Aujourd'hui, aucun signal confirm\u00e9. \u00c0 demain !" if man else
                        "Aujourd'hui, le robot a surveill\u00e9 le march\u00e9 "
                        "sans trader. \u00c0 demain !"))
            elif en:
                body = (f"Today: {today:+.2f} $ \u00b7 {n} trade{'s' if n > 1 else ''}"
                        + (f", {g} won" if n > 1 else (" (won)" if g else " (lost)"))
                        + (". Good evening!" if man else ". The robot is done for the day."))
            else:
                body = (f"Aujourd'hui : {today:+.2f} $ \u00b7 {n} trade"
                        f"{'s' if n > 1 else ''}"
                        + (f", dont {g} gagn\u00e9{'s' if g > 1 else ''}" if n > 1 else
                           (" (gagn\u00e9)" if g else " (perdu)"))
                        + (". Bonne soir\u00e9e !" if man else ". Le robot a fini sa journ\u00e9e."))
            send_all("\U0001f319 " + ("Daily review" if en else "Bilan du jour"), body, kind="batch", only_uid=uid)
        json.dump({"sent": day}, open(EVENING_MARK, "w"))
    except Exception as e:
        mylog(f"evening failed: {e}")



def member_trades():
    """Per-member personalized pushes: watch each subscribed family
    member's own nest stats and push THEIR deltas (their scale)."""
    try:
        subs = json.load(open(SUBS))
    except Exception:
        return
    for uid in subs:
        if uid in ("kino", "std"):
            continue    # the master hears the log-based pushes
        try:
            nd = json.load(open(os.path.join(DIR, "nest_data",
                                             uid + ".json")))
            t = round(float(nd.get("today") or 0.0), 2)
        except Exception:
            continue
        prev = _member_today.get(uid)
        _member_today[uid] = t
        if prev is None:
            continue
        delta = round(t - prev, 2)
        if abs(delta) < 0.01 or (t == 0 and abs(prev) > 0.01):
            continue    # no change, or day rollover
        # 2026-09-27: same voice as the app's toast
        if lang_of(uid) == "en":
            title = (f"\u2705 Trade closed \u00b7 +{delta:.2f} $" if delta > 0
                     else f"\u274c Trade closed \u00b7 {delta:.2f} $")
            body = (f"Today: {t:+.2f} $. Well played." if delta > 0
                    else (f"Today: {t:+.2f} $. It happens." if is_manual(uid)
                          else f"Today: {t:+.2f} $. It happens \u2014 the robot carries on."))
        else:
            title = (f"\u2705 Trade termin\u00e9 \u00b7 +{delta:.2f} $" if delta > 0
                     else f"\u274c Trade termin\u00e9 \u00b7 {delta:.2f} $")
            body = (f"Aujourd'hui : {t:+.2f} $. Bien jou\u00e9." if delta > 0
                    else (f"Aujourd'hui : {t:+.2f} $. \u00c7a arrive." if is_manual(uid)
                          else f"Aujourd'hui : {t:+.2f} $. \u00c7a arrive \u2014 le robot continue."))
        send_all(title, body, kind="batch", only_uid=uid)
        _wake_chercheur()


_wake_last = {"t": 0.0}


def _wake_chercheur():
    """2026-10-04 (owner): a closed trade wakes the chercheur now, not at
    the next half-hour. wake.py keeps its own rules (20-minute gap, ten
    looks a day, never during the night run, one at a time); this only
    knocks - at most once a minute, so a mirrored close on two accounts
    is one knock."""
    now = time.time()
    if now - _wake_last["t"] < 60:
        return
    _wake_last["t"] = now
    try:
        subprocess.Popen([sys.executable, os.path.join(DIR, "lab", "wake.py")], cwd=DIR,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        mylog(f"wake knock failed: {e}")


DAYDONE_MARK = os.path.join(DIR, "owl_push_dayclose.json")
# Which state file belongs to which account. There is NO rule to derive
# this: the first live bot writes bos_state.json with no suffix, and
# Valere's account id is u224016179 while its bot variant is "valere". An
# earlier draft guessed with a fallback chain and would have pushed one
# account's day to another member - so the map is explicit, and it mirrors
# BOT_OF in owl_app_server.py. Add an account there, add it here.
DAY_STATE_OF = {
    "kino": "bos_state_kino.json",
    "bos": "bos_state.json",
    "u224016179": "bos_state_valere.json",
    "demo": "bos_state_demo.json",
    "infinity": "bos_state_infinity.json",
    "expenses": "bos_state_expenses.json",
}


def maybe_day_close():
    """One push per account per day, the moment the robot stops for the day.

    Owner 2026-10-01: silence and a dead bot look identical on a phone, so
    the end of a good day should say so. `day_capped` is the bot's own
    flag - set when the daily limit actually refused an entry, cleared at
    the UTC day roll - so this fires on the event the robot acted on, with
    the adaptive cap included rather than the package number.
    """
    try:
        subs = json.load(open(SUBS))
    except Exception:
        return
    day = time.strftime("%Y-%m-%d", time.gmtime())
    try:
        mark = json.load(open(DAYDONE_MARK, encoding="utf-8"))
    except Exception:
        mark = {}
    if mark.get("day") != day:
        mark = {"day": day, "sent": []}
    changed = False
    for uid in subs:
        if uid in mark["sent"]:
            continue
        name = DAY_STATE_OF.get(uid)
        if not name:
            continue          # no structure bot on this account
        f = os.path.join(DIR, name)
        try:
            st = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if st.get("day_key") != day or not st.get("day_capped"):
            continue
        if st.get("killed"):
            continue          # the kill has its own alarm; not a good day
        pnl = float(st.get("day_pnl") or 0.0)
        if lang_of(uid) == "en":
            title = f"\u2705 Day complete \u00b7 {pnl:+.2f} $"
            body = ("Target reached \u2014 the robot is done for today. "
                    "It starts again at 00:00 UTC.")
        else:
            title = f"\u2705 Journ\u00e9e termin\u00e9e \u00b7 {pnl:+.2f} $"
            body = ("Objectif atteint \u2014 le robot a fini sa journ\u00e9e. "
                    "\u00c0 demain \u00e0 00:00 UTC.")
        send_all(title, body, kind="batch", only_uid=uid)
        mark["sent"].append(uid)
        changed = True
    if changed:
        try:
            json.dump(mark, open(DAYDONE_MARK, "w", encoding="utf-8"))
        except Exception:
            pass


def main():
    mylog("notifier started")
    # two live accounts (2026-09-07): Pro (flagship, no prefix) and
    # Standard (prefixed) - one notifier tails both logs
    sources = []
    for path, pfx, uid in ((LOG, "", "kino"),
                           (os.path.join(DIR, "owl_std.log"),
                            "\U0001f948 Standard \u2014 ", "std")):
        try:
            fh = open(path, "r", encoding="utf-8", errors="replace")
            fh.seek(0, 2)
            sources.append({"f": fh, "pfx": pfx, "uid": uid,
                            "batch": [], "t0": None})
        except Exception:
            pass
    # watchdog restarts: any "starting X" line in boot_all.log means
    # something was found dead and revived - tell the master
    try:
        _bf = open(os.path.join(DIR, "boot_all.log"), "r",
                   encoding="utf-8", errors="replace")
        _bf.seek(0, 2)
    except Exception:
        _bf = None
    try:
        _sf = open(BOS_LOG, "r", encoding="utf-8", errors="replace")
        _sf.seek(0, 2)
    except Exception:
        _sf = None
    _wk_last = 0.0
    _mb_last = 0.0
    _sg_last = 0.0
    while True:
        if _sf is not None:
            while True:
                _l = _sf.readline()
                if not _l:
                    break
                try:
                    feed_line(_l)
                except Exception as e:
                    mylog(f"signal feed: {type(e).__name__}: {e}")
        if time.time() - _wk_last > 600:
            _wk_last = time.time()
            maybe_weekly()
            maybe_proof_weekly()
            maybe_digest()
            maybe_morning()
            maybe_evening()
        if time.time() - _mb_last > 12:
            _mb_last = time.time()
            member_trades()
            # 2026-09-27: pushes queued by the app server (e.g. a payment activated)
            _qf = os.path.join(DIR, "owl_push_queue.json")
            try:
                _q = json.load(open(_qf, encoding="utf-8"))
            except Exception:
                _q = []
            if _q:
                try:
                    os.remove(_qf)
                except Exception:
                    pass
                for it in _q:
                    try:
                        send_all(it.get("title") or "OwlNest", it.get("body") or "",
                                 kind="instant", only_uid=it.get("uid"))
                    except Exception:
                        pass
        if time.time() - _sg_last > 60:
            _sg_last = time.time()
            maybe_signal()
            maybe_health()
            maybe_demo_reset()
            maybe_renewals()
            maybe_share()
            maybe_launch_report()
            maybe_waitlist()
            maybe_day_close()
            market_memory_tick()
        if _bf is not None:
            while True:
                bl = _bf.readline()
                if not bl:
                    break
                if "UI CHECK FAILED" in bl:
                    send_all("\u26a0\ufe0f V\u00e9rification de l'app",
                             "La v\u00e9rification automatique a \u00e9chou\u00e9 apr\u00e8s le "
                             "d\u00e9marrage - voir owl_ui_check.log.", kind="instant", only_uid="kino")
                elif "starting" in bl:
                    send_all("⚠️ Redémarrage",
                             "Le gardien a relancé : "
                             + bl.split("starting", 1)[-1].strip(), only_uid="kino")
        got = False
        for s in sources:
            while True:
                line = s["f"].readline()
                if not line:
                    break
                got = True
                ev = instant_event(line)
                if ev is not None:
                    send_all(s["pfx"] + ev[0], ev[1], only_uid="kino")
                    continue
                m = RX_EXIT.search(line)
                if m:
                    # 2026-09-07 user: instant per-trade pushes (the
                    # calm-only era trades ~3-6x/day - no spam risk);
                    # "Important seulement" users still skip these
                    try:
                        p = float(m.group(2))
                    except Exception:
                        continue
                    if p > 0.005:
                        title = f"\U0001f4b0 +{p:.2f} $"
                    elif p < -0.005:
                        title = f"\U0001f6e1\ufe0f {p:.2f} $"
                    else:
                        title = "\u26aa 0,00 $"
                    body = "Trade termin\u00e9."
                    try:
                        nd = json.load(open(os.path.join(
                            DIR, "nest_data", s["uid"] + ".json")))
                        body = (f"Aujourd'hui : "
                                f"{float(nd.get('today') or 0):+.2f}"
                                f" $")
                    except Exception:
                        pass
                    # master log numbers go only to the master; family
                    # members get their OWN account's numbers via the
                    # per-member watcher below (2026-09-07 go-live)
                    send_all(s["pfx"] + title, body, kind="batch",
                             only_uid="kino")
        if not got:
            time.sleep(2)


if __name__ == "__main__":
    main()
