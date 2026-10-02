"""The chercheur's eyes (owner 2026-10-02: "eyes wide open ... the system
provides him with the tools").

Read-only. Answers questions about the REAL trades without anyone writing
code: win rate, profit factor, expectancy, biggest hole, trades a day, by
any fact a trade carries, for every pile, for loss streaks and for the
money management. Every number here comes from the bot journals, the same
rows the Labo counts, each entry counted once across accounts (the
accounts take the same entries) - adds are reported on their own.

    python lab/scrutiny.py                      # the overview
    python lab/scrutiny.py --by hour            # one fact: hour wday nerv kind dir gap dur prev
                                                #   dist trend dayn debt storm htf move shape
    python lab/scrutiny.py --by nerv --by prev  # several facts
    python lab/scrutiny.py --pile weekend       # a pile from lab/cuts.json, profiled
    python lab/scrutiny.py --streaks            # runs of losses and what followed
    python lab/scrutiny.py --mm                 # the money: lots, adds, debt, balance path
    python lab/scrutiny.py --all                # everything
    python lab/scrutiny.py --json ...           # machine form of the same
    python lab/scrutiny.py --write              # lab/metrics.json, the nightly ledger

Under 30 trades a line means little; the tables say n so you can tell.
"""
import csv
import glob
import io
import json
import os
import sys
import time
from datetime import datetime

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
sys.path.insert(0, LIVE)
sys.path.insert(0, LAB)
A = sys.argv[1:]
sys.argv = ["scrutiny"]
import owl_package as PK            # noqa: E402

MIN_N = 30
UID_OF = {"valere": "u224016179", "": "bos"}


def _f(x, d=None):
    try:
        return float(x)
    except Exception:
        return d


def load():
    """Every closed main trade once (same minute + direction = same entry),
    plus the adds, with the account shape each row came from."""
    seen, adds = {}, []
    for f in sorted(glob.glob(os.path.join(LIVE, "bos_journal*.csv"))):
        tag = os.path.basename(f)[len("bos_journal"):-4].lstrip("_")
        uid = UID_OF.get(tag, tag)
        try:
            pk = PK.for_account(uid)
            capped = pk.get("day_cap") is not None
        except Exception:
            capped = None
        try:
            rows = list(csv.DictReader(open(f, encoding="utf-8", errors="replace")))
        except Exception:
            continue
        for r in rows:
            o = (r.get("outcome") or "").lower()
            if o not in ("win", "loss"):
                continue
            try:
                et = datetime.fromisoformat(r["entry_time_utc"]).timestamp()
                xt = datetime.fromisoformat(r["exit_time_utc"]).timestamp() if r.get("exit_time_utc") else et
            except Exception:
                continue
            row = {"t": et, "x": xt, "win": o == "win", "p": _f(r.get("profit_usd"), 0.0), "lot": _f(r.get("lot"), 0.02),
                   "nerv": _f(r.get("nervosity")), "kind": r.get("kind") or "", "internal": r.get("internal") == "True",
                   "dir": (r.get("direction") or "").upper(), "dist": _f(r.get("dist_pts")), "trend": r.get("trend") or "",
                   "dayn": _f(r.get("day_n_at_entry")), "debt": _f(r.get("debt_at_entry"), 0.0), "bal": _f(r.get("balance_at_entry")),
                   "storm": r.get("storm") or "", "dur": _f(r.get("duration_min")), "htf": r.get("htf_entry") or "",
                   "move": _f(r.get("movement_count")), "acct": tag or "bos", "capped": capped}
            if r.get("is_add") == "True":
                adds.append(row)
                continue
            k = (r["entry_time_utc"][:16], row["dir"])
            if k in seen:
                continue
            seen[k] = row
    J = sorted(seen.values(), key=lambda x: x["t"])
    for i, r in enumerate(J):
        g = time.gmtime(r["t"])
        r["hour"], r["wday"] = g.tm_hour, g.tm_wday
        r["gap_min"] = ((r["t"] - J[i - 1]["x"]) / 60.0) if i else None
        r["prev_win"] = J[i - 1]["win"] if i else None
        if r["dur"] is None:
            r["dur"] = max(0.0, (r["x"] - r["t"]) / 60.0)
    return J, sorted(adds, key=lambda x: x["t"])


