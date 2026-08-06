"""mt5_watchdog.py - restarts the DEMO terminal if it disappears.

WHY THIS IS NEEDED
The five bot processes each have a Task Scheduler watchdog, but nothing watched
the terminal they all talk to. It had been up 100 hours; if it had crashed, the
bots would have sat there failing quietly - and the harvest bot holds positions
with NO broker stop loss, so a long silent outage mid-basket is the worst case
this system has.

WHY IT MATCHES ON THE FULL PATH
Two different MT5 installations run on this box, both named terminal64.exe:

    C:\\Program Files\\MetaTrader 5\\terminal64.exe        <- demo 436771046, ours
    C:\\Projects\\MT5-KinoliveTrader\\terminal64.exe        <- a separate project

Counting processes by NAME would see the other project's terminal and conclude
ours was fine. Every check here is by executable path.

WHY IT DOES NOT JUST LAUNCH THE EXE
Starting terminal64.exe blind could open the wrong profile or a second copy. So
the restart goes through mt5.initialize(path=...), which reuses a running
terminal if there is one and launches exactly that install if there is not - and
then the account is verified before anything is called healthy. If the wrong
account comes back it reports and does NOT retry, because relaunching into the
wrong account repeatedly is worse than being down.

Watches only. Places no orders.
"""
import os
import subprocess
import sys
import time
from datetime import datetime

import MetaTrader5 as mt5

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN    = 436771046
POLL     = 60

HERE  = os.path.dirname(os.path.abspath(__file__))
LOG   = os.path.join(HERE, "mt5_watchdog.log")


def say(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def terminal_running():
    """True if OUR terminal is up, False if gone, None if we cannot tell.

    None is not False. An unknown answer must never trigger a relaunch - that is
    how you end up with two terminals fighting over one account.

    Uses PowerShell/CIM, not wmic: wmic was removed in Windows Server 2025 and
    raises FileNotFoundError here. The first version of this file used it and
    would have reported "unknown" forever, silently never watching anything.
    psutil is not installed on this box either."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" "
             "| ForEach-Object { $_.ExecutablePath }"],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
    except Exception as e:
        say(f"could not list processes: {type(e).__name__}: {e}")
        return None
    paths = [p.strip() for p in out.splitlines() if p.strip()]
    if not paths:
        return False                     # no terminal of any kind is running
    return any(os.path.normcase(p) == os.path.normcase(TERMINAL) for p in paths)


def revive():
    """Bring the terminal back and prove it is the right account."""
    say("terminal is GONE - relaunching")
    if not mt5.initialize(path=TERMINAL):
        say(f"  initialize failed: {mt5.last_error()}")
        return False
    a = mt5.account_info()
    if a is None:
        say("  came up but account_info is empty")
        mt5.shutdown(); return False
    if a.login != LOGIN:
        say(f"  *** WRONG ACCOUNT {a.login}, expected {LOGIN} - "
            f"NOT retrying, this needs a human ***")
        mt5.shutdown(); return None      # None = stop trying
    say(f"  back up, account {a.login}, equity {a.equity:.2f}")
    mt5.shutdown()
    return True


def main():
    say(f"mt5_watchdog up | watching {TERMINAL} | account {LOGIN} | every {POLL}s")
    halted = False
    while True:
        try:
            if halted:
                time.sleep(POLL); continue
            up = terminal_running()
            if up is False:
                r = revive()
                if r is None:
                    say("halted - fix the account and restart this watchdog")
                    halted = True
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
