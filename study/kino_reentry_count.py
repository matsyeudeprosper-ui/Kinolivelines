"""Count KINO immediate re-entries (old structure) vs fresh-cycle entries.

Classification per KINO entry:
  flip        - direction opposite to the previous KINO trade
  old-struct  - same direction AND its pending (peak/dip official) was armed
                BEFORE the previous KINO exit  -> the user's rule would block
  fresh       - same direction, pending armed after the previous exit
  first       - no previous KINO trade to compare
"""
import re
from datetime import datetime

LOG = r"C:\Projects\KinoliveLines\live\owl_manual.log"

ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
arm_re = re.compile(r"KINO: (peak|dip) [\d.]+ official")
kino_re = re.compile(r"KINO ENTRY: (BUY|SELL)")
elog_re = re.compile(r"ENTRY logged: (BUY|SELL) [\d.]+ @ [\d.]+ ticket (\d+)")
exit_re = re.compile(r"EXIT logged: ticket (\d+) (\S+) profit (-?[\d.]+)")

events = []
for line in open(LOG, encoding="utf-8", errors="replace"):
    m = ts_re.match(line)
    if not m:
        continue
    t = datetime.fromisoformat(m.group(1))
    if arm_re.search(line):
        d = 1 if arm_re.search(line).group(1) == "peak" else -1
        events.append((t, "arm", d, line.strip()))
    elif kino_re.search(line):
        d = 1 if kino_re.search(line).group(1) == "BUY" else -1
        events.append((t, "kino", d, line.strip()))
    elif elog_re.search(line):
        g = elog_re.search(line)
        d = 1 if g.group(1) == "BUY" else -1
        events.append((t, "elog", d, int(g.group(2))))
    elif exit_re.search(line):
        g = exit_re.search(line)
        events.append((t, "exit", int(g.group(1)),
                       (g.group(2), float(g.group(3)))))

# KINO tickets: an "ENTRY logged" within 30s after a "KINO ENTRY" line
kino_entries = []   # (time, dir, ticket)
last_kino = None
for t, kind, a, b in events:
    if kind == "kino":
        last_kino = (t, a)
    elif kind == "elog" and last_kino and (t - last_kino[0]).total_seconds() <= 30:
        if a == last_kino[1]:
            kino_entries.append((t, a, b))
        last_kino = None

kino_tickets = {tk for _, _, tk in kino_entries}
exits = {}          # ticket -> (time, reason, profit)
for t, kind, a, b in events:
    if kind == "exit" and a in kino_tickets and a not in exits:
        exits[a] = (t, b[0], b[1])

arms = [(t, d) for t, kind, d, _ in events if kind == "arm"]

groups = {}
rows = []
prev = None         # (exit_time, dir, profit) of previous KINO trade
done = sorted((exits[tk][0], t, d, tk) for t, d, tk in kino_entries
              if tk in exits)
# iterate entries in entry-time order, tracking the latest prior exit
entries_sorted = sorted(kino_entries)
closed = sorted((exits[tk][0], d, exits[tk][2]) for t, d, tk in kino_entries
                if tk in exits)
for t, d, tk in entries_sorted:
    if tk not in exits:
        continue
    _, reason, profit = exits[tk]
    prior = [c for c in closed if c[0] < t]
    my_arms = [a for a in arms if a[1] == d and a[0] < t]
    if not prior:
        cls = "first"
        gap = None
    else:
        pex_t, pex_d, pex_p = prior[-1]
        gap = (t - pex_t).total_seconds() / 60
        if d != pex_d:
            cls = "flip"
        elif my_arms and my_arms[-1][0] < pex_t:
            cls = "old-struct" + ("(after win)" if pex_p > 0 else "(after loss)")
        else:
            cls = "fresh"
    g = groups.setdefault(cls, [])
    g.append(profit)
    rows.append((t, "BUY" if d == 1 else "SELL", tk, cls,
                 round(gap, 1) if gap is not None else "-", reason, profit))

print(f"KINO trades matched: {len(rows)}  (entries {len(kino_entries)}, "
      f"with exit {len(exits)})")
print()
print(f"{'class':22} {'n':>3} {'total':>8} {'avg':>7} {'win%':>5}")
for cls, ps in sorted(groups.items()):
    wins = sum(1 for p in ps if p > 0)
    print(f"{cls:22} {len(ps):3d} {sum(ps):8.2f} {sum(ps)/len(ps):7.2f} "
          f"{100*wins/len(ps):5.0f}")
allp = [p for ps in groups.values() for p in ps]
print(f"{'ALL':22} {len(allp):3d} {sum(allp):8.2f} {sum(allp)/len(allp):7.2f}")
print()
print("last 20 trades:")
for r in rows[-20:]:
    print(f"  {r[0]:%m-%d %H:%M} {r[1]:4} {r[3]:22} gap {r[4]!s:>6}min "
          f"{r[5]:12} {r[6]:+7.2f}")
