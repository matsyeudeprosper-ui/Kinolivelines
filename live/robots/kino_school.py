"""kino_school.py (2026-11-02, owner: "users who know nothing about trading but would like to learn... something never done
before, with Kino: tools, workshops, continuous learning, levels - experts and beginners, no clutter").

L'école de Kino - you learn to trade by building your own robot, and every step is measured against chance.

  1 Lire      read real candles (past Bitcoin, minute by minute)              5 right answers -> level 2
  2 Voir      read the structure: the trend, the next break                  7 of the last 10 right -> level 3
  3 Décider   the dojo: a real past session replayed, buy / sell / wait,     15 sessions -> level 4
              scored in R against Kino and against a robot that picks at random
  4 Ton robot Kino finds the habit hidden in your dojo decisions and builds it  a robot made after the habit -> 5
  5 Prouver   that robot on 10 months of real prices, then the luck test     luck test passed -> 6
  6 En vrai   your robot, small, on a real account

Plus, at every level: "le moment du jour" (one question on the LIVE market, a streak), the weekly workshop with Kino, and a
certificate earned by proof (your dojo decisions beat chance), never by attendance.

Data: past prices = study/ticks_archive_BTCUSD/bars_YYYY-MM.npz (Exness M1, Dec 2025 -> Sep 2026); the live moment =
live/owl_chart_btc.json. State: robots/kino_school.json (one record per person). No AI call here - Kino talks in the chat.
"""
import glob, json, math, os, random, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
ARCH = os.path.join(os.path.dirname(LIVE), "study", "ticks_archive_BTCUSD")
STORE = os.path.join(HERE, "kino_school.json")
FEED = os.path.join(LIVE, "owl_chart_btc.json")
_LOCK = threading.Lock()
_BARS = {}

LEVELS = [("lire", "Lire", "Read"), ("voir", "Voir", "See"), ("decider", "Décider", "Decide"),
          ("robot", "Ton robot", "Your robot"), ("prouver", "Prouver", "Prove"), ("vrai", "En vrai", "For real")]
L1_NEED, L2_WIN, L2_NEED, DOJO_NEED = 5, 10, 7, 15
DEC_N, DEC_GAP, HIST, ATR_N, COST_R = 6, 6, 48, 14, 0.05


# ------------------------------------------------------------------ store
def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = STORE + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, STORE)


def _me(d, pid):
    return d.setdefault(pid, {"track": None, "reads": [], "moments": {}, "dojo": [], "cur": None, "habit": None,
                              "cert": None, "created": int(time.time())})


# ------------------------------------------------------------------ prices
def _months():
    return sorted(glob.glob(os.path.join(ARCH, "bars_*.npz")))


def _bars(path):
    if path not in _BARS:
        import numpy as np
        R = np.load(path)["R"]
        _BARS[path] = [(int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])) for r in R]
    return _BARS[path]


def _window(n_m1, rnd):
    """n_m1 consecutive minutes (no gap over 3 min) from a random past month"""
    M = _months()
    for _ in range(60):
        p = rnd.choice(M)
        B = _bars(p)
        if len(B) < n_m1 + 10:
            continue
        i = rnd.randrange(0, len(B) - n_m1)
        w = B[i:i + n_m1]
        if all(w[k + 1][0] - w[k][0] <= 180 for k in range(len(w) - 1)):
            return os.path.basename(p), i, w
    raise RuntimeError("no clean window")


def _m5(w):
    out = []
    for k in range(0, len(w) - 4, 5):
        g = w[k:k + 5]
        out.append([g[0][0], g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4]])
    return out


def _ema(vals, n):
    a, e, out = 2.0 / (n + 1), None, []
    for v in vals:
        e = v if e is None else e + a * (v - e)
        out.append(e)
    return out


def _atr(c, n=ATR_N):
    tr = [c[0][2] - c[0][3]] + [max(c[i][2], c[i - 1][4]) - min(c[i][3], c[i - 1][4]) for i in range(1, len(c))]
    return sum(tr[-n:]) / max(1, len(tr[-n:]))


