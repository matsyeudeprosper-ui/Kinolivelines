"""og_card.py - the picture shown when someone shares the OwlNest link
(WhatsApp, Telegram, Facebook...). 2026-10-11 (owner, acquisition).

Draws the witness account's public numbers (from /landing_data, aggregates
only) as a 1200x630 card and writes live/static/og_card.png, served at
/shots/og_card.png. Run by hand or nightly from study/proof_autorun.py.
    python live/review/og_card.py
"""
import json, os, subprocess, sys, tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "static", "og_card.png")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def fr(v, d=1):
    return (("%." + str(d) + "f") % v).replace(".", ",")


def page(L):
    W = L["witness"]
    sign = "+" if W["ret"] >= 0 else "&minus;"
    days = max(1, round((time.time() - W["start"]) / 86400))
    # equity line from the public aggregates is not available per trade, so
    # the card shows numbers only - no invented curve
    tiles = [("R&eacute;ussite", "%d&#8239;%%" % round(W["wr"]), "#8df0bb" if W["wr"] >= 55 else "#e8c55a"),
             ("Profit factor", fr(W["pf"], 2), "#8df0bb" if W["pf"] >= 1.5 else ("#e8c55a" if W["pf"] >= 1.15 else "#ff9a9a")),
             ("Baisse max", "&minus;" + fr(W["dd_pct"]) + "&#8239;%", "#8df0bb" if W["dd_pct"] <= 12 else ("#e8c55a" if W["dd_pct"] <= 22 else "#ff9a9a"))]
    T = "".join('<div class="t"><small>%s</small><b style="color:%s">%s</b></div>' % (k, c, v) for k, v, c in tiles)
    return """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:1200px;height:630px;overflow:hidden}
body{font-family:'Segoe UI',system-ui,sans-serif;color:#fff;
 background:radial-gradient(70%% 90%% at 100%% 0%%,rgba(46,204,113,.20),transparent 60%%),radial-gradient(60%% 80%% at 0%% 100%%,rgba(232,197,90,.13),transparent 60%%),linear-gradient(160deg,#0f2236,#0b1420)}
.w{padding:64px 72px;height:100%%;box-sizing:border-box;display:flex;flex-direction:column}
.top{display:flex;justify-content:space-between;align-items:center}
.br{font-size:40px;font-weight:900;letter-spacing:-.02em}.br span{color:#e8c55a}
.lv{font-size:20px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#8df0bb;border:2px solid rgba(46,204,113,.35);background:rgba(46,204,113,.10);border-radius:99px;padding:10px 22px}
.ey{margin-top:46px;font-size:24px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:#9fc2de}
.big{font-size:150px;font-weight:900;letter-spacing:-.04em;line-height:1;margin-top:10px}
.sub{font-size:30px;color:#9fc2de;margin-top:14px}
.g{display:flex;gap:22px;margin-top:auto}
.t{flex:1;background:rgba(255,255,255,.05);border:2px solid rgba(255,255,255,.09);border-radius:26px;padding:22px 26px}
.t small{display:block;font-size:20px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#9fc2de}
.t b{display:block;font-size:52px;font-weight:900;margin-top:6px}
</style></head><body><div class="w">
<div class="top"><div class="br">Owl<span>Nest</span></div><div class="lv">Argent r&eacute;el &middot; pertes comprises</div></div>
<div class="ey">Compte t&eacute;moin</div>
<div class="big">%s%s&#8239;%%</div>
<div class="sub">en %d jours &middot; %d trades &middot; %d semaines sur %d en positif</div>
<div class="g">%s</div>
</div></body></html>""" % (sign, fr(abs(W["ret"])), days, W["n"], W["weeks_pos"], W["weeks"], T)


def main():
    with urllib.request.urlopen("http://127.0.0.1:8787/landing_data", timeout=30) as r:
        L = json.loads(r.read().decode("utf-8"))
    if not L.get("witness"):
        print("no witness data, card left as is"); return 1
    d = tempfile.mkdtemp(prefix="owl_og_")
    src = os.path.join(d, "card.html"); png = os.path.join(d, "card.png")
    open(src, "w", encoding="utf-8").write(page(L))
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                    "--user-data-dir=" + os.path.join(d, "prof"), "--window-size=1200,630",
                    "--screenshot=" + png, "file:///" + src.replace("\\", "/")], timeout=90,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # msedge.exe hands off to a child and returns before the file is written
    for _ in range(120):
        if os.path.exists(png) and os.path.getsize(png) > 5000:
            time.sleep(1); break
        time.sleep(0.5)
    if not os.path.exists(png) or os.path.getsize(png) < 5000:
        print("render failed, card left as is"); return 1
    os.replace(png, OUT)
    print("og_card.png written", os.path.getsize(OUT), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
