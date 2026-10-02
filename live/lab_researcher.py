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
ARCH = os.path.join(LAB, "archive.json")
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
    ("bul2", "Deux trades de rattrapage au lieu de trois après une perte", "Two catch-up trades instead of three after a loss", "argent", {"bullets": 2}),
    ("bul4", "Quatre trades de rattrapage au lieu de trois après une perte", "Four catch-up trades instead of three after a loss", "argent", {"bullets": 4}),
    ("bul0", "Aucun trade de rattrapage après une perte", "No catch-up trade after a loss", "argent", {"bullets": 0}),
    ("k1", "Se rattraper une seule fois, puis attendre un gain", "Catch up once, then wait for a win", "argent", {"k_streak": 1}),
    ("k3", "Se rattraper jusqu’à trois pertes de suite", "Keep catching up until three losses in a row", "argent", {"k_streak": 3}),
    # 2026-09-30: the per-trade risk ceiling (review/RISK_CAP.md). It
    # SHRINKS the lot to fit and only refuses when even 0.01 would
    # exceed the cap - refusing outright costs about twice as much,
    # because the widest stops are the best trades (E009). Measured once
    # over two months, the cost came out somewhere between nothing and
    # 9% and the two halves disagreed, so it is in the battery to be
    # RE-MEASURED as the sample grows, not because it is settled.
    ("fit3", "Ne jamais risquer plus de 3 % du compte sur un trade",
     "Never risk more than 3% of the account on one trade", "argent",
     {"risk_fit": 3.0}),
    ("fit5", "Ne jamais risquer plus de 5 % du compte sur un trade",
     "Never risk more than 5% of the account on one trade", "argent",
     {"risk_fit": 5.0}),
    ("fit8", "Ne jamais risquer plus de 8 % du compte sur un trade",
     "Never risk more than 8% of the account on one trade", "argent",
     {"risk_fit": 8.0}),
    # NOT in the battery, on purpose: `internal` (and with it
    # int_max_stop / int_tighter). Internal-structure entries were
    # measured on 2026-09-30 and were worse in EVERY split on two
    # accounts - review/INTERNAL_BOS.md - and no stop guard rescued them
    # - review/INTERNAL_WIDESTOP.md. They are switched off live. Running
    # a proven loser 34 times a night only gives noise more chances to
    # produce a false A, which is the same reason cost_max and friends
    # are kept out above. The chercheur can still propose it if it ever
    # has a reason.
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


