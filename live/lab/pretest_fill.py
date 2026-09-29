"""Give every pending proposal its pre-test numbers (lab/proposals.json ->
`pretest`), so the lab card can show tiles instead of prose. Runs the same
harness the nightly battery uses: the 42-day window (the verdict), the
long window and the real trades (two more views, owner 2026-09-29).
Idempotent: a proposal that already has `pretest` is left alone unless
--redo."""
import io, json, os, sys, datetime as dt
_ARGS = list(sys.argv[1:])          # harness rewrites sys.argv on import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H

LAB = os.path.dirname(os.path.abspath(__file__))
PF = os.path.join(LAB, "proposals.json")


def main():
    redo = "--redo" in _ARGS
    j = json.load(io.open(PF, encoding="utf-8"))
    todo = [p for p in j.get("proposals", []) if (p.get("status") in (None, "pending")) and (redo or not p.get("pretest"))]
    if not todo:
        print("nothing to fill")
        return
    sym, R = H.bars()
    base = H.run_cfg(R, 7.0, {})
    _, RL = H.bars_long()
    baseL = H.run_cfg(RL, 7.0, {}) if (RL is not None and len(RL) >= len(R) + 7 * 1440) else None
    T = H.real_entries()
    baseT = H.simulate_real(T, R, 7.0, {}) if T else None
    for p in todo:
        cfg = H.cfg_of(p.get("cfg") or {})
        v = H.run_cfg(R, 7.0, cfg)
        pt = {"net": v["full"]["net"], "worst": v["full"]["worst_debt"],
              "h1": v["h1"]["net"], "h2": v["h2"]["net"],
              "base_net": base["full"]["net"], "base_worst": base["full"]["worst_debt"],
              "base_h1": base["h1"]["net"], "base_h2": base["h2"]["net"],
              "verdict": H.verdict(v, base), "trades": v["full"]["trades"],
              "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
        if baseL:
            vL = H.run_cfg(RL, 7.0, cfg)
            pt["long"] = {"days": round(len(RL) / 1440), "verdict": H.verdict(vL, baseL),
                          "diff_net": round(vL["full"]["net"] - baseL["full"]["net"], 2),
                          "diff_worst": round(vL["full"]["worst_debt"] - baseL["full"]["worst_debt"], 2)}
        if baseT:
            vT = H.simulate_real(T, R, 7.0, cfg)
            pt["real"] = {"n_real": len(T), "trades": vT["trades"], "diff_net": round(vT["net"] - baseT["net"], 2),
                          "diff_worst": round(vT["worst_debt"] - baseT["worst_debt"], 2)}
        p["pretest"] = pt
        print(p["id"], pt["verdict"], "net", v["full"]["net"], "vs", base["full"]["net"],
              "| long", (pt.get("long") or {}).get("verdict"), (pt.get("long") or {}).get("diff_net"),
              "| real", (pt.get("real") or {}).get("diff_net"), "n", (pt.get("real") or {}).get("n_real"))
    io.open(PF, "w", encoding="utf-8").write(json.dumps(j, ensure_ascii=False, indent=1))
    print("filled", len(todo))


if __name__ == "__main__":
    main()
