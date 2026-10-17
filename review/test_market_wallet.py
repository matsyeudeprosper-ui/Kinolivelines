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
check("bob pays his first $60 -> ann gets 50 % = $30 in MONEY", (r, usd) == ("ann", 30.0), (r, usd))
check("referral money sits in the cash ledger, not in days", W.earnings("ann")["cash"] == 30.0 and W.balance("ann") == 0.0)
r, usd = W.on_member_payment("bob", "family", 60.0, "Automatique")
check("bob's SECOND month credits nothing", usd == 0.0 and W.earnings("ann")["cash"] == 30.0)
r, usd = W.on_member_payment("cat", "family", 0.0, "Automatique")
check("an OFFERED (free) first month credits nothing", usd == 0.0 and W.earnings("ann")["cash"] == 30.0)
st = W.referral_stats("ann")
check("campaign stats: 2 friends signed, 1 paid, $30 earned", (st["signed"], st["paid"], st["earned"]) == (2, 1, 30.0), st)
check("referral payout door is $%d" % W.REF_PAYOUT_MIN, W.earnings("ann")["due"] is False and W.REF_PAYOUT_MIN == 100.0)
# a cagnotte in DAYS only for whoever still has one (legacy): credit by hand to test the conversion
W._credit("ann", 12.0, "legacy", "old cagnotte")
r, usd = W.on_member_payment("self", "family", 60.0, "Automatique")
check("self-referral credits nothing", (r, usd) == (None, 0.0), (r, usd))
r, usd = W.on_member_payment("ann", "family", 60.0, "Automatique")
check("a member without referrer credits nothing", (r, usd) == (None, 0.0))

# the monthly cap: more than MAX_REF_PER_MONTH distinct friends in one month -> the extra ones credit 0
extra = [{"id": "f%d" % i, "name": "F", "referred_by": "ann"} for i in range(W.MAX_REF_PER_MONTH + 3)]
json.dump(users + extra, open(W.USERS, "w"))
got = [W.on_member_payment("f%d" % i, "manual", 29.0, "Signal")[1] for i in range(W.MAX_REF_PER_MONTH + 3)]
check("cap: at most %d friends credited per month" % W.MAX_REF_PER_MONTH, sum(1 for g in got if g > 0) == W.MAX_REF_PER_MONTH - 1, got)   # bob already counted this month
e = W.earnings("ann")
check("9 Signal friends x $14.50 + $30 -> $160.50, payout due (>= $100)", abs(e["cash"] - 160.5) < 0.01 and e["due"] is True, e["cash"])
check("owner's list carries the referral part", any(p["uid"] == "ann" and p["ref"] >= 160 for p in W.payouts_due()))
check("paying it out empties the referral part", W.mark_paid("ann", 160.5, "tx-ref") is True and W.referral_stats("ann")["cash_ref"] == 0.0 and W.earnings("ann")["cash"] == 0.0)
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


print("CREATORS / YOUTUBERS (2026-10-17)")
import owl_influencers as INF
INF.FILE = os.path.join(TMP, "inf.json")
json.dump(users + [{"id": "yt", "name": "Yuki"}, {"id": "v1", "name": "Viewer", "referred_by": "yt"}, {"id": "v2", "name": "Viewer2", "referred_by": "yt"}], open(W.USERS, "w"))
check("apply needs a channel and a video", INF.apply("yt", "", "")["ok"] is False and INF.apply("yt", "youtube.com/@yuki", "")["ok"] is False)
check("apply records pending", INF.apply("yt", "youtube.com/@yuki", "https://youtu.be/abc")["ok"] and INF.status("yt")["status"] == "pending" and INF.status("yt")["channel"].startswith("https://"))
r, usd = W.on_member_payment("v1", "manual", 29.0, "Signal")
check("before approval a viewer's first month is a standard referral (50 % once)", usd == 14.5)
check("owner's pending list names the applicant", [p["uid"] for p in INF.pending()] == ["yt"])
check("approve", INF.review("yt", True)["status"] == "approved" and INF.is_approved("yt"))
r, usd = W.on_member_payment("v1", "manual", 29.0, "Signal")
check("after approval the SAME viewer's next month pays 30 % (recurring)", usd == 8.7, usd)
r, usd = W.on_member_payment("v1", "manual", 29.0, "Signal")
check("and the month after too", usd == 8.7)
r, usd = W.on_member_payment("v2", "strategy", 49.0, "Strategie")
check("a new viewer pays 30 % from the first month", usd == 14.7)
st = W.referral_stats("yt")
check("creator stats: 2 users, recurring $32.10, this month counted", st["signed"] == 2 and abs(st["recurring"] - 32.1) < 0.01 and st["this_month"] >= 32.1 and st["active"] == 2, st)
check("refuse works and the next payment falls back to the one-time rule (already paid -> 0)", INF.review("yt", False)["status"] == "refused" and W.on_member_payment("v1", "manual", 29.0, "Signal")[1] == 0.0)
check("nest keeps at least 70 % of every creator-referred payment", W.INF_PCT <= 0.30)
INF.review("yt", True)
for i in range(14):
    W.on_member_payment("v2", "strategy", 49.0, "Strategie")
