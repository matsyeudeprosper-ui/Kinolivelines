import re
from datetime import datetime
LOG = r"C:\Projects\KinoliveLines\live\owl_manual.log"
ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
arm_re = re.compile(r"KINO: (peak|dip) [\d.]+ official")
kino_re = re.compile(r"KINO ENTRY: (BUY|SELL).*risk \$([\d.]+)")
elog_re = re.compile(r"ENTRY logged: (BUY|SELL) [\d.]+ @ [\d.]+ ticket (\d+)")
exit_re = re.compile(r"EXIT logged: ticket (\d+) (\S+) profit (-?[\d.]+)")
events = []
for line in open(LOG, encoding="utf-8", errors="replace"):
    m = ts_re.match(line)
    if not m:
        continue
    t = datetime.fromisoformat(m.group(1))
    if arm_re.search(line):
        events.append((t, "arm",
                       1 if arm_re.search(line).group(1) == "peak" else -1,
                       None))
    elif kino_re.search(line):
        g = kino_re.search(line)
        events.append((t, "kino", 1 if g.group(1) == "BUY" else -1,
                       float(g.group(2))))
    elif elog_re.search(line):
        g = elog_re.search(line)
        events.append((t, "elog", 1 if g.group(1) == "BUY" else -1,
                       int(g.group(2))))
    elif exit_re.search(line):
        g = exit_re.search(line)
        events.append((t, "exit", int(g.group(1)),
                       (g.group(2), float(g.group(3)))))
entries = []
last = None
for t, k, a, b in events:
    if k == "kino":
        last = (t, a, b)
    elif (k == "elog" and last and (t - last[0]).total_seconds() <= 30
          and a == last[1]):
        entries.append((t, a, b, last[2]))
        last = None
tickets = {tk for _, _, tk, _ in entries}
exits = {}
for t, k, a, b in events:
    if k == "exit" and a in tickets and a not in exits:
        exits[a] = (t, b[0], b[1])
arms = [(t, d) for t, k, d, _ in events if k == "arm"]
closed = sorted((exits[tk][0], d, exits[tk][2])
                for t, d, tk, _ in entries if tk in exits)
groups = {}
for t, d, tk, risk in sorted(entries):
    if tk not in exits:
        continue
    prior = [c for c in closed if c[0] < t]
    my = [a for a in arms if a[1] == d and a[0] < t]
    if not prior:
        cls = "first"
    elif d != prior[-1][1]:
        cls = "flip"
    elif my and my[-1][0] < prior[-1][0]:
        cls = "old-struct"
    else:
        cls = "fresh"
    groups.setdefault(cls, []).append(risk)
print(f"{'class':12}{'n':>4}{'avg risk $':>11}{'median':>8}{'max':>7}")
for cls, rs in sorted(groups.items()):
    rs2 = sorted(rs)
    med = rs2[len(rs2) // 2]
    print(f"{cls:12}{len(rs):4d}{sum(rs)/len(rs):11.2f}{med:8.2f}"
          f"{max(rs):7.2f}")
