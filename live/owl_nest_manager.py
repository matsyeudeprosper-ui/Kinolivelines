"""owl_nest_manager.py - keeps one stats worker alive per OwlNest user.

Reads owl_nest_users.json every 30s; spawns owl_nest_worker.py <id> for
each user and restarts any that died. Adding a family member = add their
entry to the json; the manager picks them up within 30s, no restart.
Workers are READ-ONLY (stats only, no trading).
"""
import json, os, subprocess, sys, time

DUCK = os.path.join(r"C:\Projects\KinoliveLines\live", "owl_duckdns.json")
_last_ping = 0.0


def duck_ping(say):
    """Keep the DuckDNS domains alive forever (12h heartbeat)."""
    global _last_ping
    if time.time() - _last_ping < 12 * 3600:
        return
    _last_ping = time.time()
    try:
        c = json.load(open(DUCK))
        url = (f"https://www.duckdns.org/update?domains={c['domains']}"
               f"&token={c['token']}&ip={c['ip']}")
        r = subprocess.run(["curl", "-s", "-m", "20", url],
                           capture_output=True, text=True)
        say(f"duckdns ping: {r.stdout.strip() or 'no reply'}")
    except Exception as e:
        say(f"duckdns ping failed: {e}")

DIR = r"C:\Projects\KinoliveLines\live"
USERS = os.path.join(DIR, "owl_nest_users.json")
LOG = os.path.join(DIR, "owl_nest_manager.log")
CREATE_NO_WINDOW = 0x08000000


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")


procs = {}
say("manager starting")
while True:
    try:
        users = json.load(open(USERS, encoding="utf-8"))
    except Exception as e:
        say(f"users.json unreadable: {e}")
        users = []
    for u in users:
        uid = u.get("id")
        if not uid or not u.get("terminal"):
            continue          # not provisioned yet (join flow in progress)
        p = procs.get(uid)
        if p is None or p.poll() is not None:
            say(f"spawning worker for {uid}")
            procs[uid] = subprocess.Popen(
                [sys.executable, os.path.join(DIR, "owl_nest_worker.py"), uid],
                cwd=DIR, creationflags=CREATE_NO_WINDOW)
        # personal trading Owl (demo trials with trading enabled)
        if u.get("trading") and u.get("mt5_password"):
            import datetime as _dt
            _alive = False
            if u.get("plan") in ("premium", "family"):
                _alive = True
            else:
                try:
                    _te = _dt.datetime.fromisoformat(u.get("trial_end"))
                    if _te.tzinfo is None:
                        _te = _te.replace(tzinfo=_dt.timezone.utc)
                    _alive = _dt.datetime.now(_dt.timezone.utc) < _te
                except Exception:
                    _alive = False
            if _alive:
                bk = uid + ":bot"
                bp = procs.get(bk)
                if bp is None or bp.poll() is not None:
                    say(f"spawning trading Owl for {uid}")
                    procs[bk] = subprocess.Popen(
                        [sys.executable,
                         os.path.join(DIR, "owl_user_bot.py"), uid],
                        cwd=DIR, creationflags=CREATE_NO_WINDOW)
    duck_ping(say)
    time.sleep(30)
