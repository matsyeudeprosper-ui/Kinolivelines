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