def _swings(c):
    """swing highs / lows: a candle higher (lower) than the 2 on each side"""
    H, L = [], []
    for i in range(2, len(c) - 2):
        if c[i][2] >= max(c[j][2] for j in (i - 2, i - 1, i + 1, i + 2)):
            H.append((i, c[i][2]))
        if c[i][3] <= min(c[j][3] for j in (i - 2, i - 1, i + 1, i + 2)):
            L.append((i, c[i][3]))
    return H, L


def _trend(c):
    H, L = _swings(c)
    if len(H) < 2 or len(L) < 2:
        return 0, H, L
    hh, hl = H[-1][1] > H[-2][1], L[-1][1] > L[-2][1]
    return (1 if hh and hl else -1 if (not hh and not hl) else 0), H, L


def _fmt(c):
    return [[int(x[0]), round(x[1], 2), round(x[2], 2), round(x[3], 2), round(x[4], 2)] for x in c]


# ------------------------------------------------------------------ level 1-2 questions (past prices)
def new_read(pid, level, en=False):
    """a reading exercise on a real past window - level 1: the candles, level 2: the structure"""
    T = (lambda f, e: e if en else f)
    rnd = random.Random()
    for _ in range(40):
        _, _, w = _window(5 * 52, rnd)
        c = _m5(w)
        if level <= 1:
            kind = rnd.choice(["dir", "wick", "big"])
            last = c[-1]
            body, rng = abs(last[4] - last[1]), max(1e-9, last[2] - last[3])
            if kind == "dir":
                if body < 0.2 * rng:
                    continue
                ans = "up" if last[4] > last[1] else "down"
                q = {"q": T("La dernière bougie (à droite) : pendant ces 5 minutes, le prix a…", "The last candle (right): over these 5 minutes, price…"),
                     "opts": [["up", T("monté", "went up")], ["down", T("baissé", "went down")]], "ans": ans,
                     "why": T("Une bougie verte ferme plus haut qu'elle n'a ouvert, une rouge plus bas.", "A green candle closes higher than it opened, a red one lower.")}
            elif kind == "wick":
                up = last[2] - max(last[1], last[4])
                dn = min(last[1], last[4]) - last[3]
                if max(up, dn) < 0.5 * rng:
                    continue
                ans = "sellers" if up > dn else "buyers"
                q = {"q": T("La dernière bougie a une longue mèche " + ("en haut" if up > dn else "en bas") + ". Ça montre que…",
                            "The last candle has a long wick at the " + ("top" if up > dn else "bottom") + ". It shows that…"),
                     "opts": [["sellers", T("les vendeurs ont repoussé le prix vers le bas", "sellers pushed the price back down")],
                              ["buyers", T("les acheteurs ont repoussé le prix vers le haut", "buyers pushed the price back up")]], "ans": ans,
                     "why": T("Une mèche, c'est un prix touché puis refusé : en haut les vendeurs ont gagné, en bas les acheteurs.",
                              "A wick is a price reached then refused: at the top sellers won, at the bottom buyers did.")}
            else:
                last6 = c[-6:]
                rngs = [x[2] - x[3] for x in last6]
                i = max(range(6), key=lambda k: rngs[k])
                if sorted(rngs)[-1] < 1.4 * sorted(rngs)[-2]:
                    continue
                q = {"q": T("Parmi les 6 dernières bougies, laquelle a le plus bougé ? (1 = la plus ancienne)",
                            "Among the last 6 candles, which one moved the most? (1 = the oldest)"),
                     "opts": [[str(k + 1), str(k + 1)] for k in range(6)], "ans": str(i + 1),
                     "why": T("La taille d'une bougie, du haut de la mèche au bas, c'est l'agitation du marché à ce moment.",
                              "A candle's size, top of the wick to the bottom, is how agitated the market was then.")}
            q.update(level=1, kind=kind, candles=_fmt(c))
            return q
        tr, H, L = _trend(c)
        kind = rnd.choice(["trend", "trend", "next"])
        if kind == "trend":
            if tr == 0 and rnd.random() < 0.6:
                continue
            ans = {1: "up", -1: "down", 0: "range"}[tr]
            q = {"q": T("Regarde les sommets et les creux. La tendance de fond est…", "Look at the highs and lows. The background trend is…"),
                 "opts": [["up", T("à la hausse", "up")], ["down", T("à la baisse", "down")], ["range", T("sans direction claire", "no clear direction")]],
                 "ans": ans, "marks": {"H": [[c[i][0], v] for i, v in H[-3:]], "L": [[c[i][0], v] for i, v in L[-3:]]},
                 "why": T("En hausse : chaque sommet et chaque creux est plus haut que le précédent. En baisse : plus bas. Sinon : pas de direction.",
                          "Up: each high and each low is higher than the one before. Down: lower. Otherwise: no direction.")}
        else:
            if tr == 0 or len(H) < 1 or len(L) < 1:
                continue
            lvl = H[-1][1] if tr == 1 else L[-1][1]
            other = L[-1][1] if tr == 1 else H[-1][1]
            mid = (lvl + other) / 2
            o = [["a", "%.0f" % lvl], ["b", "%.0f" % other], ["c", "%.0f" % mid]]
            rnd.shuffle(o)
            q = {"q": T("La tendance est " + ("à la hausse" if tr == 1 else "à la baisse") + ". Quel niveau, s'il casse, la confirmerait ?",
                        "The trend is " + ("up" if tr == 1 else "down") + ". Which level, if broken, would confirm it?"),
                 "opts": o, "ans": "a",
                 "why": T("Une tendance se confirme quand le prix dépasse son dernier " + ("sommet" if tr == 1 else "creux") + " : c'est une cassure (un BOS).",
                          "A trend is confirmed when price goes past its last " + ("high" if tr == 1 else "low") + ": a break (a BOS).")}
        q.update(level=2, kind=kind, candles=_fmt(c))
        return q
    raise RuntimeError("no question")


