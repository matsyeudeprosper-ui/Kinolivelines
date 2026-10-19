"""luck_queue.py (2026-10-18, owner: "is there a way it pauses and continues throughout days? what if the server dies
midway?") - runs the queued luck tests one at a time and restarts the unfinished one after a crash or a reboot.

A luck test is random_control_market.py --journal (up to 100 draws, the 6th random robot that does as well ends it,
each draw saved the moment it ends). This script only decides WHEN to start one: never while another luck test or
heavy job runs, and only with room on the VPS (live bots first). The OwlLuckQueue scheduled task runs it every
15 minutes, so a dead test is back within 15 minutes of the VPS being up again, from its last saved draw.

    python study/luck_queue.py                              start the next unfinished test if there is room
    python study/luck_queue.py add XAUUSD owl-sans-orage [--fresh] [--uid=u1] [--nm=name]
    python study/luck_queue.py list
--fresh = a NEW test (the robot or its market test changed): the old journal is dropped on its first start only.
Queue: study/luck/queue.json; progress: study/luck/<robot>_<SYM>.status.json; log: study/luck/<robot>_<SYM>.log
"""
import os, sys, json, time, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from when_free import free_gb, heavy_running

LDIR = os.path.join(HERE, "luck")
QF = os.path.join(LDIR, "queue.json")
NEED_GB = float(os.environ.get("LUCK_NEED_GB", "3.0"))   # ONE process (~1.3 GB); this VPS idles at 2.5-3.6 GB free, 4.5 never came (10-17)
FINAL = ("pass", "fail", "data_changed")


def load():
    try:
        return json.load(open(QF, encoding="utf-8"))
    except Exception:
        return []


def save(q):
    os.makedirs(LDIR, exist_ok=True)
    json.dump(q, open(QF + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(QF + ".tmp", QF)


def status(rid, sym):
    try:
        return json.load(open(os.path.join(LDIR, "%s_%s.status.json" % (rid, sym)), encoding="utf-8"))
    except Exception:
        return {}


def finished(e):
    """an entry is over when its test reached a verdict after the entry was queued"""
    s = status(e["rid"], e["sym"])
    return s.get("state") in FINAL and str(s.get("updated") or "") >= e["at"]


def add(sym, rid, fresh=False, uid=None, nm=None):
    q = load()
    for e in q:
        if e["rid"] == rid and e["sym"] == sym and not finished(e):
            return False                                     # already queued and not over
    q.append({"rid": rid, "sym": sym, "fresh": bool(fresh), "uid": uid, "nm": nm,
              "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    save(q[-60:])
    return True


def kick():
    q = load()
    todo = [e for e in q if not finished(e) and int(e.get("starts") or 0) < 30]     # 30 starts without a verdict = broken, skip it
    if not todo:
        return "nothing queued"
    busy = heavy_running()
    if busy:
        return "busy: " + "; ".join(busy)                    # a luck test (or another heavy job) is running
    f = free_gb()
    if f < NEED_GB:
        return "waiting for room: %.1f GB free" % f
    e = todo[0]
    cmd = [sys.executable, "-u", os.path.join(HERE, "random_control_market.py"), e["sym"], e["rid"], "--journal"]
    if e.get("fresh") and not e.get("launched"):
        cmd.append("--fresh")                                # only the first start of a new test drops the old journal
    if e.get("uid"):
        cmd.append("--uid=%s" % e["uid"])
    if e.get("nm"):
        cmd.append("--nm=%s" % e["nm"])
    log = open(os.path.join(LDIR, "%s_%s.log" % (e["rid"], e["sym"])), "a", encoding="utf-8")
    log.write("\n%s start (%.1f GB free): %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), f, " ".join(cmd[2:]))); log.flush()
    flags = 0x00000008 | 0x08000000 | 0x00000200            # detached, no window, own process group
    try:
        subprocess.Popen(cmd, cwd=HERE, stdout=log, stderr=subprocess.STDOUT, creationflags=flags | 0x01000000, close_fds=True)
    except OSError:                                          # the task's job does not allow breakaway
        subprocess.Popen(cmd, cwd=HERE, stdout=log, stderr=subprocess.STDOUT, creationflags=flags, close_fds=True)
    for x in q:
        if x is e:
            x["launched"] = x.get("launched") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            x["starts"] = int(x.get("starts") or 0) + 1
    save(q)
    return "started %s %s" % (e["rid"], e["sym"])


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["add"]:
        fl = {x.split("=", 1)[0]: (x.split("=", 1)[1] if "=" in x else True) for x in a if x.startswith("--")}
        pos = [x for x in a[1:] if not x.startswith("--")]
        print(add(pos[0].upper(), pos[1], fl.get("--fresh", False), fl.get("--uid"), fl.get("--nm")))
    elif a[:1] == ["list"]:
        for e in load():
            s = status(e["rid"], e["sym"])
            print(e["rid"], e["sym"], "done" if finished(e) else "open", s.get("state"), "%s/%s" % (s.get("n"), s.get("max")), "beats", s.get("beats"))
    else:
        os.makedirs(LDIR, exist_ok=True)
        r = kick()
        if r != "nothing queued":
            with open(os.path.join(LDIR, "queue.log"), "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + r + "\n")
        print(r)
