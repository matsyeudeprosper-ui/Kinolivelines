"""owl_backup.py - nightly local backup of the OwlNest configuration
and books (users, states, ledgers, invites, codes, subs). Keeps 14
days of zips in live\\backups. Secrets stay local - never in git."""
import glob
import os
import time
import zipfile

DIR = r"C:\Projects\KinoliveLines\live"
OUT = os.path.join(DIR, "backups")
os.makedirs(OUT, exist_ok=True)

PATTERNS = ["owl_nest_users.json", "owl_secrets.json",
            "owl_*state*.json", "owl_ledger*.json",
            "owl_fight_history*.json", "owl_chain_floor*.json",
            "owl_invites.json", "owl_activation_codes.json",
            "owl_push_subs.json", "owl_push_prefs.json",
            "owl_push_vapid.json", "owl_milestone*.json"]

name = os.path.join(OUT, "owl-" + time.strftime("%Y%m%d") + ".zip")
with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as z:
    seen = set()
    for pat in PATTERNS:
        for p in glob.glob(os.path.join(DIR, pat)):
            if p not in seen and os.path.isfile(p):
                seen.add(p)
                z.write(p, os.path.basename(p))
print("backup:", name, len(seen), "files")

old = sorted(glob.glob(os.path.join(OUT, "owl-*.zip")))
for p in old[:-14]:
    os.remove(p)
    print("rotated out:", os.path.basename(p))
