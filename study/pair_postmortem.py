"""Why are BOTH accounts losing, when one is supposed to offset the other?

The design intent was that a demo loss is a live win. Tonight both sides lost. This pulls
every deal from both terminals, pairs them by open time, and shows what actually happened
at each exit - in particular WHY each side closed, which is the part that explains it.
"""
import datetime as d
import MetaTrader5 as mt5

REASON = {0: "client", 1: "mobile", 2: "web", 3: "EA closed it",
          4: "STOP LOSS", 5: "TAKE PROFIT", 6: "stop out", 7: "rollover"}
SINCE = d.datetime(2026, 8, 1, 23, 0)


def pull(path, label):
    mt5.initialize(path=path)
    acct = mt5.account_info()
    deals = mt5.history_deals_get(SINCE, d.datetime.now() + d.timedelta(hours=3)) or []
    mt5.shutdown()
    out, opens = [], {}
    for x in deals:
        if x.entry == 0:
            opens[x.position_id] = x
        else:
            o = opens.get(x.position_id)
            out.append({
                "acct": label,
                "opened": d.datetime.fromtimestamp(o.time) if o else None,
                "closed": d.datetime.fromtimestamp(x.time),
                "side": "BUY" if (o and o.type == 0) else "SELL",
                "entry": o.price if o else float("nan"),
                "exit": x.price,
                "pnl": x.profit + x.commission + x.swap,
                "why": REASON.get(x.reason, str(x.reason)),
            })
    return acct, out


_, demo = pull(r"C:\Program Files\MetaTrader 5\terminal64.exe", "demo")
_, live = pull(r"C:\Projects\MT5-KinoliveTrader\terminal64.exe", "live")

print("EVERY TRADE SINCE %s\n" % SINCE)
print("%-5s %-8s %-8s %-5s %9s %9s %7s   %s"
      % ("acct", "open", "close", "side", "entry", "exit", "P&L", "why it closed"))
print("-" * 88)
for r in sorted(demo + live, key=lambda z: z["closed"]):
    print("%-5s %-8s %-8s %-5s %9.2f %9.2f %+7.2f   %s"
          % (r["acct"], r["opened"].strftime("%H:%M:%S") if r["opened"] else "?",
             r["closed"].strftime("%H:%M:%S"), r["side"], r["entry"], r["exit"],
             r["pnl"], r["why"]))

print("\nTOTALS")
for lab, rows in (("demo", demo), ("live", live)):
    print("  %-5s %2d trades   net $%+.2f" % (lab, len(rows), sum(r["pnl"] for r in rows)))
print("  %-5s          net $%+.2f" % ("PAIR", sum(r["pnl"] for r in demo + live)))

print("\nHOW THE LIVE SIDE ACTUALLY EXITED  (this is the whole answer)")
tot = {}
for r in live:
    a, b = tot.get(r["why"], [0, 0.0])
    tot[r["why"]] = [a + 1, b + r["pnl"]]
for why, (n, p) in sorted(tot.items(), key=lambda z: -z[1][0]):
    print("  %-14s %2d trades   $%+7.2f   avg $%+.2f" % (why, n, p, p / n))

print("""
READ THE 'EA closed it' ROW. Those are mirrors shut by MirrorClose the moment the demo
position closed, instead of being allowed to run to their own target. The hedge only pays
if the mirror reaches its $1 target - closed early at market it collects roughly nothing,
because buying back costs the spread it just earned.""")
