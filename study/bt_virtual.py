"""User 2026-09-10: after a real LOSS, go virtual (paper trades
only); resume real trading after a virtual trade WINS (that win is
not banked).  The signal stream is unchanged, so this is a
relabeling of the same 622-trade sequence.  Also: does a loss even
predict the next result? (streak autocorrelation check).
Variants: resume after 1 or 2 virtual wins; also the mirror
(pause after WIN) as a sanity control."""
import numpy as np

rows = np.load("whip_rows.npy", allow_pickle=True)
pnl = [float(r["pnl"]) for r in rows]
half = len(pnl) // 2


def stats(xs):
    if not xs:
        return "n 0"
    w = sum(1 for x in xs if x > 0)
    cum = pk = mdd = 0.0
    for x in xs:
        cum += x
        pk = max(pk, cum)
        mdd = max(mdd, pk - cum)
    return (f"n {len(xs):3d} wr {w/len(xs):.0%} "
            f"net {sum(xs):+8.2f} maxDD {mdd:6.2f}")


def relabel(seq, pause_on_loss=True, wins_to_resume=1):
    real, virtual_wins, live = [], 0, True
    for x in seq:
        if live:
            real.append(x)
            if (x < 0) == pause_on_loss:
                live = False
                virtual_wins = 0
        else:
            if (x > 0) == pause_on_loss:
                virtual_wins += 1
                if virtual_wins >= wins_to_resume:
                    live = True
            else:
                virtual_wins = 0
    return real


print("baseline        :", stats(pnl))
print("pause-loss v1   :", stats(relabel(pnl, True, 1)))
print("pause-loss v2   :", stats(relabel(pnl, True, 2)))
print("mirror pause-win:", stats(relabel(pnl, False, 1)))
print("-- halves, pause-loss v1 --")
print("h1 baseline     :", stats(pnl[:half]))
print("h1 filtered     :", stats(relabel(pnl[:half], True, 1)))
print("h2 baseline     :", stats(pnl[half:]))
print("h2 filtered     :", stats(relabel(pnl[half:], True, 1)))
print("-- does the last result predict the next? --")
aw = [b for a, b in zip(pnl, pnl[1:]) if a > 0]
al = [b for a, b in zip(pnl, pnl[1:]) if a < 0]
print(f"after a WIN : next wr {sum(1 for x in aw if x>0)/len(aw):.0%}"
      f" avg {sum(aw)/len(aw):+.3f} (n {len(aw)})")
print(f"after a LOSS: next wr {sum(1 for x in al if x>0)/len(al):.0%}"
      f" avg {sum(al)/len(al):+.3f} (n {len(al)})")
