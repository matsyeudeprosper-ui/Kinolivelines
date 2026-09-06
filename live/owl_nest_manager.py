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
    # AUTO-REGISTRATION CLEANUP (2026-09-06 user): a pending signup
    # whose worker reports bad credentials (auth_failed), or that never
    # came alive within 12 minutes, is removed - user record AND the
    # terminal instance we tried with.
    try:
        _changed = False
        _keep = []
        for u in users:
            _ps = u.get("pending_since")
            if not _ps:
                _keep.append(u)
                continue
            _nd = os.path.join(DIR, "nest_data", u["id"] + ".json")
            _bad = False
            _ok = False
            try:
                _d = json.load(open(_nd, encoding="utf-8"))
                if _d.get("auth_failed"):
                    _bad = True
                elif _d.get("balance") is not None:
                    _ok = True
            except Exception:
                pass
            if _ok:
                u.pop("pending_since", None)
                say(f"signup {u['id']} verified - credentials work")
                _changed = True
                _keep.append(u)
            elif _bad or time.time() - float(_ps) > 720:
                say(f"signup {u['id']} FAILED validation - cleaning "
                    f"up user + terminal")
                _changed = True
                try:
                    os.remove(_nd)
                except Exception:
                    pass
                _wp = procs.pop(u["id"], None)
                if _wp is not None and _wp.poll() is None:
                    _wp.kill()          # stop the failing worker now
                _t = u.get("terminal") or ""
                _tdir = os.path.dirname(_t)
                if _tdir.startswith(r"C:\NestTerminals"):
                    # the tried terminal64.exe keeps running even after
                    # a failed login - kill it before deleting
                    subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         "Get-CimInstance Win32_Process -Filter "
                         "\"Name='terminal64.exe'\" | Where-Object "
                         "{ $_.ExecutablePath -like '" + _tdir
                         + "*' } | ForEach-Object "
                         "{ Stop-Process -Id $_.ProcessId -Force }"],
                        capture_output=True)
                    time.sleep(2)
                    subprocess.run(
                        ["cmd", "/c", f"rmdir /s /q \"{_tdir}\""],
                        capture_output=True)
            else:
                _keep.append(u)
        if _changed:
            json.dump(_keep, open(USERS, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
    except Exception as e:
        say(f"cleanup error: {e}")
    duck_ping(say)
    time.sleep(30)
