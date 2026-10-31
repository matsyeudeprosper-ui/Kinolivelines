"""proof_nightly.py - keeps the Tests page proof card up to date by itself (2026-10-31, owner: "yes do").

Each night: replay yesterday (UTC) of the reference account (u477508138, the bot's own demo - it keeps trading while the
real accounts are paused) with the real bot code (run_sim.py), then publish the last DAYS nightly runs together as the
proof card (publish_proof.py botsim). Days already simulated are not re-run.

    python -X utf8 study/botsim/proof_nightly.py            # started by task OwlTestProof via study/when_free.py
    python -X utf8 study/botsim/proof_nightly.py --publish  # republish only
Needs the broker bars + forward ticks of that day (OwlProofNightly / OwlForwardTicks run earlier in the night).
"""
import datetime as dt
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ACCT = "u477508138"
TAG = "proofref"
DAYS = 7


def run_dir(day):
    return os.path.join(HERE, "runs", "%s_%s" % (TAG, day))


def simulate(day):
    log = os.path.join(run_dir(day), "bos_bot_%s.log" % ACCT)
    if os.path.exists(os.path.join(run_dir(day), "DONE")):
        return log
    nxt = (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()
    rc = subprocess.call([sys.executable, "-X", "utf8", os.path.join(HERE, "run_sim.py"), "--acct", ACCT,     # 6 h past
                          "--start", day + "T00:00:01", "--end", nxt + "T06:00:00", "--tag", TAG], cwd=ROOT)  # midnight: late trades finish
    if rc != 0 or not os.path.exists(log):
        raise SystemExit("run_sim failed for %s (rc %s)" % (day, rc))
    open(os.path.join(run_dir(day), "DONE"), "w").close()
    return log


def publish():
    today = dt.datetime.utcnow().date()
    days = [(today - dt.timedelta(days=k)).isoformat() for k in range(DAYS, 0, -1)]
    done = [d for d in days if os.path.exists(os.path.join(run_dir(d), "DONE"))]
    if not done:
        raise SystemExit("no nightly run yet")
    nxt = lambda d: (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
    parts = "+".join("%s|%sT00:00:00|%sT00:00:00" % (os.path.join(run_dir(d), "bos_bot_%s.log" % ACCT), d, nxt(d)) for d in done)
    subprocess.check_call([sys.executable, "-X", "utf8", os.path.join(HERE, "publish_proof.py"), "botsim", parts, ACCT], cwd=ROOT)


if __name__ == "__main__":
    if "--publish" not in sys.argv:
        simulate((dt.datetime.utcnow().date() - dt.timedelta(days=1)).isoformat())
    publish()
    for old in glob.glob(os.path.join(HERE, "runs", TAG + "_*")):     # keep a month of nightly runs
        if os.path.basename(old)[len(TAG) + 1:] < (dt.datetime.utcnow().date() - dt.timedelta(days=30)).isoformat():
            import shutil
            shutil.rmtree(old, ignore_errors=True)
