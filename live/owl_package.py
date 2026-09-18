"""owl_package.py - money management per account, from owl_packages.json.

Owner 2026-09-18: "Valere's difference should just be the daily cut off
profit... going forward new accounts may have different money management,
package kind of thing... so make things easy for codes to go that route."

So: STRATEGY is code and is identical everywhere; MONEY MANAGEMENT is data
and may differ per account. A new offer is a few lines of JSON, and the
numbers can be retuned without touching a bot or restarting one.

    import owl_package as PKG
    P = PKG.for_account("u224016179")
    P["day_cap"]        -> 3.0
    P.get("base_lot")   -> 0.02

The file is re-read at most once a minute, so edits reach a running bot
on their own. If the file is missing or broken the last good copy is kept
(and BASE is used if there never was one) - a typo in a config file must
never stop a live account from managing its open trades.
"""
import json
import os
import time

DIR = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(DIR, "owl_packages.json")
TTL = 60.0

# what a package may set. Anything not listed here is strategy and stays
# in code, the same for every account.
FIELDS = ("label", "base_lot", "max_extra", "adds_on", "chest_cap",
          "jar", "jar_skim", "jar_stake", "jar_debt_mult", "jar_floor_cap",
          "kill_net", "min_balance", "max_risk_pct", "debt_mode",
          "day_cap", "max_trades_day", "week_target")

BASE = {"label": "Standard", "base_lot": 0.02, "max_extra": 3,
        "adds_on": True, "chest_cap": 10.0, "jar": True, "jar_skim": 0.50,
        "jar_stake": 0.50, "jar_debt_mult": 0.5, "jar_floor_cap": 10.0,
        "kill_net": -60.0, "min_balance": 20.0, "max_risk_pct": 0.10,
        "debt_mode": "hwm", "day_cap": None, "max_trades_day": None,
        "week_target": None}

_cache = {"t": 0.0, "raw": None, "err": None}


def _resolve(name, packs, seen=None):
    """A package plus everything it inherits, nearest wins."""
    seen = seen or set()
    if name in seen:                      # a cycle is a typo, not a plan
        return dict(BASE)
    seen.add(name)
    p = packs.get(name)
    if not isinstance(p, dict):
        return dict(BASE)
    parent = p.get("extends")
    out = _resolve(parent, packs, seen) if parent else dict(BASE)
    for k, v in p.items():
        if k in FIELDS:
            out[k] = v
    return out


def _load():
    if _cache["raw"] is not None and time.time() - _cache["t"] < TTL:
        return _cache["raw"]
    try:
        with open(CONF, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw.get("packages"), dict):
            raise ValueError("no packages")
        _cache["raw"] = raw
        _cache["err"] = None
    except Exception as e:
        # keep the last good copy; never let a bad file stop a live account
        _cache["err"] = str(e)
    _cache["t"] = time.time()
    return _cache["raw"]


def package_name(uid):
    raw = _load() or {}
    return (raw.get("accounts") or {}).get(uid, "base")


def for_account(uid):
    """The money-management dials for ONE account. Always a full dict."""
    raw = _load()
    if not raw:
        return dict(BASE, package="base")
    name = (raw.get("accounts") or {}).get(uid, "base")
    out = _resolve(name, raw.get("packages") or {})
    out["package"] = name
    return out


def error():
    """Last config problem, or None. Bots log this at startup."""
    _load()
    return _cache["err"]


def all_accounts():
    raw = _load() or {}
    return dict(raw.get("accounts") or {})


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(for_account(sys.argv[1]), indent=2))
    else:
        for uid, name in sorted(all_accounts().items()):
            p = for_account(uid)
            print(f"{uid:<14} {name:<10} {p['label']}")
            print(f"{'':14} lot {p['base_lot']}  +{p['max_extra']} bullets"
                  f"  kill {p['kill_net']}  day_cap {p['day_cap']}"
                  f"  trades/j {p['max_trades_day']}")
        if error():
            print("PROBLEME de config:", error())
