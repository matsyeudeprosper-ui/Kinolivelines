"""2026-10-17 (owner: "make sure the referral system and the robot system are fully working, no errors").
Exercises owl_wallet + owl_market on TEMPORARY files - never the live ledgers. Run: python review/test_market_wallet.py
Every assert is a money or lifecycle rule from review/REFERRAL_AND_MARKET.md."""
import os, sys, json, time, tempfile, importlib

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(os.path.dirname(HERE), "live")
sys.path.insert(0, LIVE)
TMP = tempfile.mkdtemp(prefix="owl_test_")

import owl_wallet as W
import owl_market as M
W.WALLET = os.path.join(TMP, "wallet.json")
W.USERS = os.path.join(TMP, "users.json")
M.MARKET = os.path.join(TMP, "market.json")
M.ROBOTS = os.path.join(TMP, "robots.json")
M.RESULTS = os.path.join(TMP, "results"); os.makedirs(M.RESULTS)

PACKAGES = {"manual": {"usd": 29.0, "days": 30}, "strategy": {"usd": 49.0, "days": 30}, "family": {"usd": 60.0, "days": 30}}
FAM = 60.0
N = [0, 0]


def check(name, cond, info=""):
    N[0] += 1
    if cond:
        print("  ok   ", name)
    else:
        N[1] += 1; print("  FAIL ", name, info)


# ---------- fixtures ----------
users = [{"id": "ann", "name": "Ann"}, {"id": "bob", "name": "Bob", "referred_by": "ann"}, {"id": "cat", "name": "Cat", "referred_by": "ann"},
         {"id": "pub", "name": "Demo", "public": True}, {"id": "self", "name": "Self", "referred_by": "self"}]
json.dump(users, open(W.USERS, "w"))
json.dump({"robots": [{"id": "owl", "name_fr": "L'Owl", "stage": "real"},
                      {"id": "r1", "name_fr": "Robot Ann", "stage": "tested", "by_uid": "ann"},
                      {"id": "r2", "name_fr": "Robot Bad", "stage": "tested", "by_uid": "ann"},
                      {"id": "r3", "name_fr": "Pas testé", "stage": "draft", "by_uid": "ann"}]}, open(M.ROBOTS, "w"))
json.dump({"days": 42, "generated_at": "2026-10-17", "robot": {"net": 50.0, "trades": 80, "win_rate": 0.6, "cc_dd": 30.0, "profit_factor": 1.4, "curve": [["2026-09-01", 1.0], ["2026-10-01", 50.0]]}}, open(os.path.join(M.RESULTS, "r1.json"), "w"))
json.dump({"days": 42, "generated_at": "2026-10-17", "robot": {"net": -5.0, "trades": 80, "win_rate": 0.4, "cc_dd": 30.0, "profit_factor": 0.9, "curve": []}}, open(os.path.join(M.RESULTS, "r2.json"), "w"))

print("REFERRAL")
c = W.code_of("ann")
check("code shape OWL-XXXXX", c.startswith("OWL-") and len(c) == 9)
check("code resolves to member", W.uid_of_code(c.lower()) == "ann")
check("public account has no usable code", W.uid_of_code(W.code_of("pub")) is None)
check("unknown code -> None", W.uid_of_code("OWL-ZZZZZ") is None and W.uid_of_code("hello") is None)
check("referrer of bob is ann", W.referrer_of("bob") == "ann")
check("friends of ann = bob, cat", sorted(f["id"] for f in W.friends_of("ann")) == ["bob", "cat"])

r, usd = W.on_member_payment("bob", "family", 60.0, "Automatique")
check("bob pays $60 -> ann gets 20 % = $12 in days", (r, usd) == ("ann", 12.0), (r, usd))
check("balance is $12", W.balance("ann") == 12.0)
r, usd = W.on_member_payment("bob", "family", 0.0, "Automatique")
check("an OFFERED (free) month credits nothing", usd == 0.0 and W.balance("ann") == 12.0)
r, usd = W.on_member_payment("self", "family", 60.0, "Automatique")
check("self-referral credits nothing", (r, usd) == (None, 0.0), (r, usd))
r, usd = W.on_member_payment("ann", "family", 60.0, "Automatique")
check("a member without referrer credits nothing", (r, usd) == (None, 0.0))

