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


def send_all(title, body, kind="instant", only_uid=None,
             skip_uids=None):
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
    for uid, lst in list(subs.items()):
        if only_uid is not None and uid != only_uid:
            continue
        if skip_uids and uid in skip_uids:
            continue
        if kind == "batch" and prefs.get(uid) == "important":
            continue    # this user only wants the big events
        keep = []
        for s in lst:
            try:
                resp = webpush(s, json.dumps({"title": title,
                                              "body": body,
                                              "tag": "owl"}),
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
    if changed:
        try:
            json.dump(subs, open(SUBS, "w"))
        except Exception:
            pass
    mylog(f"push '{title}' -> {total} device(s)")


RX_EXIT = re.compile(r"EXIT logged: ticket \d+ (\w+) "
                     r"profit (-?[\d.eE+]+)")


def instant_event(line):
    if "WEATHER: storm detected" in line:
        return ("\u26c8\ufe0f Orage", "Le march\u00e9 s'agite trop - "
                "le robot se met \u00e0 l'abri et attend.")
    if "WEATHER CLEAR" in line:
        return ("\U0001f324\ufe0f L'orage est pass\u00e9",
                "Le robot reprend le travail.")
    if "FUNDED FIGHTER:" in line:
        return ("\u2694\ufe0f Un soldat part au combat",
                "Sa tentative est d\u00e9j\u00e0 pay\u00e9e d'avance "
                "par les petits gains.")
    if "FIGHTER WON" in line:
        if "EMPTY" in line:
            return ("\U0001f3c6 Le soldat a gagn\u00e9 !",
                    "Toutes les pertes sont rattrap\u00e9es.")
        return ("\u2694\ufe0f Le soldat a gagn\u00e9",
                "Une partie des pertes est rattrap\u00e9e.")
    if "FIGHTER lost" in line:
        return ("\U0001f6e1\ufe0f Le soldat a perdu",
                "Pas de panique : le coup \u00e9tait pay\u00e9 "
                "d'avance. On recommence \u00e0 \u00e9conomiser.")
    return None


WEEKLY_MARK = os.path.join(DIR, "owl_push_weekly.json")


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
            send_all(f"\U0001f4ca Votre semaine : {week:+.2f} $",
                     f"{g} jour{'s' if g > 1 else ''} vert"
                     f"{'s' if g > 1 else ''}, {r} rouge"
                     f"{'s' if r > 1 else ''}. Bonne semaine !",
                     only_uid=uid)
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
        send_all("☀️ Bonjour ! Pendant la nuit :",
                 " · ".join(parts)
                 + ". Bonne journée !")
        json.dump({"sent": day}, open(MORNING_MARK, "w"))
    except Exception as e:
        mylog(f"morning failed: {e}")


_member_today = {}


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
        title = (f"\U0001f4b0 +{delta:.2f} $" if delta > 0
                 else f"\U0001f6e1️ {delta:.2f} $")
        send_all(title, f"Aujourd'hui : {t:+.2f} $ (votre compte)",
                 kind="batch", only_uid=uid)


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
    while True:
        if time.time() - _wk_last > 600:
            _wk_last = time.time()
            maybe_weekly()
            maybe_morning()
        if time.time() - _mb_last > 12:
            _mb_last = time.time()
            member_trades()
        if _bf is not None:
            while True:
                bl = _bf.readline()
                if not bl:
                    break
                if "starting" in bl:
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
