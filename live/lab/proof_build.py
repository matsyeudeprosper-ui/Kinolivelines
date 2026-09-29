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


def accounts():
    """Each journal: account, name, package, trades, money, win rate, since."""
    try:
        us = {u["id"]: u for u in json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8"))}
    except Exception:
        us = {}
    try:
        sys.path.insert(0, LIVE)
        import owl_app_server as S
        pkg_of = lambda uid: (S.PKG.for_account(uid) or {}).get("package")
    except Exception:
        pkg_of = lambda uid: None
    out = []
    for f in sorted(glob.glob(os.path.join(LIVE, "bos_journal*.csv"))):
        try:
            rows = list(csv.DictReader(open(f, encoding="utf-8", errors="replace")))
        except Exception:
            continue
        closed = [r for r in rows if r.get("exit_time_utc")]
        if not closed:
            continue
        uid = closed[0].get("account")
        base = [r for r in closed if r.get("is_add") != "True"]
        pn = [{"pnl": float(r.get("profit_usd") or 0)} for r in base]
        net_all = round(sum(float(r.get("profit_usd") or 0) for r in closed), 2)
        lot = sorted(float(r.get("lot") or 0) for r in base)[len(base) // 2] if base else None
        out.append({"uid": uid, "name": (us.get(uid) or {}).get("name") or uid, "demo": uid == "demo",
                    "trades": len(base), "adds": len(closed) - len(base), "net": net_all,
                    "net_base": round(sum(x["pnl"] for x in pn), 2), "wr": _wr(pn), "lot": lot,
                    "since": min([r["entry_time_utc"][:10] for r in closed if r.get("entry_time_utc")] or [""]),
                    "package": pkg_of(uid)})
    return out


def main():
    t0 = time.time()
    sym, R = H.bars()
    base = H.run_cfg(R, 7.0, {})
    _, RL = H.bars_long()
    base_long = H.run_cfg(RL, 7.0, {}) if RL is not None and len(RL) > len(R) + 7 * 1440 else None
    T = H.real_entries()
    real_replay = H.simulate_real(T, R, 7.0, {}) if T else None
    acc = accounts()
    since = min([a["since"] for a in acc if not a["demo"] and a["since"]] or [None])
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
        union = {"trades": len(T), "net": round(sum(x["pnl"] for x in T), 2), "wr": _wr(pn), "since": time.strftime("%Y-%m-%d", time.gmtime(T[0]["t"])),
                 "replay_same_entries": real_replay}
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
           "base_long": base_long, "expected": expected, "accounts": acc, "union": union, "rules": rules,
           "seconds": round(time.time() - t0, 1)}
    tmp = OUT + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))
    os.replace(tmp, OUT)
    print(f"proof: 42d net {base['full']['net']:+.2f} ({base['full']['trades']} trades, wr {base['full']['wr']}%), "
          f"long {(base_long or {}).get('full', {}).get('net')}, expected since {since}: {expected and expected['net']}, "
          f"real union {union and union['net']} ({union and union['trades']}), accounts {len(acc)}, {out['seconds']} s")


if __name__ == "__main__":
    main()
