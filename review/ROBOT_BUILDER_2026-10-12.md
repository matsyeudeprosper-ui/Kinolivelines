# The robot builder (owner request, 2026-10-12)

## The owner's definition
A **robot** = the **eyes** (the nest's market-structure reading: swings, BOS, CHoCH, the pullback chart -
shared by every robot, never swapped) + **4 parts**: entry, exit, catch-up after a loss (recovery), money.
A robot can inherit from another (parent) and replace any part, or borrow parts from several robots.
A **plug** = robot x money version x market x account. The owner wants to plug / unplug / replace a robot
on any market of his choice.

## What exists now (built this session)
- `live/robots/robots.json` - the parts catalogue (entry: owl_bos; exit: target N x risk, choch;
  recovery: current, all_bos; money = the packages of owl_packages.json) and the composed robots
  (`owl` = today's robot; `owl-choch` = the owner's first robot).
- Labo > Robots: definition, the composed robots with their parts, "Créer un robot" (parent + parts + name,
  POST `<tok>/robot_create`, Strategie members + admin, max 12 per member), the plug board (read-only:
  today every account = the Owl on BTCUSD with its money version), then the money versions / twins.
- `study/robot_runner.py` - tests queued robots on the proof page's harness ($200 base, tick engine, live
  gate order, adaptive cap, sticky pullback structure, trend filter, 0.35 $/lot) next to the parent; the
  app starts it in the background when a robot is created (lock file, one run at a time).
- `study/robot_choch_exit.py` - the owner's robot, part by part (results below).

## Not built yet (next steps, need the owner)
1. The live bot cannot run a different exit: `structure_bos_bot.py` has the fixed target. A CHoCH exit
   needs the bot to watch the main structure while a trade is open and close at the confirming candle.
2. Plugs are read-only: today owl_packages.json `accounts` maps an account to a money version only. A plug
   list (account -> robot, money, symbol) + the bot reading it is the step after 1.
3. Other markets with real orders: the bot trades BTCUSD only (the scanner trades 13 markets virtually).
4. A new robot's twin (live, no money) - the lab's twin runner does not know exit parts yet.

## Results - the owner's robot (exit only at a CHoCH; unlimited BOS during catch-up)
(filled in below once study/robot_choch_exit.py finishes)

$200 base money, 42 days (2026-08-28 -> 2026-10-09), tick engine, 0.35 $/lot cost. The `today` arm reproduces
lab/proof_current.json exactly (+57.39, 82 trades, dip 28.15) - the bench is the proof page's harness.

| arm | net | dip (cc) | trades | won | PF | 1st half | 2nd half | median hold |
|---|---|---|---|---|---|---|---|---|
| today (the Owl) | +57.39 | 28.15 | 82 | 67 % | 1.49 | +15.32 | +42.02 | 10.5 min |
| exit at CHoCH only | -0.99 | 39.09 | 62 | 26 % | 0.99 | -23.74 | +22.77 | 93 min |
| unlimited catch-up only | +49.25 | 19.98 | 97 | 64 % | 1.31 | +17.03 | +32.16 | 10.5 min |
| owner's robot (both) | -3.49 | 42.80 | 70 | 24 % | 0.97 | -28.45 | +24.96 | 98 min |
| owner's robot, no stop at all | -60.68 | 60.70 | 30 | 20 % | 0.38 | -60.70 | 0.00 | 124 min (hit the -60 kill line) |

Reading: the CHoCH exit is the part that costs (break-even instead of +57; half its exits are at the CHoCH,
the rest at the safety stop). The unlimited catch-up alone keeps most of the money (+49 vs +57) with a
SMALLER dip (20 vs 28) - better first half, worse second half: a lead, not a verdict (one 42-day window).
Without the safety stop the robot reaches the -60 kill line in the first half. Nothing deployed.