def answer_read(pid, q, choice):
    ok = str(choice) == str(q.get("ans"))
    with _LOCK:
        d = _load()
        me = _me(d, pid)
        me["reads"] = (me.get("reads") or []) + [{"t": int(time.time()), "lv": int(q.get("level") or 1), "ok": ok}]
        me["reads"] = me["reads"][-400:]
        _save(d)
    return ok


# ------------------------------------------------------------------ le moment du jour (the LIVE market)
def moment(pid, en=False):
    T = (lambda f, e: e if en else f)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    d = _load()
    me = _me(d, pid)
    done = (me.get("moments") or {}).get(today)
    try:
        j = json.load(open(FEED, encoding="utf-8"))
    except Exception:
        return {"ok": False}
    c = j.get("candles") or []
    px = c[-1][4] if c else None
    tr, nb, inv = j.get("trend") or 0, j.get("next_bos"), j.get("invalid")
    kind = ["trend", "bos", "choch"][int(time.strftime("%j", time.gmtime())) % 3]
    if kind != "trend" and (nb is None or inv is None or not tr):
        kind = "trend"
    if kind == "trend":
        q = {"q": T("Bitcoin, maintenant. D'après sa structure, la tendance est…", "Bitcoin, right now. From its structure, the trend is…"),
             "opts": [["up", T("à la hausse", "up")], ["down", T("à la baisse", "down")], ["range", T("pas claire", "unclear")]],
             "ans": {1: "up", -1: "down"}.get(tr, "range"),
             "why": T("La structure compte les sommets et les creux, pas une seule bougie.", "Structure counts highs and lows, not a single candle.")}
    elif kind == "bos":
        q = {"q": T("Si Bitcoin passe %s, ce serait…" % ("au-dessus de %.0f" % nb if tr == 1 else "sous %.0f" % nb),
                    "If Bitcoin goes %s, it would be…" % ("above %.0f" % nb if tr == 1 else "below %.0f" % nb)),
             "opts": [["cont", T("une continuation de la tendance (BOS)", "a continuation of the trend (BOS)")],
                      ["rev", T("un retournement (CHoCH)", "a reversal (CHoCH)")]], "ans": "cont",
             "why": T("Dépasser le dernier sommet d'une hausse (ou creux d'une baisse) la prolonge : c'est un BOS.",
                      "Going past the last high of an uptrend (or low of a downtrend) extends it: a BOS.")}
    else:
        q = {"q": T("Et si Bitcoin passait %s ?" % ("sous %.0f" % inv if tr == 1 else "au-dessus de %.0f" % inv),
                    "And if Bitcoin went %s?" % ("below %.0f" % inv if tr == 1 else "above %.0f" % inv)),
             "opts": [["cont", T("la tendance continue", "the trend goes on")], ["rev", T("la tendance change de sens (CHoCH)", "the trend changes direction (CHoCH)")]],
             "ans": "rev",
             "why": T("Le point protégé est le dernier creux (ou sommet) qui a lancé la tendance : le casser la retourne.",
                      "The protected point is the last low (or high) that started the trend: breaking it turns the trend.")}
    q.update(kind=kind, px=px, candles=[[int(x[0]), x[1], x[2], x[3], x[4]] for x in c[-60:]], done=done, day=today,
             streak=streak(me))
    return q


