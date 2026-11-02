"""kino_care.py (2026-11-01, owner: "the VPS is his body... he must take care of it, fixing it, cleaning etc.") - phase 5.

A person looks after their body from what they can feel and what a check-up tells them. Kino is a standard user and cannot
see most of the machine, so the app (administrator) writes him a CHECK-UP every 10 minutes into his world -
C:\\KinoWorld\\body\\health.txt: free disk, processor and memory, the heaviest programs (names only, no command lines), how many
bots and app processes run, errors in the last hour, the biggest folders (hourly, sizes only - never contents, never secrets).
He reads it like a chart. When his body is out of balance (kino_body), it pulls him to his computer (kino_work.due), and what
he wants done outside his world goes to the owner as a request card with the exact command - nothing happens without that tap.

Log robots/kino_care.log (git-ignored).
"""
import json, os, subprocess, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = r"C:\KinoWorld"
OUT = os.path.join(WORLD, "body", "health.txt")
LOG = os.path.join(HERE, "kino_care.log")
_S = {"t": 0, "sizes_t": 0, "sizes": [], "busy": False}
WATCH = [r"C:\Users\Administrator\AppData\Local\Temp", r"C:\Windows\Temp", r"C:\Users\Administrator\backups",
         r"C:\Users\Administrator\.cache", r"C:\Users\Administrator\AppData\Roaming\MetaQuotes", r"C:\Projects\KinoliveLines",
         r"C:\Users\Administrator\open-webui-src", r"C:\KinoWorld", r"C:\Windows\SoftwareDistribution\Download",
         r"C:\ProgramData\Microsoft\Windows\WER"]


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _size(p, cap_s=120):
    t0, tot = time.time(), 0
    for r, ds, fs in os.walk(p):
        for f in fs:
            try:
                tot += os.path.getsize(os.path.join(r, f))
            except Exception:
                pass
        if time.time() - t0 > cap_s:
            return tot, True
    return tot, False


def _sizes():
    S = []
    for p in WATCH:
        if os.path.exists(p):
            b, part = _size(p)
            S.append((p, round(b / 1e9, 2), part))
            time.sleep(1)
    return sorted(S, key=lambda x: -x[1])


def _procs():
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                              "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 12 Name,"
                              "@{n='MB';e={[int]($_.WorkingSet64/1MB)}},@{n='CPUs';e={[int]$_.CPU}} | ConvertTo-Json -Compress"],
                             capture_output=True, text=True, timeout=60)
        P = json.loads(out.stdout or "[]")
        return P if isinstance(P, list) else [P]
    except Exception:
        return []


def _groups():
    """2026-11-02 (owner: "Kino was supposed to pick up that cpu and clean up - why did he do nothing"): 234 small hidden
    test browsers ate the processor and never showed among the heaviest single programs. Counted by name, a swarm shows."""
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                              "Get-Process | Group-Object Name | Sort-Object Count -Descending | Select-Object -First 8 Name,Count,"
                              "@{n='MB';e={[int](($_.Group | Measure-Object WorkingSet64 -Sum).Sum/1MB)}} | ConvertTo-Json -Compress"],
                             capture_output=True, text=True, timeout=60)
        G = json.loads(out.stdout or "[]")
        return G if isinstance(G, list) else [G]
    except Exception:
        return []


# a body reflex, not a decision: hidden test browsers left behind by a finished screenshot/check script (headless, a
# throw-away profile in a Temp folder, open 30 min or more). Never his own browser (Playwright / KinoWorld profiles).
_REFLEX = os.path.join(HERE, "kino_reflex.ps1")   # the reflex itself (a script file: no quoting traps)


def reflex_clean(min_age=30):
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", _REFLEX, "-MinAge", str(min_age)],
                             capture_output=True, text=True, timeout=120)
        n = int((out.stdout or "0").strip().splitlines()[-1] or 0)
    except Exception:
        n = 0
    if n:
        _S["reflex"] = (time.time(), n)
        _log("REFLEX closed %d leftover hidden test browsers" % n)
    return n


def write_checkup():
    """the check-up in his world (called from the app every minute; works every 10 min; folder sizes hourly in background)"""
    now = time.time()
    if now - _S["t"] < 600:
        return False
    _S["t"] = now
    if now - _S["sizes_t"] > 3600 and not _S["busy"]:
        _S["busy"] = True

        def bg():
            try:
                _S["sizes"] = _sizes()
                _S["sizes_t"] = time.time()
            finally:
                _S["busy"] = False
        threading.Thread(target=bg, daemon=True).start()
    L = ["CHECK-UP of your machine - %s UTC (written by the app; you cannot see these places yourself)" % time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)), ""]
    try:
        import kino_body as KB
        d = KB.sense()
        L.append("Body signals (0 = fine, 1 = badly out of balance): " + ", ".join("%s %.2f" % kv for kv in (d.get("gap") or {}).items()))
        L.append("Raw: " + json.dumps(d.get("raw") or {}))
    except Exception as e:
        L.append("body signals unavailable: %s" % e)
    reflex_clean()
    if _S.get("reflex") and now - _S["reflex"][0] < 86400:
        L.append("")
        L.append("Your body cleaned itself at %s UTC: it closed %d hidden test browsers left open by a finished check "
                 "(they were eating the processor). Nothing for you to do - tell the owner if he asks why things were slow." % (
                     time.strftime("%H:%M", time.gmtime(_S["reflex"][0])), _S["reflex"][1]))
    G = _groups()
    if G:
        L.append("")
        L.append("Programs counted by name (name, how many, MB together) - a swarm of small ones shows here:")
        L += ["  %s x%s, %s MB" % (g.get("Name"), g.get("Count"), g.get("MB")) for g in G]
    P = _procs()
    if P:
        L.append("")
        L.append("Heaviest programs in memory (name, MB, CPU seconds since start):")
        L += ["  %s %s MB %s s" % (p.get("Name"), p.get("MB"), p.get("CPUs")) for p in P]
        names = [str(p.get("Name") or "").lower() for p in P]
        L.append("python processes among them: %d" % sum(1 for n in names if n.startswith("python")))
    if _S["sizes"]:
        L.append("")
        L.append("Biggest folders I watch (GB, measured %d min ago; '+' = still counting):" % ((now - _S["sizes_t"]) / 60))
        L += ["  %s  %.2f%s" % (p, gb, "+" if part else "") for p, gb, part in _S["sizes"]]
    try:
        errs = sum(1 for l in open(os.path.join(HERE, "chat_errors.log"), encoding="utf-8", errors="replace") if l[:10] == time.strftime("%Y-%m-%d"))
        L.append("")
        L.append("Conversation errors logged today: %d" % errs)
    except Exception:
        pass
    L.append("")
    L.append("You can ask for a fix outside your world with a request (exact PowerShell command + why); the owner decides. Never "
             "ask to touch C:\\Projects, the bots, MetaQuotes data, keys or member data - those are not yours to clean.")
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    except Exception as e:
        _log("ERR write %s" % e)
        return False
    return True


def out_of_balance():
    """the body signal that needs care, or None"""
    try:
        import kino_body as KB
        g = (KB._load().get("gap") or {})
        k = max(g, key=lambda x: float(g[x] or 0)) if g else None
        return (k, float(g[k])) if k and float(g[k]) >= 0.5 else None
    except Exception:
        return None
