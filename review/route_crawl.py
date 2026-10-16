"""route_crawl.py - hit every user-facing route of the running app with good and bad input and report anything that
is not a clean answer: 5xx, a Python traceback in the body, a dropped connection, or an empty 404 for a browser.
    python review/route_crawl.py [base=http://127.0.0.1:8787]
Member sub-routes are walked with the public demo's token (read from live/owl_nest_users.json) and a bogus token.
"""
import sys, os, json, urllib.request, urllib.error, http.client, socket
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787"
LIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live")
users = json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8"))
TOK = next(u["token"] for u in users if u.get("id") == "demo")
SUBS = ["", "ai_get", "ai_pulse", "api", "audio", "chart", "chart_data", "chart_day", "chart_htf", "compare", "day", "funnel", "health", "inbox",
        "lab", "lab_peek", "manual_state", "market_hours", "nest_reset_preview", "patterns", "payments", "pockets", "proof", "push_key",
        "rentabilite", "rentabilite_data", "robot_journal", "robot_preview", "robot_why", "robots_data", "scanner_data", "signals", "studio_get",
        "team_data", "test_pockets", "trade", "wealth", "wealth_data", "nonexistent_sub"]
PUBLIC = ["/", "/offres", "/demo", "/legal", "/manifest.json", "/sw.js", "/apk.json", "/landing_data", "/activate", "/verif", "/verif?j=zz",
          "/probe", "/probe?j=zz", "/brokerinfo", "/brokerinfo?server=x", "/codeinfo", "/codeinfo?c=ZZZZZZ", "/app", "/logout",
          "/nonexistent", "/nonexistent/deeper", "/fonts/none.woff2", "/shots/none.png", "/.well-known/assetlinks.json",
          "/" + "x" * 300, "/%00", "/..%2f..%2fetc/passwd", "/badtoken12/", "/badtoken12/chart", "/badtoken12/chart_data"]
POSTS = [("/activate", ""), ("/login", ""), ("/register", ""), ("/find", ""), ("/join", ""), ("/activate", "action=continue&probe=zz"),
         ("/" + TOK + "/account_robot_set", ""), ("/" + TOK + "/nonexistent_post", "x=1"), ("/badtoken12/account_robot_set", "")]


def hit(method, path, body=None):
    url = BASE + path
    req = urllib.request.Request(url, data=(body or "").encode() if method == "POST" else None, method=method,
                                 headers={"Accept": "text/html", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            b = r.read(400000); code = r.status; ct = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        b = e.read(400000); code = e.code; ct = e.headers.get("Content-Type", "")
    except (urllib.error.URLError, http.client.RemoteDisconnected, ConnectionResetError, socket.timeout, http.client.BadStatusLine) as e:
        return ("DROPPED", str(e)[:60], "")
    txt = b.decode("utf-8", "replace")
    flag = ""
    if code >= 500:
        flag = "5xx"
    elif "Traceback (most recent call last)" in txt:
        flag = "traceback"
    elif code == 404 and len(b) < 50:
        flag = "blank 404"
    elif code == 200 and len(b) == 0:
        flag = "empty 200"
    return (code, ct.split(";")[0], flag)


bad = 0
for p in PUBLIC:
    code, ct, flag = hit("GET", p); print("%-7s %-22s %s%s" % (code, ct, p[:60], ("   <-- " + flag) if flag else "")); bad += bool(flag)
for s in SUBS:
    for tok, lab in ((TOK, "demo"), ("badtoken12", "bad")):
        p = "/%s/%s" % (tok, s)
        code, ct, flag = hit("GET", p); print("%-7s %-22s /<%s>/%s%s" % (code, ct, lab, s, ("   <-- " + flag) if flag else "")); bad += bool(flag)
for p, body in POSTS:
    code, ct, flag = hit("POST", p, body); print("%-7s %-22s POST %s [%s]%s" % (code, ct, p.replace(TOK, "<demo>")[:50], body[:30], ("   <-- " + flag) if flag else "")); bad += bool(flag)
print("\n%d route(s) flagged" % bad)