def answer_moment(pid, ok):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with _LOCK:
        d = _load()
        me = _me(d, pid)
        if today not in (me.get("moments") or {}):
            me.setdefault("moments", {})[today] = {"ok": bool(ok), "t": int(time.time())}
            _save(d)
        return streak(me)


def streak(me):
    M = me.get("moments") or {}
    n, t = 0, time.time()
    while time.strftime("%Y-%m-%d", time.gmtime(t - 86400 * n)) in M:
        n += 1
    if n == 0 and time.strftime("%Y-%m-%d", time.gmtime(t - 86400)) in M:     # today not yet played: the streak still holds
        k = 1
        while time.strftime("%Y-%m-%d", time.gmtime(t - 86400 * k)) in M:
            k += 1
        n = k - 1
    return n


# ------------------------------------------------------------------ level 3: the dojo
def _feat(c, i, ema):
    x = c[i]
    hi12, lo12 = max(z[2] for z in c[i - 12:i]), min(z[3] for z in c[i - 12:i])
    return {"green": x[4] > x[1], "above": x[4] > ema[i], "mom": x[4] > c[i - 3][4],
            "brk": 1 if x[4] > hi12 else (-1 if x[4] < lo12 else 0)}


def _outcome(w, k0, side, atr):
    """enter at the close of M1 index k0, stop and target 1 ATR away, over the next 30 minutes; in R, cost included"""
    e = w[k0][4]
    for z in w[k0 + 1:k0 + 1 + DEC_GAP * 5]:
        up, dn = z[2] - e, e - z[3]
        if side == 1:
            if dn >= atr:
                return -1.0 - COST_R
            if up >= atr:
                return 1.0 - COST_R
        else:
            if up >= atr:
                return -1.0 - COST_R
            if dn >= atr:
                return 1.0 - COST_R
    last = w[min(len(w) - 1, k0 + DEC_GAP * 5)][4]
    return round(side * (last - e) / atr - COST_R, 3)


