"""kino_hands.py (2026-10-31, owner: "the VPS is his body/his world: he takes care of it, builds, tests, experiments safely; all
the tools a human uses on a computer - we give him a life").

His hands on the computer. Every command he runs, runs as the Windows user "kino" (not an administrator), started in his world
C:\\KinoWorld. Windows itself fences him off from the bots, the app, the member terminals, keys and the admin profile (explicit
deny ACLs set at creation), so a mistake in his world cannot break anything outside it. That is the safety - not a word filter.

Outside his world he does not act: he writes a REQUEST (what, why, the exact command) and the owner approves or refuses it.
Every command, its output and its time are logged (robots/kino_hands.log, and C:\\KinoWorld\\diary\\hands.log for him).

run(cmd)            -> {"ok", "code", "out"}   a PowerShell command as kino, cwd = his home, time and output limits
request(...)        -> a request for something outside his world, waiting for the owner
"""
import ctypes, ctypes.wintypes as wt, json, os, re, threading, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = r"C:\KinoWorld"
SECRET = r"C:\ProgramData\kino_secret\pw.txt"
LOG = os.path.join(HERE, "kino_hands.log")
REQ = os.path.join(HERE, "kino_requests.json")
_LK = threading.Lock()
ON_REQUEST = None               # set by the app: posts the request as an approve card in the owner's conversation
LOGON_WITH_PROFILE = 0x1
CREATE_NO_WINDOW = 0x08000000
IDLE_PRIORITY = 0x00000040      # his work never takes the processor from the bots


class _SI(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE)]


class _PI(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _diary(line):
    try:
        open(os.path.join(WORLD, "diary", "hands.log"), "a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M ") + line + "\n")
    except Exception:
        pass


