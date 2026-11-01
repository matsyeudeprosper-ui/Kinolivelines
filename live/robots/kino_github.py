"""kino_github.py (2026-11-01, owner approved Kino's proposal #2: a small free tool published on GitHub; owner: "outside his
world he asks for everything").

His GitHub account is kinoverse26-byte. The token lives only in C:\\ProgramData\\kino_secret\\github.txt (his Windows user is
denied there), so he can never push on his own: he asks with a "publish" request, the owner approves the card, the app uploads.

What the owner approves is what goes out: at request time the files are COPIED out of his world into a staging folder he cannot
touch (C:\\ProgramData\\kino_publish\\<id>), and the card lists every file with its size. Changing the files after the card is
answered changes nothing - a new version is a new request. A file that contains one of his real secrets (Windows password, mail
app password, this token) stops the request: that check compares against the secret values themselves.

stage(folder, files=None) -> (sid, [(rel, bytes)])   copy for review
publish(sid, repo, description) -> url                 create the repo if needed, upload every staged file
"""
import base64, json, os, re, shutil, subprocess, time, urllib.error, urllib.request, uuid

WORLD = r"C:\KinoWorld"
PROJECTS = os.path.join(WORLD, "projects")
SECRET_DIR = r"C:\ProgramData\kino_secret"
TOKEN = os.path.join(SECRET_DIR, "github.txt")
STAGE = r"C:\ProgramData\kino_publish"
ACCOUNT = "kinoverse26-byte"
API = "https://api.github.com"
MAX_FILE, MAX_TOTAL, MAX_FILES = 1_000_000, 5_000_000, 60
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules"}
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kino_github.log")


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _stage_root():
    """his user must not be able to swap a staged file after the owner saw the list"""
    if not os.path.isdir(STAGE):
        os.makedirs(STAGE)
        subprocess.run(["icacls", STAGE, "/inheritance:r", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                       capture_output=True)
    return STAGE


def _secrets():
    out = []
    for fn in os.listdir(SECRET_DIR):
        try:
            s = open(os.path.join(SECRET_DIR, fn), encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        try:
            d = json.loads(s)
            out += [str(v) for v in d.values() if isinstance(v, str) and len(v) >= 8 and "@" not in v]
            out += [x.replace(" ", "") for x in out if " " in x]
        except Exception:
            if len(s.strip()) >= 8:
                out.append(s.strip())
    return [x for x in out if x]


def repo_name(s):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(s or "").strip()).strip("-.")
    return s[:80]


def stage(folder, files=None):
    """copy his project (or only the listed files) out of his world -> (sid, [(rel, size)])"""
    src = os.path.realpath(str(folder or ""))
    if not src.lower().startswith(os.path.realpath(PROJECTS).lower() + os.sep) or not os.path.isdir(src):
        raise ValueError("the folder must be one of your projects in %s" % PROJECTS)
    picked = []
    if files:
        for f in files:
            p = os.path.realpath(os.path.join(src, str(f)))
            if not p.lower().startswith(src.lower() + os.sep) or not os.path.isfile(p):
                raise ValueError("not a file of that project: %s" % f)
            picked.append(p)
    else:
        for root, dirs, fs in os.walk(src):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            picked += [os.path.join(root, f) for f in fs if not f.startswith(".") and not f.endswith(".pyc")]
    if not picked:
        raise ValueError("no file to publish")
    if len(picked) > MAX_FILES:
        raise ValueError("%d files - at most %d" % (len(picked), MAX_FILES))
    sec = _secrets()
    total, rows = 0, []
    for p in picked:
        n = os.path.getsize(p)
        if n > MAX_FILE:
            raise ValueError("%s is %d KB - at most %d KB per file" % (os.path.relpath(p, src), n // 1000, MAX_FILE // 1000))
        total += n
        b = open(p, "rb").read()
        if any(s.encode("utf-8") in b for s in sec):
            raise ValueError("%s contains one of your secrets - it cannot go out" % os.path.relpath(p, src))
        rows.append((os.path.relpath(p, src).replace("\\", "/"), n))
    if total > MAX_TOTAL:
        raise ValueError("%d KB in all - at most %d KB" % (total // 1000, MAX_TOTAL // 1000))
    sid = uuid.uuid4().hex[:10]
    dst = os.path.join(_stage_root(), sid)
    for rel, _ in rows:
        os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
        shutil.copyfile(os.path.join(src, rel), os.path.join(dst, rel))
    _log("STAGE %s %s %d files %d bytes" % (sid, src, len(rows), total))
    return sid, rows


def _call(method, path, body=None):
    tok = open(TOKEN, encoding="ascii").read().strip()
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json",
                                          "User-Agent": "kino", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def publish(sid, repo, description=""):
    """the owner approved: create the repo if it does not exist, then upload every staged file (an update keeps history)"""
    repo = repo_name(repo)
    src = os.path.join(STAGE, re.sub(r"[^0-9a-f]", "", str(sid)))
    if not repo or not os.path.isdir(src):
        raise ValueError("nothing staged for this request")
    st, _ = _call("GET", "/repos/%s/%s" % (ACCOUNT, repo))
    if st == 404:
        st, d = _call("POST", "/user/repos", {"name": repo, "description": str(description)[:300], "private": False,
                                               "auto_init": False, "has_wiki": False})
        if st not in (200, 201):
            raise RuntimeError("could not create the repo (%s %s)" % (st, d.get("message")))
    n = 0
    for root, _, fs in os.walk(src):
        for f in fs:
            rel = os.path.relpath(os.path.join(root, f), src).replace("\\", "/")
            path = "/repos/%s/%s/contents/%s" % (ACCOUNT, repo, urllib.request.quote(rel))
            st, d = _call("GET", path)
            body = {"message": "Kino: %s" % rel, "content": base64.b64encode(open(os.path.join(root, f), "rb").read()).decode()}
            if st == 200 and isinstance(d, dict) and d.get("sha"):
                body["sha"] = d["sha"]
            st, d = _call("PUT", path, body)
            if st not in (200, 201):
                raise RuntimeError("upload of %s failed (%s %s) after %d files" % (rel, st, d.get("message"), n))
            n += 1
    url = "https://github.com/%s/%s" % (ACCOUNT, repo)
    _log("PUBLISH %s -> %s (%d files)" % (sid, url, n))
    return url
