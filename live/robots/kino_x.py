"""kino_x.py (2026-11-05, owner: "we can start with X") - Kino's X account, through X's official API (OAuth 2.0, user context).

The account carries X's "Automated" label, managed by the owner. Pay-per-use API: a post ~0.015 $, a post WITH a link ~0.20 $
(prices from X's pricing, 2026) - so his links live in his bio / a pinned post, not in every post (post() refuses a link unless
link_ok=True). The owner sets a monthly spending cap in X's console.

Secrets (C:\\ProgramData\\kino_secret, the kino user is denied): x_oauth2.json {cid, sec} (the app's OAuth 2.0 client),
x_token.json {access_token, refresh_token, expires_at, scope, user_id, handle} (written by the connect step), x_pkce.json
(the pending authorization, minutes). Log robots/kino_x.log.
  auth_url()            -> the link the owner opens while logged in as Kino (state + PKCE verifier saved)
  callback(code, state) -> exchanges the code at once (X codes expire in ~30 s); saves the tokens
  post(text, reply_to=None, link_ok=False) -> {"ok", "id", "url"} | {"ok": False, "err"}
"""
import base64, hashlib, json, os, re, secrets, threading, time, urllib.parse, urllib.request

SECRET = r"C:\ProgramData\kino_secret"
CLIENT = os.path.join(SECRET, "x_oauth2.json")
TOKEN = os.path.join(SECRET, "x_token.json")
PKCE = os.path.join(SECRET, "x_pkce.json")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kino_x.log")
REDIRECT = "https://owltrader.duckdns.org/x/callback"
SCOPES = "tweet.read tweet.write users.read offline.access like.read like.write follows.read follows.write"
# 2026-11-05 (owner: "all abilities to manage freely the channels, he owns them"): likes and follows added - an account
# authorized before that keeps posting; the new abilities need one more "Authorize" by the owner (auth_url)
API = "https://api.x.com/2/"
_LK = threading.Lock()


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _j(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def _w(p, d):
    json.dump(d, open(p + ".tmp", "w", encoding="utf-8"))
    os.replace(p + ".tmp", p)


def connected():
    return bool(_j(TOKEN).get("refresh_token") or _j(TOKEN).get("access_token"))


def auth_url():
    c = _j(CLIENT)
    ver = secrets.token_urlsafe(64)[:96]
    ch = base64.urlsafe_b64encode(hashlib.sha256(ver.encode()).digest()).decode().rstrip("=")
    st = secrets.token_urlsafe(16)
    _w(PKCE, {"state": st, "verifier": ver, "t": time.time()})
    return "https://x.com/i/oauth2/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": c["cid"], "redirect_uri": REDIRECT, "scope": SCOPES, "state": st,
        "code_challenge": ch, "code_challenge_method": "S256"})


def _token_call(form):
    c = _j(CLIENT)
    req = urllib.request.Request(API + "oauth2/token", data=urllib.parse.urlencode(form).encode(), method="POST")
    req.add_header("Authorization", "Basic " + base64.b64encode((c["cid"] + ":" + c["sec"]).encode()).decode())
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    return json.load(urllib.request.urlopen(req, timeout=20))


def _save_tokens(j, keep=None):
    d = dict(keep or {})
    d.update(access_token=j["access_token"], expires_at=time.time() + int(j.get("expires_in") or 7200) - 120,
             scope=j.get("scope"), refresh_token=j.get("refresh_token") or d.get("refresh_token"))
    _w(TOKEN, d)
    return d


_CB = threading.Lock()


def callback(code, state):
    """the redirect from X: exchange the code now; returns (ok, message for the page). 2026-11-05: phones load the page twice at
    once - the second load got 'refused' while the first connected; one at a time, and the second sees it is done"""
    with _CB:
        return _callback(code, state)


def _callback(code, state):
    p = _j(PKCE)
    if not p and connected():                          # 2026-11-05: the browser loaded the page twice - the first one connected
        return True, "Kino is already connected to X as @%s. You can close this page." % (_j(TOKEN).get("handle") or "?")
    if not p or not state or state != p.get("state") or time.time() - float(p.get("t") or 0) > 1800:
        return False, "This link is old or was not started here. Ask Claude for a new one."
    try:
        j = _token_call({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "code_verifier": p["verifier"],
                         "client_id": _j(CLIENT)["cid"]})
    except urllib.error.HTTPError as e:
        _log("callback refused %s %s" % (e.code, e.read()[:200]))
        return False, "X refused the connection (%s). Ask Claude for a new link." % e.code
    except Exception as e:
        _log("callback error %r" % e)
        return False, "Something failed while talking to X. Ask Claude for a new link."
    with _LK:
        d = _save_tokens(j)
    try:
        me = _get("users/me")
        d.update(user_id=me["data"]["id"], handle=me["data"]["username"])
        _w(TOKEN, d)
    except Exception as e:
        _log("users/me failed %r" % e)
    os.remove(PKCE)
    _log("CONNECTED as @%s (scope %s)" % (d.get("handle"), d.get("scope")))
    return True, "Kino is connected to X as @%s. You can close this page." % (d.get("handle") or "?")


