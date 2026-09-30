"""La preuve (2026-09-29, owner): the numbers behind the proof page, built
once a night (and on demand) into lab/proof.json so the app server never
touches MT5 itself.

  1. the robot as it is today, replayed on the last 42 days and on the
     long window: money, hole, trades, win rate, daily curve
  2. the real trades since the journals began, per account and all
     together, against what the replay expected over the same dates and
     against the replay of the exact same entries
  3. the dates the rules entered the robot (from lab/registry.json)

    python lab/proof_build.py
"""
import csv
import glob
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
sys.path.insert(0, LIVE)
sys.path.insert(0, LAB)
import harness as H  # noqa: E402

OUT = os.path.join(LAB, "proof.json")


def _wr(rows):
    w = sum(1 for r in rows if r["pnl"] > 0)
    return round(100 * w / len(rows)) if rows else None


def _journal(f):
    try:
        rows = list(csv.DictReader(open(os.path.join(LIVE, f), encoding="utf-8", errors="replace")))
    except Exception:
        return None
    closed = [r for r in rows if r.get("exit_time_utc")]
    if not closed:
        return None
    base = [r for r in closed if r.get("is_add") != "True"]
    pn = [{"pnl": float(r.get("profit_usd") or 0)} for r in base]
    return {"trades": len(base), "adds": len(closed) - len(base),
            "net": round(sum(float(r.get("profit_usd") or 0) for r in closed), 2),
            "wr": _wr(pn), "since": min([r["entry_time_utc"][:10] for r in closed if r.get("entry_time_utc")] or [""])}


def sources():
    """The clean sources, without names (owner 2026-09-29: never list the
    accounts we host): how many real accounts feed the numbers, the demo
    account on its own, and the earliest date."""
    real = [j for j in (_journal(f) for f in H.REAL_SOURCES) if j]
    demo = _journal("bos_journal_demo.csv")
    since = min([j["since"] for j in real if j["since"]] or [""])
    return {"real_accounts": len(real), "demo": demo, "since": since or None}


def rule_change(T):
    """The honest note about a rule that ran live but was never in the test.

    Lives here, and is called by BOTH writers - proof_build at night and
    proof_refresh every hour. It used to be computed inline in main(), so
    the hourly refresh rebuilt `sources` without it and the note vanished
    from the page within the hour (found by review/ui_smoke.mjs).
    """
    ints = [x for x in (T or []) if x.get("internal")]
    return {"what": "internal", "off_since": "2026-09-30",
            "live_trades": len(ints),
            "live_net": round(sum(x.get("pnl") or 0.0 for x in ints), 2),
            "of_total": len(T or []), "in_backtest": False}


def clean_union(T):
    """the same forward record WITHOUT the retired rule, or None when the
    two are identical"""
    t2 = [x for x in (T or []) if not x.get("internal")]
    if not T or len(t2) == len(T):
        return None
    return {"trades": len(t2),
            "net": round(sum(x["pnl"] for x in t2), 2),
            "wr": _wr([{"pnl": x["pnl"]} for x in t2])}


