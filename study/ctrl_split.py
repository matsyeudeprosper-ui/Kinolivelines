"""ctrl_split.py <SYM> <robot> [seeds=20] [parts=4] - the random-entry control of random_control_market.py run as
<parts> processes side by side (each its share of the seeds), then merged by merge_random_control.py.

2026-10-16: on a tick pack one seed replays every broker tick of 60 days (~14 min on Gold's 13 M ticks, ~1 h on
Nasdaq's 56 M), so 40 seeds in one process took 9 h and hit the runner's 4 h limit. Tick arrays are memory-mapped
(tick_pack.real_ticks), so 4 processes cost ~1.5 GB together on the 6-core VPS. 20 seeds keep the fixed rule
readable (beats 19 of 20 = the 95th percentile).
"""
import sys, os, glob, subprocess, time
HERE = os.path.dirname(os.path.abspath(__file__))
sym, rid = sys.argv[1].upper(), sys.argv[2]
seeds = int(sys.argv[3]) if len(sys.argv) > 3 else 20
parts = int(sys.argv[4]) if len(sys.argv) > 4 else 4
for f in glob.glob(os.path.join(HERE, "random_control_%s_%s_part*.json" % (rid, sym))):
    os.remove(f)                                              # never merge stale parts
share = [seeds // parts + (1 if i < seeds % parts else 0) for i in range(parts)]
procs, start, t0 = [], 0, time.time()
for n in share:
    if n:
        procs.append(subprocess.Popen([sys.executable, "-u", os.path.join(HERE, "random_control_market.py"), sym, rid, str(n), str(start)],
                                      cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, creationflags=0x08000000))
        start += n
print("%s %s: %d seeds in %d processes" % (rid, sym, seeds, len(procs)), flush=True)
codes = [p.wait() for p in procs]
print("parts done in %.0f s, exit codes %s" % (time.time() - t0, codes), flush=True)
r = subprocess.run([sys.executable, os.path.join(HERE, "merge_random_control.py"), sym, rid], cwd=HERE, capture_output=True, text=True)
print(r.stdout[-600:], r.stderr[-300:], flush=True)
for f in glob.glob(os.path.join(HERE, "random_control_%s_%s_part*.json" % (rid, sym))):
    os.remove(f)
sys.exit(0 if r.returncode == 0 and all(c == 0 for c in codes) else 1)