def _access():
    with _LK:
        d = _j(TOKEN)
        if not d:
            raise RuntimeError("not connected")
        if time.time() < float(d.get("expires_at") or 0):
            return d["access_token"]
        j = _token_call({"grant_type": "refresh_token", "refresh_token": d["refresh_token"], "client_id": _j(CLIENT)["cid"]})
        return _save_tokens(j, d)["access_token"]


def _get(path):
    req = urllib.request.Request(API + path)
    req.add_header("Authorization", "Bearer " + _access())
    return json.load(urllib.request.urlopen(req, timeout=20))


def _post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + _access())
    req.add_header("Content-Type", "application/json")
    return json.load(urllib.request.urlopen(req, timeout=20))


_URL = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|org|net|io|app|social|fr)\b", re.I)


def post(text, reply_to=None, link_ok=False):
    """one post (or a reply) as Kino. A link costs ~13x a plain post on X: refused unless link_ok"""
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "err": "empty"}
    if len(text) > 280:
        return {"ok": False, "err": "longer than 280 characters"}
    if _URL.search(text) and not link_ok:
        return {"ok": False, "err": "a link in a post costs about 0.20 $ on X instead of 0.015 $ - keep links in your bio and pinned post"}
    body = {"text": text}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": str(reply_to)}
    try:
        j = _post("tweets", body)
    except urllib.error.HTTPError as e:
        err = "%s %s" % (e.code, e.read()[:200].decode("utf-8", "replace"))
        _log("post refused %s" % err)
        return {"ok": False, "err": err}
    except Exception as e:
        _log("post error %r" % e)
        return {"ok": False, "err": repr(e)[:200]}
    pid = (j.get("data") or {}).get("id")
    h = _j(TOKEN).get("handle") or "i"
    _log("POSTED %s %s" % (pid, text[:120]))
    return {"ok": True, "id": pid, "url": "https://x.com/%s/status/%s" % (h, pid)}


# ------------------------------------------------------------------ 2026-11-05: the rest of managing his own account
def _id(x):
    m = re.search(r"/status/(\d+)", str(x or "")) or re.match(r"^\s*(\d+)\s*$", str(x or ""))
    return m.group(1) if m else None


def _call(method, path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header("Authorization", "Bearer " + _access())
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        return True, json.load(urllib.request.urlopen(req, timeout=20))
    except urllib.error.HTTPError as e:
        return False, "%s %s" % (e.code, e.read()[:200].decode("utf-8", "replace"))
    except Exception as e:
        return False, repr(e)[:200]


def _me():
    d = _j(TOKEN)
    return d.get("user_id")


def scopes():
    return str(_j(TOKEN).get("scope") or "")


def delete(post):
    i = _id(post)
    if not i:
        return {"ok": False, "err": "not a post of yours (give its x.com link or id)"}
    ok, r = _call("DELETE", "tweets/" + i)
    _log("DELETE %s -> %s" % (i, "ok" if ok else r))
    return {"ok": ok} if ok else {"ok": False, "err": r}


def like(post, undo=False):
    i = _id(post)
    if not i:
        return {"ok": False, "err": "give the post's x.com link or id"}
    ok, r = _call("DELETE", "users/%s/likes/%s" % (_me(), i)) if undo else _call("POST", "users/%s/likes" % _me(), {"tweet_id": i})
    return {"ok": ok} if ok else {"ok": False, "err": r}


def repost(post, undo=False):
    i = _id(post)
    if not i:
        return {"ok": False, "err": "give the post's x.com link or id"}
    ok, r = _call("DELETE", "users/%s/retweets/%s" % (_me(), i)) if undo else _call("POST", "users/%s/retweets" % _me(), {"tweet_id": i})
    return {"ok": ok} if ok else {"ok": False, "err": r}


def follow(handle, undo=False):
    h = str(handle or "").strip().lstrip("@").split("/")[-1]
    ok, r = _call("GET", "users/by/username/" + urllib.parse.quote(h))
    if not ok:
        return {"ok": False, "err": r}
    uid = (r.get("data") or {}).get("id")
    ok, r = _call("DELETE", "users/%s/following/%s" % (_me(), uid)) if undo else _call("POST", "users/%s/following" % _me(), {"target_user_id": uid})
    return {"ok": ok} if ok else {"ok": False, "err": r}


def mentions(n=10):
    """who talked to him on X lately (paid reads: ~0.005 $ each)"""
    ok, r = _call("GET", "users/%s/mentions?max_results=%d&tweet.fields=created_at,author_id&expansions=author_id&user.fields=username" % (
        _me(), max(5, min(int(n), 20))))
    if not ok:
        return {"ok": False, "err": r}
    U = {u["id"]: u.get("username") for u in (r.get("includes") or {}).get("users") or []}
    return {"ok": True, "items": [{"id": t["id"], "by": U.get(t.get("author_id")), "text": t.get("text"), "at": t.get("created_at"),
                                   "url": "https://x.com/%s/status/%s" % (U.get(t.get("author_id")) or "i", t["id"])}
                                  for t in r.get("data") or []]}
