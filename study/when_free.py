"""when_free.py - run heavy study jobs one at a time, each only when the VPS has room (owner 2026-10-16:
"as soon as you have free memory, start whatever can run; schedule it at the right moment").

    python study/when_free.py <name> -- <cmd...> [-- <cmd...> ...]
Each command waits until free memory >= NEED_GB for STEADY consecutive minutes AND no other heavy job is running
(tick_pack, robot_runner, random_control, spread_whatif, proof_current_rules, market_pack), then runs; while it
runs, free memory is watched every 20 s: below PANIC_GB the job is killed, and retried later (3 tries). Log:
study/when_free_<name>.log; the Claude session reads it. Start it DETACHED (Start-Process) so an idle-memory reaper
of the chat's own background shells never takes it down.
"""
import os, sys, time, subprocess, ctypes

NEED_GB, STEADY, PANIC_GB, TRIES = float(os.environ.get("WHEN_FREE_NEED_GB", "4.5")), 2, 0.9, 3
HEAVY = ("tick_pack", "robot_runner", "random_control", "spread_whatif", "proof_current_rules", "market_pack", "valere_sync", "tick1s_pack")
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)


class _MS(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def free_gb():
    m = _MS(); m.dwLength = ctypes.sizeof(_MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 2**30


def heavy_running(ignore_pid=None):
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" | ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }"],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return ["(process list unavailable - assume busy)"]     # 2026-10-19: cannot tell = busy, never start a second job
    found = []
    for ln in out.splitlines():
        pid, _, cmd = ln.partition("|")
        if pid.strip() in (str(os.getpid()), str(ignore_pid or -1)):
            continue
        if any(h in (cmd or "") for h in HEAVY) and "when_free" not in (cmd or ""):
            found.append(cmd.strip()[-70:])
    return found


def main():
    name = sys.argv[1]
    cmds, cur = [], []
    for a in sys.argv[3:]:
        if a == "--":
            cmds.append(cur); cur = []
        else:
            cur.append(a)
    if cur:
        cmds.append(cur)
    log = open(os.path.join(HERE, "when_free_%s.log" % name), "a", encoding="utf-8")

    def say(m):
        log.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n"); log.flush()

    say("plan: %d job(s): %s" % (len(cmds), " || ".join(" ".join(c) for c in cmds)))
    for cmd in cmds:
        for attempt in range(1, TRIES + 1):
            steady = 0
            while steady < STEADY:
                f = free_gb(); h = heavy_running()
                if f >= NEED_GB and not h:
                    steady += 1
                else:
                    steady = 0
                    say("waiting: %.1f GB free%s" % (f, (", busy: " + "; ".join(h)) if h else "")) if int(time.time()) % 600 < 60 else None
                time.sleep(60)
            say("start (try %d, %.1f GB free): %s" % (attempt, free_gb(), " ".join(cmd)))
            t0 = time.time()
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=0x08000000 | 0x00004000)   # below-normal priority
            killed = False
            while p.poll() is None:
                time.sleep(20)
                f = free_gb()
                if f < PANIC_GB:
                    say("PANIC %.2f GB free - killing the job" % f); p.kill(); killed = True; break
            say("%s after %.0f s (exit %s)" % ("killed" if killed else "done", time.time() - t0, p.returncode))
            if not killed:
                break
            time.sleep(600)
    say("all done")


if __name__ == "__main__":
    main()
