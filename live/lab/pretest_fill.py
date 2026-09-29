"""Give every pending proposal its pre-test numbers (lab/proposals.json ->
`pretest`), so the lab card can show tiles instead of prose. Runs the same
harness the nightly battery uses; ~1 s per proposal. Idempotent: a
proposal that already has `pretest` is left alone unless --redo."""
import io, json, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H

LAB = os.path.dirname(os.path.abspath(__file__))
PF = os.path.join(LAB, "proposals.json")


def main():
    redo = "--redo" in sys.argv
    j = json.load(io.open(PF, encoding="utf-8"))
    todo = [p for p in j.get("proposals", []) if (p.get("status") in (None, "pending")) and (redo or not p.get("pretest"))]
    if not todo:
        print("nothing to fill")
        return
    sym, R = H.bars()
    base = H.run_cfg(R, 7.0, {})
    for p in todo:
        v = H.run_cfg(R, 7.0, H.cfg_of(p.get("cfg") or {}))
        p["pretest"] = {"net": v["full"]["net"], "worst": v["full"]["worst_debt"],
                        "h1": v["h1"]["net"], "h2": v["h2"]["net"],
                        "base_net": base["full"]["net"], "base_worst": base["full"]["worst_debt"],
                        "base_h1": base["h1"]["net"], "base_h2": base["h2"]["net"],
                        "verdict": H.verdict(v, base), "trades": v["full"]["trades"],
                        "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
        print(p["id"], p["pretest"]["verdict"], "net", v["full"]["net"], "vs", base["full"]["net"],
              "worst", v["full"]["worst_debt"], "vs", base["full"]["worst_debt"])
    io.open(PF, "w", encoding="utf-8").write(json.dumps(j, ensure_ascii=False, indent=1))
    print("filled", len(todo))


if __name__ == "__main__":
    main()
