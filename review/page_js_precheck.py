"""page_js_precheck.py - syntax-check the app page's inline <script>s from the
SOURCE, before restarting the server.

2026-10-14: an extra ')' in a new panel took the whole app page down for two
minutes - the check ran against the served page AFTER the restart. This
reads PAGE out of live/owl_app_server.py without importing it (importing
starts threads), and runs `node --check` on every inline script.

    python review/page_js_precheck.py      -> exit 0 = all scripts parse
"""
import ast
import os
import re
import subprocess
import sys
import tempfile

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "live", "owl_app_server.py")
tree = ast.parse(open(SRC, encoding="utf-8-sig").read())
page = None
for node in tree.body:
    if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "PAGE" for t in node.targets):
        try:
            page = ast.literal_eval(node.value)
        except ValueError:
            pass
        break
if not isinstance(page, str):
    print("PAGE not found as a plain string literal - cannot check")
    sys.exit(2)
scripts = re.findall(r"<script(?![^>]*src)[^>]*>([\s\S]*?)</script>", page)
bad = 0
with tempfile.TemporaryDirectory() as d:
    for i, js in enumerate(scripts, 1):
        f = os.path.join(d, f"s{i}.js")
        open(f, "w", encoding="utf-8").write(js)
        r = subprocess.run(["node", "--check", f], capture_output=True, text=True)
        if r.returncode:
            bad += 1
            print(f"script {i}: SYNTAX ERROR")
            print("\n".join(r.stderr.splitlines()[:5]))
print(f"{len(scripts)} scripts, {bad} with a syntax error")
# 2026-10-14: the other served pages too (a duplicate `const` in owl_strategies_page.html would have broken
# the robot pages). %%PLACEHOLDERS%% are filled by the server: replaced by null for the check.
import glob
LIVE = os.path.dirname(SRC)
for hp in sorted(glob.glob(os.path.join(LIVE, "owl_*page*.html"))):
    h = open(hp, encoding="utf-8-sig").read()
    sc = re.findall(r"<script(?![^>]*src)[^>]*>([\s\S]*?)</script>", h)
    nb = 0
    with tempfile.TemporaryDirectory() as d:
        for i, js in enumerate(sc, 1):
            f = os.path.join(d, f"p{i}.js")
            open(f, "w", encoding="utf-8").write(re.sub(r"%%[A-Z0-9_]+%%", "null", js))
            r = subprocess.run(["node", "--check", f], capture_output=True, text=True)
            if r.returncode:
                nb += 1
                print(f"{os.path.basename(hp)} script {i}: SYNTAX ERROR")
                print(chr(10).join(r.stderr.splitlines()[:5]))
    bad += nb
    print(f"{os.path.basename(hp)}: {len(sc)} scripts, {nb} with a syntax error")
sys.exit(1 if bad else 0)
