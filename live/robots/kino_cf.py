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


# ---- 2026-11-12 (owner: "Kino will have to do such things by itself - creating emails for the clients and all. I can't repeat
# this for each client"). The whole client setup, end to end, with the account-wide token (zones, DNS, Email Routing) and the
# Resend full key. The client's domain moves to OUR Cloudflare (one step for them at any registrar: paste 2 nameservers), then
# everything else is done here. There is deliberately NO delete / remove function in this file: the owner must be asked first
# (2026-11-12 promise) - removing a zone, record, route or Resend domain is done by hand.
RESEND = os.path.join(os.path.dirname(SECRET), "resend.json")


def _dom(domain):
    d = str(domain or "").strip().lower().replace("https://", "").replace("http://", "").strip("/").split("/")[0]
    return d[4:] if d.startswith("www.") else d


def zone(domain):
    """the client's domain on our Cloudflare: {"ok", "id", "status" pending|active, "nameservers"}; created if missing"""
    d = _dom(domain)
    if not re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$", d):
        return {"ok": False, "err": "not a domain: %r" % domain}
    r = _req("GET", "zones?name=%s" % d)
    z = (r.get("result") or [None])[0]
    if not z:
        r = _req("POST", "zones", {"name": d, "account": {"id": _c()["account_id"]}, "type": "full"})
        if not r.get("success"):
            return {"ok": False, "err": str(r.get("errors"))[:200]}
        z = r["result"]
        _log("ZONE ADDED %s %s" % (d, z["id"]))
    elif z["status"] != "active":
        _req("PUT", "zones/%s/activation_check" % z["id"])
    return {"ok": True, "id": z["id"], "status": z["status"], "nameservers": z.get("name_servers") or [],
            "how": ("At the place they bought %s (OVH, GoDaddy, Namecheap, IONOS...), in the domain's settings, choose custom "
                    "nameservers / DNS servers and put exactly these two: %s. Nothing else. It takes from minutes to a few hours."
                    % (d, " and ".join(z.get("name_servers") or [])))}


def _record(zid, typ, name, content, proxied=False, priority=None):
    """add a DNS record unless the same one is there (never overwrites or removes)"""
    ex = _req("GET", "zones/%s/dns_records?type=%s&name=%s" % (zid, typ, name)).get("result") or []
    if any(str(x.get("content")).strip('"') == str(content).strip('"') for x in ex):
        return True
    b = {"type": typ, "name": name, "content": content, "ttl": 1}
    if typ in ("A", "AAAA", "CNAME"):
        b["proxied"] = proxied
    if priority is not None:
        b["priority"] = int(priority)
    r = _req("POST", "zones/%s/dns_records" % zid, b)
    if not r.get("success"):
        _log("DNS FAIL %s %s %s" % (typ, name, r.get("errors")))
    return bool(r.get("success"))


def site_on_domain(name, domain):
    """the client's site (Pages project of `name`) on domain + www, with https"""
    d = _dom(domain)
    z = zone(d)
    if not z.get("ok"):
        return z
    pn = project_name(name)
    a = _c()["account_id"]
    sub = (_req("GET", "accounts/%s/pages/projects/%s" % (a, pn)).get("result") or {}).get("subdomain")
    if not sub:
        return {"ok": False, "err": "no site deployed for %s yet - deploy first" % name}
    for h in (d, "www." + d):
        _req("POST", "accounts/%s/pages/projects/%s/domains" % (a, pn), {"name": h})
        _record(z["id"], "CNAME", h, sub, proxied=True)
    _log("SITE %s -> %s (%s)" % (d, pn, z["status"]))
    return {"ok": True, "zone": z["status"], "how": z["how"] if z["status"] != "active" else "",
            "site": {h: domain_status(name, h).get("status") for h in (d, "www." + d)}}


