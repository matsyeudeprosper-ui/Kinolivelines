# CANDIDATE: TP $1 / wide hindsight-calibrated SL, no daily protection — 2026-08-14

*Not a closed/killed spec — flagged as a candidate with known problems, for
the record. User asked to test this exact shape; result saved before
iterating on smaller SL sizes.*

## Idea

Same entry as the live bot (A0 — every reversal brick, `study/renko_clean.py`
signal definition). Single position per signal (no recovery basket, no cap).
**TP = $1.00.** **SL = the worst adverse move ever observed anywhere in the
4.6-year backtest, plus a 25% buffer.** No daily loss limit.

Code: `study/tp1_wide_sl.py`.

## Result

| | |
|---|---|
| SL used | $602.02 (worst-ever adverse move $481.61 + 25% buffer) |
| TP | $1.00 |
| Trades | 864 |
| Wins | 863 (99.9%) |
| Losses | **1** (0.1%) |
| Ended (from $1,000) | $1,260.98 (+26.1%) |
| Worst drawdown | $602.02 (47.7% from peak) |
| Expectancy/trade | +$0.302 |
| Breakeven win rate needed (given this TP:SL ratio) | 99.8% |

## Why this is NOT a validated result — two real problems

1. **Lookahead bias in the SL itself.** The stop size was set using the worst
   adverse move seen *anywhere across the whole 4.6-year test*, including
   years after most of the trades in the test already happened. A real
   trader cannot know in advance "the worst it will ever get" — the SL had
   to be guessed, and this backtest cheated by looking at the future to pick
   a number that (barely) worked. A genuinely new worst case, bigger than
   anything in this sample, is always possible.

2. **One loss in 864 trades is not a safe sample.** The win rate (99.9%)
   sits right at the breakeven line (99.8% needed) — razor-thin margin. The
   entire result rests on a catastrophic loss happening exactly once instead
   of twice. This is a "picking up pennies in front of a steamroller" shape:
   many tiny wins, one loss that erases most of them.

**Verdict: candidate, not adopted.** Interesting shape, real flaw. Superseded
by the SL-sweep test that follows (smaller, non-hindsight-calibrated SL
sizes), see below / next entry in this file.
