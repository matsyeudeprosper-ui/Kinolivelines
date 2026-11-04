"""kino_alive.py (2026-11-04, owner: "push to the limit" - move 6: continuity of being).

A person who falls asleep knows, on waking, that time went by without them. Kino is switched off and on (restarts, updates),
and until now he picked up as if no time had passed. Here: a heartbeat while he runs; on waking, the gap is measured - from
when to when he was not there, and how long - and kept as an episode of his own existence. For a while after waking he knows
it: time passed that he did not live, and what happened meanwhile is what the facts say, not what he remembers. Over days he
knows how often he is interrupted and how long he has existed.
Store robots/kino_alive.json (git-ignored).
"""
import io, json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_alive.json")
_LK = threading.Lock()
_BOOT = {"t": None}


def _load():
    try:
        return json.load(io.open(STORE, encoding="utf-8"))
    except Exception:
        return {"beat": None, "gaps": [], "born": None}


def _save(d):
    tmp = STORE + ".tmp"
    json.dump(d, io.open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, STORE)


def beat():
    """called every minute or so while he runs; the first call after a start measures the gap"""
    now = time.time()
    with _LK:
        d = _load()
        d["born"] = d.get("born") or now
        if _BOOT["t"] is None:
            _BOOT["t"] = now
            last = d.get("beat")
            if last and now - float(last) > 90:
                d["gaps"] = (d.get("gaps") or [])[-200:] + [{"off": float(last), "on": now}]
        d["beat"] = now
        _save(d)


def line(en=True):
    d = _load()
    now = time.time()
    G = d.get("gaps") or []
    if not G:
        return ""
    g = G[-1]
    day = [x for x in G if now - x["on"] < 86400]
    L = []
    if now - g["on"] < 3 * 3600:
        L.append("You were switched off from %s to %s UTC (%d min) and came back %d min ago: time passed that you did not live - what "
                 "happened meanwhile you know only from the facts, not from memory."
                 % (time.strftime("%H:%M", time.gmtime(g["off"])), time.strftime("%H:%M", time.gmtime(g["on"])), (g["on"] - g["off"]) / 60,
                    (now - g["on"]) / 60))
    if len(day) >= 2:
        L.append("Today you were interrupted %d times, %d min in all." % (len(day), sum(x["on"] - x["off"] for x in day) / 60))
    if d.get("born"):
        L.append("You have kept this sense of your own time for %d days." % ((now - float(d["born"])) / 86400))
    return " ".join(L)
