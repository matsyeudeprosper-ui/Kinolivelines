"""Development screens of the two entry briefs (ChatGPT, 2026-10-09), on the
manifest's package regimes with the corrected parity runner (live-order limits,
canonical reference not needed here - no Compte). Research only.

Brief A - delayed recovery MAIN (original stop and target kept):
    baseline | delayed (adverse same-bar reading) | delayed (favorable, diagnostic) |
    half-size recovery main at the original entry (attribution control, floor 0.01)
Brief B - protected-dot projected line, first touch from the trend side:
    baseline | tl (projected) | tl_h (frozen horizontal at arming, attribution control)

Dataset b (closed M1 bars), spread 7, drag 0 / 0.35 per 0.02 lot. Rows cached.
"""
import sys, json, hashlib, time, statistics
sys.argv = ["x"]
src = open(r"C:\Projects\KinoliveLines\study\manifest_runner.py", encoding="utf-8").read().split("REGIMES = [")[0]
ns = {"__file__": r"C:\Projects\KinoliveLines\study\manifest_runner.py"}; exec(src, ns)
H, man, R, META, effective_cfg, dd_of = ns["H"], ns["man"], ns["R"], ns["META"], ns["effective_cfg"], ns["dd_of"]
H.DIRGATE = None
PR = man["arms"]["baseline"]["package_regimes"]
T0 = int(R["time"][0]); T1 = int(R["time"][-1]) + 60; TMID = (T0 + T1) // 2
REGIMES = [("infinity", "valere", 175.70), ("u224016179", "valere_cap3", 267.42), ("bos", "special_10", 360.37), ("reference_uncapped", "reference", 1000.0)]
ARMS = [("baseline", {}, None), ("delayed_adverse", {"delay_main_mid": 1, "delay_order": "adverse"}, None),
        ("delayed_favorable", {"delay_main_mid": 1, "delay_order": "favorable"}, None), ("half_main_in_debt", {}, 0.5),
        ("tl_projected", {"entry_mode": "tl"}, None), ("tl_horizontal", {"entry_mode": "tl_h"}, None)]


def _h(path): return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]
KEY = ":".join([META["sha256"][:16], _h(r"C:\Projects\KinoliveLines\live\lab\harness.py"), hashlib.sha256(src.encode()).hexdigest()[:16],
                _h(r"C:\Projects\KinoliveLines\live\structure_bos_bot.py"), hashlib.sha256(json.dumps(ARMS, sort_keys=True, default=str).encode()).hexdigest()[:8], "spread7"])
ROWS = r"C:\Projects\KinoliveLines\study\entry_screens_rows.json"
try:
    cache = json.load(open(ROWS)); cache = cache if cache.get("key") == KEY else {"key": KEY, "rows": {}}
except Exception:
    cache = {"key": KEY, "rows": {}}


def run(cfg, debt_mult):
    H.DEBT_MAIN_MULT = debt_mult; H.TRACE = []
    f = H.simulate(R, 7.0, cfg); tr = [x for x in H.TRACE if x.get("pnl") is not None and x.get("tc")]; setups = [x for x in H.TRACE if x.get("delayed_setup")]
    H.TRACE = None; H.DEBT_MAIN_MULT = None
    return f, sorted(tr, key=lambda x: x["tc"]), setups