def main():
    t0 = time.time()
    sym, R = H.bars()
    # 2026-09-29 (owner): the test now runs with each account's OWN rules.
    # The generic run stays as `base` for anything that has no package.
    base = H.run_cfg(R, 7.0, H.package_cfg("base"))
    # 2026-09-29 (owner): "each account may not have the same balance, so not
    # the same risk". The live bot resizes the lot AND the daily cap by
    # balance / 200, so every account is a different test. One run per account.
    import math
    packages = {}
    try:
        sys.path.insert(0, LIVE)
        import owl_app_server as S
        us = json.load(io.open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8"))
    except Exception:
        us = []
    for u in us:
        uid = u.get("id")
        try:
            bal = float(json.load(io.open(os.path.join(LIVE, "nest_data", uid + ".json"), encoding="utf-8")).get("balance") or 0)
        except Exception:
            bal = 0.0
        if bal <= 0:
            continue
        try:
            pk = (S.PKG.for_account(uid) or {}).get("package") or "base"
            cfg = H.package_cfg(pk, {"balance": bal})
            ratio = bal / cfg["scale_ref"] if cfg["scale_ref"] else 1.0
            v = H.run_cfg(R, 7.0, cfg)
            packages[uid] = {"full": v["full"], "h1": v["h1"], "h2": v["h2"],
                             "day_cap": round(cfg["day_cap"] * ratio, 2), "jar": cfg["jar"],
                             "kill_net": cfg["kill_net"], "balance": round(bal, 2),
                             "lot": max(0.01, math.floor((cfg["lot"] * ratio) / 0.01) * 0.01)}
        except Exception as e:
            print("account", uid, "failed:", e)
    for pk in ("base", "valere"):
        try:
            cfg = H.package_cfg(pk)
            v = H.run_cfg(R, 7.0, cfg)
            packages[pk] = {"full": v["full"], "h1": v["h1"], "h2": v["h2"],
                            "day_cap": cfg["day_cap"], "jar": cfg["jar"], "kill_net": cfg["kill_net"],
                            "lot": cfg["lot"]}
        except Exception as e:
            print("package", pk, "failed:", e)
    _, RL = H.bars_long()
    base_long = H.run_cfg(RL, 7.0, {}) if RL is not None and len(RL) > len(R) + 7 * 1440 else None
    T = H.real_entries()
    # 2026-09-30: honesty block. Until today the bot took
    # internal-structure entries and this test never modelled one, so
    # the backtest and the live record were not the same strategy.
    # The rule is off now (owl_package internal_entries=False) and the
    # two match from here. The trades that already happened are NOT
    # deleted - they really cost that money - they are labelled.
    _rc = rule_change(T)
    real_replay = H.simulate_real(T, R, 7.0, {}) if T else None
    src = sources()
    src["rule_change"] = _rc
    since = src.get("since")
    # what the replay expected over the same dates (lot 0.02, the replay's lot)
    expected = None
    curve = base["full"].get("curve") or []
    if since and curve:
        start = next((v for d, v in curve if d >= since), None)
        if start is not None:
            expected = {"since": since, "net": round(curve[-1][1] - start, 2), "lot": H.CFG_BASE["lot"],
                        "days": max(1, (datetime.now(timezone.utc) - datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)).days)}
    union = None
    if T:
        pn = [{"pnl": x["pnl"]} for x in T]
        # 2026-09-30: the same record WITHOUT the rule that no longer
        # exists. The headline win rate was being compared against a
        # test that never contained internal entries, so the two were
        # not measuring the same robot. Both are published; the page
        # shows the clean one beside it rather than instead of it.

        union = {"trades": len(T), "net": round(sum(x["pnl"] for x in T), 2), "wr": _wr(pn), "since": time.strftime("%Y-%m-%d", time.gmtime(T[0]["t"])),
                 "replay_same_entries": real_replay,
                 "clean": clean_union(T)}
    rules = []
    try:
        reg = json.load(open(os.path.join(LAB, "registry.json"), encoding="utf-8"))
        for it in reg.get("items", []):
            if it.get("status") == "deployed":
                rules.append({"id": it["id"], "date": it.get("date"), "title_fr": it.get("title_fr"), "title_en": it.get("title_en"),
                              "verdict": it.get("verdict")})
        rules.sort(key=lambda x: x.get("date") or "")
    except Exception:
        pass
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "symbol": sym,
           "days": round(len(R) / 1440, 1), "base": base, "days_long": (round(len(RL) / 1440) if RL is not None else None),
           "base_long": base_long, "expected": expected, "sources": src, "union": union, "rules": rules,
           "packages": packages, "seconds": round(time.time() - t0, 1)}
    tmp = OUT + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))
    os.replace(tmp, OUT)
    print(f"proof: 42d net {base['full']['net']:+.2f} ({base['full']['trades']} trades, wr {base['full']['wr']}%), "
          f"long {(base_long or {}).get('full', {}).get('net')}, expected since {since}: {expected and expected['net']}, "
          f"real union {union and union['net']} ({union and union['trades']}), sources {src['real_accounts']} real + demo, {out['seconds']} s")


if __name__ == "__main__":
    main()