def dojo_new(pid):
    rnd = random.Random()
    n_m1 = 5 * (HIST + DEC_N * DEC_GAP) + 10
    f, i, w = _window(n_m1, rnd)
    c = _m5(w)
    ema = _ema([x[4] for x in c], 20)
    dec = []
    for k in range(DEC_N):
        ci = HIST - 1 + k * DEC_GAP
        atr = _atr(c[:ci + 1])
        k1 = ci * 5 + 4
        rb, rs = _outcome(w, k1, 1, atr), _outcome(w, k1, -1, atr)
        diff = c[ci][4] - ema[ci]
        kino = 0 if abs(diff) < 0.2 * atr else (1 if diff > 0 else -1)
        dec.append({"ci": ci, "rb": rb, "rs": rs, "kino": kino, "feat": _feat(c, ci, ema)})
    s = {"id": "%x" % rnd.getrandbits(40), "f": f, "i": i, "t": int(time.time()), "dec": dec, "ch": [],
         "date": time.strftime("%Y-%m-%d", time.gmtime(c[0][0])), "c": _fmt(c)}
    with _LOCK:
        d = _load()
        _me(d, pid)["cur"] = s
        _save(d)
    return _dojo_view(s)


def _dojo_view(s, en=False):
    k = len(s["ch"])
    last = s["dec"][min(k, DEC_N - 1)]["ci"] if k < DEC_N else len(s["c"]) - 1
    out = {"id": s["id"], "step": k, "of": DEC_N, "candles": s["c"][:last + 1], "done": k >= DEC_N,
           "past": [{"ch": s["ch"][j], "r": _r(s["dec"][j], s["ch"][j]), "kino": s["dec"][j]["kino"], "at": s["c"][s["dec"][j]["ci"]][0]} for j in range(k)]}
    if k >= DEC_N:
        out["score"] = _score(s)
        out["date"] = s.get("date")
    return out


def _r(dc, ch):
    return 0.0 if ch == 0 else (dc["rb"] if ch == 1 else dc["rs"])


