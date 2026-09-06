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


def send_all(title, body):
    try:
        subs = json.load(open(SUBS))
    except Exception:
        return
    changed = False
    total = 0
    for uid, lst in list(subs.items()):
        keep = []
        for s in lst:
            try:
                webpush(s, json.dumps({"title": title, "body": body,
                                       "tag": "owl"}),
                        vapid_private_key=VAPID_PEM,
                        vapid_claims=dict(CLAIMS), timeout=10)
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


def main():
    mylog("notifier started")
    f = open(LOG, "r", encoding="utf-8", errors="replace")
    f.seek(0, 2)
    batch = []
    batch_t0 = None
    while True:
        line = f.readline()
        if not line:
            if batch and time.time() - batch_t0 >= BATCH_SECS:
                n = len(batch)
                tot = sum(batch)
                wins = sum(1 for p in batch if p > 0)
                title = (f"\U0001f4b0 {tot:+.2f} $"
                         if tot >= 0 else f"\U0001f4c9 {tot:+.2f} $")
                body = (f"{n} trade{'s' if n > 1 else ''} "
                        f"({wins} gagn\u00e9{'s' if wins > 1 else ''}) "
                        f"sur les 10 derni\u00e8res minutes.")
                send_all(title, body)
                batch, batch_t0 = [], None
            time.sleep(2)
            continue
        ev = instant_event(line)
        if ev is not None:
            send_all(*ev)
            continue
        m = RX_EXIT.search(line)
        if m:
            try:
                p = float(m.group(2))
            except Exception:
                continue
            batch.append(p)
            if batch_t0 is None:
                batch_t0 = time.time()


if __name__ == "__main__":
    main()
