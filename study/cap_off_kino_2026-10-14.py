import sys, json, time
OUTF = sys.argv[1]
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import harness as H
t0 = time.time()
sym, R = H.bars()
out = {"symbol": sym, "days": round(len(R) / 1440, 1), "first": int(R["time"][0]), "last": int(R["time"][-1])}
for drag in (0.0, 0.35):
    on = H.package_cfg("valere", {"drag": drag, "pb_dir_gate": True})
    off = H.package_cfg("valere", {"drag": drag, "day_cap": 0.0, "pb_dir_gate": True})
    out[f"drag{drag}"] = {"cap_on": H.run_cfg(R, 7.0, on), "cap_off": H.run_cfg(R, 7.0, off)}
    out[f"drag{drag}"]["verdict"] = H.verdict(out[f"drag{drag}"]["cap_off"], out[f"drag{drag}"]["cap_on"])
    print("done drag", drag, round(time.time() - t0), "s", flush=True)
out["cfg_on"] = H.package_cfg("valere", {"drag": 0.0, "pb_dir_gate": True})
json.dump(out, open(OUTF, "w"), default=str, indent=1)
print("saved", flush=True)
