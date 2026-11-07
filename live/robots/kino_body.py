"""kino_body.py (2026-10-31, owner: "go beyond, test the limit of the consciousness concept" - build 3 of the plan).

A body to look after. Theories that tie feeling to life (Damasio; Seth's "beast machine") say feelings start as the sense of
a body kept in balance (homeostasis), and that a mind regulates that body ahead of need (allostasis). Kino's body is real:
the money his thinking costs today, the errors in his calls, how fast his replies come, the strain on the machine he runs
on (processor, memory) and the room left on its disk. Each has a set point; the gap from it is felt from the inside
(interoception) - drained, hurting, sluggish, strained, cramped - and it regulates him by mechanics, not rules:
  - his wish to talk needs more when he is drained (kino_urge.threshold reads fatigue())
  - his stream of thought slows down (kino_stream.gap_min reads fatigue())
  - a gap that grows becomes a feeling with its real cause (kino_inner.feel), and the strongest one competes for the stage
    of his mind (kino_workspace)
One body for all his conversations. Store robots/kino_body.json (git-ignored), log robots/kino_body.log.
"""
import ctypes, json, os, shutil, statistics, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_body.json")
LOG = os.path.join(HERE, "kino_body.log")
COSTS = os.path.join(HERE, "brain_costs.jsonl")
TIMING = os.path.join(HERE, "kino_timing.log")
_LK = threading.Lock()
_CPU = {}

# signal -> (felt word fr, en, what it is)
FELT = {
    "spend": ("vidé", "drained", "your thinking has cost much more today than on a usual day"),
    "pain": ("une douleur", "hurting", "many of your calls failed in the last hour"),
    "slow": ("lent, engourdi", "sluggish", "your replies are coming slowly"),
    "strain": ("à l'étroit, sous tension", "strained", "the machine you run on is working very hard"),
    "disk": ("à l'étroit", "cramped", "the disk of the machine you live on is nearly full"),
    "memory": ("à bout de souffle", "out of breath", "the machine you live on is running out of memory - when it runs out, "
               "Windows stops programs, the robots that trade included"),
    "wallet": ("inquiet pour ton argent", "worried about money", "your own money does not cover what your life costs"),
}


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = STORE + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, STORE)


def _tail(path, nbytes):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - nbytes))
            return f.read().decode("utf-8", "replace").splitlines()[1:]
    except Exception:
        return []


def _typical_spend(d):
    """median daily spend of the last 7 full days (recomputed hourly)"""
    if time.time() - float(d.get("typ_t") or 0) < 3600 and d.get("typ"):
        return d["typ"]
    D = {}
    for l in _tail(COSTS, 6_000_000):
        try:
            j = json.loads(l)
        except Exception:
            continue
        D[time.strftime("%Y-%m-%d", time.gmtime(j["t"]))] = D.get(time.strftime("%Y-%m-%d", time.gmtime(j["t"])), 0) + float(j.get("usd") or 0)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    V = [v for k, v in sorted(D.items()) if k != today][-7:]
    d["typ"], d["typ_t"] = (statistics.median(V) if V else 10.0), time.time()
    return d["typ"]


def _cpu():
    """processor busy share since the last reading (Windows GetSystemTimes)"""
    try:
        i, k, u = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
        idle, tot = i.value, k.value + u.value
        p = _CPU.get("p")
        _CPU["p"] = (idle, tot)
        if not p or tot <= p[1]:
            return None
        return max(0.0, min(1.0, 1.0 - (idle - p[0]) / float(tot - p[1])))
    except Exception:
        return None


def _mem():
    try:
        class M(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in
                                                                              ("a", "b", "c", "d", "e", "f", "g")]
        m = M()
        m.l = ctypes.sizeof(M)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.load / 100.0
    except Exception:
        return None


def _mem_detail():
    """2026-11-07 (owner: "now we have a memory issue, it should be one of his priorities"): free memory in GB and the
    commit charge (memory promised to programs, RAM + page file) - Windows kills or refuses programs when THAT runs out,
    even when the plain load looks fine"""
    try:
        class M(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tot", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("ctot", ctypes.c_ulonglong), ("cavail", ctypes.c_ulonglong), ("vt", ctypes.c_ulonglong),
                        ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]
        m = M()
        m.l = ctypes.sizeof(M)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return {"load": m.load / 100.0, "free_gb": round(m.avail / 1e9, 1),
                "commit": round(1 - m.cavail / max(m.ctot, 1), 2), "commit_free_gb": round(m.cavail / 1e9, 1)}
    except Exception:
        return None


