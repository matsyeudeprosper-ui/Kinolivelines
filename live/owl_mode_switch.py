"""owl_mode_switch.py - swaps 441 between the auto bot and the manual desk.

Owner 2026-09-23: "make sure [the trade tool] is available whenever an
account turns manual trading. However when in auto trading that same
trade tool on the chart must be gone."

Before today, the trade tool's visibility (manual_ok(), MANUAL_MODES) and
the actual EXECUTION of a hand-placed order were both owl_manual_trader.py
(the desk) - the one process that ever supported it, on the one account
(441) that has ever run it. This morning's uniformity switch moved 441
onto structure_bos_bot.py, which has no manual-order code at all. So just
flipping the account's "mode" field would show the tool while nothing on
the other end executes what the owner draws on the chart - the exact
half-fix the owner caught.

This watcher does the real swap: stop whichever process is running for
the account, wait for it to actually exit, flip the nest record, start
the process the new mode calls for. ONE at a time, always - two processes
placing independent trades on the same account is the failure this
guards against.

Watches owl_mode_switch_request.json (written by the app's /<uid>/mode
POST) for a wanted mode that differs from the last one this watcher
handled. Writes owl_mode_switch_status.json so the app - and the owner -
can see the outcome of the last swap.

Only "bos" (441) is wired up. It is the only account that has ever
supported manual trading; the other four are pure-auto by design and
have no desk equivalent to swap to.
"""
import json
import os
import subprocess
import time

DIR = r"C:\Projects\KinoliveLines\live"
USERS = os.path.join(DIR, "owl_nest_users.json")
REQ = os.path.join(DIR, "owl_mode_switch_request.json")
STATUS = os.path.join(DIR, "owl_mode_switch_status.json")
LOG = os.path.join(DIR, "owl_mode_switch.log")
PY = (r"C:\Users\Administrator\AppData\Local\Programs\Python\Python311"
      r"\pythonw.exe")

ACCOUNTS = {
    "bos": {
        # -match (regex), NOT -like: proven live 2026-09-23 that Windows
        # records this command line with a TRAILING SPACE
        # ("structure_bos_bot.py "), which silently failed to match
        # '*structure_bos_bot.py' (no trailing wildcard) - so a swap
        # detected the desk fine (its pattern already had a trailing *)
        # but never saw the bot as running, skipped stopping it, and left
        # TWO live processes on the same real account for several
        # minutes before this was caught. \s*$ tolerates the trailing
        # space either way. End-anchored so this never matches
        # "structure_bos_bot.py valere/kino/demo/infinity".
        "bot_match": r"structure_bos_bot\.py\s*$",
        "desk_match": r"owl_manual_trader\.py bos\s*$",
        "bot_args": "structure_bos_bot.py",
        "desk_args": "owl_manual_trader.py bos",
    },
}


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")


def ps(cmd, timeout=30):
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip(), r.stderr.strip()


def stop_matching(pattern):
    ps("Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
       f"Where-Object {{ $_.CommandLine -match '{pattern}' }} | "
       "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
       "-Confirm:$false }")


def is_running(pattern):
    out, _ = ps(
        "(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
        f"Where-Object {{ $_.CommandLine -match '{pattern}' }} | "
        "Measure-Object).Count")
    return out.strip() not in ("", "0")


def start(args):
    ps(f'Start-Process -FilePath "{PY}" -ArgumentList "{args}" '
      f'-WorkingDirectory "{DIR}" -WindowStyle Hidden')


def load(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def save_atomic(p, obj):
    tmp = p + ".tmp"
    json.dump(obj, open(tmp, "w", encoding="utf-8"), indent=1)
    for _ in range(5):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.3)


def positions_open():
    """The bot and the desk use DIFFERENT magic numbers (909101 vs 909102),
    so swapping which one is running while a position is open would leave
    it unmanaged by whichever process starts next - it could not see the
    other's position and might open a second one alongside it. Checked via
    a short-lived subprocess so this watcher never holds its own MT5
    session. Returns None if the check itself could not be completed
    (treated as "cannot confirm flat" - the caller aborts either way)."""
    r = subprocess.run(
        [PY.replace("pythonw.exe", "python.exe"), "-c",
         "import sys; sys.argv=['x']; sys.path.insert(0,'.'); "
         "import structure_bos_bot as B; import MetaTrader5 as mt5; "
         "ok=mt5.initialize(path=B.TERMINAL, login=B.LOGIN, "
         "password=B.PASSWORD, server=B.SERVER, timeout=30000); "
         "print(len(mt5.positions_get() or []) if ok else -1); "
         "mt5.shutdown() if ok else None"],
        cwd=DIR, capture_output=True, text=True, timeout=45)
    try:
        return int(r.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def handle(uid, want):
    cfg = ACCOUNTS[uid]
    say(f"request: {uid} -> {want}")
    n = positions_open()
    if n is None or n > 0:
        say(f"REFUSED: {uid} has {n} open position(s) or the check failed "
            "- a swap now could leave one unmanaged")
        save_atomic(STATUS, {"uid": uid, "mode": want, "t": time.time(),
                             "ok": False,
                             "err": "position ouverte - bascule refusee, "
                                    "reessayer une fois le compte plat"})
        return
    for like in (cfg["bot_match"], cfg["desk_match"]):
        if is_running(like):
            stop_matching(like)
    stopped_ok = True
    for _ in range(15):
        if not is_running(cfg["bot_match"]) and not is_running(cfg["desk_match"]):
            break
        time.sleep(1)
    else:
        stopped_ok = False
        say(f"WARNING: a process for {uid} would not stop")

    us = load(USERS, [])
    for u in us:
        if u.get("id") == uid:
            u["mode"] = want
            u["dedicated"] = (cfg["desk_args"] if want == "semi"
                              else cfg["bot_args"])
    save_atomic(USERS, us)

    time.sleep(1)
    start(cfg["desk_args"] if want == "semi" else cfg["bot_args"])
    time.sleep(4)
    live = is_running(cfg["desk_match"] if want == "semi" else cfg["bot_match"])
    save_atomic(STATUS, {"uid": uid, "mode": want, "t": time.time(),
                         "ok": bool(stopped_ok and live),
                         "running": live})
    say(f"done: {uid} now {want}, running={live}, ok={stopped_ok and live}")


def main():
    say("mode-switch watcher starting")
    last_t = 0.0
    while True:
        try:
            req = load(REQ)
            if req and req.get("t", 0) > last_t and req.get("uid") in ACCOUNTS \
                    and req.get("want") in ("semi", "auto"):
                last_t = req["t"]
                handle(req["uid"], req["want"])
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(4)


if __name__ == "__main__":
    main()