n_v2 = sum(1 for h in W.earnings("yt")["history"] if h.get("kind") == "influencer" and h.get("friend") == "v2")
check("the 30 %% stops after %d paid months of the same user" % W.INF_MONTHS, n_v2 == W.INF_MONTHS, n_v2)
check("months_left reaches 0 for that user", max(W.referral_stats("yt")["friends"], key=lambda f: f["usd"])["months_left"] == 0)

print("LINK TRAFFIC + AUTO-CHECK")
W.CLICKS = os.path.join(TMP, "clicks.json"); W.SALT_F = os.path.join(TMP, "salt")
code = W.code_of("ann")
check("a visit with an unknown code is ignored", W.record_click("OWL-ZZZZZ", "1.2.3.4") is False)
for ip in ("1.2.3.4", "1.2.3.4", "5.6.7.8"):
    W.record_click(code, ip)
ck = W.clicks_of("ann")
check("3 hits, 2 unique visitors today", ck["today"] == 3 and ck["u7"] == 2 and ck["d30"] == 3, ck)
check("no IP is stored, only a salted hash", "1.2.3.4" not in open(W.CLICKS).read())
check("stats carry the clicks and a conversion rate", W.referral_stats("ann")["clicks"]["u7"] == 2 and W.referral_stats("ann")["conversion"] is not None)
check("SSRF guard: localhost refused", INF._public_host("http://127.0.0.1:8787/") is False and INF._public_host("http://192.168.1.5/") is False)
check("SSRF guard: a public name is allowed", INF._public_host("https://example.com/") is True)
check("a file: or ftp: link is refused", INF._public_host("file:///etc/passwd") is False)

print("AUTOMATIC CHECK OF THE PUBLICATION")
check("our own pages are never a proof", INF._public_host("https://owltrader.duckdns.org/offres?p=OWL-ABCDE") is False)
check("a bare IP is never a publication", INF._public_host("http://8.8.8.8/post") is False)
INF.apply("yt2", "https://youtube.com/@two", "https://example.com/video-two", platform="youtube")
_real = INF.fetch_text
INF.fetch_text = lambda url: "<html>my OwlNest code is " + W.code_of("yt2") + " enjoy</html>"
r = INF.verify("yt2", W.code_of("yt2"), "owltrader.duckdns.org/offres?p=" + W.code_of("yt2"))
check("code found on the page -> approved automatically", r["status"] == "approved" and r["auto_check"]["found"] is True and r["review_note"].startswith("auto"), r.get("auto_check"))
INF.apply("yt3", "", "https://example.com/other", platform="blog")
INF.fetch_text = lambda url: "<html>nothing about it</html>"
r = INF.verify("yt3", W.code_of("yt3"), "")
check("code absent -> stays pending with the reason", r["status"] == "pending" and r["auto_check"]["found"] is False and "absent" in r["auto_check"]["reason"], r.get("auto_check"))
INF.fetch_text = lambda url: None
r = INF.verify("yt3", W.code_of("yt3"), "")
check("page unreadable -> stays pending, says so", r["status"] == "pending" and "illisible" in r["auto_check"]["reason"])
INF.fetch_text = _real

print("PUBLICATIONS OF AN APPROVED CREATOR")
check("an approved creator adds a publication instead of re-applying", INF.apply("yt2", "", "https://example.com/video-three", platform="tiktok") == {"ok": True, "added": True})
check("the same link twice is refused", INF.apply("yt2", "", "https://example.com/video-three")["err"] == "dup")
P = INF.publications("yt2")
check("publications: the approved one first, then the added one", len(P) == 2 and P[0]["main"] is True and P[1]["url"].endswith("video-three"))
INF.fetch_text = lambda url: "<html>no code here</html>"
INF.verify("yt2", W.code_of("yt2"), "", url="https://example.com/video-three")
P = INF.publications("yt2")
check("an added publication is checked on its own, the status stays approved", INF.is_approved("yt2") and P[1]["auto_check"]["found"] is False and P[0]["auto_check"]["found"] is True)
INF.fetch_text = _real
print("\n%d checks, %d failed" % (N[0], N[1]))
sys.exit(1 if N[1] else 0)
