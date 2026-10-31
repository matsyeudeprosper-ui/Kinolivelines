"""filter_screen.py (2026-10-31, owner: "all possible filters to get a positive month, all 10 months. Use quick tests first")

QUICK screen, no new simulation: the closed trades of the 10 botsim month replays (real bot, fresh 200 $ each month),
every filter = skip the main trades matching 1 or 2 conditions (their recovery adds go with them). Per filter: months
positive out of 10, total $. Controls, because many filters on 10 months WILL find 10/10 by luck:
  random   skip the same number of random main trades (300 draws): how often luck reaches the same months / total
  split    pick the best filters on Jan-May, judge them on Jun-Oct, and the reverse
Limits (say them): skipping a trade in the real bot changes debt/jar/one-position state and can free later entries;
this screen cannot see that - survivors go to a full botsim run before any claim.

    python -X utf8 study/botsim/filter_screen.py   -> table + study/botsim/filter_screen.json
"""
import calendar, csv, glob, itertools, json, os, random, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MONTHS = ["2026-%02d" % m for m in range(1, 11)]


def tsec(s):
    return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))


T = []
for p in sorted(glob.glob(os.path.join(HERE, "runs", "month_2026-*-01", "bos_journal_valere.csv"))):
    ym = p.split("month_")[1][:7]
    for r in csv.DictReader(open(p, encoding="utf-8")):
        if r.get("outcome") not in ("WIN", "LOSS") or not r.get("exit_time_utc"):
            continue
        h = {}
        try:
            h = json.loads(r.get("htf_entry") or "{}")
        except Exception:
            pass
        te = tsec(r["entry_time_utc"])
        d = 1 if r["direction"] == "BUY" else -1
        T.append({"ym": ym, "t": te, "tx": tsec(r["exit_time_utc"]), "add": r["is_add"] == "True", "pl": float(r["profit_usd"] or 0),
                  "kind": r["kind"], "internal": r["internal"] == "True", "dir": d, "hour": time.gmtime(te).tm_hour,
                  "wday": time.gmtime(te).tm_wday, "stop": float(r["dist_pts"] or 0), "nerv": float(r["nervosity"] or 0),
                  "vratio": float(r["vol_now"] or 0) / max(1e-9, float(r["vol_ref"] or 0)), "moves": int(float(r["movement_count"] or 0)),
                  "day_n": int(float(r["day_n_at_entry"] or 0)), "debt": float(r["debt_at_entry"] or 0), "storm": r["storm"],
                  "m15": d * ((h.get("m15") or {}).get("t") or 0), "h1": d * ((h.get("h1") or {}).get("t") or 0),
                  "h4": d * ((h.get("h4") or {}).get("t") or 0), "agree": (h.get("agree") or 0)})
MAIN = [x for x in T if not x["add"]]
# recovery bullets are not in the journal: "ADD +-x (lot" lines of the month log, closed while a main trade was open
ADDS = []
for p in sorted(glob.glob(os.path.join(HERE, "runs", "month_2026-*-01", "bos_bot_valere.log"))):
    ym = p.split("month_")[1][:7]
    for ln in open(p, encoding="utf-8", errors="replace"):
        parts = ln.split(" ")
        if len(parts) > 3 and parts[1] == "ADD" and parts[3] == "(lot":
            ADDS.append({"ym": ym, "t": tsec(parts[0]), "pl": float(parts[2])})
for x in MAIN:                       # a bullet belongs to the main trade open when it closed (else the one before it)
    x["adds"] = []
for a in ADDS:
    own = [x for x in MAIN if x["ym"] == a["ym"] and x["t"] <= a["t"]]
    if own:
        max(own, key=lambda x: x["t"])["adds"].append(a)
T += [dict(a, add=True) for a in ADDS]
base = {m: round(sum(x["pl"] for x in T if x["ym"] == m), 2) for m in MONTHS}
print("trades %d main + %d adds | months %s | total %+.2f" % (len(MAIN), len(T) - len(MAIN),
      " ".join("%+.0f" % base[m] for m in MONTHS), sum(base.values())))


