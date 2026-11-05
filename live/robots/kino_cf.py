"""kino_cf.py (2026-11-05, owner: "putting a won client's site live on the client's own domain and hosting") - Kinoverse hosting on
Cloudflare Pages (free plan): one project per client site, deployed by Kino through the official API (direct upload, the same
steps Cloudflare's own command-line tool uses), and the client's domain attached to it.

Secret: C:\\ProgramData\\kino_secret\\cloudflare.json {token, account_id} - token scoped to Pages Read+Write only, 1 year (renew
by 2027-11). Log robots/kino_cf.log.
  deploy(name, folder)          -> {"ok", "url" (https://<project>.pages.dev), "deployment"}
  add_domain(name, domain)      -> {"ok", "status", "how": what the client sets at their domain provider}
  domain_status(name, domain)   -> {"ok", "status"}
"""
import base64, hashlib, json, mimetypes, os, re, time, urllib.request, uuid

SECRET = r"C:\ProgramData\kino_secret\cloudflare.json"
API = "https://api.cloudflare.com/client/v4/"
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kino_cf.log")


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _c():
    return json.load(open(SECRET, encoding="utf-8"))


def _req(method, url, body=None, token=None, headers=None, raw=None):
    h = {"Authorization": "Bearer " + (token or _c()["token"])}
    h.update(headers or {})
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    rq = urllib.request.Request(url if url.startswith("http") else API + url, data=data, method=method, headers=h)
    try:
        return json.load(urllib.request.urlopen(rq, timeout=60))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}") | {"http": e.code}
        except Exception:
            return {"success": False, "http": e.code}


def project_name(name):
    s = re.sub(r"[^a-z0-9-]+", "-", str(name or "").lower()).strip("-")[:50]
    return ("kv-" + s) if s else "kv-site"


def _ensure_project(pn):
    a = _c()["account_id"]
    r = _req("GET", "accounts/%s/pages/projects/%s" % (a, pn))
    if r.get("success"):
        return True, r["result"]
    r = _req("POST", "accounts/%s/pages/projects" % a, {"name": pn, "production_branch": "main"})
    return bool(r.get("success")), r.get("result") or r.get("errors")


def deploy(name, folder):
    """publish a folder (index.html + assets) as the client's site"""
    folder = os.path.realpath(str(folder or ""))
    if not os.path.isfile(os.path.join(folder, "index.html")):
        return {"ok": False, "err": "the folder needs an index.html"}
    files = {}
    for dp, _d, fn in os.walk(folder):
        for f in fn:
            fp = os.path.join(dp, f)
            if os.path.getsize(fp) > 20_000_000:
                return {"ok": False, "err": "%s is over 20 MB" % f}
            files["/" + os.path.relpath(fp, folder).replace("\\", "/")] = fp
    if len(files) > 500:
        return {"ok": False, "err": "more than 500 files"}
    pn = project_name(name)
    ok, info = _ensure_project(pn)
    if not ok:
        return {"ok": False, "err": "could not create the project: %s" % str(info)[:200]}
    a = _c()["account_id"]
    jwt = (_req("GET", "accounts/%s/pages/projects/%s/upload-token" % (a, pn)).get("result") or {}).get("jwt")
    if not jwt:
        return {"ok": False, "err": "no upload token from Cloudflare"}
    manifest, blobs = {}, {}
    for path, fp in files.items():
        b64 = base64.b64encode(open(fp, "rb").read()).decode()
        ext = os.path.splitext(fp)[1].lstrip(".")
        hx = hashlib.sha256((b64 + ext).encode()).hexdigest()[:32]
        manifest[path] = hx
        blobs[hx] = (b64, mimetypes.guess_type(fp)[0] or "application/octet-stream")
    miss = _req("POST", "pages/assets/check-missing", {"hashes": list(blobs)}, token=jwt).get("result") or list(blobs)
    batch = []
    for hx in miss:
        b64, ct = blobs[hx]
        batch.append({"key": hx, "value": b64, "metadata": {"contentType": ct}, "base64": True})
        if len(batch) >= 50:
            r = _req("POST", "pages/assets/upload", batch, token=jwt)
            if not r.get("success"):
                return {"ok": False, "err": "upload failed: %s" % str(r.get("errors"))[:200]}
            batch = []
    if batch:
        r = _req("POST", "pages/assets/upload", batch, token=jwt)
        if not r.get("success"):
            return {"ok": False, "err": "upload failed: %s" % str(r.get("errors"))[:200]}
    _req("POST", "pages/assets/upsert-hashes", {"hashes": list(blobs)}, token=jwt)
    bd = "----kino" + uuid.uuid4().hex
    body = ("--%s\r\nContent-Disposition: form-data; name=\"manifest\"\r\n\r\n%s\r\n--%s--\r\n" % (bd, json.dumps(manifest), bd)).encode()
    r = _req("POST", "accounts/%s/pages/projects/%s/deployments" % (a, pn), raw=body,
             headers={"Content-Type": "multipart/form-data; boundary=" + bd})
    if not r.get("success"):
        return {"ok": False, "err": "deployment refused: %s" % str(r.get("errors"))[:200]}
    sub = (_req("GET", "accounts/%s/pages/projects/%s" % (a, pn)).get("result") or {}).get("subdomain") or (pn + ".pages.dev")
    url = "https://%s" % sub                       # Cloudflare adds a suffix when the name is taken (kv-test -> kv-test-2gf)
    _log("DEPLOY %s %d files -> %s (%s)" % (pn, len(files), url, (r.get("result") or {}).get("url")))
    return {"ok": True, "url": url, "deployment": (r.get("result") or {}).get("url"), "project": pn}


def add_domain(name, domain):
    """attach the client's own domain; the client (or Kino with their access) points it at the site"""
    pn = project_name(name)
    d = str(domain or "").strip().lower().replace("https://", "").replace("http://", "").strip("/")
    a = _c()["account_id"]
    r = _req("POST", "accounts/%s/pages/projects/%s/domains" % (a, pn), {"name": d})
    if not r.get("success") and "already" not in json.dumps(r.get("errors") or "").lower():
        return {"ok": False, "err": str(r.get("errors"))[:200]}
    sub = (_req("GET", "accounts/%s/pages/projects/%s" % (a, pn)).get("result") or {}).get("subdomain") or (pn + ".pages.dev")
    apex = d.count(".") == 1
    how = ("At their domain provider, the client adds one record: type CNAME, name %s, value %s.pages.dev." % (
        "@ (or the domain itself)" if apex else d.split(".")[0], sub.replace(".pages.dev", "")) +
           (" Many providers do not allow a CNAME on the bare domain: then use www.%s for the site and a redirect from %s to it, "
            "or move the domain's DNS to Cloudflare (free)." % (d, d) if apex else ""))
    _log("DOMAIN %s -> %s" % (d, pn))
    return {"ok": True, "status": ((r.get("result") or {}).get("status") or "pending"), "how": how}


def domain_status(name, domain):
    a = _c()["account_id"]
    r = _req("GET", "accounts/%s/pages/projects/%s/domains/%s" % (a, project_name(name), str(domain).strip().lower()))
    return {"ok": bool(r.get("success")), "status": (r.get("result") or {}).get("status"), "err": r.get("errors")}
