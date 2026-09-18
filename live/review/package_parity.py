"""Does owl_packages.json still hold the values the accounts ran on?

A money-management refactor that quietly changes a live account is worse
than no refactor. This compares each account's resolved package against
FROZEN, the dials that were HARDCODED in structure_bos_bot.py before the
2026-09-18 refactor, copied here by hand from the pre-refactor source.

Comparing against the bot's own constants would be circular now that the
bot reads the package - it would compare the file to itself. The frozen
table is the independent witness, and it is also the regression guard: an
accidental edit to owl_packages.json shows up here as a difference from
what the accounts were actually trading.

Deliberate changes ARE expected over time - a retuned offer, a new
package. When one is intended, update FROZEN in the same commit and say
so in the message; the point is that no dial moves unnoticed.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)

_BASE = {"base_lot": 0.02, "max_extra": 3, "adds_on": True,
         "chest_cap": 10.0, "jar": True, "jar_skim": 0.50,
         "jar_stake": 0.50, "jar_debt_mult": 0.5, "jar_floor_cap": 10.0,
         "kill_net": -60.0, "min_balance": 20.0, "max_risk_pct": 0.10,
         "debt_mode": "hwm", "day_cap": None, "week_target": None}

# copied by hand from structure_bos_bot.py as it stood on 2026-09-17,
# before money management moved into owl_packages.json
FROZEN = {
    "bos": dict(_BASE),
    "kino": dict(_BASE),
    "u224016179": dict(_BASE, day_cap=3.0, week_target=20.0),
    "sniper": dict(_BASE, base_lot=0.06, max_extra=0, adds_on=False,
                   kill_net=-80.0),
    "half": dict(_BASE, debt_mode="half"),
}


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    return a == b


def main():
    sys.path.insert(0, LIVE)
    import owl_package as PKG
    if PKG.error():
        print("config illisible:", PKG.error())
        return 1
    bad = 0
    for uid, want in sorted(FROZEN.items()):
        P = PKG.for_account(uid)
        diffs = [(k, v, P.get(k)) for k, v in want.items()
                 if not same(v, P.get(k))]
        print(f"\n{uid:<12} paquet '{P['package']}'  ({P['label']})")
        if not diffs:
            print("   identique a ce que le compte tradait")
        for k, was, now in diffs:
            bad += 1
            print(f"   ECART {k:<15} avant={was!r:<10} maintenant={now!r}")
    unknown = set(PKG.all_accounts()) - set(FROZEN)
    for u in sorted(unknown):
        print(f"\n{u:<12} NOUVEAU compte, rien a comparer "
              f"(paquet '{PKG.package_name(u)}')")
    print("\n" + ("TOUT CONCORDE" if bad == 0
                  else f"{bad} ECART(S) - voulus ? mets FROZEN a jour"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
