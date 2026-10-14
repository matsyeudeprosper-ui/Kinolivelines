"""owl_markets.py - which markets an account may trade for real, besides Bitcoin (owner 2026-10-15).

THE RULE (owner: "auto allow all symbols that tested positive on that bot ... a rule of the system, applied to any
account by default"; chose "beat chance" over "positive only"): an account runs the robot plugged on it (none = the
Owl) on Bitcoin, PLUS every other market where that robot passed BOTH checks:
  1. its market test (robots/results/<robot>@<SYM>.json) made money, and
  2. its random-entry control (study/random_control_<robot>_<SYM>.json) beats chance: percentile >= 95,
and the market is on that account's own broker (nest_data/<uid>.symbols.json) and has a market pack (the scale the
test used). The reference account stays dedicated to Bitcoin (it feeds the Compte indicator).

A market bot is the same structure_bos_bot.py, started as `<variant>@<SYM>` (e.g. expenses@USTEC): it sees the
market's prices multiplied by the pack's k, exactly as the test did, so every Bitcoin-sized rule and dial applies
unchanged; lots are multiplied back so a point of risk costs the same dollars as in the test (ScaledMT5 below).

    python owl_markets.py            print the allowed markets per account (and why the others are not)
    python owl_markets.py --launch   print one '<variant>@<SYM>' per allowed market bot (boot_all.ps1 reads this)
"""
import json
import os
import sys
import types

DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(DIR)
RESULTS = os.path.join(DIR, "robots", "results")
CONTROLS = os.path.join(ROOT, "study")
PACKS = os.path.join(ROOT, "study", "markets")
PCT_MIN = 95.0
EXCLUDED = {"u477508138"}            # the reference account: Bitcoin only, never a copier or a second market
# account id -> the argument its Bitcoin bot runs with (no argument = "live" = the 'bos' account)
VARIANT = {"bos": "live", "u224016179": "valere", "demo": "demo", "infinity": "infinity", "expenses": "expenses",
           "kino": "kino", "labo": "labo", "sniper": "sniper", "half": "halfdebt"}
# a stable magic per market, so each market bot only ever sees its own trades (Bitcoin bots keep theirs)
MARKET_IDX = ["XAUUSD", "XAGUSD", "USOIL", "US30", "USTEC", "US500", "DE30", "UK100", "JP225", "EURUSD", "GBPUSD",
              "USDJPY", "UKOIL", "ETHUSD"]


def _load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def base(sym):
    """the broker's name -> the common one: XAUUSDm / USTEC -> XAUUSD / USTEC"""
    s = str(sym)
    return s[:-1] if s.endswith("m") and s[:-1].isupper() else s


def robot_of(uid):
    plugs = (_load(os.path.join(DIR, "owl_packages.json"), {}) or {}).get("robot_plugs") or {}
    return (plugs.get(uid) or {}).get("robot") or "owl"


def pack_meta(sym):
    return _load(os.path.join(PACKS, base(sym).upper(), "meta.json"))


def check(uid, sym):
    """(allowed, reason) for one account and one market (common name)"""
    rid = robot_of(uid)
    B = base(sym).upper()
    if uid in EXCLUDED:
        return False, "compte de reference: Bitcoin seulement"
    res = _load(os.path.join(RESULTS, "%s@%s.json" % (rid, B)))
    if not res or not (res.get("robot") or {}).get("trades"):
        return False, "pas teste"
    net = float(res["robot"].get("net") or 0)
    if net <= 0:
        return False, "test negatif (%.2f)" % net
    ctl = _load(os.path.join(CONTROLS, "random_control_%s_%s.json" % (rid, B)))
    if not ctl or ctl.get("percentile") is None:
        return False, "controle hasard pas encore fait"
    if float(ctl["percentile"]) < PCT_MIN:
        return False, "dans la chance (%.1fe percentile)" % float(ctl["percentile"])
    syms = (_load(os.path.join(DIR, "nest_data", "%s.symbols.json" % uid), {}) or {}).get("symbols") or []
    if not any(base(x.get("s", "")).upper() == B for x in syms):
        return False, "pas sur le courtier de ce compte"
    if not pack_meta(B):
        return False, "pas de donnees de marche"
    return True, "test +%.2f, bat le hasard (%.1fe percentile)" % (net, float(ctl["percentile"]))


def account_symbol(uid, sym):
    """the broker's own name of this market on this account (USTEC, USTECm...)"""
    B = base(sym).upper()
    syms = (_load(os.path.join(DIR, "nest_data", "%s.symbols.json" % uid), {}) or {}).get("symbols") or []
    names = [x["s"] for x in syms if base(x.get("s", "")).upper() == B]
    return B if B in names else (names[0] if names else B)


def allowed(uid):
    out = []
    for f in sorted(os.listdir(RESULTS)) if os.path.isdir(RESULTS) else []:
        if not f.endswith(".json") or "@" not in f:
            continue
        rid, sym = f[:-5].split("@", 1)
        if rid != robot_of(uid):
            continue
        ok, why = check(uid, sym)
        out.append({"sym": sym, "ok": ok, "why": why})
    return out


