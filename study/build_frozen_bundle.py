"""Build the ISOLATED frozen bundle for the entry study (review 16, item 4).

Copies every source the replication needs into study/frozen_entry_study/, rewrites the absolute
paths inside the copies so that each copy resolves its dependencies INSIDE the bundle (the engine's
exec of manifest_runner, the sys.path inserts, the Compte manifest path, the tick directory default),
copies the data pins (dataset b bars + meta, the Compte package snapshot, the package file), hashes
every bundle file and writes the list into review/entry_study_manifest.json (frozen_copy.files) and
re-stamps the manifest's own sources. Idempotent; run it right before the FROZEN commit.
    python build_frozen_bundle.py
"""
import os, re, json, shutil, hashlib, time
ROOT = r"C:\Projects\KinoliveLines"; B = os.path.join(ROOT, "study", "frozen_entry_study"); os.makedirs(B, exist_ok=True)
PY = ["study/tick_engine.py", "study/tick_engine_forward.py", "study/tick_engine_stats.py", "study/manifest_runner.py", "study/dev_dataset.py",
      "study/fetch_ticks.py", "live/lab/harness.py", "live/structure_bos_bot.py", "live/owl_package.py", "live/lab/compte_controller.py", "live/lab/test_tick_engine.py",
      # imported by the bot / the controller at import time (review 16: the bundle must resolve everything itself)
      "live/owl_shadow.py", "live/owl_chart_feed.py", "live/pb_gate.py"]
DATA = ["review/compte_frozen_manifest.json", "live/owl_packages.json", "study/dev_bars_2026-10-09b.npz", "study/dev_bars_2026-10-09b.json"]
# every absolute root the sources use -> the bundle (longest first so prefixes do not clobber)
ROOTS = [r"C:\Projects\KinoliveLines\review\compte_frozen_manifest.json", r"C:\Projects\KinoliveLines\live\lab", r"C:\Projects\KinoliveLines\live",
         r"C:\Projects\KinoliveLines\study\ticks", r"C:\Projects\KinoliveLines\study", "C:/Projects/KinoliveLines/study", r"C:\Projects\KinoliveLines"]
REPL = {ROOTS[0]: os.path.join(B, "compte_frozen_manifest.json"), ROOTS[1]: B, ROOTS[2]: B, ROOTS[3]: os.path.join(B, "ticks_unset"), ROOTS[4]: B, ROOTS[5]: B.replace("\\", "/"), ROOTS[6]: B}


# relative-path sys.path inserts that would climb OUT of the bundle (review 16 isolation): pinned to the bundle itself
REL_FIXES = [("sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))", "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))")]
import re as _re


def rewrite(src):
    for a, b in REL_FIXES:
        src = src.replace(a, b)
    src = _re.sub(r"^LIVE = .*$", "LIVE = os.path.dirname(os.path.abspath(__file__))   # bundle (frozen copy)", src, count=1, flags=_re.M)
    # two passes with placeholders so a replacement's output can never be re-matched by a later key
    # (the bundle path itself contains the working roots as prefixes)
    toks = {}
    for i, k in enumerate(ROOTS):
        tok = "\x00ROOT%d\x00" % i; toks[tok] = REPL[k]; src = src.replace(k, tok)
    for tok, v in toks.items():
        src = src.replace(tok, v)
    return src


h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
for rel in PY:
    s = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    open(os.path.join(B, os.path.basename(rel)), "w", encoding="utf-8", newline="").write(rewrite(s))
for rel in DATA:
    shutil.copy2(os.path.join(ROOT, rel), os.path.join(B, os.path.basename(rel)))
# the harness's generic sys.path insert of its own folder is relative (fine); nothing else to patch
# results / logs written by runs are NOT part of the frozen set (a run must not change what it checks)
files = {f: h(os.path.join(B, f)) for f in sorted(os.listdir(B))
         if f != "run_frozen.py" and not f.startswith("__") and not f.startswith("frozen_result") and not f.startswith("frozen_fixture") and not f.endswith((".pyc", ".out", ".log"))}
man_path = os.path.join(ROOT, "review", "entry_study_manifest.json"); man = json.load(open(man_path, encoding="utf-8"))
man["frozen_copy"] = {"dir": "study/frozen_entry_study", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "runner": "run_frozen.py",
                      "isolation": "paths rewritten into the bundle; run_frozen.py asserts every loaded module sits inside it and hashes every bundle file first",
                      "files": files, "run_frozen_sha256": h(os.path.join(B, "run_frozen.py"))}
man["sources"] = {k: h(os.path.join(ROOT, k)) for k in man["sources"]}
json.dump(man, open(man_path, "w", encoding="utf-8"), indent=1)
print("bundle:", len(files), "files; manifest updated;", "paths left:", sum(1 for f in files if f.endswith(".py") and "KinoliveLines\\\\study" in open(os.path.join(B, f), encoding="utf-8").read()))
for f in files:
    if f.endswith(".py"):
        txt = open(os.path.join(B, f), encoding="utf-8").read()
        left = [m for m in re.findall(r"C:[\\/]+Projects[\\/]+KinoliveLines[^\"'\\s]*", txt) if "frozen_entry_study" not in m]
        if left: print("  WARNING unrewritten path in", f, left[:3])
