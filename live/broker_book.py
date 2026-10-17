"""broker_book.py - the broker book + the sign-up probe (owner 2026-10-16: "the fastest way to say it's not gonna work").

The BOOK (live/broker_book.json) keeps one page per broker server we have ever read: its Bitcoin name, sizing,
cost (spread in $), clock, fill type, history depth, and how to reach it (a server address when the name is not
in the terminal's list). Sources: the workers' 6-hourly nest_data/<uid>.broker.json, the pilot checks, and the
sign-up probe. A member who names a broker in the book gets the verdict BEFORE typing a password.

The PROBE logs the member's own account into ONE shared terminal (C:\\NestTerminals\\probe), reads the facts
in a single call, and logs out. No personal terminal is built for a red verdict. One probe at a time.

The VERDICT places the broker's cost on the robot's cost curve (live/lab/spread_curve.json, from
study/spread_whatif.py: the proof page's 42-day tick replay rerun at several spreads):
    green  - the robot keeps >= 70 % of its Exness result at this cost
    orange - still positive, but less
    red    - nothing pays at this cost, or the account cannot be traded (sizing, currency, netting)
    unknown - no curve yet, or the broker could not be read

    lookup(server) / record(profile, source) / sync_nest_data()
    verdict(profile) -> {"zone", "spread", "exness_spread", "est_net", "native_net", "reasons": [...]}
    probe_start(job_id, login, password, server) / probe_state(job_id)
"""
import json, os, sys, time, threading, subprocess

DIR = os.path.dirname(os.path.abspath(__file__))
BOOK = os.path.join(DIR, "broker_book.json")
CURVE = os.path.join(DIR, "lab", "spread_curve.json")
NEST_DATA = os.path.join(DIR, "nest_data")
PROBE_TERMINAL = r"C:\NestTerminals\probe\terminal64.exe"
PROBE_TIMEOUT_S = 75                 # the name lookup; the address (when the book has one) is tried after
EXNESS_SPREAD = 4.48                 # Exness Pro BTCUSD, measured 2026-10-16 (the bots' home cost)
GREEN_KEEP = 0.70
_LOCK = threading.Lock()
_PROBE_LOCK = threading.Lock()


def norm(server):
    return str(server or "").strip().lower()


def key_of(server):
    """the broker's feed key: the server name before '-', letters and digits only ("Exness-MT5Real30" -> "exness",
    "FOREX.comGlobal-Demo 531" -> "forexcomglobal", "PepperstoneUK-Demo" -> "pepperstoneuk"); '' when unknown"""
    import re
    s = norm(server)
    if not s:
        return ""
    if "exness" in s:
        return "exness"
    return re.sub(r"[^a-z0-9]", "", s.split("-")[0])


def feed_file(server, kind=""):
    """the chart feed files for a member's broker: Exness -> the main feed; another broker -> chart_broker/<key>...
    kind '' candles, 'htf', 'nerv', 'pbchain'. Returns None for a non-Exness broker without a feed yet."""
    k = key_of(server)
    if not k or k == "exness":
        return os.path.join(DIR, {"": "owl_chart_btc.json", "htf": "owl_chart_htf.json", "nerv": "owl_nerv_hist.json", "pbchain": "owl_pb_chain.json"}[kind])
    p = os.path.join(DIR, "chart_broker", k + ("_" + kind if kind else "") + ".json")
    return p if os.path.exists(os.path.join(DIR, "chart_broker", k + ".json")) else None


def feed_fresh(server, max_age_s=180):
    """is this broker's feed alive? (Exness: the main feed file; others: chart_broker/<key>.json)"""
    p = feed_file(server)
    try:
        return p is not None and time.time() - os.path.getmtime(p) < max_age_s
    except OSError:
        return False


def _load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def _save(path, obj):
    tmp = path + ".%d.tmp" % os.getpid()
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def book():
    return _load(BOOK, {}) or {}


def lookup(server):
    """the book's page for this server (by exact name, else by the company/prefix before '-')"""
    b = book(); k = norm(server)
    if not k:
        return None
    pg = None
    if k in b:
        pg = dict(b[k])
    else:
        pre = k.split("-")[0]
        for kk, v in b.items():
            if kk.split("-")[0] == pre:
                pg = dict(v, matched_by="prefix"); break
    if pg is not None and pg.get("btc"):
        pg["verdict"] = verdict(pg)          # always against the CURRENT cost curve, never a stored verdict
    return pg


def spread_usd(profile):
    b = (profile or {}).get("btc") or {}
    try:
        return round(float(b.get("spread") or 0) * float(b.get("point") or 0), 2)
    except Exception:
        return None