def _score(s):
    me = sum(_r(dc, ch) for dc, ch in zip(s["dec"], s["ch"]))
    kino = sum(_r(dc, dc["kino"]) for dc in s["dec"])
    rnd = random.Random(s["id"])
    sims = sorted(sum(_r(dc, rnd.choice((1, -1, 0))) for dc in s["dec"]) for _ in range(2000))
    pct = 100.0 * sum(1 for v in sims if v < me) / len(sims)
    return {"me": round(me, 2), "kino": round(kino, 2), "rand_med": round(sims[len(sims) // 2], 2), "pct": round(pct)}


def dojo_decide(pid, choice):
    ch = {"buy": 1, "sell": -1, "wait": 0}.get(str(choice), 0)
    with _LOCK:
        d = _load()
        me = _me(d, pid)
        s = me.get("cur")
        if not s or len(s["ch"]) >= DEC_N:
            return {"ok": False, "err": "no session"}
        s["ch"].append(ch)
        if len(s["ch"]) >= DEC_N:
            sc = _score(s)
            me["dojo"] = (me.get("dojo") or []) + [{"t": int(time.time()), "id": s["id"], "date": s.get("date"), "score": sc,
                                                     "dec": [{"ch": c_, "r": _r(dc, c_), "kino": dc["kino"], "feat": dc["feat"], "rb": dc["rb"], "rs": dc["rs"]}
                                                             for dc, c_ in zip(s["dec"], s["ch"])]}]
            me["dojo"] = me["dojo"][-300:]
            _habit(me)
            _cert(me)
        _save(d)
        v = _dojo_view(s)
    v["ok"] = True
    return v


def _all_dec(me):
    return [x for ss in (me.get("dojo") or []) for x in ss.get("dec") or []]


# ------------------------------------------------------------------ level 4: the habit hidden in the decisions
HAB = {"above": ("close > ema(close, 20) @ M5", "close < ema(close, 20) @ M5",
                 ("tu achètes quand le prix est au-dessus de sa moyenne des 20 dernières bougies, tu vends quand il est en dessous",
                  "you buy when price is above its 20-candle average, you sell when it is below"),
                 ("tu achètes quand le prix est sous sa moyenne des 20 dernières bougies (tu joues le retour), tu vends quand il est au-dessus",
                  "you buy when price is below its 20-candle average (you play the return), you sell when it is above")),
       "green": ("close > open @ M5", "close < open @ M5",
                 ("tu achètes après une bougie verte, tu vends après une rouge", "you buy after a green candle, you sell after a red one"),
                 ("tu achètes après une bougie rouge, tu vends après une verte", "you buy after a red candle, you sell after a green one")),
       "mom": ("close > prev(close, 3) @ M5", "close < prev(close, 3) @ M5",
               ("tu achètes quand le prix a monté sur les 15 dernières minutes, tu vends quand il a baissé",
                "you buy when price rose over the last 15 minutes, you sell when it fell"),
               ("tu achètes quand le prix a baissé sur les 15 dernières minutes, tu vends quand il a monté",
                "you buy when price fell over the last 15 minutes, you sell when it rose"))}
HAB_MIN = 0.6          # below this, no habit yet: the decisions do not follow one simple rule


def _habit(me):
    D = [x for x in _all_dec(me) if x["ch"] in (1, -1)]
    if len(me.get("dojo") or []) < DOJO_NEED or len(D) < 30:
        return
    best = None
    for f in HAB:
        agree = sum(1 for x in D if (x["ch"] == 1) == bool(x["feat"].get(f))) / len(D)
        if agree >= 0.5 and (not best or agree > best[1]):
            best = (f, agree)
        if 1 - agree > (best[1] if best else 0) and 1 - agree >= 0.5:
            best = (f + "_rev", 1 - agree)
    if not best or best[1] < HAB_MIN:
        me["habit"] = None
        me["habit_none"] = {"n": len(D), "best": round(best[1], 2) if best else None}
        return
    f, agree = best
    rev = f.endswith("_rev")
    base = f.replace("_rev", "")
    buy, sell, txt, rtxt = HAB[base]
    if rev:
        buy, sell, txt = sell, buy, rtxt
    paid = [x["r"] for x in D if (x["ch"] == 1) == (bool(x["feat"].get(base)) != rev)]
    me["habit"] = {"f": f, "agree": round(agree, 2), "n": len(D), "buy": buy, "sell": sell, "rev": rev,
                   "fr": txt[0], "en": txt[1],
                   "avg_r": round(sum(paid) / max(1, len(paid)), 3), "t": me.get("habit", {}).get("t") if me.get("habit") else int(time.time())}


# ------------------------------------------------------------------ the certificate: decisions that beat chance
def _cert(me):
    D = _all_dec(me)
    if len(D) < 120 or me.get("cert"):
        return
    tot = sum(x["r"] for x in D)
    rnd = random.Random(len(D))
    sims = [sum(x["rb"] if c_ == 1 else x["rs"] if c_ == -1 else 0 for x in D for c_ in (rnd.choice((1, -1, 0)),)) for _ in range(1500)]
    pct = 100.0 * sum(1 for v in sims if v < tot) / len(sims)
    if pct >= 95:
        me["cert"] = {"id": "%x" % random.getrandbits(32), "t": int(time.time()), "n": len(D), "total_r": round(tot, 1), "pct": round(pct, 1)}


# ------------------------------------------------------------------ the learner as a whole
def state(pid, robot_after=None, luck_ok=None, live=None, en=False):
    """robot_after(ts) -> the person's robot created after ts, or None; luck_ok(rid) / live(rid) -> bool (from the app)"""
    d = _load()
    me = _me(d, pid)
    R = me.get("reads") or []
    l1 = sum(1 for x in R if x["lv"] == 1 and x["ok"])
    l2 = [x["ok"] for x in R if x["lv"] == 2][-L2_WIN:]
    nd = len(me.get("dojo") or [])
    hab = me.get("habit")
    rob = robot_after(hab["t"]) if (hab and robot_after) else None
    lk = bool(rob and luck_ok and luck_ok(rob["id"]))
    lv = bool(rob and live and live(rob["id"]))
    done = [l1 >= L1_NEED, sum(l2) >= L2_NEED, nd >= DOJO_NEED and bool(hab), bool(rob), lk, lv]
    level = next((i for i, x in enumerate(done) if not x), len(done)) + 1
    D = _all_dec(me)
    last = (me.get("dojo") or [])[-10:]
    T = (lambda f, e: e if en else f)
    return {"ok": True, "track": me.get("track"), "level": min(level, 6), "done": done,
            "levels": [{"k": k, "name": en and e or f, "done": done[i]} for i, (k, f, e) in enumerate(LEVELS)],
            "progress": {"lire": [l1, L1_NEED], "voir": [sum(l2), L2_NEED, len(l2)], "decider": [nd, DOJO_NEED]},
            "dojo": {"sessions": nd, "decisions": len(D), "total_r": round(sum(x["r"] for x in D), 2),
                     "kino_r": round(sum(_r(x, x["kino"]) for x in D), 2),
                     "last": [{"date": s.get("date"), **(s.get("score") or {})} for s in last][::-1],
                     "pct_avg": round(sum((s.get("score") or {}).get("pct", 50) for s in last) / max(1, len(last))) if last else None},
            "habit": hab, "robot": rob, "cert": me.get("cert"), "streak": streak(me),
            "moment_done": time.strftime("%Y-%m-%d", time.gmtime()) in (me.get("moments") or {}),
            "in_dojo": bool(me.get("cur") and len(me["cur"].get("ch") or []) < DEC_N)}


def set_track(pid, track):
    with _LOCK:
        d = _load()
        _me(d, pid)["track"] = track if track in ("beginner", "some", "expert") else None
        _save(d)


def block(pid, en=False, owner=False):
    """what Kino knows of the person as a learner (his context, every reply)"""
    d = _load()
    me = d.get(pid)
    if not me or not me.get("track"):
        # 2026-11-02 (watch, Valère - new to trading): Kino answered him like a trader ("-13 R", "la cassure", "trois robots")
        # and never mentioned the school. He now knows it exists and what a newcomer needs - his judgment, not a rule.
        return "" if owner else (
            "L'ÉCOLE DE KINO existe dans l'app (page « L'école de Kino », menu Compte, ou la carte de l'accueil) : on y apprend à "
            "lire le marché, à décider sur de vraies séances passées (le dojo, comparé au hasard) et à construire son propre robot. "
            "Cette personne n'a pas encore dit si elle sait trader : écoute comment elle parle. Si elle débute, parle sans "
            "jargon (explique R, BOS, cassure, rebond la première fois en mots simples), ne lui fais pas construire des robots "
            "à l'aveugle, et propose-lui l'école une fois, naturellement, quand ça s'y prête.")
    s = state(pid)
    h = s.get("habit")
    L = LEVELS[s["level"] - 1]
    return ("L'ÉCOLE DE KINO - cette personne %s. Niveau %d/6 (%s). Lecture %d/%d, structure %d/%d, dojo %d séances "
            "(%d décisions, total %+.1f R ; toi Kino %+.1f R ; dernières séances au %s e centile face au hasard)%s%s. "
            "Tu es son prof et son partenaire d'entraînement : explique en mots simples, à partir de ses propres décisions, "
            "jamais de promesse de gain ; propose l'étape suivante seulement si elle s'y prête." % (
                {"beginner": "débute en trading", "some": "a déjà un peu tradé", "expert": "trade déjà (expert)"}.get(s["track"], "?"),
                s["level"], L[1], s["progress"]["lire"][0], L1_NEED, s["progress"]["voir"][0], L2_NEED, s["dojo"]["sessions"],
                s["dojo"]["decisions"], s["dojo"]["total_r"], s["dojo"]["kino_r"], s["dojo"]["pct_avg"] if s["dojo"]["pct_avg"] is not None else "-",
                (" ; son habitude trouvée : %s (%d %% de ses décisions)" % (h["fr"], round(100 * h["agree"]))) if h else "",
                (" ; certificat obtenu (%s décisions, mieux que %s %% du hasard)" % (s["cert"]["n"], s["cert"]["pct"])) if s.get("cert") else ""))
