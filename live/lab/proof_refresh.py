"""Hourly refresh of the numbers that actually move during the day
(owner 2026-09-29). NOT the whole lab: no replay, no MetaTrader, no AI.

It rereads the journals and the twin states, updates the real-trade side of
lab/proof.json, and lets the twin judge retire or flag a paper copy. The
replay itself is rebuilt once a night by lab/proof_build.py, because one hour
adds 60 minutes to a 42-day window, a tenth of a percent, and re-judging the
same data every hour only gives noise more chances to produce a false A.

    python lab/proof_refresh.py
"""
import io
import json
import os
import sys
import time

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
sys.path.insert(0, LAB)
sys.path.insert(0, LIVE)
OUT = os.path.join(LAB, "proof.json")


def night_alarm():
    """2026-10-03 (owner): if the 03:30 night did not run, say so by 06:00 -
    one push to Kino per day. The Labo's 36 h banner was the only sign, and
    a banner nobody opens is a silence."""
    import datetime as _dt
    now = _dt.datetime.now()
    if now.hour < 6:
        return
    today = now.strftime("%Y-%m-%d")
    log = os.path.join(LAB, "chercheur.log")
    mark = os.path.join(LAB, "night_alarm_seen")
    try:
        if io.open(mark, encoding="utf-8").read().strip() == today:
            return
    except Exception:
        pass
    ran = False
    try:
        for ln in io.open(log, encoding="utf-8").read().splitlines()[-40:]:
            if ln.startswith(today) and "run end" in ln:
                ran = True
                break
    except Exception:
        pass
    if ran:
        return
    try:
        import twin_judge as TJ
        TJ.emit("night_missing",
                ("\u26a0\ufe0f Le labo : la nuit n\u2019a pas tourn\u00e9",
                 f"Il est {now.strftime('%H:%M')} et la s\u00e9ance de nuit du {today} n\u2019a pas fini. Les v\u00e9rifications, le critique et le constructeur n\u2019ont rien fait cette nuit. \u00c0 regarder : lab/chercheur.log."),
                ("\u26a0\ufe0f The lab: the night did not run",
                 f"It is {now.strftime('%H:%M')} and the night session of {today} has not finished. Checks, critic and builder did nothing tonight. Look at lab/chercheur.log."),
                members=False)
        io.open(mark, "w", encoding="utf-8").write(today)
    except Exception as e:
        print("night alarm:", e)


def main():
    try:
        p = json.load(io.open(OUT, encoding="utf-8"))
    except Exception:
        print("no proof.json yet - the nightly build has to run first")
        return
    import harness as H
    import proof_build as PB

    before = dict((p.get("union") or {}))
    src = PB.sources()
    since = src.get("since")
    T = H.real_entries()
    if T:
        pn = [{"pnl": x["pnl"]} for x in T]
        union = {"trades": len(T), "net": round(sum(x["pnl"] for x in T), 2),
                 "wr": PB._wr(pn), "since": time.strftime("%Y-%m-%d", time.gmtime(T[0]["t"])),
                 # the replay of the same entries needs the price history, so it
                 # is left as the nightly build computed it and marked as such
                 "replay_same_entries": (p.get("union") or {}).get("replay_same_entries"),
                 "clean": PB.clean_union(T)}
        p["union"] = union
    src["rule_change"] = PB.rule_change(T)
    # the replay itself needs price history, so the hourly pass reuses
    # the nightly one - but the drag row is still re-dated and kept
    src["drag"] = (PB.drag((p.get("union") or {}).get("replay_same_entries"),
                           os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "drag_history.json"))
                   or (p.get("sources") or {}).get("drag"))
    p["sources"] = src
    # what the replay expected over the same days, from the stored daily curve
    cv = ((p.get("base") or {}).get("full") or {}).get("curve") or []
    if since and cv:
        start = next((v for d, v in cv if d >= since), None)
        if start is not None:
            p["expected"] = {"since": since, "net": round(cv[-1][1] - start, 2),
                             "lot": H.CFG_BASE["lot"],
                             "days": max(1, (time.time() - time.mktime(time.strptime(since, "%Y-%m-%d"))) // 86400)}
    p["refreshed"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    tmp = OUT + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(p, ensure_ascii=False))
    os.replace(tmp, OUT)
    try:
        import twin_judge as TJ
        TJ.judge()
    except Exception as e:
        print("twin judge:", e)
    night_alarm()
    u = p.get("union") or {}
    print(f"refreshed: {u.get('trades', 0)} real trades {u.get('net', 0):+.2f} "
          f"(was {before.get('trades', 0)} {before.get('net', 0):+.2f}), "
          f"{src.get('real_accounts', 0)} real accounts")


if __name__ == "__main__":
    main()