def record(profile, source, server_addr=None):
    """fold one profile into the book (never drops a stored server address)"""
    if not profile or not profile.get("server"):
        return None
    with _LOCK:
        b = book(); k = norm(profile["server"])
        page = dict(b.get(k) or {})
        page.update({"server": profile["server"], "company": profile.get("company", ""), "currency": profile.get("currency"),
                     "leverage": profile.get("leverage"), "margin_mode": profile.get("margin_mode"), "btc": profile.get("btc"),
                     "spread_usd": spread_usd(profile), "checked_at": int(profile.get("checked_at") or time.time()), "source": source})
        if server_addr:
            page["server_addr"] = server_addr
        page["verdict"] = verdict(profile)
        b[k] = page
        _save(BOOK, b)
        return page


def sync_nest_data():
    """the workers' broker files -> the book (cheap; called before a lookup)"""
    try:
        for f in os.listdir(NEST_DATA):
            if f.endswith(".broker.json"):
                p = _load(os.path.join(NEST_DATA, f), None)
                if p and p.get("server"):
                    cur = book().get(norm(p["server"]))
                    if not cur or int(cur.get("checked_at") or 0) < int(p.get("checked_at") or 0):
                        record(p, "worker:" + f[:-12])
    except Exception:
        pass


def curve():
    """{"native_spread": x, "robots": {id: {"name", "native": net, "points": {"10": net, "20": net, ...}}}} or None"""
    c = _load(CURVE, None)
    return c if c and c.get("robots") else None


def est_at(sp, robot="owl"):
    """this robot's 42-day net at this spread, read off its curve (linear between measured points) -> (est, native)"""
    c = curve()
    if c is None or sp is None or robot not in c["robots"]:
        return None, None
    r = c["robots"][robot]; nat = float(r["native"])
    _d = {float(k): float(v) for k, v in (r.get("points") or {}).items()}
    _d[float(c["native_spread"])] = nat                   # the real-tick point wins over a forced one at the same spread
    pts = sorted(_d.items())
    if sp <= pts[0][0]:
        return pts[0][1], nat
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= sp <= x1:
            return round(y0 + (y1 - y0) * (sp - x0) / (x1 - x0), 2), nat
    (x0, y0), (x1, y1) = pts[-2], pts[-1]                      # beyond the last point: continue the last slope
    return round(y1 + (y1 - y0) * (sp - x1) / (x1 - x0), 2), nat


def verdict(profile):
    """owner 2026-10-16: "the verification should check any existing robot" - every robot on the curve is placed at
    this broker's cost; the zone is the BEST robot's, and "robots" lists them all, best first (est > 0 = pays)."""
    import broker_profile as BP
    out = {"zone": "unknown", "spread": spread_usd(profile), "exness_spread": EXNESS_SPREAD, "est_net": None, "native_net": None, "robots": [], "reasons": []}
    if not profile:
        out["reasons"].append("compte illisible"); return out
    C = {c["k"]: c for c in BP.checks(profile)}
    # 2026-10-17: which of the nest's other markets exist at this broker (information today, a gate for market robots)
    _mk = profile.get("markets") or {}
    out["markets"] = [{"key": k, "label": fr, "found": bool(_mk.get(k)), "name": (_mk.get(k) or {}).get("name")} for k, fr, _, _, _ in BP.NEST_MARKETS]
    hard = [k for k in ("btc_found", "contract", "lots", "currency", "hedging") if k in C and not C[k]["ok"]]
    if hard:
        out["zone"] = "red"; out["reasons"] = [C[k]["fr"] for k in hard]; return out
    c = curve()
    if c is None:
        out["reasons"].append("courbe de coût pas encore mesurée"); return out
    rows = []
    for rid, r in c["robots"].items():
        est, nat = est_at(out["spread"], rid)
        if est is not None:
            rows.append({"id": rid, "name": r.get("name") or rid, "est": est, "native": nat, "pays": est > 0, "keeps": (est / nat) if nat else None})
    rows.sort(key=lambda x: -x["est"])
    out["robots"] = rows
    if not rows:
        out["reasons"].append("courbe de coût pas encore mesurée"); return out
    best = rows[0]
    out["est_net"], out["native_net"], out["best"] = best["est"], best["native"], best["id"]
    if "exness" in str(profile.get("server", "")).lower():
        out["zone"] = "green"; return out                    # the robots' home broker: the curve's native point
    if best["est"] <= 0:
        out["zone"] = "red"; out["reasons"].append("le coût par trade mange tout le gain, pour chaque robot")
    elif best["keeps"] is not None and best["keeps"] >= GREEN_KEEP:
        out["zone"] = "green"
    else:
        out["zone"] = "orange"; out["reasons"].append("le coût par trade réduit le gain")
    return out


