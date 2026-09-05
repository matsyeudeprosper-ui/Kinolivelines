"""owl_nest_provision.py - auto-builds a nest for new family members.

Watches owl_nest_users.json for entries whose "terminal" is empty (created
by the /join page). For each: clones a lean MT5 terminal (no history bases,
no editor) into C:\\NestTerminals\\<id>\\ and fills in the terminal path.
The manager then spawns their stats worker, which logs in with the
INVESTOR password (read-only) - and their OwlNest page comes alive.
"""
import json, os, subprocess, time

DIR = r"C:\Projects\KinoliveLines\live"
USERS = os.path.join(DIR, "owl_nest_users.json")
LOG = os.path.join(DIR, "owl_nest_provision.log")
TPL = r"C:\Projects\MT5-KinoliveTrader-Session2"
DEST = r"C:\NestTerminals"


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")


say("provisioner starting")
os.makedirs(DEST, exist_ok=True)
while True:
    try:
        users = json.load(open(USERS, encoding="utf-8"))
    except Exception:
        users = None
    if users:
        changed = False
        for u in users:
            if u.get("terminal") or not u.get("id"):
                continue
            uid = u["id"]
            tgt = os.path.join(DEST, uid)
            say(f"provisioning terminal for {uid}")
            r = subprocess.run(
                ["robocopy", TPL, tgt, "/E",
                 "/XD", "Bases", "temp", "logs", "dir_diagnostic_study",
                 "__pycache__",
                 "/XF", "MetaEditor64.exe", "metatester64.exe",
                 "uninstall.exe",
                 "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
                capture_output=True)
            exe = os.path.join(tgt, "terminal64.exe")
            if r.returncode < 8 and os.path.exists(exe):
                u["terminal"] = exe
                changed = True
                say(f"terminal ready for {uid}: {exe}")
            else:
                say(f"robocopy FAILED for {uid}: rc={r.returncode}")
        if changed:
            # MERGE-AT-WRITE (2026-09-05): robocopy takes minutes, and a
            # user deleted via the app during that window was silently
            # resurrected by this stale full-list write. Re-read the
            # file and only update the fields of users still present.
            try:
                cur = json.load(open(USERS, encoding="utf-8"))
                byid = {x.get("id"): x for x in users}
                # merge ONLY the terminal field - replacing whole
                # records stomped flags set meanwhile (e.g. trade:true
                # from an activation code, 2026-09-05)
                for x in cur:
                    v = byid.get(x.get("id"))
                    if (v and v.get("terminal")
                            and not x.get("terminal")):
                        x["terminal"] = v["terminal"]
                json.dump(cur, open(USERS, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
            except Exception:
                json.dump(users, open(USERS, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
    time.sleep(15)