def stats(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    wins = [r["p"] for r in rows if r["win"]]
    loss = [r["p"] for r in rows if not r["win"]]
    gw, gl = sum(wins), -sum(loss)
    cum = pk = worst = 0.0
    for r in sorted(rows, key=lambda x: x["t"]):
        cum += r["p"]; pk = max(pk, cum); worst = max(worst, pk - cum)
    days = max(1.0, (rows[-1]["t"] - rows[0]["t"]) / 86400.0) if n > 1 else 1.0
    return {"n": n, "win": round(100.0 * len(wins) / n), "net": round(cum, 2),
            "pf": (round(gw / gl, 2) if gl > 0 else None), "exp": round(cum / n, 2),
            "avg_win": (round(gw / len(wins), 2) if wins else None), "avg_loss": (round(-gl / len(loss), 2) if loss else None),
            "worst": round(worst, 2), "per_day": round(n / days, 2)}


def halves(rows, mid):
    a = [r for r in rows if r["t"] < mid]; b = [r for r in rows if r["t"] >= mid]
    sa, sb = stats(a), stats(b)
    return {"h1": sa.get("win"), "h1n": sa["n"], "h2": sb.get("win"), "h2n": sb["n"],
            "agree": (sa["n"] >= 5 and sb["n"] >= 5 and sa.get("net", 0) > 0) == (sb.get("net", 0) > 0) if (sa["n"] >= 5 and sb["n"] >= 5) else None}


def band(v, edges, labels):
    if v is None:
        return "?"
    for e, l in zip(edges, labels):
        if v < e:
            return l
    return labels[-1]


FACTS = {
    "hour": lambda r: "%02d h" % r["hour"],
    "wday": lambda r: ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"][r["wday"]],
    "nerv": lambda r: band(r["nerv"], [0.8, 1.0, 1.3, 1.85], ["< 0,8 calme", "0,8-1,0", "1,0-1,3 nerveux", "1,3-1,85", ">= 1,85 orage"]),
    "kind": lambda r: r["kind"] or "?",
    "dir": lambda r: r["dir"] or "?",
    "gap": lambda r: band(r["gap_min"], [15, 30, 60, 180], ["< 15 min", "15-30", "30-60", "1-3 h", "> 3 h"]),
    "dur": lambda r: band(r["dur"], [15, 30, 60, 180], ["< 15 min", "15-30", "30-60", "1-3 h", "> 3 h"]),
    "prev": lambda r: {True: "apres un gain", False: "apres une perte", None: "premier"}[r["prev_win"]],
    "dist": lambda r: band(r["dist"], [100, 150, 250, 400], ["< 100 pts", "100-150", "150-250", "250-400", ">= 400"]),
    "trend": lambda r: r["trend"] or "?",
    "dayn": lambda r: band(r["dayn"], [2, 3, 5], ["1er du jour", "2e", "3e-4e", "5e et +"]),
    "debt": lambda r: "dans le rouge" if (r["debt"] or 0) > 0.5 else "a flot",
    "storm": lambda r: r["storm"] or "non",
    "htf": lambda r: r["htf"] or "?",
    "move": lambda r: band(r["move"], [1, 2, 4], ["0", "1", "2-3", "4 et +"]),
    "shape": lambda r: {True: "avec plafond", False: "sans plafond", None: "?"}[r["capped"]],
    "acct": lambda r: "compte " + r["acct"],
}
ORDER = {"wday": ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]}


