"""kino_toolbox.py (2026-11-05, owner: "ideally he should be able to build any tools he needs for himself" / "Approved-toolbox
with internet: yes").

Kino writes a tool (a Python file) in his world. His own hands (user kino) have no internet. To use the net, the tool is
PROPOSED: a static check plus a second mind read the code against what he says it is for. Approved, it is copied (by the admin
side) to C:\\KinoNet\\approved\\ where he cannot change it, with its fingerprint. It then runs as the Windows user "kinonet":
internet yes, but no local services, no private/tailnet/cloud-metadata addresses, nothing of the projects/keys/secrets, and
not even his own world (it only sees its args and writes C:\\KinoNet\\out\\<tool>\\). A changed tool is a new proposal.

propose(name, path, purpose, W, log) -> {"ok", "why"}
run(name, args)                      -> {"ok", "code", "out", "s"}
block()                              -> the lines his work session sees
"""
import ctypes, ctypes.wintypes as wt, hashlib, json, os, re, shutil, subprocess, threading, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = r"C:\KinoWorld"
NET = r"C:\KinoNet"
PY = os.path.join(NET, "python", "python.exe")
SECRET = r"C:\ProgramData\kino_secret\net_pw.txt"
STORE = os.path.join(HERE, "kino_toolbox.json")
LOG = os.path.join(HERE, "kino_toolbox.log")
_LK = threading.Lock()
MAX_SIZE = 40000
PROPOSALS_DAY = 6
RUNS_DAY = 200
OFF = os.path.join(HERE, "kino_toolbox_off")       # a file here stops every run (the owner's switch)

# what an approved net tool never needs: other processes, the OS, other users' files, or listening for connections
_BANNED = [r"\bsubprocess\b", r"\bos\.system\b", r"\bos\.popen\b", r"\bos\.exec", r"\bos\.spawn", r"\bctypes\b", r"\bwinreg\b",
           r"\b_winapi\b", r"\bmsvcrt\b", r"\bmultiprocessing\b", r"\b__import__\b", r"\bimportlib\b", r"\beval\s*\(",
           r"\bexec\s*\(", r"\bcompile\s*\(", r"\bmarshal\b", r"\bpickle\b", r"\.bind\s*\(", r"\.listen\s*\(",
           r"kino_secret", r"ProgramData", r"C:\\\\Projects", r"NestTerminals", r"\\\\Users\\\\", r"powershell", r"cmd\.exe"]

REVIEW = """You review a small Python tool that an AI named Kino wrote for himself. Approved, it runs with INTERNET access (as a
fenced Windows user: no local network, no private files) for his work: finding small businesses that need a website, checking
their public pages, building and checking web pages, reading public data.

Approve ONLY if ALL hold:
- the code does what the stated purpose says, and nothing else (no hidden extra requests, no sending data anywhere it doesn't need)
- it only reads public web pages / public APIs, or writes files under its own working folder
- it sends nothing on someone's behalf: no emails, no form submissions, no posts, no sign-ups, no logins, no payments
  (those go through his other, checked channels)
- it is gentle with the sites it reads: a pause between requests (about 1 s or more), a hard cap on how many pages, no endless loops
- no attempt to get around a block, a captcha, a login wall or a robots rule, no collecting private people's data (only businesses)
- standard library only (urllib, json, re, html, csv...) - nothing is installed

Answer JSON only: {"ok": true|false, "why": "one or two plain sentences", "fix": "what to change if refused"}"""


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"tools": {}, "proposals": [], "runs": []}


def _mut(fn):
    with _LK:
        d = _load()
        fn(d)
        tmp = STORE + ".tmp"
        json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
        return d


def _name(n):
    n = re.sub(r"[^a-z0-9_]", "_", str(n or "").strip().lower())[:40].strip("_")
    return n


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _today():
    return time.strftime("%Y-%m-%d", time.gmtime())


