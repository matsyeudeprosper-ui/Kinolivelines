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
RESET_REQ = os.path.join(DIR, "owl_reset_request.json")
RESET_STATUS = os.path.join(DIR, "owl_reset_status.json")
LOG = os.path.join(DIR, "owl_mode_switch.log")
PY = (r"C:\Users\Administrator\AppData\Local\Programs\Python\Python311"
      r"\pythonw.exe")

# 2026-09-27 (owner): "make sure accounts in manual trading mode always have
# the trade tool in the chart" - the swap is generic now. Every nest account
# gets a desk (owl_manual_trader.py <uid>); the bot to stop/start is the one
# in BOT_ARGS, or nothing at all for an account that has no bot (Kino 778:
# "auto" simply means no process on it).
BOT_ARGS = {
    "bos": "structure_bos_bot.py",
    "kino": "structure_bos_bot.py kino",
    "demo": "structure_bos_bot.py demo",
    "infinity": "structure_bos_bot.py infinity",
    "u224016179": "structure_bos_bot.py valere",
}


def cfg_for(uid):
    """-match (regex), NOT -like: proven live 2026-09-23 that Windows records
    a command line with a TRAILING SPACE ("structure_bos_bot.py "), which
    silently failed a '*...py' -like. A trailing "backslash-s star dollar" tolerates it and end-anchors, so
    the bare bot never matches "structure_bos_bot.py valere/kino/demo"."""
    import re as _re
    bot = BOT_ARGS.get(uid)
    return {
        "bot_match": (_re.escape(bot) + r"\s*$") if bot else None,
        "desk_match": _re.escape(f"owl_manual_trader.py {uid}") + r"\s*$",
        "bot_args": bot,
        "desk_args": f"owl_manual_trader.py {uid}",
    }


def known_uids():
    return [u.get("id") for u in (load(USERS, []) or []) if u.get("id")]


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")


def ps(cmd, timeout=30):
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip(), r.stderr.strip()


def stop_matching_any(pattern):
    """python.exe AND pythonw.exe (the nest workers run under python.exe)."""
    ps("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and "
       f"$_.CommandLine -match '{pattern}' }} | "
       "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }")


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