def mailbox(domain, local, forward_to):
    """<local>@domain lands in the client's own inbox (forward_to). Cloudflare mails forward_to ONE confirmation link the
    first time - the client clicks it; until then status is 'waiting for the client to click the link'. Run again to finish."""
    d, local, to = _dom(domain), str(local or "").strip().lower(), str(forward_to or "").strip().lower()
    if not re.match(r"^[a-z0-9._+-]+$", local) or "@" not in to:
        return {"ok": False, "err": "need an address name (like contact) and the client's own email"}
    z = zone(d)
    if not z.get("ok"):
        return z
    a = _c()["account_id"]
    _req("POST", "zones/%s/email/routing/enable" % z["id"], {})
    addrs = _req("GET", "accounts/%s/email/routing/addresses?per_page=100" % a).get("result") or []
    dest = next((x for x in addrs if str(x.get("email")).lower() == to), None)
    if not dest:
        _req("POST", "accounts/%s/email/routing/addresses" % a, {"email": to})
        _log("MAIL DEST %s (confirmation link sent)" % to)
        return {"ok": True, "status": "waiting for the client to click the link", "how":
                "Cloudflare just sent %s an email 'Verify your Email Routing address' - ask them to open it and click the link, "
                "then run this again." % to}
    if not dest.get("verified"):
        return {"ok": True, "status": "waiting for the client to click the link", "how":
                "%s has not clicked the Cloudflare confirmation link yet (email 'Verify your Email Routing address', maybe in spam)." % to}
    addr = "%s@%s" % (local, d)
    rules = _req("GET", "zones/%s/email/routing/rules?per_page=100" % z["id"]).get("result") or []
    if not any(any(m.get("value") == addr for m in (x.get("matchers") or [])) for x in rules):
        r = _req("POST", "zones/%s/email/routing/rules" % z["id"], {"name": local, "enabled": True,
                 "matchers": [{"type": "literal", "field": "to", "value": addr}], "actions": [{"type": "forward", "value": [to]}]})
        if not r.get("success"):
            return {"ok": False, "err": str(r.get("errors"))[:200]}
    _log("MAILBOX %s -> %s" % (addr, to))
    return {"ok": True, "status": "live" if z["status"] == "active" else "ready, live once the domain is connected",
            "address": addr}


def _resend(method, path, body=None):
    k = json.load(open(RESEND, encoding="utf-8"))["api_key"]
    rq = urllib.request.Request("https://api.resend.com/" + path, data=json.dumps(body).encode() if body is not None else None,
                                method=method, headers={"Authorization": "Bearer " + k, "Content-Type": "application/json",
                                                        "User-Agent": "kinoverse/1.0"})
    try:
        return json.load(urllib.request.urlopen(rq, timeout=60))
    except urllib.error.HTTPError as e:
        try:
            return {"error": json.loads(e.read() or b"{}"), "http": e.code}
        except Exception:
            return {"error": "http %s" % e.code}


def send_domain(domain):
    """the domain can SEND mail (Resend, DKIM/SPF in its DNS): for the client's contact form, invoices, newsletters"""
    d = _dom(domain)
    z = zone(d)
    if not z.get("ok"):
        return z
    rd = next((x for x in (_resend("GET", "domains").get("data") or []) if x.get("name") == d), None)
    if not rd:
        rd = _resend("POST", "domains", {"name": d, "region": "eu-west-1"})
        if rd.get("error"):
            return {"ok": False, "err": str(rd["error"])[:200]}
    rd = _resend("GET", "domains/%s" % rd["id"])
    for x in rd.get("records") or []:
        n = x["name"] if x["name"].endswith(d) else "%s.%s" % (x["name"], d)
        _record(z["id"], x["type"], n, x["value"], priority=x.get("priority") if x["type"] == "MX" else None)
    if not _req("GET", "zones/%s/dns_records?type=TXT&name=_dmarc.%s" % (z["id"], d)).get("result"):
        _record(z["id"], "TXT", "_dmarc." + d, "v=DMARC1; p=none")
    _resend("POST", "domains/%s/verify" % rd["id"])
    _log("SEND DOMAIN %s %s" % (d, rd.get("status")))
    return {"ok": True, "status": rd.get("status"), "zone": z["status"]}


def setup(name, domain, mail=None, forward_to=None, send=False):
    """everything for one client in one call; safe to run again and again (it only adds what is missing)"""
    out = {"zone": zone(domain)}
    if not out["zone"].get("ok"):
        return out
    out["site"] = site_on_domain(name, domain)
    if mail and forward_to:
        out["mail"] = mailbox(domain, mail, forward_to)
    if send:
        out["send"] = send_domain(domain)
    return out