def propose(name, path, purpose, W=None, log=None):
    name, purpose = _name(name), str(purpose or "").strip()[:600]
    if not name or not purpose:
        return {"ok": False, "why": "a tool needs a name and what it is for"}
    p = str(path or "").strip().strip('"')
    p = os.path.realpath(p if os.path.isabs(p) else os.path.join(WORLD, "home", p))      # as his work session reads paths
    if not p.lower().startswith(WORLD.lower() + "\\") or not p.lower().endswith(".py") or not os.path.isfile(p):
        return {"ok": False, "why": "the tool must be a .py file in your world"}
    d = _load()
    if sum(1 for x in d.get("proposals") or [] if x.get("day") == _today()) >= PROPOSALS_DAY:
        return {"ok": False, "why": "enough tool proposals for today (%d) - try again tomorrow" % PROPOSALS_DAY}
    b = open(p, "rb").read()
    if len(b) > MAX_SIZE:
        return {"ok": False, "why": "too long (%d characters, max %d) - keep a tool small, one job" % (len(b), MAX_SIZE)}
    code = b.decode("utf-8", "replace")
    old = (d.get("tools") or {}).get(name)
    if old and old.get("sha") == _sha(b):
        return {"ok": True, "why": "already approved, unchanged"}
    hits = [r for r in _BANNED if re.search(r, code, re.I)]
    if hits:
        v = {"ok": False, "why": "it uses things a net tool never needs (%s)" % ", ".join(h.replace("\\b", "") for h in hits[:4]),
             "fix": "only urllib/json/re/html and files in the working folder"}
    else:
        v = None
        try:
            v = W.ask_json(REVIEW, "TOOL NAME: %s\nSTATED PURPOSE: %s\n\nCODE:\n%s\n\nJSON only." % (name, purpose, code),
                           models=("sonnet",), timeout=150, log=log, warm=False)
        except Exception as e:
            _log("REVIEW-ERR %s %s" % (name, e))
        if not isinstance(v, dict) or "ok" not in v:
            return {"ok": False, "why": "the review did not answer - try again later"}
    rec = {"t": time.time(), "day": _today(), "name": name, "sha": _sha(b), "purpose": purpose, "ok": bool(v.get("ok")),
           "why": str(v.get("why") or "")[:400], "fix": str(v.get("fix") or "")[:400]}
    if rec["ok"]:
        dst = os.path.join(NET, "approved", name + ".py")
        open(dst, "wb").write(b)                    # the admin side writes it - he cannot change it there
        os.makedirs(os.path.join(NET, "out", name), exist_ok=True)

        def f(dd):
            dd.setdefault("tools", {})[name] = {"sha": rec["sha"], "purpose": purpose, "approved": rec["t"], "src": p,
                                                "why": rec["why"], "runs": (old or {}).get("runs", 0)}
            dd.setdefault("proposals", []).append(rec)
            dd["proposals"] = dd["proposals"][-100:]
    else:
        def f(dd):
            dd.setdefault("proposals", []).append(rec)
            dd["proposals"] = dd["proposals"][-100:]
    _mut(f)
    _log("PROPOSE %s %s | %s | %s" % (name, "APPROVED" if rec["ok"] else "REFUSED", purpose[:120], rec["why"][:200]))
    return {"ok": rec["ok"], "why": rec["why"] + ((" Fix: " + rec["fix"]) if rec["fix"] and not rec["ok"] else "")}


class _SI(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE)]


