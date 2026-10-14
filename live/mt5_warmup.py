"""mt5_warmup.py - bring every MT5 terminal up ONE AT A TIME after a reboot.

Why (2026-10-14 reboot): MT5 build 6230 was waiting to install. At logon
every script that calls mt5.initialize() (recorders, observers, 8 bots,
9 nest workers, chart feeds) hit a terminal that was busy updating, timed
out, and launched ANOTHER copy. 85 terminals later WMI hung, the 5-min
watchdog froze and every bot died with "MT5 init failed". About 1 h down.
Killing the stuck copies then killed liveupdate\\terminal64.exe mid-write
and left 4 truncated exe files ("Process create failed").

So, after each boot, boot_all runs this BEFORE starting anything that
talks to MT5, and the logon tasks wait for it (mt5_gate.ps1):
  * one terminal at a time, never in parallel
  * while an updater (liveupdate\\terminal64.exe) runs: wait, NEVER kill it
  * at most MAX_TRIES initialize() calls per terminal, so a stuck terminal
    costs a few extra copies, not dozens
  * an exe without a version resource (truncated) is reported, not started

    python mt5_warmup.py           warm up, write mt5_ready.json
    python mt5_warmup.py --check   exit 0 if the warm-up already ran since
                                   this boot, 1 otherwise (used by the gates)
"""
import ctypes
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
READY = os.path.join(HERE, "mt5_ready.json")
LOG = os.path.join(HERE, "mt5_warmup.log")
PY = sys.executable.replace("pythonw.exe", "python.exe")

# terminals that are not in owl_nest_users.json but are used (recorders use
# the default install; structure_bos_bot labo uses u476989740; the old
# standard account runs the manual desk). Not u476989735: only the retired
# 'sniper' variant used it and it never answers (cost 11 min on 10-14).
EXTRA = [
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
    r"C:\Projects\MT5-KinoliveTrader\terminal64.exe",
    r"C:\NestTerminals\u476989740\terminal64.exe",
]
INIT_TIMEOUT_S = 180       # one initialize() call may take this long
MAX_TRIES = 3              # initialize() calls per terminal
UPDATE_WAIT_S = 900        # longest wait for an updater to finish
BOOT_TOL_S = 120           # two boot-time readings closer than this = same boot


def say(m):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def boot_epoch():
    ms = ctypes.windll.kernel32.GetTickCount64
    ms.restype = ctypes.c_ulonglong
    return time.time() - ms() / 1000.0


def ready_for_this_boot():
    try:
        with open(READY, encoding="utf-8") as f:
            r = json.load(f)
        return abs(float(r["boot"]) - boot_epoch()) < BOOT_TOL_S
    except (OSError, ValueError, KeyError):
        return False


def terminals():
    seen, out = set(), []
    paths = list(EXTRA)
    try:
        with open(os.path.join(HERE, "owl_nest_users.json"), encoding="utf-8") as f:
            paths += [u.get("terminal") for u in json.load(f)]
    except (OSError, ValueError):
        say("could not read owl_nest_users.json - extra list only")
    for p in paths:
        if p and os.path.normcase(p) not in seen:
            seen.add(os.path.normcase(p))
            out.append(p)
    return out


def exe_ok(path):
    """A truncated exe (killed updater) has no version resource."""
    if not os.path.exists(path):
        return False
    return ctypes.windll.version.GetFileVersionInfoSizeW(path, None) > 0


def running_paths():
    """Paths of running terminal64 processes; None if we cannot tell.
    Get-Process, not CIM: CIM is what hung under load on 2026-10-14."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-Process terminal64 -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }"],
            capture_output=True, text=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except Exception as e:
        say(f"  cannot list terminals: {type(e).__name__}")
        return None
    return [p.strip() for p in out.splitlines() if p.strip()]


def wait_for_updaters():
    t0 = time.time()
    while time.time() - t0 < UPDATE_WAIT_S:
        rp = running_paths()
        busy = [p for p in (rp or []) if "\\liveupdate\\" in p.lower()]
        if not busy:
            return True
        say(f"  MT5 update installing ({len(busy)} updater) - waiting, never killing it")
        time.sleep(15)
    say("  updater still running after the wait - continuing anyway")
    return False


PROBE = r"""
import sys, MetaTrader5 as mt5
ok = mt5.initialize(path=sys.argv[1], timeout=int(sys.argv[2]) * 1000)
if not ok:
    print("FAIL", mt5.last_error()); sys.exit(1)
a = mt5.account_info(); ti = mt5.terminal_info()
print("OK", a.login if a else None, "build", ti.build if ti else None,
      "connected", ti.connected if ti else None)
mt5.shutdown()   # detaches; the terminal keeps running
"""


def warm(path):
    if not exe_ok(path):
        say(f"BROKEN exe (no version resource, truncated?) {path} - NOT started; "
            f"copy a good terminal64.exe of the same build over it")
        return "broken"
    for i in range(1, MAX_TRIES + 1):
        wait_for_updaters()
        rp = running_paths() or []
        n = sum(os.path.normcase(p) == os.path.normcase(path) for p in rp)
        if n > 1:
            say(f"  {n} copies of {path} already running")
        try:
            r = subprocess.run([PY, "-c", PROBE, path, str(INIT_TIMEOUT_S)],
                               capture_output=True, text=True,
                               timeout=INIT_TIMEOUT_S + 30,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            res = (r.stdout.strip().splitlines() or [r.stderr.strip()[-200:]])[-1]
        except subprocess.TimeoutExpired:
            res = "FAIL probe timed out"
        say(f"  try {i}/{MAX_TRIES} {path}: {res}")
        if res.startswith("OK"):
            return "ok"
        time.sleep(30)       # let a slow start / update settle before trying again
    return "failed"


def main():
    if "--check" in sys.argv:
        sys.exit(0 if ready_for_this_boot() else 1)
    t0 = time.time()
    say(f"warm-up start (boot {time.strftime('%Y-%m-%d %H:%M', time.localtime(boot_epoch()))})")
    results = {}
    for p in terminals():
        say(f"terminal {p}")
        results[p] = warm(p)
    bad = {p: r for p, r in results.items() if r != "ok"}
    with open(READY, "w", encoding="utf-8") as f:
        json.dump({"boot": boot_epoch(), "ts": time.time(), "results": results}, f, indent=1)
    say(f"warm-up done in {time.time() - t0:.0f}s: {len(results) - len(bad)} ok"
        + (f", NOT OK: {bad}" if bad else ""))


if __name__ == "__main__":
    main()
