"""The lab's tireless layer (2026-09-28, owner: "an intelligence that watches
the data, tries 'what if we did x differently', endlessly").

Every night:
  1. replay the deployed rules on the last ~42 days (the base);
  2. replay a fixed BATTERY of what-ifs through lab/harness.py - target size,
     continuations, waiting, big-hour brake, weekday and hour exclusions,
     half size in a nervous market, the nervosity brake, bullets, streaks;
  3. replay every pending proposal the chercheur session left in
     lab/proposals.json;
  4. write lab/auto.json (verdicts A/B/C/=, both halves, blocked entries),
     append lab/auto_history.jsonl, and for every A make sure a paper twin
     exists in lab/twins.json and is running (bos_paper_variant.py).

It never touches the bots. Verdict rules live in lab/harness.py and are
never tuned here.

    python lab_researcher.py            # the full battery (~40 min)
    python lab_researcher.py --quick    # a handful, for a smoke test
    python lab_researcher.py --cuts     # only the live-journal cuts, as JSON
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

LIVE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(LIVE, "lab")
sys.path.insert(0, LAB)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["lab_researcher"]
import harness as H                    # noqa: E402

AUTO = os.path.join(LAB, "auto.json")
HIST = os.path.join(LAB, "auto_history.jsonl")
# 2026-09-29: simulate() also returns the daily curve and the per-trade money
# (the proof page needs them). auto.json and the app payload keep the scalars
# only, or every night's file would carry ~100 kB of arrays per variant.
def _slim(d):
    return {k: val for k, val in d.items() if k not in ("curve", "pnls")}
REQ = os.path.join(LAB, "requests.json")
PROP = os.path.join(LAB, "proposals.json")
TWINS = os.path.join(LAB, "twins.json")
LOG = os.path.join(LAB, "researcher.log")


def say(m):
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


BATTERY = [
    ("rr04", "Viser un gain de 0,4 fois le risque", "Aim for a gain of 0.4 times the risk", "cible", {"rr": 0.4}),
    ("rr05", "Viser un gain de 0,5 fois le risque", "Aim for a gain of 0.5 times the risk", "cible", {"rr": 0.5}),
    ("rr06", "Viser un gain de 0,6 fois le risque", "Aim for a gain of 0.6 times the risk", "cible", {"rr": 0.6}),
    ("rr07", "Viser un gain de 0,7 fois le risque", "Aim for a gain of 0.7 times the risk", "cible", {"rr": 0.7}),
    ("rr10", "Viser un gain égal au risque", "Aim for a gain equal to the risk", "cible", {"rr": 1.0}),
    ("rr12", "Viser un gain de 1,2 fois le risque", "Aim for a gain of 1.2 times the risk", "cible", {"rr": 1.2}),
    ("cont0", "Après une perte, aucun trade de plus dans le même sens", "After a loss, no extra same-direction trade", "structure", {"n_cont": 0}),
    ("cont2", "Après une perte, deux trades de plus dans le même sens", "After a loss, two extra same-direction trades", "structure", {"n_cont": 2}),
    ("wait10", "Attendre 10 minutes après chaque trade", "Wait 10 minutes after each trade", "rythme", {"wait_min": 10}),
    ("wait20", "Attendre 20 minutes après chaque trade", "Wait 20 minutes after each trade", "rythme", {"wait_min": 20}),
    ("wait30", "Attendre 30 minutes après chaque trade", "Wait 30 minutes after each trade", "rythme", {"wait_min": 30}),
    ("ext300", "Ne pas entrer après une envolée de 300 points", "No entry after a 300-point run", "rythme", {"ext_pts": 300}),
    ("ext400", "Ne pas entrer après une envolée de 400 points", "No entry after a 400-point run", "rythme", {"ext_pts": 400}),
    ("ext500", "Ne pas entrer après une envolée de 500 points", "No entry after a 500-point run", "rythme", {"ext_pts": 500}),
    ("ext700", "Ne pas entrer après une envolée de 700 points", "No entry after a 700-point run", "rythme", {"ext_pts": 700}),
    ("nosun", "Ne pas trader le dimanche", "No trading on Sunday", "rythme", {"skip_wd": [6]}),
    ("nowe", "Ne pas trader le week-end", "No trading on weekends", "rythme", {"skip_wd": [5, 6]}),
    ("nomon", "Ne pas trader le lundi", "No trading on Monday", "rythme", {"skip_wd": [0]}),
    ("nonight", "Ne pas trader la nuit (00–08 h UTC)", "No trading at night (00–08 UTC)", "rythme", {"skip_hours": list(range(0, 8))}),
    ("noday", "Ne pas trader en journée (08–16 h UTC)", "No trading during the day (08–16 UTC)", "rythme", {"skip_hours": list(range(8, 16))}),
    ("noeve", "Ne pas trader en soirée (16–24 h UTC)", "No trading in the evening (16–24 UTC)", "rythme", {"skip_hours": list(range(16, 24))}),
    ("hothalf", "Miser moitié moins quand le marché est nerveux", "Bet half when the market is nervous", "meteo", {"size_hot": 0.5}),
    ("nervgate", "Ne rien prendre quand le marché est nerveux", "Take nothing when the market is nervous", "meteo", {"nerv_gate": True}),
    ("debtnerv", "Ne rien prendre quand on est encore dans le rouge ET que le marché est nerveux", "Take nothing when still in the red AND the market is nervous", "meteo", {"debt_nerv_gate": True}),
    # 2026-09-29: cost_max, min_range, minute_win and one_per_hour exist as
    # dials but are NOT in the nightly battery. Every dose was tested and
    # scored C (see lab/CHERCHEUR.md). Re-running proven losers 34 times a
    # night only gives noise more chances to produce a false A; the chercheur
    # can still combine them in a proposal when it has a reason.
    ("bul2", "Deux renforts au lieu de trois après une perte", "Two boosts instead of three after a loss", "argent", {"bullets": 2}),
    ("bul4", "Quatre renforts au lieu de trois après une perte", "Four boosts instead of three after a loss", "argent", {"bullets": 4}),
    ("bul0", "Aucun renfort après une perte", "No boost after a loss", "argent", {"bullets": 0}),
    ("k1", "Un seul renfort de suite, puis on attend un gain", "One boost in a row, then wait for a win", "argent", {"k_streak": 1}),
    ("k3", "Jusqu’à trois renforts de suite", "Up to three boosts in a row", "argent", {"k_streak": 3}),
]
QUICK = {"rr06", "ext500", "hothalf", "nosun"}


def load_json(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def save_json(p, obj):
    tmp = p + ".tmp"
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def ensure_twin(vid, title_fr, title_en, cfg, verdict):
    """Layer 3: an A starts observing by itself (paper, no money)."""
    tw = load_json(TWINS, {"twins": []})
    lst = tw.setdefault("twins", [])
    if any(t.get("id") == vid for t in lst):
        return False
    lst.append({"id": vid, "title_fr": title_fr, "title_en": title_en, "cfg": cfg, "verdict": verdict,
                "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "running", "by": "chercheur"})
    save_json(TWINS, tw)
    try:
        subprocess.Popen([sys.executable.replace("python.exe", "pythonw.exe"), os.path.join(LIVE, "bos_paper_variant.py"), vid],
                         cwd=LIVE, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        say(f"twin started for {vid}")
    except Exception as e:
        say(f"twin start failed for {vid}: {e}")
    return True


def main():
    quick = "--quick" in _A
    if "--cuts" in _A:
        sys.path.insert(0, LIVE)
        import owl_app_server as S     # the same cuts the lab shows
        print(json.dumps(S.lab_candidates(S._journal_unique()), ensure_ascii=False))
        return
    t0 = time.time()
    sym, R = H.bars()
    say(f"researcher start: {sym} {len(R)/1440:.1f} days, {'quick' if quick else 'full battery'}")
    base = H.run_cfg(R, 7.0, {})
    say(f"base: {base['full']['trades']} trades net {base['full']['net']:+.2f} worst {base['full']['worst_debt']:.2f}")
    # 2026-09-29 (owner): the long window and the real trades, as two more
    # views - the 42-day verdict stays the verdict; a weaker long-window or
    # real-trade result is a caution, never a drop
    RL = None
    baseL = None
    try:
        _, RL = H.bars_long()
        if RL is not None and len(RL) >= len(R) + 7 * 1440:
            baseL = H.run_cfg(RL, 7.0, {})
            say(f"long window: {len(RL)/1440:.1f} days, base net {baseL['full']['net']:+.2f} worst {baseL['full']['worst_debt']:.2f}")
        else:
            RL = None
    except Exception as e:
        say(f"long window unavailable: {e}")
        RL = None
    T = H.real_entries()
    baseT = H.simulate_real(T, R, 7.0, {}) if T else None
    if baseT:
        say(f"real trades: {len(T)} entries since the journal began, base net {baseT['net']:+.2f} (actual {baseT['actual']:+.2f})")
    prev = load_json(AUTO, {"variants": []})
    prev_by = {v["id"]: v for v in prev.get("variants", [])}
    items = [b for b in BATTERY if (not quick or b[0] in QUICK)]
    props = load_json(PROP, {"proposals": []})
    for p in props.get("proposals", []):
        if p.get("status", "pending") == "pending" and isinstance(p.get("cfg"), dict):
            items.append((p["id"], p.get("title_fr", p["id"]), p.get("title_en", p["id"]), p.get("family", "idee"), p["cfg"]))
    out = []
    hist = open(HIST, "a", encoding="utf-8")
    for vid, fr, en, fam, cfg in items:
        try:
            v = H.run_cfg(R, 7.0, cfg)
            vd = H.verdict(v, base)
        except Exception as e:
            say(f"{vid}: ERROR {type(e).__name__}: {e}")
            continue
        prevv = (prev_by.get(vid) or {}).get("verdict")
        rec = {"id": vid, "title_fr": fr, "title_en": en, "family": fam, "cfg": H.cfg_of(cfg), "full": _slim(v["full"]),
               "h1": _slim(v["h1"]), "h2": _slim(v["h2"]), "verdict": vd, "prev_verdict": prevv,
               "src": "chercheur" if any(p.get("id") == vid for p in props.get("proposals", [])) else "battery",
               "diff_net": round(v["full"]["net"] - base["full"]["net"], 2),
               "diff_worst": round(v["full"]["worst_debt"] - base["full"]["worst_debt"], 2)}
        if RL is not None and baseL is not None:
            try:
                vL = H.run_cfg(RL, 7.0, cfg)
                rec["long"] = {"days": round(len(RL) / 1440), "verdict": H.verdict(vL, baseL),
                               "diff_net": round(vL["full"]["net"] - baseL["full"]["net"], 2),
                               "diff_worst": round(vL["full"]["worst_debt"] - baseL["full"]["worst_debt"], 2),
                               "h1": round(vL["h1"]["net"] - baseL["h1"]["net"], 2), "h2": round(vL["h2"]["net"] - baseL["h2"]["net"], 2),
                               "net": vL["full"]["net"], "worst": vL["full"]["worst_debt"], "trades": vL["full"]["trades"]}
            except Exception as e:
                say(f"{vid}: long window ERROR {e}")
        if baseT:
            try:
                vT = H.simulate_real(T, R, 7.0, cfg)
                rec["real"] = {"n_real": len(T), "trades": vT["trades"], "blocked": vT["blocked"], "net": vT["net"],
                               "worst": vT["worst_debt"], "diff_net": round(vT["net"] - baseT["net"], 2),
                               "diff_worst": round(vT["worst_debt"] - baseT["worst_debt"], 2)}
            except Exception as e:
                say(f"{vid}: real trades ERROR {e}")
        out.append(rec)
        hist.write(json.dumps({"d": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "id": vid, "verdict": vd,
                               "net": v["full"]["net"], "worst": v["full"]["worst_debt"], "trades": v["full"]["trades"]}) + "\n")
        say(f"{vid:9s} {vd}  net {v['full']['net']:+8.2f} ({rec['diff_net']:+.2f})  worst {v['full']['worst_debt']:6.2f} ({rec['diff_worst']:+.2f})  halves {v['h1']['net']-base['h1']['net']:+.2f} / {v['h2']['net']-base['h2']['net']:+.2f}")
        for p in props.get("proposals", []):
            if p.get("id") == vid and p.get("status", "pending") == "pending":
                p["status"] = "done"; p["verdict"] = vd; p["done"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if vd == "A":
            if ensure_twin(vid, fr, en, H.cfg_of(cfg), vd):
                try:
                    import twin_judge as TJ      # 2026-09-29: tell Kino + the Strategie members
                    TJ.emit("twin_started", ("\U0001f9ea Le labo : un jumeau démarre",
                                             f"« {fr} » a eu un A cette nuit. Une copie du robot l’essaie pour de faux à partir de maintenant."),
                            ("\U0001f9ea The lab: a twin starts",
                             f"“{en}” scored an A tonight. A copy of the robot tries it for pretend from now on."), members=True)
                except Exception as e:
                    say(f"event failed: {e}")
    hist.close()
    save_json(PROP, props)
    # the dials built on the chercheur's requests retire by themselves after
    # three nights where every what-if using them scores C (owner 2026-09-29)
    try:
        rq = load_json(REQ, {"requests": []})
        changed = False
        for r in rq.get("requests", []):
            key = r.get("key")
            if r.get("status") != "built" or not key:
                continue
            used = [v for v in out if v["cfg"].get(key) not in (None, False, 0, [], H.CFG_BASE.get(key))]
            if not used:
                continue
            if all(v["verdict"] == "C" for v in used):
                r["c_nights"] = int(r.get("c_nights") or 0) + 1
            else:
                r["c_nights"] = 0
            if r["c_nights"] >= 3:
                r["status"] = "retired"; r["retired"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                say(f"dial {key} retired after 3 nights of C")
            changed = True
        if changed:
            save_json(REQ, rq)
    except Exception as e:
        say(f"requests lifecycle: {e}")
    counts = {}
    for r in out:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    save_json(AUTO, {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "symbol": sym,
                     "days": round(len(R) / 1440, 1), "base": base, "variants": out, "counts": counts,
                     "days_long": (round(len(RL) / 1440) if RL is not None else None), "base_long": baseL,
                     "base_real": baseT, "real_n": (len(T) if T else 0),
                     "minutes": round((time.time() - t0) / 60, 1)})
    say(f"researcher done: {len(out)} what-ifs in {(time.time()-t0)/60:.1f} min - {counts}")


if __name__ == "__main__":
    main()