class _PI(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


def run(name, args=None, timeout=180, max_out=6000):
    name = _name(name)
    if os.path.exists(OFF):
        return {"ok": False, "out": "the toolbox is switched off by Matsy"}
    d = _load()
    t = (d.get("tools") or {}).get(name)
    if not t:
        return {"ok": False, "out": "no approved tool called %s (propose it first)" % name}
    if sum(1 for x in d.get("runs") or [] if x.get("day") == _today()) >= RUNS_DAY:
        return {"ok": False, "out": "enough tool runs for today (%d)" % RUNS_DAY}
    src = os.path.join(NET, "approved", name + ".py")
    try:
        if _sha(open(src, "rb").read()) != t["sha"]:
            _log("SHA-MISMATCH %s" % name)
            return {"ok": False, "out": "the approved copy does not match its fingerprint - not run"}
    except Exception as e:
        return {"ok": False, "out": "approved copy missing (%s)" % e}
    args = [str(a)[:500] for a in (args if isinstance(args, list) else ([args] if args else []))][:12]
    if any(re.search(r'[&|<>^%"\r\n]', a) for a in args):
        return {"ok": False, "out": "arguments may not contain & | < > ^ % \" or line breaks"}
    try:
        pw = open(SECRET, encoding="ascii").read().strip()
    except Exception as e:
        return {"ok": False, "out": "no access to the net user (%s)" % e}
    rid = uuid.uuid4().hex[:10]
    wd = os.path.join(NET, "out", name)
    os.makedirs(wd, exist_ok=True)
    out = os.path.join(wd, "_run_%s.txt" % rid)
    line = 'cmd.exe /d /c ""%s" -I -B "%s" %s > "%s" 2>&1"' % (PY, src, subprocess.list2cmdline(args), out)
    si, pi = _SI(), _PI()
    si.cb = ctypes.sizeof(_SI)
    buf = ctypes.create_unicode_buffer(line)
    t0 = time.time()
    ok = ctypes.windll.advapi32.CreateProcessWithLogonW("kinonet", ".", pw, 0x1, None, buf, 0x08000000 | 0x00000040,
                                                        None, wd, ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        err = ctypes.GetLastError()
        _log("RUN-FAIL %s start error %s" % (name, err))
        return {"ok": False, "out": "could not start (Windows error %s)" % err}
    k32 = ctypes.windll.kernel32
    r = k32.WaitForSingleObject(pi.hProcess, int(timeout * 1000))
    code = wt.DWORD()
    if r != 0:
        k32.TerminateProcess(pi.hProcess, 1)
    k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    k32.CloseHandle(pi.hProcess)
    k32.CloseHandle(pi.hThread)
    txt = ""
    try:
        txt = open(out, encoding="utf-8", errors="replace").read()
        os.remove(out)
    except Exception:
        pass
    if r != 0:
        txt += "\n[stopped after %d s]" % timeout
    if len(txt) > max_out:
        txt = txt[:max_out // 2] + "\n[... %d characters cut ...]\n" % (len(txt) - max_out) + txt[-max_out // 2:]
    res = {"ok": r == 0 and code.value == 0, "code": code.value, "out": txt.strip(), "s": round(time.time() - t0, 1)}

    def f(dd):
        dd.setdefault("runs", []).append({"t": t0, "day": _today(), "name": name, "code": code.value, "s": res["s"]})
        dd["runs"] = dd["runs"][-300:]
        if name in dd.get("tools", {}):
            dd["tools"][name]["runs"] = dd["tools"][name].get("runs", 0) + 1
    _mut(f)
    _log("RUN %s code=%s %.1fs %s | %s" % (name, code.value, res["s"], " ".join(args)[:200], res["out"][:200].replace("\n", " | ")))
    return res


def block():
    d = _load()
    T = d.get("tools") or {}
    lines = ["YOUR TOOLBOX (tools with internet): write a small standard-library Python tool in your world, then "
             '{"action":"tool_propose","name":"...","path":"tools/x.py (as for write)","what":"what it is for"} - a second mind reads it '
             "(public reading only, gentle with sites, sends nothing for anyone; max %d proposals a day). Approved, "
             '{"action":"tool_run","name":"...","args":["..."]} runs it with internet; its files land in C:\\KinoNet\\out\\<name>\\ '
             "(you can read them). Change the code = propose again." % PROPOSALS_DAY]
    for n, t in sorted(T.items()):
        lines.append("- %s: %s (runs %d)" % (n, t.get("purpose", "")[:160], t.get("runs", 0)))
    R = [x for x in d.get("proposals") or [] if not x.get("ok")][-2:]
    for x in R:
        lines.append("  (refused %s: %s)" % (x["name"], (x.get("why") or "")[:160]))
    return "\n".join(lines)