def by(J, fact):
    f = FACTS[fact]
    mid = J[len(J) // 2]["t"] if J else 0
    groups = {}
    for r in J:
        groups.setdefault(f(r), []).append(r)
    keys = sorted(groups, key=lambda k: (ORDER.get(fact, []).index(k) if k in ORDER.get(fact, []) else 99, k))
    out = []
    for k in keys:
        rows = groups[k]; rest = [r for r in J if r not in rows]
        s = stats(rows); s["group"] = k; s["rest_win"] = stats(rest).get("win"); s.update(halves(rows, mid))
        out.append(s)
    return out


def streaks(J):
    runs, cur, after = [], 0, {}
    for i, r in enumerate(J):
        if not r["win"]:
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 0
        if i and cur == 0 and not J[i - 1]["win"]:
            pass
    if cur:
        runs.append(cur)
    # what the NEXT trade did after k losses in a row
    k = 0
    for i, r in enumerate(J):
        if i:
            if k:
                after.setdefault(k, []).append(r)
        k = 0 if r["win"] else k + 1
    dist = {}
    for x in runs:
        dist[x] = dist.get(x, 0) + 1
    return {"runs": dict(sorted(dist.items())), "longest": max(runs) if runs else 0,
            "after": {str(k): dict(stats(v), label=f"le trade apres {k} perte(s) de suite") for k, v in sorted(after.items())}}


def mm(J, adds):
    lots = {}
    for r in J:
        lots[r["lot"]] = lots.get(r["lot"], 0) + 1
    red = [r for r in J if (r["debt"] or 0) > 0.5]
    bal = [r["bal"] for r in J if r["bal"] is not None]
    return {"main": stats(J), "adds": dict(stats(adds), note="les trades de rattrapage, a part"),
            "lots": {str(k): v for k, v in sorted(lots.items())},
            "in_the_red": dict(stats(red), share=round(100.0 * len(red) / len(J)) if J else 0),
            "afloat": stats([r for r in J if (r["debt"] or 0) <= 0.5]),
            "balance_first_last": [bal[0], bal[-1]] if bal else None,
            "by_shape": by(J, "shape")}


def table(rows, title):
    print(f"\n== {title}")
    print("   %-18s %4s %5s %6s %8s %7s %8s %8s %7s  %s" % ("groupe", "n", "gagn", "autres", "net", "PF", "gain moy", "perte moy", "trou", "moities"))
    for s in rows:
        if s["n"] == 0:
            continue
        hv = ("%s%% / %s%% (%d/%d)%s" % (s.get("h1"), s.get("h2"), s.get("h1n", 0), s.get("h2n", 0),
                                         {True: " ok", False: " pas d'accord", None: ""}[s.get("agree")])) if "h1" in s else ""
        print("   %-18s %4d %4s%% %5s%% %+8.2f %7s %8s %8s %7.2f  %s%s" % (
            s["group"][:18], s["n"], s.get("win"), s.get("rest_win"), s.get("net", 0), s.get("pf"), s.get("avg_win"), s.get("avg_loss"),
            s.get("worst", 0), hv, "" if s["n"] >= MIN_N else "  (peu)"))


def main():
    J, adds = load()
    want_json = "--json" in A
    out = {"updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "trades": len(J), "adds": len(adds),
           "since": datetime.utcfromtimestamp(J[0]["t"]).strftime("%Y-%m-%d") if J else None}
    facts = [A[i + 1] for i, a in enumerate(A) if a == "--by" and i + 1 < len(A)]
    piles = [A[i + 1] for i, a in enumerate(A) if a == "--pile" and i + 1 < len(A)]
    everything = "--all" in A or "--write" in A
    if not (facts or piles or "--streaks" in A or "--mm" in A) or everything:
        out["overview"] = stats(J)
        out["overview"]["by_shape"] = by(J, "shape")
    if everything:
        facts = [f for f in FACTS if f != "acct"]
    out["by"] = {f: by(J, f) for f in facts if f in FACTS}
    bad = [f for f in facts if f not in FACTS]
    if bad:
        print("facts inconnus:", bad, "| possibles:", ", ".join(FACTS))
    if piles or everything:
        import owl_app_server as S
        cuts = {c["id"]: c for c in S.lab_cuts() if c.get("status", "open") != "retired"}
        out["piles"] = {}
        for pid in (piles or list(cuts)):
            c = cuts.get(pid)
            if not c or S.cut_error(c):
                out["piles"][pid] = {"error": "pile inconnue ou mal ecrite"}
                continue
            mid = J[len(J) // 2]["t"] if J else 0
            rows = [r for r in J if S._cut_match(c["where"], r)]
            prof = dict(stats(rows), title_fr=c.get("title_fr"), why_fr=c.get("why_fr", ""), by=c.get("by"))
            prof.update(halves(rows, mid))
            prof["rest"] = stats([r for r in J if r not in rows])
            prof["inside"] = {f: by(rows, f) for f in ("nerv", "prev", "hour", "dur")} if len(rows) >= 10 else {}
            out["piles"][pid] = prof
    if "--streaks" in A or everything:
        out["streaks"] = streaks(J)
    if "--mm" in A or everything:
        out["mm"] = mm(J, adds)
    if "--write" in A:
        p = os.path.join(LAB, "metrics.json")
        tmp = p + ".tmp"
        io.open(tmp, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
        os.replace(tmp, p)
        print("lab/metrics.json written:", len(J), "trades,", len(adds), "adds,", len(out.get("by", {})), "facts,", len(out.get("piles", {})), "piles")
        return
    if want_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if "overview" in out:
        o = out["overview"]
        print(f"VRAIS TRADES depuis {out['since']} : {o['n']} trades, {o.get('win')} % gagnes, net {o.get('net'):+.2f} $, "
              f"PF {o.get('pf')}, {o.get('exp'):+.2f} $ par trade, gain moyen {o.get('avg_win')}, perte moyenne {o.get('avg_loss')}, "
              f"plus gros trou {o.get('worst')}, {o.get('per_day')} trades/jour ; {len(adds)} trades de rattrapage a part")
    for f, rows in out["by"].items():
        table(rows, "par " + f)
    for pid, pr in out.get("piles", {}).items():
        if "error" in pr:
            print(f"\n== pile {pid}: {pr['error']}")
            continue
        print(f"\n== pile {pid} - {pr.get('title_fr')} ({pr.get('by')})")
        print(f"   {pr['n']} trades, {pr.get('win')} % gagnes contre {pr['rest'].get('win')} % pour les autres, net {pr.get('net', 0):+.2f} $, PF {pr.get('pf')}, "
              f"trou {pr.get('worst')}, moities {pr.get('h1')} % / {pr.get('h2')} % ({pr.get('h1n')}/{pr.get('h2n')})")
        if pr.get("why_fr"):
            print("   pourquoi :", pr["why_fr"])
        for f, rows in pr.get("inside", {}).items():
            table(rows, f"dans la pile, par {f}")
    if "streaks" in out:
        s = out["streaks"]
        print(f"\n== series de pertes : {s['runs']} (la plus longue : {s['longest']})")
        table([dict(v, group=v["label"]) for v in s["after"].values()], "le trade qui suit k pertes de suite")
    if "mm" in out:
        m = out["mm"]
        print("\n== l'argent")
        print("   trades principaux :", m["main"])
        print("   rattrapages       :", {k: v for k, v in m["adds"].items() if k != "note"})
        print("   lots utilises     :", m["lots"], "| solde premier/dernier :", m["balance_first_last"])
        print("   dans le rouge     :", m["in_the_red"])
        print("   a flot            :", m["afloat"])
        table(m["by_shape"], "par forme de compte")


if __name__ == "__main__":
    main()
