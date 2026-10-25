"""publish_proof.py - the latest test-vs-reality check, in the form the Tests page shows (2026-10-25).

    python study/botsim/publish_proof.py harness study/live_vs_engine/valere_trades_match.json valere
    python study/botsim/publish_proof.py botsim <sim log> valere <start ISO> <end ISO>
-> live/lab/backtest_proof.json. Honest by construction: the page prints these numbers as they are; "verified" only
when every compared trade is the same trade with the same result and the money is within 1 % of the real money.
"""
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LIVE = os.path.join(ROOT, "live")
OUT = os.path.join(LIVE, "lab", "backtest_proof.json")
NAMES = {"valere": ("Valère", "vrai compte, argent réel, jamais touché à la main depuis son ouverture")}


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def real_money(acct, a, b):
    m_ = ad = 0.0
    for ln in open(os.path.join(LIVE, "bos_bot_%s.log" % acct), encoding="utf-8", errors="replace"):
        m = re.match(r"(\S+) (WIN|LOSS|ADD) ([+-][0-9.]+) \(lot", ln)
        if m and a <= ts(m.group(1)) < b:
            if m.group(2) == "ADD":
                ad += float(m.group(3))
            else:
                m_ += float(m.group(3))
    return round(m_ + ad, 2)


def from_harness(path, acct):
    J = json.load(open(path, encoding="utf-8"))
    a, b = ts(J["summary"]["window"][0]), ts(J["summary"]["window"][1])
    rows = []
    for x in J["rows"]:
        r, e = x["real"], x["eng"]
        rows.append({"t": int(r["t"]), "dir": r["d"], "kind": r.get("kind"), "real": None if r.get("win") is None else ("W" if r["win"] else "L"),
                     "real_pnl": r.get("pnl"), "test": None if not e else ("W" if e.get("win") else "L"),
                     "test_pnl": None if not e else round((e.get("pnl_main") or 0) + (e.get("pnl_add") or 0), 2),
                     "same": bool(e) and (r.get("win") is None or bool(e.get("win")) == bool(r.get("win")))})
    for e in J.get("engine_only") or []:
        rows.append({"t": int(e["t"]), "dir": e["d"], "kind": e.get("kind"), "real": None, "real_pnl": None, "test": "W" if e.get("win") else "L",
                     "test_pnl": round((e.get("pnl_main") or 0) + (e.get("pnl_add") or 0), 2), "same": False, "test_only": True})
    rows.sort(key=lambda z: z["t"])
    test_money = round(sum((z["test_pnl"] or 0) for z in rows), 2)
    return a, b, rows, test_money, "moteur de test (copie des règles)"


def publish(acct, a, b, rows, test_money, engine):
    real = [z for z in rows if not z.get("test_only")]
    same = sum(1 for z in real if z["test"] is not None)
    same_res = sum(1 for z in real if z["same"])
    rm = real_money(acct, a, b)
    ok = same == len(real) and same_res == len(real) and not any(z.get("test_only") for z in rows) and abs(test_money - rm) <= max(0.5, 0.01 * abs(rm))
    nm, note = NAMES.get(acct, (acct, ""))
    out = {"status": "verified" if ok else "verifying", "engine": engine, "account": nm, "account_note": note,
           "from": dt.datetime.utcfromtimestamp(a).strftime("%Y-%m-%d"), "to": dt.datetime.utcfromtimestamp(b - 1).strftime("%Y-%m-%d"),
           "real_trades": len(real), "same_trades": same, "same_result": same_res, "test_only": sum(1 for z in rows if z.get("test_only")),
           "money_real": rm, "money_test": test_money, "pct_same": round(100.0 * same_res / max(1, len(real))),
           "rows": rows, "updated": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("published", OUT, {k: out[k] for k in ("status", "real_trades", "same_trades", "same_result", "test_only", "money_real", "money_test")})


if __name__ == "__main__":
    kind = sys.argv[1]
    if kind == "harness":
        publish(sys.argv[3], *from_harness(sys.argv[2], sys.argv[3]))
    else:
        raise SystemExit("botsim mode: wired once the full real-bot replay has run (compare.py rows)")
