"""owl_push_notifier.py - phone push notifications for OwlNest.

Tails owl_manual.log and sends web-push notifications (French, easy
words) to every subscribed device in owl_push_subs.json:
  - immediately: storms, storm-lift, funded fighters, fighter results
  - batched (10 min): trade exits, summed into one message
Dead subscriptions (410/404) are pruned automatically.
"""
import json
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
                                       ("manual_until", "Manuel", "Manual")):
            until = float(e.get(key) or 0)
            if not until:
                continue
            if key == "manual_until" and float(e.get("strategy_until") or 0) > now:
                continue          # covered by the strategy package
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
                             ("The robot is paused on your account. Settle with Kino and enter the renewal code in the app."
                              if en else "Le robot est en pause sur votre compte. R\u00e9glez Kino et entrez le code de renouvellement dans l'app."),
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
                             ("Settle with Kino now, then enter the code he sends you, to avoid an interruption."
                              if en else "R\u00e9glez Kino d\u00e8s maintenant, puis entrez le code qu'il vous enverra, pour \u00e9viter une coupure."),
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
        return any(u.get("id") == uid and u.get("mode") in ("manual", "semi")
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
    'extends' chain); both default to on."""
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
        return bool(out.get("nervosity", True)), bool(out.get("movement", True))
    except Exception:
        return True, True


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
    has_int = bool(cj.get("int_trend"))
    int_ok = (not has_int) or (cj.get("int_state") in (None, "ready"))
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
        if not is_manual(uid):
            continue
        gN, gM = _package_gates(uid)
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
        st[uid] = {"ready": ready, "t": rec.get("t", 0)}
        changed = True
        if time.time() - (rec.get("t") or 0) < 1800:
            continue        # one push per half hour, the state still moves
        st[uid]["t"] = time.time()
        en = lang_of(uid) == "en"
        if ready:
            send_all("\U0001f7e2 " + ("Playable signal" if en else "Signal jouable"),
                     ("Conditions are met. Open the chart to decide." if en else
                      "Les conditions sont r\u00e9unies. Ouvrez le graphique "
                      "pour d\u00e9cider."), kind="instant", only_uid=uid)
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
                 + ". Bonne journ\u00e9e !")
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
    _wk_last = 0.0
    _mb_last = 0.0
    _sg_last = 0.0
    while True:
        if time.time() - _wk_last > 600:
            _wk_last = time.time()
            maybe_weekly()
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
                             + bl.split("starting", 1)[-1].strip())
        got = False
        for s in sources:
            while True:
                line = s["f"].readline()
                if not line:
                    break
                got = True
                ev = instant_event(line)
                if ev is not None:
                    send_all(s["pfx"] + ev[0], ev[1])
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
