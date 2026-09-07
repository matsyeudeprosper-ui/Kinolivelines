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


def send_all(title, body, kind="instant"):
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
        d = json.load(open(os.path.join(DIR, "nest_data",
                                        "kino.json")))
        week = float(d.get("week") or 0.0)
        days = d.get("days") or []
        g = sum(1 for x in days if x.get("p", 0) > 0)
        r = sum(1 for x in days if x.get("p", 0) < 0)
        title = (f"\U0001f4ca Votre semaine : {week:+.2f} $")
        body = (f"{g} jour{'s' if g > 1 else ''} vert"
                f"{'s' if g > 1 else ''}, {r} rouge"
                f"{'s' if r > 1 else ''}. Bonne semaine !")
        send_all(title, body)
        json.dump({"sent": wk}, open(WEEKLY_MARK, "w"))
    except Exception as e:
        mylog(f"weekly failed: {e}")


def main():
    mylog("notifier started")
    # two live accounts (2026-09-07): Pro (flagship, no prefix) and
    # Standard (prefixed) - one notifier tails both logs
    sources = []
    for path, pfx in ((LOG, ""),
                      (os.path.join(DIR, "owl_std.log"),
                       "\U0001f948 Standard \u2014 ")):
        try:
            fh = open(path, "r", encoding="utf-8", errors="replace")
            fh.seek(0, 2)
            sources.append({"f": fh, "pfx": pfx, "batch": [],
                            "t0": None})
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
    while True:
        if time.time() - _wk_last > 600:
            _wk_last = time.time()
            maybe_weekly()
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
                    try:
                        s["batch"].append(float(m.group(2)))
                    except Exception:
                        continue
                    if s["t0"] is None:
                        s["t0"] = time.time()
            if s["batch"] and time.time() - s["t0"] >= BATCH_SECS:
                n = len(s["batch"])
                tot = sum(s["batch"])
                wins = sum(1 for p in s["batch"] if p > 0)
                title = s["pfx"] + (f"\U0001f4b0 {tot:+.2f} $"
                                    if tot >= 0
                                    else f"\U0001f4c9 {tot:+.2f} $")
                body = (f"{n} trade{'s' if n > 1 else ''} "
                        f"({wins} gagn\u00e9"
                        f"{'s' if wins > 1 else ''}) sur les 10 "
                        f"derni\u00e8res minutes.")
                send_all(title, body, kind="batch")
                s["batch"], s["t0"] = [], None
        if not got:
            time.sleep(2)


if __name__ == "__main__":
    main()