def launch_list():
    users = _load(os.path.join(DIR, "owl_nest_users.json"), []) or []
    L = []
    for u in users:
        uid = u.get("id")
        if not (u.get("trade") and u.get("mt5_login")) or uid in EXCLUDED:
            continue
        v = VARIANT.get(uid, uid)
        for a in allowed(uid):
            if a["ok"]:
                L.append("%s@%s" % (v, a["sym"]))
    return L


def market_magic(magic, sym):
    B = base(sym).upper()
    i = MARKET_IDX.index(B) + 1 if B in MARKET_IDX else 50 + (sum(map(ord, B)) % 40)
    return int(magic) + 10000 * i


class _Obj:
    """a read-only copy of an MT5 record with some fields replaced"""

    def __init__(self, src, **over):
        self._src, self._over = src, over

    def __getattr__(self, k):
        if k in self._over:
            return self._over[k]
        return getattr(self._src, k)

    def _asdict(self):
        d = self._src._asdict() if hasattr(self._src, "_asdict") else {}
        d.update(self._over)
        return d


class ScaledMT5(types.ModuleType):
    """MetaTrader5 for a market bot: every price it reads is multiplied by k (the pack's scale, so the market looks
    like the Bitcoin the rules were written for - the same transform the test used) and every price it sends is
    divided back; lots are multiplied by k / V (V = $ per point per lot of THIS account's symbol) so one engine lot
    risks the same dollars as in the test. Profits, balances and everything else pass through untouched."""

    def __init__(self, real, sym, k):
        super().__init__("mt5_market")
        self._m, self._sym, self._k = real, sym, float(k)
        self._info = None

    def __getattr__(self, name):
        return getattr(self._m, name)

    # ---- the symbol's facts, read once connected
    def _si(self):
        if self._info is None:
            self._info = self._m.symbol_info(self._sym)
        return self._info

    def lot_factor(self):
        si = self._si()
        V = float(si.trade_tick_value) / float(si.trade_tick_size) if si and si.trade_tick_size else 1.0
        return self._k / V

    def _px_out(self, p):
        si = self._si()
        return round(float(p) / self._k, int(si.digits) if si else 5)

    def _vol_out(self, v):
        si = self._si()
        step = float(si.volume_step) if si else 0.01
        vmin = float(si.volume_min) if si else 0.01
        n = max(vmin, round(round(float(v) * self.lot_factor() / step) * step, 8))
        return round(n, 8)

    # ---- reads
    def copy_rates_from_pos(self, *a, **kw):
        R = self._m.copy_rates_from_pos(*a, **kw)
        if R is None:
            return R
        R = R.copy()
        for f in ("open", "high", "low", "close"):
            R[f] = R[f] * self._k
        return R

    def symbol_info_tick(self, sym):
        t = self._m.symbol_info_tick(sym)
        if t is None:
            return t
        return _Obj(t, bid=t.bid * self._k, ask=t.ask * self._k, last=t.last * self._k)

    def _pos(self, p):
        return _Obj(p, price_open=p.price_open * self._k, sl=p.sl * self._k, tp=p.tp * self._k,
                    price_current=p.price_current * self._k, volume=p.volume / self.lot_factor())

    def positions_get(self, *a, **kw):
        P = self._m.positions_get(*a, **kw)
        return None if P is None else tuple(self._pos(p) for p in P)

    def _deal(self, d):
        if getattr(d, "symbol", self._sym) != self._sym:
            return d
        return _Obj(d, price=d.price * self._k, volume=d.volume / self.lot_factor())

    def history_deals_get(self, *a, **kw):
        D = self._m.history_deals_get(*a, **kw)
        return None if D is None else tuple(self._deal(d) for d in D)

    # ---- the one write
    def order_send(self, req):
        r = dict(req)
        for f in ("price", "sl", "tp"):
            if r.get(f):
                r[f] = self._px_out(r[f])
        if "volume" in r:
            if r.get("position"):
                # closing (all or part) of a real position: never send more than it holds
                real = next((p for p in (self._m.positions_get(ticket=r["position"]) or [])), None)
                want = self._vol_out(r["volume"])
                r["volume"] = min(want, real.volume) if real else want
                if real and abs(want - real.volume) <= float(self._si().volume_step) * 0.51:
                    r["volume"] = real.volume
            else:
                r["volume"] = self._vol_out(r["volume"])
        res = self._m.order_send(r)
        if res is None:
            return res
        return _Obj(res, price=(res.price or 0) * self._k, volume=(res.volume or 0) / self.lot_factor(),
                    bid=(getattr(res, "bid", 0) or 0) * self._k, ask=(getattr(res, "ask", 0) or 0) * self._k)


if __name__ == "__main__":
    if "--launch" in sys.argv:
        for x in launch_list():
            print(x)
        sys.exit(0)
    for u in _load(os.path.join(DIR, "owl_nest_users.json"), []) or []:
        if not (u.get("trade") and u.get("mt5_login")):
            continue
        A = allowed(u["id"])
        print("%-12s robot %-12s %s" % (u["id"], robot_of(u["id"]),
                                        "; ".join("%s %s (%s)" % (a["sym"], "OUI" if a["ok"] else "non", a["why"]) for a in A) or "Bitcoin seulement"))