# the monthly cap: more than MAX_REF_PER_MONTH distinct friends in one month -> the extra ones credit 0
extra = [{"id": "f%d" % i, "name": "F", "referred_by": "ann"} for i in range(W.MAX_REF_PER_MONTH + 3)]
json.dump(users + extra, open(W.USERS, "w"))
got = [W.on_member_payment("f%d" % i, "manual", 29.0, "Signal")[1] for i in range(W.MAX_REF_PER_MONTH + 3)]
check("cap: at most %d friends credited per month" % W.MAX_REF_PER_MONTH, sum(1 for g in got if g > 0) == W.MAX_REF_PER_MONTH - 1, got)   # bob already counted this month
bal = W.balance("ann")
check("cagnotte converts at the package daily price (family $2/day)", W.days_available("ann", "family", PACKAGES, FAM) == int(bal // 2.0))
check("cagnotte converts at Signal price ($0.97/day)", W.days_available("ann", "manual", PACKAGES, FAM) == int(bal // (29.0 / 30)))
spent = W.spend_days("ann", "family", 3, PACKAGES, FAM)
check("spending 3 family days debits $6", spent == 6.0 and abs(W.balance("ann") - (bal - 6.0)) < 1e-9, (spent, W.balance("ann")))
check("cannot spend more days than the cagnotte holds", W.spend_days("ann", "family", 10 ** 6, PACKAGES, FAM) == 0.0)
check("referral money never touches creator cash", W.earnings("ann")["cash"] == 0.0)

print("CREATOR SHARE (pay once, by time)")
slice10 = FAM / 30 / 86400 * 600 * W.CREATOR_SHARE
check("5 minutes stay below a cent", W.accrue_share("ann", "bob", "r1", slice10 / 2) == 0.0)
tot = sum(W.accrue_share("ann", "bob", "r1", slice10) for _ in range(144))
e = W.earnings("ann")
check("one day of $60 plan -> $0.60 to the creator", abs(e["cash"] - 0.60) < 0.011, e["cash"])
check("one history line per robot, follower and day", len([h for h in e["history"] if h["kind"] == "share"]) == 1)
check("creator_earned(rid) matches", abs(W.creator_earned("r1") - e["cash"]) < 1e-9)
check("creator cannot earn from themselves", W.accrue_share("ann", "ann", "r1", 1.0) == 0.0)
check("no creator -> nothing", W.accrue_share("", "bob", "r1", 1.0) == 0.0)
check("cash and cagnotte are separate ledgers", W.balance("ann") == bal - 6.0)

print("PAYOUTS")
W.set_payout_addr("ann", "TXYZ")
for _ in range(90):
    W.accrue_share("ann", "cat", "r1", 0.60)        # 90 days of a second follower
e = W.earnings("ann")
check("threshold reached at $%d" % W.PAYOUT_MIN, e["due"] is True and e["cash"] >= W.PAYOUT_MIN, e["cash"])
due = W.payouts_due()
check("owner's payout list names ann with her address", due and due[0]["uid"] == "ann" and due[0]["addr"] == "TXYZ")
check("overpaying is refused", W.mark_paid("ann", e["cash"] + 1, "x") is False)
check("paying zero is refused", W.mark_paid("ann", 0, "x") is False)
check("paying the due amount works", W.mark_paid("ann", e["cash"], "tx-1") is True and W.earnings("ann")["cash"] == 0.0)
check("payout recorded with reference", W.earnings("ann")["payouts"][-1]["ref"] == "tx-1")
check("earned-in-all is unchanged by a payout", W.earnings("ann")["cash_earned"] >= 54.0)

print("PLACE")
ok, why = M.can_publish("r1", "ann"); check("tested positive robot can be published", ok, why)
ok, why = M.can_publish("r2", "ann"); check("negative test cannot be published", not ok and "négatif" in why, why)
ok, why = M.can_publish("r3", "ann"); check("untested robot cannot be published", not ok, why)
ok, why = M.can_publish("r1", "bob"); check("someone else's robot cannot be published", not ok, why)
check("publish needs an author name", M.publish("r1", "ann", "", "", 0, True)["ok"] is False)
res = M.publish("r1", "ann", "Ann", "Mon robot", 49, True)
check("publish works and the price is always 0 (included)", res["ok"] and M.listing("r1")["price_usd"] == 0)
cat_ = M.catalogue("bob", "")
check("catalogue shows it as free/included with its test", cat_[0]["id"] == "r1" and cat_[0]["free"] and cat_[0]["test"]["net"] == 50.0)
s = M.start_sub("bob", "r1", 0.0, "included")
check("a follow is open-ended", s["open"] is True and M.sub_of("bob")["rid"] == "r1")
check("followers counted", M.followers("r1") == ["bob"])
check("open subs never expire", M.expired_subs() == [])
old = M.start_sub("cat", "r1", 9.0, "legacy")
d = M.data(); d["subs"]["cat"]["until"] = int(time.time()) - 10; M._save(M.MARKET, d)
check("a legacy paid sub past its end is reported", [u for u, _ in M.expired_subs()] == ["cat"])
M.mark_ended("cat"); check("ended once, then silent", M.expired_subs() == [])
check("stop_sub removes the follow", M.stop_sub("bob") is not None and M.sub_of("bob") is None)
json.dump({"days": 42, "generated_at": "2026-10-17", "robot": {"net": -1.0, "trades": 80, "curve": []}}, open(os.path.join(M.RESULTS, "r1.json"), "w"))
M.refresh_pauses(); check("a listing whose test turns negative is paused", M.listing("r1")["paused"] is True)
json.dump({"days": 42, "generated_at": "2026-10-17", "robot": {"net": 50.0, "trades": 80, "curve": []}}, open(os.path.join(M.RESULTS, "r1.json"), "w"))
M.refresh_pauses(); check("and unpaused when it comes back", M.listing("r1")["paused"] is False)
check("unpublish hides it", M.unpublish("r1", "ann")["ok"] and M.listing("r1")["hidden"] is True and M.catalogue("bob", "") == [])
check("unpublish by a stranger is refused", M.unpublish("r1", "bob")["ok"] is False)
st = M.creator_stats("ann")
check("creator stats carry wallet earnings per robot", st and st[0]["id"] == "r1" and st[0]["earned_usd"] >= 54.0, st)

print("\n%d checks, %d failed" % (N[0], N[1]))
sys.exit(1 if N[1] else 0)