def positions_open(uid="bos"):
    """The bot and the desk use DIFFERENT magic numbers (909101 vs 909102),
    so swapping which one is running while a position is open would leave
    it unmanaged by whichever process starts next - it could not see the
    other's position and might open a second one alongside it. Checked via
    a short-lived subprocess so this watcher never holds its own MT5
    session. Returns None if the check itself could not be completed
    (treated as "cannot confirm flat" - the caller aborts either way)."""
    # 2026-09-27: per account, from the nest record (a record without a
    # password attaches to its already-logged-in terminal, like the desk)
    code = (
        "import sys, json; sys.argv=['x']; import MetaTrader5 as mt5; "
        f"u=[x for x in json.load(open(r'{USERS}', encoding='utf-8')) if x.get('id')=='{uid}'][0]; "
        "login=int(u.get('mt5_login') or u['login']); "
        "ok=(mt5.initialize(path=u['terminal'], login=login, password=u['mt5_password'], "
        "server=u.get('mt5_server') or 'Exness-MT5Real30', timeout=30000) if u.get('mt5_password') "
        "else mt5.initialize(path=u['terminal'], timeout=30000)); "
        "ai=mt5.account_info() if ok else None; "
        "print(len(mt5.positions_get() or []) if (ai and int(ai.login)==login) else -1); "
        "mt5.shutdown() if ok else None")
    r = subprocess.run([PY.replace("pythonw.exe", "python.exe"), "-c", code],
                       cwd=DIR, capture_output=True, text=True, timeout=45)
    try:
        return int(r.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def handle(uid, want):
    cfg = cfg_for(uid)
    say(f"request: {uid} -> {want}")
    n = positions_open(uid)
    if n is None or n > 0:
        say(f"REFUSED: {uid} has {n} open position(s) or the check failed "
            "- a swap now could leave one unmanaged")
        save_atomic(STATUS, {"uid": uid, "mode": want, "t": time.time(),
                             "ok": False,
                             "err": "position ouverte - bascule refusee, "
                                    "reessayer une fois le compte plat"})
        return
    pats = [x for x in (cfg["bot_match"], cfg["desk_match"]) if x]
    for like in pats:
        if is_running(like):
            stop_matching(like)
    stopped_ok = True
    for _ in range(15):
        if not any(is_running(x) for x in pats):
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
    want_args = cfg["desk_args"] if want == "semi" else cfg["bot_args"]
    if want_args:
        start(want_args)
        time.sleep(4)
        live = is_running(cfg["desk_match"] if want == "semi" else cfg["bot_match"])
    else:
        # an account with no bot: "auto" means nothing runs on it
        live = True
    save_atomic(STATUS, {"uid": uid, "mode": want, "t": time.time(),
                         "ok": bool(stopped_ok and live),
                         "running": live})
    say(f"done: {uid} now {want}, running={live}, ok={stopped_ok and live}")


def state_file_for(bot_args):
    """structure_bos_bot.py [variant] -> its state file (see _SFX in the bot)."""
    parts = (bot_args or "").split()
    if not parts or parts[0] != "structure_bos_bot.py":
        return None
    v = parts[1] if len(parts) > 1 else ""
    sfx = {"": "", "sniper": "_sniper", "halfdebt": "_half"}.get(v, "_" + v if v else "")
    return f"bos_state{sfx}.json"


def handle_reset(uid):
    """2026-09-27 (owner): restart an account's robot from zero - the demo
    died at its kill line and the shop window must not stay dark. Stop the
    bot, archive its ledger/state (never delete), move the member's
    era_start to now (the app's history restarts too), start the bot."""
    cfg = cfg_for(uid)
    sf = state_file_for(cfg["bot_args"])
    say(f"reset request: {uid}")
    if not sf:
        save_atomic(RESET_STATUS, {"uid": uid, "t": time.time(), "ok": False,
                                   "err": "pas de robot a reinitialiser"})
        return
    n = positions_open(uid)
    if n is None or n > 0:
        save_atomic(RESET_STATUS, {"uid": uid, "t": time.time(), "ok": False,
                                   "err": "position ouverte - reinitialisation refusee"})
        return
    if is_running(cfg["bot_match"]):
        stop_matching(cfg["bot_match"])
    for _ in range(15):
        if not is_running(cfg["bot_match"]):
            break
        time.sleep(1)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    src = os.path.join(DIR, sf)
    if os.path.exists(src):
        os.replace(src, os.path.join(DIR, f"{sf}.{stamp}.bak"))
    # 2026-09-27 (owner): a clean start on the UI too - the journal (the
    # app's day stories / trade stories / CSV read it) is archived as well;
    # the bot writes a fresh header on its next trade.
    jf = "bos_journal" + sf[len("bos_state"):-len(".json")] + ".csv"
    jp = os.path.join(DIR, jf)
    if os.path.exists(jp):
        os.replace(jp, os.path.join(DIR, f"{jf}.{stamp}.bak"))
    us = load(USERS, [])
    for u in us:
        if u.get("id") == uid:
            u["era_start"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
            u["era_prev"] = (u.get("era_prev") or []) + [stamp]
    save_atomic(USERS, us)
    # the stats worker bakes era_start in at start - kill it, the manager
    # respawns it within 30 s with the new era (history restarts in the app)
    stop_matching_any(r"owl_nest_worker\.py\s+" + uid + r"\s*$")
    time.sleep(1)
    start(cfg["bot_args"])
    time.sleep(4)
    live = is_running(cfg["bot_match"])
    save_atomic(RESET_STATUS, {"uid": uid, "t": time.time(), "ok": bool(live),
                               "running": live, "archived": f"{sf}.{stamp}.bak"})
    say(f"reset done: {uid} running={live} archived {sf}.{stamp}.bak")


def main():
    say("mode-switch watcher starting")
    # 2026-09-27: start from the request already on disk - a fresh watcher
    # used to replay the last request (seen live today: a restart replayed
    # "bos -> auto" from four days earlier and bounced the live bot).
    last_t = float((load(REQ) or {}).get("t", 0) or 0)
    if last_t:
        say(f"ignoring the request already handled before this start (t={last_t:.0f})")
    last_r = float((load(RESET_REQ) or {}).get("t", 0) or 0)
    while True:
        try:
            rq = load(RESET_REQ)
            if rq and rq.get("t", 0) > last_r and rq.get("uid") in known_uids():
                last_r = rq["t"]
                handle_reset(rq["uid"])
            req = load(REQ)
            if req and req.get("t", 0) > last_t and req.get("uid") in known_uids() \
                    and req.get("want") in ("semi", "auto"):
                last_t = req["t"]
                handle(req["uid"], req["want"])
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(4)


if __name__ == "__main__":
    main()