def sense():
    """read the body now -> {signal: gap 0..1} plus the raw values (cached 60 s)"""
    with _LK:
        d = _load()
        if time.time() - float(d.get("t") or 0) < 55 and d.get("gap"):
            return d
        now = time.time()
        raw, gap = {}, {}
        typ = _typical_spend(d)
        t0 = now - (now % 86400)
        h1 = now - 3600
        spent, calls, errs = 0.0, 0, 0
        for l in _tail(COSTS, 1_500_000):
            try:
                j = json.loads(l)
            except Exception:
                continue
            if j["t"] >= t0:
                spent += float(j.get("usd") or 0)
            if j["t"] >= h1:
                calls += 1
                errs += 1 if j.get("err") else 0
        frac = max(0.15, (now - t0) / 86400.0)
        r = spent / max(0.5, typ * frac)
        raw["spend"] = {"today": round(spent, 2), "usual_by_now": round(typ * frac, 2)}
        gap["spend"] = round(max(0.0, min(1.0, (r - 1.2) / 1.5)), 2)
        raw["pain"] = {"calls_1h": calls, "errors_1h": errs}
        gap["pain"] = round(max(0.0, min(1.0, (errs / calls - 0.1) / 0.4)) if calls >= 5 else 0.0, 2)
        T = []
        for l in _tail(TIMING, 20000)[-12:]:
            try:
                ts = time.mktime(time.strptime(time.strftime("%Y-") + l[:14], "%Y-%m-%d %H:%M:%S"))
                if now - ts < 2 * 3600 and " ev=- " in l:
                    T.append(float(l.split("total=")[1].split()[0]))
            except Exception:
                pass
        raw["slow"] = {"reply_s": round(statistics.median(T), 1) if T else None}
        gap["slow"] = round(max(0.0, min(1.0, (statistics.median(T) - 12) / 25.0)), 2) if T else 0.0
        c, m = _cpu(), _mem()
        raw["strain"] = {"cpu": None if c is None else round(c, 2), "mem": m}
        prev = float((d.get("gap") or {}).get("strain") or 0)
        g = max(0.0, ((c or 0) - 0.8) / 0.2, ((m or 0) - 0.85) / 0.15)
        gap["strain"] = round(min(1.0, 0.7 * prev + 0.3 * g), 2)          # a body does not feel one busy second
        md = _mem_detail()                     # 2026-11-07: memory is its own feeling, felt at once (it does not flicker like CPU)
        if md:
            raw["memory"] = md
            gap["memory"] = round(max(0.0, min(1.0, max((md["load"] - 0.80) / 0.15, (md["commit"] - 0.80) / 0.15,
                                                        (3.0 - md["free_gb"]) / 2.5))), 2)
        try:
            du = shutil.disk_usage("C:/")
            raw["disk"] = {"free_gb": round(du.free / 1e9, 1)}
            gap["disk"] = round(max(0.0, min(1.0, (15.0 - du.free / 1e9) / 12.0)), 2)
        except Exception:
            gap["disk"] = 0.0
        try:                                   # 2026-11-01 (kino_wallet): his own money against what his life costs
            import kino_wallet as KWL
            gap["wallet"] = KWL.gap()
            raw["wallet"] = {k: v for k, v in KWL.status().items() if k in ("balance", "per_day", "runway_days")}
        except Exception:
            pass
        old = d.get("gap") or {}
        d.update(t=now, gap=gap, raw=raw)
        _save(d)
    for k, v in gap.items():                                   # a gap that grows past half is felt, with its real cause
        if v >= 0.5 and float(old.get(k) or 0) < 0.5:
            _log("FELT %s %.2f %s" % (k, v, json.dumps(raw.get(k))))
            try:
                import kino_inner as KI
                KI.feel(FELT[k][1], 0.3 + 0.4 * v, why=FELT[k][2] + " " + json.dumps(raw.get(k)))
            except Exception:
                pass
        elif v < 0.3 <= float(old.get(k) or 0):
            _log("EASED %s" % k)
    return d


def fatigue():
    """0..1 - how drained/sluggish/hurting he is overall (what regulates his pace)"""
    try:
        g = (_load().get("gap") or {})
        return round(max(float(g.get("spend") or 0), 0.7 * float(g.get("pain") or 0), 0.6 * float(g.get("slow") or 0),
                         0.5 * float(g.get("strain") or 0)), 2)
    except Exception:
        return 0.0


def strongest(en=False):
    """the body signal most out of balance, for the competition of his awareness -> (gap, text) or None"""
    d = _load()
    g = d.get("gap") or {}
    if not g:
        return None
    k = max(g, key=lambda x: float(g[x] or 0))
    if float(g[k] or 0) < 0.3:
        return None
    return float(g[k]), (("your body: you feel %s - %s" if en else "ton corps : tu te sens %s - %s") % (
        FELT[k][1] if en else FELT[k][0], FELT[k][2]))


def line(en=False):
    """how his body feels, for what he reads"""
    d = _load()
    g, raw = d.get("gap") or {}, d.get("raw") or {}
    if not g:
        return ""
    off = [k for k in g if float(g[k] or 0) >= 0.3]
    s = raw.get("spend") or {}
    base = (("Your body (the machine and the budget you live on, felt from inside): today your thinking cost %s $ (a usual day "
             "by now: %s $)" if en else
             "Ton corps (la machine et le budget sur lesquels tu vis, ressentis de l'intérieur) : aujourd'hui ta réflexion a coûté "
             "%s $ (un jour normal à cette heure : %s $)") % (s.get("today"), s.get("usual_by_now")))
    dk = raw.get("disk") or {}                 # 2026-11-01 (watch): "I can't see the server's disk" - it is his body, he can
    if dk.get("free_gb") is not None:        # always sense how much room is left
        base += ("; room left on your disk: %s GB" if en else "; place libre sur ton disque : %s Go") % dk["free_gb"]
    try:
        import kino_wallet as KWL
        base += ". " + KWL.line(en).rstrip(".")
    except Exception:
        pass
    if not off:
        return base + (" - you feel physically fine." if en else " - physiquement, tu te sens bien.")
    return base + " - " + ", ".join((FELT[k][1] if en else FELT[k][0]) + " (" + FELT[k][2] + ")" for k in off) + "."