# ---- the sign-up probe: a subprocess (the MetaTrader5 module is one connection per process) ----
_PROBE_CODE = r"""
import sys, json, time
sys.path.insert(0, %(dir)r)
import MetaTrader5 as mt5
import broker_profile as BP
login, pwd, server, addr, term, tmo = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], int(sys.argv[6])
ok = False; used = None; errs = []
for srv in [s for s in (addr, server) if s]:      # a known address first: the name lookup can take 75 s to fail
    t0 = time.time()
    ok = mt5.initialize(path=term, login=login, password=pwd, server=srv, timeout=tmo * 1000)
    if ok and (mt5.account_info() is None or mt5.account_info().login != login):
        ok = False
    if ok:
        used = srv; break
    errs.append("%%s: %%s (%%.0fs)" %% (srv, mt5.last_error(), time.time() - t0)); mt5.shutdown()
if not ok:
    print(json.dumps({"error": "; ".join(errs)})); sys.exit(0)
p = BP.profile(mt5)
mt5.shutdown()
print(json.dumps({"profile": p, "via": used}))
"""


def _job_path(job_id):
    return os.path.join(NEST_DATA, "probe_%s.json" % job_id)


def probe_state(job_id):
    return _load(_job_path(job_id), None)


def _run(job_id, login, password, server, form):
    page = lookup(server) or {}
    addr = page.get("server_addr") or ""
    res = {"state": "running", "t": int(time.time()), "server": server, "login": int(login), "form": form}
    _save(_job_path(job_id), res)
    with _PROBE_LOCK:                                         # one shared terminal: one probe at a time
        try:
            r = subprocess.run([sys.executable, "-c", _PROBE_CODE % {"dir": DIR}, str(login), password, server, addr, PROBE_TERMINAL, str(PROBE_TIMEOUT_S)],
                               capture_output=True, text=True, timeout=2 * PROBE_TIMEOUT_S + 60, creationflags=0x08000000, cwd=DIR)
            line = (r.stdout.strip().splitlines() or [""])[-1]
            j = json.loads(line) if line.startswith("{") else {"error": (r.stderr.strip()[-200:] or "probe gave no answer")}
        except subprocess.TimeoutExpired:
            j = {"error": "le courtier n'a pas répondu à temps"}
        except Exception as e:
            j = {"error": str(e)[:200]}
    res["state"] = "done"; res["done_t"] = int(time.time())
    if j.get("profile"):
        res["profile"] = j["profile"]; res["via"] = j.get("via")
        res["verdict"] = verdict(j["profile"])
        record(j["profile"], "probe", server_addr=j.get("via") if j.get("via") and j.get("via") != server else None)
    else:
        res["error"] = j.get("error") or "?"
        res["verdict"] = {"zone": "unknown", "reasons": ["connexion impossible : " + res["error"]]}
    _save(_job_path(job_id), res)


def probe_start(job_id, login, password, server, form=None):
    """non-blocking; the result lands in nest_data/probe_<id>.json (state running -> done). The form is kept
    with the job so the member's 'Continuer' needs nothing retyped; jobs older than 1 h are swept."""
    os.makedirs(NEST_DATA, exist_ok=True)
    try:
        for f in os.listdir(NEST_DATA):
            if f.startswith("probe_") and f.endswith(".json") and time.time() - os.path.getmtime(os.path.join(NEST_DATA, f)) > 3600:
                os.remove(os.path.join(NEST_DATA, f))
    except Exception:
        pass
    threading.Thread(target=_run, args=(job_id, login, password, server, form or {}), daemon=True).start()


if __name__ == "__main__":
    # python broker_book.py                 -> sync the workers' files, print the book
    # python broker_book.py <secrets key>   -> probe that pilot account through the shared terminal
    sync_nest_data()
    if len(sys.argv) > 1:
        P = _load(os.path.join(DIR, "owl_secrets.json"), {})[sys.argv[1]]
        if P.get("server_addr"):
            with _LOCK:
                b = book(); b.setdefault(norm(P["server"]), {"server": P["server"]})["server_addr"] = P["server_addr"]; _save(BOOK, b)
        jid = "cli%d" % int(time.time())
        _run(jid, P["login"], P["password"], P["server"], {})
        st = probe_state(jid)
        print(json.dumps({k: v for k, v in st.items() if k not in ("form", "profile")}, ensure_ascii=False, indent=1))
    for k, v in book().items():
        print("%-28s %-10s spread $%-6s %s" % (k, (v.get("verdict") or {}).get("zone"), v.get("spread_usd"), (v.get("btc") or {}).get("name")))