def q(key):
    v = sorted(x[key] for x in MAIN)
    return [v[len(v) // 3], v[2 * len(v) // 3]]


# every condition is "skip when ..."
C = {}
for k in ("FLIP-BOS", "BOS"):
    C["kind=" + k] = lambda x, k=k: x["kind"] == k
C["internal"] = lambda x: x["internal"]
C["buy"] = lambda x: x["dir"] == 1
C["sell"] = lambda x: x["dir"] == -1
for a, b in ((0, 6), (6, 12), (12, 17), (17, 24), (8, 16), (13, 21), (0, 8), (21, 24)):
    C["hour %02d-%02d" % (a, b)] = lambda x, a=a, b=b: a <= x["hour"] < b
C["weekend"] = lambda x: x["wday"] >= 5
C["monday"] = lambda x: x["wday"] == 0
C["friday"] = lambda x: x["wday"] == 4
for key in ("stop", "nerv", "vratio", "debt"):
    lo, hi = q(key)
    C["%s low third" % key] = lambda x, key=key, lo=lo: x[key] < lo
    C["%s high third" % key] = lambda x, key=key, hi=hi: x[key] >= hi
C["moves>=4"] = lambda x: x["moves"] >= 4
C["moves<=2"] = lambda x: x["moves"] <= 2
C["day_n>=3"] = lambda x: x["day_n"] >= 3
C["day_n>=5"] = lambda x: x["day_n"] >= 5
C["in debt"] = lambda x: x["debt"] > 0
for tf in ("m15", "h1", "h4"):
    C[tf + " against"] = lambda x, tf=tf: x[tf] < 0
    C[tf + " not with"] = lambda x, tf=tf: x[tf] <= 0
C["agree 0"] = lambda x: x["agree"] == 0
for s in sorted(set(x["storm"] for x in MAIN)):
    C["storm=" + s] = lambda x, s=s: x["storm"] == s

F = dict(C)
for (n1, f1), (n2, f2) in itertools.combinations(C.items(), 2):
    F[n1 + " OR " + n2] = lambda x, f1=f1, f2=f2: f1(x) or f2(x)
    F[n1 + " AND " + n2] = lambda x, f1=f1, f2=f2: f1(x) and f2(x)


def months_of(skip):
    mo = {m: 0.0 for m in MONTHS}
    for i, x in enumerate(MAIN):
        if not skip[i]:
            mo[x["ym"]] += x["pl"] + sum(a["pl"] for a in x["adds"])
    return np.array([mo[m] for m in MONTHS])


res = []
for name, f in F.items():
    skip = [bool(f(x)) for x in MAIN]
    k = sum(skip)
    if k == 0 or k > 0.7 * len(MAIN):
        continue
    mv = months_of(skip)
    res.append({"name": name, "skipped": k, "months": mv, "up": int((mv > 0).sum()), "net": float(mv.sum()),
                "h1": float(mv[:5].sum()), "h2": float(mv[5:].sum()), "up1": int((mv[:5] > 0).sum()), "up2": int((mv[5:] > 0).sum())})
print("filters tried: %d" % len(res))

rng = random.Random(7)
NULL = {}


def null_for(k):
    b = k // 10 * 10 + 5                     # bucket the skip count so the random control is reused
    if b not in NULL:
        L = []
        for _ in range(300):
            idx = set(rng.sample(range(len(MAIN)), min(b, len(MAIN) - 1)))
            mv = months_of([i in idx for i in range(len(MAIN))])
            L.append((int((mv > 0).sum()), float(mv.sum()), float(mv[:5].sum()), float(mv[5:].sum())))
        NULL[b] = np.array(L)
    return NULL[b]


for r in res:
    N = null_for(r["skipped"])
    r["p_up"] = float(np.mean(N[:, 0] >= r["up"]))
    r["p_net"] = float(np.mean(N[:, 1] >= r["net"]))

ten = [r for r in res if r["up"] == 10]
nine = [r for r in res if r["up"] >= 9]
print("10/10 months: %d filters | 9+/10: %d" % (len(ten), len(nine)))
anyN = np.concatenate(list(NULL.values()))
print("random skips reaching 10/10: %.1f %% of draws, 9+/10: %.1f %%" % (100 * np.mean(anyN[:, 0] >= 10), 100 * np.mean(anyN[:, 0] >= 9)))

print("\nTOP by months up then total:")
for r in sorted(res, key=lambda r: (-r["up"], -r["net"]))[:25]:
    print("  %-48s skip %3d | %2d/10  net %+7.1f | random beats months %.2f, money %.2f | %s" % (
        r["name"][:48], r["skipped"], r["up"], r["net"], r["p_up"], r["p_net"], " ".join("%+.0f" % v for v in r["months"])))


def judge(pick_key, judge_key, up_pick, up_judge, label):
    top = sorted(res, key=lambda r: (-r[up_pick], -r[pick_key]))[:10]
    print("\nSPLIT %s: top 10 picked there, judged on the other half" % label)
    for r in top:
        N = null_for(r["skipped"])
        col = 2 if judge_key == "h1" else 3
        p = float(np.mean(N[:, col] >= r[judge_key]))
        print("  %-48s pick %+6.1f (%d/5) -> judged %+6.1f (%d/5), random beats it %.2f" % (
            r["name"][:48], r[pick_key], r[up_pick], r[judge_key], r[up_judge], p))
        r.setdefault("judged", {})[label] = p


judge("h1", "h2", "up1", "up2", "Jan-May -> Jun-Oct")
judge("h2", "h1", "up2", "up1", "Jun-Oct -> Jan-May")
json.dump([{k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in r.items()} for r in sorted(res, key=lambda r: (-r["up"], -r["net"]))],
          open(os.path.join(HERE, "filter_screen.json"), "w"), indent=1)
print("DONE")
