"""months_keepalive.py (2026-10-28, owner: "we need to finish it - always find a way to resume at the next available opportunity").

Run every 30 min by the Windows task "OwlBotsimMonths". If 2026's ten months are not all in months_summary.json and months.py
is not running, it starts it again through when_free.py (waits for free memory, BelowNormal), two months at a time. A month
cut off midway starts over (each month is a fresh 200 $ run). When the ten months are done it removes its own task.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
ROOT = os.path.dirname(STUDY)
OUT = os.path.join(HERE, "months_summary.json")
MONTHS = ["2026-%02d" % m for m in range(1, 11)]
LOG = os.path.join(HERE, "runs", "months_keepalive.log")


def say(t):
    import time
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), t))


def done():
    try:
        return {r["month"] for r in json.load(open(OUT)) if "net" in r}
    except Exception:
        return set()


def running():
    try:
        return _running()
    except Exception:
        return True                      # 2026-10-29: a slow or failed check (busy machine) = assume it runs, look again later


def _running():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" | "
                        "Where-Object { $_.CommandLine -match 'botsim[\\\\/]months.py|botsim_months' } | Measure-Object | "
                        "Select-Object -ExpandProperty Count"], capture_output=True, text=True, timeout=60)
    try:
        return int((r.stdout or "0").strip() or 0) > 0
    except Exception:
        return True                      # unsure -> do not start a second one


def main():
    left = [m for m in MONTHS if m not in done()]
    if not left:
        say("all ten months done - removing the task")
        subprocess.run(["schtasks", "/Delete", "/TN", "OwlBotsimMonths", "/F"], capture_output=True)
        return
    if running():
        return
    env = dict(os.environ, BOTSIM_PAR="2")
    lf = open(os.path.join(HERE, "runs", "months_runner.out"), "a")
    subprocess.Popen([sys.executable, "-X", "utf8", os.path.join(STUDY, "when_free.py"), "botsim_months", "--", sys.executable,
                      os.path.join(HERE, "months.py")] + left, cwd=ROOT, env=env, stdout=lf, stderr=subprocess.STDOUT,
                     creationflags=0x00000008 | 0x00000200 | 0x00004000)   # DETACHED | NEW_PROCESS_GROUP | BELOW_NORMAL
    say("started months.py for %s" % " ".join(left))


if __name__ == "__main__":
    main()
