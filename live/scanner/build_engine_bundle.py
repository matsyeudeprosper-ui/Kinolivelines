"""build_engine_bundle.py - the scanner's ISOLATED, immutable engine (GPT review of 59f09ee, item 3).

The scanner must not import the working robot / chart files: an ordinary product edit would change the
signals under a running forward test. This copies every engine source the scanner loads into
live/scanner/engine_f2/, rewrites absolute paths into the bundle, adds inert stand-ins for the files the
robot module reads at import time (no secret, no member list), copies the control parameters, and writes
BUNDLE_MANIFEST.json with the SHA-256 of every bundle file and of the runner (live/owl_scanner.py).

owl_scanner.py loads the engine ONLY from this folder, checks every loaded module's __file__ sits inside it,
and refuses new virtual trades if the manifest is missing, unreadable, incomplete or does not match.
Run it once, right before a FROZEN commit:
    python live/scanner/build_engine_bundle.py
"""
import hashlib
import json
import os
import re
import time

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(LIVE, "scanner", "engine_f2")
ENGINE = ["structure_bos_bot.py", "owl_package.py", "owl_shadow.py", "pb_gate.py", "owl_chart_feed.py"]
DATA = ["owl_packages.json"]
REQUIRED = ENGINE + DATA + ["owl_secrets.json", "owl_nest_users.json", "control_params.json"]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def rewrite(src):
    for root in (r"C:\Projects\KinoliveLines\live", "C:/Projects/KinoliveLines/live",
                 r"C:\\Projects\\KinoliveLines\\live"):
        src = src.replace(root, B)
    return src


def control_params():
    """frozen inputs of the random controls: each symbol's mean time between strategy trades and its
    stop distances as a share of price, from the scanner's last-30-calendar-day bar backtest"""
    out = {}
    for sym in ("USTEC", "XAUUSD", "US30", "US500", "BTCUSD"):
        b = json.load(open(os.path.join(LIVE, "scanner", "backtest_%s.json" % sym), encoding="utf-8"))
        T = b.get("trades") or []
        if not T:
            continue
        span = max(1, int(b["to"]) - int(b["from"]))
        out[sym] = {"mean_gap_s": round(span / len(T), 1), "risk_frac": [round(t["risk"] / t["e"], 7) for t in T],
                    "source": "backtest_%s.json %s..%s n=%d" % (sym, b["from"], b["to"], len(T))}
    return out


def main():
    os.makedirs(B, exist_ok=True)
    for f in ENGINE:
        s = open(os.path.join(LIVE, f), encoding="utf-8").read()
        open(os.path.join(B, f), "w", encoding="utf-8", newline="").write(rewrite(s))
    for f in DATA:
        open(os.path.join(B, f), "wb").write(open(os.path.join(LIVE, f), "rb").read())
    # inert stand-ins for the robot module's import-time reads: no password, no member list
    json.dump({"mt5_password": ""}, open(os.path.join(B, "owl_secrets.json"), "w", encoding="utf-8"))
    json.dump([], open(os.path.join(B, "owl_nest_users.json"), "w", encoding="utf-8"))
    json.dump(control_params(), open(os.path.join(B, "control_params.json"), "w", encoding="utf-8"), indent=1)
    left = []
    for f in ENGINE:
        txt = open(os.path.join(B, f), encoding="utf-8").read()
        left += [(f, m) for m in re.findall(r"C:[\\/]+Projects[\\/]+KinoliveLines[^\"'\s]*", txt) if "engine_f2" not in m]
    files = {f: sha(os.path.join(B, f)) for f in sorted(os.listdir(B))
             if not f.startswith("__") and f != "BUNDLE_MANIFEST.json" and not f.endswith(".pyc")}
    man = {"bundle": "engine_f2", "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "required": REQUIRED, "files": files, "runner": {"owl_scanner.py": sha(os.path.join(LIVE, "owl_scanner.py"))},
           "unrewritten_paths": left}
    json.dump(man, open(os.path.join(B, "BUNDLE_MANIFEST.json"), "w", encoding="utf-8"), indent=1)
    print("bundle %s: %d files, unrewritten paths: %d" % (B, len(files), len(left)))
    for f, m in left[:10]:
        print("  WARNING", f, m)


if __name__ == "__main__":
    main()
