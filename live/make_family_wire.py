"""USER-RUN: wires the FAMILY INVITE system (real accounts, self-service,
invite-gated). Run with:
  ! python C:/Projects/KinoliveLines/live/make_family_wire.py
then:
  ! powershell -NoProfile -File C:/Projects/KinoliveLines/live/restart_nest.ps1

What it does:
- Join form gains an optional "Code d'invitation famille" field.
- A REAL-server signup is accepted ONLY with a valid unused invite code
  (owl_invites.json) -> plan "family": trading Owl, no trial expiry.
  Without a code, real accounts stay rejected; demo trials unchanged.
- The demo-only iron lock in owl_user_bot.py gains exactly ONE exception:
  plan == "family".
"""
import ast, json, os

DIR = r"C:\Projects\KinoliveLines\live"

# 0) invites file
ip = os.path.join(DIR, "owl_invites.json")
if not os.path.exists(ip):
    json.dump({"codes": {}}, open(ip, "w"))
    print("owl_invites.json created")

# 1) server: form field + family flow
p = os.path.join(DIR, "owl_app_server.py")
s = open(p, encoding='utf-8').read()

old = '''<label>Code famille</label>
<input name="code" required placeholder="le mot secret">
<button class="go">Cr&eacute;er &#10142;</button>'''
new = '''<label>Code famille</label>
<input name="code" required placeholder="le mot secret">
<label>Code d&#8217;invitation <span style="color:#9aa7b4">(compte
 r&eacute;el famille &mdash; sinon laisser vide)</span></label>
<input name="invite" placeholder="ex : FAM-XXXX">
<button class="go">Cr&eacute;er &#10142;</button>'''
assert old in s, "form anchor"
s = s.replace(old, new)

old = '''    _srv = server.lower()
    _is_demo = ("trial" in _srv) or ("demo" in _srv)
    if not _is_demo:
        return _join_result(
            "&#11088; Compte r&eacute;el = Premium",
            "<p>Commencez avec un <b>compte d&eacute;mo</b> (7 jours "
            "d&#8217;essai gratuit).</p><p>Pour connecter un compte "
            "r&eacute;el, contactez Kino pour activer votre acc&egrave;s "
            "Premium.</p>")'''
new = '''    _srv = server.lower()
    _is_demo = ("trial" in _srv) or ("demo" in _srv)
    _plan = "trial"
    if not _is_demo:
        _invite = (form.get("invite", [""])[0] or "").strip().upper()
        _ipath = os.path.join(DIR, "owl_invites.json")
        try:
            _iv = json.load(open(_ipath, encoding="utf-8"))
        except Exception:
            _iv = {"codes": {}}
        _c0 = _iv.get("codes", {}).get(_invite)
        if not _invite or _c0 is None or _c0.get("used"):
            return _join_result(
                "&#11088; Compte r&eacute;el = famille ou Premium",
                "<p>Commencez avec un <b>compte d&eacute;mo</b> (7 jours "
                "d&#8217;essai gratuit) &mdash; ou demandez un <b>code "
                "d&#8217;invitation</b> &agrave; Kino si vous &ecirc;tes "
                "de la famille.</p>")
        _c0["used"] = True
        _c0["used_by"] = login
        json.dump(_iv, open(_ipath, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        _plan = "family"'''
assert old in s, "join real-check anchor"
s = s.replace(old, new)

old = '''        "plan": "trial",
        "trading": True,
        "trial_end": (datetime.now(timezone.utc)
                      + timedelta(days=7)).isoformat(timespec="seconds"),
    })'''
new = '''        "plan": _plan,
        "trading": True,
        "trial_end": (None if _plan == "family" else
                      (datetime.now(timezone.utc)
                       + timedelta(days=7)).isoformat(timespec="seconds")),
    })'''
assert old in s, "entry anchor"
s = s.replace(old, new)

open(p, 'w', encoding='utf-8').write(s)
ast.parse(s)
print("server: invite flow wired")

# 2) manager: family = always alive
p2 = os.path.join(DIR, "owl_nest_manager.py")
s2 = open(p2, encoding='utf-8').read()
old2 = '''            if u.get("plan") == "premium":
                _alive = True'''
new2 = '''            if u.get("plan") in ("premium", "family"):
                _alive = True'''
assert old2 in s2, "manager anchor"
s2 = s2.replace(old2, new2)
open(p2, 'w', encoding='utf-8').write(s2)
ast.parse(s2)
print("manager: family plan accepted")

# 3) user bot: family exception to the demo-only lock + no expiry
p3 = os.path.join(DIR, "owl_user_bot.py")
s3 = open(p3, encoding='utf-8').read()
old3 = '''    if uu.get("plan") == "premium":
        return True'''
new3 = '''    if uu.get("plan") in ("premium", "family"):
        return True'''
assert old3 in s3, "bot trial anchor"
s3 = s3.replace(old3, new3)
old3 = '''    srv = (u.get("mt5_server") or "").lower()
    if ("trial" not in srv) and ("demo" not in srv):
        say("SAFETY: not a demo server - trading refused forever")
        raise SystemExit(1)'''
new3 = '''    srv = (u.get("mt5_server") or "").lower()
    if ("trial" not in srv) and ("demo" not in srv):
        if u.get("plan") != "family":
            say("SAFETY: not a demo server - trading refused forever")
            raise SystemExit(1)'''
assert old3 in s3, "bot safety anchor"
s3 = s3.replace(old3, new3)
open(p3, 'w', encoding='utf-8').write(s3)
ast.parse(s3)
print("user bot: family exception in place")
print("DONE - run restart_nest.ps1")