def latest_critique(vid):
    """The critic's last word on an idea (lab/critiques.json), or None."""
    mine = [c for c in load_json(os.path.join(LAB, "critiques.json"), {"critiques": []}).get("critiques", []) if c.get("id") == vid]
    mine.sort(key=lambda c: c.get("date", ""))
    return mine[-1] if mine else None


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
    # 2026-09-30: does the harness still describe the bot? This runs
    # FIRST, because a battery scored by a harness that has drifted is
    # worse than no battery - it produces confident numbers about a
    # strategy nobody is running. That is exactly what happened with
    # internal entries: the bot took them for weeks and the harness had
    # never modelled one, and nothing noticed because nothing looked.
    parity = None
    try:
        import importlib.util as _iu
        _pp = os.path.join(os.path.dirname(LIVE), 'review',
                           'bot_harness_parity.py')
        _sp = _iu.spec_from_file_location('parity', _pp)
        _pm = _iu.module_from_spec(_sp)
        _sp.loader.exec_module(_pm)
        import io as _io, contextlib as _cl
        _buf = _io.StringIO()
        with _cl.redirect_stdout(_buf):
            _rc = _pm.main()
        parity = {'drift': _rc != 0, 'report': _buf.getvalue()}
        if parity['drift']:
            say('PARITY DRIFT - the harness no longer describes the bot. '
                'Tonight''s verdicts describe a strategy that may not be '
                'the one running. Details in review/bot_harness_parity.json')
            for _l in _buf.getvalue().split(chr(10)):
                if 'DRIFT' in _l or 'NOT IN HARNESS' in _l:
                    say('  ' + _l.strip())
        else:
            say('parity ok: every rule the bot reads has a dial, every '
                'live trade kind can be produced, entry rates agree')
    except Exception as _e:
        say(f'parity check unavailable: {_e}')
    # 2026-09-29 (owner): one answer for a generic account is a fiction - the
    # daily cap changes it. Every what-if is judged against BOTH shapes a real
    # account has, and only counts as an A when both agree.
    REF = {}
    for _r in H.REFS:
        _c = H.package_cfg(_r, {"balance": 252.0} if _r == "valere" else {})
        REF[_r] = (_c, H.run_cfg(R, 7.0, _c))
        say(f"reference {_r}: {REF[_r][1]['full']['trades']} trades "
            f"net {REF[_r][1]['full']['net']:+.2f} worst {REF[_r][1]['full']['worst_debt']:.2f}")
    base = REF["base"][1]
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
    # a verdict from an older engine cannot vouch for tonight's: the two A's
    # rule must not be satisfied by a number we no longer believe
    if prev.get("engine") != H.ENGINE:
        say(f"previous run was engine {prev.get('engine')}, this is {H.ENGINE} - "
            "yesterday's verdicts are not counted towards a twin")
        prev = {"variants": []}
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
            byref = {}
            for _r, (_c, _b) in REF.items():
                _v = H.run_cfg(R, 7.0, H.package_cfg(_r, dict(cfg, **({"balance": 252.0} if _r == "valere" else {}))))
                byref[_r] = {"verdict": H.verdict(_v, _b),
                             "diff_net": round(_v["full"]["net"] - _b["full"]["net"], 2),
                             "diff_worst": round(_v["full"]["worst_debt"] - _b["full"]["worst_debt"], 2)}
            v = H.run_cfg(R, 7.0, H.package_cfg("base", cfg))
            vd = H.verdict(v, base)
            # an A has to hold on an account WITH the daily cap as well
            if vd == "A" and byref.get("valere", {}).get("verdict") != "A":
                vd = "B"
        except Exception as e:
            say(f"{vid}: ERROR {type(e).__name__}: {e}")
            continue
        prevv = (prev_by.get(vid) or {}).get("verdict")
        rec = {"id": vid, "title_fr": fr, "title_en": en, "family": fam, "cfg": H.cfg_of(cfg), "full": _slim(v["full"]),
               "h1": _slim(v["h1"]), "h2": _slim(v["h2"]), "verdict": vd, "prev_verdict": prevv,
               "engine": H.ENGINE, "byref": byref,
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
        # 2026-09-29 (owner): an A on ONE night is not enough to start a paper
        # copy. With 34 what-ifs a night, noise produces an A sooner or later;
        # two nights in a row costs one day and removes most false starts.
        if vd == "A" and prevv != "A":
            say(f"{vid}: A held back, waiting for a second A tomorrow")
        crit = latest_critique(vid)
        if vd == "A" and prevv == "A" and crit and crit.get("verdict") == "bloque":
            # 2026-10-02 (phase 3): a second A is not enough when the critic
            # could break it. It stays on the board with the critic's words.
            say(f"{vid}: A twice, but the critic blocked it - {(crit.get('fr') or '')[:90]}")
        elif vd == "A" and prevv == "A":
            if ensure_twin(vid, fr, en, H.cfg_of(cfg), vd):
                if crit and crit.get("verdict") == "doute":
                    try:
                        _tw = load_json(TWINS, {"twins": []})
                        for _t in _tw.get("twins", []):
                            if _t.get("id") == vid:
                                _t["critique"] = {k: crit.get(k) for k in ("date", "verdict", "fr", "en")}
                        save_json(TWINS, _tw)
                    except Exception:
                        pass
                try:
                    import twin_judge as TJ      # 2026-09-29: tell Kino + the Strategie members
                    TJ.emit("twin_started", ("\U0001f9ea Le labo : un jumeau démarre",
                                             f"« {fr} » a été mieux sur les deux moitiés cette nuit. Une copie du robot l’essaie pour de faux à partir de maintenant."),
                            ("\U0001f9ea The lab: a twin starts",
                             f"“{en}” was better on both halves tonight. A copy of the robot tries it for pretend from now on."), members=True)
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
    # 2026-09-29 (owner): "auto remove the ones no longer relevant, or archive
    # them so the chercheur stays aware". An idea leaves the board after three
    # nights of C in a row on the CURRENT engine. It keeps living in
    # lab/archive.json, which the chercheur must read before proposing.
    try:
        arch = load_json(ARCH, {"archived": {}, "engine": H.ENGINE})
        if arch.get("engine") != H.ENGINE:
            arch = {"archived": {}, "engine": H.ENGINE}   # a new engine re-opens every case
            say("engine changed: archive cleared, every idea gets a fresh hearing")
        A = arch.setdefault("archived", {})
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        protected = set()
        try:
            for it in json.load(open(os.path.join(LAB, "registry.json"), encoding="utf-8")).get("items", []):
                if it.get("status") in ("deployed", "forward", "candidate") or it.get("reference"):
                    protected.add(it["id"])
            for t in load_json(TWINS, {"twins": []}).get("twins", []):
                protected.add(t.get("id"))
        except Exception:
            pass
        for r in out:
            vid = r["id"]
            if vid in protected:
                A.pop(vid, None)
                continue
            e = A.setdefault(vid, {"c": 0, "title_fr": r["title_fr"], "title_en": r["title_en"]})
            e["title_fr"], e["title_en"] = r["title_fr"], r["title_en"]
            if r["verdict"] == "C":
                e["c"] = int(e.get("c") or 0) + 1
                if e["c"] >= 3 and not e.get("since"):
                    e["since"] = today
                    e["why_fr"] = f"trois nuits de suite à C ({r['diff_net']:+.0f} $ la dernière)"
                    e["why_en"] = f"three nights of C in a row ({r['diff_net']:+.0f} $ on the last one)"
                    say(f"{vid}: archived after 3 nights of C")
            else:
                if e.get("since"):
                    say(f"{vid}: back on the board, it scored {r['verdict']}")
                e["c"] = 0
                e.pop("since", None)
        save_json(ARCH, arch)
    except Exception as e:
        say(f"archive: {e}")
    counts = {}
    for r in out:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    save_json(AUTO, {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "symbol": sym,
                     "days": round(len(R) / 1440, 1), "base": base, "variants": out, "counts": counts,
                     "engine": H.ENGINE, "refs": {k: _slim(vv["full"]) for k, (cc, vv) in REF.items()},
                     "days_long": (round(len(RL) / 1440) if RL is not None else None), "base_long": baseL,
                     "base_real": baseT, "real_n": (len(T) if T else 0),
                     "minutes": round((time.time() - t0) / 60, 1),
                     "parity": parity})
    # 2026-09-30 (owner): the risk ceiling is on Depenses only, with
    # Infinity left uncapped as its control. Two accounts on the same
    # rules and the same signals, one capped - that answers in ~50
    # trades what two months of bars could not. A reminder in a commit
    # message is a reminder nobody reads, so the nightly run watches the
    # count itself and reports BOTH sides when it arrives.
    try:
        import csv as _csv

        def _tally(fn):
            n = 0
            net = 0.0
            try:
                with open(os.path.join(LIVE, fn), encoding='utf-8',
                          errors='replace') as fh:
                    for r in _csv.DictReader(fh):
                        if (r.get('is_add') or '') == 'True':
                            continue
                        try:
                            net += float(r.get('profit_usd') or '')
                        except Exception:
                            continue
                        n += 1
            except Exception:
                return None
            return n, round(net, 2)

        _cap = _tally('bos_journal_expenses.csv')
        _ctl = _tally('bos_journal_infinity.csv')
        if _cap and _ctl:
            _n = _cap[0]
            _line = (f'risk-ceiling watch: Depenses (3% cap) {_cap[0]} trades {_cap[1]:+.2f}, '
                     f'Infinity (no cap) {_ctl[0]} trades {_ctl[1]:+.2f}')
            if _n >= 50:
                say('DECISION DUE - ' + _line + ' - 50 trades reached, the pair can be compared now (review/RISK_CAP.md)')
            elif _n >= 25:
                say(_line + f' - {50 - _n} trades to go before the comparison is worth reading')
            else:
                say(_line)
    except Exception as _e:
        say(f'risk-ceiling watch unavailable: {_e}')
    say(f"researcher done: {len(out)} what-ifs in {(time.time()-t0)/60:.1f} min - {counts}")
    # 2026-09-30 (owner): the screen test, every night. It drives the
    # real pages and asserts what they PAINT, which is how the proof
    # page's honest note was caught being wiped by the hourly refresh.
    # LAST, after the battery: a browser that will not start must never
    # cost us the night's research.
    if not quick:
        try:
            import subprocess as _sp
            _out = os.path.join(LAB, 'ui_smoke')
            _r = _sp.run(['node',
                          os.path.join(os.path.dirname(LIVE), 'review',
                                       'ui_smoke.mjs'), _out],
                         capture_output=True, text=True, timeout=900)
            _txt = (_r.stdout or '') + (_r.stderr or '')
            _last = [l for l in _txt.split(chr(10))
                     if l.startswith('UI SMOKE:')]
            if _r.returncode == 0:
                say('screen test ok - ' + (_last[-1] if _last else 'passed'))
            else:
                say('SCREEN TEST FAILED - something the app draws is not what it should be:')
                for _l in _txt.split(chr(10)):
                    if 'FAIL' in _l:
                        say('  ' + _l.strip())
        except Exception as _e:
            say(f'screen test unavailable: {_e}')


if __name__ == "__main__":
    main()