def metrics(f, tr, setups):
    main = sum(x.get("pnl_main", x["pnl"]) for x in tr); add = sum(x.get("pnl_add", 0.0) for x in tr)
    lots = {}
    for x in tr: lots[str(x["lot"])] = lots.get(str(x["lot"]), 0) + 1
    m = {"net": f["net"], "dd_cc": round(dd_of([x["pnl"] for x in tr]), 2), "dd_daily": f["worst_debt"], "mtm_proxy": f["mtm_dd_adverse"], "trades": len(tr),
         "wins": sum(1 for x in tr if x["win"]), "pnl_main": round(main, 2), "pnl_add": round(add, 2),
         "risk_main": round(sum(x["risk"] for x in tr), 2), "risk_add_actual": round(sum(x.get("add_risk", 0) for x in tr), 2), "adds_fired": sum(x.get("add_n", 0) for x in tr),
         "later_half_net": round(sum(x["pnl"] for x in tr if x["tc"] >= TMID), 2), "killed": bool(f["net"] <= -60 and len(tr) and tr[-1]["tc"] < T1 - 86400 * 3),
         "blocked": f["blocked"], "lots": lots, "pend": f.get("pend"), "tl": f.get("tl")}
    dl = [x for x in tr if x.get("delayed")]
    if dl or setups:
        fills = len(dl); wins = sum(1 for x in dl if x["win"])
        impr = sum(x["d"] * (x["e0"] - x["e_fill"]) * x["lot"] for x in dl)          # $ gained at fill vs the original entry price
        pm = [x.get("pnl_main", x["pnl"]) for x in dl]
        m["delayed"] = {"setups": f["pend"]["setups"], "fills": fills, "win_rate_filled": round(wins / fills, 3) if fills else None, "breakeven_wr_fair": 0.278,
                        "mean_pnl_main_filled": round(statistics.mean(pm), 3) if pm else None, "sum_pnl_main_filled": round(sum(pm), 2),
                        "mean_win_main": round(statistics.mean([p for p in pm if p > 0]), 2) if any(p > 0 for p in pm) else None,
                        "mean_loss_main": round(statistics.mean([p for p in pm if p <= 0]), 2) if any(p <= 0 for p in pm) else None,
                        "entry_price_gain_usd": round(impr, 2), "missed_winners": f["pend"]["missed_win"], "cancelled_stop_first": f["pend"]["cancelled_stop_first"],
                        "ambiguous": f["pend"]["ambiguous"], "ambiguous_kinds": f["pend"]["ambiguous_kinds"], "still_waiting_at_end": f["pend"]["still_waiting"]}
    return m


out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key": KEY, "dataset": META["sha256"], "rows": {}, "tl_events": {}}
for drag in (0.0, 0.35):
    for uid, pname, bal in REGIMES:
        base_cfg, rep = effective_cfg(PR[uid], bal, drag)
        for arm, over, dm in ARMS:
            cfg = H.cfg_strict(dict(base_cfg, **over))
            ck = "%s|%.2f|%s|%s" % (uid, drag, arm, hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:10])
            if ck in cache["rows"]:
                row = cache["rows"][ck]
            else:
                f, tr, setups = run(cfg, dm); row = metrics(f, tr, setups); row.update({"regime": uid, "package": pname, "drag": drag, "arm": arm, "effective": rep})
                if arm == "tl_projected" and drag == 0.0:
                    out["tl_events"][uid] = f.get("tl_events", [])
                cache["rows"][ck] = row; json.dump(cache, open(ROWS, "w"), indent=1)
            out["rows"][ck] = row
            extra = ""
            if row.get("delayed"):
                d_ = row["delayed"]; extra = " | setups %d fills %d missed-win %d amb %d wr %.2f mean main %.2f entry gain %.2f" % (
                    d_["setups"], d_["fills"], d_["missed_winners"], d_["ambiguous"], d_["win_rate_filled"] or 0, d_["mean_pnl_main_filled"] or 0, d_["entry_price_gain_usd"])
            if arm.startswith("tl"):
                t_ = row["tl"]; extra = " | pairs %d touches %d entries %d geom-rej %d gap %d pre-confirm %d arm->touch med %ss stop/spread med %s" % (
                    t_["pairs"], t_["touches"], t_["entries"], t_["geom_reject"], t_["gap_fills"], t_["pre_confirm_touch"], t_["arm_to_touch_s"]["median"], t_["stop_vs_spread"]["median"])
            print("%-18s drag %.2f %-18s | net %7.2f (main %7.2f add %6.2f) dd %6.2f daily %6.2f | trades %3d wins %3d | risk main %6.0f add %5.0f | later %7.2f%s" % (
                uid, drag, arm, row["net"], row["pnl_main"], row["pnl_add"], row["dd_cc"], row["dd_daily"], row["trades"], row["wins"], row["risk_main"], row["risk_add_actual"], row["later_half_net"], extra), flush=True)
json.dump(out, open(r"C:\Projects\KinoliveLines\study\entry_screens.json", "w"), indent=1)
print("DONE", flush=True)