def run(cmd, timeout=120, max_out=12000):
    """one PowerShell command as the user kino, in his home. Output (stdout+stderr) captured through a file in his world."""
    cmd = str(cmd or "").strip()
    if not cmd:
        return {"ok": False, "code": None, "out": "empty command"}
    try:
        pw = open(SECRET, encoding="ascii").read().strip()
    except Exception as e:
        return {"ok": False, "code": None, "out": "no access to his account (%s)" % e}
    rid = uuid.uuid4().hex[:10]
    home = os.path.join(WORLD, "home")
    ps1 = os.path.join(WORLD, "tools", "_run_%s.ps1" % rid)
    out = os.path.join(WORLD, "tools", "_out_%s.txt" % rid)
    open(ps1, "w", encoding="utf-8-sig").write(
        # 2026-11-12 (Pekos chat): PowerShell 5.1 reads a BOM-less UTF-8 file as ANSI - Get-Content turned a Bluesky reply's
        # dash into "â€”" in the words he pasted "word for word". His world's files are UTF-8: read them so by default.
        "$ErrorActionPreference='Continue'\r\n$PSDefaultParameterValues['Get-Content:Encoding']='UTF8'\r\n"
        "$PSDefaultParameterValues['Select-String:Encoding']='UTF8'\r\n$PSDefaultParameterValues['Import-Csv:Encoding']='UTF8'\r\n"
        "try {\r\n& {\r\n%s\r\n} *>&1 | Out-File -FilePath '%s' -Encoding utf8 -Width 200\r\n} catch {\r\n"
        "\"ERROR: \" + $_.Exception.Message | Out-File -FilePath '%s' -Encoding utf8 -Append\r\nexit 1\r\n}\r\nexit $LASTEXITCODE\r\n" % (cmd, out, out))
    line = 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%s"' % ps1
    si, pi = _SI(), _PI()
    si.cb = ctypes.sizeof(_SI)
    buf = ctypes.create_unicode_buffer(line)
    t0 = time.time()
    ok = ctypes.windll.advapi32.CreateProcessWithLogonW("kino", ".", pw, LOGON_WITH_PROFILE, None, buf, CREATE_NO_WINDOW | IDLE_PRIORITY,
                                                        None, home, ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        err = ctypes.GetLastError()
        _log("RUN-FAIL start error %s: %s" % (err, cmd[:200]))
        return {"ok": False, "code": None, "out": "could not start (Windows error %s)" % err}
    k32 = ctypes.windll.kernel32
    r = k32.WaitForSingleObject(pi.hProcess, int(timeout * 1000))
    code = wt.DWORD()
    timed_out = r != 0
    if timed_out:
        k32.TerminateProcess(pi.hProcess, 1)
    k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    k32.CloseHandle(pi.hProcess)
    k32.CloseHandle(pi.hThread)
    txt = ""
    try:
        txt = open(out, encoding="utf-8-sig", errors="replace").read()
    except Exception:
        pass
    for f in (ps1, out):
        try:
            os.remove(f)
        except Exception:
            pass
    if timed_out:
        txt += "\n[stopped after %d s]" % timeout
    if len(txt) > max_out:
        txt = txt[:max_out // 2] + "\n[... %d characters cut ...]\n" % (len(txt) - max_out) + txt[-max_out // 2:]
    res = {"ok": (not timed_out) and code.value == 0, "code": code.value, "out": txt.strip(), "s": round(time.time() - t0, 1)}
    _log("RUN code=%s %.1fs %s | %s" % (code.value, res["s"], cmd[:300].replace("\n", " ; "), res["out"][:300].replace("\n", " | ")))
    _diary("$ %s  -> code %s" % (cmd[:200].replace("\n", " ; "), code.value))
    return res


# --------------------------------------------------------------------------------- outside his world: he asks
def _rload():
    try:
        return json.load(open(REQ, encoding="utf-8"))
    except Exception:
        return []


def _rsave(R):
    tmp = REQ + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(R, ensure_ascii=False, indent=1))
    os.replace(tmp, REQ)


def request(what, why, command="", kind="admin", extra=None):
    """a request for something outside his world (the owner decides)"""
    with _LK:
        R = _rload()
        if any(r["status"] == "waiting" and r["what"] == what for r in R):
            return None
        # 2026-11-13 (watch: 23 cards "send email to Trattoria Don Vito" in 2 h, worded a little differently each time): a
        # request that looks like one already waiting is the same request; and at most 6 new ones reach Matsy in 2 h
        _w = lambda t: {x for x in re.findall(r"[\w@.]{4,}", str(t).lower())}
        _me = _w(what)
        for r0 in R:
            if r0["status"] == "waiting" and _me:
                _o = _w(r0["what"])
                if _o and len(_me & _o) / float(min(len(_me), len(_o))) >= 0.6:
                    return None
        if sum(1 for r0 in R if time.time() - float(r0.get("t") or 0) < 7200) >= 6 and kind not in ("buy", "paycheck"):
            _log("REQUEST HELD (6 in 2 h already): %s" % str(what)[:150])
            return None
        r = {"id": uuid.uuid4().hex[:8], "t": time.time(), "what": str(what)[:300], "why": str(why)[:500],
             "command": str(command)[:2000], "kind": kind, "status": "waiting"}
        r.update(extra or {})
        R.append(r)
        _rsave(R[-200:])
    _log("REQUEST %s %s | %s" % (r["id"], r["what"], r["command"][:200]))
    try:
        if ON_REQUEST:
            ON_REQUEST(r)
    except Exception as e:
        _log("ON_REQUEST error %s" % e)
    return r


def mark(rid, **kw):
    with _LK:
        R = _rload()
        x = next((y for y in R if y["id"] == rid), None)
        if x:
            x.update(kw)
            _rsave(R)


def requests(status=None):
    return [r for r in _rload() if status is None or r["status"] == status]


def decide(rid, yes, by="owner", note=""):
    """the owner's answer; an approved admin command is run by the app (as administrator) and the result kept"""
    with _LK:
        R = _rload()
        r = next((x for x in R if x["id"] == rid), None)
        if not r or r["status"] != "waiting":
            return None
        r.update(status="approved" if yes else "refused", by=by, note=str(note)[:300], decided_t=time.time())
        _rsave(R)
    _log("DECIDE %s %s by %s %s" % (rid, r["status"], by, note))
    if yes and r.get("kind") == "email":              # an email to someone new: approved -> sent, and that person is allowed now
        try:
            import kino_mail as KM
            m = json.loads(r["command"])
            KM.allow(m["to"])
            KM.send_now(m["to"], m.get("subject") or "", m.get("body") or "", files=m.get("files") or None)
            res, code = "sent", 0
        except Exception as e:
            res, code = str(e)[:300], None
        with _LK:
            R = _rload()
            x = next((y for y in R if y["id"] == rid), None)
            if x:
                x.update(result=res, code=code, done_t=time.time())
                _rsave(R)
        _log("DONE %s email %s" % (rid, res))
        return r
    if r.get("kind") == "domain":                    # 2026-11-12: a client's domain, bought only on the owner's yes
        if yes:
            try:
                import kino_cf as KCF
                m = json.loads(r["command"])
                b = KCF.buy_domain(m["domain"], rid, contact=m.get("contact"))
                res = ("bought (%s, %.2f USD) - run domain for %s to put the site and mail on it" % (b.get("state"), b.get("usd") or 0, m.get("who"))
                       if b.get("ok") else "not bought: %s" % b.get("err"))
            except Exception as e:
                res = "failed: %s" % str(e)[:200]
            mark(rid, result=res, done_t=time.time())
            _log("DONE %s domain %s" % (rid, res))
        return r
    if r.get("kind") == "paycheck":                  # 2026-11-01: a PayPal payment the owner confirms he received
        if yes:
            try:
                import kino_pay as KPY
                x = next((i for i in KPY._load()["invoices"] if i["ref"] == r.get("command")), {})
                KPY.paid("kino|earn-%s|0" % r.get("command"), x.get("usd"), "paypal-confirmed")
                mark(rid, result="confirmed - delivered")
                if x.get("payer") and "@" in x["payer"]:
                    try:
                        import kino_mail as KM, kino_shop as KS
                        KM.allow(x["payer"])
                        KM.send_now(x["payer"], "Your download from Kino", "Thank you! Your payment is confirmed.\n\nDownload: "
                                    "https://kino.owltrader.duckdns.org/got/%s/%s\n\n- Kino (an AI)" % (x["ref"], KS._token(x["ref"])))
                    except Exception:
                        pass
            except Exception as e:
                mark(rid, result="failed: %s" % str(e)[:200])
        return r
    if r.get("kind") == "buy":                       # 2026-11-13 (owner: option 1): Matsy placed the order (yes) or could not (no)
        try:
            import kino_missions as KMb
            m = json.loads(r["command"])
            KMb.update(m["mission"], status="working", next_h=0.25,
                       note=("ORDER PLACED by Matsy for %s (%s EUR at %s)%s - tell them it is ordered, then follow the delivery "
                             "until it arrives" % (m.get("item"), m.get("price_eur"), m.get("shop"), (": " + note) if note else ""))
                       if yes else ("Matsy could NOT place the order for %s%s - find another shop or offer, or refund them"
                                    % (m.get("item"), (": " + note) if note else "")))
            mark(rid, result="ordered" if yes else "not ordered", done_t=time.time())
        except Exception as e:
            mark(rid, result="failed: %s" % str(e)[:200])
        return r
    if r.get("kind") == "proposal":                  # an idea: the answer is the decision itself, nothing runs
        return r
    if r.get("kind") == "publish":                   # his files, staged when he asked, go to GitHub (the token never reaches him)
        if yes:
            try:
                import kino_github as KG
                mark(rid, result=KG.publish(r.get("stage"), r.get("repo"), r.get("desc") or ""))
            except Exception as e:
                mark(rid, result="failed: %s" % str(e)[:250])
            _log("DONE %s publish %s" % (rid, next((x.get("result") for x in _rload() if x["id"] == rid), "")))
        return r
    if r.get("kind") == "site":                      # a permit to SEND on one website (kino_browser gate), for a day
        if yes:
            try:
                import kino_browser as KBR
                d = KBR.grant(r.get("command") or "")
                mark(rid, result="permit for %s (%d h)" % (d, KBR.PERMIT_H))
            except Exception as e:
                mark(rid, result=str(e)[:200])
        return r
    if yes and r.get("command"):
        import subprocess
        try:
            p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", r["command"]],
                               capture_output=True, text=True, timeout=600)
            res = (p.stdout + p.stderr)[-4000:]
            code = p.returncode
        except Exception as e:
            res, code = str(e), None
        with _LK:
            R = _rload()
            x = next((y for y in R if y["id"] == rid), None)
            if x:
                x.update(result=res, code=code, done_t=time.time())
                _rsave(R)
        _log("DONE %s code=%s %s" % (rid, code, res[:300].replace("\n", " | ")))
    return r
