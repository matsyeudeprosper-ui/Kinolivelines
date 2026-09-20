"""Controls for "one trade after each loss".

selector_test found: 80 trades, 67.5% win, +0.141 R/trade, 6/6 anchors,
and both halves agreeing (+0.087 / +0.204). That is the first idea this
week to pass the halves. It is also an idea FOUND in this data (test D of
trend_decay_test), so the bar has to be higher, not lower.

  1. SHUFFLE     the null is "wins and losses are independent". Shuffle
                 the outcome sequence, re-apply the selector, 4000 times.
                 If after-a-loss is nothing special, the real value sits
                 in the middle of that cloud.
  2. COMPLEMENT  after a WIN should then be worse. If both are positive
                 the story is incoherent and it is selection, not signal.
  3. DIRECTION   buys vs sells.
  4. SPREAD      0 / 7 / 15 points.
  5. VOLUME      what it costs in dollars and in trades per day.

    python review/after_loss_controls.py
"""
import os
import random
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = ["after_loss_controls"]

import selector_test as S              # noqa: E402


def mean_R(tr):
    return sum(x["R"] for x in tr) / len(tr) if tr else 0.0


def after_win(tr):
    out, armed = [], False
    for x in tr:
        if armed:
            out.append(x)
            armed = False
        if x["win"]:
            armed = True
    return out


def main():
    sym, R = S.bars()
    print(f"  {sym}  {len(R)/1440:.1f} jours\n")
    base = S.replay(R, 7.0)
    sel = S.sel_after_loss(base)
    real = mean_R(sel)
    print(f"  baseline      {len(base):>3} trades  {mean_R(base):+.3f} R/trade")
    print(f"  after a LOSS  {len(sel):>3} trades  {real:+.3f} R/trade  "
          f"{100*sum(1 for x in sel if x['win'])/len(sel):.1f}% win")

    # 1. shuffle the outcome sequence
    print("\n  1. SHUFFLE (4000 re-orderings of the same outcomes)")
    pool = [{"R": x["R"], "win": x["win"]} for x in base]
    random.seed(11)
    sims = []
    for _ in range(4000):
        random.shuffle(pool)
        s = S.sel_after_loss(pool)
        if s:
            sims.append(mean_R(s))
    mu, sd = st.mean(sims), st.pstdev(sims)
    above = sum(1 for x in sims if x >= real)
    print(f"     shuffled mean {mu:+.3f}, sd {sd:.3f}")
    print(f"     shuffles >= real: {above}/{len(sims)}  ->  p = {above/len(sims):.4f}")
    print(f"     real is {(real-mu)/max(sd,1e-9):+.1f} sd from chance")

    # 2. the complement
    aw = after_win(base)
    print(f"\n  2. COMPLEMENT")
    print(f"     after a WIN   {len(aw):>3} trades  {mean_R(aw):+.3f} R/trade  "
          f"{100*sum(1 for x in aw if x['win'])/len(aw):.1f}% win")
    print(f"     coherent story? "
          f"{'yes - loss good, win bad' if mean_R(aw) < 0 < real else 'NO - both same sign'}")

    # 3/4/5
    print(f"\n  3-4. DIRECTION and SPREAD")
    for sp in (0.0, 7.0, 15.0):
        b2 = S.replay(R, sp)
        s2 = S.sel_after_loss(b2)
        print(f"     spread {sp:>4.0f}: after-loss {mean_R(s2):+.3f} ({len(s2)})"
              f"   all {mean_R(b2):+.3f} ({len(b2)})")
    print(f"\n  5. WHAT IT COSTS")
    d = len(R) / 1440
    print(f"     all signals   {len(base)/d:.2f} trades/day  "
          f"${sum(x['usd'] for x in base):+.2f}")
    print(f"     after a loss  {len(sel)/d:.2f} trades/day  "
          f"${sum(x['usd'] for x in sel):+.2f}")
    need = int((1.96 * st.pstdev([x['R'] for x in sel]) / 0.05) ** 2)
    print(f"     trades needed to resolve 0.05 R/trade: ~{need}"
          f"  = ~{need/(len(sel)/d)/30:.0f} months at this rate")


if __name__ == "__main__":
    main()
